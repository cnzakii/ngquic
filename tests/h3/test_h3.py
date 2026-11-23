"""HTTP/3 on top of the QUIC connection: what the binding adds to nghttp3.

nghttp3 owns framing and QPACK; these tests cover the wiring this package
owns: request and response flow, body buffers and flow-control credit,
stream aborts, graceful shutdown, settings, priorities and 0-RTT.
"""

import enum

import pytest
from support.h3 import (
    CONNECT_UDP,
    DATAGRAMS,
    OK,
    POST,
    REQUEST,
    H3Network,
    connect_h3_client,
    h3_tls,
    received_body,
    resumable_ticket,
)

from ngquic import (
    CloseReason,
    ConnectionState,
    ConnectionStateError,
    ConnectionTerminated,
    DatagramError,
    EarlyDataRejected,
    HandshakeCompleted,
    Role,
    StopSendingReceived,
    StreamClosed,
    StreamLimitError,
    StreamReset,
    StreamStateError,
    StreamWritable,
    TransportConfig,
)
from ngquic.h3 import (
    DatagramReceived,
    DataReceived,
    GoAwayReceived,
    H3Config,
    H3Connection,
    H3ErrorCode,
    InformationalResponseReceived,
    NeverIndexedHeader,
    OriginReceived,
    Priority,
    RequestReceived,
    ResponseReceived,
    SettingsReceived,
    TrailersReceived,
    parse_priority,
)


def _ended(network: H3Network, connection, stream_id: int) -> bool:
    return any(
        event.stream_id == stream_id and getattr(event, "end_stream", True)
        for kind in (DataReceived, TrailersReceived, ResponseReceived, RequestReceived)
        for event in network.events_of(connection, kind)
    )


def _respond(network: H3Network, *, body: bytes = b"", trailers=None) -> None:
    """Answer every request the server receives."""

    def on_event(connection, event):
        if isinstance(event, RequestReceived):
            connection.send_response(
                event.stream_id, OK, end_stream=not body and trailers is None
            )
            if body or trailers is not None:
                connection.send_data(event.stream_id, body)
                if trailers is None:
                    connection.end_stream(event.stream_id)
                else:
                    connection.send_trailers(event.stream_id, trailers)

    network.on_event = on_event


# ---- connections


def test_h3_option_yields_an_h3_connection_on_both_sides(h3_network):
    client = connect_h3_client(h3_network)

    assert isinstance(h3_network.h3_server, H3Connection)
    assert not hasattr(client, "open_stream")
    assert (
        client.remote_settings
        == h3_network.events_of(client, SettingsReceived)[0].settings
    )


def test_h3_requires_an_h3_config(h3_network):
    with pytest.raises(TypeError, match="H3Config"):
        h3_network.connect_h3(h3={"qpack_blocked_streams": 1})


def test_a_negotiated_protocol_other_than_h3_closes_the_connection(
    h3_network, certificates
):
    h3_network.server_tls = h3_tls(certificates, Role.SERVER, "other")
    h3_network.client_tls = h3_tls(certificates, Role.CLIENT, "other")
    client = h3_network.connect_h3()

    h3_network.run()

    terminated = h3_network.events_of(client, ConnectionTerminated)[0]
    # TLS no_application_protocol (RFC 9001 8.1).
    assert (terminated.reason, terminated.error_code) == (
        CloseReason.TRANSPORT_ERROR,
        0x100 + 120,
    )


def test_peer_settings_report_its_config(h3_network):
    h3_network.server_h3 = H3Config(
        enable_connect_protocol=True, max_field_section_size=8192
    )
    client = connect_h3_client(h3_network)

    settings = client.remote_settings
    assert settings is not None
    assert (settings.enable_connect_protocol, settings.max_field_section_size) == (
        True,
        8192,
    )


def test_a_server_announces_its_origins(h3_network):
    h3_network.server_h3 = H3Config(
        origins=(b"https://localhost", b"https://example.com")
    )
    client = connect_h3_client(h3_network)
    h3_network.run(lambda: h3_network.events_of(client, OriginReceived))

    assert h3_network.events_of(client, OriginReceived)[0].origins == (
        b"https://localhost",
        b"https://example.com",
    )


# ---- requests and responses


def test_request_without_body_gets_a_response_without_body(h3_network):
    _respond(h3_network)
    client = connect_h3_client(h3_network)

    stream_id = client.send_request(REQUEST, end_stream=True)
    h3_network.run(lambda: h3_network.events_of(client, ResponseReceived))

    request = h3_network.events_of(h3_network.h3_server, RequestReceived)[0]
    response = h3_network.events_of(client, ResponseReceived)[0]
    assert (request.stream_id, request.headers, request.end_stream) == (
        stream_id,
        tuple(REQUEST),
        True,
    )
    assert (response.stream_id, response.headers, response.end_stream) == (
        stream_id,
        tuple(OK),
        True,
    )


def test_bodies_cross_in_both_directions_in_order(h3_network):
    payload = bytes(range(256)) * 4096
    _respond(h3_network, body=payload[::-1])
    client = connect_h3_client(h3_network)

    stream_id = client.send_request(POST)
    client.send_data(stream_id, payload[:1000])
    client.send_data(stream_id, memoryview(payload)[1000:], end_stream=True)
    h3_network.run(lambda: _ended(h3_network, client, stream_id))

    assert received_body(h3_network, h3_network.h3_server, stream_id) == payload
    assert received_body(h3_network, client, stream_id) == payload[::-1]


def test_the_last_data_event_carries_end_stream(h3_network):
    _respond(h3_network)
    client = connect_h3_client(h3_network)

    stream_id = client.send_request(POST)
    client.send_data(stream_id, b"body", end_stream=True)
    h3_network.run(lambda: h3_network.events_of(client, ResponseReceived))

    events = h3_network.events_of(h3_network.h3_server, DataReceived)
    assert [(e.data, e.end_stream) for e in events] == [(b"body", True)]


def test_ending_an_empty_body_reports_an_empty_final_data_event(h3_network):
    client = connect_h3_client(h3_network)

    stream_id = client.send_request(POST)
    h3_network.run(lambda: h3_network.events_of(h3_network.h3_server, RequestReceived))
    client.end_stream(stream_id)
    h3_network.run(lambda: h3_network.events_of(h3_network.h3_server, DataReceived))

    events = h3_network.events_of(h3_network.h3_server, DataReceived)
    assert [(e.data, e.end_stream) for e in events] == [(b"", True)]


def test_trailers_end_the_message(h3_network):
    _respond(h3_network, body=b"data", trailers=[(b"x-checksum", b"abc")])
    client = connect_h3_client(h3_network)

    stream_id = client.send_request(REQUEST, end_stream=True)
    h3_network.run(lambda: h3_network.events_of(client, TrailersReceived))

    assert received_body(h3_network, client, stream_id) == b"data"
    trailers = h3_network.events_of(client, TrailersReceived)[0]
    assert trailers.headers == ((b"x-checksum", b"abc"),)
    assert not any(e.end_stream for e in h3_network.events_of(client, DataReceived))


def test_informational_responses_precede_the_final_one(h3_network):
    def on_event(connection, event):
        if isinstance(event, RequestReceived):
            connection.send_informational_response(
                event.stream_id, [(b":status", b"103"), (b"link", b"</a.css>")]
            )
            connection.send_response(event.stream_id, OK, end_stream=True)

    h3_network.on_event = on_event
    client = connect_h3_client(h3_network)

    client.send_request(REQUEST, end_stream=True)
    h3_network.run(lambda: h3_network.events_of(client, ResponseReceived))

    kinds = [
        type(e)
        for e in h3_network.events_of(client)
        if isinstance(e, (InformationalResponseReceived, ResponseReceived))
    ]
    assert kinds == [InformationalResponseReceived, ResponseReceived]


def test_never_indexed_headers_arrive_marked_for_forwarding(h3_network):
    client = connect_h3_client(h3_network)
    server = h3_network.h3_server

    client.send_request(
        [*REQUEST, NeverIndexedHeader(b"authorization", b"secret")], end_stream=True
    )
    h3_network.run(lambda: h3_network.events_of(server, RequestReceived))

    headers = h3_network.events_of(server, RequestReceived)[0].headers
    assert headers[-1] == (b"authorization", b"secret")
    assert isinstance(headers[-1], NeverIndexedHeader)
    assert not any(isinstance(field, NeverIndexedHeader) for field in headers[:-1])


def test_streams_close_after_both_messages_finish(h3_network):
    _respond(h3_network, body=b"ok")
    client = connect_h3_client(h3_network)

    stream_id = client.send_request(REQUEST, end_stream=True)
    h3_network.run(lambda: h3_network.events_of(client, StreamClosed))

    closed = h3_network.events_of(client, StreamClosed)[0]
    assert (closed.stream_id, closed.receive_error_code, closed.send_error_code) == (
        stream_id,
        None,
        None,
    )
    assert client.queued_body_size() == 0


@pytest.mark.parametrize(
    "headers",
    [[(b"x", b"bad\r\nvalue")], [(b"", b"x")], [(b"x y", b"1")]],
    ids=["newline-value", "empty-name", "space-in-name"],
)
def test_invalid_headers_are_rejected_before_sending(h3_network, headers):
    client = connect_h3_client(h3_network)

    with pytest.raises(ValueError, match="header"):
        client.send_request([*REQUEST, *headers])


# The server's nghttp3 would close the whole connection on these.
@pytest.mark.parametrize(
    ("headers", "match"),
    [
        ([field for field in REQUEST if field[0] != b":path"], "non-empty :path"),
        ([*REQUEST[:3], (b":path", b"")], "non-empty :path"),
        (REQUEST[1:], "needs :method"),
        ([*REQUEST, (b":method", b"GET")], "duplicate"),
        ([*REQUEST, (b":protocol", b"websocket")], ":protocol needs :method CONNECT"),
        ([*REQUEST, (b":status", b"200")], "cannot carry"),
        ([(b"x-field", b"1"), *REQUEST], "before the regular fields"),
        (
            [field for field in REQUEST if field[0] != b":authority"],
            ":authority or host",
        ),
        (
            [
                (b":method", b"CONNECT"),
                (b":authority", b"localhost:443"),
                (b":path", b"/"),
            ],
            "no :scheme or :path",
        ),
        ([*REQUEST, (b"connection", b"close")], "connection-specific"),
        ([*REQUEST, (b"te", b"gzip")], "te can only"),
        ([*REQUEST[:3], (b":path", b"*")], "must start with /"),
        ([*REQUEST[:2], (b":authority", b""), REQUEST[3]], "non-empty :authority"),
        ([*REQUEST, (b"host", b"other")], "host must equal"),
        ([*REQUEST[:2], REQUEST[3], (b"host", b"")], "one non-empty host"),
        (
            [*REQUEST, (b"host", b"localhost"), (b"host", b"localhost")],
            "one non-empty host",
        ),
    ],
    ids=[
        "missing-path",
        "empty-path",
        "missing-method",
        "duplicate",
        "protocol-on-get",
        "response-pseudo-header",
        "pseudo-header-late",
        "missing-authority",
        "connect-with-path",
        "connection-field",
        "te-other-than-trailers",
        "asterisk-for-get",
        "empty-authority",
        "host-mismatch",
        "empty-host",
        "duplicate-host",
    ],
)
def test_a_malformed_request_is_refused_before_sending(h3_network, headers, match):
    client = connect_h3_client(h3_network)

    with pytest.raises(ValueError, match=match):
        client.send_request(headers)

    assert client.state is ConnectionState.ESTABLISHED
    client.send_request(REQUEST, end_stream=True)


def test_a_bytes_subclass_cannot_misreport_its_length(h3_network):
    class Lying(bytes):
        def __len__(self):
            return 1 << 20

    client = connect_h3_client(h3_network)
    server = h3_network.h3_server
    client.send_request([*REQUEST, (b"x-trace", Lying(b"1"))], end_stream=True)
    h3_network.run(lambda: h3_network.events_of(server, RequestReceived))

    [request] = h3_network.events_of(server, RequestReceived)
    assert list(request.headers)[-1] == (b"x-trace", b"1")


def test_requests_may_use_host_or_plain_connect(h3_network):
    client = connect_h3_client(h3_network)

    client.send_request(
        [*REQUEST[:2], REQUEST[3], (b"host", b"localhost"), (b"te", b"trailers")],
        end_stream=True,
    )
    client.send_request([(b":method", b"CONNECT"), (b":authority", b"localhost:443")])


def test_extended_connect_the_server_did_not_enable_is_a_state_error(h3_network):
    client = connect_h3_client(h3_network)
    request = [(b":method", b"CONNECT"), (b":protocol", b"websocket"), *REQUEST[1:]]

    with pytest.raises(ConnectionStateError, match="SETTINGS_ENABLE_CONNECT_PROTOCOL"):
        client.send_request(request)


@pytest.mark.parametrize(
    ("send", "headers", "match"),
    [
        ("final", [(b"x-field", b"1")], "needs :status"),
        ("final", [(b":status", b"20")], "invalid :status"),
        ("final", [(b":status", b"103")], "a final status"),
        ("final", [(b":status", b"099")], "invalid :status"),
        ("final", [(b":status", b"600")], "invalid :status"),
        ("final", [*OK, (b":path", b"/")], "cannot carry"),
        ("interim", OK, "interim 1xx"),
        ("interim", [(b":status", b"101")], "interim 1xx"),
        ("trailers", OK, "cannot carry"),
    ],
    ids=[
        "missing-status",
        "short-status",
        "interim-as-final",
        "status-099",
        "status-600",
        "request-pseudo-header",
        "final-as-interim",
        "switching-protocols",
        "pseudo-header-in-trailers",
    ],
)
def test_a_malformed_response_is_refused_before_sending(
    h3_network, send, headers, match
):
    client = connect_h3_client(h3_network)
    server = h3_network.h3_server
    stream_id = client.send_request(POST)
    h3_network.run(lambda: h3_network.events_of(server, RequestReceived))
    if send == "trailers":
        server.send_response(stream_id, OK)

    with pytest.raises(ValueError, match=match):
        if send == "final":
            server.send_response(stream_id, headers)
        elif send == "interim":
            server.send_informational_response(stream_id, headers)
        else:
            server.send_trailers(stream_id, headers)


def test_field_names_are_sent_in_lowercase(h3_network):
    client = connect_h3_client(h3_network)
    server = h3_network.h3_server

    client.send_request(
        [(b":Method", b"GET"), *REQUEST[1:], (b"X-Trace", b"A")], end_stream=True
    )
    h3_network.run(lambda: h3_network.events_of(server, RequestReceived))

    [request] = h3_network.events_of(server, RequestReceived)
    assert list(request.headers) == [*REQUEST, (b"x-trace", b"A")]


class Field(bytes, enum.Enum):
    METHOD = b":method"
    TRACE = b"x-trace"


class Value(bytes):
    pass


def test_header_names_and_values_may_subclass_bytes(h3_network):
    client = connect_h3_client(h3_network)
    server = h3_network.h3_server

    client.send_request(
        [(Field.METHOD, Value(b"GET")), *REQUEST[1:], (Field.TRACE, Value(b"1"))],
        end_stream=True,
    )
    h3_network.run(lambda: h3_network.events_of(server, RequestReceived))
    [request] = h3_network.events_of(server, RequestReceived)
    server.send_response(
        request.stream_id, [(b":status", Value(b"200"))], end_stream=True
    )
    h3_network.run(lambda: h3_network.events_of(client, ResponseReceived))

    assert list(request.headers) == [*REQUEST, (b"x-trace", b"1")]
    assert list(h3_network.events_of(client, ResponseReceived)[0].headers) == OK


def test_a_header_section_past_the_announced_limit_closes_the_connection(
    h3_network,
):
    # RFC 9114 4.2.2 counts name and value bytes plus 32 per field.
    h3_network.server_h3 = H3Config(max_field_section_size=200)
    client = connect_h3_client(h3_network)

    client.send_request([*REQUEST, (b"x-big", b"x" * 200)], end_stream=True)
    h3_network.run(lambda: h3_network.events_of(client, ConnectionTerminated))

    [terminated] = h3_network.events_of(client, ConnectionTerminated)
    assert terminated.error_code == H3ErrorCode.H3_EXCESSIVE_LOAD
    assert not h3_network.events_of(h3_network.h3_server, RequestReceived)


def test_a_header_section_within_the_announced_limit_arrives(h3_network):
    h3_network.server_h3 = H3Config(max_field_section_size=600)
    client = connect_h3_client(h3_network)

    client.send_request([*REQUEST, (b"x-big", b"x" * 200)], end_stream=True)
    h3_network.run(lambda: h3_network.events_of(h3_network.h3_server, RequestReceived))

    assert h3_network.events_of(h3_network.h3_server, RequestReceived)


def test_an_interim_response_cannot_follow_the_final_one(h3_network):
    client = connect_h3_client(h3_network)
    server = h3_network.h3_server
    stream_id = client.send_request(POST)
    h3_network.run(lambda: h3_network.events_of(server, RequestReceived))
    server.send_response(stream_id, OK)

    with pytest.raises(StreamStateError, match="final response"):
        server.send_informational_response(stream_id, [(b":status", b"103")])


@pytest.mark.parametrize("send", ["send_response", "send_informational_response"])
def test_a_response_needs_a_request_stream(h3_network, send):
    connect_h3_client(h3_network)

    with pytest.raises(ValueError, match="not a request stream"):
        getattr(h3_network.h3_server, send)(3, [(b":status", b"103")])


def test_a_shutdown_notice_cannot_follow_goaway(h3_network):
    connect_h3_client(h3_network)
    server = h3_network.h3_server
    server.send_goaway()

    with pytest.raises(ConnectionStateError, match="already sent"):
        server.send_shutdown_notice()


def test_headers_must_be_byte_pairs(h3_network):
    client = connect_h3_client(h3_network)

    with pytest.raises(TypeError, match="pair of bytes"):
        client.send_request([(":method", "GET")])  # ty: ignore[invalid-argument-type]


def test_only_clients_send_requests(h3_network):
    connect_h3_client(h3_network)

    with pytest.raises(ConnectionStateError, match="only clients"):
        h3_network.h3_server.send_request(REQUEST)


def test_only_servers_send_responses(h3_network):
    client = connect_h3_client(h3_network)
    stream_id = client.send_request(REQUEST, end_stream=True)

    with pytest.raises(ConnectionStateError, match="only servers"):
        client.send_response(stream_id, OK)


def test_a_response_needs_an_open_request(h3_network):
    connect_h3_client(h3_network)

    with pytest.raises(StreamStateError, match="cannot take a response"):
        h3_network.h3_server.send_response(4, OK)


def test_a_message_without_body_takes_no_data(h3_network):
    client = connect_h3_client(h3_network)
    stream_id = client.send_request(REQUEST, end_stream=True)

    with pytest.raises(StreamStateError, match="no open message body"):
        client.send_data(stream_id, b"late")


def test_requests_are_limited_by_the_peer_stream_credit(h3_network):
    h3_network.server_transport = TransportConfig(max_streams_bidi=2)
    client = connect_h3_client(h3_network)
    available = [client.bidi_streams_available]
    client.send_request(REQUEST)
    available.append(client.bidi_streams_available)
    client.send_request(REQUEST)

    assert [*available, client.bidi_streams_available] == [2, 1, 0]
    assert h3_network.h3_server.bidi_streams_available == 0
    with pytest.raises(StreamLimitError):
        client.send_request(REQUEST)


# ---- body buffers and flow control


def test_send_data_reports_back_pressure_until_acknowledged(h3_network):
    h3_network.client_transport = TransportConfig(
        stream_write_buffer_high=10_000, stream_write_buffer_low=1_000
    )
    client = connect_h3_client(h3_network)
    stream_id = client.send_request(POST)

    assert client.send_data(stream_id, bytes(20_000)) is False
    h3_network.run(lambda: h3_network.events_of(client, StreamWritable))

    assert h3_network.events_of(client, StreamWritable)[0].stream_id == stream_id
    assert client.queued_body_size(stream_id) <= 1_000


def test_manual_flow_control_holds_body_credit_until_consumed(h3_network):
    window = 64 * 1024
    h3_network.server_transport = TransportConfig(
        auto_flow_control=False,
        max_data=window,
        max_stream_data_bidi_remote=window,
        max_window=None,
        max_stream_window=None,
    )
    client = connect_h3_client(h3_network)
    stream_id = client.send_request(POST)
    client.send_data(stream_id, bytes(4 * window), end_stream=True)
    server = h3_network.h3_server

    h3_network.run()
    stalled = len(received_body(h3_network, server, stream_id))
    server.consume_received_data(stream_id, stalled)
    h3_network.run()

    assert stalled < window
    assert len(received_body(h3_network, server, stream_id)) > stalled


def test_a_bare_fin_needs_no_connection_credit(h3_network):
    window = 64 * 1024
    h3_network.server_transport = TransportConfig(
        auto_flow_control=False, max_data=window, max_window=None
    )
    # How much body fits before the connection credit runs out.
    probe = H3Network(
        server_tls=h3_network.server_tls,
        client_tls=h3_network.client_tls,
        server_transport=h3_network.server_transport,
    )
    client = connect_h3_client(probe)
    stream_id = client.send_request(POST)
    client.send_data(stream_id, bytes(2 * window))
    probe.run()
    fits = len(received_body(probe, probe.h3_server, stream_id))

    client = connect_h3_client(h3_network)
    stream_id = client.send_request(POST)
    client.send_data(stream_id, bytes(fits))
    h3_network.run()
    client.end_stream(stream_id)
    h3_network.run()

    server = h3_network.h3_server
    assert len(received_body(h3_network, server, stream_id)) == fits
    assert any(event.end_stream for event in h3_network.events_of(server, DataReceived))


# ---- aborts


def test_a_cancelled_request_reaches_the_server_as_a_reset(h3_network):
    client = connect_h3_client(h3_network)
    stream_id = client.send_request(POST)
    h3_network.run(lambda: h3_network.events_of(h3_network.h3_server, RequestReceived))

    client.reset_stream(stream_id)
    h3_network.run(lambda: h3_network.events_of(h3_network.h3_server, StreamReset))

    reset = h3_network.events_of(h3_network.h3_server, StreamReset)[0]
    assert (reset.stream_id, reset.error_code) == (
        stream_id,
        H3ErrorCode.H3_REQUEST_CANCELLED,
    )


def test_a_server_may_stop_reading_after_answering(h3_network):
    def on_event(connection, event):
        if isinstance(event, RequestReceived):
            connection.send_response(event.stream_id, OK, end_stream=True)
            connection.stop_sending(event.stream_id)

    h3_network.on_event = on_event
    client = connect_h3_client(h3_network)
    stream_id = client.send_request(POST)
    client.send_data(stream_id, bytes(10_000))

    h3_network.run(lambda: h3_network.events_of(client, StopSendingReceived))

    assert h3_network.events_of(client, ResponseReceived)[0].stream_id == stream_id
    stop = h3_network.events_of(client, StopSendingReceived)[0]
    assert stop.error_code == H3ErrorCode.H3_NO_ERROR
    with pytest.raises(StreamStateError):
        client.send_data(stream_id, b"more")


def test_extended_connect_reaches_a_server_that_enables_it(h3_network):
    h3_network.server_h3 = H3Config(enable_connect_protocol=True)
    client = connect_h3_client(h3_network)

    client.send_request(CONNECT_UDP)
    h3_network.run(lambda: h3_network.events_of(h3_network.h3_server, RequestReceived))

    request = h3_network.events_of(h3_network.h3_server, RequestReceived)[0]
    assert (request.headers, request.end_stream) == (tuple(CONNECT_UDP), False)


# ---- graceful shutdown


def test_goaway_drains_accepted_requests_then_refuses_new_ones(h3_network):
    client = connect_h3_client(h3_network)
    server = h3_network.h3_server
    stream_id = client.send_request(REQUEST, end_stream=True)
    h3_network.run(lambda: h3_network.events_of(server, RequestReceived))

    server.send_shutdown_notice()
    server.send_goaway()
    h3_network.run(lambda: h3_network.events_of(client, GoAwayReceived))

    assert not server.is_drained
    assert client.bidi_streams_available == 0
    with pytest.raises(ConnectionStateError, match="shutting down"):
        client.send_request(REQUEST, end_stream=True)
    server.send_response(stream_id, OK, end_stream=True)
    h3_network.run(lambda: server.is_drained)
    assert [e.id for e in h3_network.events_of(client, GoAwayReceived)][-1] == (
        stream_id + 4
    )
    # The refused request opened no stream, so none was reset either.
    assert not h3_network.events_of(server, StreamReset)
    assert not h3_network.events_of(server, StopSendingReceived)


def test_a_drained_server_closes_with_h3_no_error(h3_network):
    client = connect_h3_client(h3_network)
    server = h3_network.h3_server
    server.send_goaway()
    h3_network.run(lambda: server.is_drained)

    server.close(H3ErrorCode.H3_NO_ERROR)
    h3_network.run(lambda: h3_network.events_of(client, ConnectionTerminated))

    assert (
        h3_network.events_of(client, ConnectionTerminated)[0].error_code
        == H3ErrorCode.H3_NO_ERROR
    )


def test_a_client_goaway_reaches_the_server(h3_network):
    client = connect_h3_client(h3_network)
    server = h3_network.h3_server

    client.send_goaway()
    h3_network.run(lambda: h3_network.events_of(server, GoAwayReceived))

    # A client has no pushes to accept, so it announces push ID 0.
    assert h3_network.events_of(server, GoAwayReceived)[0].id == 0


# ---- priority


def test_a_server_sets_and_reads_a_request_priority(h3_network):
    client = connect_h3_client(h3_network)
    server = h3_network.h3_server
    stream_id = client.send_request(REQUEST, end_stream=True)
    h3_network.run(lambda: h3_network.events_of(server, RequestReceived))

    server.set_stream_priority(stream_id, Priority(urgency=1, incremental=True))

    assert server.get_stream_priority(stream_id) == Priority(1, True)


def test_a_client_priority_update_reaches_the_server(h3_network):
    client = connect_h3_client(h3_network)
    server = h3_network.h3_server
    stream_id = client.send_request(POST)
    h3_network.run(lambda: h3_network.events_of(server, RequestReceived))

    client.send_priority_update(stream_id, b"u=6, i")
    h3_network.run(lambda: server.get_stream_priority(stream_id) == Priority(6, True))

    assert server.get_stream_priority(stream_id) == Priority(6, True)


def test_the_request_priority_header_sets_the_initial_priority(h3_network):
    client = connect_h3_client(h3_network)
    server = h3_network.h3_server

    stream_id = client.send_request([*REQUEST, (b"priority", b"u=0")], end_stream=True)
    h3_network.run(lambda: h3_network.events_of(server, RequestReceived))

    assert server.get_stream_priority(stream_id) == Priority(0, False)


def test_priorities_of_an_unknown_request_are_absent(h3_network):
    client = connect_h3_client(h3_network)
    server = h3_network.h3_server

    with pytest.raises(StreamStateError, match="not an open request"):
        server.set_stream_priority(0, Priority())
    with pytest.raises(StreamStateError, match="not an open request"):
        client.send_priority_update(0, b"u=1")
    assert server.get_stream_priority(0) is None


def test_set_stream_priority_takes_a_priority(h3_network):
    connect_h3_client(h3_network)

    with pytest.raises(TypeError, match="priority must be a Priority"):
        h3_network.h3_server.set_stream_priority(0, 1)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (b"u=1, i", Priority(1, True)),
        (b"i", Priority(3, True)),
        (b"u=7, x=unknown", Priority(7, False)),
        (b"", Priority()),
    ],
)
def test_parse_priority_keeps_defaults_for_absent_parameters(value, expected):
    assert parse_priority(value) == expected


@pytest.mark.parametrize("value", [b"u=8", b"u=1,,", b"i=?2"])
def test_parse_priority_rejects_an_invalid_field(value):
    with pytest.raises(ValueError, match="Priority"):
        parse_priority(value)


# ---- HTTP/3 datagrams (RFC 9297)


def _proxy(network: H3Network, *, server_datagrams: bool = True):
    """Open a CONNECT-UDP request the server answered; return client and stream."""
    network.server_h3 = H3Config(
        enable_connect_protocol=True, h3_datagram=server_datagrams
    )
    network.server_transport = DATAGRAMS
    client = connect_h3_client(
        network, h3=H3Config(h3_datagram=True), transport=DATAGRAMS
    )
    network.run(lambda: client.remote_settings is not None)
    stream_id = client.send_request(CONNECT_UDP)
    network.run(lambda: network.events_of(network.h3_server, RequestReceived))
    network.h3_server.send_response(stream_id, OK)
    network.run(lambda: network.events_of(client, ResponseReceived))
    return client, stream_id


def test_datagrams_cross_on_a_request_stream_in_both_directions(h3_network):
    client, stream_id = _proxy(h3_network)
    server = h3_network.h3_server

    client.send_datagram(stream_id, b"ping")
    client.send_datagram(stream_id, memoryview(b""))
    h3_network.run(lambda: len(h3_network.events_of(server, DatagramReceived)) == 2)
    server.send_datagram(stream_id, bytearray(b"pong"))
    h3_network.run(lambda: h3_network.events_of(client, DatagramReceived))

    assert h3_network.events_of(server, DatagramReceived) == [
        DatagramReceived(stream_id, b"ping"),
        DatagramReceived(stream_id, b""),
    ]
    assert h3_network.events_of(client, DatagramReceived) == [
        DatagramReceived(stream_id, b"pong")
    ]


def test_datagrams_need_both_sides_to_announce_them(h3_network):
    client, stream_id = _proxy(h3_network, server_datagrams=False)

    assert client.max_datagram_size(stream_id) is None
    with pytest.raises(DatagramError, match="not negotiated"):
        client.send_datagram(stream_id, b"ping")
    assert h3_network.h3_server.max_datagram_size(stream_id) is None


def test_h3_datagrams_need_quic_datagram_frames(h3_network):
    with pytest.raises(ValueError, match="max_datagram_frame_size"):
        h3_network.connect_h3(h3=H3Config(h3_datagram=True))


def test_the_stream_prefix_counts_against_the_datagram_size(h3_network):
    client, stream_id = _proxy(h3_network)
    limit = client.max_datagram_size(stream_id)
    assert limit is not None

    # Quarter stream IDs from 64 take a 2-byte varint instead of 1.
    assert client.max_datagram_size(4 * 64) == limit - 1
    with pytest.raises(DatagramError, match="exceeds"):
        client.send_datagram(stream_id, bytes(limit + 1))


@pytest.mark.parametrize("stream_id", [1, 2, 3, 6])
def test_datagrams_belong_to_request_streams(h3_network, stream_id):
    client, _ = _proxy(h3_network)

    with pytest.raises(ValueError, match="not a request stream"):
        client.send_datagram(stream_id, b"")
    with pytest.raises(ValueError, match="not a request stream"):
        client.max_datagram_size(stream_id)


def test_a_datagram_needs_an_open_message_on_its_stream(h3_network):
    client, stream_id = _proxy(h3_network)
    server = h3_network.h3_server
    other = client.send_request(CONNECT_UDP)
    h3_network.run(lambda: len(h3_network.events_of(server, RequestReceived)) == 2)

    with pytest.raises(StreamStateError, match="no open message"):
        server.send_datagram(other, b"before the response")
    client.end_stream(stream_id)
    with pytest.raises(StreamStateError, match="no open message"):
        client.send_datagram(stream_id, b"after the request ended")


def test_datagrams_after_the_server_stops_reading_are_dropped(h3_network):
    client, stream_id = _proxy(h3_network)
    server = h3_network.h3_server

    server.stop_sending(stream_id)
    client.send_datagram(stream_id, b"late")
    h3_network.run(lambda: h3_network.events_of(client, StopSendingReceived))
    h3_network.run()

    assert not h3_network.events_of(server, DatagramReceived)
    assert server.state is ConnectionState.ESTABLISHED


# ---- 0-RTT


def test_requests_go_out_in_0rtt_with_a_resumed_session(h3_network):
    ticket = resumable_ticket(h3_network)
    _respond(h3_network, body=b"early")
    client = h3_network.connect_h3(session_ticket=ticket)

    stream_id = client.send_request(REQUEST, end_stream=True)
    h3_network.run(lambda: _ended(h3_network, client, stream_id))

    assert h3_network.events_of(client, HandshakeCompleted)[0].early_data_accepted
    assert received_body(h3_network, client, stream_id) == b"early"


def test_rejected_0rtt_requests_can_be_sent_again(h3_network):
    ticket = resumable_ticket(h3_network)
    h3_network.server_tls.early_data = False
    _respond(h3_network, body=b"late")
    client = h3_network.connect_h3(session_ticket=ticket)
    client.send_request(REQUEST, end_stream=True)

    h3_network.run(lambda: h3_network.events_of(client, EarlyDataRejected))
    h3_network.run(lambda: client.state is ConnectionState.ESTABLISHED)
    stream_id = client.send_request(REQUEST, end_stream=True)
    h3_network.run(lambda: _ended(h3_network, client, stream_id))

    assert received_body(h3_network, client, stream_id) == b"late"


def test_requests_before_the_handshake_need_0rtt(h3_network):
    client = h3_network.connect_h3()

    with pytest.raises(StreamLimitError, match="HandshakeCompleted"):
        client.send_request(REQUEST)


def test_http3_control_waits_for_the_handshake(h3_network):
    client = h3_network.connect_h3()

    with pytest.raises(ConnectionStateError, match="HTTP/3 starts when the handshake"):
        client.send_priority_update(0, b"u=1")


@pytest.mark.parametrize("header", [b":method", (b":method",)], ids=["bytes", "single"])
def test_each_header_must_be_a_pair(h3_network, header):
    client = connect_h3_client(h3_network)

    with pytest.raises(TypeError, match=r"\(name, value\) pair"):
        client.send_request([header], end_stream=True)


def test_queued_body_size_counts_every_request_body(h3_network):
    client = connect_h3_client(h3_network)
    first = client.send_request(POST)
    second = client.send_request(POST)

    client.send_data(first, b"x" * 100)
    client.send_data(second, b"y" * 50)

    assert client.queued_body_size() == 150
