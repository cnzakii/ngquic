"""QUIC-TLS handshake ordering, packet protection, and key updates, RFC 9001."""

import pytest

# Optional: aioquic needs pylsqpack, which has no free-threaded build yet.
pytest.importorskip("aioquic")

from aioquic.buffer import Buffer
from aioquic.quic.packet import pull_quic_header
from support.aioquic import (
    our_client,
    their_client,
)
from support.network import CLIENT_ADDR, SERVER_ADDR

from ngquic import (
    ConnectionStateError,
    ConnectionTerminated,
    ErrorCode,
    HandshakeCompleted,
    HandshakeConfirmed,
    StreamDataReceived,
    TransportConfig,
)


def test_server_defers_1rtt_data_until_it_processes_the_client_finished(network):
    transport = TransportConfig(pmtud=False, grease_quic_bit=False)
    network.client_transport = transport
    network.server_transport = transport
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))
    finished = []

    def hold_client_flight(data, destination):
        if destination == SERVER_ADDR:
            finished.append(data)
            return True
        return False

    network.drop = hold_client_flight
    network.run(lambda: finished)
    stream_id = client.open_stream()

    now = network.now + 0.01
    client.send_stream_data(stream_id, b"after Finished", end_stream=True)
    [early] = client.datagrams_to_send(now)
    application = early.data
    while application[0] & 0x80:
        header = pull_quic_header(Buffer(data=application))
        application = application[header.packet_length :]

    network.server_endpoint.receive_datagram(application, CLIENT_ADDR, now)

    assert [
        e for e in network.server.events() if isinstance(e, StreamDataReceived)
    ] == []

    for packet in [*finished, early.data[: len(early.data) - len(application)]]:
        network.server_endpoint.receive_datagram(packet, CLIENT_ADDR, now)

    assert [
        e for e in network.server.events() if isinstance(e, StreamDataReceived)
    ] == [StreamDataReceived(stream_id, b"after Finished", True, False)]


def test_failed_packet_authentication_does_not_consume_the_packet_number(network):
    network.client_transport = TransportConfig(pmtud=False)
    network.server_transport = TransportConfig(pmtud=False)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.advance(0.5)
    stream_id = client.open_stream()
    client.send_stream_data(stream_id, b"authenticated", end_stream=True)
    [packet] = client.datagrams_to_send(network.now)
    corrupted = packet.data[:-1] + bytes([packet.data[-1] ^ 1])

    network.server_endpoint.receive_datagram(corrupted, CLIENT_ADDR, network.now)
    network.server_endpoint.receive_datagram(packet.data, CLIENT_ADDR, network.now)

    assert network.server.events() == [
        StreamDataReceived(stream_id, b"authenticated", True, False)
    ]


def test_second_key_update_requires_acknowledgment_of_the_current_phase(network):
    network.client_transport = TransportConfig(pmtud=False)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.advance(1.0)
    client.update_key(network.now)
    client.send_stream_data(client.open_stream(), b"unacknowledged")
    [_] = client.datagrams_to_send(network.now)

    with pytest.raises(ConnectionStateError, match="key update is not possible"):
        client.update_key(network.now + 10 * client.pto)


def test_missing_alpn_offer_closes_with_no_application_protocol(
    server_tls, aio_client_config
):
    aio_client_config.alpn_protocols = None

    link = their_client(server_tls, aio_client_config)
    link.run(
        lambda: link.ours_of(ConnectionTerminated) or link.ours_of(HandshakeConfirmed)
    )

    assert [event.error_code for event in link.ours_of(ConnectionTerminated)] == [
        ErrorCode.CRYPTO_ERROR + 120
    ]


def test_missing_alpn_selection_closes_with_no_application_protocol(
    client_tls, aio_server_config
):
    aio_server_config.alpn_protocols = None

    link = our_client(client_tls, aio_server_config)
    link.run(
        lambda: link.ours_of(ConnectionTerminated) or link.ours_of(HandshakeCompleted)
    )

    assert [event.error_code for event in link.ours_of(ConnectionTerminated)] == [
        ErrorCode.CRYPTO_ERROR + 120
    ]
