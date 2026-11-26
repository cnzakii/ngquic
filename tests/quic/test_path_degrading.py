"""PathDegrading and PathRecovered: data in flight that waits too long for acknowledgment."""

import pytest
from support.network import CLIENT_ADDR, SERVER_ADDR, Network

from ngquic import HandshakeConfirmed, PathDegrading, PathRecovered, TransportConfig


def _to_server(data, destination):
    return destination == SERVER_ADDR


def _confirmed(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.advance(0.5)
    return client


def _path_events(network, client):
    return [
        event
        for event in network.events_of(client)
        if isinstance(event, PathDegrading | PathRecovered)
    ]


def _send(client):
    stream_id = client.open_stream()
    client.send_stream_data(stream_id, b"request")


def test_unacknowledged_data_reports_path_degrading_after_four_ptos(network):
    client = _confirmed(network)
    network.drop = _to_server
    sent_at, pto = network.now, client.pto

    _send(client)
    network.run(lambda: network.events_of(client, PathDegrading))

    assert network.now == pytest.approx(sent_at + 4 * pto)


def test_path_degrading_is_reported_once_per_stall(network):
    client = _confirmed(network)
    network.drop = _to_server
    _send(client)

    network.advance(10.0)

    assert network.events_of(client, PathDegrading) == [PathDegrading()]


def test_acknowledgment_after_degrading_reports_path_recovered(network):
    client = _confirmed(network)
    network.drop = _to_server
    _send(client)
    network.run(lambda: network.events_of(client, PathDegrading))

    network.drop = lambda data, destination: False
    network.advance(1.0)

    assert _path_events(network, client) == [PathDegrading(), PathRecovered()]


def test_a_recovered_path_can_degrade_again(network):
    client = _confirmed(network)
    network.drop = _to_server
    _send(client)
    network.run(lambda: network.events_of(client, PathDegrading))
    network.drop = lambda data, destination: False
    network.advance(1.0)
    network.drop = _to_server

    _send(client)
    network.advance(10.0)

    assert _path_events(network, client) == [
        PathDegrading(),
        PathRecovered(),
        PathDegrading(),
    ]


def test_steadily_acknowledged_data_reports_no_path_event(network):
    client = _confirmed(network)
    stream_id = client.open_stream()
    held: list[bytes] = []
    network.drop = lambda data, destination: (
        destination == SERVER_ADDR and held.append(data) is None
    )

    # Each step delivers the previous step's packets, so data is always in
    # flight while acknowledgments keep arriving.
    for _ in range(200):
        delivered, held[:] = held[:], []
        for datagram in delivered:
            network.server_endpoint.receive_datagram(
                datagram, CLIENT_ADDR, network.now, local_addr=SERVER_ADDR
            )
        client.send_stream_data(stream_id, b"x" * 1000)
        network.advance(0.01)

    assert _path_events(network, client) == []


def test_first_send_after_idling_waits_from_the_send(network):
    client = _confirmed(network)
    network.advance(10.0)

    _send(client)
    network.advance(1.0)

    assert network.events_of(client, PathDegrading) == []


def test_path_degrading_is_off_when_disabled(server_tls, client_tls):
    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        client_transport=TransportConfig(path_degrading_ptos=None),
    )
    client = _confirmed(network)
    network.drop = _to_server

    _send(client)
    network.advance(10.0)

    assert network.events_of(client, PathDegrading) == []


def test_servers_do_not_report_path_degrading(network):
    client = _confirmed(network)
    network.drop = lambda data, destination: destination != SERVER_ADDR
    stream_id = client.open_stream()
    client.send_stream_data(stream_id, b"request")
    network.advance(0.1)

    network.server.send_stream_data(stream_id, b"response")
    network.advance(10.0)

    assert network.events_of(network.server, PathDegrading) == []
