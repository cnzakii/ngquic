"""Event and value objects as applications build, compare and print them."""

from dataclasses import replace

import pytest
from support.network import SERVER_ADDR

from ngquic import (
    Incoming,
    NewTokenReceived,
    PeerCertificateReceived,
    SessionTicketReceived,
)
from ngquic.h3 import (
    H3Settings,
    InformationalResponseReceived,
    SettingsReceived,
    TrailersReceived,
)

HEADERS = ((b"x-test", b"1"),)
SETTINGS = H3Settings(
    max_field_section_size=4096,
    qpack_max_dtable_capacity=0,
    qpack_blocked_streams=0,
    enable_connect_protocol=False,
    h3_datagram=False,
)


@pytest.mark.parametrize(
    ("event", "same", "different"),
    [
        (
            SessionTicketReceived(b"t"),
            SessionTicketReceived(b"t"),
            SessionTicketReceived(b"u"),
        ),
        (NewTokenReceived(b"t"), NewTokenReceived(b"t"), NewTokenReceived(b"u")),
        (
            PeerCertificateReceived((b"c",)),
            PeerCertificateReceived((b"c",)),
            PeerCertificateReceived(()),
        ),
        (
            InformationalResponseReceived(0, HEADERS),
            InformationalResponseReceived(0, HEADERS),
            InformationalResponseReceived(4, HEADERS),
        ),
        (
            TrailersReceived(0, HEADERS),
            TrailersReceived(0, HEADERS),
            TrailersReceived(0, ()),
        ),
        (
            SettingsReceived(SETTINGS),
            SettingsReceived(SETTINGS),
            SettingsReceived(replace(SETTINGS, h3_datagram=True)),
        ),
    ],
    ids=["ticket", "token", "certificate", "informational", "trailers", "settings"],
)
def test_events_compare_field_by_field(event, same, different):
    assert (event == same, event == different) == (True, False)


def test_events_of_different_types_are_never_equal():
    assert NewTokenReceived(b"t") != SessionTicketReceived(b"t")


def test_event_repr_names_its_fields():
    assert repr(TrailersReceived(0, HEADERS)) == (
        "TrailersReceived(stream_id=0, headers=((b'x-test', b'1'),))"
    )


def test_transmit_and_incoming_reprs_summarize_them(network):
    seen: list[Incoming] = []
    network.accept = lambda incoming: seen.append(incoming)
    client = network.connect()
    transmit = client.datagrams_to_send(network.now)[0]
    network.run(lambda: seen)

    assert repr(transmit).startswith(
        f"Transmit(size={len(transmit.data)}, remote_addr={SERVER_ADDR!r}, "
    )
    assert repr(seen[0]).startswith("Incoming(remote_addr=('127.0.0.1', 50000), ")
