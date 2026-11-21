"""RFC 9220 sections 3 and 5: extended CONNECT negotiation and stream closure."""

import pytest

# Optional: aioquic needs pylsqpack, which has no free-threaded build yet.
pytest.importorskip("aioquic")

from aioquic.h3.connection import FrameType, Setting, encode_frame, encode_settings
from aioquic.quic import events as aio
from support.aioquic_h3 import their_h3_client
from support.h3 import OK, connect_h3_client
from support.h3_frames import close_code, headers_frame, open_control, their_server

from ngquic import ConnectionStateError, StreamReset
from ngquic.h3 import (
    DataReceived,
    H3Config,
    H3ErrorCode,
    RequestReceived,
    ResponseReceived,
)

WEBSOCKET = [
    (b":method", b"CONNECT"),
    (b":protocol", b"websocket"),
    (b":scheme", b"https"),
    (b":authority", b"localhost"),
    (b":path", b"/chat"),
]


@pytest.mark.parametrize(
    "settings", [{}, {Setting.ENABLE_CONNECT_PROTOCOL: 0}], ids=["omitted", "zero"]
)
def test_extended_connect_waits_for_a_positive_setting(certificates, settings):
    link = their_server(certificates)
    open_control(link, encode_frame(FrameType.SETTINGS, encode_settings(settings)))
    link.run(lambda: link.ours.remote_settings is not None)

    try:
        stream_id = link.ours.send_request(WEBSOCKET)
    except (ValueError, ConnectionStateError):
        return
    link.run(limit=0.5)

    assert [
        event.data
        for event in link.theirs_of(aio.StreamDataReceived)
        if event.stream_id == stream_id
    ] == []


def test_a_server_without_the_setting_rejects_extended_connect(certificates):
    link = their_h3_client(certificates, h3=False)
    open_control(link)
    link.run(limit=0.5)

    link.theirs.send_stream_data(0, headers_frame(WEBSOCKET), end_stream=True)

    # nghttp3 treats every malformed message as a connection error, which
    # RFC 9114 8 allows in place of the stream error of 4.1.2.
    assert close_code(link) == (H3ErrorCode.H3_MESSAGE_ERROR, False)
    assert not link.ours_of(RequestReceived)


def test_enable_connect_protocol_rejects_values_other_than_zero_or_one(certificates):
    link = their_server(certificates)
    settings = encode_settings({Setting.ENABLE_CONNECT_PROTOCOL: 2})

    open_control(link, encode_frame(FrameType.SETTINGS, settings))

    assert close_code(link) == (H3ErrorCode.H3_SETTINGS_ERROR, False)


@pytest.mark.parametrize("name", [b":scheme", b":path"], ids=["scheme", "path"])
def test_extended_connect_requires_scheme_and_path(h3_network, name):
    h3_network.server_h3 = H3Config(enable_connect_protocol=True)
    client = connect_h3_client(h3_network)

    # Refused before sending: the server's nghttp3 would close the connection.
    with pytest.raises(ValueError, match=f"non-empty {name.decode()}"):
        client.send_request([field for field in WEBSOCKET if field[0] != name])


def _websocket_stream(network):
    network.server_h3 = H3Config(enable_connect_protocol=True)
    client = connect_h3_client(network)
    server = network.h3_server
    stream_id = client.send_request(WEBSOCKET)
    network.run(lambda: network.events_of(server, RequestReceived))
    server.send_response(stream_id, OK)
    network.run(lambda: network.events_of(client, ResponseReceived))
    return client, stream_id


def test_an_orderly_extended_connect_shutdown_arrives_as_fin(h3_network):
    client, stream_id = _websocket_stream(h3_network)
    server = h3_network.h3_server

    client.end_stream(stream_id)
    h3_network.run(lambda: h3_network.events_of(server, DataReceived))

    assert h3_network.events_of(server, DataReceived) == [
        DataReceived(stream_id, b"", True)
    ]


def test_an_abrupt_extended_connect_shutdown_arrives_as_request_cancelled(h3_network):
    client, stream_id = _websocket_stream(h3_network)
    server = h3_network.h3_server

    client.reset_stream(stream_id)
    h3_network.run(lambda: h3_network.events_of(server, StreamReset))

    assert [
        (event.stream_id, event.error_code)
        for event in h3_network.events_of(server, StreamReset)
    ] == [(stream_id, H3ErrorCode.H3_REQUEST_CANCELLED)]
