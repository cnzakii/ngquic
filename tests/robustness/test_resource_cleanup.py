import gc
import sys
import warnings

import pytest
from support.h3 import OK, POST, REQUEST, H3Network
from support.network import Network

from ngquic import (
    Connection,
    ConnectionState,
    EarlyDataRejected,
    HandshakeConfirmed,
    Role,
    SessionTicketReceived,
    StreamStateError,
    TLSContext,
    TransportConfig,
)
from ngquic.h3 import H3Config, H3Connection, RequestReceived


@pytest.mark.parametrize("use_h3", [False, True], ids=["quic", "h3"])
def test_rejecting_early_data_releases_the_payload(network, h3_network, use_h3):
    link = h3_network if use_h3 else network
    config = H3Config() if use_h3 else None
    link.server_tls.early_data = True
    first = link.open(h3=config)
    link.run(lambda: link.events_of(first, SessionTicketReceived))
    ticket = link.events_of(first, SessionTicketReceived)[0].ticket
    first.close()
    link.run(lambda: first.state is ConnectionState.CLOSED)
    link.server_tls.early_data = False
    client = link.open(h3=config, session_ticket=ticket)
    payload = bytes(bytearray(64 * 1024))
    references = sys.getrefcount(payload)
    if isinstance(client, H3Connection):
        client.send_data(client.send_request(POST), payload, end_stream=True)
    else:
        assert isinstance(client, Connection)
        client.send_stream_data(client.open_stream(), payload, end_stream=True)

    link.run(
        lambda: (
            client.state is ConnectionState.ESTABLISHED
            and link.events_of(client, EarlyDataRejected)
        )
    )

    assert sys.getrefcount(payload) == references


def test_a_failing_final_qlog_callback_releases_send_buffers(
    server_tls, client_tls, monkeypatch
):
    unraisable = []
    monkeypatch.setattr(sys, "unraisablehook", unraisable.append)

    def qlog(data, final):
        if final:
            raise RuntimeError("qlog disk full")

    link = Network(server_tls, client_tls, client_transport=TransportConfig(qlog=qlog))
    client = link.connect()
    link.run(lambda: link.events_of(client, HandshakeConfirmed))
    client.send_stream_data(client.open_stream(), b"unsent")

    client.close()
    link.run(lambda: client.state is ConnectionState.CLOSED)

    assert [type(hook.exc_value) for hook in unraisable] == [RuntimeError]

    assert client.queued_size() == 0


def _copies_of(owner, payload):
    pending = gc.get_referents(owner)
    visited = set()
    while pending:
        obj = pending.pop()
        if isinstance(obj, bytes) and obj == payload:
            yield obj
        if isinstance(obj, (dict, list, set, tuple)) and id(obj) not in visited:
            visited.add(id(obj))
            pending.extend(gc.get_referents(obj))


def test_closing_h3_releases_partially_received_headers(h3_network: H3Network):
    client = h3_network.connect_h3()
    h3_network.run(
        lambda: client.remote_settings and h3_network.h3_server.remote_settings
    )
    h3_network.advance(0.25)
    server = h3_network.h3_server
    marker = b"marker" * 100
    client.send_request(
        [*REQUEST, (b"x-marker", marker), (b"x-tail", b"x" * 20_000)], end_stream=True
    )
    (packet,) = client.datagrams_to_send(h3_network.now, max_datagrams=1)
    h3_network.server_endpoint.receive_datagram(
        packet.data, packet.local_addr, h3_network.now
    )
    server.events()

    server.close()
    h3_network.run(lambda: server.state is ConnectionState.CLOSED)
    server.events()

    assert list(_copies_of(server, marker)) == []


@pytest.mark.parametrize(
    "owner", ["client_endpoint", "client_tls"], ids=["endpoint", "tls"]
)
def test_finishing_a_connection_releases_its_protocol_owner(network, owner):
    dependency = getattr(network, owner)
    references = sys.getrefcount(dependency)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))

    client.close()
    network.run(lambda: client.state is ConnectionState.CLOSED)

    assert sys.getrefcount(dependency) == references


def test_dropping_a_tls_context_leaves_no_key_log_open(tmp_path):
    key_log = tmp_path / "tls.keys"

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always", ResourceWarning)
        tls = TLSContext(Role.CLIENT)
        tls.keylog_filename = key_log
        del tls
        gc.collect()

    assert [
        warning for warning in captured if str(key_log) in str(warning.message)
    ] == []


def test_closing_quic_releases_active_stream_payloads_before_gc(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    payload = bytes(bytearray(64 * 1024))
    references = sys.getrefcount(payload)
    for _ in range(2):
        client.send_stream_data(client.open_stream(), payload)
    was_enabled = gc.isenabled()

    gc.disable()
    try:
        client.close()
        network.run(lambda: client.state is ConnectionState.CLOSED)
        remaining = sys.getrefcount(payload)
    finally:
        if was_enabled:
            gc.enable()

    assert remaining == references


def test_a_request_rejects_a_second_final_response(h3_network: H3Network):
    client = h3_network.connect_h3()
    h3_network.run(lambda: client.remote_settings is not None)
    stream_id = client.send_request(REQUEST, end_stream=True)
    h3_network.run(lambda: h3_network.events_of(h3_network.h3_server, RequestReceived))
    server = h3_network.h3_server
    server.send_response(stream_id, OK)

    with pytest.raises(StreamStateError, match="cannot take a response"):
        server.send_response(stream_id, OK)
