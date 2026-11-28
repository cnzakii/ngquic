cdef class Endpoint:
    # Fields and C methods are declared in endpoint.pxd.

    def __init__(self, local_addr, config=None):
        if config is None:
            config = _DEFAULT_ENDPOINT
        elif not isinstance(config, EndpointConfig):
            raise TypeError("config must be an EndpointConfig")
        _to_local_sockaddr(local_addr, &self._local, &self._local_len)
        self._cid_len = <size_t>_uint(
            config.connection_id_length, "connection_id_length", 20,
        )
        if self._cid_len < 8:
            raise ValueError("connection_id_length must be between 8 and 20")
        self._preferred_len = _versions(config.preferred_versions, self._preferred)
        if not self._preferred_len:
            raise ValueError("preferred_versions must not be empty")
        self._available_len = _versions(
            config.preferred_versions
            if config.available_versions is None
            else config.available_versions,
            self._available,
        )
        if config.secret is None:
            self._secret = os.urandom(32)
        elif isinstance(config.secret, bytes) and len(config.secret) >= 32:
            self._secret = config.secret
        else:
            raise ValueError("secret must be at least 32 bytes")
        self._retry_lifetime = _duration(
            config.retry_token_lifetime, "retry_token_lifetime",
        )
        self._token_lifetime = _duration(
            config.new_token_lifetime, "new_token_lifetime",
        )
        self._issue_tokens = config.issue_new_tokens
        self._stateless_reset = config.stateless_reset
        if config.preferred_address is not None:
            _preferred_addr(config.preferred_address, &self._preferred_addr)
            self._has_preferred_addr = True
        self.config = config
        self.local_addr = local_addr
        self._cids = {}
        # Attempts the application still holds; a dropped Incoming leaves.
        self._undecided = WeakValueDictionary()
        self._reset_tokens = {}
        self._connections = set()
        self._stateless = []

    @property
    def connections(self):
        return len(self._connections)

    def connect(
        self, remote_addr, double now, *, TLSContext tls, server_name=None,
        transport=None, session_ticket=None, token=None, local_addr=None,
        version=Version.V1, h3=None,
    ):
        if tls is None or tls._server:
            raise ValueError("tls must be a client TLSContext")
        if tls._check_hostname and server_name is None:
            raise ValueError(
                "server_name is required when tls.check_hostname is enabled"
            )
        version = Version(version)
        # ngtcp2 requires the first flight's version among the preferred ones.
        if version not in self._preferred[:self._preferred_len]:
            raise ValueError(f"version {version!r} is not in preferred_versions")
        return BaseConnection._client(
            _connection_type(h3), self, remote_addr, now,
            tls, server_name, transport, session_ticket, token, local_addr,
            version, h3,
        )

    def receive_datagram(
        self, data, remote_addr, double now, *, local_addr=None, int ecn=0,
    ):
        cdef Py_buffer view
        cdef ng.ngtcp2_tstamp ts = _timestamp(now)
        cdef ng.ngtcp2_addr remote, local
        cdef ng.ngtcp2_sockaddr_union remote_native, local_native
        cdef ng.ngtcp2_socklen remote_len

        if remote_addr is not self._remote_key and remote_addr != self._remote_key:
            # Committed together, so a rejected address leaves the cache whole.
            _to_sockaddr(remote_addr, &remote_native, &remote_len)
            self._remote = remote_native
            self._remote_len = remote_len
            self._remote_key = remote_addr
        remote.addr = &self._remote.sa
        remote.addrlen = self._remote_len
        if local_addr is not None:
            _to_local_sockaddr(local_addr, &local_native, &local.addrlen)
            local.addr = &local_native.sa

        PyObject_GetBuffer(data, &view, PyBUF_CONTIG_RO)
        try:
            return self._receive(
                <const uint8_t *>view.buf, view.len, &remote, remote_addr,
                NULL if local_addr is None else &local, local_addr, <uint8_t>ecn,
                ts,
            )
        finally:
            PyBuffer_Release(&view)

    def datagrams_to_send(self):
        result = self._stateless
        self._stateless = []
        return result

    cdef object _receive(
        self, const uint8_t *packet, size_t length, const ng.ngtcp2_addr *remote,
        object remote_addr, const ng.ngtcp2_addr *local, object local_addr,
        uint8_t ecn, ng.ngtcp2_tstamp ts,
    ):
        """Process one UDP payload; a NULL ``local`` is the endpoint's address.

        The entry point for native modules that read datagrams themselves,
        so it takes addresses as the system reports them.
        """
        cdef ng.ngtcp2_path path
        cdef ng.ngtcp2_sockaddr_union remote_copy, local_copy

        memcpy(&remote_copy, remote.addr, remote.addrlen)
        ng.glue_clear_sa_len(&remote_copy.sa)
        path.remote.addr = &remote_copy.sa
        path.remote.addrlen = remote.addrlen
        if local == NULL:
            path.local.addr = &self._local.sa
            path.local.addrlen = self._local_len
            local_addr = self.local_addr
        else:
            memcpy(&local_copy, local.addr, local.addrlen)
            ng.glue_clear_sa_len(&local_copy.sa)
            path.local.addr = &local_copy.sa
            path.local.addrlen = local.addrlen
        path.user_data = NULL
        return self._process(packet, length, &path, remote_addr, local_addr, ecn, ts)

    cdef object _process(
        self, const uint8_t *packet, size_t length, ng.ngtcp2_path *path,
        object remote_addr, object local_addr, uint8_t ecn, ng.ngtcp2_tstamp ts,
    ):
        cdef ng.ngtcp2_version_cid vc
        cdef ng.ngtcp2_pkt_hd hd
        cdef int rv = ng.ngtcp2_pkt_decode_version_cid(
            &vc, packet, length, self._cid_len,
        )
        cdef bytes key
        cdef object connection, incoming

        if rv == ng.NGTCP2_ERR_VERSION_NEGOTIATION:
            self._send_version_negotiation(&vc, remote_addr, local_addr)
            return None
        if rv != 0:
            return None
        key = _cid_key(vc.dcid, vc.dcidlen)
        connection = self._cids.get(key)
        if connection is not None:
            return self._deliver(
                <BaseConnection>connection, packet, length, path, ecn, ts,
            )
        incoming = self._undecided.get(key)
        if incoming is not None:
            # accept() replays these on the first datagram's path, whose
            # amplification limit a datagram from elsewhere must not raise.
            if (
                len((<Incoming>incoming)._extra) < _MAX_HELD_DATAGRAMS
                and remote_addr == (<Incoming>incoming).remote_addr
            ):
                (<Incoming>incoming)._extra.append(
                    PyBytes_FromStringAndSize(<const char *>packet, length)
                )
            return None
        if packet[0] & 0x80:
            if vc.version == 0:
                return None
            if not self._accepts(vc.version):
                # Only for datagrams that could start a connection (RFC 9000 5.2.2).
                if length >= <size_t>ng.NGTCP2_MAX_UDP_PAYLOAD_SIZE:
                    self._send_version_negotiation(&vc, remote_addr, local_addr)
                return None
            if ng.ngtcp2_accept(&hd, packet, length) != 0:
                return None
            return self._incoming(
                &hd, key, packet, length, path, remote_addr, local_addr, ecn, ts,
            )
        if length >= <size_t>ng.NGTCP2_STATELESS_RESET_TOKENLEN + 5:
            connection = self._reset_tokens.get(_cid_key(
                packet + length - ng.NGTCP2_STATELESS_RESET_TOKENLEN,
                ng.NGTCP2_STATELESS_RESET_TOKENLEN,
            ))
            if connection is not None:
                return self._deliver(
                    <BaseConnection>connection, packet, length, path, ecn, ts,
                )
        if self._stateless_reset:
            self._send_stateless_reset(&vc, length, remote_addr, local_addr)
        return None

    cdef BaseConnection _deliver(
        self, BaseConnection connection, const uint8_t *packet, size_t length,
        ng.ngtcp2_path *path, uint8_t ecn, ng.ngtcp2_tstamp ts,
    ):
        """Pass a datagram to ``connection``.

        A failure while it handles the datagram, such as a protocol callback
        failing and dropping it, waits for its next ``events()``, so the
        caller learns which connection failed and the others go on.
        """
        try:
            connection._receive(packet, length, path, ecn, ts)
        except Exception as error:
            connection._deferred_error = error
        return connection

    cdef Incoming _incoming(
        self, ng.ngtcp2_pkt_hd *hd, bytes key, const uint8_t *packet, size_t length,
        ng.ngtcp2_path *path, object remote_addr, object local_addr, uint8_t ecn,
        ng.ngtcp2_tstamp ts,
    ):
        cdef Incoming incoming = Incoming.__new__(Incoming)
        cdef uint8_t magic
        cdef uint8_t issued_in[4]

        incoming._endpoint = self
        incoming._hd = hd[0]
        incoming._dcid_key = key
        incoming._datagram = PyBytes_FromStringAndSize(<const char *>packet, length)
        incoming._extra = []
        memcpy(&incoming._remote, path.remote.addr, path.remote.addrlen)
        incoming._remote_len = path.remote.addrlen
        memcpy(&incoming._local, path.local.addr, path.local.addrlen)
        incoming._local_len = path.local.addrlen
        incoming.remote_addr = remote_addr
        incoming.local_addr = local_addr
        incoming.version = Version(hd.version)
        incoming._ecn = ecn
        incoming._ts = ts
        incoming._token = b""
        incoming._token_type = ng.NGTCP2_TOKEN_TYPE_UNKNOWN
        incoming.remote_address_validated = False

        if hd.tokenlen:
            magic = hd.token[0]
            if magic == ng.NGTCP2_CRYPTO_TOKEN_MAGIC_RETRY2:
                if ng.ngtcp2_crypto_verify_retry_token2(
                    &incoming._odcid, hd.token, hd.tokenlen,
                    <const uint8_t *>PyBytes_AS_STRING(self._secret), len(self._secret),
                    hd.version, path.remote.addr, path.remote.addrlen, &hd.dcid,
                    self._retry_lifetime, ts,
                ) != 0:
                    self._refuse(hd, ErrorCode.INVALID_TOKEN, remote_addr, local_addr)
                    return None
                incoming._token_type = ng.NGTCP2_TOKEN_TYPE_RETRY
            elif (
                magic == ng.NGTCP2_CRYPTO_TOKEN_MAGIC_REGULAR
                and ng.ngtcp2_crypto_verify_regular_token2(
                    issued_in, 4, hd.token, hd.tokenlen,
                    <const uint8_t *>PyBytes_AS_STRING(self._secret), len(self._secret),
                    path.remote.addr, path.remote.addrlen, self._token_lifetime, ts,
                ) == 4
                and _get_version(issued_in) == hd.version
            ):
                incoming._token_type = ng.NGTCP2_TOKEN_TYPE_NEW_TOKEN
            if incoming._token_type != ng.NGTCP2_TOKEN_TYPE_UNKNOWN:
                incoming._token = PyBytes_FromStringAndSize(
                    <const char *>hd.token, hd.tokenlen,
                )
                incoming.remote_address_validated = True
        incoming._hd.token = NULL
        incoming._hd.tokenlen = 0
        self._undecided[key] = incoming
        return incoming

    cdef bint _accepts(self, uint32_t version):
        cdef size_t i

        for i in range(self._available_len):
            if self._available[i] == version:
                return True
        return False

    cdef int _send_version_negotiation(
        self, ng.ngtcp2_version_cid *vc, object remote_addr, object local_addr,
    ) except -1:
        cdef uint8_t buffer[256]
        cdef uint8_t unused
        cdef ng.ngtcp2_ssize written

        ng.glue_random_bytes(&unused, 1)
        written = ng.ngtcp2_pkt_write_version_negotiation(
            buffer, sizeof(buffer), unused, vc.scid, vc.scidlen, vc.dcid,
            vc.dcidlen, self._available, self._available_len,
        )
        if written > 0:
            self._queue(buffer, written, remote_addr, local_addr)

    cdef int _send_stateless_reset(
        self, ng.ngtcp2_version_cid *vc, size_t received, object remote_addr,
        object local_addr,
    ) except -1:
        cdef ng.ngtcp2_cid cid
        cdef ng.ngtcp2_stateless_reset_token token
        cdef uint8_t random[64]
        cdef uint8_t buffer[64]
        cdef size_t random_len
        cdef ng.ngtcp2_ssize written

        # A reset must be shorter than what triggered it so two endpoints
        # cannot reset each other forever (RFC 9000, section 10.3.3).
        if received < self._cid_len + 22:
            return 0
        random_len = min(received - ng.NGTCP2_STATELESS_RESET_TOKENLEN - 2, 26)
        cid.datalen = vc.dcidlen
        memcpy(cid.data, vc.dcid, vc.dcidlen)
        if ng.ngtcp2_crypto_generate_stateless_reset_token(
            token.data, <const uint8_t *>PyBytes_AS_STRING(self._secret),
            len(self._secret), &cid,
        ) != 0:
            return 0
        ng.glue_random_bytes(random, random_len)
        written = ng.ngtcp2_pkt_write_stateless_reset2(
            buffer, sizeof(buffer), &token, random, random_len,
        )
        if written > 0:
            self._queue(buffer, written, remote_addr, local_addr)

    cdef int _refuse(
        self, ng.ngtcp2_pkt_hd *hd, uint64_t error_code, object remote_addr,
        object local_addr,
    ) except -1:
        cdef uint8_t buffer[ng.NGTCP2_MAX_UDP_PAYLOAD_SIZE]
        cdef ng.ngtcp2_ssize written = ng.ngtcp2_crypto_write_connection_close(
            buffer, sizeof(buffer), hd.version, &hd.scid, &hd.dcid, error_code,
            NULL, 0,
        )

        if written > 0:
            self._queue(buffer, written, remote_addr, local_addr)

    cdef int _queue(
        self, const uint8_t *data, Py_ssize_t length, object remote_addr,
        object local_addr,
    ) except -1:
        self._stateless.append(_transmit(
            PyBytes_FromStringAndSize(<const char *>data, length),
            remote_addr, local_addr, length, 0,
        ))

    cdef int _register(self, BaseConnection connection, bytes key) except -1:
        # Tracked first, so a failure never leaves a route _unregister misses.
        connection._cid_keys.add(key)
        self._cids[key] = connection

    cdef void _unregister(self, BaseConnection connection):
        for key in connection._cid_keys:
            if self._cids.get(key) is connection:
                del self._cids[key]
        connection._cid_keys.clear()
        for key in connection._reset_keys:
            if self._reset_tokens.get(key) is connection:
                del self._reset_tokens[key]
        connection._reset_keys.clear()
        self._connections.discard(connection)


cdef class Incoming:
    # Fields and C methods are declared in endpoint.pxd.

    def __init__(self):
        raise TypeError("Incoming objects come from Endpoint.receive_datagram()")

    def accept(self, *, TLSContext tls, transport=None, h3=None):
        self._decide()
        if tls is None or not tls._server:
            raise ValueError("tls must be a server TLSContext")
        return BaseConnection._server(_connection_type(h3), self, tls, transport, h3)

    def retry(self):
        cdef ng.ngtcp2_cid scid
        cdef uint8_t token[ng.NGTCP2_CRYPTO_MAX_RETRY_TOKENLEN2]
        cdef uint8_t buffer[ng.NGTCP2_MAX_UDP_PAYLOAD_SIZE]
        cdef ng.ngtcp2_ssize token_len, written
        cdef Endpoint endpoint = self._endpoint

        self._decide()
        _random_cid(&scid, endpoint._cid_len)
        token_len = ng.ngtcp2_crypto_generate_retry_token2(
            token, <const uint8_t *>PyBytes_AS_STRING(endpoint._secret),
            len(endpoint._secret), self._hd.version, &self._remote.sa,
            self._remote_len, &scid, &self._hd.dcid, self._ts,
        )
        if token_len < 0:
            raise InternalError("cannot generate a Retry token")
        written = ng.ngtcp2_crypto_write_retry(
            buffer, min(sizeof(buffer), 3 * len(self._datagram)), self._hd.version,
            &self._hd.scid, &scid, &self._hd.dcid, token, token_len,
        )
        if written > 0:
            endpoint._queue(buffer, written, self.remote_addr, self.local_addr)

    def refuse(self, error_code=ErrorCode.CONNECTION_REFUSED):
        cdef uint64_t code = _uint(error_code, "error_code", _MAX_VARINT)

        self._decide()
        self._endpoint._refuse(&self._hd, code, self.remote_addr, self.local_addr)

    def ignore(self):
        self._decide()

    cdef int _decide(self) except -1:
        if self._decided:
            raise ConnectionStateError("this connection attempt was already decided")
        self._decided = True
        self._endpoint._undecided.pop(self._dcid_key, None)

    def __repr__(self):
        return (
            f"Incoming(remote_addr={self.remote_addr!r}, version={self.version!r}, "
            f"remote_address_validated={self.remote_address_validated})"
        )


cdef type _connection_type(object h3):
    if h3 is None:
        return Connection
    # Imported on use: ngquic.h3 builds on this module.
    from .h3 import H3Connection
    return H3Connection


cdef size_t _versions(object versions, uint32_t *out) except? 0:
    cdef size_t count = 0

    for version in versions:
        if count == _MAX_VERSIONS:
            raise ValueError(f"at most {_MAX_VERSIONS} versions are supported")
        out[count] = Version(version)
        count += 1
    return count


cdef int _preferred_addr(object value, ng.ngtcp2_preferred_addr *out) except -1:
    """Fill the addresses of a server's preferred_address transport parameter."""
    cdef ng.ngtcp2_sockaddr_union address
    cdef ng.ngtcp2_socklen length

    if not isinstance(value, PreferredAddress):
        raise TypeError("preferred_address must be a PreferredAddress")
    if value.ipv4 is None and value.ipv6 is None:
        raise ValueError("preferred_address needs an IPv4 or IPv6 address")
    memset(out, 0, sizeof(ng.ngtcp2_preferred_addr))
    if value.ipv4 is not None:
        _to_sockaddr(value.ipv4, &address, &length)
        if address.sa.sa_family != ng.AF_INET:
            raise ValueError("preferred_address.ipv4 must be an IPv4 address")
        memcpy(&out.ipv4, &address.in4, sizeof(ng.sockaddr_in))
        out.ipv4_present = 1
    if value.ipv6 is not None:
        _to_sockaddr(value.ipv6, &address, &length)
        if address.sa.sa_family != ng.AF_INET6:
            raise ValueError("preferred_address.ipv6 must be an IPv6 address")
        memcpy(&out.ipv6, &address.in6, sizeof(ng.sockaddr_in6))
        out.ipv6_present = 1
