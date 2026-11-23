"""Raw HTTP/3 frames and streams written by an aioquic peer."""

import pylsqpack
from aioquic.buffer import Buffer
from aioquic.h3.connection import (
    FrameType,
    StreamType,
    encode_frame,
    parse_settings,
)
from aioquic.quic import events as aio
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.connection import QuicConnection
from aioquic.quic.packet import pull_quic_header

from ngquic import (
    ConnectionTerminated,
    Endpoint,
    Role,
    TransportConfig,
)
from ngquic.h3 import H3Config
from support.aioquic import segments
from support.aioquic_h3 import H3Link
from support.h3 import h3_tls
from support.network import CLIENT_ADDR, SERVER_ADDR

SETTINGS = encode_frame(FrameType.SETTINGS, b"")


RESERVED = 0x21


def their_server(
    certificates,
    *,
    h3: H3Config | None = None,
    transport: TransportConfig | None = None,
) -> H3Link:
    config = QuicConfiguration(is_client=False, alpn_protocols=["h3"])
    config.load_cert_chain(certificates.cert, certificates.key)
    endpoint = Endpoint(CLIENT_ADDR)
    ours = endpoint.connect(
        SERVER_ADDR,
        1.0,
        tls=h3_tls(certificates, Role.CLIENT),
        server_name="localhost",
        transport=transport,
        h3=H3Config() if h3 is None else h3,
    )
    first = ours.datagrams_to_send(1.0)
    header = pull_quic_header(Buffer(data=first[0].data), host_cid_length=8)
    theirs = QuicConnection(
        configuration=config, original_destination_connection_id=header.destination_cid
    )
    for transmit in first:
        for datagram in segments(transmit):
            theirs.receive_datagram(datagram, CLIENT_ADDR, 1.0)
    return H3Link(ours, theirs, endpoint, 1.0)


def open_uni(link: H3Link, data: bytes, *, end_stream: bool = False) -> int:
    stream_id = link.theirs.get_next_available_stream_id(is_unidirectional=True)
    link.theirs.send_stream_data(stream_id, data, end_stream=end_stream)
    return stream_id


def open_control(link: H3Link, frames: bytes = SETTINGS, *, end_stream: bool = False):
    return open_uni(link, bytes([StreamType.CONTROL]) + frames, end_stream=end_stream)


def stream_bytes(link: H3Link, stream_id: int) -> bytes:
    return b"".join(
        event.data
        for event in link.theirs_of(aio.StreamDataReceived)
        if event.stream_id == stream_id
    )


def close_code(link: H3Link) -> tuple[int, bool] | None:
    link.run(limit=0.5)
    events = link.ours_of(ConnectionTerminated)
    return (events[0].error_code, events[0].by_peer) if events else None


def peer_settings(link: H3Link) -> dict[int, int]:
    stream_id = 2 if link.ours.is_client else 3
    link.run(lambda: stream_bytes(link, stream_id))
    data = Buffer(data=stream_bytes(link, stream_id))
    assert (data.pull_uint_var(), data.pull_uint_var()) == (
        StreamType.CONTROL,
        FrameType.SETTINGS,
    )
    return parse_settings(data.pull_bytes(data.pull_uint_var()))


def headers_frame(fields: list[tuple[bytes, bytes]]) -> bytes:
    _, block = pylsqpack.Encoder().encode(0, fields)
    return encode_frame(FrameType.HEADERS, block)
