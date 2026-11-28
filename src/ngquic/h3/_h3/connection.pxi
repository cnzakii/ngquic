cdef class _Body(_Stream):
    """A message body nghttp3 sends; its bytes stay until acknowledged."""

    # Fields are declared in connection.pxd.


cdef class H3Connection(BaseConnection):
    # Fields and C methods are declared in connection.pxd.

    def __cinit__(self):
        self._h3 = NULL
        self._receiving = {}
        self._field_section_size = {}
        self._finished = set()
        self._readable = set()
        self._credit_blocked = set()
        self._origins = []

    def __dealloc__(self):
        if self._h3 != NULL:
            nh.nghttp3_conn_del(self._h3)
            self._h3 = NULL

    # ---- requests and responses

    def send_request(self, headers, *, bint end_stream=False):
        cdef list fields = _header_list(headers, _REQUEST)
        cdef _Body stream = _Body.__new__(_Body)
        cdef int64_t stream_id
        cdef int rv

        self._require_open()
        if not self.is_client:
            raise ConnectionStateError("only clients send requests")
        if any(field[0] == b":protocol" for field in fields) and not (
            self.remote_settings is not None
            and self.remote_settings.enable_connect_protocol
        ):
            raise ConnectionStateError(
                "extended CONNECT needs the server's SETTINGS_ENABLE_CONNECT_PROTOCOL"
            )
        if self._goaway_received:
            # Before the QUIC stream exists, or it would be opened only to be reset.
            raise ConnectionStateError("the server is shutting down")
        if self._h3 == NULL:
            self._start_early()
        rv = self._open_stream(&stream_id, False)
        if rv == ng.NGTCP2_ERR_STREAM_ID_BLOCKED:
            raise StreamLimitError("the server allows no more requests yet")
        if rv != 0:
            raise _native_error(rv)
        stream.stream_id = stream_id
        stream.fin_queued = stream.fin_sent = end_stream
        # Owned before nghttp3 holds its pointer, so a MemoryError cannot dangle it.
        self._streams[stream_id] = stream
        try:
            self._readable.add(stream_id)
        except MemoryError:
            del self._streams[stream_id]
            raise
        rv = _submit(self._h3, stream_id, fields, 0, stream, end_stream)
        if rv != 0:
            # Only NOMEM is left, which nghttp3 deems fatal, and it may already
            # hold the stream's pointer: the owner stays until the connection,
            # closed here, releases both.
            self.close(H3ErrorCode.H3_INTERNAL_ERROR)
            raise _h3_error(rv)
        return stream_id

    @property
    def bidi_streams_available(self):
        if self._conn == NULL or not self.is_client or self._goaway_received:
            return 0
        return self._bidi_streams_left()

    def send_response(self, stream_id, headers, *, bint end_stream=False):
        cdef int64_t sid = _request_stream_id(stream_id)
        cdef list fields = _header_list(headers, _RESPONSE)
        cdef _Body stream = _Body.__new__(_Body)
        cdef int rv

        self._require_server("only servers send responses")
        if sid in self._streams:
            raise StreamStateError(f"stream {sid} cannot take a response now")
        stream.stream_id = sid
        stream.fin_queued = stream.fin_sent = end_stream
        # Owned before nghttp3 holds its pointer, so a failure cannot dangle it.
        self._streams[sid] = stream
        rv = nh.nghttp3_conn_set_stream_user_data(self._h3, sid, <void *>stream)
        if rv == 0:
            rv = _submit(self._h3, sid, fields, 1, stream, end_stream)
        if rv != 0:
            del self._streams[sid]
            nh.nghttp3_conn_set_stream_user_data(self._h3, sid, NULL)
        if rv == nh.NGHTTP3_ERR_STREAM_NOT_FOUND or rv == nh.NGHTTP3_ERR_INVALID_STATE:
            raise StreamStateError(f"stream {sid} cannot take a response now")
        if rv != 0:
            raise _h3_error(rv)

    def send_informational_response(self, stream_id, headers):
        cdef int64_t sid = _request_stream_id(stream_id)
        cdef list fields = _header_list(headers, _INFORMATIONAL)
        cdef int rv

        self._require_server("only servers send responses")
        # The final response has taken the stream; nghttp3 does not check.
        if sid in self._streams:
            raise StreamStateError(f"stream {sid} already has its final response")
        rv = _submit(self._h3, sid, fields, 2, None, False)
        if rv == nh.NGHTTP3_ERR_STREAM_NOT_FOUND or rv == nh.NGHTTP3_ERR_INVALID_STATE:
            raise StreamStateError(f"stream {sid} cannot take a response now")
        if rv != 0:
            raise _h3_error(rv)

    def send_data(self, stream_id, data, *, bint end_stream=False):
        cdef _Body stream = self._body(_stream_id(stream_id))
        cdef bint writable = self._enqueue(stream, data, end_stream)

        nh.nghttp3_conn_resume_stream(self._h3, stream.stream_id)
        return writable

    def end_stream(self, stream_id):
        cdef _Body stream = self._body(_stream_id(stream_id))

        stream.fin_queued = True
        nh.nghttp3_conn_resume_stream(self._h3, stream.stream_id)

    def send_trailers(self, stream_id, headers):
        # Headers first: iterating them runs caller code that may end the stream.
        cdef list fields = _header_list(headers, _TRAILERS)
        cdef _Body stream = self._body(_stream_id(stream_id))
        cdef int rv

        rv = _submit(self._h3, stream.stream_id, fields, 3, None, False)
        if rv != 0:
            raise _h3_error(rv)
        stream.fin_queued = stream.trailers = True
        nh.nghttp3_conn_resume_stream(self._h3, stream.stream_id)

    def reset_stream(self, stream_id, error_code=H3ErrorCode.H3_REQUEST_CANCELLED):
        cdef int64_t sid = _request_stream_id(stream_id)
        cdef uint64_t code = _uint(error_code, "error_code", _MAX_VARINT)
        cdef _Stream stream

        self._require_open()
        self._shutdown_stream(sid, code, True, True)
        if self._h3 != NULL:
            nh.nghttp3_conn_shutdown_stream_read(self._h3, sid)
        self._readable.discard(sid)
        stream = self._streams.get(sid)
        if stream is not None:
            stream.abandon()

    def stop_sending(self, stream_id, error_code=H3ErrorCode.H3_NO_ERROR):
        cdef int64_t sid = _request_stream_id(stream_id)
        cdef uint64_t code = _uint(error_code, "error_code", _MAX_VARINT)

        self._require_open()
        self._shutdown_stream(sid, code, True, False)
        if self._h3 != NULL:
            nh.nghttp3_conn_shutdown_stream_read(self._h3, sid)
        self._readable.discard(sid)

    def consume_received_data(self, stream_id, amount):
        self._consume_received(stream_id, amount)

    def queued_body_size(self, stream_id=None):
        return self._held(stream_id)

    # ---- shutdown

    def send_shutdown_notice(self):
        self._require_ready()
        if self._goaway_sent:
            raise ConnectionStateError("GOAWAY was already sent")
        _check(nh.nghttp3_conn_submit_shutdown_notice(self._h3))

    def send_goaway(self):
        self._require_ready()
        _check(nh.nghttp3_conn_shutdown(self._h3))
        self._goaway_sent = True

    @property
    def is_drained(self):
        return bool(
            self._h3 != NULL
            and not self.is_client
            and nh.nghttp3_conn_is_drained2(self._h3)
        )

    # ---- priority (RFC 9218)

    def send_priority_update(self, stream_id, field_value):
        cdef int64_t sid = _stream_id(stream_id)
        cdef bytes value = _owned_bytes(field_value)
        cdef int rv

        self._require_ready()
        if not self.is_client:
            raise ConnectionStateError("only clients send PRIORITY_UPDATE")
        rv = nh.nghttp3_conn_set_client_stream_priority(
            self._h3, sid, <const uint8_t *>PyBytes_AS_STRING(value), len(value),
        )
        if (
            rv == nh.NGHTTP3_ERR_STREAM_NOT_FOUND
            or rv == nh.NGHTTP3_ERR_INVALID_ARGUMENT
        ):
            raise StreamStateError(f"stream {sid} is not an open request")
        _check(rv)

    def set_stream_priority(self, stream_id, priority):
        cdef int64_t sid = _stream_id(stream_id)
        cdef nh.nghttp3_pri pri
        cdef int rv

        self._require_server("only servers schedule responses")
        if not isinstance(priority, Priority):
            raise TypeError("priority must be a Priority")
        pri.urgency = <uint32_t>_uint(priority.urgency, "urgency", 7)
        pri.inc = priority.incremental
        rv = nh.nghttp3_conn_set_server_stream_priority(self._h3, sid, &pri)
        if (
            rv == nh.NGHTTP3_ERR_STREAM_NOT_FOUND
            or rv == nh.NGHTTP3_ERR_INVALID_ARGUMENT
        ):
            raise StreamStateError(f"stream {sid} is not an open request")
        _check(rv)

    def get_stream_priority(self, stream_id):
        cdef nh.nghttp3_pri pri

        self._require_server("only servers track request priorities")
        if nh.nghttp3_conn_get_stream_priority2(
            self._h3, &pri, _stream_id(stream_id),
        ) != 0:
            return None
        return Priority(pri.urgency, bool(pri.inc))

    # ---- HTTP/3 datagrams (RFC 9297)

    def send_datagram(self, stream_id, data):
        cdef int64_t sid = _request_stream_id(stream_id)
        cdef int64_t limit
        cdef object stream
        cdef Py_buffer view
        cdef bytes datagram
        cdef uint8_t *out

        self._require_ready()
        limit = self._h3_datagram_limit(sid)
        if limit < 0:
            raise DatagramError("HTTP/3 datagrams are not negotiated")
        stream = self._streams.get(sid)
        if (
            stream is None
            or (<_Stream>stream).fin_queued
            or (<_Stream>stream).send_closed
        ):
            raise StreamStateError(f"stream {sid} has no open message")
        PyObject_GetBuffer(data, &view, PyBUF_CONTIG_RO)
        try:
            if view.len > limit:
                raise DatagramError(f"HTTP/3 datagram payload exceeds {limit} bytes")
            datagram = PyBytes_FromStringAndSize(
                NULL, <Py_ssize_t>nh.nghttp3_put_uvarintlen(sid >> 2) + view.len,
            )
            out = nh.nghttp3_put_uvarint(
                <uint8_t *>PyBytes_AS_STRING(datagram), <uint64_t>(sid >> 2),
            )
            memcpy(out, view.buf, view.len)
        finally:
            PyBuffer_Release(&view)
        return self._queue_datagram(datagram)

    def max_datagram_size(self, stream_id):
        cdef int64_t limit = self._h3_datagram_limit(_request_stream_id(stream_id))

        return None if limit < 0 else limit

    # ---- stream protocol hooks

    cdef int _set_application(self, object application, object transport) except -1:
        if not isinstance(application, H3Config):
            raise TypeError("h3 must be an H3Config")
        if application.h3_datagram and (
            transport is None or not transport.max_datagram_frame_size
        ):
            # SETTINGS_H3_DATAGRAM promises QUIC DATAGRAM frames are received.
            raise ValueError(
                "h3_datagram needs TransportConfig.max_datagram_frame_size"
            )
        if transport is not None and transport.max_streams_uni < 3:
            # RFC 9114 6.2: the peer opens a control and two QPACK streams.
            raise ValueError("HTTP/3 needs TransportConfig.max_streams_uni >= 3")
        self._config = application

    cdef bint _server_opens_bidi(self):
        # RFC 9114 6.1: HTTP/3 servers open no bidirectional streams.
        return False

    cdef bytes _early_settings(self):
        # RFC 9114 7.2.4.2 and RFC 9297 2.1.1: 0-RTT relies on the SETTINGS.
        cdef object config = self._config

        return repr((
            config.max_field_section_size,
            config.qpack_max_dtable_capacity,
            config.qpack_blocked_streams,
            config.enable_connect_protocol,
            config.h3_datagram,
        )).encode()

    cdef int _application_keys(self) except -1:
        """Start HTTP/3 once 1-RTT keys exist; again after 0-RTT is rejected."""
        if self._state >= _CLOSING:
            return 0
        # Also when 0-RTT already started HTTP/3: the ticket chose the early
        # protocol, which the handshake has now settled.
        if self.alpn_protocol != "h3":
            # TLS no_application_protocol: this connection cannot carry HTTP/3.
            return self._close_with_alert(120)
        if self._h3 != NULL:
            return 0
        if self._uni_streams_left() < 3:
            # RFC 9114 6.2: the peer must allow the control and QPACK streams.
            return self._close_with(H3ErrorCode.H3_GENERAL_PROTOCOL_ERROR)
        self._start()
        return 0

    cdef int _remote_streams_bidi(self, uint64_t max_streams) except -1:
        self._max_requests = max_streams
        if self._h3 != NULL:
            nh.nghttp3_conn_set_max_client_streams_bidi(self._h3, max_streams)
        return 0

    cdef int _stream_opened(self, int64_t stream_id) except -1:
        if not stream_id & 0x2:
            self._readable.add(stream_id)
        return 0

    cdef int _stream_data(
        self, uint32_t flags, int64_t stream_id, const uint8_t *data, size_t length,
    ) except -1:
        cdef nh.nghttp3_ssize consumed = nh.nghttp3_conn_read_stream2(
            self._h3, stream_id, data, length,
            flags & ng.NGTCP2_STREAM_DATA_FLAG_FIN,
            self._last_timestamp(),
        )

        if consumed < 0:
            return self._h3_failed(<int>consumed)
        # Framing and QPACK bytes; body bytes return credit in recv_data.
        if consumed:
            self._consume(stream_id, consumed)
        return 0

    cdef int _stream_acked(
        self, int64_t stream_id, uint64_t length, void *stream_user_data,
    ) except -1:
        cdef int rv

        if self._h3 == NULL:
            return 0
        rv = nh.nghttp3_conn_add_ack_offset(self._h3, stream_id, length)
        return self._h3_failed(rv) if rv != 0 else 0

    cdef int _stream_closed(
        self, uint32_t flags, int64_t stream_id, uint64_t rx_error_code,
        uint64_t tx_error_code, void *stream_user_data,
    ) except -1:
        cdef uint32_t h3_flags = 0
        cdef int rv

        if self._h3 == NULL:
            return 0
        if flags & ng.NGTCP2_STREAM_CLOSE2_FLAG_RX_APP_ERROR_CODE_SET:
            h3_flags |= nh.NGHTTP3_STREAM_CLOSE_FLAG_RX_APP_ERROR_CODE_SET
        if flags & ng.NGTCP2_STREAM_CLOSE2_FLAG_TX_APP_ERROR_CODE_SET:
            h3_flags |= nh.NGHTTP3_STREAM_CLOSE_FLAG_TX_APP_ERROR_CODE_SET
        rv = nh.nghttp3_conn_close_stream2(
            self._h3, h3_flags, stream_id, rx_error_code, tx_error_code,
        )
        if rv != 0 and rv != nh.NGHTTP3_ERR_STREAM_NOT_FOUND:
            return self._h3_failed(rv)
        return 0

    cdef int _stream_reset(
        self, int64_t stream_id, uint64_t final_size, uint64_t error_code,
    ) except -1:
        cdef int rv

        if self._h3 == NULL:
            return 0
        rv = nh.nghttp3_conn_shutdown_stream_read(self._h3, stream_id)
        if rv != 0:
            return self._h3_failed(rv)
        self._readable.discard(stream_id)
        if not stream_id & 0x2:
            BaseConnection._stream_reset(self, stream_id, final_size, error_code)
        return 0

    cdef int _stop_sending_received(
        self, int64_t stream_id, uint64_t error_code, void *stream_user_data,
    ) except -1:
        cdef _Stream stream

        # ngtcp2 resets the sending side itself, and nghttp3 learns it from
        # STREAM_SHUT_WR; the response may still arrive. The queued body is
        # dropped.
        stream = self._streams.get(stream_id)
        if stream is not None:
            stream.abandon()
        return BaseConnection._stop_sending_received(self, stream_id, error_code, NULL)

    cdef int _stream_unblocked(
        self, int64_t stream_id, void *stream_user_data,
    ) except -1:
        cdef int rv

        if self._h3 == NULL:
            return 0
        rv = nh.nghttp3_conn_unblock_stream(self._h3, stream_id)
        return self._h3_failed(rv) if rv != 0 else 0

    cdef int _early_data_rejected(self) except -1:
        # Requests sent in 0-RTT are gone; HTTP/3 restarts with the handshake.
        # nghttp3 goes first: it holds borrowed pointers to the streams.
        self._drop_h3()
        self._credit_blocked.clear()
        self._receiving.clear()
        self._field_section_size.clear()
        self._finished.clear()
        self._readable.clear()
        return BaseConnection._early_data_rejected(self)

    cdef int _datagram_received(
        self, uint32_t flags, const uint8_t *data, size_t length,
    ) except -1:
        cdef uint64_t quarter
        cdef size_t prefix
        cdef int64_t stream_id
        cdef DatagramReceived event

        # Only a peer that saw SETTINGS_H3_DATAGRAM may send one.
        if self._h3 == NULL or not self._config.h3_datagram:
            return 0
        prefix = nh.nghttp3_get_uvarintlen(data) if length else 1
        if prefix > length:
            return self._close_with(H3ErrorCode.H3_DATAGRAM_ERROR)
        nh.nghttp3_get_uvarint(&quarter, data)
        if quarter > _MAX_QUARTER_STREAM_ID:
            return self._close_with(H3ErrorCode.H3_DATAGRAM_ERROR)
        stream_id = <int64_t>(quarter * 4)
        if stream_id not in self._readable:
            if not self.is_client and quarter >= self._max_requests:
                # A stream the client can never open (RFC 9297 2.1).
                return self._close_with(H3ErrorCode.H3_ID_ERROR)
            # Not opened yet, or no longer read: drop it silently.
            return 0
        event = DatagramReceived.__new__(DatagramReceived)
        event.stream_id = stream_id
        event.data = PyBytes_FromStringAndSize(
            <const char *>data + prefix, length - prefix,
        )
        self._events.append(event)
        return 0

    cdef ng.ngtcp2_ssize _write_stream(
        self, ng.ngtcp2_path *path, ng.ngtcp2_pkt_info *info, uint8_t *dest,
        size_t destlen, ng.ngtcp2_tstamp ts,
    ) except? -1:
        cdef nh.nghttp3_vec vecs[_MAX_VECS]
        cdef nh.nghttp3_ssize count = 0
        cdef ng.ngtcp2_ssize written, framed = -1
        cdef int64_t stream_id = -1
        cdef int fin = 0, rv
        cdef uint32_t flags = ng.NGTCP2_WRITE_STREAM_FLAG_MORE
        cdef uint64_t left = self._data_left()
        cdef size_t pending = 0
        cdef nh.nghttp3_ssize index
        # Offering data once at zero credit lets ngtcp2 send DATA_BLOCKED
        # (RFC 9000 4.1); more offers would only spin.
        cdef bint probe = left == 0 and not self._data_blocked

        if left:
            self._data_blocked = False
        if self._h3 != NULL:
            if left > self._parked_left and self._credit_blocked:
                for blocked in self._credit_blocked:
                    rv = nh.nghttp3_conn_unblock_stream(self._h3, blocked)
                    if rv != 0:
                        return self._h3_failed(rv)
                self._credit_blocked.clear()
            count = nh.nghttp3_conn_writev_stream(
                self._h3, &stream_id, &fin, vecs, _MAX_VECS,
            )
            if count < 0:
                return self._h3_failed(<int>count)
            for index in range(count):
                pending += vecs[index].len
            # Offer what fits, or credit past write_stream_data_threshold;
            # park the rest, as ngtcp2's examples wait for connection credit.
            # A bare FIN needs none, and the peer may hold credit until the
            # message ends.
            if pending > left and not self._send_credit():
                if not probe:
                    nh.nghttp3_conn_block_stream(self._h3, stream_id)
                    self._credit_blocked.add(stream_id)
                    self._parked_left = left
                    return ng.NGTCP2_ERR_WRITE_MORE
                self._data_blocked = True
        if fin:
            flags |= ng.NGTCP2_WRITE_STREAM_FLAG_FIN
        written = self._writev_stream(
            path, info, dest, destlen, &framed, flags, stream_id,
            <ng.ngtcp2_vec *>vecs, count, ts,
        )
        if written == ng.NGTCP2_ERR_STREAM_DATA_BLOCKED:
            nh.nghttp3_conn_block_stream(self._h3, stream_id)
            return ng.NGTCP2_ERR_WRITE_MORE
        if written == ng.NGTCP2_ERR_STREAM_SHUT_WR:
            nh.nghttp3_conn_shutdown_stream_write(self._h3, stream_id)
            return ng.NGTCP2_ERR_WRITE_MORE
        if framed >= 0:
            rv = nh.nghttp3_conn_add_write_offset(self._h3, stream_id, framed)
            if rv != 0:
                return self._h3_failed(rv)
        return written

    cdef void _finish(self):
        # nghttp3 points at none of these.
        self._receiving.clear()
        self._field_section_size.clear()
        self._finished.clear()
        self._readable.clear()
        self._credit_blocked.clear()
        BaseConnection._finish(self)

    cdef void _release(self):
        # Also runs from __dealloc__, after Python fields are cleared.
        BaseConnection._release(self)
        self._drop_h3()

    # ---- internals

    cdef int _start(self) except -1:
        """Create the nghttp3 connection and open its three unidirectional streams."""
        cdef nh.nghttp3_callbacks callbacks
        cdef nh.nghttp3_settings settings
        cdef nh.nghttp3_vec origins
        cdef object config = self._config
        cdef uint64_t bidi, uni
        cdef int64_t control, encoder, decoder
        cdef int rv

        memset(&callbacks, 0, sizeof(callbacks))
        callbacks.acked_stream_data = _h3_acked_stream_data
        callbacks.stream_close2 = _h3_stream_close
        callbacks.recv_data = _h3_recv_data
        callbacks.deferred_consume = _h3_deferred_consume
        callbacks.begin_headers = _h3_begin_headers
        callbacks.recv_header = _h3_recv_header
        callbacks.end_headers = _h3_end_headers
        callbacks.begin_trailers = _h3_begin_headers
        callbacks.recv_trailer = _h3_recv_header
        callbacks.end_trailers = _h3_end_trailers
        callbacks.end_stream = _h3_end_stream
        callbacks.stop_sending = _h3_stop_sending
        callbacks.reset_stream = _h3_reset_stream
        callbacks.shutdown = _h3_shutdown
        callbacks.recv_settings2 = _h3_recv_settings
        callbacks.recv_origin = _h3_recv_origin
        callbacks.end_origin = _h3_end_origin
        callbacks.rand = _h3_rand

        nh.nghttp3_settings_default(&settings)
        if config.max_field_section_size is not None:
            settings.max_field_section_size = _uint(
                config.max_field_section_size, "max_field_section_size", _MAX_VARINT,
            )
            self._field_section_limit = settings.max_field_section_size
        settings.qpack_max_dtable_capacity = <size_t>_uint(
            config.qpack_max_dtable_capacity, "qpack_max_dtable_capacity", 1 << 30,
        )
        settings.qpack_encoder_max_dtable_capacity = <size_t>_uint(
            config.qpack_encoder_max_dtable_capacity,
            "qpack_encoder_max_dtable_capacity",
            1 << 30,
        )
        settings.qpack_blocked_streams = <size_t>_uint(
            config.qpack_blocked_streams, "qpack_blocked_streams", 1 << 16,
        )
        settings.enable_connect_protocol = config.enable_connect_protocol
        settings.h3_datagram = config.h3_datagram
        settings.glitch_ratelim_burst = _uint(
            config.glitch_rate_limit[0], "glitch_rate_limit", <uint64_t>-1,
        )
        settings.glitch_ratelim_rate = _uint(
            config.glitch_rate_limit[1], "glitch_rate_limit", <uint64_t>-1,
        )
        if config.origins is not None and not self.is_client:
            self._origin_payload = _origin_payload(config.origins)
            origins.base = <uint8_t *>PyBytes_AS_STRING(self._origin_payload)
            origins.len = len(self._origin_payload)
            settings.origin_list = &origins

        if self.is_client:
            rv = nh.nghttp3_conn_client_new(
                &self._h3, &callbacks, &settings, &_MEM, <void *>self,
            )
        else:
            rv = nh.nghttp3_conn_server_new(
                &self._h3, &callbacks, &settings, &_MEM, <void *>self,
            )
        if rv != 0:
            self._h3 = NULL
            raise _h3_error(rv)
        self._local_stream_limits(&bidi, &uni)
        if not self.is_client:
            self._max_requests = max(self._max_requests, bidi)
            nh.nghttp3_conn_set_max_client_streams_bidi(self._h3, self._max_requests)
        # QPACK caps its decoder stream buffer at 20 bytes per stream the peer
        # may open at once (the default assumes 100); keep that from wrapping.
        nh.nghttp3_conn_set_max_concurrent_streams(
            self._h3, <size_t>min(bidi + uni, SIZE_MAX // 20),
        )
        _check_native(self._open_stream(&control, True))
        _check_native(self._open_stream(&encoder, True))
        _check_native(self._open_stream(&decoder, True))
        _check(nh.nghttp3_conn_bind_control_stream(self._h3, control))
        _check(nh.nghttp3_conn_bind_qpack_streams(self._h3, encoder, decoder))

    cdef int _start_early(self) except -1:
        """Start HTTP/3 for 0-RTT requests from a resumed session."""
        if self._uni_streams_left() < 3:
            raise StreamLimitError("send requests after HandshakeCompleted")
        self._start()

    cdef void _drop_h3(self):
        if self._h3 != NULL:
            nh.nghttp3_conn_del(self._h3)
            self._h3 = NULL

    cdef int _h3_failed(self, int rv) except -1:
        """Map an nghttp3 failure: re-raise a callback error, else close."""
        if self._callback_error is not None:
            return ng.NGTCP2_ERR_CALLBACK_FAILURE
        if self._violation:
            rv = self._violation
        return self._close_with(nh.nghttp3_err_infer_quic_app_error_code(rv))

    cdef int64_t _h3_datagram_limit(self, int64_t stream_id):
        """Largest datagram payload for a stream, or -1 if not negotiated.

        RFC 9297 2.1.1: both sides must have sent SETTINGS_H3_DATAGRAM=1.
        """
        cdef int64_t limit

        if (
            self._h3 == NULL
            or not self._config.h3_datagram
            or self.remote_settings is None
            or not self.remote_settings.h3_datagram
        ):
            return -1
        limit = self._datagram_limit()
        if limit < 0:
            return -1
        limit -= <int64_t>nh.nghttp3_put_uvarintlen(<uint64_t>(stream_id >> 2))
        return limit if limit >= 0 else -1

    cdef int _require_ready(self) except -1:
        self._require_open()
        if self._h3 == NULL:
            raise ConnectionStateError("HTTP/3 starts when the handshake completes")

    cdef int _require_server(self, str message) except -1:
        self._require_ready()
        if self.is_client:
            raise ConnectionStateError(message)

    cdef _Body _body(self, int64_t stream_id):
        cdef object stream

        self._require_open()
        stream = self._streams.get(stream_id)
        if (
            stream is None
            or (<_Stream>stream).fin_queued
            or (<_Stream>stream).send_closed
        ):
            raise StreamStateError(f"stream {stream_id} has no open message body")
        return <_Body>stream

    cdef int _emit_end(self, int64_t stream_id) except -1:
        """Mark the end of a message: on its last DATA event, or a new empty one."""
        cdef DataReceived event

        if stream_id in self._finished:
            self._finished.discard(stream_id)
            return 0
        if self._events:
            last = self._events[-1]
            if (
                type(last) is DataReceived
                and (<DataReceived>last).stream_id == stream_id
            ):
                (<DataReceived>last).end_stream = True
                return 0
        event = DataReceived.__new__(DataReceived)
        event.stream_id = stream_id
        event.data = b""
        event.end_stream = True
        self._events.append(event)


cdef int64_t _request_stream_id(object value) except -1:
    cdef int64_t stream_id = _stream_id(value)

    if stream_id & 0x3:
        raise ValueError(f"stream {stream_id} is not a request stream")
    return stream_id


# The header sections _header_list checks, in _submit's order.
cdef enum:
    _REQUEST, _RESPONSE, _INFORMATIONAL, _TRAILERS

# Pseudo-header flags, as nghttp3 tracks them on receipt.
cdef enum:
    _METHOD = 1
    _SCHEME = 2
    _AUTHORITY = 4
    _PATH = 8
    _PROTOCOL = 16
    _STATUS = 32

_PSEUDO = {
    b":method": _METHOD, b":scheme": _SCHEME, b":authority": _AUTHORITY,
    b":path": _PATH, b":protocol": _PROTOCOL, b":status": _STATUS,
}
# Connection-specific fields, which HTTP/3 forbids (RFC 9114, section 4.2).
_CONNECTION_FIELDS = frozenset((
    b"connection", b"keep-alive", b"proxy-connection", b"transfer-encoding",
    b"upgrade",
))


cdef list _header_list(object headers, int section):
    """Snapshot and validate headers as ``(name, value, never_indexed)``.

    Rejects the structure a peer's nghttp3 finds malformed, which closes the
    whole connection (H3_MESSAGE_ERROR), so a mistake fails here instead;
    the byte syntax of values beyond nghttp3_check_header_value is left to
    the peer.
    """
    cdef list result = []
    cdef int seen = 0, flag
    cdef int allowed = (
        0 if section == _TRAILERS
        else _METHOD | _SCHEME | _AUTHORITY | _PATH | _PROTOCOL
        if section == _REQUEST else _STATUS
    )
    cdef bint regular = False
    cdef object name, value
    cdef object method = None, path = None, authority = None, host = None
    cdef object status = None, scheme = None

    for item in headers:
        try:
            name, value = item
        except (TypeError, ValueError):
            raise TypeError(
                "each header must be a (name, value) pair of bytes"
            ) from None
        if not PyBytes_Check(name) or not PyBytes_Check(value):
            raise TypeError("each header must be a (name, value) pair of bytes")
        # A subclass, such as a bytes enum, is copied: its methods may differ.
        if not PyBytes_CheckExact(name):
            name = PyBytes_FromStringAndSize(
                PyBytes_AS_STRING(name), PyBytes_GET_SIZE(name),
            )
        if not PyBytes_CheckExact(value):
            value = PyBytes_FromStringAndSize(
                PyBytes_AS_STRING(value), PyBytes_GET_SIZE(value),
            )
        # Converted, not refused: RFC 9114 section 4.2, as h2 does.
        if not name.islower():
            name = name.lower()
        if not nh.nghttp3_check_header_name(
            <const uint8_t *>PyBytes_AS_STRING(name), PyBytes_GET_SIZE(name),
        ):
            raise ValueError(f"invalid header name {name!r}")
        if not nh.nghttp3_check_header_value(
            <const uint8_t *>PyBytes_AS_STRING(value), PyBytes_GET_SIZE(value),
        ):
            raise ValueError(f"invalid value for header {name!r}")
        if PyBytes_AS_STRING(name)[0] == b":":
            flag = _PSEUDO.get(name, 0)
            if not flag & allowed:
                raise ValueError(f"this header section cannot carry {name!r}")
            if regular:
                raise ValueError(f"{name!r} must come before the regular fields")
            if seen & flag:
                raise ValueError(f"duplicate {name!r}")
            if not value:
                raise ValueError(f"a header section needs a non-empty {name.decode()}")
            seen |= flag
            if flag == _METHOD:
                method = value
            elif flag == _PATH:
                path = value
            elif flag == _AUTHORITY:
                authority = value
            elif flag == _SCHEME:
                scheme = value
            elif flag == _STATUS:
                status = value
        else:
            regular = True
            if name in _CONNECTION_FIELDS:
                raise ValueError(f"HTTP/3 forbids the connection-specific {name!r}")
            if name == b"te" and value.lower() != b"trailers":
                raise ValueError("te can only be b'trailers'")
            if name == b"host":
                if host is not None or not value:
                    raise ValueError("a request carries one non-empty host at most")
                host = value
        result.append((name, value, isinstance(item, NeverIndexedHeader)))

    if section == _REQUEST:
        # RFC 9114 section 4.3.1, and RFC 9220 for :protocol.
        if method is None:
            raise ValueError("a request needs :method")
        if authority is not None and host is not None and host != authority:
            raise ValueError("host must equal :authority")
        if method == b"CONNECT" and not seen & _PROTOCOL:
            if seen & (_SCHEME | _PATH):
                raise ValueError("CONNECT takes no :scheme or :path")
            if authority is None:
                raise ValueError("CONNECT needs :authority")
        elif seen & _PROTOCOL and method != b"CONNECT":
            raise ValueError(":protocol needs :method CONNECT")
        elif seen & _PROTOCOL and authority is None:
            raise ValueError("extended CONNECT needs :authority")
        elif scheme is None:
            raise ValueError("a request needs a non-empty :scheme")
        elif path is None:
            raise ValueError("a request needs a non-empty :path")
        elif authority is None and host is None:
            raise ValueError("a request needs :authority or host")
        elif (
            path[:1] != b"/"
            and scheme.lower() in (b"https", b"http")
            and not (method == b"OPTIONS" and path == b"*")
        ):
            raise ValueError(":path must start with / or be * for OPTIONS")
    elif section != _TRAILERS:
        # RFC 9114 section 4.3.2; RFC 9110 section 15 for 100 to 599.
        if status is None:
            raise ValueError("a response needs :status")
        if (
            len(status) != 3 or not status.isdigit()
            or status[:1] not in b"12345"
        ):
            raise ValueError(f"invalid :status {status!r}")
        if (section == _INFORMATIONAL) != (status[:1] == b"1") or status == b"101":
            raise ValueError(
                f":status {status!r} is not "
                + (
                    "an interim 1xx other than 101" if section == _INFORMATIONAL
                    else "a final status"
                )
            )
    return result


cdef int _submit(
    nh.nghttp3_conn *conn, int64_t stream_id, list fields, int kind,
    _Body stream, bint end_stream,
) except? -1:
    """Submit a header section; ``kind`` is request, response, 1xx or trailers.

    nghttp3 copies the fields, which ``fields`` keeps alive for the call.
    """
    cdef Py_ssize_t count = len(fields)
    cdef nh.nghttp3_nv *nva = <nh.nghttp3_nv *>malloc(
        (count if count else 1) * sizeof(nh.nghttp3_nv)
    )
    cdef const nh.nghttp3_data_reader *reader = NULL if end_stream else &_BODY_READER
    cdef Py_ssize_t index
    cdef bytes name, value

    if nva == NULL:
        return nh.NGHTTP3_ERR_NOMEM
    try:
        for index in range(count):
            name, value, never = fields[index]
            nva[index].name = <const uint8_t *>PyBytes_AS_STRING(name)
            nva[index].namelen = PyBytes_GET_SIZE(name)
            nva[index].value = <const uint8_t *>PyBytes_AS_STRING(value)
            nva[index].valuelen = PyBytes_GET_SIZE(value)
            nva[index].flags = (
                nh.NGHTTP3_NV_FLAG_NEVER_INDEX if never else nh.NGHTTP3_NV_FLAG_NONE
            )
        if kind == 0:
            return nh.nghttp3_conn_submit_request(
                conn, stream_id, nva, count, reader, <void *>stream,
            )
        if kind == 1:
            return nh.nghttp3_conn_submit_response(conn, stream_id, nva, count, reader)
        if kind == 2:
            return nh.nghttp3_conn_submit_info(conn, stream_id, nva, count)
        return nh.nghttp3_conn_submit_trailers(conn, stream_id, nva, count)
    finally:
        free(nva)


cdef bytes _origin_payload(object origins):
    """Serialize an ORIGIN frame payload: 2-byte length-prefixed origins."""
    cdef bytearray payload = bytearray()

    for origin in origins:
        if not isinstance(origin, bytes) or not 0 < len(origin) <= 0xFFFF:
            raise ValueError("origins must be non-empty bytes of at most 65535 bytes")
        payload += len(origin).to_bytes(2, "big")
        payload += origin
    return bytes(payload)


cdef int _check_native(int rv) except -1:
    if rv != 0:
        raise _native_error(rv)


cdef int _check(int rv) except -1:
    if rv != 0:
        raise _h3_error(rv)


cdef object _h3_error(int rv):
    if rv == nh.NGHTTP3_ERR_NOMEM:
        return MemoryError()
    return InternalError(nh.nghttp3_strerror(rv).decode("ascii", "replace"))
