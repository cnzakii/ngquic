"""RFC 9000 section 7: handshake binding and remembered transport limits."""

import pytest
from support.network import ALPN

from ngquic import (
    EarlyDataRejected,
    HandshakeCompleted,
    HandshakeConfirmed,
    SessionTicketReceived,
    StreamDataReceived,
    TransportConfig,
)


def test_early_data_uses_the_remembered_stream_window(network):
    network.server_tls.early_data = True
    network.server_transport = TransportConfig(
        max_stream_data_bidi_remote=4, max_stream_window=None, auto_flow_control=False
    )
    first = network.connect()
    network.run(lambda: network.events_of(first, SessionTicketReceived))
    ticket = network.events_of(first, SessionTicketReceived)[0]
    resumed = network.connect(session_ticket=ticket.ticket)
    stream_id = resumed.open_stream()

    resumed.send_stream_data(stream_id, b"abcdefgh", end_stream=True)
    network.run(lambda: network.events_of(resumed, HandshakeConfirmed))
    network.server.consume_received_data(stream_id, 4)
    network.run(
        lambda: any(
            e.end_stream for e in network.events_of(network.server, StreamDataReceived)
        )
    )

    assert network.events_of(network.server, StreamDataReceived) == [
        StreamDataReceived(stream_id, b"abcd", False, True),
        StreamDataReceived(stream_id, b"efgh", True, False),
    ]


def test_a_resumed_handshake_uses_the_servers_new_ack_parameters(network):
    network.server_tls.early_data = True
    network.server_transport = TransportConfig(
        ack_delay_exponent=6, max_ack_delay=0.018
    )
    first = network.connect()
    network.run(lambda: network.events_of(first, SessionTicketReceived))
    ticket = network.events_of(first, SessionTicketReceived)[0]
    network.server_transport = TransportConfig(
        ack_delay_exponent=2, max_ack_delay=0.013
    )
    resumed = network.connect(session_ticket=ticket.ticket)

    network.run(lambda: network.events_of(resumed, HandshakeConfirmed))

    params = resumed.peer_transport_parameters
    assert params is not None
    assert (
        network.events_of(resumed, HandshakeCompleted),
        params.ack_delay_exponent,
        params.max_ack_delay,
    ) == ([HandshakeCompleted(ALPN, True, True)], 2, 0.013)


@pytest.mark.parametrize(
    ("previous", "current"),
    [
        pytest.param(
            TransportConfig(max_data=3),
            TransportConfig(max_data=2),
            id="max_data",
        ),
        pytest.param(
            TransportConfig(max_stream_data_bidi_local=3),
            TransportConfig(max_stream_data_bidi_local=2),
            id="max_stream_data_bidi_local",
        ),
        pytest.param(
            TransportConfig(max_stream_data_bidi_remote=3),
            TransportConfig(max_stream_data_bidi_remote=2),
            id="max_stream_data_bidi_remote",
        ),
        pytest.param(
            TransportConfig(max_stream_data_uni=3),
            TransportConfig(max_stream_data_uni=2),
            id="max_stream_data_uni",
        ),
        pytest.param(
            TransportConfig(max_streams_uni=3),
            TransportConfig(max_streams_uni=2),
            id="max_streams_uni",
        ),
        pytest.param(
            TransportConfig(active_connection_id_limit=3),
            TransportConfig(active_connection_id_limit=2),
            id="active_connection_id_limit",
        ),
    ],
)
def test_server_rejects_early_data_when_a_remembered_limit_decreases(
    network, previous, current
):
    network.server_tls.early_data = True
    network.server_transport = previous
    first = network.connect()
    network.run(lambda: network.events_of(first, SessionTicketReceived))
    ticket = network.events_of(first, SessionTicketReceived)[0]
    network.server_transport = current
    resumed = network.connect(session_ticket=ticket.ticket)

    resumed.send_stream_data(resumed.open_stream(), b"x", end_stream=True)
    network.advance(0.5)

    assert (
        network.events_of(resumed, EarlyDataRejected),
        network.events_of(resumed, HandshakeCompleted),
    ) == ([EarlyDataRejected()], [HandshakeCompleted(ALPN, True, False)])
