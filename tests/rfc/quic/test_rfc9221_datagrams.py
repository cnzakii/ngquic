"""DATAGRAM frame negotiation, 0-RTT, acknowledgment, and delivery, RFC 9221."""

import pytest

# Optional: aioquic needs pylsqpack, which has no free-threaded build yet.
pytest.importorskip("aioquic")

from aioquic.quic.packet import QuicFrameType
from support.aioquic import our_client
from support.network import SERVER_ADDR

from ngquic import (
    ConnectionTerminated,
    DatagramAcknowledged,
    DatagramReceived,
    ErrorCode,
    HandshakeCompleted,
    HandshakeConfirmed,
    SessionTicketReceived,
    TransportConfig,
)


@pytest.mark.parametrize("limit", [None, 64], ids=["not-advertised", "exceeded"])
def test_receiving_a_datagram_outside_the_advertised_limit_closes_the_connection(
    client_tls, aio_server_config, limit
):
    link = our_client(
        client_tls, aio_server_config, TransportConfig(max_datagram_frame_size=limit)
    )
    link.run(lambda: link.ours_of(HandshakeConfirmed))
    link.run(limit=0.5)

    # A 63-byte message occupies 65 bytes including the type and length.
    link.theirs._datagrams_pending.append(bytes(63))
    link.run(lambda: link.ours_of(ConnectionTerminated))

    assert [event.error_code for event in link.ours_of(ConnectionTerminated)] == [
        ErrorCode.PROTOCOL_VIOLATION
    ]


def test_a_datagram_can_use_a_remembered_frame_limit_in_0rtt(network):
    network.server_tls.early_data = True
    network.server_transport = TransportConfig(max_datagram_frame_size=256)
    first = network.connect()
    network.run(lambda: network.events_of(first, SessionTicketReceived))
    [ticket] = network.events_of(first, SessionTicketReceived)[:1]
    resumed = network.connect(session_ticket=ticket.ticket)

    resumed.send_datagram(b"early message")
    network.run(lambda: network.events_of(network.server, DatagramReceived))

    assert network.events_of(network.server, DatagramReceived) == [
        DatagramReceived(b"early message", True)
    ]


def test_a_server_rejects_0rtt_when_its_datagram_frame_limit_decreases(network):
    network.server_tls.early_data = True
    network.server_transport = TransportConfig(max_datagram_frame_size=256)
    first = network.connect()
    network.run(lambda: network.events_of(first, SessionTicketReceived))
    [ticket] = network.events_of(first, SessionTicketReceived)[:1]
    network.server_transport = TransportConfig(max_datagram_frame_size=64)
    resumed = network.connect(session_ticket=ticket.ticket)

    resumed.send_datagram(bytes(100))
    network.run(lambda: network.events_of(resumed, HandshakeCompleted))

    assert [
        e.early_data_accepted for e in network.events_of(resumed, HandshakeCompleted)
    ] == [False]


def test_a_datagram_only_packet_is_acknowledged_within_the_advertised_delay(network):
    network.client_transport = TransportConfig(pmtud=False)
    network.server_transport = TransportConfig(
        max_datagram_frame_size=256, max_ack_delay=0.020, pmtud=False
    )
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.advance(0.5)
    sent_at = network.now

    datagram_id = client.send_datagram(b"delayed ACK")
    network.run(lambda: network.events_of(client, DatagramAcknowledged))

    assert (
        0 < network.now - sent_at <= 0.020,
        network.events_of(client, DatagramAcknowledged),
    ) == (
        True,
        [DatagramAcknowledged(datagram_id)],
    )


def test_datagrams_wait_when_the_congestion_window_is_full(network):
    transport = TransportConfig(
        pmtud=False,
        max_tx_udp_payload_size=1200,
        max_datagram_frame_size=1200,
        max_datagram_queue=128,
    )
    network.client_transport = network.server_transport = transport
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.advance(0.5)
    window = client.stats.congestion_window
    network.drop = lambda data, destination: destination == SERVER_ADDR

    for _ in range(100):
        client.send_datagram(bytes(1100))
    network.advance(client.pto / 2)

    # ngtcp2 sends while bytes in flight are below the window, so the last
    # packet may cross it by less than one packet.
    assert window - 1200 < client.stats.bytes_in_flight < window + 1200


def test_a_lengthless_datagram_delivers_the_rest_of_its_packet(
    client_tls, aio_server_config, monkeypatch
):
    transport = TransportConfig(pmtud=False, max_datagram_frame_size=256)
    link = our_client(client_tls, aio_server_config, transport)
    link.run(lambda: link.ours_of(HandshakeConfirmed))
    link.run(limit=0.5)

    def write_lengthless_datagram(builder, data, frame_type):
        buffer = builder.start_frame(QuicFrameType.DATAGRAM, capacity=1 + len(data))
        buffer.push_bytes(data)
        return True

    monkeypatch.setattr(link.theirs, "_write_datagram_frame", write_lengthless_datagram)

    link.theirs.send_datagram_frame(b"lengthless message")
    link.run(lambda: link.ours_of(DatagramReceived))

    assert link.ours_of(DatagramReceived) == [
        DatagramReceived(b"lengthless message", False)
    ]
