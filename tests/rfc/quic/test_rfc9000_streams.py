"""RFC 9000 sections 2 and 3: stream identifiers, ordering and state."""

import pytest
from support.network import CLIENT_ADDR, SERVER_ADDR

from ngquic import (
    HandshakeConfirmed,
    StopSendingReceived,
    StreamClosed,
    StreamDataReceived,
    TransportConfig,
)


@pytest.mark.parametrize(
    ("is_client", "unidirectional", "first"),
    [(True, False, 0), (False, False, 1), (True, True, 2), (False, True, 3)],
    ids=["client-bidi", "server-bidi", "client-uni", "server-uni"],
)
def test_a_closed_stream_id_is_never_reused(network, is_client, unidirectional, first):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    sender, receiver = (
        (client, network.server) if is_client else (network.server, client)
    )
    stream_id = sender.open_stream(unidirectional=unidirectional)
    sender.send_stream_data(stream_id, b"", end_stream=True)
    network.run(lambda: network.events_of(receiver, StreamDataReceived))
    if not unidirectional:
        receiver.end_stream(stream_id)
    network.run(lambda: network.events_of(sender, StreamClosed))

    next_stream_id = sender.open_stream(unidirectional=unidirectional)

    assert (stream_id, next_stream_id) == (first, first + 4)


def test_out_of_order_fin_waits_for_the_missing_prefix(network):
    network.gso = False
    network.client_transport = TransportConfig(pmtud=False)
    network.server_transport = TransportConfig(pmtud=False)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.advance(0.5)
    stream_id = client.open_stream()
    client.send_stream_data(stream_id, b"first")
    [first] = client.datagrams_to_send(network.now)
    held = []

    def hold_tail(data, destination):
        if destination == SERVER_ADDR:
            held.append(data)
            return True
        return False

    network.drop = hold_tail
    client.send_stream_data(stream_id, b"last", end_stream=True)
    network.run(lambda: held)
    [last] = held

    network.server_endpoint.receive_datagram(last, CLIENT_ADDR, network.now)
    before_prefix = network.server.events()
    network.server_endpoint.receive_datagram(first.data, CLIENT_ADDR, network.now)
    after_prefix = [
        event
        for event in network.server.events()
        if isinstance(event, StreamDataReceived)
    ]

    assert (
        before_prefix,
        {event.stream_id for event in after_prefix},
        b"".join(event.data for event in after_prefix),
        any(event.end_stream for event in after_prefix[:-1]),
        after_prefix[-1].end_stream,
    ) == ([], {stream_id}, b"firstlast", False, True)


def test_lost_stop_sending_is_retransmitted(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    stream_id = client.open_stream()
    client.send_stream_data(stream_id, b"request")
    network.run(lambda: network.events_of(network.server, StreamDataReceived))
    network.advance(0.5)
    network.server.stop_sending(stream_id, 42)
    [_lost] = network.server.datagrams_to_send(network.now, max_datagrams=1)

    network.run(lambda: network.events_of(client, StopSendingReceived))

    assert network.events_of(client, StopSendingReceived) == [
        StopSendingReceived(stream_id, 42)
    ]
