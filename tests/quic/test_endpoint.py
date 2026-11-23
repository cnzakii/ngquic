import ssl
from pathlib import Path

import pytest
from support.network import CLIENT_ADDR, SERVER_ADDR, Network

from ngquic import (
    CloseReason,
    ConnectionState,
    ConnectionStateError,
    ConnectionTerminated,
    EarlyDataRejected,
    Endpoint,
    EndpointConfig,
    ErrorCode,
    HandshakeCompleted,
    HandshakeConfirmed,
    Incoming,
    NewTokenReceived,
    Role,
    SessionTicketReceived,
    StreamDataReceived,
    TLSContext,
    TLSError,
    TransportConfig,
    Version,
)


def test_retry_proves_the_address_before_accepting(server_tls, client_tls):
    decisions = []

    def accept(incoming):
        decisions.append(incoming.remote_address_validated)
        if not incoming.remote_address_validated:
            incoming.retry()
            return None
        return incoming.accept(tls=server_tls)

    network = Network(server_tls=server_tls, client_tls=client_tls, accept=accept)
    client = network.connect()

    network.run(lambda: network.events_of(client, HandshakeCompleted))

    # Each datagram of the first flight is a separate unvalidated attempt.
    assert decisions[-1] is True and set(decisions[:-1]) == {False}


def test_refuse_reports_connection_refused_to_the_client(server_tls, client_tls):
    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        accept=lambda incoming: incoming.refuse(),
    )
    client = network.connect()

    network.run(lambda: network.events_of(client, ConnectionTerminated))

    terminated = network.events_of(client, ConnectionTerminated)[0]
    assert (terminated.error_code, terminated.by_peer) == (
        ErrorCode.CONNECTION_REFUSED,
        True,
    )


def test_an_attempt_is_decided_once(server_tls, client_tls):
    attempts = []
    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        accept=lambda incoming: attempts.append(incoming) or incoming.ignore(),
    )
    network.connect()
    network.run(lambda: attempts)

    with pytest.raises(ConnectionStateError, match="already decided"):
        attempts[0].accept(tls=server_tls)


def test_new_token_validates_the_next_connection(server_tls, client_tls):
    validated = []

    def accept(incoming):
        validated.append(incoming.remote_address_validated)
        return incoming.accept(tls=server_tls)

    network = Network(server_tls=server_tls, client_tls=client_tls, accept=accept)
    first = network.connect()
    network.run(lambda: network.events_of(first, NewTokenReceived))
    token = network.events_of(first, NewTokenReceived)[0].token

    second = network.connect(token=token)
    network.run(lambda: network.events_of(second, HandshakeCompleted))

    assert validated == [False, True]


def test_resumed_session_carries_0rtt_data(server_tls, client_tls):
    server_tls.early_data = True
    network = Network(server_tls=server_tls, client_tls=client_tls)
    first = network.connect()
    network.run(lambda: network.events_of(first, SessionTicketReceived))
    ticket = network.events_of(first, SessionTicketReceived)[-1].ticket

    second = network.connect(session_ticket=ticket)
    stream_id = second.open_stream()
    second.send_stream_data(stream_id, b"early", end_stream=True)
    network.run(lambda: network.events_of(second, HandshakeCompleted))
    network.run()

    assert network.events_of(second, HandshakeCompleted) == [
        HandshakeCompleted("test", True, True)
    ]
    received = [
        e for e in network.events_of(network.server, StreamDataReceived) if e.data
    ]
    assert received[0].data == b"early" and received[0].early


def test_invalid_session_ticket_is_rejected(network):
    with pytest.raises(ValueError, match="session_ticket"):
        network.connect(session_ticket=b"\x01junk")


def test_unknown_version_gets_version_negotiation():
    endpoint = Endpoint(SERVER_ADDR)
    # Long header, version 0x1a2a3a4a, 8-byte DCID, 8-byte SCID, padded to 1200.
    packet = (
        bytes([0xC0])
        + bytes.fromhex("1a2a3a4a")
        + b"\x08"
        + b"D" * 8
        + b"\x08"
        + b"S" * 8
    )
    packet += bytes(1200 - len(packet))

    assert endpoint.receive_datagram(packet, CLIENT_ADDR, 1.0) is None

    [reply] = endpoint.datagrams_to_send()
    assert reply.data[1:5] == bytes(4)
    assert reply.data[6:14] == b"S" * 8
    assert reply.remote_addr == CLIENT_ADDR


def test_garbage_datagram_is_dropped_quietly():
    endpoint = Endpoint(SERVER_ADDR, EndpointConfig(stateless_reset=False))

    assert endpoint.receive_datagram(b"\x00garbage", CLIENT_ADDR, 1.0) is None
    assert endpoint.datagrams_to_send() == []


def test_restarted_server_resets_the_client_statelessly(server_tls, client_tls):
    secret = bytes(range(32))
    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        server_config=EndpointConfig(secret=secret),
    )
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))
    network.advance(1.0)

    # The server process restarts with the same secret but no connection state.
    network.connections.remove(network.server)
    network.server_endpoint = Endpoint(SERVER_ADDR, EndpointConfig(secret=secret))
    stream_id = client.open_stream()
    client.send_stream_data(stream_id, b"anyone there?")
    network.run(lambda: network.events_of(client, ConnectionTerminated))

    assert (
        network.events_of(client, ConnectionTerminated)[0].reason
        is CloseReason.STATELESS_RESET
    )


def test_hostname_mismatch_fails_the_handshake(network):
    client = network.connect(server_name="example.com")

    network.run(lambda: network.events_of(client, ConnectionTerminated))

    terminated = network.events_of(client, ConnectionTerminated)[0]
    assert terminated.reason is CloseReason.TRANSPORT_ERROR
    assert terminated.error_code & ~0xFF == ErrorCode.CRYPTO_ERROR
    assert client.state is not ConnectionState.ESTABLISHED


def test_untrusted_certificate_fails_the_handshake(server_tls, certificates):
    client_tls = TLSContext(Role.CLIENT)
    client_tls.load_verify_locations(cafile=certificates.other_ca)
    client_tls.set_alpn_protocols(["test"])
    network = Network(server_tls=server_tls, client_tls=client_tls)
    client = network.connect()

    network.run(lambda: network.events_of(client, ConnectionTerminated))

    assert (
        network.events_of(client, ConnectionTerminated)[0].error_code & ~0xFF
        == ErrorCode.CRYPTO_ERROR
    )


def test_no_shared_alpn_fails_the_handshake(server_tls, client_tls):
    client_tls.set_alpn_protocols(["other"])
    network = Network(server_tls=server_tls, client_tls=client_tls)
    client = network.connect()

    network.run(lambda: network.events_of(client, ConnectionTerminated))

    # no_application_protocol (120), RFC 9001 section 8.1.
    assert (
        network.events_of(client, ConnectionTerminated)[0].error_code
        == ErrorCode.CRYPTO_ERROR + 120
    )


def test_ip_address_server_name_is_verified(network):
    client = network.connect(server_name="127.0.0.1")

    network.run(lambda: network.events_of(client, HandshakeCompleted))

    assert client.state is ConnectionState.ESTABLISHED


def test_client_certificate_is_required_when_configured(
    server_tls, client_tls, certificates
):
    server_tls.load_verify_locations(cafile=certificates.ca)
    server_tls.verify_mode = ssl.CERT_REQUIRED
    network = Network(server_tls=server_tls, client_tls=client_tls)
    client = network.connect()

    network.run(lambda: network.events_of(client, ConnectionTerminated))

    # TLS 1.3 clients finish first; the server's alert arrives afterwards.
    terminated = network.events_of(client, ConnectionTerminated)[0]
    assert terminated.by_peer
    assert terminated.error_code & ~0xFF == ErrorCode.CRYPTO_ERROR


def test_client_certificate_authenticates_the_client(
    server_tls, client_tls, certificates
):
    server_tls.load_verify_locations(cafile=certificates.ca)
    server_tls.verify_mode = ssl.CERT_REQUIRED
    client_tls.load_cert_chain(certificates.cert, certificates.key)
    network = Network(server_tls=server_tls, client_tls=client_tls)
    network.connect()

    network.run(
        lambda: (
            network.accepted and network.events_of(network.accepted, HandshakeCompleted)
        )
    )

    assert network.server.peer_certificate is not None


def test_tls_context_follows_ssl_defaults():
    client = TLSContext(Role.CLIENT)
    server = TLSContext(Role.SERVER)

    assert (client.verify_mode, client.check_hostname) == (ssl.CERT_REQUIRED, True)
    assert (server.verify_mode, server.check_hostname) == (ssl.CERT_NONE, False)
    with pytest.raises(ValueError, match="check_hostname"):
        client.verify_mode = ssl.CERT_NONE


def test_missing_certificate_file_raises_tls_error(tmp_path):
    context = TLSContext(Role.SERVER)

    with pytest.raises(TLSError, match="certificate chain"):
        context.load_cert_chain(tmp_path / "missing.pem")


def test_cadata_accepts_pem_text_and_der(certificates):
    pem = Path(certificates.ca).read_text()
    der = ssl.PEM_cert_to_DER_cert(pem)
    context = TLSContext(Role.CLIENT)

    context.load_verify_locations(cadata=pem)
    context.load_verify_locations(cadata=der)
    with pytest.raises(TLSError, match="no PEM certificate"):
        context.load_verify_locations(cadata="not a certificate")


def test_connect_requires_server_name_for_hostname_checks(client_tls):
    endpoint = Endpoint(CLIENT_ADDR)

    with pytest.raises(ValueError, match="server_name"):
        endpoint.connect(SERVER_ADDR, 1.0, tls=client_tls)


@pytest.mark.parametrize(
    "address",
    [("localhost", 1), ("127.0.0.1",), ("127.0.0.1", 70000), "127.0.0.1:1"],
    ids=["hostname", "no-port", "port-range", "string"],
)
def test_endpoint_rejects_non_ip_addresses(address):
    with pytest.raises((TypeError, ValueError)):
        Endpoint(address)


def test_a_rejected_address_leaves_the_last_one_routable(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))

    with pytest.raises(ValueError):
        network.server_endpoint.receive_datagram(
            b"x" * 64, ("localhost", 1), network.now
        )
    stream_id = client.open_stream()
    client.send_stream_data(stream_id, b"after", end_stream=True)
    network.run(lambda: network.events_of(network.accepted, StreamDataReceived))

    assert network.events_of(network.accepted, StreamDataReceived)[0].data == b"after"


def test_transport_config_is_validated_on_connect(client_tls):
    endpoint = Endpoint(CLIENT_ADDR)

    with pytest.raises(ValueError, match="max_tx_udp_payload_size"):
        endpoint.connect(
            SERVER_ADDR,
            1.0,
            tls=client_tls,
            server_name="localhost",
            transport=TransportConfig(max_tx_udp_payload_size=1000),
        )


def test_incoming_cannot_be_constructed_directly():
    with pytest.raises(TypeError):
        Incoming()


def test_client_reconnects_in_a_version_the_server_offers(server_tls, client_tls):
    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        server_config=EndpointConfig(preferred_versions=(Version.V2,)),
    )
    client = network.connect()

    network.run(lambda: network.events_of(client, HandshakeCompleted))

    assert (client.version, network.server.version) == (Version.V2, Version.V2)
    assert not network.events_of(client, ConnectionTerminated)


def test_client_gives_up_without_a_shared_version(server_tls, client_tls):
    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        server_config=EndpointConfig(preferred_versions=(Version.V2,)),
    )
    network.client_endpoint = Endpoint(
        CLIENT_ADDR, EndpointConfig(preferred_versions=(Version.V1,))
    )
    client = network.connect()

    network.run(lambda: network.events_of(client, ConnectionTerminated))

    terminated = network.events_of(client, ConnectionTerminated)[0]
    assert terminated.reason is CloseReason.VERSION_NEGOTIATION
    assert network.server_endpoint.connections == 0


def test_client_finds_its_version_after_many_unknown_ones(server_tls, client_tls):
    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        server_config=EndpointConfig(preferred_versions=(Version.V2,)),
    )
    client = network.connect()
    data = client.datagrams_to_send(network.now)[0].data
    dcid = data[6 : 6 + data[5]]
    scid_at = 6 + data[5]
    scid = data[scid_at + 1 : scid_at + 1 + data[scid_at]]
    unknown = b"".join((0x5A000000 + i).to_bytes(4, "big") for i in range(8))
    negotiation = (
        b"\x80\x00\x00\x00\x00"
        + bytes([len(scid)])
        + scid
        + bytes([len(dcid)])
        + dcid
        + unknown
        + int(Version.V2).to_bytes(4, "big")
    )

    network.client_endpoint.receive_datagram(negotiation, SERVER_ADDR, network.now)
    network.run(lambda: network.events_of(client, HandshakeCompleted))

    assert client.version is Version.V2


def test_0rtt_streams_are_rejected_when_the_version_changes(server_tls, client_tls):
    server_tls.early_data = True
    network = Network(server_tls=server_tls, client_tls=client_tls)
    first = network.connect()
    network.run(lambda: network.events_of(first, SessionTicketReceived))
    ticket = network.events_of(first, SessionTicketReceived)[-1].ticket
    network.server_endpoint = Endpoint(
        SERVER_ADDR, EndpointConfig(preferred_versions=(Version.V2,))
    )
    second = network.connect(session_ticket=ticket)
    second.send_stream_data(second.open_stream(), b"early")

    network.run(lambda: network.events_of(second, HandshakeCompleted))

    # The V1 ticket cannot resume a V2 connection (RFC 9369 section 3.3).
    assert network.events_of(second, EarlyDataRejected) == [EarlyDataRejected()]
    assert network.events_of(second, HandshakeCompleted)[0].session_resumed is False
    assert second.open_stream() == 0


def test_a_retransmitted_initial_joins_the_undecided_attempt(server_tls, client_tls):
    network = Network(server_tls=server_tls, client_tls=client_tls)
    client = network.connect()
    [initial] = client.datagrams_to_send(network.now, max_datagrams=1)
    endpoint = network.server_endpoint

    attempt = endpoint.receive_datagram(initial.data, CLIENT_ADDR, network.now)
    assert isinstance(attempt, Incoming)

    again = endpoint.receive_datagram(initial.data, CLIENT_ADDR, network.now)
    attempt.accept(tls=server_tls)

    assert again is None
    assert endpoint.connections == 1
