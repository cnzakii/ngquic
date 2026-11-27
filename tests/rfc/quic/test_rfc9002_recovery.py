"""Observable loss detection, timers, and congestion control, RFC 9002."""

import json

import pytest

# Optional: aioquic needs pylsqpack, which has no free-threaded build yet.
pytest.importorskip("aioquic")

from support.aioquic import our_client
from support.network import CLIENT_ADDR, SERVER_ADDR

from ngquic import (
    CongestionControl,
    DatagramAcknowledged,
    DatagramLost,
    HandshakeConfirmed,
    Incoming,
    TransportConfig,
)


@pytest.mark.parametrize(
    ("initial_rtt", "flights_expected"),
    [(0.1, [0.0, 0.3, 0.9]), (None, [0.0, 0.999, 2.997])],
    ids=["configured-rtt", "default-rtt"],
)
def test_initial_probe_timeout_backs_off_by_a_factor_of_two(
    network, initial_rtt, flights_expected
):
    network.client_transport = (
        TransportConfig(initial_rtt=initial_rtt, pmtud=False)
        if initial_rtt is not None
        else TransportConfig(pmtud=False)
    )
    network.connect()
    start = network.now
    flights = set()

    def drop(data, destination):
        flights.add(round(network.now - start, 3))
        return True

    network.drop = drop
    network.run(lambda: len(flights) == 3)

    assert sorted(flights) == flights_expected


def test_probe_timeout_does_not_declare_an_unacknowledged_datagram_lost(network):
    transport = TransportConfig(pmtud=False, max_datagram_frame_size=256)
    network.client_transport = transport
    network.server_transport = transport
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.advance(0.5)
    client.send_datagram(b"wait for loss evidence")
    client.datagrams_to_send(network.now)
    timeout = network.now + client.pto
    before = client.stats

    client.handle_timer(timeout)
    probes = client.datagrams_to_send(timeout)

    assert probes
    assert (
        client.stats.packets_lost - before.packets_lost,
        [e for e in client.events() if isinstance(e, DatagramLost)],
    ) == (0, [])


def test_first_rtt_sample_sets_the_minimum_rtt(network):
    network.client_transport = TransportConfig(initial_rtt=0.333, pmtud=False)
    client = network.connect()
    [initial] = client.datagrams_to_send(network.now, max_datagrams=1)
    incoming = network.server_endpoint.receive_datagram(
        initial.data, CLIENT_ADDR, network.now + 0.025
    )
    assert isinstance(incoming, Incoming)
    server = incoming.accept(tls=network.server_tls)
    assert server is not None

    for packet in server.datagrams_to_send(network.now + 0.025):
        network.client_endpoint.receive_datagram(
            packet.data, SERVER_ADDR, network.now + 0.05
        )

    stats = client.stats
    assert (stats.min_rtt, stats.latest_rtt) == pytest.approx((0.05, 0.05))


def test_reno_limits_bytes_in_flight_without_acknowledgments(network):
    network.client_transport = TransportConfig(
        congestion_control=CongestionControl.RENO,
        max_tx_udp_payload_size=1200,
        pmtud=False,
    )
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.advance(0.5)
    window = client.stats.congestion_window

    network.drop = lambda data, destination: destination == SERVER_ADDR
    client.send_stream_data(client.open_stream(), bytes(128 * 1024))
    network.advance(client.pto / 2)

    assert (
        client.stats.bytes_in_flight <= window,
        client.stats.bytes_in_flight > window - 1200,
    ) == (True, True)


def test_an_ack_only_packet_does_not_start_an_ack_loop(client_tls, aio_server_config):
    records = []
    transport = TransportConfig(
        pmtud=False, qlog=lambda data, final: records.append(data)
    )
    link = our_client(client_tls, aio_server_config, transport)
    link.run(lambda: link.ours_of(HandshakeConfirmed))
    link.run(limit=0.5)
    records.clear()

    datagram_id = link.ours.send_datagram(b"ack this")
    link.run(limit=0.5)

    packets = [
        (record["name"], [frame["frame_type"] for frame in record["data"]["frames"]])
        for record in map(json.loads, (data[1:] for data in records))
        if record["name"] in {"transport:packet_sent", "transport:packet_received"}
    ]
    assert (
        len(packets),
        packets[-1],
        link.ours_of(DatagramAcknowledged),
        link.ours.stats.bytes_in_flight,
    ) == (
        2,
        ("transport:packet_received", ["ack"]),
        [DatagramAcknowledged(datagram_id)],
        0,
    )


def test_reno_halves_the_congestion_window_when_a_packet_is_lost(network):
    network.client_transport = TransportConfig(
        congestion_control=CongestionControl.RENO,
        max_tx_udp_payload_size=1200,
        pmtud=False,
    )
    network.server_transport = TransportConfig(
        ack_threshold=1, max_datagram_frame_size=1200, pmtud=False
    )
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.advance(0.5)
    before = client.stats

    for _ in range(4):
        client.send_datagram(bytes(1100))
    _, _, _, fourth = client.datagrams_to_send(network.now)
    network.server_endpoint.receive_datagram(fourth.data, CLIENT_ADDR, network.now)
    network.run(lambda: client.stats.packets_lost > before.packets_lost)

    # One congestion event halves the window once, however many packets it
    # declares lost: ngtcp2 skips packet numbers at random, so the packet
    # threshold can take the second datagram's packet as well.
    after = client.stats
    assert (after.congestion_window, after.slow_start_threshold) == (
        before.congestion_window // 2,
        before.congestion_window // 2,
    )
