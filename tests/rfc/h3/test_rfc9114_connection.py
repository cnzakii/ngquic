"""RFC 9114 sections 3.2, 5.2, 6-9: setup, shutdown, streams and frames."""

import pytest

# Optional: aioquic needs pylsqpack, which has no free-threaded build yet.
pytest.importorskip("aioquic")

from aioquic.buffer import encode_uint_var
from aioquic.h3.connection import (
    FrameType,
    encode_frame,
    encode_settings,
)
from aioquic.quic import events as aio
from support.aioquic_h3 import their_h3_client
from support.h3 import REQUEST, connect_h3_client, resumable_ticket
from support.h3_frames import (
    RESERVED,
    SETTINGS,
    close_code,
    open_control,
    open_uni,
    peer_settings,
    stream_bytes,
    their_server,
)

from ngquic import (
    ConnectionTerminated,
    HandshakeCompleted,
    TransportConfig,
)
from ngquic.h3 import GoAwayReceived, H3Config, H3ErrorCode


@pytest.mark.parametrize("is_client", [True, False], ids=["client", "server"])
def test_settings_are_sent_first_without_receiving_peer_settings(
    certificates, is_client
):
    link = (
        their_server(certificates)
        if is_client
        else their_h3_client(certificates, h3=False)
    )

    settings = peer_settings(link)

    assert (bool(settings), link.ours.remote_settings) == (True, None)


@pytest.mark.xfail(
    strict=True, reason="RFC 9114 7.2.4.1: outgoing SETTINGS omit reserved identifiers"
)
def test_settings_contain_a_reserved_identifier(certificates):
    link = their_h3_client(certificates, h3=False)

    settings = peer_settings(link)

    assert any(value >= 0x21 and (value - 0x21) % 0x1F == 0 for value in settings)


@pytest.mark.parametrize(
    "frame",
    [encode_frame(FrameType.GOAWAY, b"\x00"), encode_frame(RESERVED, b"")],
    ids=["known", "reserved"],
)
def test_control_stream_requires_settings_first(certificates, frame):
    link = their_h3_client(certificates, h3=False)

    open_control(link, frame)

    assert close_code(link) == (H3ErrorCode.H3_MISSING_SETTINGS, False)


@pytest.mark.parametrize(
    "frame_type",
    [
        FrameType.DATA,
        FrameType.HEADERS,
        FrameType.SETTINGS,
        FrameType.PUSH_PROMISE,
        0x6,
    ],
    ids=["data", "headers", "second-settings", "push-promise", "reserved-http2-ping"],
)
def test_control_stream_rejects_unexpected_frames(certificates, frame_type):
    link = their_h3_client(certificates, h3=False)

    open_control(link, SETTINGS + encode_frame(frame_type, b""))

    assert close_code(link) == (H3ErrorCode.H3_FRAME_UNEXPECTED, False)


@pytest.mark.parametrize(
    "frame_type",
    [
        FrameType.SETTINGS,
        FrameType.CANCEL_PUSH,
        FrameType.PUSH_PROMISE,
        FrameType.GOAWAY,
        FrameType.MAX_PUSH_ID,
    ],
    ids=["settings", "cancel-push", "push-promise", "goaway", "max-push-id"],
)
def test_a_request_stream_rejects_frames_not_permitted_there(certificates, frame_type):
    link = their_h3_client(certificates, h3=False)
    open_control(link)

    link.theirs.send_stream_data(0, encode_frame(frame_type, b"\x00"))

    assert close_code(link) == (H3ErrorCode.H3_FRAME_UNEXPECTED, False)


def test_an_http2_only_setting_closes_with_h3_settings_error(certificates):
    link = their_h3_client(certificates, h3=False)

    open_control(link, encode_frame(FrameType.SETTINGS, b"\x02\x00"))

    assert close_code(link) == (H3ErrorCode.H3_SETTINGS_ERROR, False)


def test_unknown_settings_do_not_hide_recognized_settings(certificates):
    link = their_h3_client(certificates, h3=False)
    payload = encode_settings({RESERVED: 42, 0x6: 8192})

    open_control(link, encode_frame(FrameType.SETTINGS, payload))
    link.run(lambda: link.ours.remote_settings is not None)

    assert link.ours.remote_settings is not None
    assert link.ours.remote_settings.max_field_section_size == 8192


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"\x40", id="short-varint"),
        pytest.param(
            b"\x00\x00",
            id="extra-byte",
            marks=pytest.mark.xfail(
                strict=True, reason="RFC 9114 7.1: GOAWAY accepts bytes after the ID"
            ),
        ),
    ],
)
def test_goaway_payload_must_contain_exactly_one_complete_id(certificates, payload):
    link = their_h3_client(certificates, h3=False)

    open_control(link, SETTINGS + encode_frame(FrameType.GOAWAY, payload))

    assert close_code(link) == (H3ErrorCode.H3_FRAME_ERROR, False)


def test_goaway_id_cannot_increase(certificates):
    link = their_h3_client(certificates, h3=False)
    control = open_control(link, SETTINGS + encode_frame(FrameType.GOAWAY, b"\x04"))
    link.run(lambda: link.ours_of(GoAwayReceived))

    link.theirs.send_stream_data(control, encode_frame(FrameType.GOAWAY, b"\x05"))

    assert close_code(link) == (H3ErrorCode.H3_ID_ERROR, False)


def test_a_server_goaway_id_must_identify_a_request_stream(certificates):
    link = their_server(certificates)

    open_control(link, SETTINGS + encode_frame(FrameType.GOAWAY, b"\x01"))

    assert close_code(link) == (H3ErrorCode.H3_ID_ERROR, False)


def test_a_client_lets_the_server_open_no_bidirectional_stream(certificates):
    link = their_server(certificates)
    link.run(lambda: link.theirs_of(aio.HandshakeCompleted))

    # Whatever TransportConfig.max_streams_bidi says: servers open none.
    assert link.theirs._remote_max_streams_bidi == 0


def test_a_client_cannot_open_a_push_stream(certificates):
    link = their_h3_client(certificates, h3=False)
    open_control(link)

    open_uni(link, b"\x01\x00")

    assert close_code(link) == (H3ErrorCode.H3_STREAM_CREATION_ERROR, False)


@pytest.mark.xfail(
    strict=True,
    reason="RFC 9114 4.6: an unsolicited push stream gets H3_STREAM_CREATION_ERROR",
)
def test_a_push_stream_without_max_push_id_is_an_id_error(certificates):
    link = their_server(certificates)
    open_control(link)

    open_uni(link, b"\x01\x00")

    assert close_code(link) == (H3ErrorCode.H3_ID_ERROR, False)


def test_a_control_stream_fin_is_a_critical_stream_error(certificates):
    link = their_h3_client(certificates, h3=False)

    open_control(link, end_stream=True)

    assert close_code(link) == (H3ErrorCode.H3_CLOSED_CRITICAL_STREAM, False)


def test_a_control_stream_reset_is_a_critical_stream_error(certificates):
    link = their_h3_client(certificates, h3=False)
    stream_id = open_control(link)
    link.run(lambda: link.ours.remote_settings is not None)

    link.theirs.reset_stream(stream_id, H3ErrorCode.H3_NO_ERROR)

    assert close_code(link) == (H3ErrorCode.H3_CLOSED_CRITICAL_STREAM, False)


def test_stopping_our_control_stream_is_a_critical_stream_error(certificates):
    link = their_h3_client(certificates, h3=False)
    peer_settings(link)

    link.theirs.stop_stream(3, H3ErrorCode.H3_NO_ERROR)

    assert close_code(link) == (H3ErrorCode.H3_CLOSED_CRITICAL_STREAM, False)


@pytest.mark.parametrize("stream_type", [RESERVED, 0x42], ids=["reserved", "unknown"])
def test_unknown_unidirectional_streams_leave_the_control_stream_usable(
    certificates, stream_type
):
    link = their_h3_client(certificates, h3=False)

    open_uni(link, encode_uint_var(stream_type) + SETTINGS, end_stream=True)
    open_control(link, encode_frame(FrameType.SETTINGS, b"\x06\x40\x64"))
    link.run(limit=0.5)

    assert link.ours.remote_settings is not None
    assert link.ours.remote_settings.max_field_section_size == 100


@pytest.mark.parametrize("reset", [False, True], ids=["fin", "reset"])
def test_a_unidirectional_stream_can_end_before_its_type(certificates, reset):
    link = their_h3_client(certificates, h3=False)

    stream_id = open_uni(link, b"", end_stream=not reset)
    if reset:
        link.theirs.reset_stream(stream_id, H3ErrorCode.H3_NO_ERROR)
    open_control(link)
    link.run(limit=0.5)

    assert link.ours_of(ConnectionTerminated) == []


def test_a_finished_request_stream_cannot_end_mid_frame(certificates):
    link = their_h3_client(certificates, h3=False)
    open_control(link)

    link.theirs.send_stream_data(0, b"\x01\x05\x00", end_stream=True)

    assert close_code(link) == (H3ErrorCode.H3_FRAME_ERROR, False)


def test_default_transport_credit_allows_three_critical_streams(h3_network):
    client = h3_network.connect_h3()

    h3_network.run(lambda: h3_network.events_of(client, HandshakeCompleted))

    for connection in (client, h3_network.h3_server):
        params = connection.peer_transport_parameters
        assert params is not None
        assert params.max_streams_uni >= 3


def test_h3_does_not_advertise_credit_for_fewer_than_three_unidirectional_streams(
    h3_network,
):
    try:
        h3_network.connect_h3(transport=TransportConfig(max_streams_uni=2))
    except ValueError:
        return

    h3_network.run(limit=1, quiet=0.1)

    params = h3_network.h3_server.peer_transport_parameters
    assert params is not None
    assert params.max_streams_uni >= 3


@pytest.mark.parametrize(
    ("remembered", "current"),
    [
        (H3Config(max_field_section_size=8192), H3Config(max_field_section_size=4096)),
        (
            H3Config(qpack_max_dtable_capacity=4096),
            H3Config(qpack_max_dtable_capacity=0),
        ),
    ],
    ids=["field-section-size", "qpack-capacity"],
)
def test_a_server_cannot_accept_0rtt_with_incompatible_settings(
    h3_network, remembered, current
):
    h3_network.server_h3 = remembered
    ticket = resumable_ticket(h3_network)
    h3_network.server_h3 = current
    client = h3_network.connect_h3(session_ticket=ticket)

    client.send_request(REQUEST, end_stream=True)
    h3_network.run(
        lambda: (
            client.remote_settings is not None
            and h3_network.events_of(client, HandshakeCompleted)
        )
    )

    settings = client.remote_settings
    assert settings is not None
    handshake = h3_network.events_of(client, HandshakeCompleted)[0]
    incompatible = (
        remembered.max_field_section_size is not None
        and settings.max_field_section_size < remembered.max_field_section_size
    ) or settings.qpack_max_dtable_capacity != remembered.qpack_max_dtable_capacity
    assert (handshake.early_data_accepted and incompatible) is False


def test_default_request_credit_permits_one_hundred_concurrent_requests(h3_network):
    client = h3_network.connect_h3()

    h3_network.run(lambda: h3_network.events_of(client, HandshakeCompleted))

    params = client.peer_transport_parameters
    assert params is not None
    assert params.max_streams_bidi >= 100


def test_default_unidirectional_stream_credit_is_at_least_1024_bytes(h3_network):
    client = h3_network.connect_h3()

    h3_network.run(lambda: h3_network.events_of(client, HandshakeCompleted))

    for connection in (client, h3_network.h3_server):
        params = connection.peer_transport_parameters
        assert params is not None
        assert params.max_stream_data_uni >= 1024


def test_a_client_rejects_max_push_id_from_a_server(certificates):
    link = their_server(certificates)

    open_control(link, SETTINGS + encode_frame(FrameType.MAX_PUSH_ID, b"\x00"))

    assert close_code(link) == (H3ErrorCode.H3_FRAME_UNEXPECTED, False)


@pytest.mark.xfail(
    strict=True, reason="RFC 9114 7.2.7: a decreasing MAX_PUSH_ID gets H3_FRAME_ERROR"
)
def test_max_push_id_cannot_decrease(certificates):
    link = their_h3_client(certificates, h3=False)

    open_control(
        link,
        SETTINGS
        + encode_frame(FrameType.MAX_PUSH_ID, b"\x01")
        + encode_frame(FrameType.MAX_PUSH_ID, b"\x00"),
    )

    assert close_code(link) == (H3ErrorCode.H3_ID_ERROR, False)


@pytest.mark.xfail(
    strict=True,
    reason="RFC 9114 7.2.3: an unpromised CANCEL_PUSH gets H3_FRAME_UNEXPECTED",
)
def test_an_unpromised_cancel_push_is_an_id_error(certificates):
    link = their_h3_client(certificates, h3=False)

    open_control(link, SETTINGS + encode_frame(FrameType.CANCEL_PUSH, b"\x00"))

    assert close_code(link) == (H3ErrorCode.H3_ID_ERROR, False)


@pytest.mark.xfail(
    strict=True,
    reason="RFC 9114 7.2.5: an unsolicited PUSH_PROMISE gets H3_FRAME_UNEXPECTED",
)
def test_a_push_promise_without_max_push_id_is_an_id_error(certificates):
    link = their_server(certificates)
    open_control(link)
    link.run(lambda: link.theirs_of(aio.HandshakeCompleted))
    stream_id = link.ours.send_request(REQUEST, end_stream=True)
    link.run(lambda: stream_bytes(link, stream_id))

    link.theirs.send_stream_data(
        stream_id, encode_frame(FrameType.PUSH_PROMISE, b"\x00")
    )

    assert close_code(link) == (H3ErrorCode.H3_ID_ERROR, False)


def test_client_can_offer_other_alpns_with_h3(h3_network):
    h3_network.client_tls.set_alpn_protocols(["other", "h3"])
    client = h3_network.connect_h3()

    h3_network.run(lambda: h3_network.events_of(client, HandshakeCompleted))

    assert h3_network.events_of(client, HandshakeCompleted)[0].alpn_protocol == "h3"


def test_a_client_rejects_push_promise_on_the_control_stream(certificates):
    link = their_server(certificates)

    open_control(link, SETTINGS + encode_frame(FrameType.PUSH_PROMISE, b"\x00"))

    assert close_code(link) == (H3ErrorCode.H3_FRAME_UNEXPECTED, False)


def test_configured_glitch_limit_closes_with_excessive_load(certificates):
    link = their_server(certificates, h3=H3Config(glitch_rate_limit=(1, 1)))

    open_uni(link, encode_uint_var(RESERVED), end_stream=True)
    open_uni(link, encode_uint_var(RESERVED), end_stream=True)

    assert close_code(link) == (H3ErrorCode.H3_EXCESSIVE_LOAD, False)


def test_aborting_an_unknown_stream_uses_the_stream_creation_error(certificates):
    link = their_h3_client(certificates, h3=False)

    stream_id = open_uni(link, encode_uint_var(RESERVED))
    link.run(lambda: link.theirs_of(aio.StopSendingReceived))

    assert link.theirs_of(aio.StopSendingReceived) == [
        aio.StopSendingReceived(
            error_code=H3ErrorCode.H3_STREAM_CREATION_ERROR, stream_id=stream_id
        )
    ]


def test_server_shutdown_notice_uses_the_maximum_request_stream_id(h3_network):
    client = connect_h3_client(h3_network)
    server = h3_network.h3_server

    server.send_shutdown_notice()
    h3_network.run(lambda: h3_network.events_of(client, GoAwayReceived))

    assert h3_network.events_of(client, GoAwayReceived) == [
        GoAwayReceived((1 << 62) - 4)
    ]


def test_duplicate_nonzero_qpack_capacity_is_rejected(certificates):
    link = their_h3_client(certificates, h3=False)
    setting = b"\x01\x01"

    open_control(link, encode_frame(FrameType.SETTINGS, setting * 2))

    assert close_code(link) == (H3ErrorCode.H3_SETTINGS_ERROR, False)
