"""RFC 9000 section 10: closing packet protection, idle floor and resets."""

import pytest

# Optional: aioquic needs pylsqpack, which has no free-threaded build yet.
pytest.importorskip("aioquic")

from aioquic.buffer import Buffer
from aioquic.quic.packet import QuicPacketType, pull_quic_header
from support.network import CLIENT_ADDR, SERVER_ADDR

from ngquic import (
    CloseReason,
    ConnectionState,
    ConnectionTerminated,
    Endpoint,
    EndpointConfig,
    ErrorCode,
    HandshakeConfirmed,
    Incoming,
    TransportConfig,
)


def test_close_before_the_server_has_handshake_keys_hides_application_details(network):
    client = network.connect()
    [initial] = client.datagrams_to_send(network.now, max_datagrams=1)
    attempt = network.server_endpoint.receive_datagram(
        initial.data, CLIENT_ADDR, network.now
    )
    assert isinstance(attempt, Incoming)
    server = attempt.accept(tls=network.server_tls)
    assert server is not None

    client.close(42, b"application-only details")
    for transmit in client.datagrams_to_send(network.now):
        network.server_endpoint.receive_datagram(
            transmit.data, CLIENT_ADDR, network.now
        )

    assert server.events() == [
        ConnectionTerminated(
            CloseReason.TRANSPORT_ERROR, ErrorCode.APPLICATION_ERROR, 0, b"", True
        )
    ]


def test_close_after_confirmation_uses_only_short_headers(network):
    network.server_transport = TransportConfig(grease_quic_bit=False)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.advance(0.5)
    cid_length = network.server_endpoint.config.connection_id_length

    client.close()
    [close] = client.datagrams_to_send(network.now)
    header = pull_quic_header(Buffer(data=close.data), host_cid_length=cid_length)

    assert (header.packet_type, header.packet_length) == (
        QuicPacketType.ONE_RTT,
        len(close.data),
    )


def test_closing_limits_replies_to_repeated_peer_traffic(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.advance(0.5)
    server = network.server
    server.send_stream_data(server.open_stream(), b"already in flight")
    [late] = server.datagrams_to_send(network.now)
    client.close()
    [_initial_close] = client.datagrams_to_send(network.now)

    replies = []
    for _ in range(8):
        network.client_endpoint.receive_datagram(late.data, SERVER_ADDR, network.now)
        replies.append(len(client.datagrams_to_send(network.now)))

    assert (sum(replies) < len(replies), sum(replies) > 0) == (True, True)


def test_short_idle_timeout_is_raised_to_three_probe_timeouts(network):
    transport = TransportConfig(idle_timeout=0.002, pmtud=False, ack_threshold=1)
    network.client_transport = transport
    network.server_transport = transport
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.run(quiet=0.001)
    client.send_stream_data(client.open_stream(), b"last activity")
    deadline = network.now + 3 * client.pto

    network.advance(deadline - network.now - 0.001)
    before_deadline = client.state
    network.run(lambda: network.events_of(client, ConnectionTerminated))

    assert (before_deadline, network.now) == (
        ConnectionState.ESTABLISHED,
        pytest.approx(deadline, abs=1e-9),
    )


def test_a_restarted_endpoint_sends_a_shorter_stateless_reset(network):
    config = EndpointConfig(secret=bytes(range(32)))
    network.server_endpoint = Endpoint(SERVER_ADDR, config)
    network.server_transport = TransportConfig(grease_quic_bit=False)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.advance(0.5)
    endpoint = Endpoint(SERVER_ADDR, config)
    client.send_stream_data(client.open_stream(), b"test")
    [late] = client.datagrams_to_send(network.now)

    endpoint.receive_datagram(late.data, CLIENT_ADDR, network.now)
    [reset] = endpoint.datagrams_to_send()
    header = pull_quic_header(
        Buffer(data=reset.data), host_cid_length=endpoint.config.connection_id_length
    )

    assert (header.packet_type, len(reset.data) < len(late.data)) == (
        QuicPacketType.ONE_RTT,
        True,
    )
