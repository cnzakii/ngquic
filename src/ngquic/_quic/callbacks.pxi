# ngtcp2 calls these while the connection runs read_pkt, writes or timers. An
# exception is parked on the connection and re-raised once control returns.

cdef inline int _fail(BaseConnection connection, object error) noexcept:
    connection._callback_error = error
    return ng.NGTCP2_ERR_CALLBACK_FAILURE


cdef ng.ngtcp2_conn *_get_conn(ng.ngtcp2_crypto_conn_ref *ref) noexcept:
    return (<BaseConnection>ref.user_data)._conn


cdef void _rand(
    uint8_t *dest, size_t length, const ng.ngtcp2_rand_ctx *context,
) noexcept:
    ng.glue_random_bytes(dest, length)


cdef void _write_qlog(
    void *user_data, uint32_t flags, const void *data, size_t length,
) noexcept:
    cdef BaseConnection connection = <BaseConnection>user_data

    if connection._conn == NULL or connection._qlog is None:
        return

    try:
        connection._qlog(
            PyBytes_FromStringAndSize(<const char *>data, length), bool(flags & 1),
        )
    except BaseException as error:
        # A failing writer is not called again, not even for the final notice.
        connection._qlog = None
        connection._callback_error = error


cdef ng.ngtcp2_ssize _write_pkt(
    ng.ngtcp2_conn *conn, ng.ngtcp2_path *path, ng.ngtcp2_pkt_info *info,
    uint8_t *dest, size_t destlen, ng.ngtcp2_tstamp ts, void *user_data,
) noexcept:
    """Fill one packet with DATAGRAMs, then stream data."""
    cdef BaseConnection connection = <BaseConnection>user_data
    cdef ng.ngtcp2_vec vec
    cdef ng.ngtcp2_ssize written
    cdef int accepted
    cdef object item
    cdef bytes payload
    cdef uint32_t datagram_flags = ng.NGTCP2_WRITE_DATAGRAM_FLAG_MORE | (
        ng.NGTCP2_WRITE_DATAGRAM_FLAG_PADDING if connection._padding else 0
    )

    try:
        while True:
            if connection._datagrams:
                item = connection._datagrams[0]
                payload = <bytes>item[1]
                # The path may have shrunk since it was queued (migration).
                if PyBytes_GET_SIZE(payload) > connection._datagram_limit():
                    connection._drop_datagram()
                    continue
                vec.base = <uint8_t *>PyBytes_AS_STRING(payload)
                vec.len = PyBytes_GET_SIZE(payload)
                accepted = 0
                written = ng.ngtcp2_conn_writev_datagram(
                    conn, path, info, dest, destlen, &accepted,
                    datagram_flags,
                    <uint64_t>item[0], &vec, 1, ts,
                )
                if accepted:
                    connection._datagrams.popleft()
                if written == ng.NGTCP2_ERR_WRITE_MORE:
                    continue
                return written
            written = connection._write_stream(path, info, dest, destlen, ts)
            if written != ng.NGTCP2_ERR_WRITE_MORE:
                return written
    except BaseException as error:
        return _fail(connection, error)


cdef int _recv_tx_key(
    ng.ngtcp2_conn *conn, ng.ngtcp2_encryption_level level, void *user_data,
) noexcept:
    cdef BaseConnection connection = <BaseConnection>user_data
    cdef uint8_t context[4]

    try:
        if level == ng.NGTCP2_ENCRYPTION_LEVEL_1RTT and not connection.is_client:
            # A server may send 1-RTT data before the handshake completes.
            return connection._application_keys()
        if level != ng.NGTCP2_ENCRYPTION_LEVEL_HANDSHAKE or connection.is_client:
            return 0
        # The version is negotiated by now (RFC 9368); tickets issued in this
        # connection resume only in it. The server's own setting still names
        # the client's chosen version, against which incoming tickets are
        # checked.
        _put_version(context, ng.ngtcp2_conn_get_negotiated_version2(conn))
        ng.SSL_SESSION_set1_id_context(ng.SSL_get_session(connection._ssl), context, 4)
    except BaseException as error:
        return _fail(connection, error)
    return 0


cdef int _recv_rx_key(
    ng.ngtcp2_conn *conn, ng.ngtcp2_encryption_level level, void *user_data,
) noexcept:
    """Start the stream protocol once a client can read 1-RTT data."""
    cdef BaseConnection connection = <BaseConnection>user_data

    if level != ng.NGTCP2_ENCRYPTION_LEVEL_1RTT:
        return 0

    try:
        return connection._application_keys()
    except BaseException as error:
        return _fail(connection, error)


cdef int _handshake_completed(ng.ngtcp2_conn *conn, void *user_data) noexcept:
    cdef BaseConnection connection = <BaseConnection>user_data
    cdef HandshakeCompleted event

    try:
        connection._state = _ESTABLISHED
        event = HandshakeCompleted.__new__(HandshakeCompleted)
        event.alpn_protocol = connection.alpn_protocol
        event.session_resumed = ng.SSL_session_reused(connection._ssl)
        event.early_data_accepted = ng.SSL_early_data_accepted(connection._ssl)
        connection._events.append(event)
        if not connection.is_client:
            # A server is confirmed on completion (RFC 9001 4.1.2); ngtcp2
            # only calls handshake_confirmed on clients.
            connection._events.append(HandshakeConfirmed.__new__(HandshakeConfirmed))
        if not connection.is_client:
            _issue_token(connection, ng.ngtcp2_conn_get_path2(conn))
        # Some TLS stacks report rejected 0-RTT only now.
        return connection._application_keys()
    except BaseException as error:
        return _fail(connection, error)


cdef int _handshake_confirmed(ng.ngtcp2_conn *conn, void *user_data) noexcept:
    cdef BaseConnection connection = <BaseConnection>user_data

    try:
        connection._events.append(HandshakeConfirmed.__new__(HandshakeConfirmed))
    except BaseException as error:
        return _fail(connection, error)
    return 0


cdef int _stream_open(
    ng.ngtcp2_conn *conn, int64_t stream_id, void *user_data,
) noexcept:
    cdef BaseConnection connection = <BaseConnection>user_data

    try:
        return connection._stream_opened(stream_id)
    except BaseException as error:
        return _fail(connection, error)


cdef int _recv_stream_data(
    ng.ngtcp2_conn *conn, uint32_t flags, int64_t stream_id, uint64_t offset,
    const uint8_t *data, size_t length, void *user_data, void *stream_user_data,
) noexcept:
    cdef BaseConnection connection = <BaseConnection>user_data

    try:
        return connection._stream_data(flags, stream_id, data, length)
    except BaseException as error:
        return _fail(connection, error)


cdef int _acked_stream_data_offset(
    ng.ngtcp2_conn *conn, int64_t stream_id, uint64_t offset, uint64_t length,
    void *user_data, void *stream_user_data,
) noexcept:
    cdef BaseConnection connection = <BaseConnection>user_data

    try:
        return connection._stream_acked(stream_id, length, stream_user_data)
    except BaseException as error:
        return _fail(connection, error)


cdef int _stream_close(
    ng.ngtcp2_conn *conn, uint32_t flags, int64_t stream_id,
    uint64_t rx_error_code, uint64_t tx_error_code, void *user_data,
    void *stream_user_data,
) noexcept:
    cdef BaseConnection connection = <BaseConnection>user_data
    cdef int rv

    try:
        rv = connection._stream_closed(
            flags, stream_id, rx_error_code, tx_error_code, stream_user_data,
        )
    except BaseException as error:
        return _fail(connection, error)
    # A finished peer stream frees its slot under max_streams_*.
    if not ng.ngtcp2_conn_is_local_stream2(conn, stream_id):
        if ng.ngtcp2_is_bidi_stream(stream_id):
            ng.ngtcp2_conn_extend_max_streams_bidi(conn, 1)
        else:
            ng.ngtcp2_conn_extend_max_streams_uni(conn, 1)
    return rv


cdef int _extend_max_remote_streams_bidi(
    ng.ngtcp2_conn *conn, uint64_t max_streams, void *user_data,
) noexcept:
    cdef BaseConnection connection = <BaseConnection>user_data

    try:
        return connection._remote_streams_bidi(max_streams)
    except BaseException as error:
        return _fail(connection, error)


cdef int _stream_reset(
    ng.ngtcp2_conn *conn, int64_t stream_id, uint64_t final_size,
    uint64_t error_code, void *user_data, void *stream_user_data,
) noexcept:
    cdef BaseConnection connection = <BaseConnection>user_data

    try:
        return connection._stream_reset(stream_id, final_size, error_code)
    except BaseException as error:
        return _fail(connection, error)


cdef int _recv_stop_sending(
    ng.ngtcp2_conn *conn, int64_t stream_id, uint64_t error_code,
    void *user_data, void *stream_user_data,
) noexcept:
    cdef BaseConnection connection = <BaseConnection>user_data

    try:
        return connection._stop_sending_received(
            stream_id, error_code, stream_user_data,
        )
    except BaseException as error:
        return _fail(connection, error)


cdef int _extend_max_local_streams(
    ng.ngtcp2_conn *conn, uint64_t max_streams, void *user_data,
) noexcept:
    cdef BaseConnection connection = <BaseConnection>user_data
    cdef list events = connection._events

    try:
        # Both directions often extend together; one event reports both.
        if events and type(events[-1]) is StreamsAvailable:
            events[-1] = _streams_available(conn)
        else:
            events.append(_streams_available(conn))
    except BaseException as error:
        return _fail(connection, error)
    return 0


cdef int _extend_max_stream_data(
    ng.ngtcp2_conn *conn, int64_t stream_id, uint64_t max_data, void *user_data,
    void *stream_user_data,
) noexcept:
    cdef BaseConnection connection = <BaseConnection>user_data

    try:
        return connection._stream_unblocked(stream_id, stream_user_data)
    except BaseException as error:
        return _fail(connection, error)


cdef int _get_new_connection_id(
    ng.ngtcp2_conn *conn, ng.ngtcp2_cid *cid, ng.ngtcp2_stateless_reset_token *token,
    size_t length, void *user_data,
) noexcept:
    cdef BaseConnection connection = <BaseConnection>user_data
    cdef Endpoint endpoint = connection._endpoint

    try:
        while True:
            _random_cid(cid, length)
            key = _cid_key(cid.data, cid.datalen)
            if key not in endpoint._cids:
                break
        if ng.ngtcp2_crypto_generate_stateless_reset_token(
            token.data, <const uint8_t *>PyBytes_AS_STRING(endpoint._secret),
            len(endpoint._secret), cid,
        ) != 0:
            return ng.NGTCP2_ERR_CALLBACK_FAILURE
        endpoint._register(connection, key)
    except BaseException as error:
        return _fail(connection, error)
    return 0


cdef int _remove_connection_id(
    ng.ngtcp2_conn *conn, const ng.ngtcp2_cid *cid, void *user_data,
) noexcept:
    cdef BaseConnection connection = <BaseConnection>user_data
    cdef Endpoint endpoint = connection._endpoint

    try:
        key = _cid_key(cid.data, cid.datalen)
        connection._cid_keys.discard(key)
        if endpoint._cids.get(key) is connection:
            del endpoint._cids[key]
    except BaseException as error:
        return _fail(connection, error)
    return 0


cdef int _dcid_status(
    ng.ngtcp2_conn *conn, ng.ngtcp2_connection_id_status_type kind, uint64_t sequence,
    const ng.ngtcp2_cid *cid, const ng.ngtcp2_stateless_reset_token *token,
    void *user_data,
) noexcept:
    """Track the peer's reset tokens: a stateless reset has no usable DCID."""
    cdef BaseConnection connection = <BaseConnection>user_data
    cdef Endpoint endpoint = connection._endpoint

    if token == NULL:
        return 0
    try:
        key = _cid_key(token.data, ng.NGTCP2_STATELESS_RESET_TOKENLEN)
        if kind == ng.NGTCP2_CONNECTION_ID_STATUS_TYPE_ACTIVATE:
            endpoint._reset_tokens[key] = connection
            connection._reset_keys.add(key)
        else:
            connection._reset_keys.discard(key)
            if endpoint._reset_tokens.get(key) is connection:
                del endpoint._reset_tokens[key]
    except BaseException as error:
        return _fail(connection, error)
    return 0


cdef int _recv_datagram(
    ng.ngtcp2_conn *conn, uint32_t flags, const uint8_t *data, size_t length,
    void *user_data,
) noexcept:
    cdef BaseConnection connection = <BaseConnection>user_data

    try:
        return connection._datagram_received(flags, data, length)
    except BaseException as error:
        return _fail(connection, error)


cdef int _ack_datagram(
    ng.ngtcp2_conn *conn, uint64_t datagram_id, void *user_data,
) noexcept:
    cdef BaseConnection connection = <BaseConnection>user_data
    cdef DatagramAcknowledged event

    try:
        event = DatagramAcknowledged.__new__(DatagramAcknowledged)
        event.datagram_id = datagram_id
        connection._events.append(event)
    except BaseException as error:
        return _fail(connection, error)
    return 0


cdef int _lost_datagram(
    ng.ngtcp2_conn *conn, uint64_t datagram_id, void *user_data,
) noexcept:
    cdef BaseConnection connection = <BaseConnection>user_data
    cdef DatagramLost event

    try:
        event = DatagramLost.__new__(DatagramLost)
        event.datagram_id = datagram_id
        event.sent = True
        connection._events.append(event)
    except BaseException as error:
        return _fail(connection, error)
    return 0


cdef int _recv_new_token(
    ng.ngtcp2_conn *conn, const uint8_t *token, size_t length, void *user_data,
) noexcept:
    cdef BaseConnection connection = <BaseConnection>user_data
    cdef NewTokenReceived event

    try:
        event = NewTokenReceived.__new__(NewTokenReceived)
        event.token = PyBytes_FromStringAndSize(<const char *>token, length)
        connection._events.append(event)
    except BaseException as error:
        return _fail(connection, error)
    return 0


cdef int _recv_stateless_reset(
    ng.ngtcp2_conn *conn, const ng.ngtcp2_pkt_stateless_reset2 *reset, void *user_data,
) noexcept:
    # Only reading a packet calls it, which needs a live connection.
    (<BaseConnection>user_data)._stateless_reset = True
    return 0


cdef int _tls_early_data_rejected(
    ng.ngtcp2_conn *conn, void *user_data,
) noexcept:
    cdef BaseConnection connection = <BaseConnection>user_data

    try:
        connection._events.append(EarlyDataRejected.__new__(EarlyDataRejected))
        return connection._early_data_rejected()
    except BaseException as error:
        return _fail(connection, error)


cdef int _path_event(
    BaseConnection connection, type kind, uint32_t flags, const ng.ngtcp2_path *path,
    int success,
) except -1:
    cdef object event = kind.__new__(kind)

    if kind is PathValidated:
        (<PathValidated>event).local_addr = _from_sockaddr(path.local.addr)
        (<PathValidated>event).remote_addr = _from_sockaddr(path.remote.addr)
        (
            <PathValidated>event
        ).preferred_address = flags & ng.NGTCP2_PATH_VALIDATION_FLAG_PREFERRED_ADDR
        (<PathValidated>event).success = success
    else:
        (<PathValidationStarted>event).local_addr = _from_sockaddr(path.local.addr)
        (<PathValidationStarted>event).remote_addr = _from_sockaddr(path.remote.addr)
        (
            <PathValidationStarted>event
        ).preferred_address = flags & ng.NGTCP2_PATH_VALIDATION_FLAG_PREFERRED_ADDR
    connection._events.append(event)
    return 0


cdef int _begin_path_validation(
    ng.ngtcp2_conn *conn, uint32_t flags, const ng.ngtcp2_path *path,
    const ng.ngtcp2_path *fallback, void *user_data,
) noexcept:
    cdef BaseConnection connection = <BaseConnection>user_data

    try:
        _path_event(connection, PathValidationStarted, flags, path, 0)
    except BaseException as error:
        return _fail(connection, error)
    return 0


cdef int _path_validation(
    ng.ngtcp2_conn *conn, uint32_t flags, const ng.ngtcp2_path *path,
    const ng.ngtcp2_path *fallback, ng.ngtcp2_path_validation_result result,
    void *user_data,
) noexcept:
    cdef BaseConnection connection = <BaseConnection>user_data
    cdef bint validated = result == ng.NGTCP2_PATH_VALIDATION_RESULT_SUCCESS

    try:
        _path_event(connection, PathValidated, flags, path, validated)
        # A client on a new address needs a token for it (RFC 9000 9.3).
        if validated and flags & ng.NGTCP2_PATH_VALIDATION_FLAG_NEW_TOKEN:
            _issue_token(connection, path)
    except BaseException as error:
        return _fail(connection, error)
    return 0


cdef void _issue_token(BaseConnection connection, const ng.ngtcp2_path *path):
    """Send a NEW_TOKEN for the client's address, if the endpoint issues them."""
    cdef Endpoint endpoint = connection._endpoint
    cdef uint8_t token[ng.NGTCP2_CRYPTO_MAX_REGULAR_TOKENLEN + 4]
    cdef uint8_t version[4]
    cdef ng.ngtcp2_ssize token_len

    if not endpoint._issue_tokens:
        return
    _put_version(version, ng.ngtcp2_conn_get_negotiated_version2(connection._conn))
    token_len = ng.ngtcp2_crypto_generate_regular_token2(
        token, <const uint8_t *>PyBytes_AS_STRING(endpoint._secret),
        len(endpoint._secret), path.remote.addr, path.remote.addrlen,
        version, 4, ng.ngtcp2_conn_get_timestamp(connection._conn),
    )
    if token_len > 0:
        ng.ngtcp2_conn_submit_new_token(connection._conn, token, token_len)


cdef int _recv_version_negotiation(
    ng.ngtcp2_conn *conn, const ng.ngtcp2_pkt_hd *hd, const uint32_t *versions,
    size_t count, void *user_data,
) noexcept:
    cdef BaseConnection connection = <BaseConnection>user_data

    try:
        connection._offered_versions = [versions[i] for i in range(count)]
    except BaseException as error:
        return _fail(connection, error)
    return 0


cdef int _select_preferred_addr(
    ng.ngtcp2_conn *conn, ng.ngtcp2_path *dest,
    const ng.ngtcp2_preferred_addr *preferred, void *user_data,
) noexcept:
    """Move to the preferred address of the current address family.

    ngtcp2 prefills ``dest.local`` with the current local address, which stays.
    """
    cdef int family = ng.ngtcp2_conn_get_path2(conn).remote.addr.sa_family

    if family == ng.AF_INET and preferred.ipv4_present:
        memcpy(dest.remote.addr, &preferred.ipv4, sizeof(ng.sockaddr_in))
        dest.remote.addrlen = sizeof(ng.sockaddr_in)
    elif family == ng.AF_INET6 and preferred.ipv6_present:
        memcpy(dest.remote.addr, &preferred.ipv6, sizeof(ng.sockaddr_in6))
        dest.remote.addrlen = sizeof(ng.sockaddr_in6)
    return 0
