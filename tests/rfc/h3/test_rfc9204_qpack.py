"""RFC 9204 sections 2-5 and 7.4: QPACK streams, field sections and errors."""

import json

import pytest

# Optional: aioquic needs pylsqpack, which has no free-threaded build yet.
pytest.importorskip("aioquic")

import pylsqpack
from aioquic.buffer import Buffer
from aioquic.h3.connection import (
    FrameType,
    Setting,
    StreamType,
    encode_frame,
    encode_settings,
)
from aioquic.quic import events as aio
from support.aioquic_h3 import their_h3_client
from support.h3 import OK, REQUEST
from support.h3_frames import (
    close_code,
    headers_frame,
    open_control,
    open_uni,
    stream_bytes,
    their_server,
)

from ngquic import TransportConfig
from ngquic.h3 import (
    H3Config,
    H3ErrorCode,
    NeverIndexedHeader,
    RequestReceived,
    ResponseReceived,
)

CAPACITY_64 = b"\x3f\x21"
INSERT_X = b"\x41x\x01v"

QPACK_STREAMS = [StreamType.QPACK_ENCODER, StreamType.QPACK_DECODER]


@pytest.mark.parametrize("stream_type", QPACK_STREAMS, ids=["encoder", "decoder"])
def test_a_second_qpack_stream_of_the_same_type_is_rejected(certificates, stream_type):
    link = their_h3_client(certificates, h3=False)

    open_uni(link, bytes([stream_type]))
    open_uni(link, bytes([stream_type]))

    assert close_code(link) == (H3ErrorCode.H3_STREAM_CREATION_ERROR, False)


@pytest.mark.parametrize("stream_type", QPACK_STREAMS, ids=["encoder", "decoder"])
def test_a_qpack_stream_fin_is_a_critical_stream_error(certificates, stream_type):
    link = their_h3_client(certificates, h3=False)

    open_uni(link, bytes([stream_type]), end_stream=True)

    assert close_code(link) == (H3ErrorCode.H3_CLOSED_CRITICAL_STREAM, False)


@pytest.mark.parametrize("stream_type", QPACK_STREAMS, ids=["encoder", "decoder"])
def test_a_qpack_stream_reset_is_a_critical_stream_error(certificates, stream_type):
    link = their_h3_client(certificates, h3=False)
    stream_id = open_uni(link, bytes([stream_type]))
    link.run(limit=0.5)

    link.theirs.reset_stream(stream_id, H3ErrorCode.H3_NO_ERROR)

    assert close_code(link) == (H3ErrorCode.H3_CLOSED_CRITICAL_STREAM, False)


@pytest.mark.parametrize(
    "instructions",
    [
        b"\x3f\xe2\x1f",
        b"\x3f\x00" + INSERT_X,
        CAPACITY_64 + b"\xff\x24\x00",
        CAPACITY_64 + INSERT_X + b"\x41x\x01w\x01",
    ],
    ids=[
        "capacity-over-limit",
        "entry-larger-than-capacity",
        "invalid-static-index",
        "evicted-dynamic-index",
    ],
)
def test_invalid_qpack_encoder_instructions_close_the_connection(
    certificates, instructions
):
    link = their_h3_client(certificates, h3=False)

    open_uni(link, bytes([StreamType.QPACK_ENCODER]) + instructions)

    assert close_code(link) == (H3ErrorCode.QPACK_ENCODER_STREAM_ERROR, False)


@pytest.mark.parametrize(
    "instruction",
    [b"\x00", b"\x01", b"\x80"],
    ids=[
        "zero-insert-increment",
        "unsent-insert-increment",
        "no-section-to-acknowledge",
    ],
)
def test_invalid_qpack_decoder_instructions_close_the_connection(
    certificates, instruction
):
    link = their_h3_client(certificates, h3=False)

    open_uni(link, bytes([StreamType.QPACK_DECODER]) + instruction)

    assert close_code(link) == (H3ErrorCode.QPACK_DECODER_STREAM_ERROR, False)


@pytest.mark.parametrize(
    "block",
    [b"\x00\x00\xff\x24", b"\x00\x00\x80", b"\xff\x02\x00", b"\x00\x80"],
    ids=[
        "invalid-static-index",
        "dynamic-reference-with-zero-required-count",
        "invalid-encoded-insert-count",
        "negative-base",
    ],
)
def test_invalid_qpack_field_sections_close_with_decompression_failed(
    certificates, block
):
    link = their_h3_client(certificates, h3=False)
    open_control(link)

    link.theirs.send_stream_data(0, encode_frame(FrameType.HEADERS, block))

    assert close_code(link) == (H3ErrorCode.QPACK_DECOMPRESSION_FAILED, False)


def test_an_encoder_cannot_reference_an_evicted_entry_in_a_field_section(certificates):
    link = their_h3_client(certificates, h3=False)
    open_control(link)
    open_uni(
        link, bytes([StreamType.QPACK_ENCODER]) + CAPACITY_64 + INSERT_X + b"\x41x\x01w"
    )
    link.run(limit=0.5)

    link.theirs.send_stream_data(0, encode_frame(FrameType.HEADERS, b"\x03\x00\x81"))

    assert close_code(link) == (H3ErrorCode.QPACK_DECOMPRESSION_FAILED, False)


def dynamic_request(prefix: bytes = b"\x02\x00") -> bytes:
    _, static = pylsqpack.Encoder().encode(0, REQUEST)
    return encode_frame(FrameType.HEADERS, prefix + static[2:] + b"\x80")


def test_a_request_waits_for_qpack_inserts_before_delivery(certificates):
    link = their_h3_client(certificates, h3=False)
    open_control(link)
    stream_id = open_uni(link, bytes([StreamType.QPACK_ENCODER]) + CAPACITY_64)

    link.theirs.send_stream_data(0, dynamic_request(), end_stream=True)
    link.run(limit=0.5)
    before_insert = link.ours_of(RequestReceived)
    link.theirs.send_stream_data(stream_id, INSERT_X)
    link.run(lambda: link.ours_of(RequestReceived))

    assert (before_insert, link.ours_of(RequestReceived)) == (
        [],
        [RequestReceived(0, (*REQUEST, (b"x", b"v")), True)],
    )


def test_qpack_accepts_duplicate_dynamic_table_entries(certificates):
    link = their_h3_client(certificates, h3=False)
    open_control(link)
    open_uni(link, bytes([StreamType.QPACK_ENCODER]) + b"\x3f\x61" + INSERT_X + b"\x00")

    link.theirs.send_stream_data(0, dynamic_request(b"\x03\x00"), end_stream=True)
    link.run(lambda: link.ours_of(RequestReceived))

    assert link.ours_of(RequestReceived) == [
        RequestReceived(0, (*REQUEST, (b"x", b"v")), True)
    ]


def test_a_dynamic_field_section_is_acknowledged_on_the_decoder_stream(certificates):
    link = their_h3_client(certificates, h3=False)
    open_control(link)
    open_uni(link, bytes([StreamType.QPACK_ENCODER]) + CAPACITY_64 + INSERT_X)

    link.theirs.send_stream_data(0, dynamic_request(), end_stream=True)
    link.run(limit=0.5)

    assert stream_bytes(link, 11).startswith(b"\x03")
    assert stream_bytes(link, 11).endswith(b"\x80")


def test_a_reset_cancels_a_blocked_qpack_field_section(certificates):
    link = their_h3_client(certificates, h3=False)
    open_control(link)
    link.theirs.send_stream_data(0, dynamic_request())
    link.run(limit=0.5)

    link.theirs.reset_stream(0, H3ErrorCode.H3_REQUEST_CANCELLED)
    link.run(limit=0.5)

    assert stream_bytes(link, 11) == b"\x03\x40"


def test_a_zero_peer_table_capacity_prohibits_encoder_instructions(certificates):
    link = their_server(certificates)
    open_control(
        link,
        encode_frame(
            FrameType.SETTINGS,
            encode_settings(
                {
                    Setting.QPACK_MAX_TABLE_CAPACITY: 0,
                    Setting.QPACK_BLOCKED_STREAMS: 100,
                }
            ),
        ),
    )
    link.run(lambda: link.ours.remote_settings is not None)
    headers = [*REQUEST, (b"user-agent", b"test client")]

    for _ in range(3):
        link.ours.send_request(headers, end_stream=True)
    link.run(limit=0.5)

    assert stream_bytes(link, 6) in (b"", b"\x02")


def test_decoder_rejects_more_blocked_streams_than_it_advertised(certificates):
    link = their_server(certificates, h3=H3Config(qpack_blocked_streams=1))
    open_control(link)
    link.run(lambda: link.ours.remote_settings is not None)
    ids = [link.ours.send_request(REQUEST, end_stream=True) for _ in range(2)]
    link.run(lambda: all(stream_bytes(link, stream_id) for stream_id in ids))
    blocked_response = encode_frame(FrameType.HEADERS, b"\x02\x00\xd9\x80")

    for stream_id in ids:
        link.theirs.send_stream_data(stream_id, blocked_response, end_stream=True)

    assert close_code(link) == (H3ErrorCode.QPACK_DECOMPRESSION_FAILED, False)


def test_qpack_streams_are_accepted_when_the_dynamic_table_is_disabled(certificates):
    link = their_server(
        certificates, h3=H3Config(qpack_max_dtable_capacity=0, qpack_blocked_streams=0)
    )
    open_control(link)
    link.run(lambda: link.ours.remote_settings is not None)
    stream_id = link.ours.send_request(REQUEST, end_stream=True)
    link.run(lambda: stream_bytes(link, stream_id))

    for stream_type in QPACK_STREAMS:
        open_uni(link, bytes([stream_type]))
    link.theirs.send_stream_data(stream_id, headers_frame(OK), end_stream=True)
    link.run(limit=0.5)

    assert link.ours_of(ResponseReceived) == [
        ResponseReceived(stream_id, tuple(OK), True)
    ]


def test_never_indexed_trailers_carry_the_qpack_n_bit(certificates):
    link = their_server(certificates)
    open_control(link)
    link.run(lambda: link.ours.remote_settings is not None)
    stream_id = link.ours.send_request(REQUEST)

    link.ours.send_trailers(stream_id, [NeverIndexedHeader(b"x-private", b"value")])
    link.run(limit=0.5)

    frames = Buffer(data=stream_bytes(link, stream_id))
    assert frames.pull_uint_var() == FrameType.HEADERS
    frames.pull_bytes(frames.pull_uint_var())
    assert frames.pull_uint_var() == FrameType.HEADERS
    trailers = frames.pull_bytes(frames.pull_uint_var())
    assert trailers[2] & 0xF0 == 0x30


def test_a_field_section_can_use_a_62_bit_delta_base(certificates):
    link = their_h3_client(certificates, h3=False)
    open_control(link)
    _, static = pylsqpack.Encoder().encode(0, REQUEST)
    delta_base = b"\x7f\x80" + b"\xff" * 7 + b"\x3f"

    link.theirs.send_stream_data(
        0,
        encode_frame(FrameType.HEADERS, b"\x00" + delta_base + static[2:]),
        end_stream=True,
    )
    link.run(limit=0.5)

    assert link.ours_of(RequestReceived) == [RequestReceived(0, tuple(REQUEST), True)]


def test_an_encoder_cannot_block_requests_when_the_peer_allows_zero(certificates):
    link = their_server(certificates)
    settings = encode_settings({Setting.QPACK_MAX_TABLE_CAPACITY: 4096})
    open_control(link, encode_frame(FrameType.SETTINGS, settings))
    link.run(lambda: link.ours.remote_settings is not None)
    fields = [*REQUEST, (b"user-agent", b"repeated")]

    stream_ids = [link.ours.send_request(fields, end_stream=True) for _ in range(3)]
    link.run(limit=0.5)

    required_insert_counts = []
    for stream_id in stream_ids:
        frame = Buffer(data=stream_bytes(link, stream_id))
        assert frame.pull_uint_var() == FrameType.HEADERS
        required_insert_counts.append(frame.pull_bytes(frame.pull_uint_var())[0])
    assert required_insert_counts == [0, 0, 0]


def test_only_one_qpack_stream_of_each_type_is_sent(certificates):
    link = their_server(certificates)
    open_control(link)

    link.run(limit=0.5)

    stream_ids = {
        event.stream_id
        for event in link.theirs_of(aio.StreamDataReceived)
        if event.stream_id % 4 == 2
    }
    stream_types = [
        Buffer(data=stream_bytes(link, stream_id)).pull_uint_var()
        for stream_id in stream_ids
    ]
    assert all(stream_types.count(stream_type) <= 1 for stream_type in QPACK_STREAMS)


@pytest.mark.parametrize(
    ("stream_type", "error_code"),
    [
        (StreamType.QPACK_ENCODER, H3ErrorCode.QPACK_ENCODER_STREAM_ERROR),
        (StreamType.QPACK_DECODER, H3ErrorCode.QPACK_DECODER_STREAM_ERROR),
    ],
    ids=["encoder", "decoder"],
)
def test_overflowing_qpack_stream_integers_use_the_directional_error(
    certificates, stream_type, error_code
):
    link = their_h3_client(certificates, h3=False)
    instruction = b"\x3f" + b"\xff" * 8 + b"\x40"

    open_uni(link, bytes([stream_type]) + instruction)

    assert close_code(link) == (error_code, False)


def test_an_overflowing_qpack_field_section_integer_is_a_decompression_error(
    certificates,
):
    link = their_h3_client(certificates, h3=False)
    open_control(link)
    block = b"\x00\x7f" + b"\xff" * 8 + b"\x40"

    link.theirs.send_stream_data(0, encode_frame(FrameType.HEADERS, block))

    assert close_code(link) == (H3ErrorCode.QPACK_DECOMPRESSION_FAILED, False)


def test_blocked_header_bytes_hold_stream_credit_until_inserts_arrive(certificates):
    records = []
    link = their_server(
        certificates,
        transport=TransportConfig(
            max_stream_data_bidi_local=512,
            max_stream_window=None,
            qlog=lambda data, final: records.append(data),
        ),
    )
    open_control(link)
    encoder_stream = open_uni(link, bytes([StreamType.QPACK_ENCODER]) + CAPACITY_64)
    link.run(lambda: link.ours.remote_settings is not None)
    stream_id = link.ours.send_request(REQUEST, end_stream=True)
    link.run(lambda: stream_bytes(link, stream_id))
    _, static = pylsqpack.Encoder().encode(0, [*OK, (b"x-padding", b"a" * 720)])
    block = encode_frame(FrameType.HEADERS, b"\x02\x00" + static[2:] + b"\x80")
    assert 256 < len(block) <= 512

    link.theirs.send_stream_data(stream_id, block)
    link.run(limit=0.5)
    blocked_records = len(records)
    link.theirs.send_stream_data(encoder_stream, INSERT_X)
    link.run(limit=0.5)

    def credit_updates(chunks):
        entries = (
            json.loads(record)
            for record in b"".join(chunks).split(b"\x1e")
            if record.strip()
        )
        return [
            frame["maximum"]
            for entry in entries
            if entry.get("name") == "transport:packet_sent"
            for frame in entry["data"]["frames"]
            if frame["frame_type"] == "max_stream_data"
            and frame["stream_id"] == stream_id
        ]

    assert (
        credit_updates(records[:blocked_records]),
        credit_updates(records[blocked_records:]),
    ) == (
        [],
        [512 + len(block)],
    )
