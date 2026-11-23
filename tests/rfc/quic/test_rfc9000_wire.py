"""QUIC wire behavior, RFC 9000 sections 11-19."""

import json

import pytest

# Optional: aioquic needs pylsqpack, which has no free-threaded build yet.
pytest.importorskip("aioquic")

from aioquic.buffer import Buffer, encode_uint_var
from aioquic.quic.connection import QuicConnection
from aioquic.quic.packet import QuicFrameType, QuicPacketType, pull_quic_header
from aioquic.quic.packet_builder import QuicPacketBuilder
from support.aioquic import (
    our_client,
    their_client,
)
from support.network import CLIENT_ADDR, SERVER_ADDR

from ngquic import (
    ConnectionTerminated,
    DatagramReceived,
    EndpointConfig,
    ErrorCode,
    HandshakeConfirmed,
    Incoming,
    StreamLimitError,
    TransportConfig,
    Version,
)


@pytest.mark.parametrize("sender", ["client", "server"])
def test_initial_flight_uses_a_1200_byte_udp_payload(network, sender):
    network.client_tls.set_groups(["X25519"])
    initials = []

    def observe(data, destination):
        if (
            data[0] & 0x80
            and (destination == SERVER_ADDR) == (sender == "client")
            and pull_quic_header(Buffer(data=data)).packet_type
            == QuicPacketType.INITIAL
        ):
            initials.append(len(data))
        return False

    network.drop = observe
    network.client_transport = network.server_transport = TransportConfig(
        grease_quic_bit=False
    )
    client = network.connect(version=Version.V1)

    network.run(lambda: network.events_of(client, HandshakeConfirmed))

    assert (bool(initials), min(initials) >= 1200) == (True, True)


def test_server_handshake_coalesces_packets_for_the_same_connection(network):
    coalesced = []

    def observe(data, destination):
        if destination == CLIENT_ADDR and data[0] & 0x80:
            buffer = Buffer(data=data)
            initial = pull_quic_header(buffer)
            if (
                initial.packet_type == QuicPacketType.INITIAL
                and initial.packet_length < len(data)
            ):
                buffer.seek(initial.packet_length)
                handshake = pull_quic_header(buffer)
                coalesced.append(
                    (
                        handshake.packet_type,
                        handshake.destination_cid == initial.destination_cid,
                    )
                )
        return False

    network.drop = observe
    network.client_transport = network.server_transport = TransportConfig(
        grease_quic_bit=False
    )
    client = network.connect(version=Version.V1)

    network.run(lambda: network.events_of(client, HandshakeConfirmed))

    assert set(coalesced) == {(QuicPacketType.HANDSHAKE, True)}


def test_retry_replaces_the_destination_cid_and_preserves_the_source_cid(network):
    client = network.connect(version=Version.V1)
    [first] = client.datagrams_to_send(network.now, max_datagrams=1)
    original = pull_quic_header(Buffer(data=first.data))
    incoming = network.server_endpoint.receive_datagram(
        first.data, CLIENT_ADDR, network.now
    )
    assert isinstance(incoming, Incoming)
    incoming.retry()
    [retry] = network.server_endpoint.datagrams_to_send()
    retry_header = pull_quic_header(Buffer(data=retry.data))

    network.client_endpoint.receive_datagram(retry.data, SERVER_ADDR, network.now)
    [second] = client.datagrams_to_send(network.now, max_datagrams=1)
    retried = pull_quic_header(Buffer(data=second.data))

    assert (
        retry_header.source_cid != original.destination_cid,
        retried.destination_cid,
        retried.source_cid,
        retried.token,
    ) == (True, retry_header.source_cid, original.source_cid, retry_header.token)


def test_a_retry_with_a_corrupted_tag_leaves_the_original_attempt_usable(network):
    network.client_tls.set_groups(["X25519"])
    client = network.connect(version=Version.V1)
    [first] = client.datagrams_to_send(network.now, max_datagrams=1)
    incoming = network.server_endpoint.receive_datagram(
        first.data, CLIENT_ADDR, network.now
    )
    assert isinstance(incoming, Incoming)
    incoming.retry()
    [retry] = network.server_endpoint.datagrams_to_send()
    corrupted = retry.data[:-1] + bytes([retry.data[-1] ^ 1])

    network.client_endpoint.receive_datagram(corrupted, SERVER_ADDR, network.now)
    assert client.datagrams_to_send(network.now) == []

    network.client_endpoint.receive_datagram(retry.data, SERVER_ADDR, network.now)
    [second] = client.datagrams_to_send(network.now, max_datagrams=1)

    assert (
        pull_quic_header(Buffer(data=second.data)).token
        == pull_quic_header(Buffer(data=retry.data)).token
    )


def test_a_duplicate_packet_delivers_its_datagram_once(network):
    network.client_transport = TransportConfig(pmtud=False)
    network.server_transport = TransportConfig(pmtud=False, max_datagram_frame_size=256)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.advance(0.5)
    client.send_datagram(b"once")
    [packet] = client.datagrams_to_send(network.now)

    for _ in range(2):
        network.server_endpoint.receive_datagram(packet.data, CLIENT_ADDR, network.now)

    assert network.server.events() == [DatagramReceived(b"once", False)]


def test_version_negotiation_reflects_both_cids_even_for_an_unknown_version(network):
    dcid = b"d" * 21
    scid = b"s" * 22
    header = b"\xc0\x1a\x2a\x3a\x4a" + bytes([len(dcid)]) + dcid
    header += bytes([len(scid)]) + scid
    datagram = header.ljust(1200, b"\x00")

    network.server_endpoint.receive_datagram(datagram, CLIENT_ADDR, network.now)
    [reply] = network.server_endpoint.datagrams_to_send()
    assert reply.data[1 : 5 + 1 + len(scid) + 1 + len(dcid)] == (
        bytes(4) + bytes([len(scid)]) + scid + bytes([len(dcid)]) + dcid
    )


def test_path_response_echoes_the_challenge_data(network):
    records = []
    network.client_transport = TransportConfig(
        pmtud=False, qlog=lambda data, final: records.append(data)
    )
    network.server_config = EndpointConfig(issue_new_tokens=False)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.advance(0.5)
    records.clear()

    client.migrate(("127.0.0.1", 50001), network.now)
    network.run(until=lambda: client.local_addr == ("127.0.0.1", 50001))
    network.advance(0.5)
    frames = [
        frame
        for record in map(json.loads, (data[1:] for data in records))
        for frame in record.get("data", {}).get("frames", [])
    ]
    challenges = {f["data"] for f in frames if f["frame_type"] == "path_challenge"}
    responses = {f["data"] for f in frames if f["frame_type"] == "path_response"}

    assert responses - challenges == set()
    assert responses != set()


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="RFC 9000 19.14: a blocked unidirectional stream open does not send STREAMS_BLOCKED",
)
def test_a_blocked_unidirectional_stream_open_signals_the_limit_to_the_peer(network):
    records = []
    network.client_transport = TransportConfig(
        pmtud=False, qlog=lambda data, final: records.append(data)
    )
    network.server_transport = TransportConfig(max_streams_uni=0, pmtud=False)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.advance(0.5)
    records.clear()

    with pytest.raises(StreamLimitError, match="allows no more streams"):
        client.open_stream(unidirectional=True)
    network.advance(0.5)

    assert [
        (frame["stream_type"], frame["limit"])
        for record in map(json.loads, (data[1:] for data in records))
        if record["name"] == "transport:packet_sent"
        for frame in record["data"]["frames"]
        if frame["frame_type"] == "streams_blocked"
    ] == [("unidirectional", 0)]


@pytest.mark.parametrize(
    "parameter",
    [
        b"\x00\x08" + b"d" * 8,
        b"\x02\x10" + bytes(16),
        b"\x0d\x31\x7f\x00\x00\x01\x11\x51"
        + bytes(18)
        + b"\x08"
        + b"p" * 8
        + bytes(16),
        b"\x10\x08" + b"s" * 8,
    ],
    ids=["original-dcid", "stateless-reset-token", "preferred-address", "retry-scid"],
)
def test_a_server_rejects_a_client_sending_a_server_only_parameter(
    server_tls, aio_client_config, monkeypatch, parameter
):
    serialize = QuicConnection._serialize_transport_parameters
    monkeypatch.setattr(
        QuicConnection,
        "_serialize_transport_parameters",
        lambda peer: serialize(peer) + parameter,
    )

    link = their_client(server_tls, aio_client_config)

    assert [
        e.error_code for e in link.ours.events() if isinstance(e, ConnectionTerminated)
    ] == [ErrorCode.TRANSPORT_PARAMETER_ERROR]


def test_transport_parameter_integers_accept_a_longer_varint_encoding(
    server_tls, aio_client_config, monkeypatch
):
    serialize = QuicConnection._serialize_transport_parameters
    monkeypatch.setattr(
        QuicConnection,
        "_serialize_transport_parameters",
        lambda peer: serialize(peer) + b"\x03\x04\x80\x00\x04\xb0",
    )
    link = their_client(server_tls, aio_client_config)

    link.run(lambda: link.ours_of(HandshakeConfirmed))

    parameters = link.ours.peer_transport_parameters
    assert parameters is not None
    assert parameters.max_udp_payload_size == 1200


@pytest.mark.parametrize(
    ("frame", "fields", "error"),
    [
        pytest.param(0x3F, b"", ErrorCode.FRAME_ENCODING_ERROR, id="unknown-frame"),
        pytest.param(
            QuicFrameType.ACK,
            b"\x00\x00\x00\x01",
            ErrorCode.FRAME_ENCODING_ERROR,
            id="negative-ack-range",
        ),
        pytest.param(
            QuicFrameType.RESET_STREAM,
            b"\x02\x00\x00",
            ErrorCode.STREAM_STATE_ERROR,
            id="reset-send-only-stream",
        ),
        pytest.param(
            QuicFrameType.STOP_SENDING,
            b"\x03\x00",
            ErrorCode.STREAM_STATE_ERROR,
            id="stop-receive-only-stream",
        ),
        pytest.param(
            QuicFrameType.STOP_SENDING,
            b"\x04\x00",
            ErrorCode.STREAM_STATE_ERROR,
            id="stop-unopened-local-stream",
        ),
        pytest.param(
            QuicFrameType.STREAM_BASE | 0x02,
            b"\x02\x01x",
            ErrorCode.STREAM_STATE_ERROR,
            id="data-on-send-only-stream",
        ),
        pytest.param(
            QuicFrameType.STREAM_BASE | 0x02,
            b"\x04\x01x",
            ErrorCode.STREAM_STATE_ERROR,
            id="data-on-unopened-local-stream",
        ),
        pytest.param(
            QuicFrameType.MAX_STREAM_DATA,
            b"\x03\x01",
            ErrorCode.STREAM_STATE_ERROR,
            id="credit-for-receive-only-stream",
        ),
        pytest.param(
            QuicFrameType.MAX_STREAM_DATA,
            b"\x04\x01",
            ErrorCode.STREAM_STATE_ERROR,
            id="credit-for-unopened-local-stream",
        ),
        pytest.param(
            QuicFrameType.NEW_TOKEN,
            b"\x00",
            ErrorCode.FRAME_ENCODING_ERROR,
            id="empty-new-token",
        ),
        pytest.param(
            QuicFrameType.STREAM_DATA_BLOCKED,
            b"\x02\x00",
            ErrorCode.STREAM_STATE_ERROR,
            id="blocked-send-only-stream",
        ),
        pytest.param(
            QuicFrameType.MAX_STREAMS_BIDI,
            encode_uint_var((1 << 60) + 1),
            ErrorCode.FRAME_ENCODING_ERROR,
            id="unrepresentable-stream-limit",
        ),
        pytest.param(
            QuicFrameType.NEW_CONNECTION_ID,
            b"\x01\x00\x00" + bytes(16),
            ErrorCode.FRAME_ENCODING_ERROR,
            id="empty-connection-id",
        ),
        pytest.param(
            QuicFrameType.NEW_CONNECTION_ID,
            b"\x3f\x40\x40\x08" + b"cid-test" + bytes(16),
            ErrorCode.FRAME_ENCODING_ERROR,
            id="retire-prior-to-exceeds-sequence",
        ),
        pytest.param(
            QuicFrameType.RETIRE_CONNECTION_ID,
            encode_uint_var(500),
            ErrorCode.PROTOCOL_VIOLATION,
            id="retire-unissued-connection-id",
        ),
    ],
)
def test_a_malformed_peer_frame_closes_with_its_transport_error(
    client_tls, aio_server_config, monkeypatch, frame, fields, error
):
    transport = TransportConfig(max_datagram_frame_size=256, pmtud=False)
    link = our_client(client_tls, aio_server_config, transport)
    link.run(lambda: link.ours_of(HandshakeConfirmed))
    link.run(limit=0.5)

    def write_frame(builder: QuicPacketBuilder, data: bytes, frame_type: QuicFrameType):
        buffer = builder.start_frame(frame, capacity=1 + len(fields))
        buffer.push_bytes(fields)
        return True

    monkeypatch.setattr(link.theirs, "_write_datagram_frame", write_frame)

    link.theirs.send_datagram_frame(b"")
    link.run(lambda: link.ours_of(ConnectionTerminated))

    assert [event.error_code for event in link.ours_of(ConnectionTerminated)] == [error]


def test_a_reserved_transport_parameter_is_ignored(
    server_tls, aio_client_config, monkeypatch
):
    serialize = QuicConnection._serialize_transport_parameters
    monkeypatch.setattr(
        QuicConnection,
        "_serialize_transport_parameters",
        lambda peer: serialize(peer) + b"\x1b\x03new",
    )
    link = their_client(server_tls, aio_client_config)

    link.run(
        lambda: link.ours_of(HandshakeConfirmed) or link.ours_of(ConnectionTerminated)
    )

    assert link.ours_of(HandshakeConfirmed) == [HandshakeConfirmed()]
