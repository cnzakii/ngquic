import pytest
from support.network import CLIENT_ADDR, SERVER_ADDR, Network

from ngquic import (
    ConnectionState,
    EarlyDataRejected,
    HandshakeCompleted,
    HandshakeConfirmed,
    SessionTicketReceived,
    StopSendingReceived,
    StreamClosed,
    StreamDataReceived,
    StreamLimitError,
    StreamReset,
    StreamsAvailable,
    StreamStateError,
    StreamWritable,
    TransportConfig,
)


def _echo(connection, event):
    if isinstance(event, StreamDataReceived) and not connection.is_client:
        connection.send_stream_data(
            event.stream_id, event.data, end_stream=event.end_stream
        )


def _received(network, connection, stream_id) -> bytes:
    return b"".join(
        event.data
        for event in network.events_of(connection, StreamDataReceived)
        if event.stream_id == stream_id
    )


def test_handshake_reports_alpn_and_stream_credit(network):
    client = network.connect()

    network.run(lambda: network.events_of(client, HandshakeCompleted))

    assert network.events_of(client, HandshakeCompleted) == [
        HandshakeCompleted("test", False, False)
    ]
    assert client.state is ConnectionState.ESTABLISHED
    assert network.events_of(client, StreamsAvailable)[-1] == StreamsAvailable(100, 3)
    assert client.peer_certificate is not None


def test_bidirectional_stream_round_trip_closes_both_sides(network):
    network.on_event = _echo
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))
    stream_id = client.open_stream()

    client.send_stream_data(stream_id, b"hello ", end_stream=False)
    client.send_stream_data(stream_id, bytearray(b"quic"), end_stream=True)
    network.run(
        lambda: (
            network.events_of(client, StreamClosed)
            and network.events_of(network.server, StreamClosed)
        )
    )

    assert _received(network, client, stream_id) == b"hello quic"
    assert network.events_of(client, StreamClosed) == [
        StreamClosed(stream_id, None, None)
    ]
    assert network.events_of(network.server, StreamClosed) == [
        StreamClosed(stream_id, None, None)
    ]
    assert client.queued_size() == 0


def test_large_transfer_survives_packet_loss_and_releases_buffers(network):
    payload = bytes(range(256)) * 4096
    counter = iter(range(10**9))
    network.drop = lambda data, destination: next(counter) % 7 == 3
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))
    stream_id = client.open_stream()

    for offset in range(0, len(payload), 10_000):
        client.send_stream_data(stream_id, payload[offset : offset + 10_000])
    client.end_stream(stream_id)
    network.run(
        lambda: (
            client.queued_size(stream_id) == 0
            and any(
                event.end_stream
                for event in network.events_of(network.server, StreamDataReceived)
            )
        )
    )

    assert _received(network, network.server, stream_id) == payload
    assert client.stream_loss_count(stream_id) >= 0
    assert client.stats.packets_lost > 0


def test_gso_transmit_carries_several_equal_segments(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))
    stream_id = client.open_stream()
    client.send_stream_data(stream_id, bytes(200_000))
    # Past the pacing delay of the handshake's last packets.
    now = network.now + 0.001

    transmits = client.datagrams_to_send(now, gso=True)

    assert any(len(t.data) > t.segment_size for t in transmits)
    assert all(
        len(t.data) % t.segment_size == 0 or t is transmits[-1] for t in transmits
    )


def test_a_small_reply_is_not_padded_for_gso(network):
    # PMTUD probes are padded to the size they probe.
    network.server_transport = TransportConfig(pmtud=False)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    stream_id = client.open_stream()
    client.send_stream_data(stream_id, b"ask", end_stream=True)
    network.run(lambda: network.events_of(network.server, StreamDataReceived))
    network.server.send_stream_data(stream_id, bytes(100), end_stream=True)

    transmits = network.server.datagrams_to_send(network.now + 0.001, gso=True)

    assert transmits
    assert all(len(t.data) < 300 for t in transmits)


def test_by_default_each_transmit_carries_one_payload(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))
    stream_id = client.open_stream()
    client.send_stream_data(stream_id, bytes(200_000))

    transmits = client.datagrams_to_send(network.now + 0.001)

    assert len(transmits) > 1
    assert all(len(t.data) == t.segment_size for t in transmits)


def test_max_datagrams_counts_udp_payloads(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))
    stream_id = client.open_stream()
    client.send_stream_data(stream_id, bytes(200_000))

    transmits = client.datagrams_to_send(network.now + 0.001, max_datagrams=2)

    assert sum(-(-len(t.data) // t.segment_size) for t in transmits) == 2


def test_send_stream_data_reports_back_pressure_until_acknowledged(
    server_tls, client_tls
):
    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        client_transport=TransportConfig(
            stream_write_buffer_high=50_000, stream_write_buffer_low=10_000
        ),
    )
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))
    stream_id = client.open_stream()

    below_high = client.send_stream_data(stream_id, bytes(40_000))
    above_high = client.send_stream_data(stream_id, bytes(40_000))
    network.run(lambda: network.events_of(client, StreamWritable))

    assert (below_high, above_high) == (True, False)
    assert network.events_of(client, StreamWritable) == [StreamWritable(stream_id)]
    assert client.queued_size(stream_id) <= 10_000


def test_manual_flow_control_stalls_until_data_is_consumed(server_tls, client_tls):
    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        server_transport=TransportConfig(
            auto_flow_control=False,
            max_stream_data_bidi_remote=10_000,
            max_data=10_000,
            max_window=None,
            max_stream_window=None,
        ),
    )
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))
    stream_id = client.open_stream()
    client.send_stream_data(stream_id, bytes(30_000), end_stream=True)

    network.run()
    stalled = len(_received(network, network.server, stream_id))
    network.server.consume_received_data(stream_id, stalled)
    network.run()

    assert stalled == 10_000
    assert len(_received(network, network.server, stream_id)) == 20_000


def test_open_stream_raises_until_the_peer_frees_a_slot(server_tls, client_tls):
    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        server_transport=TransportConfig(max_streams_bidi=1),
        on_event=_echo,
    )
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))
    first = client.open_stream()

    with pytest.raises(StreamLimitError, match="no more streams"):
        client.open_stream()
    client.send_stream_data(first, b"x", end_stream=True)
    network.run(
        lambda: (
            network.events_of(client, StreamClosed) and client.bidi_streams_available
        )
    )

    assert client.open_stream() == first + 4


def test_reset_stream_reports_code_to_peer(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))
    stream_id = client.open_stream()
    client.send_stream_data(stream_id, b"partial")
    network.run()

    client.reset_stream(stream_id, 7)
    network.run(lambda: network.events_of(network.server, StreamReset))

    assert network.events_of(network.server, StreamReset) == [
        StreamReset(stream_id, 7, 7)
    ]
    with pytest.raises(StreamStateError, match="finished sending"):
        client.send_stream_data(stream_id, b"more")


def test_stop_sending_makes_the_peer_reset_its_side(network):
    network.on_event = lambda connection, event: (
        connection.stop_sending(event.stream_id, 9)
        if isinstance(event, StreamDataReceived) and not connection.is_client
        else None
    )
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))
    stream_id = client.open_stream()

    client.send_stream_data(stream_id, b"stop me")
    network.run(lambda: network.events_of(client, StopSendingReceived))

    assert network.events_of(client, StopSendingReceived) == [
        StopSendingReceived(stream_id, 9)
    ]
    with pytest.raises(StreamStateError):
        client.send_stream_data(stream_id, b"more")


def test_peer_can_answer_a_stream_it_only_saw_reset(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))
    stream_id = client.open_stream()
    client.reset_stream(stream_id, 7)
    network.run(lambda: network.events_of(network.server, StreamReset))

    network.server.send_stream_data(stream_id, b"response", end_stream=True)
    network.run(lambda: network.events_of(client, StreamClosed))

    assert _received(network, client, stream_id) == b"response"


def test_reset_releases_data_already_sent(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))
    stream_id = client.open_stream()
    client.send_stream_data(stream_id, bytes(10_000))
    client.datagrams_to_send(network.now, max_datagrams=1)

    client.reset_stream(stream_id, 17)

    assert client.queued_size(stream_id) == 0


def test_send_on_unknown_stream_raises(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))

    with pytest.raises(StreamStateError, match="does not exist"):
        client.send_stream_data(8, b"x")


def test_unidirectional_stream_from_peer_is_receive_only(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))
    stream_id = network.server.open_stream(unidirectional=True)
    network.server.send_stream_data(stream_id, b"push", end_stream=True)
    network.run(lambda: network.events_of(client, StreamDataReceived))

    with pytest.raises(StreamStateError, match="receive-only"):
        client.send_stream_data(stream_id, b"x")


def test_each_call_sends_one_pacing_burst(server_tls, client_tls):
    window = 64 << 20
    transport = TransportConfig(
        max_data=window,
        max_stream_data_bidi_local=window,
        max_stream_data_bidi_remote=window,
        pmtud=False,
    )
    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        client_transport=transport,
        server_transport=transport,
    )
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))
    stream_id = client.open_stream()
    client.send_stream_data(stream_id, bytes(32 << 20))
    # Long enough for the congestion window to outgrow one burst.
    network.run(lambda: len(_received(network, network.server, stream_id)) > 8 << 20)
    due = client.get_timer()
    assert due is not None
    stats = client.stats
    room = stats.congestion_window - stats.bytes_in_flight

    burst = client.datagrams_to_send(due, max_datagrams=10_000)
    again = client.datagrams_to_send(due, max_datagrams=10_000)

    # The window allows far more; pacing spreads it over later calls.
    assert 0 < sum(len(t.data) for t in burst) < room // 2
    assert again == []
    assert (client.get_timer() or 0.0) > due


def test_consuming_data_returns_connection_credit_for_other_streams(network):
    network.server_transport = TransportConfig(
        max_data=8, max_window=None, auto_flow_control=False
    )
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    first = client.open_stream()
    second = client.open_stream()
    client.send_stream_data(first, b"abcdefgh")
    network.run(lambda: _received(network, network.server, first) == b"abcdefgh")
    client.send_stream_data(second, b"ijklmnop")

    network.advance(0.5)
    before_consuming = _received(network, network.server, second)
    network.server.consume_received_data(first, 8)
    network.advance(0.5)

    assert (before_consuming, _received(network, network.server, second)) == (
        b"",
        b"ijklmnop",
    )


def test_consuming_data_returns_stream_credit_only_to_that_stream(network):
    network.server_transport = TransportConfig(
        max_data=64,
        max_stream_data_bidi_remote=8,
        max_window=None,
        max_stream_window=None,
        auto_flow_control=False,
    )
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    first = client.open_stream()
    second = client.open_stream()
    client.send_stream_data(first, b"abcdefghijkl")
    client.send_stream_data(second, b"mnopqrstuvwx")
    network.advance(0.5)
    assert (
        _received(network, network.server, first),
        _received(network, network.server, second),
    ) == (
        b"abcdefgh",
        b"mnopqrst",
    )

    network.server.consume_received_data(first, 8)
    network.advance(0.5)

    assert (
        _received(network, network.server, first),
        _received(network, network.server, second),
    ) == (
        b"abcdefghijkl",
        b"mnopqrst",
    )


def test_stream_stays_writable_at_the_exact_high_watermark(network):
    network.client_transport = TransportConfig(stream_write_buffer_high=8)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    stream_id = client.open_stream()

    at_high = client.send_stream_data(stream_id, bytes(8))
    above_high = client.send_stream_data(stream_id, bytes(1))

    assert (at_high, above_high) == (True, False)


def test_later_ack_keeps_stream_buffer_paused_until_the_missing_prefix_is_acked(
    network,
):
    network.client_transport = TransportConfig(
        stream_write_buffer_high=8, stream_write_buffer_low=1, pmtud=False
    )
    network.server_transport = TransportConfig(ack_threshold=1, pmtud=False)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.advance(0.5)
    stream_id = client.open_stream()
    held = []
    acks = []

    def hold_first(data, destination):
        if destination == SERVER_ADDR:
            held.append(data)
            return True
        return False

    network.drop = hold_first
    client.send_stream_data(stream_id, b"first")
    network.run(lambda: held)
    [first_packet] = held

    def observe_ack(data, destination):
        if destination == CLIENT_ADDR:
            acks.append(data)
        return False

    network.drop = observe_ack
    client.send_stream_data(stream_id, b"last")
    network.run(lambda: acks)
    assert len(acks) == 1
    buffered_before_prefix = client.queued_size(stream_id)
    writable_before_prefix = network.events_of(client, StreamWritable)
    network.server_endpoint.receive_datagram(first_packet, CLIENT_ADDR, network.now)
    network.run(lambda: network.events_of(client, StreamWritable))

    assert (buffered_before_prefix, writable_before_prefix) == (9, [])
    assert network.events_of(client, StreamWritable) == [StreamWritable(stream_id)]
    assert client.queued_size(stream_id) == 0


def test_mutating_a_queued_bytearray_does_not_change_the_stream_data(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    stream_id = client.open_stream()
    payload = bytearray(b"original")
    client.send_stream_data(stream_id, payload, end_stream=True)

    payload[:] = b"modified"
    network.run(lambda: network.events_of(network.server, StreamDataReceived))

    assert _received(network, network.server, stream_id) == b"original"


def test_fin_on_a_peer_unidirectional_stream_restores_unidirectional_credit(network):
    network.server_transport = TransportConfig(max_streams_uni=1, max_streams_bidi=2)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    stream_id = client.open_stream(unidirectional=True)
    assert client.uni_streams_available == 0
    previous_events = len(network.events_of(client, StreamsAvailable))

    client.send_stream_data(stream_id, b"one message", end_stream=True)
    network.advance(0.5)

    assert network.events_of(client, StreamsAvailable)[previous_events:] == [
        StreamsAvailable(2, 1)
    ]


def test_reset_final_size_excludes_unsent_stream_data(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    stream_id = client.open_stream()
    client.send_stream_data(stream_id, b"sent")
    network.run(lambda: network.events_of(network.server, StreamDataReceived))
    client.send_stream_data(stream_id, b"queued")

    client.reset_stream(stream_id, 42)
    network.run(lambda: network.events_of(network.server, StreamReset))

    assert network.events_of(network.server, StreamReset) == [
        StreamReset(stream_id, 42, 4)
    ]


def test_stream_closed_reports_each_directions_own_reset_code(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    server = network.server
    stream_id = client.open_stream()
    client.send_stream_data(stream_id, b"request")
    network.run(lambda: network.events_of(server, StreamDataReceived))
    server.send_stream_data(stream_id, b"response")
    network.run(lambda: network.events_of(client, StreamDataReceived))

    client.reset_stream(stream_id, 10)
    server.reset_stream(stream_id, 20)
    network.run(
        lambda: (
            network.events_of(client, StreamClosed)
            and network.events_of(server, StreamClosed)
        )
    )

    assert network.events_of(client, StreamClosed) == [StreamClosed(stream_id, 20, 10)]
    assert network.events_of(server, StreamClosed) == [StreamClosed(stream_id, 10, 20)]


def test_stop_sending_on_a_local_unidirectional_stream_raises(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    stream_id = client.open_stream(unidirectional=True)

    with pytest.raises(StreamStateError, match="no receiving direction"):
        client.stop_sending(stream_id, 13)


def test_rejected_early_stream_data_is_discarded_before_the_stream_id_is_reused(
    server_tls, client_tls
):
    server_tls.early_data = True
    network = Network(server_tls, client_tls)
    first = network.connect()
    network.run(lambda: network.events_of(first, SessionTicketReceived))
    ticket = network.events_of(first, SessionTicketReceived)[0].ticket
    network.server_transport = TransportConfig(max_streams_bidi=1)
    resumed = network.connect(session_ticket=ticket)
    early_stream = resumed.open_stream()
    resumed.send_stream_data(early_stream, b"discard this", end_stream=True)
    network.run(lambda: network.events_of(resumed, HandshakeConfirmed))
    assert network.events_of(resumed, EarlyDataRejected) == [EarlyDataRejected()]
    reopened = resumed.open_stream()
    assert reopened == early_stream

    resumed.send_stream_data(reopened, b"retry after rejection", end_stream=True)
    network.advance(0.5)

    assert network.events_of(network.server, StreamDataReceived) == [
        StreamDataReceived(reopened, b"retry after rejection", True, False)
    ]


def test_data_that_fits_the_credit_goes_below_the_threshold(network):
    network.server_transport = TransportConfig(
        max_data=64, max_window=None, auto_flow_control=False
    )
    client = network.connect(transport=TransportConfig(write_stream_data_threshold=128))
    network.run(lambda: network.events_of(client, HandshakeCompleted))
    stream_id = client.open_stream()

    client.send_stream_data(stream_id, b"hi", end_stream=True)
    network.run()

    [received] = network.events_of(network.accepted, StreamDataReceived)
    assert (received.data, received.end_stream) == (b"hi", True)
