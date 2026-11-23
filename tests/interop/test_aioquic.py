"""Interoperability with aioquic, an independent QUIC implementation.

Both stacks run in process on one virtual clock; this checks our wire
behavior against someone else's reading of RFC 9000/9001, which tests
between two copies of ngtcp2 cannot.
"""

import pytest

# Optional: aioquic needs pylsqpack, which has no free-threaded build yet.
pytest.importorskip("aioquic")

from aioquic.quic import events as aio
from support.aioquic import our_client, their_client
from support.network import ALPN

from ngquic import (
    ConnectionTerminated,
    DatagramReceived,
    HandshakeCompleted,
    StreamDataReceived,
    TransportConfig,
)

PAYLOAD = bytes(range(256)) * 1024


def test_our_client_completes_a_handshake_with_aioquic(client_tls, aio_server_config):
    link = our_client(client_tls, aio_server_config)

    link.run(
        lambda: (
            link.ours_of(HandshakeCompleted) and link.theirs_of(aio.HandshakeCompleted)
        )
    )

    assert link.ours_of(HandshakeCompleted)[0].alpn_protocol == ALPN
    assert link.theirs_of(aio.HandshakeCompleted)[0].alpn_protocol == ALPN


def test_our_client_streams_to_aioquic_and_back(client_tls, aio_server_config):
    link = our_client(client_tls, aio_server_config)
    link.run(lambda: link.ours_of(HandshakeCompleted))
    stream_id = link.ours.open_stream()

    link.ours.send_stream_data(stream_id, PAYLOAD, end_stream=True)
    link.run(lambda: any(e.end_stream for e in link.theirs_of(aio.StreamDataReceived)))
    link.theirs.send_stream_data(
        stream_id,
        b"".join(e.data for e in link.theirs_of(aio.StreamDataReceived)),
        end_stream=True,
    )
    link.run(lambda: any(e.end_stream for e in link.ours_of(StreamDataReceived)))

    assert b"".join(e.data for e in link.ours_of(StreamDataReceived)) == PAYLOAD


def test_aioquic_client_streams_to_our_server(server_tls, aio_client_config):
    link = their_client(server_tls, aio_client_config)
    link.run(lambda: link.theirs_of(aio.HandshakeCompleted))
    stream_id = link.theirs.get_next_available_stream_id()

    link.theirs.send_stream_data(stream_id, PAYLOAD, end_stream=True)
    link.run(lambda: any(e.end_stream for e in link.ours_of(StreamDataReceived)))
    link.ours.send_stream_data(
        stream_id,
        b"".join(e.data for e in link.ours_of(StreamDataReceived)),
        end_stream=True,
    )
    link.run(lambda: any(e.end_stream for e in link.theirs_of(aio.StreamDataReceived)))

    assert b"".join(e.data for e in link.theirs_of(aio.StreamDataReceived)) == PAYLOAD


def test_datagrams_cross_between_stacks(client_tls, aio_server_config):
    link = our_client(
        client_tls, aio_server_config, TransportConfig(max_datagram_frame_size=1200)
    )
    link.run(
        lambda: (
            link.ours_of(HandshakeCompleted) and link.theirs_of(aio.HandshakeCompleted)
        )
    )

    link.ours.send_datagram(b"ping")
    link.run(lambda: link.theirs_of(aio.DatagramFrameReceived))
    link.theirs.send_datagram_frame(b"pong")
    link.run(lambda: link.ours_of(DatagramReceived))

    assert link.theirs_of(aio.DatagramFrameReceived)[0].data == b"ping"
    assert link.ours_of(DatagramReceived)[0].data == b"pong"


def test_close_from_aioquic_reaches_our_client(client_tls, aio_server_config):
    link = our_client(client_tls, aio_server_config)
    link.run(
        lambda: (
            link.ours_of(HandshakeCompleted) and link.theirs_of(aio.HandshakeCompleted)
        )
    )
    link.run(limit=0.5)

    link.theirs.close(error_code=7, reason_phrase="bye")
    link.run(lambda: link.ours_of(ConnectionTerminated))

    terminated = link.ours_of(ConnectionTerminated)[0]
    assert (terminated.error_code, terminated.reason_phrase, terminated.by_peer) == (
        7,
        b"bye",
        True,
    )


def test_our_close_reaches_aioquic(server_tls, aio_client_config):
    link = their_client(server_tls, aio_client_config)
    link.run(lambda: link.theirs_of(aio.HandshakeCompleted))
    link.run(limit=0.5)

    link.ours.close(9, b"done")
    link.run(lambda: link.theirs_of(aio.ConnectionTerminated))

    terminated = link.theirs_of(aio.ConnectionTerminated)[0]
    assert (terminated.error_code, terminated.reason_phrase) == (9, "done")
