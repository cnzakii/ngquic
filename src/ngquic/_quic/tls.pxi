cdef class TLSContext:
    # Fields and C methods are declared in tls.pxd.

    def __cinit__(self):
        self._ctx = NULL
        self._alpn = b""

    def __init__(self, role):
        if not isinstance(role, Role):
            raise TypeError("role must be a Role")
        self.role = role
        self._server = role is Role.SERVER
        self._ctx = ng.SSL_CTX_new(
            ng.TLS_server_method() if self._server else ng.TLS_client_method()
        )
        if self._ctx == NULL:
            raise _tls_error("cannot create TLS context")
        if self._server:
            ng.ngtcp2_crypto_boringssl_configure_server_context(self._ctx)
            ng.SSL_CTX_set_alpn_select_cb(self._ctx, _select_alpn, <void *>self)
        else:
            ng.ngtcp2_crypto_boringssl_configure_client_context(self._ctx)
            ng.SSL_CTX_set_session_cache_mode(
                self._ctx, ng.SSL_SESS_CACHE_CLIENT | ng.SSL_SESS_CACHE_NO_INTERNAL,
            )
            ng.SSL_CTX_sess_set_new_cb(self._ctx, _new_session)
        ng.SSL_CTX_set_app_data(self._ctx, <void *>self)
        self._check_hostname = not self._server
        self.verify_mode = CERT_NONE if self._server else CERT_REQUIRED

    def __dealloc__(self):
        if self._ctx != NULL:
            ng.SSL_CTX_free(self._ctx)

    @property
    def verify_mode(self):
        return self._verify_mode

    @verify_mode.setter
    def verify_mode(self, value):
        cdef int flags

        value = VerifyMode(value)
        if value == CERT_NONE and self._check_hostname:
            raise ValueError(
                "Cannot set verify_mode to CERT_NONE when check_hostname is enabled"
            )
        if value == CERT_NONE:
            flags = ng.SSL_VERIFY_NONE
        elif value == CERT_OPTIONAL and self._server:
            flags = ng.SSL_VERIFY_PEER
        else:
            flags = ng.SSL_VERIFY_PEER | ng.SSL_VERIFY_FAIL_IF_NO_PEER_CERT
        ng.SSL_CTX_set_verify(self._ctx, flags, NULL)
        ng.SSL_CTX_set_custom_verify(
            self._ctx, flags,
            _verify_peer if self._defer_verification
            else <ng.glue_custom_verify_cb>NULL,
        )
        self._verify_mode = value

    @property
    def check_hostname(self):
        return self._check_hostname

    @check_hostname.setter
    def check_hostname(self, bint value):
        if value and self._defer_verification:
            raise ValueError(
                "Cannot enable check_hostname while peer verification is deferred"
            )
        if value and self._verify_mode == CERT_NONE:
            self.verify_mode = CERT_REQUIRED
        self._check_hostname = value

    @property
    def keylog_filename(self):
        return self._keylog_filename

    @keylog_filename.setter
    def keylog_filename(self, value):
        if value is None:
            ng.SSL_CTX_set_keylog_callback(self._ctx, NULL)
        else:
            # Fail here, not silently in the handshake, if it cannot be written.
            open(value, "a").close()
            ng.SSL_CTX_set_keylog_callback(self._ctx, _write_keylog)
        self._keylog_filename = value

    @property
    def early_data(self):
        return self._early_data

    @early_data.setter
    def early_data(self, bint value):
        if not self._server:
            raise ValueError("early_data applies to server contexts")
        self._early_data = value

    @property
    def num_tickets(self):
        return ng.SSL_CTX_get_num_tickets(self._ctx)

    @num_tickets.setter
    def num_tickets(self, value):
        if not self._server:
            raise ValueError("num_tickets applies to server contexts")
        ng.SSL_CTX_set_num_tickets(self._ctx, <size_t>_uint(value, "num_tickets", 16))

    @property
    def defer_certificate_selection(self):
        return self._defer_selection

    @defer_certificate_selection.setter
    def defer_certificate_selection(self, bint value):
        if not self._server:
            raise ValueError("defer_certificate_selection applies to server contexts")
        if value:
            ng.SSL_CTX_set_cert_cb(self._ctx, _select_certificate, NULL)
            ng.SSL_CTX_set_select_certificate_cb(self._ctx, _read_client_hello)
        else:
            ng.SSL_CTX_set_cert_cb(self._ctx, NULL, NULL)
            ng.SSL_CTX_set_select_certificate_cb(self._ctx, NULL)
        self._defer_selection = value

    @property
    def defer_peer_verification(self):
        return self._defer_verification

    @defer_peer_verification.setter
    def defer_peer_verification(self, bint value):
        if value and self._check_hostname:
            raise ValueError(
                "Cannot defer peer verification when check_hostname is enabled"
            )
        self._defer_verification = value
        self.verify_mode = self._verify_mode

    def load_cert_chain(self, certfile, keyfile=None, password=None):
        cdef bytes cert_path = os.fsencode(certfile)
        cdef bytes key_path = os.fsencode(certfile if keyfile is None else keyfile)
        cdef bytes secret = None

        if password is not None:
            secret = password.encode() if isinstance(password, str) else bytes(password)
            ng.SSL_CTX_set_default_passwd_cb_userdata(self._ctx, <char *>secret)
        try:
            ng.ERR_clear_error()
            if ng.SSL_CTX_use_certificate_chain_file(self._ctx, cert_path) != 1:
                raise _tls_error("cannot load certificate chain")
            # This also rejects a key that does not match the certificate.
            if ng.SSL_CTX_use_PrivateKey_file(
                self._ctx, key_path, ng.X509_FILETYPE_PEM,
            ) != 1:
                raise _tls_error("cannot load private key")
        finally:
            if secret is not None:
                ng.SSL_CTX_set_default_passwd_cb_userdata(self._ctx, NULL)

    def load_verify_locations(self, cafile=None, capath=None, cadata=None):
        cdef bytes file_path = None if cafile is None else os.fsencode(cafile)
        cdef bytes dir_path = None if capath is None else os.fsencode(capath)

        if cafile is None and capath is None and cadata is None:
            raise TypeError("cafile, capath or cadata must be given")
        ng.ERR_clear_error()
        if cafile is not None or capath is not None:
            if ng.SSL_CTX_load_verify_locations(
                self._ctx,
                NULL if file_path is None else <char *>file_path,
                NULL if dir_path is None else <char *>dir_path,
            ) != 1:
                raise _tls_error("cannot load verify locations")
        if cadata is not None:
            if isinstance(cadata, str):
                self._add_pem(cadata.encode("ascii"))
            else:
                self._add_der(bytes(cadata))

    def load_default_certs(self, purpose=Purpose.SERVER_AUTH):
        if not isinstance(purpose, Purpose):
            raise TypeError("purpose must be an ssl.Purpose")
        if sys.platform == "win32":
            from ssl import enum_certificates

            for store in ("CA", "ROOT"):
                try:
                    certificates = enum_certificates(store)
                except PermissionError:
                    warnings.warn("unable to enumerate Windows certificate store")
                    continue
                for der, encoding, trust in certificates:
                    if encoding == "x509_asn" and (
                        trust is True or purpose.oid in trust
                    ):
                        try:
                            self._add_der(der)
                        except TLSError as error:
                            warnings.warn(
                                f"Bad certificate in Windows certificate store: {error}"
                            )
        self.set_default_verify_paths()

    def set_default_verify_paths(self):
        cdef object paths = get_default_verify_paths()

        if paths.cafile is not None or paths.capath is not None:
            self.load_verify_locations(paths.cafile, paths.capath)

    def set_alpn_protocols(self, protocols):
        cdef list parts = []

        for protocol in protocols:
            encoded = protocol.encode("ascii")
            if not 0 < len(encoded) < 256:
                raise ValueError("ALPN protocols must be 1 to 255 bytes")
            parts.append(bytes((len(encoded),)) + encoded)
        if not parts:
            raise ValueError("at least one ALPN protocol is required")
        self._alpn = b"".join(parts)

    def set_groups(self, groups):
        cdef bytes names = ":".join(groups).encode("ascii")

        ng.ERR_clear_error()
        if ng.SSL_CTX_set1_groups_list(self._ctx, names) != 1:
            raise _tls_error("cannot set key exchange groups")

    cdef int _add_pem(self, bytes data) except -1:
        cdef ng.BIO *bio = ng.BIO_new_mem_buf(PyBytes_AS_STRING(data), len(data))
        cdef ng.X509 *certificate
        cdef int count = 0

        if bio == NULL:
            raise MemoryError()
        try:
            while True:
                certificate = ng.PEM_read_bio_X509(bio, NULL, NULL, NULL)
                if certificate == NULL:
                    break
                ng.X509_STORE_add_cert(
                    ng.SSL_CTX_get_cert_store(self._ctx), certificate,
                )
                ng.X509_free(certificate)
                count += 1
        finally:
            ng.BIO_free(bio)
        ng.ERR_clear_error()
        if count == 0:
            raise TLSError("cadata contains no PEM certificate")

    cdef int _add_der(self, bytes data) except -1:
        cdef const uint8_t *cursor = <const uint8_t *>PyBytes_AS_STRING(data)
        cdef const uint8_t *end = cursor + len(data)
        cdef ng.X509 *certificate

        while cursor < end:
            certificate = ng.d2i_X509(NULL, &cursor, end - cursor)
            if certificate == NULL:
                raise _tls_error("cadata is not DER certificates")
            ng.X509_STORE_add_cert(ng.SSL_CTX_get_cert_store(self._ctx), certificate)
            ng.X509_free(certificate)


cdef int _select_alpn(
    ng.SSL *ssl, const uint8_t **out, uint8_t *out_len,
    const uint8_t *offered, unsigned int offered_len, void *arg,
) noexcept:
    """Pick the server's most preferred protocol that the client offers."""
    cdef TLSContext context = <TLSContext>arg
    cdef const uint8_t *ours = <const uint8_t *>PyBytes_AS_STRING(context._alpn)
    cdef size_t ours_len = PyBytes_GET_SIZE(context._alpn)
    cdef size_t i = 0, j
    cdef uint8_t length

    while i < ours_len:
        length = ours[i]
        j = 0
        while j < offered_len:
            if offered[j] == length and j + 1 + length <= offered_len and memcmp(
                offered + j + 1, ours + i + 1, length,
            ) == 0:
                out[0] = offered + j + 1
                out_len[0] = length
                return ng.SSL_TLSEXT_ERR_OK
            j += 1 + offered[j]
        i += 1 + length
    return ng.SSL_TLSEXT_ERR_ALERT_FATAL


cdef void _write_keylog(const ng.SSL *ssl, const char *line) noexcept:
    cdef TLSContext context = <TLSContext>ng.SSL_CTX_get_app_data(
        ng.SSL_get_SSL_CTX(ssl)
    )

    # Opened per line: a debugging aid writes a few lines per handshake, and
    # no file handle outlives the context. One append is one write().
    try:
        with open(context._keylog_filename, "a", encoding="ascii") as file:
            file.write(line.decode("ascii") + "\n")
    except BaseException:
        # A debugging aid must not break the handshake.
        pass


cdef int _new_session(ng.SSL *ssl, ng.SSL_SESSION *session) noexcept:
    """Turn a client's new TLS session into a resumption ticket event."""
    cdef ng.ngtcp2_crypto_conn_ref *ref = (
        <ng.ngtcp2_crypto_conn_ref *>ng.SSL_get_app_data(ssl)
    )
    cdef BaseConnection connection = <BaseConnection>ref.user_data
    cdef uint8_t *encoded = NULL
    cdef size_t encoded_len = 0
    cdef uint8_t params[_MAX_EARLY_PARAMS]
    cdef ng.ngtcp2_ssize params_len
    cdef SessionTicketReceived event

    if ng.SSL_SESSION_to_bytes(session, &encoded, &encoded_len) != 1:
        return 0
    try:
        params_len = ng.ngtcp2_conn_encode_0rtt_transport_params2(
            connection._conn, params, _MAX_EARLY_PARAMS,
        )
        if params_len < 0:
            return 0
        event = SessionTicketReceived.__new__(SessionTicketReceived)
        event.ticket = (
            bytes((_TICKET_FORMAT,))
            + encoded_len.to_bytes(4, "big")
            + PyBytes_FromStringAndSize(<const char *>encoded, encoded_len)
            + PyBytes_FromStringAndSize(<const char *>params, params_len)
        )
        connection._events.append(event)
    except BaseException as error:
        connection._callback_error = error
    finally:
        ng.OPENSSL_free(encoded)
    return 0


cdef inline BaseConnection _ssl_connection(const ng.SSL *ssl):
    cdef ng.ngtcp2_crypto_conn_ref *ref = (
        <ng.ngtcp2_crypto_conn_ref *>ng.SSL_get_app_data(ssl)
    )

    return <BaseConnection>ref.user_data


cdef ng.ssl_select_cert_result_t _read_client_hello(
    const ng.SSL_CLIENT_HELLO *hello,
) noexcept:
    """Record the client's ALPN list for ``ClientHelloReceived``."""
    cdef BaseConnection connection = _ssl_connection(hello.ssl)
    cdef const uint8_t *data
    cdef size_t length = 0, offset = 2, size

    try:
        protocols = []
        if ng.SSL_early_callback_ctx_extension_get(
            hello, ng.TLSEXT_TYPE_application_layer_protocol_negotiation,
            &data, &length,
        ):
            while offset < length:
                size = data[offset]
                if offset + 1 + size > length:
                    break
                protocols.append(data[offset + 1:offset + 1 + size].decode("latin-1"))
                offset += 1 + size
        connection._client_alpn = tuple(protocols)
    except BaseException as error:
        connection._callback_error = error
        return ng.ssl_select_cert_error
    return ng.ssl_select_cert_success


cdef int _select_certificate(ng.SSL *ssl, void *arg) noexcept:
    """Pause the server handshake until the application picks a context."""
    cdef BaseConnection connection = _ssl_connection(ssl)
    cdef const char *name
    cdef ClientHelloReceived event

    if connection._certificate_selected:
        return 1
    if connection._tls_pause == _PAUSE_SELECT:
        return -1

    try:
        name = ng.SSL_get_servername(ssl, ng.TLSEXT_NAMETYPE_host_name)
        event = ClientHelloReceived.__new__(ClientHelloReceived)
        event.server_name = None if name == NULL else name.decode("ascii", "replace")
        event.alpn_protocols = connection._client_alpn
        connection._events.append(event)
        connection._tls_pause = _PAUSE_SELECT
    except BaseException as error:
        connection._callback_error = error
        return 0
    return -1


cdef ng.ssl_verify_result_t _verify_peer(ng.SSL *ssl, uint8_t *out_alert) noexcept:
    """Pause the handshake until the application judges the peer's chain."""
    cdef BaseConnection connection = _ssl_connection(ssl)
    cdef const ng.stack_st_CRYPTO_BUFFER *chain
    cdef const ng.CRYPTO_BUFFER *certificate
    cdef PeerCertificateReceived event
    cdef size_t i

    if connection._peer_verdict == 1:
        return ng.ssl_verify_ok
    if connection._peer_verdict == 0:
        out_alert[0] = ng.SSL_AD_BAD_CERTIFICATE
        return ng.ssl_verify_invalid
    if connection._tls_pause == _PAUSE_VERIFY:
        return ng.ssl_verify_retry

    try:
        chain = ng.SSL_get0_peer_certificates(ssl)
        certificates = []
        if chain != NULL:
            for i in range(ng.sk_CRYPTO_BUFFER_num(chain)):
                certificate = ng.sk_CRYPTO_BUFFER_value(chain, i)
                certificates.append(PyBytes_FromStringAndSize(
                    <const char *>ng.CRYPTO_BUFFER_data(certificate),
                    ng.CRYPTO_BUFFER_len(certificate),
                ))
        event = PeerCertificateReceived.__new__(PeerCertificateReceived)
        event.chain = tuple(certificates)
        connection._events.append(event)
        connection._tls_pause = _PAUSE_VERIFY
    except BaseException as error:
        connection._callback_error = error
        out_alert[0] = ng.SSL_AD_BAD_CERTIFICATE
        return ng.ssl_verify_invalid
    return ng.ssl_verify_retry
