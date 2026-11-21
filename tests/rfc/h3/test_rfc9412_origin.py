"""RFC 9412 sections 2-2.1: ORIGIN direction, stream placement and wire layout."""

import pytest

# Optional: aioquic needs pylsqpack, which has no free-threaded build yet.
pytest.importorskip("aioquic")

from aioquic.h3.connection import encode_frame
from aioquic.quic import events as aio
from support.aioquic_h3 import their_h3_client
from support.h3 import OK, REQUEST
from support.h3_frames import (
    SETTINGS,
    close_code,
    headers_frame,
    open_control,
    stream_bytes,
    their_server,
)

from ngquic.h3 import GoAwayReceived, H3ErrorCode, OriginReceived, ResponseReceived

ORIGIN = 0x0C
LOCALHOST = b"https://localhost"
ORIGIN_FRAME = encode_frame(ORIGIN, len(LOCALHOST).to_bytes(2, "big") + LOCALHOST)


def test_an_empty_origin_frame_is_reported(certificates):
    link = their_server(certificates)

    open_control(link, SETTINGS + encode_frame(ORIGIN, b""))
    link.run(limit=0.5)

    assert link.ours_of(OriginReceived) == [OriginReceived(())]


def test_origins_from_a_client_are_ignored(certificates):
    link = their_h3_client(certificates, h3=False)
    goaway = b"\x07\x01\x00"

    open_control(link, SETTINGS + ORIGIN_FRAME + goaway)
    link.run(lambda: link.ours_of(GoAwayReceived))

    assert link.ours_of(OriginReceived) == []


def test_an_origin_frame_on_a_request_stream_is_ignored(certificates):
    link = their_server(certificates)
    open_control(link)
    link.run(lambda: link.theirs_of(aio.HandshakeCompleted))
    stream_id = link.ours.send_request(REQUEST, end_stream=True)
    link.run(lambda: stream_bytes(link, stream_id))

    link.theirs.send_stream_data(
        stream_id, ORIGIN_FRAME + headers_frame(OK), end_stream=True
    )
    link.run(limit=0.5)

    assert (link.ours_of(OriginReceived), link.ours_of(ResponseReceived)) == (
        [],
        [ResponseReceived(stream_id, tuple(OK), True)],
    )


@pytest.mark.parametrize(
    "payload", [b"\x00", b"\x00\x02a"], ids=["partial-length", "partial-origin"]
)
def test_truncated_origin_entries_are_a_frame_error(certificates, payload):
    link = their_server(certificates)

    open_control(link, SETTINGS + encode_frame(ORIGIN, payload))

    assert close_code(link) == (H3ErrorCode.H3_FRAME_ERROR, False)
