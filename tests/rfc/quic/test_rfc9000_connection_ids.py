"""RFC 9000 sections 5.1, 5.2 and 7.2: CID routing and replacement."""

import json

import pytest

# Optional: aioquic needs pylsqpack, which has no free-threaded build yet.
pytest.importorskip("aioquic")

from aioquic.buffer import Buffer
from aioquic.quic import events as aio
from aioquic.quic.connection import QuicConnection
from aioquic.quic.packet import pull_quic_header
from support.aioquic import Link
from support.network import CLIENT_ADDR, SERVER_ADDR

from ngquic import (
    Endpoint,
    EndpointConfig,
    HandshakeConfirmed,
    Incoming,
    StreamDataReceived,
    TransportConfig,
)


@pytest.mark.parametrize("connection_id_length", [8, 20], ids=["minimum", "maximum"])
def test_packets_using_a_replacement_connection_id_reach_the_server(
    server_tls, aio_client_config, connection_id_length
):
    endpoint = Endpoint(
        SERVER_ADDR, EndpointConfig(connection_id_length=connection_id_length)
    )
    peer = QuicConnection(configuration=aio_client_config)
    peer.connect(SERVER_ADDR, now=1.0)
    # aioquic 1.9 spreads its ClientHello, with an ML-KEM key share, over two.
    (initial, _), *rest = peer.datagrams_to_send(1.0)
    attempt = endpoint.receive_datagram(initial, CLIENT_ADDR, 1.0)
    assert isinstance(attempt, Incoming)
    for data, _ in rest:
        endpoint.receive_datagram(data, CLIENT_ADDR, 1.0)
    server = attempt.accept(tls=server_tls)
    assert server is not None
    link = Link(server, peer, endpoint, 1.0)
    link.run(lambda: link.theirs_of(aio.HandshakeCompleted))
    link.run(limit=0.5)
    stream_id = peer.get_next_available_stream_id()
    peer.send_stream_data(stream_id, b"original")
    [(original, _)] = peer.datagrams_to_send(link.now)
    endpoint.receive_datagram(original, CLIENT_ADDR, link.now)
    server.events()
    cid = pull_quic_header(
        Buffer(data=original), host_cid_length=connection_id_length
    ).destination_cid

    peer.change_connection_id()
    peer.send_stream_data(stream_id, b"replacement", end_stream=True)
    [(replacement, _)] = peer.datagrams_to_send(link.now)
    new_cid = pull_quic_header(
        Buffer(data=replacement), host_cid_length=connection_id_length
    ).destination_cid
    result = endpoint.receive_datagram(replacement, CLIENT_ADDR, link.now)

    assert (new_cid == cid, result, server.events()) == (
        False,
        server,
        [StreamDataReceived(stream_id, b"replacement", True, False)],
    )


def test_client_initial_retransmission_keeps_the_original_destination_id(network):
    network.client_tls.set_groups(["X25519"])
    network.gso = False
    network.connect()
    network.drop = lambda data, destination: destination == SERVER_ADDR
    network.run(lambda: network.sent)
    [initial] = network.sent
    original = pull_quic_header(Buffer(data=initial))

    network.run(lambda: len(network.sent) > 1)
    repeated = pull_quic_header(Buffer(data=network.sent[1]))

    assert (len(original.destination_cid) >= 8, repeated.destination_cid) == (
        True,
        original.destination_cid,
    )


@pytest.mark.parametrize("limit", [2, 3], ids=["default-limit", "raised-limit"])
def test_issued_connection_ids_are_sequenced_up_to_the_peers_limit(network, limit):
    records = []
    network.server_transport = TransportConfig(
        qlog=lambda data, final: records.append(data)
    )
    network.client_transport = TransportConfig(active_connection_id_limit=limit)
    client = network.connect()

    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.advance(0.5)
    issued = {
        (frame["sequence_number"], frame["connection_id"])
        for data in records
        for record in data.split(b"\x1e")
        if record.strip()
        for event in [json.loads(record)]
        if event.get("name") == "transport:packet_sent"
        for frame in event["data"]["frames"]
        if frame["frame_type"] == "new_connection_id"
    }

    assert sorted(sequence for sequence, _ in issued) == list(range(1, limit))
