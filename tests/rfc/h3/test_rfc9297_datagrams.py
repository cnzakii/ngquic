"""RFC 9297 sections 1.1, 2.1, and 2.1.1: HTTP/3 datagram wire format and settings."""

import pytest

# Optional: aioquic needs pylsqpack, which has no free-threaded build yet.
pytest.importorskip("aioquic")

from aioquic.h3 import events as aio_h3
from aioquic.h3.connection import FrameType, Setting, encode_frame, encode_settings
from support.aioquic_h3 import our_h3_client, their_h3_client
from support.h3 import CONNECT_UDP, DATAGRAMS, OK, REQUEST, resumable_ticket
from support.h3_frames import close_code, open_control

from ngquic import HandshakeCompleted
from ngquic.h3 import DatagramReceived, H3Config, H3ErrorCode, ResponseReceived


def test_a_nonminimal_quarter_stream_id_still_identifies_the_request(certificates):
    link = our_h3_client(certificates, datagrams=True)
    link.run(lambda: link.ours.remote_settings is not None)
    assert link.their_h3 is not None
    link.ours.send_request(REQUEST, end_stream=True)
    stream_id = link.ours.send_request(CONNECT_UDP)
    assert stream_id == 4
    link.run(limit=0.5)

    link.theirs.send_datagram_frame(b"\x40\x01payload")
    link.run(lambda: link.ours_of(DatagramReceived))

    assert link.ours_of(DatagramReceived) == [DatagramReceived(stream_id, b"payload")]


def test_a_non_boolean_datagram_setting_is_a_settings_error(certificates):
    link = their_h3_client(certificates, h3=False, datagrams=True)
    settings = encode_settings({Setting.H3_DATAGRAM: 2})

    open_control(link, encode_frame(FrameType.SETTINGS, settings))

    assert close_code(link) == (H3ErrorCode.H3_SETTINGS_ERROR, False)


def test_datagram_settings_cannot_be_downgraded_when_accepting_0rtt(h3_network):
    h3_network.server_transport = DATAGRAMS
    h3_network.server_h3 = H3Config(h3_datagram=True)
    ticket = resumable_ticket(h3_network)
    h3_network.server_h3 = H3Config()
    client = h3_network.connect_h3(session_ticket=ticket)

    client.send_request(REQUEST, end_stream=True)
    h3_network.run(lambda: client.remote_settings is not None)

    handshake = h3_network.events_of(client, HandshakeCompleted)[0]
    assert client.remote_settings is not None
    assert (
        handshake.early_data_accepted and not client.remote_settings.h3_datagram
    ) is False


def test_datagrams_received_after_a_response_fin_are_dropped(certificates):
    link = our_h3_client(certificates, datagrams=True)
    link.run(lambda: link.ours.remote_settings is not None)
    assert link.their_h3 is not None
    stream_id = link.ours.send_request(CONNECT_UDP)
    link.run(lambda: link.their_h3_of(aio_h3.HeadersReceived))
    link.their_h3.send_headers(stream_id, OK, end_stream=True)
    link.run(lambda: link.ours_of(ResponseReceived))

    link.theirs.send_datagram_frame(b"\x00late")
    link.run(limit=0.5)

    assert link.ours_of(DatagramReceived) == []
