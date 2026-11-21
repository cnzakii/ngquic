"""RFC 9114 sections 4.1-4.5, 7.1, 9, and 10.3: HTTP messages and CONNECT."""

import pytest

# Optional: aioquic needs pylsqpack, which has no free-threaded build yet.
pytest.importorskip("aioquic")

from aioquic.h3.connection import FrameType, encode_frame
from aioquic.quic import events as aio
from support.aioquic_h3 import their_h3_client
from support.h3 import OK, POST, REQUEST, connect_h3_client
from support.h3_frames import (
    RESERVED,
    close_code,
    headers_frame,
    open_control,
    peer_settings,
    stream_bytes,
    their_server,
)

from ngquic.h3 import DataReceived, H3ErrorCode, RequestReceived, ResponseReceived


@pytest.mark.parametrize(
    "frames",
    [
        encode_frame(FrameType.DATA, b"content"),
        headers_frame(POST)
        + headers_frame([(b"x-trailer", b"done")])
        + encode_frame(FrameType.DATA, b"late"),
        headers_frame(POST) + headers_frame([(b"x-trailer", b"done")]) * 2,
    ],
    ids=["data-before-headers", "data-after-trailers", "headers-after-trailers"],
)
def test_invalid_request_frame_order_is_a_frame_unexpected_error(certificates, frames):
    link = their_h3_client(certificates, h3=False)
    open_control(link)

    link.theirs.send_stream_data(0, frames, end_stream=True)

    assert close_code(link) == (H3ErrorCode.H3_FRAME_UNEXPECTED, False)


@pytest.mark.parametrize(
    "payload",
    [
        headers_frame([*POST, (b"transfer-encoding", b"chunked")]),
        headers_frame([*POST, (b"connection", b"close")]),
        headers_frame([*POST, (b"te", b"gzip")]),
        headers_frame([*POST, (b"x-Upper", b"v")]),
        pytest.param(
            headers_frame([*POST, (b"x invalid", b"v")]),
            id="invalid-name",
            marks=pytest.mark.xfail(
                strict=True,
                reason="RFC 9114 10.3: nghttp3 drops a field with an invalid name",
            ),
        ),
        pytest.param(
            headers_frame([*POST, (b"x-field", b"bad\x00value")]),
            id="invalid-value",
            marks=pytest.mark.xfail(
                strict=True,
                reason="RFC 9114 10.3: nghttp3 drops a field with an invalid value",
            ),
        ),
        headers_frame([*POST, (b":undefined", b"1")]),
        headers_frame([*POST, (b":status", b"200")]),
        headers_frame([*POST[:-1], (b"x", b"1"), POST[-1]]),
        headers_frame([*POST[:-1], (b":path", b"")]),
        headers_frame(POST[:-1]),
        headers_frame(POST[1:]),
        headers_frame([POST[0], *POST[2:]]),
        headers_frame([POST[0], *POST]),
        headers_frame([*POST[:2], POST[-1]]),
        headers_frame([*POST[:2], (b":authority", b""), POST[-1]]),
        headers_frame([*POST, (b"host", b"elsewhere.example")]),
        headers_frame([*POST, (b"content-length", b"3")])
        + encode_frame(FrameType.DATA, b"xy"),
        headers_frame(POST) * 2,
        headers_frame(POST) + headers_frame([(b":path", b"/")]),
    ],
    ids=[
        "transfer-encoding",
        "connection",
        "invalid-te",
        "uppercase-name",
        "invalid-name",
        "invalid-value",
        "unknown-pseudo-header",
        "response-pseudo-header",
        "pseudo-header-after-field",
        "empty-path",
        "missing-path",
        "missing-method",
        "missing-scheme",
        "duplicate-method",
        "missing-authority",
        "empty-authority",
        "mismatched-host",
        "short-body",
        "second-request",
        "pseudo-header-in-trailers",
    ],
)
def test_a_malformed_request_is_rejected_with_h3_message_error(certificates, payload):
    link = their_h3_client(certificates, h3=False)
    open_control(link)

    link.theirs.send_stream_data(0, payload, end_stream=True)

    terminated = close_code(link)
    resets = [event.error_code for event in link.theirs_of(aio.StreamReset)]
    assert (terminated, resets) in (
        ((H3ErrorCode.H3_MESSAGE_ERROR, False), []),
        (None, [H3ErrorCode.H3_MESSAGE_ERROR]),
    )


@pytest.mark.parametrize(
    "fields",
    [
        [(b"x-field", b"value")],
        [(b":status", b"101")],
        [*OK, (b":method", b"GET")],
    ],
    ids=["missing-status", "switching-protocols", "request-pseudo-header"],
)
def test_a_malformed_response_is_rejected_with_h3_message_error(certificates, fields):
    link = their_server(certificates)
    link.run(lambda: link.theirs_of(aio.HandshakeCompleted))
    stream_id = link.ours.send_request(REQUEST, end_stream=True)
    link.run(lambda: stream_bytes(link, stream_id))

    link.theirs.send_stream_data(stream_id, headers_frame(fields), end_stream=True)

    assert close_code(link) == (H3ErrorCode.H3_MESSAGE_ERROR, False)


def test_a_second_final_response_is_rejected_with_h3_message_error(certificates):
    link = their_server(certificates)
    link.run(lambda: link.theirs_of(aio.HandshakeCompleted))
    stream_id = link.ours.send_request(REQUEST, end_stream=True)
    link.run(lambda: stream_bytes(link, stream_id))

    link.theirs.send_stream_data(stream_id, headers_frame(OK) * 2, end_stream=True)

    assert close_code(link) == (H3ErrorCode.H3_MESSAGE_ERROR, False)


def test_reserved_frames_do_not_interrupt_a_request(certificates):
    link = their_h3_client(certificates, h3=False)
    open_control(link)
    reserved_frame = encode_frame(RESERVED, b"skipped")

    link.theirs.send_stream_data(
        0,
        reserved_frame
        + headers_frame(POST)
        + reserved_frame
        + encode_frame(FrameType.DATA, b"body")
        + reserved_frame,
        end_stream=True,
    )
    link.run(lambda: link.ours_of(DataReceived))

    assert [event.data for event in link.ours_of(DataReceived)] == [b"body"]


@pytest.mark.parametrize(
    "field",
    [(b"te", b"trailers"), (b"host", b"localhost")],
    ids=["te-trailers", "host"],
)
def test_a_permitted_request_header_is_delivered(certificates, field):
    link = their_h3_client(certificates, h3=False)
    open_control(link)
    fields = [*REQUEST, field]

    link.theirs.send_stream_data(0, headers_frame(fields), end_stream=True)
    link.run(lambda: link.ours_of(RequestReceived))

    assert link.ours_of(RequestReceived) == [RequestReceived(0, tuple(fields), True)]


def test_head_response_may_advertise_a_length_without_content(h3_network):
    client = connect_h3_client(h3_network)
    server = h3_network.h3_server
    stream_id = client.send_request(
        [(b":method", b"HEAD"), *REQUEST[1:]], end_stream=True
    )
    h3_network.run(lambda: h3_network.events_of(server, RequestReceived))
    fields = [*OK, (b"content-length", b"15")]

    server.send_response(stream_id, fields, end_stream=True)
    h3_network.run(lambda: h3_network.events_of(client, ResponseReceived))

    assert h3_network.events_of(client, ResponseReceived) == [
        ResponseReceived(stream_id, tuple(fields), True)
    ]


def test_cancelling_an_open_request_also_stops_the_response(certificates):
    link = their_server(certificates)
    link.run(lambda: link.theirs_of(aio.HandshakeCompleted))
    stream_id = link.ours.send_request(POST)
    link.run(lambda: stream_bytes(link, stream_id))

    link.ours.reset_stream(stream_id)
    link.run(lambda: link.theirs_of(aio.StopSendingReceived))

    assert link.theirs_of(aio.StopSendingReceived) == [
        aio.StopSendingReceived(
            error_code=H3ErrorCode.H3_REQUEST_CANCELLED, stream_id=stream_id
        )
    ]


def test_plain_connect_carries_data_after_the_response(h3_network):
    client = connect_h3_client(h3_network)
    server = h3_network.h3_server
    request = [(b":method", b"CONNECT"), (b":authority", b"localhost:443")]
    stream_id = client.send_request(request)
    h3_network.run(lambda: h3_network.events_of(server, RequestReceived))
    server.send_response(stream_id, OK)
    h3_network.run(lambda: h3_network.events_of(client, ResponseReceived))

    client.send_data(stream_id, b"client", end_stream=True)
    server.send_data(stream_id, b"server", end_stream=True)
    h3_network.run(
        lambda: (
            h3_network.events_of(client, DataReceived)
            and h3_network.events_of(server, DataReceived)
        )
    )

    assert (
        h3_network.events_of(server, DataReceived),
        h3_network.events_of(client, DataReceived),
    ) == (
        [DataReceived(stream_id, b"client", True)],
        [DataReceived(stream_id, b"server", True)],
    )


@pytest.mark.parametrize(
    "extra_fields",
    [[], [(b":scheme", b"https")], [(b":path", b"/")]],
    ids=["no-authority", "scheme", "path"],
)
def test_plain_connect_rejects_invalid_pseudo_headers(certificates, extra_fields):
    link = their_h3_client(certificates, h3=False)
    open_control(link)
    authority = [(b":authority", b"localhost:443")] if extra_fields else []
    fields = [(b":method", b"CONNECT"), *authority, *extra_fields]

    link.theirs.send_stream_data(0, headers_frame(fields))

    assert close_code(link) == (H3ErrorCode.H3_MESSAGE_ERROR, False)


def test_a_successful_connect_tunnel_rejects_trailers(certificates):
    link = their_h3_client(certificates, h3=False)
    open_control(link)
    fields = [(b":method", b"CONNECT"), (b":authority", b"localhost:443")]
    link.theirs.send_stream_data(0, headers_frame(fields))
    link.run(lambda: link.ours_of(RequestReceived))
    link.ours.send_response(0, OK)
    link.run(limit=0.5)

    link.theirs.send_stream_data(
        0, headers_frame([(b"x-trailer", b"value")]), end_stream=True
    )

    assert close_code(link) == (H3ErrorCode.H3_FRAME_UNEXPECTED, False)


@pytest.mark.xfail(
    strict=True,
    reason="RFC 9114 4.1: a request ending before HEADERS gets H3_FRAME_UNEXPECTED",
)
def test_a_request_ending_before_any_headers_is_incomplete(certificates):
    link = their_h3_client(certificates, h3=False)
    open_control(link)

    link.theirs.send_stream_data(0, b"", end_stream=True)
    terminated = close_code(link)

    assert (
        terminated,
        [event.error_code for event in link.theirs_of(aio.StreamReset)],
    ) in (
        ((H3ErrorCode.H3_REQUEST_INCOMPLETE, False), []),
        (None, [H3ErrorCode.H3_REQUEST_INCOMPLETE]),
    )


def test_split_cookie_fields_remain_in_order(certificates):
    link = their_h3_client(certificates, h3=False)
    open_control(link)
    fields = [*REQUEST, (b"cookie", b"a=1"), (b"cookie", b"b=2")]

    link.theirs.send_stream_data(0, headers_frame(fields), end_stream=True)
    link.run(lambda: link.ours_of(RequestReceived))

    assert link.ours_of(RequestReceived) == [RequestReceived(0, tuple(fields), True)]


def test_a_request_at_the_goaway_cutoff_is_rejected(certificates):
    link = their_h3_client(certificates, h3=False)
    open_control(link)
    peer_settings(link)
    link.ours.send_goaway()
    link.run(limit=0.5)

    link.theirs.send_stream_data(0, headers_frame(REQUEST))
    link.run(limit=0.5)

    assert link.theirs_of(aio.StreamReset) == [
        aio.StreamReset(error_code=H3ErrorCode.H3_REQUEST_REJECTED, stream_id=0)
    ]


def test_an_unknown_stop_sending_code_does_not_discard_the_response(certificates):
    link = their_server(certificates)
    open_control(link)
    link.run(lambda: link.theirs_of(aio.HandshakeCompleted))
    stream_id = link.ours.send_request(POST)
    link.run(lambda: stream_bytes(link, stream_id))

    link.theirs.stop_stream(stream_id, RESERVED)
    link.theirs.send_stream_data(stream_id, headers_frame(OK), end_stream=True)
    link.run(limit=0.5)

    assert link.ours_of(ResponseReceived) == [
        ResponseReceived(stream_id, tuple(OK), True)
    ]
