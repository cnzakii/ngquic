cdef class Connection(BaseConnection):
    """A QUIC connection whose application uses streams and DATAGRAMs directly."""

    # Fields and C methods are declared in connection.pxd.

    # ---- streams

    def open_stream(self, *, bint unidirectional=False):
        """Open a stream; before the handshake only after 0-RTT resumption.

        Returns:
            The stream ID.

        Raises:
            StreamLimitError: If the peer allows no more streams of this type
                yet; ``StreamsAvailable`` reports new credit.
            ConnectionStateError: If the connection is closing or closed.
        """
        cdef int64_t stream_id
        cdef int rv
        cdef _ScheduledStream stream

        self._require_open()
        stream = _ScheduledStream.__new__(_ScheduledStream)
        rv = self._open_stream(&stream_id, unidirectional)
        if rv == ng.NGTCP2_ERR_STREAM_ID_BLOCKED:
            raise StreamLimitError("the peer allows no more streams of this type yet")
        if rv != 0:
            raise _native_error(rv)
        stream.stream_id = stream_id
        # Owned before ngtcp2 holds its pointer, so a MemoryError cannot dangle it.
        self._streams[stream_id] = stream
        ng.ngtcp2_conn_set_stream_user_data(self._conn, stream_id, <void *>stream)
        return stream_id

    def send_stream_data(self, stream_id, data, *, bint end_stream=False):
        """Queue data on a stream.

        ``bytes`` are held without copying until the peer acknowledges them;
        other buffers are copied once.

        Args:
            stream_id: The stream.
            data: Bytes-like data, possibly empty.
            end_stream: Whether this finishes the sending direction.

        Returns:
            ``False`` once the stream holds more than
            ``stream_write_buffer_high`` bytes; wait for ``StreamWritable``
            before queuing more.

        Raises:
            StreamStateError: If the stream does not exist or its sending
                direction finished.
            ConnectionStateError: If the connection is closing or closed.
        """
        cdef _ScheduledStream stream = self._sendable(_stream_id(stream_id))
        cdef bint writable = self._enqueue(stream, data, end_stream)

        self._activate(stream)
        return writable

    def end_stream(self, stream_id):
        """Finish the sending direction of a stream after its queued data."""
        cdef _ScheduledStream stream = self._sendable(_stream_id(stream_id))

        stream.fin_queued = True
        self._activate(stream)

    def reset_stream(self, stream_id, error_code):
        """Abandon sending on a stream with RESET_STREAM; unsent data is dropped."""
        cdef int64_t sid = _stream_id(stream_id)
        cdef uint64_t code = _uint(error_code, "error_code", _MAX_VARINT)
        cdef _ScheduledStream stream = <_ScheduledStream>self._existing(sid)
        cdef int rv

        rv = ng.ngtcp2_conn_shutdown_stream_write(self._conn, 0, sid, code)
        if rv != 0:
            raise StreamStateError("this stream has no sending direction")
        stream.abandon()
        self._deactivate(stream)

    def stop_sending(self, stream_id, error_code):
        """Ask the peer to stop sending on a stream with STOP_SENDING."""
        cdef int64_t sid = _stream_id(stream_id)
        cdef uint64_t code = _uint(error_code, "error_code", _MAX_VARINT)
        cdef int rv

        self._existing(sid)
        rv = ng.ngtcp2_conn_shutdown_stream_read(self._conn, 0, sid, code)
        if rv != 0:
            raise StreamStateError("this stream has no receiving direction")

    def consume_received_data(self, stream_id, amount):
        """Return flow-control credit for data the application processed.

        Only needed when ``TransportConfig.auto_flow_control`` is ``False``.
        """
        self._consume_received(stream_id, amount)

    def queued_size(self, stream_id=None):
        """Return bytes held for sending: unsent plus unacknowledged."""
        return self._held(stream_id)

    def send_capacity(self, stream_id=None):
        """Return bytes the peer's flow control allows on a stream or the connection."""
        if self._conn == NULL:
            return 0
        if stream_id is None:
            return ng.ngtcp2_conn_get_max_data_left2(self._conn)
        return ng.ngtcp2_conn_get_max_stream_data_left2(
            self._conn, _stream_id(stream_id),
        )

    def stream_loss_count(self, stream_id):
        """Return how many packets carrying this stream were declared lost."""
        if self._conn == NULL:
            return 0
        return ng.ngtcp2_conn_get_stream_loss_count2(self._conn, _stream_id(stream_id))

    # ---- datagrams

    def send_datagram(self, data):
        """Queue an unreliable DATAGRAM frame.

        Returns:
            An ID reported by ``DatagramAcknowledged`` or ``DatagramLost``.

        Raises:
            DatagramError: If the peer does not accept DATAGRAM frames or
                ``data`` exceeds ``max_datagram_size``.
            ConnectionStateError: If the connection is closing or closed.
        """
        cdef bytes payload = _owned_bytes(data)
        cdef object limit

        self._require_open()
        limit = self.max_datagram_size
        if limit is None:
            raise DatagramError("the peer does not accept DATAGRAM frames")
        if len(payload) > limit:
            raise DatagramError(f"DATAGRAM payload exceeds {limit} bytes")
        return self._queue_datagram(payload)

    @property
    def max_datagram_size(self):
        """Largest DATAGRAM payload sendable now; ``None`` if the peer accepts none."""
        cdef int64_t limit = self._datagram_limit()

        return None if limit < 0 else limit

    # ---- state

    @property
    def bidi_streams_available(self):
        """Bidirectional streams that can be opened now."""
        if self._conn == NULL:
            return 0
        return ng.ngtcp2_conn_get_streams_bidi_left2(self._conn)

    @property
    def uni_streams_available(self):
        """Unidirectional streams that can be opened now."""
        if self._conn == NULL:
            return 0
        return ng.ngtcp2_conn_get_streams_uni_left2(self._conn)

    # ---- stream protocol hooks

    cdef int _stream_opened(self, int64_t stream_id) except -1:
        cdef _ScheduledStream stream = _ScheduledStream.__new__(_ScheduledStream)

        stream.stream_id = stream_id
        self._streams[stream_id] = stream
        ng.ngtcp2_conn_set_stream_user_data(self._conn, stream_id, <void *>stream)
        return 0

    cdef int _stream_data(
        self, uint32_t flags, int64_t stream_id, const uint8_t *data, size_t length,
    ) except -1:
        cdef StreamDataReceived event = StreamDataReceived.__new__(StreamDataReceived)

        event.stream_id = stream_id
        event.data = PyBytes_FromStringAndSize(<const char *>data, length)
        event.end_stream = flags & ng.NGTCP2_STREAM_DATA_FLAG_FIN
        event.early = flags & ng.NGTCP2_STREAM_DATA_FLAG_0RTT
        self._events.append(event)
        if self._auto_flow and length:
            self._consume(stream_id, length)
        return 0

    cdef int _stream_acked(
        self, int64_t stream_id, uint64_t length, void *stream_user_data,
    ) except -1:
        if stream_user_data != NULL:
            self._acknowledge(<_Stream>stream_user_data, length)
        return 0

    cdef int _stream_closed(
        self, uint32_t flags, int64_t stream_id, uint64_t rx_error_code,
        uint64_t tx_error_code, void *stream_user_data,
    ) except -1:
        if stream_user_data != NULL:
            self._deactivate(<_ScheduledStream>stream_user_data)
        self._streams.pop(stream_id, None)
        return self._emit_stream_closed(
            stream_id,
            rx_error_code
            if flags & ng.NGTCP2_STREAM_CLOSE2_FLAG_RX_APP_ERROR_CODE_SET
            else None,
            tx_error_code
            if flags & ng.NGTCP2_STREAM_CLOSE2_FLAG_TX_APP_ERROR_CODE_SET
            else None,
        )

    cdef int _stop_sending_received(
        self, int64_t stream_id, uint64_t error_code, void *stream_user_data,
    ) except -1:
        if stream_user_data != NULL:
            self._deactivate(<_ScheduledStream>stream_user_data)
        return BaseConnection._stop_sending_received(
            self, stream_id, error_code, stream_user_data,
        )

    cdef int _stream_unblocked(
        self, int64_t stream_id, void *stream_user_data,
    ) except -1:
        cdef _ScheduledStream stream

        if stream_user_data != NULL:
            stream = <_ScheduledStream>stream_user_data
            if stream.blocked:
                stream.blocked = False
                self._activate(stream)
        return 0

    cdef int _datagram_received(
        self, uint32_t flags, const uint8_t *data, size_t length,
    ) except -1:
        cdef DatagramReceived event = DatagramReceived.__new__(DatagramReceived)

        event.data = PyBytes_FromStringAndSize(<const char *>data, length)
        event.early = flags & ng.NGTCP2_DATAGRAM_FLAG_0RTT
        self._events.append(event)
        return 0

    cdef ng.ngtcp2_ssize _write_stream(
        self, ng.ngtcp2_path *path, ng.ngtcp2_pkt_info *info, uint8_t *dest,
        size_t destlen, ng.ngtcp2_tstamp ts,
    ) except? -1:
        """Write one packet of stream data in round-robin order.

        Returns ``NGTCP2_ERR_WRITE_MORE`` while the packet has room.
        """
        cdef ng.ngtcp2_vec vecs[_MAX_VECS]
        cdef ng.ngtcp2_ssize written, framed = -1
        cdef _ScheduledStream stream = self._active_head
        cdef uint32_t flags = (
            ng.NGTCP2_WRITE_STREAM_FLAG_PADDING if self._padding else 0
        )
        cdef size_t count = 0
        cdef bint covers_end
        cdef int64_t stream_id = -1
        cdef uint64_t left = ng.ngtcp2_conn_get_max_data_left2(self._conn)
        # Offering data once at zero credit lets ngtcp2 send DATA_BLOCKED
        # (RFC 9000 4.1); more offers would only spin.
        cdef bint probe = left == 0 and not self._data_blocked

        if left:
            self._data_blocked = False
        # What fits whole goes even below write_stream_data_threshold, as
        # ngtcp2 writes it; a bare FIN fits in none.
        if stream is not None and (
            self._send_credit() or stream.end - stream.sent <= left or probe
        ):
            self._data_blocked |= probe
            count = stream.vectors(vecs, &covers_end)
            flags |= ng.NGTCP2_WRITE_STREAM_FLAG_MORE
            if stream.fin_queued and covers_end:
                flags |= ng.NGTCP2_WRITE_STREAM_FLAG_FIN
            stream_id = stream.stream_id
        written = ng.ngtcp2_conn_writev_stream(
            self._conn, path, info, dest, destlen, &framed, flags, stream_id, vecs,
            count, ts,
        )
        if written == ng.NGTCP2_ERR_WRITE_MORE:
            self._written(stream, framed, flags)
        elif written == ng.NGTCP2_ERR_STREAM_DATA_BLOCKED:
            stream.blocked = True
            self._deactivate(stream)
            return ng.NGTCP2_ERR_WRITE_MORE
        elif (
            written == ng.NGTCP2_ERR_STREAM_SHUT_WR
            or written == ng.NGTCP2_ERR_STREAM_NOT_FOUND
        ):
            stream.abandon()
            self._deactivate(stream)
            return ng.NGTCP2_ERR_WRITE_MORE
        elif written >= 0 and stream_id >= 0 and framed >= 0:
            self._written(stream, framed, flags)
        return written

    cdef void _stop_sending_streams(self):
        """Empty the active list, unlinking its streams so none keeps another alive."""
        cdef _ScheduledStream stream = self._active_head
        cdef _ScheduledStream following

        while stream is not None:
            following = stream.next
            stream.active = False
            stream.prev = stream.next = None
            stream = following
        self._active_head = self._active_tail = None

    # ---- internals

    cdef _ScheduledStream _sendable(self, int64_t stream_id):
        cdef _Stream stream

        self._require_open()
        # Direction is a property of the ID, known even after the stream closed.
        if (stream_id & 0x2) and not ng.ngtcp2_conn_is_local_stream2(
            self._conn, stream_id,
        ):
            raise StreamStateError(f"stream {stream_id} is receive-only")
        stream = self._existing(stream_id)
        if stream.fin_queued or stream.send_closed:
            raise StreamStateError(f"stream {stream_id} finished sending")
        return <_ScheduledStream>stream

    cdef void _activate(self, _ScheduledStream stream):
        if stream.active or stream.blocked or not stream.pending():
            return
        stream.active = True
        stream.next = None
        stream.prev = self._active_tail
        if self._active_tail is None:
            self._active_head = stream
        else:
            self._active_tail.next = stream
        self._active_tail = stream

    cdef void _deactivate(self, _ScheduledStream stream):
        if not stream.active:
            return
        stream.active = False
        if stream.prev is None:
            self._active_head = stream.next
        else:
            stream.prev.next = stream.next
        if stream.next is None:
            self._active_tail = stream.prev
        else:
            stream.next.prev = stream.prev
        stream.prev = None
        stream.next = None

    cdef void _written(
        self, _ScheduledStream stream, ng.ngtcp2_ssize length, uint32_t flags,
    ):
        """Account for stream data ngtcp2 framed, then rotate for fairness."""
        if length > 0:
            stream.advance(<size_t>length)
        if (
            flags & ng.NGTCP2_WRITE_STREAM_FLAG_FIN
            and stream.cursor == len(stream.chunks)
        ):
            stream.fin_sent = True
        self._deactivate(stream)
        self._activate(stream)
