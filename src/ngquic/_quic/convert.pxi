cdef inline ng.ngtcp2_tstamp _timestamp(double now) except? 0:
    """Convert a monotonic time in seconds to an ngtcp2 timestamp."""
    if not (0.0 <= now < 1.8e10):
        raise ValueError("now must be a non-negative monotonic time in seconds")
    # Round, not truncate; with _deadline() this maps get_timer() back to the
    # exact expiry, or ngtcp2 would see the timer as not yet due.
    return <ng.ngtcp2_tstamp>(now * _NANOSECONDS + 0.5)


cdef double _deadline(uint64_t value) except? 0:
    """Return the earliest seconds that convert back to ``value`` or later.

    Far from the epoch of the caller's clock a float's step exceeds a
    nanosecond, so a rounded deadline handed back to ``handle_timer()`` could
    still be before it and the timer would never fire.
    """
    cdef double seconds = value / _NANOSECONDS

    while _timestamp(seconds) < value:
        seconds = nextafter(seconds, INFINITY)
    return seconds


cdef inline double _seconds(uint64_t value):
    return value / _NANOSECONDS


cdef ng.ngtcp2_duration _duration(object value, str name) except? 0:
    """Convert a non-negative duration in seconds to nanoseconds."""
    cdef double seconds = value

    if not (0.0 <= seconds < 1.8e10):
        raise ValueError(f"{name} must be a non-negative number of seconds")
    return <ng.ngtcp2_duration>(seconds * _NANOSECONDS + 0.5)


cdef ng.ngtcp2_duration _timeout(object value, str name) except? 0:
    """A positive duration, or ``None`` for none, which is 0 here."""
    if value is None:
        return 0
    if _duration(value, name) == 0:
        raise ValueError(f"{name} must be positive; None disables it")
    return _duration(value, name)


cdef uint64_t _limit(object value, str name, uint64_t maximum) except? 0:
    """A positive bound, or ``None`` for none, which is 0 here."""
    if value is None:
        return 0
    if _uint(value, name, maximum) == 0:
        raise ValueError(f"{name} must be positive; None disables it")
    return value


cdef uint64_t _uint(object value, str name, uint64_t maximum) except? 0:
    """Validate an integer in ``[0, maximum]``."""
    if value is True or value is False or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if not 0 <= value <= maximum:
        raise ValueError(f"{name} must be between 0 and {maximum}")
    return value


cdef int64_t _stream_id(object value) except -1:
    return <int64_t>_uint(value, "stream_id", _MAX_VARINT)


cdef bytes _reason_bytes(object reason):
    if not isinstance(reason, bytes):
        raise TypeError("reason must be bytes")
    if len(reason) > _MAX_REASON_LENGTH:
        raise ValueError(f"reason must be at most {_MAX_REASON_LENGTH} bytes")
    return reason


cdef bytes _owned_bytes(object data):
    """Return immutable bytes for data the connection must hold until acknowledged."""
    if PyBytes_CheckExact(data):
        return <bytes>data
    # bytearray and memoryview can change after the call; keep a snapshot.
    return bytes(memoryview(data))


cdef int _to_sockaddr(
    object address, ng.ngtcp2_sockaddr_union *out, ng.ngtcp2_socklen *outlen,
) except -1:
    """Convert an ``(host, port)`` or ``(host, port, flowinfo, scope_id)`` tuple."""
    cdef bytes host
    cdef object port

    if not isinstance(address, tuple) or len(address) not in (2, 4):
        raise TypeError(
            "address must be an (host, port) or (host, port, flowinfo, scope_id) tuple"
        )
    if not isinstance(address[0], str):
        raise TypeError("address host must be a str")
    port = address[1]
    _uint(port, "address port", 65535)
    # A scope suffix such as "%eth0" is carried by scope_id instead.
    host = (<str>address[0]).partition("%")[0].encode("ascii", "replace")
    memset(out, 0, sizeof(ng.ngtcp2_sockaddr_union))
    if ng.inet_pton(ng.AF_INET, host, &out.in4.sin_addr) == 1:
        out.in4.sin_family = ng.AF_INET
        out.in4.sin_port = ng.htons(<uint16_t>port)
        outlen[0] = sizeof(ng.sockaddr_in)
        return 0
    if ng.inet_pton(ng.AF_INET6, host, &out.in6.sin6_addr) == 1:
        out.in6.sin6_family = ng.AF_INET6
        out.in6.sin6_port = ng.htons(<uint16_t>port)
        if len(address) == 4:
            out.in6.sin6_flowinfo = ng.htonl(
                <uint32_t>_uint(address[2], "address flowinfo", 0xFFFFFFFF)
            )
            out.in6.sin6_scope_id = <uint32_t>_uint(
                address[3], "address scope_id", 0xFFFFFFFF,
            )
        outlen[0] = sizeof(ng.sockaddr_in6)
        return 0
    raise ValueError("address host must be an IPv4 or IPv6 address")


cdef object _from_sockaddr(const ng.ngtcp2_sockaddr *address):
    cdef char text[64]
    cdef const ng.sockaddr_in *v4
    cdef const ng.sockaddr_in6 *v6

    if address.sa_family == ng.AF_INET:
        v4 = <const ng.sockaddr_in *>address
        ng.inet_ntop(ng.AF_INET, &v4.sin_addr, text, sizeof(text))
        return (text.decode("ascii"), ng.ntohs(v4.sin_port))
    v6 = <const ng.sockaddr_in6 *>address
    ng.inet_ntop(ng.AF_INET6, &v6.sin6_addr, text, sizeof(text))
    return (
        text.decode("ascii"),
        ng.ntohs(v6.sin6_port),
        ng.ntohl(v6.sin6_flowinfo),
        v6.sin6_scope_id,
    )


cdef class _AddressCache:
    """Remember the tuple form of the last native address seen."""

    # Fields and C methods are declared in convert.pxd.

    cdef object get(self, const ng.ngtcp2_addr *address):
        if (
            self.value is None
            or address.addrlen != self.length
            or memcmp(address.addr, &self.native, address.addrlen) != 0
        ):
            memcpy(&self.native, address.addr, address.addrlen)
            self.length = address.addrlen
            self.value = _from_sockaddr(address.addr)
        return self.value


cdef inline bytes _cid_key(const uint8_t *data, size_t length):
    return PyBytes_FromStringAndSize(<const char *>data, length)


cdef void _random_cid(ng.ngtcp2_cid *cid, size_t length) noexcept:
    cid.datalen = length
    ng.glue_random_bytes(cid.data, length)


# Session tickets and NEW_TOKEN tokens carry the QUIC version that issued them,
# and the server accepts them only in that version (RFC 9369 section 5).
cdef inline void _put_version(uint8_t *out, uint32_t version) noexcept:
    out[0] = version >> 24
    out[1] = version >> 16
    out[2] = version >> 8
    out[3] = version


cdef inline uint32_t _get_version(const uint8_t *data) noexcept:
    return (
        (<uint32_t>data[0] << 24) | (<uint32_t>data[1] << 16)
        | (<uint32_t>data[2] << 8) | data[3]
    )


cdef void _accept_tickets_from(ng.SSL *ssl, uint32_t version) noexcept:
    cdef uint8_t context[4]

    _put_version(context, version)
    ng.SSL_set_session_id_context(ssl, context, 4)


cdef object _tls_error(str message):
    """Return a TLSError carrying the most recent AWS-LC error."""
    cdef unsigned long code = ng.ERR_peek_last_error()
    cdef char text[256]

    ng.ERR_clear_error()
    if code == 0:
        return TLSError(message)
    ng.ERR_error_string_n(code, text, sizeof(text))
    return TLSError(f"{message}: {text.decode('utf-8', 'replace')}")


cdef object _error_code(uint64_t value, bint transport):
    if transport:
        return _ERROR_CODES.get(value, value)
    return value
