# nghttp3 calls these only from inside the nghttp3 calls H3Connection makes,
# never from nghttp3_conn_del(), so the connection is always live. An
# exception is parked like the QUIC callbacks do and re-raised by the public
# method that drove nghttp3.

cdef inline int _h3_fail(H3Connection connection, object error) noexcept:
    connection._callback_error = error
    return nh.NGHTTP3_ERR_CALLBACK_FAILURE


cdef nh.nghttp3_ssize _read_body(
    nh.nghttp3_conn *conn, int64_t stream_id, nh.nghttp3_vec *vec, size_t veccnt,
    uint32_t *pflags, void *user_data, void *stream_user_data,
) noexcept:
    """Hand nghttp3 queued body chunks; it keeps them until acked_stream_data."""
    cdef _Body stream = <_Body>stream_user_data
    cdef Py_ssize_t count = len(stream.chunks)
    cdef size_t used = 0
    cdef bytes chunk

    while stream.cursor < count and used < veccnt:
        chunk = <bytes>stream.chunks[stream.cursor]
        vec[used].base = <uint8_t *>PyBytes_AS_STRING(chunk) + stream.cursor_pos
        vec[used].len = PyBytes_GET_SIZE(chunk) - stream.cursor_pos
        stream.sent += vec[used].len
        stream.cursor += 1
        stream.cursor_pos = 0
        used += 1
    if stream.cursor == count and stream.fin_queued:
        pflags[0] |= nh.NGHTTP3_DATA_FLAG_EOF
        if stream.trailers:
            pflags[0] |= nh.NGHTTP3_DATA_FLAG_NO_END_STREAM
        stream.fin_sent = True
    elif used == 0:
        return nh.NGHTTP3_ERR_WOULDBLOCK
    return used


cdef nh.nghttp3_data_reader _BODY_READER
_BODY_READER.read_data = _read_body


cdef int _h3_acked_stream_data(
    nh.nghttp3_conn *conn, int64_t stream_id, uint64_t length, void *user_data,
    void *stream_user_data,
) noexcept:
    cdef H3Connection connection = <H3Connection>user_data

    try:
        if stream_user_data != NULL:
            connection._acknowledge(<_Stream>stream_user_data, length)
    except BaseException as error:
        return _h3_fail(connection, error)
    return 0


cdef int _h3_stream_close(
    nh.nghttp3_conn *conn, uint32_t flags, int64_t stream_id, uint64_t rx_error_code,
    uint64_t tx_error_code, void *user_data, void *stream_user_data,
) noexcept:
    cdef H3Connection connection = <H3Connection>user_data

    try:
        connection._streams.pop(stream_id, None)
        connection._receiving.pop(stream_id, None)
        connection._field_section_size.pop(stream_id, None)
        connection._finished.discard(stream_id)
        connection._readable.discard(stream_id)
        connection._credit_blocked.discard(stream_id)
        if stream_id & 0x2:
            return 0
        connection._emit_stream_closed(
            stream_id,
            rx_error_code
            if flags & nh.NGHTTP3_STREAM_CLOSE_FLAG_RX_APP_ERROR_CODE_SET
            else None,
            tx_error_code
            if flags & nh.NGHTTP3_STREAM_CLOSE_FLAG_TX_APP_ERROR_CODE_SET
            else None,
        )
    except BaseException as error:
        return _h3_fail(connection, error)
    return 0


cdef int _h3_recv_data(
    nh.nghttp3_conn *conn, int64_t stream_id, const uint8_t *data, size_t length,
    void *user_data, void *stream_user_data,
) noexcept:
    cdef H3Connection connection = <H3Connection>user_data
    cdef DataReceived event

    try:
        event = DataReceived.__new__(DataReceived)
        event.stream_id = stream_id
        event.data = PyBytes_FromStringAndSize(<const char *>data, length)
        connection._events.append(event)
    except BaseException as error:
        return _h3_fail(connection, error)
    if connection._auto_flow:
        connection._consume(stream_id, length)
    return 0


cdef int _h3_deferred_consume(
    nh.nghttp3_conn *conn, int64_t stream_id, size_t consumed, void *user_data,
    void *stream_user_data,
) noexcept:
    # Bytes QPACK held back until the encoder stream caught up.
    (<H3Connection>user_data)._consume(stream_id, consumed)
    return 0


cdef int _h3_begin_headers(
    nh.nghttp3_conn *conn, int64_t stream_id, void *user_data,
    void *stream_user_data,
) noexcept:
    cdef H3Connection connection = <H3Connection>user_data

    try:
        connection._receiving[stream_id] = []
        if connection._field_section_limit:
            connection._field_section_size[stream_id] = 0
    except BaseException as error:
        return _h3_fail(connection, error)
    return 0


cdef int _h3_recv_header(
    nh.nghttp3_conn *conn, int64_t stream_id, int32_t token,
    nh.nghttp3_rcbuf *name, nh.nghttp3_rcbuf *value, uint8_t flags,
    void *user_data, void *stream_user_data,
) noexcept:
    cdef H3Connection connection = <H3Connection>user_data
    cdef nh.nghttp3_vec name_buf = nh.nghttp3_rcbuf_get_buf(name)
    cdef nh.nghttp3_vec value_buf = nh.nghttp3_rcbuf_get_buf(value)
    cdef list fields
    cdef bytes field_value
    cdef uint64_t size

    try:
        fields = connection._receiving[stream_id]
        if connection._field_section_limit:
            # RFC 9114 4.2.2: name and value bytes plus 32 per field.
            size = connection._field_section_size[stream_id] + (
                name_buf.len + value_buf.len + 32
            )
            if size > connection._field_section_limit:
                connection._violation = nh.NGHTTP3_ERR_H3_EXCESSIVE_LOAD
                return nh.NGHTTP3_ERR_CALLBACK_FAILURE
            connection._field_section_size[stream_id] = size
        field_value = PyBytes_FromStringAndSize(
            <const char *>value_buf.base, value_buf.len
        )
        if token == nh.NGHTTP3_QPACK_TOKEN_HOST and not connection.is_client:
            # RFC 9114 4.3.1, which nghttp3 does not check; pseudo headers
            # come first, so :authority is already here.
            for field_name, authority in fields:
                if field_name == b":authority" and authority != field_value:
                    connection._violation = nh.NGHTTP3_ERR_MALFORMED_HTTP_HEADER
                    return nh.NGHTTP3_ERR_CALLBACK_FAILURE
        field_name = PyBytes_FromStringAndSize(
            <const char *>name_buf.base, name_buf.len
        )
        # Kept, so a proxy that forwards the field forwards it the same way
        # (RFC 9204 7.1.3).
        if flags & nh.NGHTTP3_NV_FLAG_NEVER_INDEX:
            fields.append(NeverIndexedHeader(field_name, field_value))
        else:
            fields.append((field_name, field_value))
    except BaseException as error:
        return _h3_fail(connection, error)
    return 0


cdef int _h3_end_headers(
    nh.nghttp3_conn *conn, int64_t stream_id, int fin, void *user_data,
    void *stream_user_data,
) noexcept:
    cdef H3Connection connection = <H3Connection>user_data
    cdef tuple headers
    cdef object event
    cdef bytes status = b""

    try:
        headers = tuple(connection._receiving.pop(stream_id))
        connection._field_section_size.pop(stream_id, None)
        if not connection.is_client:
            event = RequestReceived.__new__(RequestReceived)
            (<RequestReceived>event).stream_id = stream_id
            (<RequestReceived>event).headers = headers
            (<RequestReceived>event).end_stream = fin
        else:
            for name, value in headers:
                if name == b":status":
                    status = value
                    break
            # nghttp3 already checked :status; 101 is not allowed in HTTP/3.
            if status[:1] == b"1":
                event = InformationalResponseReceived.__new__(
                    InformationalResponseReceived
                )
                (<InformationalResponseReceived>event).stream_id = stream_id
                (<InformationalResponseReceived>event).headers = headers
            else:
                event = ResponseReceived.__new__(ResponseReceived)
                (<ResponseReceived>event).stream_id = stream_id
                (<ResponseReceived>event).headers = headers
                (<ResponseReceived>event).end_stream = fin
        connection._events.append(event)
        if fin:
            connection._finished.add(stream_id)
    except BaseException as error:
        return _h3_fail(connection, error)
    return 0


cdef int _h3_end_trailers(
    nh.nghttp3_conn *conn, int64_t stream_id, int fin, void *user_data,
    void *stream_user_data,
) noexcept:
    cdef H3Connection connection = <H3Connection>user_data
    cdef TrailersReceived event

    try:
        event = TrailersReceived.__new__(TrailersReceived)
        event.stream_id = stream_id
        event.headers = tuple(connection._receiving.pop(stream_id))
        connection._field_section_size.pop(stream_id, None)
        connection._events.append(event)
        connection._finished.add(stream_id)
    except BaseException as error:
        return _h3_fail(connection, error)
    return 0


cdef int _h3_end_stream(
    nh.nghttp3_conn *conn, int64_t stream_id, void *user_data,
    void *stream_user_data,
) noexcept:
    cdef H3Connection connection = <H3Connection>user_data

    try:
        connection._readable.discard(stream_id)
        connection._emit_end(stream_id)
    except BaseException as error:
        return _h3_fail(connection, error)
    return 0


cdef int _h3_stop_sending(
    nh.nghttp3_conn *conn, int64_t stream_id, uint64_t error_code,
    void *user_data, void *stream_user_data,
) noexcept:
    (<H3Connection>user_data)._shutdown_stream(stream_id, error_code, True, False)
    return 0


cdef int _h3_reset_stream(
    nh.nghttp3_conn *conn, int64_t stream_id, uint64_t error_code,
    void *user_data, void *stream_user_data,
) noexcept:
    (<H3Connection>user_data)._shutdown_stream(stream_id, error_code, False, True)
    if stream_user_data != NULL:
        (<_Stream>stream_user_data).abandon()
    return 0


cdef int _h3_shutdown(nh.nghttp3_conn *conn, int64_t id, void *user_data) noexcept:
    cdef H3Connection connection = <H3Connection>user_data
    cdef GoAwayReceived event

    connection._goaway_received = True
    try:
        event = GoAwayReceived.__new__(GoAwayReceived)
        event.id = id
        connection._events.append(event)
    except BaseException as error:
        return _h3_fail(connection, error)
    return 0


cdef int _h3_recv_settings(
    nh.nghttp3_conn *conn, const nh.nghttp3_proto_settings *settings,
    void *user_data,
) noexcept:
    cdef H3Connection connection = <H3Connection>user_data
    cdef SettingsReceived event

    try:
        connection.remote_settings = H3Settings(
            max_field_section_size=settings.max_field_section_size,
            qpack_max_dtable_capacity=settings.qpack_max_dtable_capacity,
            qpack_blocked_streams=settings.qpack_blocked_streams,
            enable_connect_protocol=bool(settings.enable_connect_protocol),
            h3_datagram=bool(settings.h3_datagram),
        )
        event = SettingsReceived.__new__(SettingsReceived)
        event.settings = connection.remote_settings
        connection._events.append(event)
    except BaseException as error:
        return _h3_fail(connection, error)
    return 0


cdef int _h3_recv_origin(
    nh.nghttp3_conn *conn, const uint8_t *origin, size_t length, void *user_data,
) noexcept:
    cdef H3Connection connection = <H3Connection>user_data

    try:
        connection._origins.append(
            PyBytes_FromStringAndSize(<const char *>origin, length)
        )
    except BaseException as error:
        return _h3_fail(connection, error)
    return 0


cdef int _h3_end_origin(nh.nghttp3_conn *conn, void *user_data) noexcept:
    cdef H3Connection connection = <H3Connection>user_data
    cdef OriginReceived event

    try:
        event = OriginReceived.__new__(OriginReceived)
        event.origins = tuple(connection._origins)
        connection._origins = []
        connection._events.append(event)
    except BaseException as error:
        return _h3_fail(connection, error)
    return 0


cdef void _h3_rand(uint8_t *dest, size_t length) noexcept:
    _random_bytes(dest, length)
