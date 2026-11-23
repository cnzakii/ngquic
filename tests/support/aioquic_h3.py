"""aioquic's HTTP/3 layer as an independent peer."""

from aioquic.buffer import Buffer
from aioquic.h3.connection import H3_ALPN
from aioquic.h3.connection import H3Connection as AioH3Connection
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.connection import QuicConnection
from aioquic.quic.packet import pull_quic_header

from ngquic import (
    Endpoint,
    Incoming,
    Role,
    TransportConfig,
)
from ngquic.h3 import (
    H3Config,
    H3Connection,
)
from support.aioquic import Link, segments
from support.h3 import h3_tls
from support.network import CLIENT_ADDR, SERVER_ADDR

DATAGRAM_FRAME_SIZE = 65535


class H3Link(Link[H3Connection]):
    """A link whose aioquic side may run aioquic's HTTP/3 layer."""

    their_h3: AioH3Connection | None = None
    their_h3_events: list

    def _drain(self) -> None:
        self.our_events += self.ours.events()
        while (event := self.theirs.next_event()) is not None:
            self.their_events.append(event)
            if self.their_h3 is not None:
                self.their_h3_events += self.their_h3.handle_event(event)

    def their_h3_of(self, kind):
        return [e for e in self.their_h3_events if isinstance(e, kind)]


def our_h3_client(certificates, *, datagrams: bool = False) -> H3Link:
    config = QuicConfiguration(
        is_client=False,
        alpn_protocols=H3_ALPN,
        max_datagram_frame_size=DATAGRAM_FRAME_SIZE if datagrams else None,
    )
    config.load_cert_chain(certificates.cert, certificates.key)
    endpoint = Endpoint(CLIENT_ADDR)
    ours = endpoint.connect(
        SERVER_ADDR,
        1.0,
        tls=h3_tls(certificates, Role.CLIENT),
        server_name="localhost",
        transport=_transport(datagrams),
        h3=H3Config(h3_datagram=datagrams),
    )
    first = ours.datagrams_to_send(1.0)
    header = pull_quic_header(Buffer(data=first[0].data), host_cid_length=8)
    theirs = QuicConnection(
        configuration=config, original_destination_connection_id=header.destination_cid
    )
    for transmit in first:
        for datagram in segments(transmit):
            theirs.receive_datagram(datagram, CLIENT_ADDR, 1.0)
    link = H3Link(ours, theirs, endpoint, 1.0)
    # aioquic announces SETTINGS_H3_DATAGRAM only together with WebTransport.
    link.their_h3 = AioH3Connection(theirs, enable_webtransport=datagrams)
    link.their_h3_events = []
    return link


def _transport(datagrams: bool) -> TransportConfig | None:
    return (
        TransportConfig(max_datagram_frame_size=DATAGRAM_FRAME_SIZE)
        if datagrams
        else None
    )


def their_h3_client(
    certificates, *, h3: bool = True, datagrams: bool = False
) -> H3Link:
    config = QuicConfiguration(
        is_client=True,
        alpn_protocols=H3_ALPN,
        cafile=certificates.ca,
        max_datagram_frame_size=DATAGRAM_FRAME_SIZE if datagrams else None,
    )
    config.server_name = "localhost"
    endpoint = Endpoint(SERVER_ADDR)
    theirs = QuicConnection(configuration=config)
    theirs.connect(SERVER_ADDR, now=1.0)
    ours = None
    for data, _ in theirs.datagrams_to_send(1.0):
        result = endpoint.receive_datagram(data, CLIENT_ADDR, 1.0)
        if isinstance(result, Incoming):
            ours = result.accept(
                tls=h3_tls(certificates, Role.SERVER),
                transport=_transport(datagrams),
                h3=H3Config(h3_datagram=datagrams),
            )
    assert isinstance(ours, H3Connection)
    link = H3Link(ours, theirs, endpoint, 1.0)
    link.their_h3_events = []
    if h3:
        link.their_h3 = AioH3Connection(theirs)
    return link
