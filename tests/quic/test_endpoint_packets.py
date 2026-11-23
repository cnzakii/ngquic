import pytest

# Optional: aioquic needs pylsqpack, which has no free-threaded build yet.
pytest.importorskip("aioquic")

from aioquic.buffer import Buffer
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.connection import QuicConnection
from aioquic.quic.packet import QuicPacketType, pull_quic_header
from support.network import ALPN, CLIENT_ADDR, SERVER_ADDR, Network

from ngquic import (
    CloseReason,
    ConnectionTerminated,
    Endpoint,
    EndpointConfig,
    ErrorCode,
    HandshakeCompleted,
    HandshakeConfirmed,
    Incoming,
    NewTokenReceived,
    PathValidated,
    SessionTicketReceived,
    StreamDataReceived,
    Version,
)


def test_connection_ids_demultiplex_connections_with_the_same_addresses(network):
    first = network.connect()
    network.run(lambda: network.events_of(first, HandshakeConfirmed))
    first_server = network.server
    second = network.connect()
    network.run(lambda: network.events_of(second, HandshakeConfirmed))

    first.send_stream_data(first.open_stream(), b"first", end_stream=True)
    second.send_stream_data(second.open_stream(), b"second", end_stream=True)
    network.advance(0.5)

    assert network.events_of(first_server, StreamDataReceived) == [
        StreamDataReceived(0, b"first", True, False)
    ]
    assert network.events_of(network.server, StreamDataReceived) == [
        StreamDataReceived(0, b"second", True, False)
    ]


def test_repeated_initial_routes_to_the_connection_that_accepted_it(network):
    client = network.connect()
    [initial] = client.datagrams_to_send(network.now, max_datagrams=1)
    endpoint = network.server_endpoint
    attempt = endpoint.receive_datagram(initial.data, CLIENT_ADDR, network.now)
    assert isinstance(attempt, Incoming)
    server = attempt.accept(tls=network.server_tls)
    assert endpoint.connections == 1

    result = endpoint.receive_datagram(initial.data, CLIENT_ADDR, network.now)

    assert result == server


def test_ignoring_an_initial_discards_it_without_a_stateless_reply(network):
    client = network.connect()
    [initial] = client.datagrams_to_send(network.now, max_datagrams=1)
    attempt = network.server_endpoint.receive_datagram(
        initial.data, CLIENT_ADDR, network.now
    )
    assert isinstance(attempt, Incoming)

    attempt.ignore()

    assert network.server_endpoint.datagrams_to_send() == []


@pytest.mark.parametrize(
    ("size", "offered_to_application"),
    [(1199, False), (1200, True)],
    ids=["below-minimum", "exact-minimum"],
)
def test_initial_admission_requires_a_1200_byte_udp_payload(
    network, size, offered_to_application
):
    peer = QuicConnection(configuration=QuicConfiguration(is_client=True))
    peer.connect(SERVER_ADDR, now=network.now)
    # The first of aioquic 1.9's two, which an ML-KEM key share needs.
    (data, _), *_ = peer.datagrams_to_send(network.now)
    header = pull_quic_header(Buffer(data=data))
    assert header.packet_type == QuicPacketType.INITIAL
    # aioquic 1.9's packet fills the datagram, so 1199 bytes also cut the
    # packet; the endpoint decides on the datagram size before decrypting.
    assert size <= len(data)

    result = network.server_endpoint.receive_datagram(
        data[:size], CLIENT_ADDR, network.now
    )

    assert isinstance(result, Incoming) == offered_to_application


@pytest.mark.parametrize(
    ("delay", "remote_addr"),
    [(2.0, CLIENT_ADDR), (0.0, ("127.0.0.1", 50001))],
    ids=["expired", "changed-port"],
)
def test_retry_token_must_be_current_and_match_the_client_address(
    network, delay, remote_addr
):
    network.server_endpoint = Endpoint(
        SERVER_ADDR, EndpointConfig(retry_token_lifetime=1.0)
    )
    client = network.connect()
    [initial] = client.datagrams_to_send(network.now, max_datagrams=1)
    attempt = network.server_endpoint.receive_datagram(
        initial.data, CLIENT_ADDR, network.now
    )
    assert isinstance(attempt, Incoming)
    attempt.retry()
    [retry] = network.server_endpoint.datagrams_to_send()
    network.client_endpoint.receive_datagram(retry.data, SERVER_ADDR, network.now)
    [retried] = client.datagrams_to_send(network.now, max_datagrams=1)

    now = network.now + delay
    result = network.server_endpoint.receive_datagram(retried.data, remote_addr, now)
    replies = network.server_endpoint.datagrams_to_send()
    for reply in replies:
        network.client_endpoint.receive_datagram(reply.data, SERVER_ADDR, now)

    assert result is None
    assert client.events() == [
        ConnectionTerminated(
            CloseReason.TRANSPORT_ERROR, ErrorCode.INVALID_TOKEN, 0, b"", True
        )
    ]


@pytest.fixture
def new_token(network):
    network.server_endpoint = Endpoint(
        SERVER_ADDR, EndpointConfig(new_token_lifetime=1.0)
    )
    first = network.connect(version=Version.V1)
    network.run(lambda: network.events_of(first, NewTokenReceived))
    [issued] = network.events_of(first, NewTokenReceived)
    return issued.token


@pytest.mark.parametrize(
    ("delay", "remote_addr"),
    [(2.0, CLIENT_ADDR), (0.0, ("127.0.0.2", 50000))],
    ids=["expired", "changed-ip"],
)
def test_new_token_validation_checks_lifetime_and_client_ip(
    network, new_token, delay, remote_addr
):
    network.advance(delay)
    client = network.connect(token=new_token)
    [initial] = client.datagrams_to_send(network.now, max_datagrams=1)
    assert pull_quic_header(Buffer(data=initial.data)).token == new_token

    attempt = network.server_endpoint.receive_datagram(
        initial.data, remote_addr, network.now
    )

    assert isinstance(attempt, Incoming)
    assert attempt.remote_address_validated is False


def test_v1_new_token_does_not_validate_an_aioquic_v2_attempt(network, new_token):
    config = QuicConfiguration(
        is_client=True, supported_versions=[int(Version.V2)], token=new_token
    )
    peer = QuicConnection(configuration=config)
    peer.connect(SERVER_ADDR, now=network.now)
    (initial, _), *_ = peer.datagrams_to_send(network.now)

    attempt = network.server_endpoint.receive_datagram(
        initial, CLIENT_ADDR, network.now
    )

    assert isinstance(attempt, Incoming)
    assert attempt.remote_address_validated is False


def test_a_v1_session_ticket_does_not_resume_a_connection_started_in_v2(network):
    network.server_tls.early_data = True
    first = network.connect(version=Version.V1)
    network.run(lambda: network.events_of(first, SessionTicketReceived))
    ticket = network.events_of(first, SessionTicketReceived)[0].ticket

    second = network.connect(version=Version.V2, session_ticket=ticket)
    network.run(lambda: network.events_of(second, HandshakeCompleted))

    assert network.events_of(second, HandshakeCompleted) == [
        HandshakeCompleted(ALPN, False, False)
    ]


def test_version_negotiation_advertises_the_available_versions(network):
    network.server_endpoint = Endpoint(
        SERVER_ADDR,
        EndpointConfig(
            preferred_versions=(Version.V1,), available_versions=(Version.V2,)
        ),
    )
    client = network.connect(version=Version.V1)
    [initial] = client.datagrams_to_send(network.now, max_datagrams=1)

    network.server_endpoint.receive_datagram(initial.data, CLIENT_ADDR, network.now)
    [reply] = network.server_endpoint.datagrams_to_send()
    header = pull_quic_header(Buffer(data=reply.data))
    # RFC 9368 permits reserved versions alongside the advertised versions.
    advertised = [
        version
        for version in header.supported_versions
        if version & 0x0F0F0F0F != 0x0A0A0A0A
    ]

    assert (header.packet_type, advertised) == (
        QuicPacketType.VERSION_NEGOTIATION,
        [Version.V2],
    )


def test_compatible_negotiation_uses_server_preference_on_the_original_attempt(
    server_tls, client_tls
):
    versions = []

    def accept(attempt):
        versions.append(attempt.version)
        return attempt.accept(tls=server_tls)

    network = Network(
        server_tls,
        client_tls,
        server_config=EndpointConfig(
            preferred_versions=(Version.V2,),
            available_versions=(Version.V1, Version.V2),
        ),
        accept=accept,
    )
    client = network.connect(version=Version.V1)

    network.run(lambda: network.events_of(client, HandshakeConfirmed))

    assert (versions, client.version, network.server.version) == (
        [Version.V1],
        Version.V2,
        Version.V2,
    )


def test_aioquic_returns_a_valid_address_token_after_v2_retry(network):
    config = QuicConfiguration(
        is_client=True,
        supported_versions=[int(Version.V2)],
    )
    peer = QuicConnection(configuration=config)
    peer.connect(SERVER_ADDR, now=network.now)
    (initial, _), *_ = peer.datagrams_to_send(network.now)
    attempt = network.server_endpoint.receive_datagram(
        initial, CLIENT_ADDR, network.now
    )
    assert isinstance(attempt, Incoming)

    attempt.retry()
    [retry] = network.server_endpoint.datagrams_to_send()
    peer.receive_datagram(retry.data, SERVER_ADDR, network.now)
    (retried, _), *_ = peer.datagrams_to_send(network.now)
    attempt = network.server_endpoint.receive_datagram(
        retried, CLIENT_ADDR, network.now
    )

    assert isinstance(attempt, Incoming)
    assert (attempt.version, attempt.remote_address_validated) == (Version.V2, True)


def test_restarted_client_resets_the_server_after_migration(network):
    config = EndpointConfig(secret=bytes(range(32)))
    network.client_endpoint = Endpoint(CLIENT_ADDR, config)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    new_addr = ("127.0.0.1", 50001)
    client.migrate(new_addr, network.now)
    network.run(lambda: network.events_of(network.server, PathValidated))
    assert network.server.remote_addr == new_addr
    network.connections.remove(client)
    network.client_endpoint = Endpoint(new_addr, config)

    server = network.server
    server.send_stream_data(server.open_stream(), b"client restarted" * 8)
    network.run(lambda: network.events_of(server, ConnectionTerminated))

    assert network.events_of(server, ConnectionTerminated) == [
        ConnectionTerminated(
            CloseReason.STATELESS_RESET, ErrorCode.NO_ERROR, None, b"", True
        )
    ]


def test_refusing_an_initial_sends_the_callers_transport_code(network):
    network.accept = lambda attempt: attempt.refuse(ErrorCode.APPLICATION_ERROR)
    client = network.connect()

    network.run(lambda: network.events_of(client, ConnectionTerminated))

    assert network.events_of(client, ConnectionTerminated) == [
        ConnectionTerminated(
            CloseReason.TRANSPORT_ERROR, ErrorCode.APPLICATION_ERROR, 0, b"", True
        )
    ]


def test_a_compatibly_negotiated_v2_ticket_resumes_a_direct_v2_connection(
    server_tls, client_tls
):
    server_tls.early_data = True
    network = Network(
        server_tls,
        client_tls,
        server_config=EndpointConfig(
            preferred_versions=(Version.V2,),
            available_versions=(Version.V1, Version.V2),
        ),
    )
    first = network.connect(version=Version.V1)
    network.run(lambda: network.events_of(first, SessionTicketReceived))
    assert first.version == Version.V2
    ticket = network.events_of(first, SessionTicketReceived)[0].ticket

    second = network.connect(version=Version.V2, session_ticket=ticket)
    network.run(lambda: network.events_of(second, HandshakeCompleted))

    assert network.events_of(second, HandshakeCompleted) == [
        HandshakeCompleted(ALPN, True, True)
    ]
