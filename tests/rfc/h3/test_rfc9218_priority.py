"""RFC 9218 sections 4, 7, and 10: HTTP/3 priorities, updates and scheduling."""

import pytest

# Optional: aioquic needs pylsqpack, which has no free-threaded build yet.
pytest.importorskip("aioquic")

from aioquic.buffer import encode_uint_var
from aioquic.h3.connection import encode_frame
from support.aioquic_h3 import their_h3_client
from support.h3 import OK, REQUEST, connect_h3_client
from support.h3_frames import (
    SETTINGS,
    close_code,
    headers_frame,
    open_control,
    their_server,
)

from ngquic import ConnectionStateError
from ngquic.h3 import DataReceived, H3ErrorCode, Priority, RequestReceived

PRIORITY_UPDATE_REQUEST = 0xF0700
PRIORITY_UPDATE_PUSH = 0xF0701


def priority_update(stream_id: int, value: bytes) -> bytes:
    return encode_frame(PRIORITY_UPDATE_REQUEST, encode_uint_var(stream_id) + value)


@pytest.mark.xfail(
    strict=True,
    reason="RFC 9218 4: one invalid parameter discards the valid priority parameter",
)
@pytest.mark.parametrize(
    ("value", "expected"),
    [(b"u=8, i", Priority(3, True)), (b"u=1, i=1", Priority(1, False))],
    ids=["out-of-range-urgency", "wrong-incremental-type"],
)
def test_a_priority_header_ignores_only_the_invalid_parameter(
    h3_network, value, expected
):
    client = connect_h3_client(h3_network)
    server = h3_network.h3_server

    stream_id = client.send_request([*REQUEST, (b"priority", value)], end_stream=True)
    h3_network.run(lambda: h3_network.events_of(server, RequestReceived))

    assert server.get_stream_priority(stream_id) == expected


def test_a_request_without_priority_uses_the_defaults(h3_network):
    client = connect_h3_client(h3_network)
    server = h3_network.h3_server

    stream_id = client.send_request(REQUEST, end_stream=True)
    h3_network.run(lambda: h3_network.events_of(server, RequestReceived))

    assert server.get_stream_priority(stream_id) == Priority(3, False)


def test_the_latest_priority_update_before_request_headers_takes_precedence(
    certificates,
):
    link = their_h3_client(certificates, h3=False)
    open_control(
        link, SETTINGS + priority_update(0, b"u=1, i") + priority_update(0, b"i")
    )
    link.run(limit=0.5)

    link.theirs.send_stream_data(
        0, headers_frame([*REQUEST, (b"priority", b"u=7")]), end_stream=True
    )
    link.run(lambda: link.ours_of(RequestReceived))

    assert link.ours.get_stream_priority(0) == Priority(3, True)


def test_priority_update_on_a_request_stream_is_unexpected(certificates):
    link = their_h3_client(certificates, h3=False)
    open_control(link)

    link.theirs.send_stream_data(0, priority_update(0, b"u=1"))

    assert close_code(link) == (H3ErrorCode.H3_FRAME_UNEXPECTED, False)


@pytest.mark.parametrize(
    "frame",
    [
        priority_update(2, b"u=1"),
        priority_update(400, b"u=1"),
        encode_frame(PRIORITY_UPDATE_PUSH, b"\x00u=1"),
    ],
    ids=["non-request-id", "beyond-stream-limit", "unpromised-push"],
)
def test_priority_update_rejects_invalid_element_ids(certificates, frame):
    link = their_h3_client(certificates, h3=False)

    open_control(link, SETTINGS + frame)

    assert close_code(link) == (H3ErrorCode.H3_ID_ERROR, False)


@pytest.mark.parametrize(
    "frame_type",
    [
        pytest.param(PRIORITY_UPDATE_REQUEST, id="request"),
        pytest.param(
            PRIORITY_UPDATE_PUSH,
            id="push",
            marks=pytest.mark.xfail(
                strict=True,
                reason="RFC 9218 7.2: server push priority update gets H3_ID_ERROR",
            ),
        ),
    ],
)
def test_a_client_rejects_server_priority_updates(certificates, frame_type):
    link = their_server(certificates)

    open_control(link, SETTINGS + encode_frame(frame_type, b"\x00u=1"))

    assert close_code(link) == (H3ErrorCode.H3_FRAME_UNEXPECTED, False)


@pytest.mark.parametrize(
    ("priorities", "expected_order"),
    [((Priority(6), Priority(1)), [4, 0]), ((Priority(), Priority()), [0, 4])],
    ids=["urgency", "request-order"],
)
def test_non_incremental_responses_are_scheduled_by_priority(
    h3_network, priorities, expected_order
):
    client = connect_h3_client(h3_network)
    server = h3_network.h3_server
    ids = [client.send_request(REQUEST, end_stream=True) for _ in priorities]
    h3_network.run(lambda: len(h3_network.events_of(server, RequestReceived)) == 2)
    for stream_id, priority in zip(reversed(ids), reversed(priorities), strict=True):
        server.set_stream_priority(stream_id, priority)
        server.send_response(stream_id, OK)

    for stream_id in ids:
        server.send_data(stream_id, bytes(64_000), end_stream=True)
    h3_network.run()

    assert [
        event.stream_id
        for event in h3_network.events_of(client, DataReceived)
        if event.end_stream
    ] == expected_order


def test_equal_urgency_incremental_responses_share_bandwidth(h3_network):
    client = connect_h3_client(h3_network)
    server = h3_network.h3_server
    ids = [client.send_request(REQUEST, end_stream=True) for _ in range(2)]
    h3_network.run(lambda: len(h3_network.events_of(server, RequestReceived)) == 2)
    for stream_id in ids:
        server.set_stream_priority(stream_id, Priority(3, True))
        server.send_response(stream_id, OK)

    for stream_id in ids:
        server.send_data(stream_id, bytes(128_000), end_stream=True)
    h3_network.run(
        lambda: any(
            event.end_stream for event in h3_network.events_of(client, DataReceived)
        )
    )

    events = h3_network.events_of(client, DataReceived)
    first_end = next(index for index, event in enumerate(events) if event.end_stream)
    assert {event.stream_id for event in events[:first_end] if event.data} == set(ids)


def test_a_server_cannot_send_a_priority_update(h3_network):
    client = connect_h3_client(h3_network)
    server = h3_network.h3_server
    stream_id = client.send_request(REQUEST, end_stream=True)
    h3_network.run(lambda: h3_network.events_of(server, RequestReceived))

    with pytest.raises(ConnectionStateError, match="only clients"):
        server.send_priority_update(stream_id, b"u=1")


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (
            lambda client: client.set_stream_priority(0, Priority(1)),
            "schedule responses",
        ),
        (lambda client: client.get_stream_priority(0), "track request priorities"),
    ],
    ids=["set", "get"],
)
def test_a_client_cannot_use_server_priorities(h3_network, call, message):
    client = connect_h3_client(h3_network)
    client.send_request(REQUEST, end_stream=True)

    with pytest.raises(ConnectionStateError, match=f"only servers {message}"):
        call(client)
