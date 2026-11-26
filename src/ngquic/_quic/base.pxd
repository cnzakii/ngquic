# The connection driver and the stream protocol hooks. Implemented in base.pxi.


cdef class BaseConnection:
    cdef ng.ngtcp2_conn *_conn
    cdef ng.SSL *_ssl
    cdef ng.ngtcp2_crypto_conn_ref _conn_ref
    cdef Endpoint _endpoint
    cdef TLSContext _tls
    cdef readonly bint is_client
    cdef readonly object server_name
    cdef int _state
    cdef list _events
    cdef dict _streams
    cdef object _datagrams
    cdef uint64_t _next_datagram_id
    cdef Py_ssize_t _datagram_queue
    cdef object _callback_error
    cdef set _cid_keys
    cdef set _reset_keys
    cdef bint _auto_flow
    # Data was offered at zero connection credit, for DATA_BLOCKED.
    cdef bint _data_blocked
    # Pad packets to the segment size while a server builds a GSO train.
    cdef bint _padding
    cdef uint64_t _high
    cdef uint64_t _low
    cdef ng.ngtcp2_ccerr _ccerr
    cdef bytes _close_reason
    cdef bint _close_pending
    cdef bytes _close_packet
    cdef object _close_remote
    cdef object _close_local
    cdef size_t _close_received
    cdef size_t _close_next
    cdef size_t _close_bytes_received
    cdef size_t _close_bytes_sent
    cdef list _pending_out
    cdef uint64_t _deadline
    cdef bint _stateless_reset
    cdef object _qlog
    cdef _AddressCache _remote_cache
    cdef _AddressCache _local_cache
    cdef object _initial_local
    cdef object _initial_remote
    cdef object _probe_storage
    # Client version negotiation (RFC 9000 6.2, RFC 9368).
    cdef object _transport
    cdef list _offered_versions
    cdef uint32_t _original_version
    cdef bint _version_retried
    # Handshakes paused for the application (ClientHelloReceived,
    # PeerCertificateReceived).
    cdef int _tls_pause
    cdef tuple _client_alpn
    cdef TLSContext _selected_tls
    cdef bint _certificate_selected
    cdef int _peer_verdict
    # Set when a hook closed the connection; _ccerr holds the error.
    cdef object _failure_reason
    # PathDegrading: probe timeouts allowed, set on handshake confirmation
    # (0 while off), when the data in flight began waiting for
    # acknowledgment progress, and whether PathRecovered is due.
    cdef uint64_t _degrading_ptos
    cdef ng.ngtcp2_tstamp _waiting_since
    cdef bint _degraded
    # A callback failure while the endpoint delivered a datagram, raised by
    # the next events().
    cdef object _deferred_error

    # ---- construction
    @staticmethod
    cdef BaseConnection _client(
        type kind, Endpoint endpoint, object remote_addr, double now,
        TLSContext tls, object server_name, object transport,
        object session_ticket, object token, object local_addr, uint32_t version,
        object application,
    )
    cdef int _start_client(
        self, ng.ngtcp2_tstamp ts, uint32_t version, object token,
        object session_ticket,
    ) except -1
    cdef bint _renegotiate_version(self, ng.ngtcp2_tstamp ts) except -1

    @staticmethod
    cdef object _server(
        type kind, Incoming incoming, TLSContext tls, object transport,
        object application,
    )
    cdef object _configure(
        self, object transport, Endpoint endpoint, ng.ngtcp2_tstamp ts,
        ng.ngtcp2_settings *settings, ng.ngtcp2_transport_params *params,
        ng.ngtcp2_callbacks *callbacks, bint server,
    )
    cdef int _pmtud_probes(self, object probes, ng.ngtcp2_settings *settings) except -1
    cdef int _apply_runtime(self, object transport) except -1
    cdef int _attach_tls(self, TLSContext tls) except -1
    cdef int _resume(self, bytes ticket) except -1

    # ---- stream protocol hooks
    cdef int _set_application(self, object application, object transport) except -1
    cdef bint _server_opens_bidi(self)
    cdef bytes _early_settings(self)
    cdef int _application_keys(self) except -1
    cdef int _remote_streams_bidi(self, uint64_t max_streams) except -1
    cdef int _stream_opened(self, int64_t stream_id) except -1
    cdef int _stream_data(
        self, uint32_t flags, int64_t stream_id, const uint8_t *data, size_t length,
    ) except -1
    cdef int _stream_acked(
        self, int64_t stream_id, uint64_t length, void *stream_user_data,
    ) except -1
    cdef int _stream_closed(
        self, uint32_t flags, int64_t stream_id, uint64_t rx_error_code,
        uint64_t tx_error_code, void *stream_user_data,
    ) except -1
    cdef int _stream_reset(
        self, int64_t stream_id, uint64_t final_size, uint64_t error_code,
    ) except -1
    cdef int _stop_sending_received(
        self, int64_t stream_id, uint64_t error_code, void *stream_user_data,
    ) except -1
    cdef int _stream_unblocked(
        self, int64_t stream_id, void *stream_user_data,
    ) except -1
    cdef int _early_data_rejected(self) except -1
    cdef int _datagram_received(
        self, uint32_t flags, const uint8_t *data, size_t length,
    ) except -1
    cdef ng.ngtcp2_ssize _write_stream(
        self, ng.ngtcp2_path *path, ng.ngtcp2_pkt_info *info, uint8_t *dest,
        size_t destlen, ng.ngtcp2_tstamp ts,
    ) except? -1
    cdef void _stop_sending_streams(self)

    # ---- shared by the stream protocols
    cdef int _close_with(self, uint64_t error_code) except -1
    cdef void _consume(self, int64_t stream_id, uint64_t length)
    cdef int _acknowledge(self, _Stream stream, uint64_t length) except -1
    cdef uint64_t _queue_datagram(self, bytes payload) except? 0
    cdef bint _enqueue(self, _Stream stream, object data, bint end_stream) except -1
    cdef uint64_t _held(self, object stream_id) except? 0
    cdef int _consume_received(self, object stream_id, object amount) except -1
    cdef int _emit_stream_closed(
        self, int64_t stream_id, object rx_error_code, object tx_error_code,
    ) except -1

    # ---- ngtcp2 calls for stream protocols in other extension modules,
    # which cannot link ngtcp2 themselves
    cdef int _open_stream(self, int64_t *stream_id, bint unidirectional)
    cdef void _shutdown_stream(
        self, int64_t stream_id, uint64_t error_code, bint read, bint write,
    )
    cdef ng.ngtcp2_ssize _writev_stream(
        self, ng.ngtcp2_path *path, ng.ngtcp2_pkt_info *info, uint8_t *dest,
        size_t destlen, ng.ngtcp2_ssize *framed, uint32_t flags, int64_t stream_id,
        const ng.ngtcp2_vec *vecs, size_t count, ng.ngtcp2_tstamp ts,
    )
    cdef ng.ngtcp2_tstamp _clock(self, double now) except? 0
    cdef ng.ngtcp2_tstamp _last_timestamp(self)
    cdef uint64_t _send_credit(self)
    cdef uint64_t _data_left(self)
    cdef uint64_t _bidi_streams_left(self)
    cdef uint64_t _uni_streams_left(self)
    cdef void _local_stream_limits(self, uint64_t *bidi, uint64_t *uni)
    cdef int _close_with_alert(self, uint8_t alert) except -1

    # ---- internals
    cdef int _read(
        self, const uint8_t *packet, size_t length, ng.ngtcp2_path *path,
        uint8_t ecn, ng.ngtcp2_tstamp ts,
    ) except? -1
    cdef int _receive(
        self, const uint8_t *packet, size_t length, ng.ngtcp2_path *path,
        uint8_t ecn, ng.ngtcp2_tstamp ts,
    ) except -1
    cdef int _answer_while_closing(self, size_t length) except -1
    cdef int _handle_error(self, int rv, ng.ngtcp2_tstamp ts) except -1
    cdef int _start_closing(self, object reason) except -1
    cdef int _report_peer_close(self) except -1
    cdef int _terminated(
        self, object reason, object error_code, object frame_type, bytes phrase,
        bint by_peer,
    ) except -1
    cdef int _write_close(self, ng.ngtcp2_tstamp ts, list result) except -1
    cdef void _finish(self)
    cdef void _release(self)
    cdef void _stop_sending_all(self)
    cdef int64_t _datagram_limit(self)
    cdef int _drop_datagram(self) except -1
    cdef int _raise_callback_error(self) except -1
    cdef int _resume_handshake(self, double now) except -1
    cdef int _require_open(self) except -1
    cdef _Stream _existing(self, int64_t stream_id)
    cdef uint64_t _in_flight(self) noexcept
    cdef uint64_t _degrading_deadline(self) noexcept


cdef object _native_error(int rv)
cdef void *_raw_malloc(size_t size, void *user_data) noexcept nogil
cdef void _raw_free(void *ptr, void *user_data) noexcept nogil
cdef void *_raw_calloc(size_t nmemb, size_t size, void *user_data) noexcept nogil
cdef void *_raw_realloc(void *ptr, size_t size, void *user_data) noexcept nogil
cdef void _random_bytes(uint8_t *dest, size_t length) noexcept
