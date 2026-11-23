import ssl
import sys
from pathlib import Path

import pytest
from support.network import ALPN, Network

from ngquic import (
    ClientHelloReceived,
    ConnectionStateError,
    ConnectionTerminated,
    ErrorCode,
    HandshakeCompleted,
    PeerCertificateReceived,
    Role,
    SessionTicketReceived,
    TLSContext,
    TLSError,
    ngtcp2_version,
    tls_version,
)

BAD_CERTIFICATE = 42


def _der(path: str) -> bytes:
    return ssl.PEM_cert_to_DER_cert(Path(path).read_text())


@pytest.fixture
def deferring_server_tls() -> TLSContext:
    # No certificate: the application supplies one per connection.
    context = TLSContext(Role.SERVER)
    context.set_alpn_protocols([ALPN])
    context.defer_certificate_selection = True
    return context


def test_server_picks_the_certificate_after_client_hello(
    deferring_server_tls, server_tls, client_tls, certificates
):
    network = Network(server_tls=deferring_server_tls, client_tls=client_tls)
    network.on_event = lambda connection, event: (
        connection.select_tls_context(server_tls, network.now)
        if isinstance(event, ClientHelloReceived)
        else None
    )
    client = network.connect()

    network.run(lambda: network.events_of(client, HandshakeCompleted))

    assert network.events_of(network.server, ClientHelloReceived) == [
        ClientHelloReceived("localhost", (ALPN,))
    ]
    assert client.peer_certificate == _der(certificates.cert)


def test_selecting_the_accepting_context_resumes_once(server_tls, client_tls):
    server_tls.defer_certificate_selection = True
    network = Network(server_tls=server_tls, client_tls=client_tls)
    network.on_event = lambda connection, event: (
        connection.select_tls_context(server_tls, network.now)
        if isinstance(event, ClientHelloReceived)
        else None
    )
    client = network.connect()

    network.run(lambda: network.events_of(client, HandshakeCompleted))

    assert len(network.events_of(network.server, ClientHelloReceived)) == 1


def test_unanswered_client_hello_holds_the_handshake(deferring_server_tls, client_tls):
    network = Network(server_tls=deferring_server_tls, client_tls=client_tls)
    client = network.connect()

    network.run(lambda: network.events_of(network.server, ClientHelloReceived))
    network.advance(0.5)

    assert not network.events_of(client, HandshakeCompleted)
    assert not network.events_of(network.server, HandshakeCompleted)


def test_select_tls_context_requires_a_pending_client_hello(network, server_tls):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))

    with pytest.raises(ConnectionStateError, match="no certificate selection"):
        network.server.select_tls_context(server_tls, network.now)


def test_client_verifies_the_server_chain_itself(server_tls, client_tls, certificates):
    client_tls.check_hostname = False
    client_tls.defer_peer_verification = True
    network = Network(server_tls=server_tls, client_tls=client_tls)
    network.on_event = lambda connection, event: (
        connection.verify_peer_certificate(True, network.now)
        if isinstance(event, PeerCertificateReceived)
        else None
    )
    client = network.connect()

    network.run(lambda: network.events_of(client, HandshakeCompleted))

    [received] = network.events_of(client, PeerCertificateReceived)
    assert received.chain[0] == _der(certificates.cert)


def test_rejected_peer_fails_the_handshake_with_bad_certificate(server_tls, client_tls):
    client_tls.check_hostname = False
    client_tls.defer_peer_verification = True
    network = Network(server_tls=server_tls, client_tls=client_tls)
    network.on_event = lambda connection, event: (
        connection.verify_peer_certificate(False, network.now)
        if isinstance(event, PeerCertificateReceived)
        else None
    )
    client = network.connect()

    network.run(lambda: network.events_of(network.server, ConnectionTerminated))

    assert not network.events_of(client, HandshakeCompleted)
    terminated = network.events_of(network.server, ConnectionTerminated)[0]
    assert (terminated.error_code, terminated.by_peer) == (
        ErrorCode.CRYPTO_ERROR + BAD_CERTIFICATE,
        True,
    )


def test_server_verifies_client_certificates_itself(
    server_tls, client_tls, certificates
):
    import ssl

    server_tls.verify_mode = ssl.CERT_REQUIRED
    server_tls.defer_peer_verification = True
    client_tls.load_cert_chain(certificates.cert, certificates.key)
    network = Network(server_tls=server_tls, client_tls=client_tls)
    network.on_event = lambda connection, event: (
        connection.verify_peer_certificate(True, network.now)
        if isinstance(event, PeerCertificateReceived)
        else None
    )
    client = network.connect()

    network.run(
        lambda: (
            network.accepted and network.events_of(network.server, HandshakeCompleted)
        )
    )

    assert network.events_of(network.server, PeerCertificateReceived)[0].chain[0] == (
        _der(certificates.cert)
    )
    assert not network.events_of(client, PeerCertificateReceived)


def test_deferred_verification_excludes_hostname_checks():
    context = TLSContext(Role.CLIENT)

    with pytest.raises(ValueError, match="check_hostname"):
        context.defer_peer_verification = True
    context.check_hostname = False
    context.defer_peer_verification = True
    with pytest.raises(ValueError, match="check_hostname"):
        context.check_hostname = True


def test_num_tickets_sets_how_many_tickets_a_client_receives(server_tls, client_tls):
    server_tls.num_tickets = 1
    network = Network(server_tls=server_tls, client_tls=client_tls)
    client = network.connect()

    network.run(lambda: network.events_of(client, HandshakeCompleted))
    network.advance(1.0)

    assert len(network.events_of(client, SessionTicketReceived)) == 1


@pytest.mark.parametrize(
    "name", ["num_tickets", "defer_certificate_selection"], ids=str
)
def test_server_only_settings_reject_client_contexts(name):
    context = TLSContext(Role.CLIENT)

    with pytest.raises(ValueError, match="server contexts"):
        setattr(context, name, 1)


def test_sessions_resume_after_the_server_switches_contexts(
    deferring_server_tls, server_tls, client_tls
):
    network = Network(server_tls=deferring_server_tls, client_tls=client_tls)
    network.on_event = lambda connection, event: (
        connection.select_tls_context(server_tls, network.now)
        if isinstance(event, ClientHelloReceived)
        else None
    )
    first = network.connect()
    network.run(lambda: network.events_of(first, SessionTicketReceived))
    ticket = network.events_of(first, SessionTicketReceived)[0].ticket

    second = network.connect(session_ticket=ticket)
    network.run(lambda: network.events_of(second, HandshakeCompleted))

    assert network.events_of(second, HandshakeCompleted) == [
        HandshakeCompleted(ALPN, True, False)
    ]


def test_keylog_file_receives_the_handshake_secrets(server_tls, client_tls, tmp_path):
    path = tmp_path / "keys.log"
    client_tls.keylog_filename = str(path)
    network = Network(server_tls=server_tls, client_tls=client_tls)
    client = network.connect()

    network.run(lambda: network.events_of(client, HandshakeCompleted))

    assert client_tls.keylog_filename == str(path)
    assert "CLIENT_HANDSHAKE_TRAFFIC_SECRET" in path.read_text()


def test_clearing_the_keylog_filename_stops_logging(server_tls, client_tls, tmp_path):
    path = tmp_path / "keys.log"
    client_tls.keylog_filename = str(path)
    client_tls.keylog_filename = None
    network = Network(server_tls=server_tls, client_tls=client_tls)
    client = network.connect()

    network.run(lambda: network.events_of(client, HandshakeCompleted))

    assert client_tls.keylog_filename is None
    assert path.read_text() == ""


@pytest.mark.parametrize("password", ["secret", b"secret"], ids=["str", "bytes"])
def test_encrypted_private_key_loads_with_its_password(
    certificates, client_tls, password
):
    server_tls = TLSContext(Role.SERVER)
    server_tls.set_alpn_protocols([ALPN])
    server_tls.load_cert_chain(certificates.cert, certificates.encrypted_key, password)
    network = Network(server_tls=server_tls, client_tls=client_tls)
    client = network.connect()

    network.run(lambda: network.events_of(client, HandshakeCompleted))

    assert client.peer_certificate == _der(certificates.cert)


@pytest.mark.parametrize(
    ("certfile", "keyfile", "password", "match"),
    [
        ("cert", "encrypted_key", "wrong", "cannot load private key"),
        ("other_ca", "key", None, "KEY_VALUES_MISMATCH"),
    ],
    ids=["wrong-password", "mismatched-key"],
)
def test_load_cert_chain_reports_an_unusable_key(
    certificates, certfile, keyfile, password, match
):
    context = TLSContext(Role.SERVER)

    with pytest.raises(TLSError, match=match):
        context.load_cert_chain(
            getattr(certificates, certfile), getattr(certificates, keyfile), password
        )


def test_load_verify_locations_needs_a_source():
    with pytest.raises(TypeError, match="cafile, capath or cadata"):
        TLSContext(Role.CLIENT).load_verify_locations()


@pytest.mark.parametrize(
    ("source", "match"),
    [
        ({"cafile": "missing.pem"}, "cannot load verify locations"),
        ({"cadata": b"not der"}, "cadata is not DER"),
    ],
    ids=["missing-file", "bad-der"],
)
def test_load_verify_locations_reports_an_unreadable_source(source, match):
    with pytest.raises(TLSError, match=match):
        TLSContext(Role.CLIENT).load_verify_locations(**source)


def test_tls_errors_are_os_errors_as_ssl_errors_are():
    # Code that catches OSError around ssl file loading catches these too.
    with pytest.raises(OSError, match="cannot load verify locations"):
        TLSContext(Role.CLIENT).load_verify_locations(cafile="missing.pem")


@pytest.mark.parametrize("method", ["set_default_verify_paths", "load_default_certs"])
def test_default_verify_paths_trust_ssl_cert_file(
    server_tls, certificates, monkeypatch, method
):
    monkeypatch.setenv("SSL_CERT_FILE", certificates.ca)
    client_tls = TLSContext(Role.CLIENT)
    client_tls.set_alpn_protocols([ALPN])
    getattr(client_tls, method)()
    network = Network(server_tls=server_tls, client_tls=client_tls)
    client = network.connect()

    network.run(lambda: network.events_of(client, HandshakeCompleted))

    assert client.peer_certificate == _der(certificates.cert)


def test_default_verify_paths_skip_missing_locations(monkeypatch, tmp_path):
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "missing.pem"))
    monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path / "missing"))

    TLSContext(Role.CLIENT).set_default_verify_paths()


def test_load_default_certs_reads_the_windows_stores(
    server_tls, certificates, monkeypatch, tmp_path
):
    stores = {
        # Trusted only for client authentication, so a server check skips it.
        "CA": [
            (_der(certificates.other_ca), "x509_asn", {ssl.Purpose.CLIENT_AUTH.oid})
        ],
        "ROOT": [
            (b"not der", "x509_asn", True),
            (b"a pkcs7 blob", "pkcs_7_asn", True),
            (_der(certificates.ca), "x509_asn", {ssl.Purpose.SERVER_AUTH.oid}),
        ],
    }
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "missing.pem"))
    monkeypatch.setattr(ssl, "enum_certificates", stores.__getitem__, raising=False)
    client_tls = TLSContext(Role.CLIENT)
    client_tls.set_alpn_protocols([ALPN])
    with monkeypatch.context() as patch:
        patch.setattr(sys, "platform", "win32")
        with pytest.warns(UserWarning, match="Bad certificate in Windows"):
            client_tls.load_default_certs()
    network = Network(server_tls=server_tls, client_tls=client_tls)
    client = network.connect()

    network.run(lambda: network.events_of(client, HandshakeCompleted))

    assert client.peer_certificate == _der(certificates.cert)


def test_load_default_certs_warns_about_an_unreadable_windows_store(monkeypatch):
    def deny(store):
        raise PermissionError(store)

    monkeypatch.setattr(ssl, "enum_certificates", deny, raising=False)
    context = TLSContext(Role.CLIENT)
    with monkeypatch.context() as patch:
        patch.setattr(sys, "platform", "win32")
        with pytest.warns(UserWarning, match="unable to enumerate"):
            context.load_default_certs()


def test_load_default_certs_needs_an_ssl_purpose():
    with pytest.raises(TypeError, match=r"ssl\.Purpose"):
        TLSContext(Role.CLIENT).load_default_certs("serverAuth")  # ty: ignore[invalid-argument-type]


@pytest.mark.parametrize("protocols", [[], [""], ["x" * 256]])
def test_alpn_protocols_must_be_1_to_255_bytes(protocols):
    with pytest.raises(ValueError, match="ALPN protocol"):
        TLSContext(Role.CLIENT).set_alpn_protocols(protocols)


def test_unknown_key_exchange_group_is_a_tls_error():
    with pytest.raises(TLSError, match="key exchange groups"):
        TLSContext(Role.CLIENT).set_groups(["no-such-group"])


def test_server_context_defaults():
    context = TLSContext(Role.SERVER)

    assert (
        context.verify_mode,
        context.check_hostname,
        context.early_data,
        context.num_tickets,
        context.defer_certificate_selection,
        context.defer_peer_verification,
    ) == (ssl.CERT_NONE, False, False, 2, False, False)


def test_enabling_check_hostname_turns_on_verification():
    context = TLSContext(Role.SERVER)

    context.check_hostname = True

    assert context.verify_mode == ssl.CERT_REQUIRED


def test_optional_client_certificate_lets_a_client_without_one_connect(
    server_tls, client_tls, certificates
):
    server_tls.load_verify_locations(cafile=certificates.ca)
    server_tls.verify_mode = ssl.CERT_OPTIONAL
    network = Network(server_tls=server_tls, client_tls=client_tls)
    client = network.connect()

    network.run(lambda: network.events_of(client, HandshakeCompleted))

    assert network.server.peer_certificate is None


def test_turning_certificate_selection_off_completes_handshakes_directly(
    server_tls, client_tls
):
    server_tls.defer_certificate_selection = True
    server_tls.defer_certificate_selection = False
    network = Network(server_tls=server_tls, client_tls=client_tls)
    client = network.connect()

    network.run(lambda: network.events_of(client, HandshakeCompleted))

    assert not network.events_of(network.server, ClientHelloReceived)


def test_select_tls_context_needs_a_server_context(
    deferring_server_tls, server_tls, client_tls
):
    network = Network(server_tls=deferring_server_tls, client_tls=client_tls)
    network.connect()
    network.run(lambda: network.events_of(network.server, ClientHelloReceived))

    with pytest.raises(ValueError, match="server context"):
        network.server.select_tls_context(client_tls, network.now)


def test_verify_peer_certificate_requires_a_pending_verification(network):
    client = network.connect()

    with pytest.raises(ConnectionStateError, match="no peer verification"):
        client.verify_peer_certificate(True, network.now)


def test_library_versions_name_the_bundled_releases():
    assert (ngtcp2_version(), tls_version().split()[0]) == ("1.26.0", "AWS-LC")
