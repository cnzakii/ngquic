"""RFC 9000 section 4: credit updates, stream cancellation and stream limits."""

import pytest
from support.qlog import sent_frames

from ngquic import (
    HandshakeConfirmed,
    StreamDataReceived,
    StreamLimitError,
    StreamReset,
    StreamStateError,
    TransportConfig,
)


def test_reset_leaves_flow_control_on_the_other_direction_intact(network):
    network.client_transport = TransportConfig(
        max_stream_data_bidi_local=4, max_stream_window=None, auto_flow_control=False
    )
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    server = network.server
    stream_id = client.open_stream()
    client.send_stream_data(stream_id, b"request")
    network.run(lambda: network.events_of(server, StreamDataReceived))
    server.send_stream_data(stream_id, b"response", end_stream=True)
    network.run(lambda: network.events_of(client, StreamDataReceived))

    client.reset_stream(stream_id, 42)
    network.run(lambda: network.events_of(server, StreamReset))
    network.advance(0.25)
    before_consume = network.events_of(client, StreamDataReceived)
    client.consume_received_data(stream_id, 4)
    network.run(
        lambda: any(e.end_stream for e in network.events_of(client, StreamDataReceived))
    )

    first = StreamDataReceived(stream_id, b"resp", False, False)
    assert (before_consume, network.events_of(client, StreamDataReceived)) == (
        [first],
        [first, StreamDataReceived(stream_id, b"onse", True, False)],
    )


def test_reset_final_size_includes_stream_bytes_that_were_lost(network):
    network.gso = False
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.advance(0.5)
    stream_id = client.open_stream()
    client.send_stream_data(stream_id, b"received")
    network.run(lambda: network.events_of(network.server, StreamDataReceived))
    network.advance(0.5)
    client.send_stream_data(stream_id, b"lost")
    [_lost] = client.datagrams_to_send(network.now)

    client.reset_stream(stream_id, 42)
    network.run(lambda: network.events_of(network.server, StreamReset))

    assert network.events_of(network.server, StreamReset) == [
        StreamReset(stream_id, 42, len(b"receivedlost"))
    ]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="RFC 9000 4.6: exhausting stream credit emits no STREAMS_BLOCKED frame",
)
def test_exhausted_bidirectional_stream_credit_sends_streams_blocked(network):
    records = []
    network.client_transport = TransportConfig(
        qlog=lambda data, final: records.append(data)
    )
    network.server_transport = TransportConfig(max_streams_bidi=0)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    first_record = len(records)

    with pytest.raises(StreamLimitError, match="no more streams"):
        client.open_stream()
    network.advance(0.5)
    limits = {
        (frame["stream_type"], frame["limit"])
        for frame in sent_frames(records[first_record:], "streams_blocked")
    }

    assert limits == {("bidirectional", 0)}


def test_consumption_returns_credit_before_the_sender_attempts_another_write(network):
    network.server_transport = TransportConfig(
        max_data=8,
        max_stream_data_bidi_remote=8,
        max_window=None,
        max_stream_window=None,
        auto_flow_control=False,
    )
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    stream_id = client.open_stream()
    client.send_stream_data(stream_id, b"abcdefgh")
    network.run(lambda: network.events_of(network.server, StreamDataReceived))
    before_consume = (client.send_capacity(), client.send_capacity(stream_id))

    network.server.consume_received_data(stream_id, 8)
    network.advance(0.5)

    assert (
        before_consume,
        client.send_capacity(),
        client.send_capacity(stream_id),
    ) == (
        (0, 0),
        8,
        8,
    )


def test_data_cannot_be_queued_after_the_final_size_is_set(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    stream_id = client.open_stream()
    client.send_stream_data(stream_id, b"final bytes", end_stream=True)

    with pytest.raises(StreamStateError, match="finished sending"):
        client.send_stream_data(stream_id, b"past the end")


@pytest.mark.parametrize(
    ("limits", "frame_type", "frame"),
    [
        ({"max_data": 8}, "data_blocked", {"limit": 8}),
        (
            {"max_stream_data_bidi_remote": 8},
            "stream_data_blocked",
            {"stream_id": 0, "limit": 8},
        ),
    ],
    ids=["connection-credit", "stream-credit"],
)
def test_data_blocked_frame_describes_the_exhausted_limit(
    network, limits, frame_type, frame
):
    records = []
    network.client_transport = TransportConfig(
        qlog=lambda data, final: records.append(data)
    )
    network.server_transport = TransportConfig(**limits, auto_flow_control=False)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    stream_id = client.open_stream()

    client.send_stream_data(stream_id, b"abcdefghijklmnop", end_stream=True)
    network.advance(0.5)
    frames = sent_frames(records, frame_type)

    assert frames == [{"frame_type": frame_type, **frame}]
