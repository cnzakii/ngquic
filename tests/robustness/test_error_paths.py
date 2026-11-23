"""Error and progress paths between the binding, ngtcp2 and nghttp3."""

import pytest
from support.h3 import OK, POST, REQUEST, connect_h3_client, received_body
from support.qlog import sent_frames

from ngquic import ConnectionState, HandshakeConfirmed, TransportConfig
from ngquic.h3 import H3Config, RequestReceived, ResponseReceived


def test_an_h3_body_resumes_after_connection_credit_falls_below_the_threshold(
    h3_network,
):
    h3_network.server_transport = TransportConfig(
        max_data=32768, max_window=32768, max_stream_data_bidi_remote=1 << 22
    )
    client = connect_h3_client(
        h3_network, transport=TransportConfig(write_stream_data_threshold=4096)
    )
    body = bytes(300_000)
    stream_id = client.send_request(POST)

    client.send_data(stream_id, body, end_stream=True)
    h3_network.run()

    assert len(received_body(h3_network, h3_network.h3_server, stream_id)) == len(body)


def test_h3_writes_what_fits_under_the_threshold(h3_network):
    # SETTINGS is smaller than the threshold; the credit holds it whole.
    h3_network.server_transport = TransportConfig(
        max_data=64, max_window=None, auto_flow_control=False
    )
    client = h3_network.connect_h3(
        transport=TransportConfig(write_stream_data_threshold=128)
    )
    h3_network.run()

    assert h3_network.h3_server.remote_settings is not None
    assert client.state is ConnectionState.ESTABLISHED


def test_h3_signals_data_blocked_at_zero_connection_credit(h3_network):
    records = []
    h3_network.server_transport = TransportConfig(
        max_data=4096, max_window=None, auto_flow_control=False
    )
    client = connect_h3_client(
        h3_network,
        transport=TransportConfig(qlog=lambda data, final: records.append(data)),
    )
    stream_id = client.send_request(POST)

    client.send_data(stream_id, bytes(8192), end_stream=True)
    h3_network.advance(0.5)

    assert [frame["limit"] for frame in sent_frames(records, "data_blocked")] == [4096]


@pytest.mark.parametrize("method", ["reset_stream", "stop_sending"])
@pytest.mark.parametrize("stream_id", [2, 3], ids=["own-control", "peer-control"])
def test_aborting_a_control_stream_is_rejected(h3_network, method, stream_id):
    client = connect_h3_client(h3_network)

    with pytest.raises(ValueError, match="not a request stream"):
        getattr(client, method)(stream_id)
    h3_network.run()

    assert client.state == ConnectionState.ESTABLISHED


def test_data_blocked_is_sent_when_new_data_meets_exhausted_connection_credit(
    network,
):
    records = []
    network.client_transport = TransportConfig(
        qlog=lambda data, final: records.append(data)
    )
    network.server_transport = TransportConfig(max_data=8, auto_flow_control=False)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    stream_id = client.open_stream()
    client.send_stream_data(stream_id, b"abcdefgh")
    network.advance(0.5)

    client.send_stream_data(stream_id, b"more")
    network.advance(0.5)

    assert sent_frames(records, "data_blocked") == [
        {"frame_type": "data_blocked", "limit": 8}
    ]


def test_a_huge_stream_limit_keeps_the_qpack_decoder_buffer_open(h3_network):
    # nghttp3 allows 20 decoder-stream bytes per concurrent stream; this many
    # streams wraps that product to 4 bytes in 64-bit arithmetic.
    streams = -(-(1 << 64) // 20)
    h3_network.server_transport = TransportConfig(
        max_streams_bidi=streams - 3, max_streams_uni=3
    )
    h3_network.on_event = lambda connection, event: (
        connection.send_response(event.stream_id, OK, end_stream=True)
        if isinstance(event, RequestReceived)
        else None
    )
    client = connect_h3_client(
        h3_network, h3=H3Config(qpack_encoder_max_dtable_capacity=4096)
    )

    for index in range(30):
        client.send_request(
            [*REQUEST, (b"x-field-%d" % index, b"v" * 50)], end_stream=True
        )
    h3_network.run()

    assert len(h3_network.events_of(client, ResponseReceived)) == 30
