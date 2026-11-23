"""CodSpeed workloads on the in-memory link; ``pytest --codspeed`` measures them.

Without ``--codspeed`` each workload runs once as a test. CodSpeed counts
instructions, so the virtual clock keeps every run identical.
"""

import pytest

pytest.importorskip("pytest_codspeed")

from support.h3 import OK, REQUEST, H3Network
from support.network import Network

from ngquic import (
    DatagramReceived,
    HandshakeCompleted,
    StreamDataReceived,
    TransportConfig,
)
from ngquic.h3 import DataReceived, RequestReceived

BODY = b"x" * 1024
BULK = b"x" * (1024 * 1024)
COUNT = 100
# The datagram queue drops what does not fit, as RFC 9221 allows.
DATAGRAMS = 32
# Rounds run back to back, before MAX_STREAMS could return any credit.
UNLIMITED = TransportConfig(max_streams_bidi=1 << 40, max_datagram_frame_size=65535)


def _connected(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))
    return client


def _forget_events(network):
    for events in network.events.values():
        events.clear()


def _finished(network, connection, kind):
    return sum(event.end_stream for event in network.events_of(connection, kind))


def test_handshake(benchmark, server_tls, client_tls):
    def handshake():
        network = Network(server_tls, client_tls)
        return _connected(network).alpn_protocol

    assert benchmark(handshake) == "test"


def test_bulk_stream(benchmark, server_tls, client_tls):
    def close(connection, event):
        end = isinstance(event, StreamDataReceived) and event.end_stream
        if end and not connection.is_client:
            connection.send_stream_data(event.stream_id, b"", end_stream=True)

    network = Network(
        server_tls, client_tls, server_transport=UNLIMITED, on_event=close
    )
    client = _connected(network)

    def upload():
        _forget_events(network)
        stream_id = client.open_stream()
        client.send_stream_data(stream_id, BULK, end_stream=True)
        network.run(lambda: _finished(network, network.server, StreamDataReceived))
        return sum(
            len(event.data)
            for event in network.events_of(network.server, StreamDataReceived)
        )

    assert benchmark(upload) == len(BULK)


def test_request_streams(benchmark, server_tls, client_tls):
    def answer(connection, event):
        end = isinstance(event, StreamDataReceived) and event.end_stream
        if end and not connection.is_client:
            connection.send_stream_data(event.stream_id, BODY, end_stream=True)

    network = Network(
        server_tls, client_tls, server_transport=UNLIMITED, on_event=answer
    )
    client = _connected(network)

    def exchange():
        _forget_events(network)
        for _ in range(COUNT):
            client.send_stream_data(client.open_stream(), BODY, end_stream=True)
        network.run(lambda: _finished(network, client, StreamDataReceived) == COUNT)
        return _finished(network, client, StreamDataReceived)

    assert benchmark(exchange) == COUNT


def test_datagrams(benchmark, server_tls, client_tls):
    network = Network(
        server_tls, client_tls, server_transport=UNLIMITED, client_transport=UNLIMITED
    )
    client = _connected(network)

    def send():
        _forget_events(network)
        for _ in range(DATAGRAMS):
            client.send_datagram(BODY)
        network.run(
            lambda: (
                len(network.events_of(network.server, DatagramReceived)) == DATAGRAMS
            )
        )
        return len(network.events_of(network.server, DatagramReceived))

    assert benchmark(send) == DATAGRAMS


def test_h3_requests(benchmark, h3_network: H3Network):
    def respond(connection, event):
        if isinstance(event, RequestReceived):
            connection.send_response(event.stream_id, OK)
            connection.send_data(event.stream_id, BODY, end_stream=True)

    h3_network.on_event = respond
    h3_network.server_transport = UNLIMITED
    client = h3_network.connect_h3()
    h3_network.run(lambda: h3_network.events_of(client, HandshakeCompleted))

    def exchange():
        _forget_events(h3_network)
        for _ in range(COUNT):
            client.send_request(REQUEST, end_stream=True)
        h3_network.run(lambda: _finished(h3_network, client, DataReceived) == COUNT)
        return _finished(h3_network, client, DataReceived)

    assert benchmark(exchange) == COUNT
