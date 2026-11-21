import pytest
from support.network import CLIENT_ADDR, SERVER_ADDR, Network

from ngquic import (
    CloseReason,
    ConnectionState,
    ConnectionStateError,
    ConnectionTerminated,
    DatagramAcknowledged,
    DatagramError,
    DatagramLost,
    DatagramReceived,
    Endpoint,
    EndpointConfig,
    ErrorCode,
    HandshakeCompleted,
    HandshakeConfirmed,
    InternalError,
    PathValidated,
    PathValidationStarted,
    PreferredAddress,
    StreamDataReceived,
    TransportConfig,
)


def test_a_connection_is_handshaking_until_the_handshake_completes(network):
    client = network.connect()
    before = client.state

    network.run(lambda: network.events_of(client, HandshakeCompleted))

    assert (before, client.state) == (
        ConnectionState.HANDSHAKING,
        ConnectionState.ESTABLISHED,
    )


def test_close_reaches_the_peer_and_both_sides_release_state(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))

    client.close(42, b"done")
    network.run()

    assert network.events_of(client, ConnectionTerminated) == [
        ConnectionTerminated(CloseReason.APPLICATION_ERROR, 42, None, b"done", False),
    ]
    assert network.events_of(network.server, ConnectionTerminated) == [
        ConnectionTerminated(CloseReason.APPLICATION_ERROR, 42, None, b"done", True),
    ]
    assert (client.state, network.server.state) == (
        ConnectionState.CLOSED,
        ConnectionState.CLOSED,
    )
    assert (
        network.client_endpoint.connections,
        network.server_endpoint.connections,
    ) == (0, 0)


def test_closing_lasts_three_probe_timeouts(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))
    pto = client.pto

    client.close()
    client.datagrams_to_send(network.now)

    assert client.state is ConnectionState.CLOSING
    assert client.get_timer() == pytest.approx(network.now + 3 * pto)


def test_operations_after_close_raise(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))
    client.close()

    with pytest.raises(ConnectionStateError, match="closing or closed"):
        client.open_stream()
    client.close()


def test_idle_timeout_terminates_silently(server_tls, client_tls):
    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        client_transport=TransportConfig(idle_timeout=2.0),
    )
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))
    started = network.now

    network.run(lambda: client.state is ConnectionState.CLOSED)

    assert (
        network.events_of(client, ConnectionTerminated)[-1].reason
        is CloseReason.IDLE_TIMEOUT
    )
    assert network.now - started == pytest.approx(2.0, abs=0.5)


def test_keep_alive_prevents_idle_timeout(server_tls, client_tls):
    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        client_transport=TransportConfig(idle_timeout=2.0, keep_alive_interval=0.5),
        server_transport=TransportConfig(idle_timeout=2.0),
    )
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))

    network.run(lambda: network.now > 10.0, limit=20)

    assert client.state is ConnectionState.ESTABLISHED


def test_lost_peer_ends_with_handshake_timeout(server_tls, client_tls):
    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        client_transport=TransportConfig(handshake_timeout=3.0),
        drop=lambda data, destination: True,
    )
    client = network.connect()

    network.run(lambda: network.events_of(client, ConnectionTerminated))

    assert (
        network.events_of(client, ConnectionTerminated)[0].reason
        is CloseReason.HANDSHAKE_TIMEOUT
    )


def test_datagrams_round_trip_and_are_acknowledged(server_tls, client_tls):
    transport = TransportConfig(max_datagram_frame_size=1200)
    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        client_transport=transport,
        server_transport=transport,
        on_event=lambda connection, event: (
            connection.send_datagram(event.data.upper())
            if isinstance(event, DatagramReceived) and not connection.is_client
            else None
        ),
    )
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))

    datagram_id = client.send_datagram(b"ping")
    network.run(
        lambda: (
            network.events_of(client, DatagramReceived)
            and network.events_of(client, DatagramAcknowledged)
        )
    )

    assert network.events_of(client, DatagramReceived) == [
        DatagramReceived(b"PING", False)
    ]
    assert network.events_of(client, DatagramAcknowledged) == [
        DatagramAcknowledged(datagram_id)
    ]


def test_send_datagram_requires_peer_support(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))

    with pytest.raises(DatagramError, match="does not accept"):
        client.send_datagram(b"x")


def test_datagram_queue_drops_oldest_when_full(server_tls, client_tls):
    transport = TransportConfig(max_datagram_frame_size=1200, max_datagram_queue=2)
    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        client_transport=transport,
        server_transport=transport,
    )
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))

    first = client.send_datagram(b"1")
    client.send_datagram(b"2")
    client.send_datagram(b"3")

    assert client.events() == [DatagramLost(first, False)]


def test_oversized_datagram_is_rejected(server_tls, client_tls):
    transport = TransportConfig(max_datagram_frame_size=1200)
    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        client_transport=transport,
        server_transport=transport,
    )
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))

    limit = client.max_datagram_size
    assert limit is not None
    with pytest.raises(DatagramError, match="exceeds"):
        client.send_datagram(bytes(limit + 1))


def test_key_update_keeps_streams_flowing(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.advance(1.0)

    client.update_key(network.now)
    stream_id = client.open_stream()
    client.send_stream_data(stream_id, b"after update", end_stream=True)
    network.run(lambda: network.events_of(network.server, StreamDataReceived))

    assert (
        network.events_of(network.server, StreamDataReceived)[0].data == b"after update"
    )


def test_migration_validates_the_new_path(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    new_local = ("127.0.0.1", 50001)

    client.migrate(new_local, network.now)
    network.run(lambda: network.events_of(client, PathValidated))

    validated = network.events_of(client, PathValidated)[-1]
    assert (validated.local_addr, validated.success) == (new_local, True)
    assert client.local_addr == new_local


def test_migration_before_confirmation_raises(network):
    client = network.connect()

    with pytest.raises(ConnectionStateError, match="confirmed"):
        client.migrate(("127.0.0.1", 50001), network.now)


def test_failing_qlog_callback_drops_the_connection(server_tls, client_tls):
    def fail(data, final):
        raise RuntimeError("disk full")

    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        client_transport=TransportConfig(qlog=fail),
    )
    client = network.connect()

    with pytest.raises(InternalError, match="callback failed") as raised:
        client.datagrams_to_send(network.now)

    assert isinstance(raised.value.__cause__, RuntimeError)
    assert client.state is ConnectionState.CLOSED


def test_qlog_receives_json_seq_records(server_tls, client_tls):
    records = []
    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        client_transport=TransportConfig(qlog=lambda data, final: records.append(data)),
    )
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))

    assert records[0].startswith(b"\x1e")


def test_transport_error_code_is_an_error_code_enum(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))

    client.close(ErrorCode.PROTOCOL_VIOLATION, application=False)
    network.run()

    peer_view = network.events_of(network.server, ConnectionTerminated)[0]
    assert (peer_view.reason, peer_view.error_code) == (
        CloseReason.TRANSPORT_ERROR,
        ErrorCode.PROTOCOL_VIOLATION,
    )


# 1e7 s (four months of uptime) is where a float's step exceeds a nanosecond.
@pytest.mark.parametrize("start", [1.0, 1e7], ids=["near-epoch", "far-from-epoch"])
def test_timer_round_trips_exactly_through_float_seconds(server_tls, client_tls, start):
    network = Network(server_tls=server_tls, client_tls=client_tls, now=start)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))

    # Firing at exactly get_timer() must make progress. After a burst whose
    # pacing delay rounds to zero, ngtcp2 reports "send now" once and the
    # next round clears it; a deadline that keeps repeating is a busy loop.
    repeated = 0
    while (timer := client.get_timer()) is not None:
        client.handle_timer(timer)
        client.datagrams_to_send(timer)
        following = client.get_timer()
        repeated = repeated + 1 if following == timer else 0
        assert (following is None or following >= timer) and repeated < 2


def test_peer_transport_parameters_reflect_the_peer_config(server_tls, client_tls):
    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        server_transport=TransportConfig(
            max_data=123_456, idle_timeout=7.0, max_datagram_frame_size=1000
        ),
    )
    client = network.connect()
    assert client.peer_transport_parameters is None

    network.run(lambda: network.events_of(client, HandshakeCompleted))

    params = client.peer_transport_parameters
    assert params is not None
    assert (params.max_data, params.idle_timeout, params.max_datagram_frame_size) == (
        123_456,
        7.0,
        1000,
    )
    server_params = network.server.peer_transport_parameters
    assert server_params is not None
    assert server_params.max_datagram_frame_size is None


def test_client_moves_to_the_server_preferred_address(server_tls, client_tls):
    preferred = ("127.0.0.2", 4434)
    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        server_config=EndpointConfig(
            preferred_address=PreferredAddress(ipv4=preferred)
        ),
    )
    client = network.connect()

    network.run(lambda: network.events_of(client, PathValidated))
    stream_id = client.open_stream()
    client.send_stream_data(stream_id, b"via preferred", end_stream=True)
    # The server switches once its own validation of the new path completes.
    network.run(
        lambda: (
            network.events_of(network.server, StreamDataReceived)
            and network.events_of(network.server, PathValidated)
        )
    )

    validated = network.events_of(client, PathValidated)[0]
    assert (validated.remote_addr, validated.preferred_address, validated.success) == (
        preferred,
        True,
        True,
    )
    params = client.peer_transport_parameters
    assert params is not None
    assert params.preferred_address == PreferredAddress(ipv4=preferred)
    assert (client.remote_addr, network.server.local_addr) == (preferred, preferred)
    assert (
        network.events_of(network.server, StreamDataReceived)[0].data
        == b"via preferred"
    )


def test_client_can_decline_the_preferred_address(server_tls, client_tls):
    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        server_config=EndpointConfig(
            preferred_address=PreferredAddress(ipv4=("127.0.0.2", 4434))
        ),
        client_transport=TransportConfig(use_preferred_address=False),
    )
    client = network.connect()

    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.advance(1.0)

    assert not network.events_of(client, PathValidated)
    assert client.remote_addr == SERVER_ADDR


@pytest.mark.parametrize(
    "preferred",
    [PreferredAddress(), PreferredAddress(ipv4=("::1", 4434))],
    ids=["empty", "wrong-family"],
)
def test_preferred_address_is_validated(preferred):
    with pytest.raises(ValueError, match="preferred_address"):
        Endpoint(SERVER_ADDR, EndpointConfig(preferred_address=preferred))


def test_pmtud_probes_go_out_one_payload_at_a_time(server_tls, client_tls):
    network = Network(server_tls=server_tls, client_tls=client_tls, gso=False)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))

    network.advance(1.0)

    assert max(len(datagram) for datagram in network.sent) > 1200


def test_a_closed_connection_sends_no_queued_close_reply(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.server.send_stream_data(network.server.open_stream(), b"in flight")
    now = network.now + 0.001
    [late] = network.server.datagrams_to_send(now)
    client.close()
    client.datagrams_to_send(now)
    network.client_endpoint.receive_datagram(late.data, SERVER_ADDR, now)

    while (timer := client.get_timer()) is not None:
        client.handle_timer(timer)

    assert client.state is ConnectionState.CLOSED
    assert client.datagrams_to_send(now) == []


def test_qlog_errors_surface_even_when_the_budget_fills(server_tls, client_tls):
    def fail(data, final):
        raise RuntimeError("disk full")

    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        client_transport=TransportConfig(qlog=fail),
    )
    client = network.connect()

    with pytest.raises(InternalError, match="callback failed"):
        client.datagrams_to_send(network.now, max_datagrams=1)


def test_qlog_gets_a_final_notice_when_the_connection_ends(server_tls, client_tls):
    records = []
    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        client_transport=TransportConfig(
            qlog=lambda data, final: records.append((data, final))
        ),
    )
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))

    client.close()
    network.run(lambda: client.state is ConnectionState.CLOSED)

    assert [final for _, final in records].count(True) == 1
    assert records[-1] == (b"", True)


def test_migrating_to_the_current_address_is_a_value_error(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))

    with pytest.raises(ValueError, match="current local address"):
        client.migrate(client.local_addr, network.now)


def test_migration_is_refused_when_the_peer_disables_it(network):
    network.server_transport = TransportConfig(disable_active_migration=True)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))

    with pytest.raises(ConnectionStateError, match="disabled active migration"):
        client.migrate(("127.0.0.1", 50001), network.now)


@pytest.fixture
def confirmed_client(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.advance(0.5)
    return client


def test_peer_close_keeps_the_connection_draining_for_three_ptos(
    network, confirmed_client
):
    server = network.server
    pto = server.pto
    confirmed_client.close()
    network.run(lambda: network.events_of(server, ConnectionTerminated))
    deadline = network.now + 3 * pto

    network.advance(3 * pto - 0.001)
    before_deadline = server.state
    network.run(lambda: server.state == ConnectionState.CLOSED)

    assert (before_deadline, network.now) == (
        ConnectionState.DRAINING,
        pytest.approx(deadline, abs=1e-9),
    )


def test_draining_connection_sends_nothing_in_response_to_late_packets(
    network, confirmed_client
):
    client = confirmed_client
    server = network.server
    client.send_stream_data(client.open_stream(), b"in flight" * 8)
    [late] = client.datagrams_to_send(network.now)
    client.close()
    network.run(lambda: network.events_of(server, ConnectionTerminated))
    assert server.state == ConnectionState.DRAINING
    sent_before = len(network.sent)

    network.server_endpoint.receive_datagram(late.data, CLIENT_ADDR, network.now)
    network.advance(0.01)

    assert network.sent[sent_before:] == []


def test_closing_discards_queued_stream_data(network, confirmed_client):
    client = confirmed_client
    client.send_stream_data(client.open_stream(), b"never sent", end_stream=True)
    sent_before = len(network.sent)

    client.close()
    network.advance(0.01)

    assert len(network.sent[sent_before:]) == 1
    assert network.events_of(network.server, StreamDataReceived) == []


def test_closing_answers_peer_traffic_after_losing_the_first_close(
    network, confirmed_client
):
    client = confirmed_client
    server = network.server
    dropped = []

    def drop_first_close(data, destination):
        if destination == SERVER_ADDR and not dropped:
            dropped.append(data)
            return True
        return False

    network.drop = drop_first_close
    client.close(77, b"closing")
    network.run(lambda: dropped)
    assert server.state == ConnectionState.ESTABLISHED

    server.send_stream_data(server.open_stream(), bytes(512))
    network.run(lambda: network.events_of(server, ConnectionTerminated))

    assert network.events_of(server, ConnectionTerminated) == [
        ConnectionTerminated(CloseReason.APPLICATION_ERROR, 77, None, b"closing", True)
    ]


@pytest.mark.parametrize(
    ("client_timeout", "server_timeout"),
    [(2.0, 7.0), (7.0, 2.0), (None, 2.0), (2.0, None)],
    ids=["client-shorter", "server-shorter", "client-disabled", "server-disabled"],
)
def test_both_peers_expire_at_the_smallest_nonzero_idle_timeout(
    server_tls, client_tls, client_timeout, server_timeout
):
    network = Network(
        server_tls,
        client_tls,
        client_transport=TransportConfig(
            idle_timeout=client_timeout, pmtud=False, ack_threshold=1
        ),
        server_transport=TransportConfig(
            idle_timeout=server_timeout, pmtud=False, ack_threshold=1
        ),
    )
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.advance(0.5)
    expiries = {}

    def record_timeout(connection, event):
        if isinstance(event, ConnectionTerminated):
            expiries[connection] = (network.now, event)

    network.on_event = record_timeout
    client.send_stream_data(client.open_stream(), b"restart the idle timer")
    deadline = network.now + 2.0

    network.advance(1.999)
    before_deadline = (client.state, network.server.state)
    network.advance(deadline - network.now)

    assert before_deadline == (ConnectionState.ESTABLISHED, ConnectionState.ESTABLISHED)
    idle = ConnectionTerminated(
        CloseReason.IDLE_TIMEOUT, ErrorCode.NO_ERROR, None, b"", False
    )
    assert expiries == {client: (deadline, idle), network.server: (deadline, idle)}


def test_transport_close_reason_phrase_reaches_the_peer(network, confirmed_client):
    phrase = "transport error: café".encode()

    confirmed_client.close(ErrorCode.INTERNAL_ERROR, phrase, application=False)
    network.run(lambda: network.events_of(network.server, ConnectionTerminated))

    assert network.events_of(network.server, ConnectionTerminated) == [
        ConnectionTerminated(
            CloseReason.TRANSPORT_ERROR, ErrorCode.INTERNAL_ERROR, 0, phrase, True
        )
    ]


def test_failed_validated_migration_keeps_the_original_local_address(
    network, confirmed_client
):
    client = confirmed_client
    new_addr = ("127.0.0.1", 50001)
    network.drop = lambda data, destination: destination == new_addr

    client.migrate(new_addr, network.now)
    network.run(lambda: network.events_of(client, PathValidated))

    assert (network.events_of(client, PathValidated), client.local_addr) == (
        [PathValidated(new_addr, SERVER_ADDR, False, False)],
        CLIENT_ADDR,
    )


def test_path_validation_start_reports_the_candidate_path(network, confirmed_client):
    client = confirmed_client
    new_addr = ("127.0.0.1", 50001)

    client.migrate(new_addr, network.now)
    network.run(lambda: network.events_of(client, PathValidationStarted))

    assert network.events_of(client, PathValidationStarted) == [
        PathValidationStarted(new_addr, SERVER_ADDR, False)
    ]


def test_key_update_before_handshake_confirmation_raises(network):
    client = network.connect()

    with pytest.raises(ConnectionStateError, match="key update is not possible"):
        client.update_key(network.now)


def test_ipv6_client_moves_to_the_server_preferred_ipv6_address(server_tls, client_tls):
    preferred = ("::1", 4434, 0, 0)
    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        server_addr=("::1", 4433, 0, 0),
        client_addr=("::1", 50000, 0, 0),
        server_config=EndpointConfig(
            preferred_address=PreferredAddress(ipv6=preferred)
        ),
    )
    client = network.connect()

    network.run(lambda: network.events_of(client, PathValidated))

    params = client.peer_transport_parameters
    assert params is not None
    assert params.preferred_address == PreferredAddress(ipv6=preferred)
    assert (client.remote_addr, client.local_addr) == (preferred, ("::1", 50000, 0, 0))


def test_closed_connection_reports_resting_values(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    client.close()
    network.run(lambda: client.state is ConnectionState.CLOSED)

    assert (
        client.local_addr,
        client.remote_addr,
        client.version,
        client.alpn_protocol,
        client.peer_certificate,
        client.peer_transport_parameters,
        client.pto,
        client.stats.bytes_sent,
        client.get_timer(),
        client.send_capacity(),
        client.stream_loss_count(0),
        client.bidi_streams_available,
        client.uni_streams_available,
    ) == (CLIENT_ADDR, SERVER_ADDR, None, None, None, None, 0.0, 0, None, 0, 0, 0, 0)


def test_handle_timer_after_close_does_nothing(network):
    client = network.connect()
    client.close()
    network.run(lambda: client.state is ConnectionState.CLOSED)

    client.handle_timer(network.now + 10)

    assert client.state is ConnectionState.CLOSED


def test_only_clients_migrate(network):
    network.connect()
    network.run(lambda: network.accepted is not None)

    with pytest.raises(ConnectionStateError, match="only clients migrate"):
        network.server.migrate(("127.0.0.1", 4444), network.now)


def test_unvalidated_migration_moves_at_once(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))

    client.migrate(("127.0.0.1", 50001), network.now, validate=False)

    assert client.local_addr == ("127.0.0.1", 50001)


def test_migration_needs_a_spare_connection_id(server_tls, client_tls):
    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        client_transport=TransportConfig(active_connection_id_limit=2),
    )
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    client.migrate(("127.0.0.1", 50001), network.now)

    with pytest.raises(ConnectionStateError, match="no spare connection ID"):
        client.migrate(("127.0.0.1", 50002), network.now)
