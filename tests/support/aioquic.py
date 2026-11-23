"""aioquic as an independent QUIC peer on the same virtual clock."""

from collections.abc import Callable
from typing import Generic, TypeVar

from aioquic.buffer import Buffer
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.connection import QuicConnection
from aioquic.quic.packet import pull_quic_header

from ngquic import (
    BaseConnection,
    Connection,
    Endpoint,
    Incoming,
    Transmit,
)
from support.network import ALPN, CLIENT_ADDR, SERVER_ADDR


def segments(transmit: Transmit):
    data, size = transmit.data, transmit.segment_size
    return (data[offset : offset + size] for offset in range(0, len(data), size))


C = TypeVar("C", bound=BaseConnection)


class Link(Generic[C]):
    """One of our connections facing one aioquic connection."""

    def __init__(
        self,
        ours: C,
        theirs: QuicConnection,
        endpoint: Endpoint,
        now: float,
    ) -> None:
        self.ours = ours
        self.theirs = theirs
        self.endpoint = endpoint
        self.now = now
        self.our_events: list = []
        self.their_events: list = []

    def run(
        self, until: Callable[[], object] | None = None, limit: float = 30.0
    ) -> None:
        """Exchange until ``until()``; without it, just let ``limit`` seconds pass."""
        deadline = self.now + limit
        while self.now <= deadline:
            moved = self._exchange()
            self._drain()
            if until is not None and until():
                return
            if moved:
                continue
            timers = [
                t
                for t in (self.ours.get_timer(), self.theirs.get_timer())
                if t is not None
            ]
            if until is None:
                if self.now >= deadline:
                    return
                timers.append(deadline)
            if not timers:
                return
            self.now = max(self.now, min(timers))
            if (t := self.ours.get_timer()) is not None and t <= self.now:
                self.ours.handle_timer(self.now)
            if (t := self.theirs.get_timer()) is not None and t <= self.now:
                self.theirs.handle_timer(self.now)
        raise AssertionError("the link did not settle within the time limit")

    def _exchange(self) -> bool:
        moved = False
        ours = self.endpoint.datagrams_to_send() + self.ours.datagrams_to_send(self.now)
        for transmit in ours:
            for datagram in segments(transmit):
                moved = True
                self.theirs.receive_datagram(
                    datagram, self.endpoint.local_addr, self.now
                )
        for data, _ in self.theirs.datagrams_to_send(self.now):
            moved = True
            self.endpoint.receive_datagram(data, self.ours.remote_addr, self.now)
        return moved

    def _drain(self) -> None:
        self.our_events += self.ours.events()
        while (event := self.theirs.next_event()) is not None:
            self.their_events.append(event)

    def ours_of(self, kind):
        return [e for e in self.our_events if isinstance(e, kind)]

    def theirs_of(self, kind):
        return [e for e in self.their_events if isinstance(e, kind)]


def our_client(client_tls, aio_server_config, transport=None) -> Link[Connection]:
    endpoint = Endpoint(CLIENT_ADDR)
    ours = endpoint.connect(
        SERVER_ADDR, 1.0, tls=client_tls, server_name="localhost", transport=transport
    )
    first = ours.datagrams_to_send(1.0)
    header = pull_quic_header(Buffer(data=first[0].data), host_cid_length=8)
    theirs = QuicConnection(
        configuration=aio_server_config,
        original_destination_connection_id=header.destination_cid,
    )
    for transmit in first:
        for datagram in segments(transmit):
            theirs.receive_datagram(datagram, CLIENT_ADDR, 1.0)
    return Link(ours, theirs, endpoint, 1.0)


def their_client(server_tls, aio_client_config, transport=None) -> Link[Connection]:
    endpoint = Endpoint(SERVER_ADDR)
    theirs = QuicConnection(configuration=aio_client_config)
    theirs.connect(SERVER_ADDR, now=1.0)
    ours = None
    for data, _ in theirs.datagrams_to_send(1.0):
        result = endpoint.receive_datagram(data, CLIENT_ADDR, 1.0)
        if isinstance(result, Incoming):
            ours = result.accept(tls=server_tls, transport=transport)
    assert ours is not None
    return Link(ours, theirs, endpoint, 1.0)


def aioquic_server_config(certificates) -> QuicConfiguration:
    config = QuicConfiguration(
        is_client=False, alpn_protocols=[ALPN], max_datagram_frame_size=1200
    )
    config.load_cert_chain(certificates.cert, certificates.key)
    return config


def aioquic_client_config(certificates) -> QuicConfiguration:
    return QuicConfiguration(
        is_client=True,
        alpn_protocols=[ALPN],
        server_name="localhost",
        cafile=certificates.ca,
        max_datagram_frame_size=1200,
    )
