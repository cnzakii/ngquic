"""HTTP/3 on the in-memory link: the network, requests and TLS setup."""

from dataclasses import dataclass, field

from ngquic import (
    BaseConnection,
    Incoming,
    Role,
    SessionTicketReceived,
    TLSContext,
    TransportConfig,
)
from ngquic.h3 import (
    DataReceived,
    H3Config,
    H3Connection,
    SettingsReceived,
)
from support.network import Network

REQUEST = [
    (b":method", b"GET"),
    (b":scheme", b"https"),
    (b":authority", b"localhost"),
    (b":path", b"/"),
]


POST = [(b":method", b"POST"), *REQUEST[1:]]


# Extended CONNECT (RFC 9220) for a UDP proxy (RFC 9298), which uses datagrams.
CONNECT_UDP = [
    (b":method", b"CONNECT"),
    (b":protocol", b"connect-udp"),
    (b":scheme", b"https"),
    (b":authority", b"localhost"),
    (b":path", b"/.well-known/masque/udp/192.0.2.1/443/"),
    (b"capsule-protocol", b"?1"),
]


DATAGRAMS = TransportConfig(max_datagram_frame_size=65535)


OK = [(b":status", b"200")]


def h3_tls(certificates, role: Role, alpn: str = "h3") -> TLSContext:
    context = TLSContext(role)
    if role is Role.SERVER:
        context.load_cert_chain(certificates.cert, certificates.key)
    else:
        context.load_verify_locations(cafile=certificates.ca)
    context.set_alpn_protocols([alpn])
    return context


@dataclass
class H3Network(Network):
    """The in-memory link with HTTP/3 on both sides."""

    server_h3: H3Config = field(default_factory=H3Config)

    @property
    def h3_server(self) -> H3Connection:
        assert isinstance(self.accepted, H3Connection), "no connection was accepted"
        return self.accepted

    def connect_h3(self, h3: H3Config | None = None, **options) -> H3Connection:
        client = self.open(h3=H3Config() if h3 is None else h3, **options)
        assert isinstance(client, H3Connection)
        return client

    def accept_incoming(self, incoming: Incoming) -> BaseConnection | None:
        return incoming.accept(
            tls=self.server_tls, transport=self.server_transport, h3=self.server_h3
        )


def connect_h3_client(network: H3Network, **options) -> H3Connection:
    client = network.connect_h3(**options)
    network.run(lambda: network.events_of(client, SettingsReceived))
    return client


def received_body(network: H3Network, connection, stream_id: int) -> bytes:
    return b"".join(
        event.data
        for event in network.events_of(connection, DataReceived)
        if event.stream_id == stream_id
    )


def resumable_ticket(network: H3Network) -> bytes:
    network.server_tls.early_data = True
    client = connect_h3_client(network)
    network.run(lambda: network.events_of(client, SessionTicketReceived))
    return network.events_of(client, SessionTicketReceived)[-1].ticket
