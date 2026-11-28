cdef class BaseConnection:
    # Fields and C methods are declared in base.pxd.

    def __cinit__(self):
        self._conn = NULL
        self._ssl = NULL
        self._events = []
        self._streams = {}
        self._datagrams = deque()
        self._cid_keys = set()
        self._reset_keys = set()
        self._pending_out = []
        self._remote_cache = _AddressCache()
        self._local_cache = _AddressCache()
        self._close_next = 1
        self._close_reason = b""
        self._deadline = _NO_EXPIRY
        self._client_alpn = ()
        self._peer_verdict = -1

    def __init__(self):
        raise TypeError("connections come from Endpoint.connect() or Incoming.accept()")

    def __dealloc__(self):
        self._release()

    # ---- construction

    @staticmethod
    cdef BaseConnection _client(
        type kind, Endpoint endpoint, object remote_addr, double now,
        TLSContext tls, object server_name, object transport,
        object session_ticket, object token, object local_addr, uint32_t version,
        object application,
    ):
        cdef BaseConnection self = <BaseConnection>kind.__new__(kind)

        if server_name is not None and not isinstance(server_name, str):
            raise TypeError("server_name must be a str")
        self._set_application(application, transport)
        self.is_client = True
        self._endpoint = endpoint
        self._tls = tls
        self.server_name = server_name
        self._transport = transport
        self._initial_remote = remote_addr
        self._initial_local = endpoint.local_addr if local_addr is None else local_addr
        self._original_version = version
        self._start_client(_timestamp(now), version, token, session_ticket)
        return self

    cdef int _start_client(
        self, ng.ngtcp2_tstamp ts, uint32_t version, object token,
        object session_ticket,
    ) except -1:
        """Create the native client connection and its first flight."""
        cdef Endpoint endpoint = self._endpoint
        cdef TLSContext tls = self._tls
        cdef ng.ngtcp2_cid dcid, scid
        cdef ng.ngtcp2_path path
        cdef ng.ngtcp2_sockaddr_union remote, local
        cdef ng.ngtcp2_settings settings
        cdef ng.ngtcp2_transport_params params
        cdef ng.ngtcp2_callbacks callbacks
        cdef bytes token_bytes = None
        cdef bytes host = None
        cdef int rv

        self._transport = self._configure(
            self._transport, endpoint, ts, &settings, &params, &callbacks, False,
        )
        # Differs from version only after a Version Negotiation packet.
        settings.original_version = self._original_version
        if token is not None:
            token_bytes = bytes(token)
            settings.token = <const uint8_t *>PyBytes_AS_STRING(token_bytes)
            settings.tokenlen = len(token_bytes)
        _to_sockaddr(self._initial_remote, &remote, &path.remote.addrlen)
        _to_client_local(self._initial_local, &local, &path.local.addrlen)
        path.remote.addr = &remote.sa
        path.local.addr = &local.sa
        path.user_data = NULL
        _random_cid(&dcid, 18)
        _random_cid(&scid, endpoint._cid_len)

        rv = ng.ngtcp2_conn_client_new(
            &self._conn, &dcid, &scid, &path, version, &callbacks, &settings,
            &params, &_MEM, <void *>self,
        )
        if rv != 0:
            raise _native_error(rv)
        self._apply_runtime(self._transport)
        self._attach_tls(tls)
        ng.SSL_set_connect_state(self._ssl)
        if tls._alpn:
            ng.SSL_set_alpn_protos(
                self._ssl,
                <const uint8_t *>PyBytes_AS_STRING(tls._alpn),
                len(tls._alpn),
            )
        if self.server_name is not None:
            host = _host_name(self.server_name)
            # AWS-LC refuses some names the checks above let through, such as
            # an IPv4 address with leading zeros: never connect unverified.
            if _is_ip_address(host.decode("ascii")):
                if tls._check_hostname and not ng.X509_VERIFY_PARAM_set1_ip_asc(
                    ng.SSL_get0_param(self._ssl), host,
                ):
                    raise ValueError(
                        f"server_name {self.server_name!r} is not an IP address"
                        " TLS accepts"
                    )
            elif not ng.SSL_set_tlsext_host_name(self._ssl, host) or (
                tls._check_hostname and not ng.X509_VERIFY_PARAM_set1_host(
                    ng.SSL_get0_param(self._ssl), host, len(host),
                )
            ):
                raise ValueError(
                    f"server_name {self.server_name!r} is not a host name TLS accepts"
                )
        if session_ticket is not None:
            self._resume(bytes(session_ticket))

        endpoint._register(self, _cid_key(scid.data, scid.datalen))
        endpoint._connections.add(self)

    cdef bint _renegotiate_version(self, ng.ngtcp2_tstamp ts) except -1:
        """Restart in a version the server offered; ``False`` if none is shared.

        Tickets and tokens belong to the abandoned version and are not reused
        (RFC 9369 section 3.3). Streams opened for 0-RTT are gone, as when
        0-RTT is rejected.
        """
        cdef uint32_t offered[_MAX_VERSIONS]
        cdef size_t count = 0
        cdef uint32_t chosen
        cdef size_t i

        # React to Version Negotiation once (RFC 9368 section 2.4).
        if self._offered_versions is None or self._version_retried:
            return False
        # Only the ones this endpoint prefers can be chosen, however many
        # unknown versions the server listed first.
        # Loops, not comprehensions: Cython 3.3 frees a comprehension's item
        # twice when appending it fails.
        preferred = []
        for i in range(self._endpoint._preferred_len):
            preferred.append(self._endpoint._preferred[i])
        for value in self._offered_versions:
            if value in preferred and count < _MAX_VERSIONS:
                offered[count] = value
                count += 1
        chosen = ng.ngtcp2_select_version(
            self._endpoint._preferred, self._endpoint._preferred_len, offered, count,
        )
        if chosen == 0:
            return False
        try:
            self._endpoint._unregister(self)
            self._release()
            self._stop_sending_streams()
            if self._streams:
                self._streams.clear()
                self._events.append(EarlyDataRejected.__new__(EarlyDataRejected))
            self._offered_versions = None
            self._version_retried = True
            self._start_client(ts, chosen, None, None)
        except BaseException:
            # Partly released: nothing is left to drive.
            self._finish()
            raise
        return True

    @staticmethod
    cdef object _server(
        type kind, Incoming incoming, TLSContext tls, object transport,
        object application,
    ):
        cdef BaseConnection self = <BaseConnection>kind.__new__(kind)
        cdef Endpoint endpoint = incoming._endpoint
        cdef ng.ngtcp2_cid scid
        cdef ng.ngtcp2_path path
        cdef ng.ngtcp2_settings settings
        cdef ng.ngtcp2_transport_params params
        cdef ng.ngtcp2_callbacks callbacks
        cdef uint8_t early_context[_MAX_EARLY_PARAMS]
        cdef ng.ngtcp2_ssize early_len
        cdef bytes early
        cdef int rv
        cdef bytes datagram

        self.is_client = False
        self._endpoint = endpoint
        self._tls = tls
        # Before the first read: the server's 1-RTT keys arrive during it.
        self._set_application(application, transport)
        transport = self._configure(
            transport, endpoint, incoming._ts, &settings, &params, &callbacks, True,
        )
        if incoming._token_type != ng.NGTCP2_TOKEN_TYPE_UNKNOWN:
            settings.token = <const uint8_t *>PyBytes_AS_STRING(incoming._token)
            settings.tokenlen = len(incoming._token)
            settings.token_type = incoming._token_type
        if incoming._token_type == ng.NGTCP2_TOKEN_TYPE_RETRY:
            params.original_dcid = incoming._odcid
            params.retry_scid = incoming._hd.dcid
            params.retry_scid_present = 1
        else:
            params.original_dcid = incoming._hd.dcid
        params.original_dcid_present = 1
        path.remote.addr = &incoming._remote.sa
        path.remote.addrlen = incoming._remote_len
        path.local.addr = &incoming._local.sa
        path.local.addrlen = incoming._local_len
        path.user_data = NULL
        _random_cid(&scid, endpoint._cid_len)
        # The client keeps this CID unless it migrates, so without the token
        # it could never recognize our stateless resets (RFC 9000 10.3).
        if ng.ngtcp2_crypto_generate_stateless_reset_token(
            params.stateless_reset_token,
            <const uint8_t *>PyBytes_AS_STRING(endpoint._secret),
            len(endpoint._secret), &scid,
        ) != 0:
            raise InternalError("cannot derive the stateless reset token")
        params.stateless_reset_token_present = 1
        if endpoint._has_preferred_addr:
            params.preferred_addr = endpoint._preferred_addr
            _random_cid(&params.preferred_addr.cid, endpoint._cid_len)
            if ng.ngtcp2_crypto_generate_stateless_reset_token(
                params.preferred_addr.stateless_reset_token,
                <const uint8_t *>PyBytes_AS_STRING(endpoint._secret),
                len(endpoint._secret), &params.preferred_addr.cid,
            ) != 0:
                raise InternalError("cannot derive the stateless reset token")
            params.preferred_addr_present = 1

        rv = ng.ngtcp2_conn_server_new(
            &self._conn, &incoming._hd.scid, &scid, &path, incoming._hd.version,
            &callbacks, &settings, &params, &_MEM, <void *>self,
        )
        if rv != 0:
            raise _native_error(rv)
        self._apply_runtime(transport)
        self._attach_tls(tls)
        ng.SSL_set_accept_state(self._ssl)
        _accept_tickets_from(self._ssl, incoming._hd.version)
        # Set even without early data: select_tls_context() may enable it.
        # A ticket whose context differs gets its 0-RTT rejected.
        early_len = _early_data_context(&params, early_context)
        early = (
            PyBytes_FromStringAndSize(<const char *>early_context, early_len)
            + self._early_settings()
        )
        ng.SSL_set_quic_early_data_context(
            self._ssl, <const uint8_t *>PyBytes_AS_STRING(early), len(early),
        )
        ng.SSL_set_early_data_enabled(self._ssl, tls._early_data)
        self._initial_remote = incoming.remote_addr
        self._initial_local = incoming.local_addr

        endpoint._register(self, _cid_key(scid.data, scid.datalen))
        endpoint._register(self, incoming._dcid_key)
        if params.preferred_addr_present:
            endpoint._register(self, _cid_key(
                params.preferred_addr.cid.data, params.preferred_addr.cid.datalen,
            ))
        endpoint._connections.add(self)
        rv = self._read(
            <const uint8_t *>PyBytes_AS_STRING(incoming._datagram),
            len(incoming._datagram), &path, incoming._ecn, incoming._ts,
        )
        if rv == ng.NGTCP2_ERR_RETRY:
            self._finish()
            _retry_after_accept(incoming)
            return None
        if rv == ng.NGTCP2_ERR_DROP_CONN:
            self._finish()
            return None
        if rv != 0:
            self._handle_error(rv, incoming._ts)
        for datagram in incoming._extra:
            self._receive(
                <const uint8_t *>PyBytes_AS_STRING(datagram), len(datagram), &path,
                incoming._ecn, incoming._ts,
            )
        return self

    cdef object _configure(
        self, object transport, Endpoint endpoint, ng.ngtcp2_tstamp ts,
        ng.ngtcp2_settings *settings, ng.ngtcp2_transport_params *params,
        ng.ngtcp2_callbacks *callbacks, bint server,
    ):
        """Translate ``transport`` into native settings, parameters and callbacks."""
        if transport is None:
            transport = _DEFAULT_TRANSPORT
        elif not isinstance(transport, TransportConfig):
            raise TypeError("transport must be a TransportConfig")

        ng.ngtcp2_settings_default(settings)
        settings.initial_ts = ts
        settings.cc_algo = <ng.ngtcp2_cc_algo><int>CongestionControl(
            transport.congestion_control
        )
        settings.initial_rtt = _duration(transport.initial_rtt, "initial_rtt")
        if not settings.initial_rtt:
            raise ValueError("initial_rtt must be positive")
        settings.max_tx_udp_payload_size = <size_t>_uint(
            transport.max_tx_udp_payload_size, "max_tx_udp_payload_size",
            ng.NGTCP2_MAX_TX_UDP_PAYLOAD_SIZE,
        )
        if settings.max_tx_udp_payload_size < <size_t>ng.NGTCP2_MAX_UDP_PAYLOAD_SIZE:
            raise ValueError("max_tx_udp_payload_size must be at least 1200")
        settings.max_window = _limit(transport.max_window, "max_window", _MAX_VARINT)
        settings.max_stream_window = _limit(
            transport.max_stream_window, "max_stream_window", _MAX_VARINT,
        )
        settings.ack_thresh = <size_t>_uint(
            transport.ack_threshold, "ack_threshold", 0xFFFF,
        )
        settings.no_tx_udp_payload_size_shaping = not transport.udp_payload_size_shaping
        settings.handshake_timeout = (
            _NO_EXPIRY if transport.handshake_timeout is None
            else _timeout(transport.handshake_timeout, "handshake_timeout")
        )
        settings.no_pmtud = not transport.pmtud
        if transport.pmtud_probes is not None:
            self._pmtud_probes(transport.pmtud_probes, settings)
        settings.preferred_versions = endpoint._preferred
        settings.preferred_versionslen = endpoint._preferred_len
        settings.available_versions = endpoint._available
        settings.available_versionslen = endpoint._available_len
        settings.glitch_ratelim_burst = _uint(
            transport.glitch_rate_limit[0], "glitch_rate_limit", <uint64_t>-1,
        )
        settings.glitch_ratelim_rate = _uint(
            transport.glitch_rate_limit[1], "glitch_rate_limit", <uint64_t>-1,
        )
        settings.write_stream_data_thresh = <size_t>_uint(
            transport.write_stream_data_threshold, "write_stream_data_threshold", 65535,
        )
        if transport.qlog is not None:
            self._qlog = transport.qlog
            settings.qlog_write = _write_qlog

        ng.ngtcp2_transport_params_default(params)
        params.initial_max_data = _uint(transport.max_data, "max_data", _MAX_VARINT)
        params.initial_max_stream_data_bidi_local = _uint(
            transport.max_stream_data_bidi_local,
            "max_stream_data_bidi_local",
            _MAX_VARINT,
        )
        params.initial_max_stream_data_bidi_remote = _uint(
            transport.max_stream_data_bidi_remote,
            "max_stream_data_bidi_remote",
            _MAX_VARINT,
        )
        params.initial_max_stream_data_uni = _uint(
            transport.max_stream_data_uni, "max_stream_data_uni", _MAX_VARINT,
        )
        params.initial_max_streams_bidi = _uint(
            transport.max_streams_bidi, "max_streams_bidi", 1 << 60,
        )
        if not server and not self._server_opens_bidi():
            params.initial_max_streams_bidi = 0
        params.initial_max_streams_uni = _uint(
            transport.max_streams_uni, "max_streams_uni", 1 << 60,
        )
        params.max_idle_timeout = _timeout(transport.idle_timeout, "idle_timeout")
        params.max_udp_payload_size = _uint(
            transport.max_udp_payload_size, "max_udp_payload_size", 65527,
        )
        if params.max_udp_payload_size < <uint64_t>ng.NGTCP2_MAX_UDP_PAYLOAD_SIZE:
            raise ValueError("max_udp_payload_size must be at least 1200")
        # ngtcp2 keeps at most 8 unused connection IDs (ngtcp2_dcidtr.h).
        params.active_connection_id_limit = _uint(
            transport.active_connection_id_limit, "active_connection_id_limit", 8,
        )
        if params.active_connection_id_limit < 2:
            raise ValueError("active_connection_id_limit must be at least 2")
        params.ack_delay_exponent = _uint(
            transport.ack_delay_exponent, "ack_delay_exponent", 20,
        )
        params.max_ack_delay = _duration(transport.max_ack_delay, "max_ack_delay")
        if params.max_ack_delay >= (<uint64_t>1 << 14) * 1000000:
            raise ValueError("max_ack_delay must be below 16.384 seconds")
        params.max_datagram_frame_size = (
            0 if transport.max_datagram_frame_size is None
            else _uint(
                transport.max_datagram_frame_size, "max_datagram_frame_size", 65535,
            )
        )
        params.disable_active_migration = transport.disable_active_migration
        params.grease_quic_bit = transport.grease_quic_bit

        memset(callbacks, 0, sizeof(ng.ngtcp2_callbacks))
        ng.glue_set_crypto_callbacks(callbacks, server)
        callbacks.handshake_completed = _handshake_completed
        callbacks.handshake_confirmed = _handshake_confirmed
        callbacks.recv_stream_data = _recv_stream_data
        callbacks.acked_stream_data_offset = _acked_stream_data_offset
        callbacks.extend_max_local_streams_bidi = _extend_max_local_streams
        callbacks.extend_max_local_streams_uni = _extend_max_local_streams
        callbacks.rand = _rand
        callbacks.remove_connection_id = _remove_connection_id
        callbacks.path_validation = _path_validation
        callbacks.begin_path_validation = _begin_path_validation
        callbacks.stream_reset = _stream_reset
        callbacks.extend_max_stream_data = _extend_max_stream_data
        callbacks.recv_new_token = _recv_new_token
        callbacks.recv_datagram = _recv_datagram
        callbacks.ack_datagram = _ack_datagram
        callbacks.lost_datagram = _lost_datagram
        callbacks.tls_early_data_rejected = _tls_early_data_rejected
        callbacks.recv_stateless_reset2 = _recv_stateless_reset
        callbacks.get_new_connection_id2 = _get_new_connection_id
        callbacks.dcid_status2 = _dcid_status
        callbacks.recv_stop_sending = _recv_stop_sending
        callbacks.stream_close2 = _stream_close
        callbacks.stream_open = _stream_open
        callbacks.recv_tx_key = _recv_tx_key
        if server:
            callbacks.extend_max_remote_streams_bidi = _extend_max_remote_streams_bidi
        else:
            callbacks.recv_rx_key = _recv_rx_key
            callbacks.recv_version_negotiation = _recv_version_negotiation
            if transport.use_preferred_address:
                callbacks.select_preferred_addr = _select_preferred_addr

        self._auto_flow = transport.auto_flow_control
        self._high = _uint(
            transport.stream_write_buffer_high, "stream_write_buffer_high", _MAX_VARINT,
        )
        self._low = (
            self._high // 4 if transport.stream_write_buffer_low is None
            else _uint(
                transport.stream_write_buffer_low,
                "stream_write_buffer_low",
                self._high,
            )
        )
        if transport.max_datagram_queue < 1:
            raise ValueError("max_datagram_queue must be at least 1")
        self._datagram_queue = <Py_ssize_t>_uint(
            transport.max_datagram_queue, "max_datagram_queue", 1 << 20,
        )
        _limit(transport.path_degrading_ptos, "path_degrading_ptos", 0xFFFF)
        return transport

    cdef int _pmtud_probes(self, object probes, ng.ngtcp2_settings *settings) except -1:
        # ngtcp2 copies the array while creating the connection.
        values = []
        for probe in probes:
            values.append(
                _uint(probe, "pmtud_probes", ng.NGTCP2_MAX_TX_UDP_PAYLOAD_SIZE)
            )
        if not values or any(
            value <= ng.NGTCP2_MAX_UDP_PAYLOAD_SIZE
            or value > settings.max_tx_udp_payload_size
            for value in values
        ):
            raise ValueError(
                "pmtud_probes must be above 1200 and at most max_tx_udp_payload_size"
            )
        self._probe_storage = bytearray(len(values) * 2)
        for index, value in enumerate(values):
            (<uint16_t *><char *>self._probe_storage)[index] = value
        settings.pmtud_probes = <const uint16_t *><char *>self._probe_storage
        settings.pmtud_probeslen = len(values)

    cdef int _apply_runtime(self, object transport) except -1:
        if transport.keep_alive_interval is not None:
            ng.ngtcp2_conn_set_keep_alive_timeout(
                self._conn,
                _timeout(transport.keep_alive_interval, "keep_alive_interval"),
            )

    cdef int _attach_tls(self, TLSContext tls) except -1:
        self._ssl = ng.SSL_new(tls._ctx)
        if self._ssl == NULL:
            raise _tls_error("cannot create TLS session")
        self._conn_ref.get_conn = _get_conn
        self._conn_ref.user_data = <void *>self
        ng.SSL_set_app_data(self._ssl, &self._conn_ref)
        # Free what only the handshake reads (certificates, ALPN, transport
        # parameters) once it completes: an idle connection keeps less.
        ng.SSL_set_shed_handshake_config(self._ssl, 1)
        ng.ngtcp2_conn_set_tls_native_handle(self._conn, self._ssl)

    cdef int _resume(self, bytes ticket) except -1:
        cdef const uint8_t *data = <const uint8_t *>PyBytes_AS_STRING(ticket)
        cdef size_t length = len(ticket)
        cdef size_t session_len
        cdef ng.SSL_SESSION *session

        if length < 5 or data[0] != _TICKET_FORMAT:
            raise ValueError(
                "session_ticket is not a ticket from SessionTicketReceived"
            )
        session_len = int.from_bytes(ticket[1:5], "big")
        if 5 + session_len > length:
            raise ValueError("session_ticket is truncated")
        session = ng.SSL_SESSION_from_bytes(data + 5, session_len, self._tls._ctx)
        if session == NULL:
            ng.ERR_clear_error()
            raise ValueError("session_ticket holds no valid TLS session")
        try:
            ng.SSL_set_session(self._ssl, session)
            if (
                ng.SSL_SESSION_early_data_capable(session)
                and ng.ngtcp2_conn_decode_and_set_0rtt_transport_params(
                    self._conn, data + 5 + session_len, length - 5 - session_len,
                ) == 0
            ):
                ng.SSL_set_early_data_enabled(self._ssl, 1)
                # ngtcp2 does not announce stream credit restored from a ticket.
                self._events.append(_streams_available(self._conn))
        finally:
            ng.SSL_SESSION_free(session)

    # ---- driving

    def events(self):
        error = self._deferred_error
        if error is not None:
            self._deferred_error = None
            raise error
        result = self._events
        self._events = []
        return result

    def datagrams_to_send(self, double now, *, int max_datagrams=64, bint gso=False):
        cdef ng.ngtcp2_tstamp ts = self._clock(now)
        cdef ng.ngtcp2_path_storage storage
        cdef ng.ngtcp2_pkt_info info
        cdef PyObject *buffer
        cdef size_t payload, probe, burst, packets, capacity, segment = 0
        cdef ng.ngtcp2_ssize written
        cdef Py_ssize_t sent
        cdef list result
        cdef bint idle

        if max_datagrams < 1:
            raise ValueError("max_datagrams must be positive")
        result = self._pending_out
        self._pending_out = []
        if self._close_pending:
            self._write_close(ts, result)
            return result
        if self._state >= _CLOSING:
            return result

        # Data sent after nothing was in flight starts waiting now.
        idle = self._degrading_ptos != 0 and self._in_flight() == 0
        payload = ng.ngtcp2_conn_get_path_max_tx_udp_payload_size2(self._conn)
        # A PMTUD probe is larger than the path's current payload size.
        probe = ng.ngtcp2_conn_get_max_tx_udp_payload_size2(self._conn)
        # One pacing burst per call, as ngtcp2_conn_write_aggregate_pkt sends.
        burst = ng.ngtcp2_conn_get_send_quantum2(self._conn)
        sent = len(result)
        while sent < max_datagrams and burst:
            packets = 1
            if gso:
                packets = min(
                    <size_t>(max_datagrams - sent),
                    _MAX_GSO_BYTES // payload,
                    _MAX_GSO_SEGMENTS,
                )
            capacity = max(min(payload * packets, burst), probe)
            buffer = _new_bytes(NULL, capacity)
            storage.path.local.addr = &storage.local_addrbuf.sa
            storage.path.remote.addr = &storage.remote_addrbuf.sa
            storage.path.local.addrlen = sizeof(ng.ngtcp2_sockaddr_union)
            storage.path.remote.addrlen = sizeof(ng.ngtcp2_sockaddr_union)
            storage.path.user_data = NULL
            info.ecn = 0
            written = ng.ngtcp2_conn_write_aggregate_pkt2(
                self._conn, &storage.path, &info, <uint8_t *>_bytes_buffer(buffer),
                capacity, &segment, _write_pkt, packets, ts,
            )
            if written <= 0:
                Py_DECREF(buffer)
                self._raise_callback_error()
                if written < 0:
                    self._handle_error(<int>written, ts)
                    if self._close_pending:
                        self._write_close(ts, result)
                    return result
                break
            if self._callback_error is not None:
                Py_DECREF(buffer)
                self._raise_callback_error()
            sent += (written + segment - 1) // segment
            burst -= min(<size_t>written, burst)
            _PyBytes_Resize(&buffer, written)
            try:
                result.append(_transmit(
                    <bytes>buffer,
                    self._remote_cache.get(&storage.path.remote),
                    self._local_cache.get(&storage.path.local),
                    segment, info.ecn,
                ))
            finally:
                Py_DECREF(buffer)
        ng.ngtcp2_conn_update_pkt_tx_time(self._conn, ts)
        if idle and self._in_flight():
            self._waiting_since = ts
        return result

    def get_timer(self):
        cdef uint64_t expiry

        if self._state == _CLOSED:
            return None
        if self._state >= _CLOSING:
            if self._deadline == _NO_EXPIRY:
                return _deadline(ng.ngtcp2_conn_get_timestamp(self._conn))
            return _deadline(self._deadline)
        expiry = min(ng.ngtcp2_conn_get_expiry2(self._conn), self._degrading_deadline())
        if expiry == _NO_EXPIRY:
            return None
        return _deadline(expiry)

    def handle_timer(self, double now):
        cdef ng.ngtcp2_tstamp ts = self._clock(now)
        cdef int rv

        if self._state == _CLOSED:
            return
        if self._state >= _CLOSING:
            if self._deadline == _NO_EXPIRY:
                self._deadline = ts + 3 * ng.ngtcp2_conn_get_pto2(self._conn)
            elif ts >= self._deadline:
                self._finish()
            return
        rv = ng.ngtcp2_conn_handle_expiry(self._conn, ts)
        self._raise_callback_error()
        if rv != 0:
            self._handle_error(rv, ts)
        elif self._degrading_deadline() <= ts:
            self._degraded = True
            self._events.append(PathDegrading.__new__(PathDegrading))

    # ---- control

    def close(self, error_code=0, reason=b"", *, bint application=True):
        cdef uint64_t code = _uint(error_code, "error_code", _MAX_VARINT)
        cdef bytes phrase = _reason_bytes(reason)

        if self._state >= _CLOSING:
            return
        self._close_reason = phrase
        if application:
            ng.ngtcp2_ccerr_set_application_error(
                &self._ccerr,
                code,
                <const uint8_t *>PyBytes_AS_STRING(phrase),
                len(phrase),
            )
        else:
            ng.ngtcp2_ccerr_set_transport_error(
                &self._ccerr,
                code,
                <const uint8_t *>PyBytes_AS_STRING(phrase),
                len(phrase),
            )
        self._start_closing(
            CloseReason.APPLICATION_ERROR if application
            else CloseReason.TRANSPORT_ERROR,
        )

    def migrate(self, local_addr, double now, *, bint validate=True):
        cdef ng.ngtcp2_tstamp ts = self._clock(now)
        cdef ng.ngtcp2_sockaddr_union local
        cdef ng.ngtcp2_path path
        cdef const ng.ngtcp2_path *current
        cdef int rv

        self._require_open()
        if not self.is_client:
            raise ConnectionStateError("only clients migrate")
        current = ng.ngtcp2_conn_get_path2(self._conn)
        _to_client_local(local_addr, &local, &path.local.addrlen)
        path.local.addr = &local.sa
        path.remote = current.remote
        path.user_data = NULL
        if validate:
            rv = ng.ngtcp2_conn_initiate_migration(self._conn, &path, ts)
        else:
            rv = ng.ngtcp2_conn_initiate_immediate_migration(self._conn, &path, ts)
        self._raise_callback_error()
        if rv == ng.NGTCP2_ERR_INVALID_STATE:
            raise ConnectionStateError(
                "migration is not possible now: the handshake is unconfirmed or "
                "the peer disabled active migration"
            )
        if rv == ng.NGTCP2_ERR_INVALID_ARGUMENT:
            raise ValueError("local_addr is already the current local address")
        if rv == ng.NGTCP2_ERR_CONN_ID_BLOCKED:
            raise ConnectionStateError("the peer provided no spare connection ID")
        if rv != 0:
            raise _native_error(rv)

    def update_key(self, double now):
        cdef int rv

        self._require_open()
        rv = ng.ngtcp2_conn_initiate_key_update(self._conn, self._clock(now))
        if rv != 0:
            raise ConnectionStateError("a key update is not possible now")

    def select_tls_context(self, TLSContext tls not None, double now):
        self._require_open()
        if self._tls_pause != _PAUSE_SELECT:
            raise ConnectionStateError("no certificate selection is pending")
        if not tls._server:
            raise ValueError("tls must be a server context")
        if tls is not self._tls:
            if ng.SSL_set_SSL_CTX(self._ssl, tls._ctx) == NULL:
                raise _tls_error("cannot switch the TLS context")
            # Switching contexts resets the early data and ticket settings.
            ng.SSL_set_early_data_enabled(self._ssl, tls._early_data)
            _accept_tickets_from(
                self._ssl, ng.ngtcp2_conn_get_client_chosen_version2(self._conn),
            )
            self._selected_tls = tls
        self._certificate_selected = True
        self._resume_handshake(now)

    def verify_peer_certificate(self, bint accepted, double now):
        self._require_open()
        if self._tls_pause != _PAUSE_VERIFY:
            raise ConnectionStateError("no peer verification is pending")
        self._peer_verdict = accepted
        self._resume_handshake(now)

    # ---- state

    @property
    def state(self):
        return _STATES[self._state]

    @property
    def local_addr(self):
        if self._conn == NULL:
            return self._initial_local
        return self._local_cache.get(&ng.ngtcp2_conn_get_path2(self._conn).local)

    @property
    def remote_addr(self):
        if self._conn == NULL:
            return self._initial_remote
        return self._remote_cache.get(&ng.ngtcp2_conn_get_path2(self._conn).remote)

    @property
    def version(self):
        cdef uint32_t value

        if self._conn == NULL:
            return None
        value = ng.ngtcp2_conn_get_negotiated_version2(self._conn)
        return Version(value) if value else None

    @property
    def alpn_protocol(self):
        cdef const uint8_t *data
        cdef unsigned int length = 0

        if self._ssl == NULL:
            return None
        ng.SSL_get0_alpn_selected(self._ssl, &data, &length)
        return data[:length].decode("ascii") if length else None

    @property
    def peer_certificate(self):
        cdef ng.X509 *certificate
        cdef uint8_t *encoded = NULL
        cdef int length

        if self._ssl == NULL:
            return None
        certificate = ng.SSL_get_peer_certificate(self._ssl)
        if certificate == NULL:
            return None
        try:
            length = ng.i2d_X509(certificate, &encoded)
            if length < 0:
                raise _tls_error("cannot encode the peer certificate")
            return PyBytes_FromStringAndSize(<const char *>encoded, length)
        finally:
            ng.OPENSSL_free(encoded)
            ng.X509_free(certificate)

    @property
    def peer_transport_parameters(self):
        cdef const ng.ngtcp2_transport_params *params

        if self._conn == NULL:
            return None
        params = ng.ngtcp2_conn_get_remote_transport_params2(self._conn)
        if params == NULL:
            return None
        return TransportParameters(
            max_data=params.initial_max_data,
            max_stream_data_bidi_local=params.initial_max_stream_data_bidi_local,
            max_stream_data_bidi_remote=params.initial_max_stream_data_bidi_remote,
            max_stream_data_uni=params.initial_max_stream_data_uni,
            max_streams_bidi=params.initial_max_streams_bidi,
            max_streams_uni=params.initial_max_streams_uni,
            idle_timeout=_seconds(params.max_idle_timeout) or None,
            max_udp_payload_size=params.max_udp_payload_size,
            active_connection_id_limit=params.active_connection_id_limit,
            ack_delay_exponent=params.ack_delay_exponent,
            max_ack_delay=_seconds(params.max_ack_delay),
            max_datagram_frame_size=params.max_datagram_frame_size or None,
            disable_active_migration=params.disable_active_migration,
            grease_quic_bit=params.grease_quic_bit,
            preferred_address=(
                PreferredAddress(
                    ipv4=_from_sockaddr(
                        <const ng.ngtcp2_sockaddr *>&params.preferred_addr.ipv4
                    ) if params.preferred_addr.ipv4_present else None,
                    ipv6=_from_sockaddr(
                        <const ng.ngtcp2_sockaddr *>&params.preferred_addr.ipv6
                    ) if params.preferred_addr.ipv6_present else None,
                )
                if params.preferred_addr_present else None
            ),
        )

    @property
    def pto(self):
        if self._conn == NULL:
            return 0.0
        return _seconds(ng.ngtcp2_conn_get_pto2(self._conn))

    @property
    def stats(self):
        cdef ng.ngtcp2_conn_info info

        if self._conn == NULL:
            memset(&info, 0, sizeof(info))
        else:
            ng.ngtcp2_conn_get_conn_info2(self._conn, &info)
        return ConnectionStats(
            latest_rtt=_seconds(info.latest_rtt),
            min_rtt=_seconds(info.min_rtt),
            smoothed_rtt=_seconds(info.smoothed_rtt),
            rtt_variance=_seconds(info.rttvar),
            congestion_window=info.cwnd,
            slow_start_threshold=info.ssthresh,
            bytes_in_flight=info.bytes_in_flight,
            packets_sent=info.pkt_sent,
            bytes_sent=info.bytes_sent,
            packets_received=info.pkt_recv,
            bytes_received=info.bytes_recv,
            packets_lost=info.pkt_lost,
            bytes_lost=info.bytes_lost,
            pings_received=info.ping_recv,
            packets_discarded=info.pkt_discarded,
        )

    def __repr__(self):
        return (
            f"{type(self).__name__}(is_client={self.is_client}, "
            f"state={self.state.name}, "
            f"remote_addr={self.remote_addr!r})"
        )

    # ---- stream protocol hooks
    #
    # Callbacks hand stream-level work to these methods: Connection exposes
    # raw streams, H3Connection drives nghttp3. Each returns 0, or a native
    # error code after _close_with() set the reason. The defaults here are
    # what both share.

    cdef int _set_application(self, object application, object transport) except -1:
        return 0

    cdef bint _server_opens_bidi(self):
        """Whether a client lets the server open bidirectional streams."""
        return True

    cdef bytes _early_settings(self):
        """Application settings a server's 0-RTT ticket relies on."""
        return b""

    cdef int _application_keys(self) except -1:
        """Run when 1-RTT keys allow application data, and on handshake completion."""
        return 0

    cdef int _remote_streams_bidi(self, uint64_t max_streams) except -1:
        return 0

    cdef int _stream_opened(self, int64_t stream_id) except -1:
        return 0

    cdef int _stream_data(
        self, uint32_t flags, int64_t stream_id, const uint8_t *data, size_t length,
    ) except -1:
        return 0

    cdef int _stream_acked(
        self, int64_t stream_id, uint64_t length, void *stream_user_data,
    ) except -1:
        return 0

    cdef int _stream_closed(
        self, uint32_t flags, int64_t stream_id, uint64_t rx_error_code,
        uint64_t tx_error_code, void *stream_user_data,
    ) except -1:
        return 0

    cdef int _stream_reset(
        self, int64_t stream_id, uint64_t final_size, uint64_t error_code,
    ) except -1:
        cdef StreamReset event = StreamReset.__new__(StreamReset)

        event.stream_id = stream_id
        event.error_code = error_code
        event.final_size = final_size
        self._events.append(event)
        return 0

    cdef int _stop_sending_received(
        self, int64_t stream_id, uint64_t error_code, void *stream_user_data,
    ) except -1:
        cdef StopSendingReceived event = StopSendingReceived.__new__(
            StopSendingReceived
        )

        # ngtcp2 answers with RESET_STREAM itself; nothing more is sent.
        if stream_user_data != NULL:
            (<_Stream>stream_user_data).abandon()
        event.stream_id = stream_id
        event.error_code = error_code
        self._events.append(event)
        return 0

    cdef int _stream_unblocked(
        self, int64_t stream_id, void *stream_user_data,
    ) except -1:
        return 0

    cdef int _early_data_rejected(self) except -1:
        # ngtcp2 freed every 0-RTT stream and the packets that carried their
        # data before calling back, so nothing native points at them any more.
        self._stop_sending_streams()
        self._streams.clear()
        return 0

    cdef int _datagram_received(
        self, uint32_t flags, const uint8_t *data, size_t length,
    ) except -1:
        return 0

    cdef ng.ngtcp2_ssize _write_stream(
        self, ng.ngtcp2_path *path, ng.ngtcp2_pkt_info *info, uint8_t *dest,
        size_t destlen, ng.ngtcp2_tstamp ts,
    ) except? -1:
        """Write one packet; ``NGTCP2_ERR_WRITE_MORE`` while it has room."""
        return ng.ngtcp2_conn_writev_stream(
            self._conn, path, info, dest, destlen, NULL, 0, -1, NULL, 0, ts,
        )

    cdef void _stop_sending_streams(self):
        """Forget which streams have data to send; nothing more is written."""
        pass

    # ---- shared by the stream protocols

    cdef int _close_with(self, uint64_t error_code) except -1:
        """Close with an application error the stream protocol detected."""
        ng.ngtcp2_ccerr_set_application_error(&self._ccerr, error_code, NULL, 0)
        self._failure_reason = CloseReason.APPLICATION_ERROR
        return ng.NGTCP2_ERR_CALLBACK_FAILURE

    cdef void _consume(self, int64_t stream_id, uint64_t length):
        ng.ngtcp2_conn_extend_max_stream_offset(self._conn, stream_id, length)
        ng.ngtcp2_conn_extend_max_offset(self._conn, length)

    cdef int _acknowledge(self, _Stream stream, uint64_t length) except -1:
        cdef StreamWritable event

        # A reset stream holds nothing more; late ACKs only report lengths.
        if stream.send_closed:
            return 0
        stream.acknowledge(length)
        if stream.paused and stream.held() <= self._low:
            stream.paused = False
            event = StreamWritable.__new__(StreamWritable)
            event.stream_id = stream.stream_id
            self._events.append(event)

    cdef uint64_t _queue_datagram(self, bytes payload) except? 0:
        """Queue a DATAGRAM payload that fits ``_datagram_limit()``; return its ID.

        A full queue reports its oldest entry lost.
        """
        cdef uint64_t datagram_id = self._next_datagram_id

        self._next_datagram_id += 1
        if len(self._datagrams) >= self._datagram_queue:
            self._drop_datagram()
        self._datagrams.append((datagram_id, payload))
        return datagram_id

    cdef bint _enqueue(self, _Stream stream, object data, bint end_stream) except -1:
        """Hold ``data`` for sending; return whether the stream stays writable."""
        cdef bytes chunk = _owned_bytes(data)
        cdef Py_ssize_t size = PyBytes_GET_SIZE(chunk)

        if size:
            stream.chunks.append(chunk)
            stream.end += size
        if end_stream:
            stream.fin_queued = True
        if stream.held() > self._high:
            stream.paused = True
        return not stream.paused

    cdef uint64_t _held(self, object stream_id) except? 0:
        """Bytes held for sending on one stream, or on all of them."""
        cdef _Stream stream
        cdef uint64_t total = 0

        if stream_id is not None:
            stream = self._streams.get(_stream_id(stream_id))
            return 0 if stream is None else stream.held()
        for stream in self._streams.values():
            total += stream.held()
        return total

    cdef int _consume_received(self, object stream_id, object amount) except -1:
        cdef int64_t sid = _stream_id(stream_id)
        cdef uint64_t length = _uint(amount, "amount", _MAX_VARINT)

        self._require_open()
        self._consume(sid, length)
        return 0

    cdef int _emit_stream_closed(
        self, int64_t stream_id, object rx_error_code, object tx_error_code,
    ) except -1:
        cdef StreamClosed event = StreamClosed.__new__(StreamClosed)

        event.stream_id = stream_id
        event.receive_error_code = rx_error_code
        event.send_error_code = tx_error_code
        self._events.append(event)
        return 0

    # ---- ngtcp2 calls for stream protocols in other extension modules,
    # which cannot link ngtcp2 themselves

    cdef int _open_stream(self, int64_t *stream_id, bint unidirectional):
        if unidirectional:
            return ng.ngtcp2_conn_open_uni_stream(self._conn, stream_id, NULL)
        return ng.ngtcp2_conn_open_bidi_stream(self._conn, stream_id, NULL)

    cdef void _shutdown_stream(
        self, int64_t stream_id, uint64_t error_code, bint read, bint write,
    ):
        if read and write:
            ng.ngtcp2_conn_shutdown_stream(self._conn, 0, stream_id, error_code)
        elif read:
            ng.ngtcp2_conn_shutdown_stream_read(self._conn, 0, stream_id, error_code)
        elif write:
            ng.ngtcp2_conn_shutdown_stream_write(self._conn, 0, stream_id, error_code)

    cdef ng.ngtcp2_ssize _writev_stream(
        self, ng.ngtcp2_path *path, ng.ngtcp2_pkt_info *info, uint8_t *dest,
        size_t destlen, ng.ngtcp2_ssize *framed, uint32_t flags, int64_t stream_id,
        const ng.ngtcp2_vec *vecs, size_t count, ng.ngtcp2_tstamp ts,
    ):
        return ng.ngtcp2_conn_writev_stream(
            self._conn, path, info, dest, destlen, framed, flags, stream_id, vecs,
            count, ts,
        )

    cdef ng.ngtcp2_tstamp _clock(self, double now) except? 0:
        """``now`` as a timestamp, never before the last one ngtcp2 saw.

        ngtcp2 aborts the process if time goes backwards; a driver that reads
        its clock once and then handles events passes a slightly older ``now``.
        """
        cdef ng.ngtcp2_tstamp ts = _timestamp(now)

        if self._conn == NULL:
            return ts
        return max(ts, ng.ngtcp2_conn_get_timestamp(self._conn))

    cdef ng.ngtcp2_tstamp _last_timestamp(self):
        return ng.ngtcp2_conn_get_timestamp(self._conn)

    cdef uint64_t _send_credit(self):
        """Connection credit above ``write_stream_data_threshold``, else 0."""
        return ng.ngtcp2_conn_get_max_data_left_write_thresh(self._conn)

    cdef uint64_t _data_left(self):
        """Connection credit left."""
        return ng.ngtcp2_conn_get_max_data_left2(self._conn)

    cdef uint64_t _bidi_streams_left(self):
        return ng.ngtcp2_conn_get_streams_bidi_left2(self._conn)

    cdef uint64_t _uni_streams_left(self):
        return ng.ngtcp2_conn_get_streams_uni_left2(self._conn)

    cdef void _local_stream_limits(self, uint64_t *bidi, uint64_t *uni):
        """Streams of each type this side lets the peer open at first."""
        cdef const ng.ngtcp2_transport_params *local = (
            ng.ngtcp2_conn_get_local_transport_params(self._conn)
        )

        bidi[0] = local.initial_max_streams_bidi
        uni[0] = local.initial_max_streams_uni

    cdef int _close_with_alert(self, uint8_t alert) except -1:
        """Close with a TLS alert, for a handshake result the protocol rejects."""
        ng.ngtcp2_ccerr_set_tls_alert(&self._ccerr, alert, NULL, 0)
        self._failure_reason = CloseReason.TRANSPORT_ERROR
        return ng.NGTCP2_ERR_CALLBACK_FAILURE

    # ---- internals

    cdef int _read(
        self, const uint8_t *packet, size_t length, ng.ngtcp2_path *path,
        uint8_t ecn, ng.ngtcp2_tstamp ts,
    ) except? -1:
        cdef ng.ngtcp2_pkt_info info
        cdef bint watching = self._degrading_ptos != 0
        cdef uint64_t in_flight = 0
        cdef int rv

        info.ecn = ecn
        ts = max(ts, ng.ngtcp2_conn_get_timestamp(self._conn))
        if watching:
            in_flight = self._in_flight()
        rv = ng.ngtcp2_conn_read_pkt(self._conn, path, &info, packet, length, ts)
        self._raise_callback_error()
        # Reading sends nothing: less in flight means the peer acknowledged
        # data or validated a new path, so it hears this side.
        if watching and self._in_flight() < in_flight:
            self._waiting_since = ts
            if self._degraded:
                self._degraded = False
                self._events.append(PathRecovered.__new__(PathRecovered))
        return rv

    cdef int _receive(
        self, const uint8_t *packet, size_t length, ng.ngtcp2_path *path,
        uint8_t ecn, ng.ngtcp2_tstamp ts,
    ) except -1:
        cdef int rv

        if self._state == _CLOSING:
            self._answer_while_closing(length)
            return 0
        if self._state >= _DRAINING:
            return 0
        rv = self._read(packet, length, path, ecn, ts)
        if rv != 0:
            self._handle_error(rv, ts)

    cdef int _answer_while_closing(self, size_t length) except -1:
        """Repeat CONNECTION_CLOSE with exponential backoff within 3x amplification."""
        self._close_received += 1
        self._close_bytes_received += length
        if self._close_packet is None or self._close_received < self._close_next:
            return 0
        if (
            self._close_bytes_received * 3
            < self._close_bytes_sent + len(self._close_packet)
        ):
            return 0
        self._close_next *= 2
        self._close_bytes_sent += len(self._close_packet)
        self._pending_out.append(_transmit(
            self._close_packet, self._close_remote, self._close_local,
            len(self._close_packet), 0,
        ))

    cdef int _handle_error(self, int rv, ng.ngtcp2_tstamp ts) except -1:
        """Move to the state ngtcp2 requires after a failed read, write or timer."""
        if self._failure_reason is not None:
            # A hook chose the error; ngtcp2 may report its failure inside the
            # handshake as NGTCP2_ERR_CRYPTO.
            self._start_closing(self._failure_reason)
        elif rv == ng.NGTCP2_ERR_DRAINING:
            self._state = _DRAINING
            self._deadline = ts + 3 * ng.ngtcp2_conn_get_pto2(self._conn)
            self._report_peer_close()
        elif rv == ng.NGTCP2_ERR_IDLE_CLOSE:
            self._terminated(
                CloseReason.IDLE_TIMEOUT, ErrorCode.NO_ERROR, None, b"", False,
            )
            self._finish()
        elif rv == ng.NGTCP2_ERR_DROP_CONN:
            self._terminated(
                CloseReason.TRANSPORT_ERROR,
                ErrorCode.PROTOCOL_VIOLATION,
                None,
                b"",
                False,
            )
            self._finish()
        elif rv == ng.NGTCP2_ERR_RECV_VERSION_NEGOTIATION:
            if self._renegotiate_version(ts):
                return 0
            self._terminated(
                CloseReason.VERSION_NEGOTIATION, ErrorCode.NO_ERROR, None, b"", True,
            )
            self._finish()
        elif rv == ng.NGTCP2_ERR_CLOSING:
            pass
        elif rv == ng.NGTCP2_ERR_CRYPTO:
            ng.ngtcp2_ccerr_set_tls_alert(
                &self._ccerr, ng.ngtcp2_conn_get_tls_alert2(self._conn), NULL, 0,
            )
            self._start_closing(CloseReason.TRANSPORT_ERROR)
        else:
            ng.ngtcp2_ccerr_set_liberr(&self._ccerr, rv, NULL, 0)
            self._start_closing(
                CloseReason.HANDSHAKE_TIMEOUT if rv == ng.NGTCP2_ERR_HANDSHAKE_TIMEOUT
                else CloseReason.TRANSPORT_ERROR,
            )

    cdef int _start_closing(self, object reason) except -1:
        self._state = _CLOSING
        self._close_pending = True
        self._stop_sending_all()
        self._terminated(
            reason,
            _error_code(
                self._ccerr.error_code,
                self._ccerr.type == ng.NGTCP2_CCERR_TYPE_TRANSPORT,
            ),
            None,
            self._close_reason,
            False,
        )

    cdef int _report_peer_close(self) except -1:
        cdef const ng.ngtcp2_ccerr *error = ng.ngtcp2_conn_get_ccerr2(self._conn)
        cdef bint transport = error.type == ng.NGTCP2_CCERR_TYPE_TRANSPORT

        self._stop_sending_all()
        if self._stateless_reset:
            self._terminated(
                CloseReason.STATELESS_RESET, ErrorCode.NO_ERROR, None, b"", True,
            )
            return 0
        self._terminated(
            CloseReason.TRANSPORT_ERROR if transport else CloseReason.APPLICATION_ERROR,
            _error_code(error.error_code, transport),
            error.frame_type if transport else None,
            PyBytes_FromStringAndSize(<const char *>error.reason, error.reasonlen),
            True,
        )

    cdef int _terminated(
        self, object reason, object error_code, object frame_type, bytes phrase,
        bint by_peer,
    ) except -1:
        cdef ConnectionTerminated event = ConnectionTerminated.__new__(
            ConnectionTerminated
        )

        event.reason = reason
        event.error_code = error_code
        event.frame_type = frame_type
        event.reason_phrase = phrase
        event.by_peer = by_peer
        self._events.append(event)

    cdef int _write_close(self, ng.ngtcp2_tstamp ts, list result) except -1:
        cdef ng.ngtcp2_path_storage storage
        cdef ng.ngtcp2_pkt_info info
        cdef uint8_t buffer[ng.NGTCP2_MAX_TX_UDP_PAYLOAD_SIZE]
        cdef ng.ngtcp2_ssize written

        self._close_pending = False
        self._deadline = ts + 3 * ng.ngtcp2_conn_get_pto2(self._conn)
        storage.path.local.addr = &storage.local_addrbuf.sa
        storage.path.remote.addr = &storage.remote_addrbuf.sa
        storage.path.local.addrlen = sizeof(ng.ngtcp2_sockaddr_union)
        storage.path.remote.addrlen = sizeof(ng.ngtcp2_sockaddr_union)
        storage.path.user_data = NULL
        written = ng.ngtcp2_conn_write_connection_close(
            self._conn, &storage.path, &info, buffer,
            ng.ngtcp2_conn_get_path_max_tx_udp_payload_size2(self._conn),
            &self._ccerr, ts,
        )
        self._raise_callback_error()
        if written <= 0:
            return 0
        self._close_packet = PyBytes_FromStringAndSize(<const char *>buffer, written)
        self._close_remote = self._remote_cache.get(&storage.path.remote)
        self._close_local = self._local_cache.get(&storage.path.local)
        self._close_bytes_sent = written
        result.append(_transmit(
            self._close_packet,
            self._close_remote,
            self._close_local,
            written,
            info.ecn,
        ))

    cdef void _finish(self):
        """Release all protocol state; the connection needs no more I/O."""
        self._state = _CLOSED
        self._pending_out = []
        if self._endpoint is not None:
            self._endpoint._unregister(self)
        self._endpoint = None
        # Native state goes first: it holds borrowed pointers to the streams.
        self._release()
        self._tls = self._selected_tls = None
        self._stop_sending_all()
        self._streams.clear()
        # ngtcp2_conn_del() wrote the final qlog notice while callbacks were
        # already off; deliver it here, outside garbage collection.
        if self._qlog is not None:
            _final_qlog_notice(self._qlog)

    cdef void _release(self):
        cdef ng.ngtcp2_conn *conn = self._conn

        # Callbacks see a NULL _conn and do nothing: ngtcp2_conn_del() can
        # call them after garbage collection has cleared Python fields.
        self._conn = NULL
        if conn != NULL:
            ng.ngtcp2_conn_del(conn)
        if self._ssl != NULL:
            ng.SSL_free(self._ssl)
            self._ssl = NULL

    cdef void _stop_sending_all(self):
        self._stop_sending_streams()
        self._datagrams.clear()

    cdef int64_t _datagram_limit(self):
        """Largest DATAGRAM payload for the current path, or -1 for none."""
        cdef const ng.ngtcp2_transport_params *params
        cdef int64_t frame, packet

        if self._conn == NULL:
            return -1
        params = ng.ngtcp2_conn_get_remote_transport_params2(self._conn)
        if params == NULL or params.max_datagram_frame_size == 0:
            return -1
        # Frame type, then the length in the varint its value needs.
        frame = <int64_t>params.max_datagram_frame_size - 2
        if frame >= 64:
            frame = max(63, <int64_t>params.max_datagram_frame_size - 3)
        if frame >= 16384:
            frame = max(16383, <int64_t>params.max_datagram_frame_size - 5)
        packet = <int64_t>ng.ngtcp2_conn_get_path_max_tx_udp_payload_size2(self._conn)
        # Without shaping the path size ignores the peer's limit; ngtcp2 still
        # caps each packet by it.
        if params.max_udp_payload_size:
            packet = min(packet, <int64_t>params.max_udp_payload_size)
        packet -= _DATAGRAM_OVERHEAD
        if frame < 1:
            return -1
        return min(frame, packet)

    cdef int _drop_datagram(self) except -1:
        cdef DatagramLost event = DatagramLost.__new__(DatagramLost)

        event.datagram_id = self._datagrams.popleft()[0]
        event.sent = False
        self._events.append(event)

    cdef int _raise_callback_error(self) except -1:
        """Raise an exception a callback deferred across the C boundary."""
        error = self._callback_error

        if error is None:
            return 0
        self._callback_error = None
        self._finish()
        if not isinstance(error, Exception):
            # KeyboardInterrupt and SystemExit stop the program, not one connection.
            raise error
        raise InternalError(
            "a protocol callback failed; the connection was dropped"
        ) from error

    cdef int _resume_handshake(self, double now) except -1:
        cdef ng.ngtcp2_tstamp ts = self._clock(now)
        cdef int rv

        self._tls_pause = _PAUSE_NONE
        rv = ng.ngtcp2_conn_continue_handshake(self._conn, ts)
        self._raise_callback_error()
        if rv != 0:
            self._handle_error(rv, ts)

    cdef int _require_open(self) except -1:
        if self._state >= _CLOSING:
            raise ConnectionStateError("the connection is closing or closed")

    cdef _Stream _existing(self, int64_t stream_id):
        cdef object stream

        self._require_open()
        stream = self._streams.get(stream_id)
        if stream is None:
            raise StreamStateError(f"stream {stream_id} does not exist")
        return <_Stream>stream

    cdef uint64_t _in_flight(self) noexcept:
        cdef ng.ngtcp2_conn_info info

        ng.ngtcp2_conn_get_conn_info2(self._conn, &info)
        return info.bytes_in_flight

    cdef uint64_t _degrading_deadline(self) noexcept:
        """When waiting data makes the path degrading, as Google quiche times it."""
        if self._degrading_ptos == 0 or self._degraded or self._in_flight() == 0:
            return _NO_EXPIRY
        return (
            self._waiting_since
            + self._degrading_ptos * ng.ngtcp2_conn_get_pto2(self._conn)
        )


_STATES = tuple(ConnectionState)


cdef bytes _host_name(object name):
    """``name`` in the ASCII form for SNI and certificate checks, as ``ssl`` has it.

    Checked after encoding: IDNA maps characters such as U+3002 and U+2024 to
    dots.
    """
    cdef bytes host

    try:
        # As a str proper, so a subclass such as a StrEnum member encodes alike.
        host = str.encode(name, "idna")
    except UnicodeError as error:
        # The reason is the last argument of UnicodeError before 3.13's
        # UnicodeEncodeError too.
        raise ValueError(
            f"server_name {name!r} is not a valid host name: {error.args[-1]}"
        ) from error
    # SNI and certificates name hosts without the root's dot (RFC 6066 3).
    if host.endswith(b"."):
        host = host[:-1]
    # An empty name would switch hostname checking off, a leading dot makes
    # AWS-LC match any subdomain, and C strings end at NUL.
    if not host or host.startswith(b".") or b"\0" in host:
        raise ValueError(
            f"server_name {name!r} cannot be empty, start with a dot or contain NUL"
        )
    return host


cdef bint _is_ip_address(str name):
    cdef ng.ngtcp2_sockaddr_union scratch
    cdef bytes host = name.encode("ascii", "replace")

    return (
        ng.inet_pton(ng.AF_INET, host, &scratch.in4.sin_addr) == 1
        or ng.inet_pton(ng.AF_INET6, host, &scratch.in6.sin6_addr) == 1
    )


cdef ng.ngtcp2_ssize _early_data_context(
    const ng.ngtcp2_transport_params *params, uint8_t *out,
) except -1:
    """Encode the limits a 0-RTT ticket may rely on (RFC 9000, section 7.4.1)."""
    cdef ng.ngtcp2_transport_params limits
    cdef ng.ngtcp2_ssize length

    ng.ngtcp2_transport_params_default(&limits)
    limits.initial_max_streams_bidi = params.initial_max_streams_bidi
    limits.initial_max_streams_uni = params.initial_max_streams_uni
    limits.initial_max_stream_data_bidi_local = (
        params.initial_max_stream_data_bidi_local
    )
    limits.initial_max_stream_data_bidi_remote = (
        params.initial_max_stream_data_bidi_remote
    )
    limits.initial_max_stream_data_uni = params.initial_max_stream_data_uni
    limits.initial_max_data = params.initial_max_data
    limits.max_datagram_frame_size = params.max_datagram_frame_size
    limits.active_connection_id_limit = params.active_connection_id_limit
    length = ng.ngtcp2_transport_params_encode(out, _MAX_EARLY_PARAMS, &limits)
    if length < 0:
        raise _native_error(<int>length)
    return length


cdef int _retry_after_accept(Incoming incoming) except -1:
    incoming._decided = False
    incoming.retry()


cdef object _native_error(int rv):
    if rv == ng.NGTCP2_ERR_NOMEM:
        return MemoryError()
    return InternalError(ng.ngtcp2_strerror(rv).decode("ascii", "replace"))


# ngtcp2 and nghttp3 allocate through Python's raw domain, which needs no
# thread state: tracemalloc sees their memory and tests can fail it on demand.
cdef void *_raw_malloc(size_t size, void *user_data) noexcept nogil:
    return PyMem_RawMalloc(size)


cdef void _raw_free(void *ptr, void *user_data) noexcept nogil:
    PyMem_RawFree(ptr)


cdef void *_raw_calloc(size_t nmemb, size_t size, void *user_data) noexcept nogil:
    return PyMem_RawCalloc(nmemb, size)


cdef void *_raw_realloc(void *ptr, size_t size, void *user_data) noexcept nogil:
    return PyMem_RawRealloc(ptr, size)


cdef ng.ngtcp2_mem _MEM = ng.ngtcp2_mem(
    user_data=NULL, malloc=_raw_malloc, free=_raw_free, calloc=_raw_calloc,
    realloc=_raw_realloc,
)


cdef StreamsAvailable _streams_available(ng.ngtcp2_conn *conn):
    cdef StreamsAvailable event = StreamsAvailable.__new__(StreamsAvailable)

    event.bidirectional = ng.ngtcp2_conn_get_streams_bidi_left2(conn)
    event.unidirectional = ng.ngtcp2_conn_get_streams_uni_left2(conn)
    return event


cdef void _random_bytes(uint8_t *dest, size_t length) noexcept:
    ng.glue_random_bytes(dest, length)
