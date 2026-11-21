"""HTTP/3 interoperability with aioquic.h3, an independent HTTP/3 and QPACK stack.

Both sides run in process on the virtual clock of ``test_interop_aioquic``.
aioquic's H3 layer is fed its QUIC events by hand, as its API expects.
"""

import pytest

# Optional: aioquic needs pylsqpack, which has no free-threaded build yet.
pytest.importorskip("aioquic")

from aioquic.h3 import events as aio_h3
from aioquic.quic import events as aio
from support.aioquic_h3 import our_h3_client, their_h3_client
from support.h3 import OK

from ngquic import (
    ConnectionTerminated,
)
from ngquic.h3 import (
    DatagramReceived,
    DataReceived,
    H3ErrorCode,
    RequestReceived,
    ResponseReceived,
)

BODY = bytes(range(256)) * 512
REQUEST = [
    (b":method", b"POST"),
    (b":scheme", b"https"),
    (b":authority", b"localhost"),
    (b":path", b"/echo"),
]


def test_our_client_requests_from_an_aioquic_server(certificates):
    link = our_h3_client(certificates)
    client = link.ours
    link.run(lambda: link.theirs_of(aio.HandshakeCompleted))
    assert link.their_h3 is not None

    stream_id = client.send_request(REQUEST)
    client.send_data(stream_id, BODY, end_stream=True)
    link.run(lambda: any(e.stream_ended for e in link.their_h3_of(aio_h3.DataReceived)))
    link.their_h3.send_headers(stream_id, [(b":status", b"200")])
    link.their_h3.send_data(
        stream_id,
        b"".join(e.data for e in link.their_h3_of(aio_h3.DataReceived))[::-1],
        end_stream=True,
    )
    link.run(lambda: any(e.end_stream for e in link.ours_of(DataReceived)))

    request = link.their_h3_of(aio_h3.HeadersReceived)[0]
    assert request.headers == REQUEST
    assert link.ours_of(ResponseReceived)[0].headers == ((b":status", b"200"),)
    assert b"".join(e.data for e in link.ours_of(DataReceived)) == BODY[::-1]


def test_an_aioquic_client_requests_from_our_server(certificates):
    link = their_h3_client(certificates)
    server = link.ours
    link.run(lambda: link.theirs_of(aio.HandshakeCompleted))
    assert link.their_h3 is not None
    stream_id = link.theirs.get_next_available_stream_id()

    link.their_h3.send_headers(stream_id, REQUEST)
    link.their_h3.send_data(stream_id, BODY, end_stream=True)
    link.run(lambda: any(e.end_stream for e in link.ours_of(DataReceived)))
    server.send_response(stream_id, [(b":status", b"200"), (b"x-echo", b"1")])
    server.send_data(
        stream_id,
        b"".join(e.data for e in link.ours_of(DataReceived)),
        end_stream=True,
    )
    link.run(lambda: any(e.stream_ended for e in link.their_h3_of(aio_h3.DataReceived)))

    assert link.ours_of(RequestReceived)[0].headers == tuple(REQUEST)
    assert link.their_h3_of(aio_h3.HeadersReceived)[0].headers == [
        (b":status", b"200"),
        (b"x-echo", b"1"),
    ]
    assert b"".join(e.data for e in link.their_h3_of(aio_h3.DataReceived)) == BODY


def test_a_second_control_stream_closes_with_h3_stream_creation_error(certificates):
    link = their_h3_client(certificates, h3=False)
    link.run(lambda: link.theirs_of(aio.HandshakeCompleted))

    # RFC 9114 6.2.1: a second control stream is H3_STREAM_CREATION_ERROR.
    for _ in range(2):
        stream_id = link.theirs.get_next_available_stream_id(is_unidirectional=True)
        link.theirs.send_stream_data(stream_id, b"\x00\x04\x00")
    link.run(lambda: link.ours_of(ConnectionTerminated))

    terminated = link.ours_of(ConnectionTerminated)[0]
    assert (terminated.error_code, terminated.by_peer) == (
        H3ErrorCode.H3_STREAM_CREATION_ERROR,
        False,
    )


def test_http_datagrams_cross_with_an_aioquic_server(certificates):
    link = our_h3_client(certificates, datagrams=True)
    client = link.ours
    link.run(lambda: client.remote_settings is not None)
    assert link.their_h3 is not None

    stream_id = client.send_request(REQUEST)
    # aioquic 1.9 drops a datagram for a stream it has not seen open, which
    # RFC 9297 2.1 allows.
    link.run(lambda: link.their_h3_of(aio_h3.HeadersReceived))
    client.send_datagram(stream_id, b"ping")
    link.run(lambda: link.their_h3_of(aio_h3.DatagramReceived))
    # aioquic 1.9 sends datagrams on a stream only after its response.
    link.their_h3.send_headers(stream_id, OK)
    link.their_h3.send_datagram(stream_id, b"pong")
    link.run(lambda: link.ours_of(DatagramReceived))

    received = link.their_h3_of(aio_h3.DatagramReceived)[0]
    assert (received.stream_id, received.data) == (stream_id, b"ping")
    assert link.ours_of(DatagramReceived) == [DatagramReceived(stream_id, b"pong")]


@pytest.mark.parametrize(
    ("payload", "error_code"),
    [
        # RFC 9297 2.1: too short for a quarter stream ID.
        (b"", H3ErrorCode.H3_DATAGRAM_ERROR),
        (b"\x40", H3ErrorCode.H3_DATAGRAM_ERROR),
        # Quarter stream ID 2^60, above the largest legal one.
        (b"\xd0" + bytes(7), H3ErrorCode.H3_DATAGRAM_ERROR),
        # Stream 400, beyond the 100 requests the server allows.
        (b"\x40\x64", H3ErrorCode.H3_ID_ERROR),
    ],
)
def test_an_invalid_http_datagram_closes_the_connection(
    certificates, payload, error_code
):
    link = their_h3_client(certificates, h3=False, datagrams=True)
    link.run(lambda: link.theirs_of(aio.HandshakeCompleted))

    link.theirs.send_datagram_frame(payload)
    link.run(lambda: link.ours_of(ConnectionTerminated))

    terminated = link.ours_of(ConnectionTerminated)[0]
    assert (terminated.error_code, terminated.by_peer) == (error_code, False)


def test_an_http_datagram_for_an_unopened_request_is_dropped(certificates):
    link = their_h3_client(certificates, h3=False, datagrams=True)
    link.run(lambda: link.theirs_of(aio.HandshakeCompleted))

    link.theirs.send_datagram_frame(b"\x01late")
    link.run()

    assert not link.ours_of(ConnectionTerminated)
    assert not link.ours_of(DatagramReceived)
