"""Negotiation and use of the QUIC fixed bit, RFC 9287 sections 3-3.2."""

import pytest

# Optional: aioquic needs pylsqpack, which has no free-threaded build yet.
pytest.importorskip("aioquic")

from aioquic import tls
from aioquic.quic.connection import QuicConnection
from support.aioquic import their_client

from ngquic import (
    ConnectionTerminated,
    ErrorCode,
    HandshakeConfirmed,
    StreamDataReceived,
    TransportConfig,
)


@pytest.mark.parametrize("advertised", [False, True], ids=["disabled", "enabled"])
def test_peer_parameters_report_quic_bit_greasing_support(network, advertised):
    transport = TransportConfig(grease_quic_bit=advertised)
    network.client_transport = network.server_transport = transport
    client = network.connect()

    network.run(lambda: network.events_of(client, HandshakeConfirmed))

    client_parameters = client.peer_transport_parameters
    server_parameters = network.server.peer_transport_parameters
    assert client_parameters is not None and server_parameters is not None
    assert (client_parameters.grease_quic_bit, server_parameters.grease_quic_bit) == (
        advertised,
        advertised,
    )


def test_quic_bit_stays_set_in_the_first_initial_without_a_token(network):
    client = network.connect()

    [initial] = client.datagrams_to_send(network.now, max_datagrams=1)

    assert initial.data[0] & 0x40 == 0x40


def test_nonempty_grease_quic_bit_parameter_is_rejected(
    server_tls, aio_client_config, monkeypatch
):
    serialize = QuicConnection._serialize_transport_parameters

    def with_nonempty_grease(peer):
        return serialize(peer) + b"\x6a\xb2\x01\x00"

    monkeypatch.setattr(
        QuicConnection, "_serialize_transport_parameters", with_nonempty_grease
    )

    link = their_client(server_tls, aio_client_config)

    assert [
        e.error_code for e in link.ours.events() if isinstance(e, ConnectionTerminated)
    ] == [ErrorCode.TRANSPORT_PARAMETER_ERROR]


@pytest.mark.parametrize("advertised", [False, True], ids=["disabled", "enabled"])
def test_a_packet_with_a_clear_quic_bit_requires_advertised_support(
    server_tls, aio_client_config, monkeypatch, advertised
):
    link = their_client(
        server_tls,
        aio_client_config,
        TransportConfig(grease_quic_bit=advertised, pmtud=False),
    )
    link.run(lambda: link.ours_of(HandshakeConfirmed))
    link.run(limit=0.5)
    crypto = link.theirs._cryptos[tls.Epoch.ONE_RTT]
    encrypt = crypto.encrypt_packet

    def with_clear_bit(header, payload, number):
        return encrypt(bytes([header[0] & ~0x40]) + header[1:], payload, number)

    monkeypatch.setattr(crypto, "encrypt_packet", with_clear_bit)
    stream_id = link.theirs.get_next_available_stream_id()

    link.theirs.send_stream_data(stream_id, b"greased", end_stream=True)
    [(data, _)] = link.theirs.datagrams_to_send(link.now)
    assert data[0] & 0xC0 == 0
    link.endpoint.receive_datagram(data, link.ours.remote_addr, link.now)

    assert [e for e in link.ours.events() if isinstance(e, StreamDataReceived)] == (
        [StreamDataReceived(stream_id, b"greased", True, False)] if advertised else []
    )
