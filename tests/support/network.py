"""The in-memory link between two endpoints on a virtual clock."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ngquic import (
    BaseConnection,
    Connection,
    Endpoint,
    EndpointConfig,
    Event,
    Incoming,
    TLSContext,
    Transmit,
    TransportConfig,
)

SERVER_ADDR = ("127.0.0.1", 4433)


CLIENT_ADDR = ("127.0.0.1", 50000)


ALPN = "test"


@dataclass
class Network:
    """Two endpoints joined by an in-memory link on a virtual clock.

    ``drop`` decides per datagram whether the link loses it; ``on_event``
    lets a test react to events the way an application would. ``arrival``
    gives the source a datagram arrives from and the ``local_addr`` reported
    with it (``None`` for the endpoint's), as sockets bound to any address
    see them; ``server_bind`` is the server endpoint's address when it
    differs from the one clients connect to.
    """

    server_tls: TLSContext
    client_tls: TLSContext
    server_transport: TransportConfig | None = None
    client_transport: TransportConfig | None = None
    server_config: EndpointConfig | None = None
    drop: Callable[[bytes, tuple], bool] = lambda data, destination: False
    # Any: handlers call methods of the connection kind the test created.
    on_event: Callable[[Any, Event], object] = lambda connection, event: None
    accept: Callable[[Incoming], BaseConnection | None] | None = None
    arrival: Callable[[Transmit], tuple[tuple, tuple | None]] = lambda transmit: (
        transmit.local_addr,
        transmit.remote_addr,
    )
    now: float = 1.0
    gso: bool = True
    server_addr: tuple = SERVER_ADDR
    client_addr: tuple = CLIENT_ADDR
    server_bind: tuple | None = None
    events: dict = field(default_factory=dict)
    accepted: BaseConnection | None = None
    sent: list = field(default_factory=list)

    @property
    def server(self) -> Connection:
        """The server side of the latest accepted connection."""
        assert isinstance(self.accepted, Connection), "no connection was accepted yet"
        return self.accepted

    def __post_init__(self):
        self.server_endpoint = Endpoint(
            self.server_bind or self.server_addr, self.server_config
        )
        self.client_endpoint = Endpoint(self.client_addr)
        self.connections: list[BaseConnection] = []

    def connect(self, **options) -> Connection:
        client = self.open(**options)
        assert isinstance(client, Connection)
        return client

    def open(self, **options) -> BaseConnection:
        """Start a client connection of whatever kind ``options`` ask for."""
        options.setdefault("server_name", "localhost")
        options.setdefault("transport", self.client_transport)
        client = self.client_endpoint.connect(
            self.server_addr,
            self.now,
            tls=self.client_tls,
            **options,
        )
        self._track(client)
        return client

    def accept_incoming(self, incoming: Incoming) -> BaseConnection | None:
        if self.accept is not None:
            return self.accept(incoming)
        return incoming.accept(tls=self.server_tls, transport=self.server_transport)

    def advance(self, seconds: float) -> None:
        """Run the link until the clock has moved ``seconds`` forward."""
        target = self.now + seconds
        self.run(lambda: self.now >= target, horizon=target)

    def run(
        self,
        until: Callable[[], object] | None = None,
        *,
        limit: float = 30.0,
        quiet: float = 3.0,
        horizon: float | None = None,
    ) -> None:
        """Exchange datagrams and fire timers until ``until()``.

        Without ``until``, run until the link has been silent for ``quiet``
        seconds: established connections always have an idle timer pending.
        The clock never jumps past ``horizon`` (or the end of that silence).
        """
        deadline = self.now + limit
        last_moved = self.now
        idle_fires = 0
        while self.now <= deadline:
            if self._flush():
                last_moved = self.now
                idle_fires = 0
                self._drain_events()
                if until is not None and until():
                    return
                continue
            self._drain_events()
            # Same expression as the cap below, so jumping to it always ends.
            if until is None and self.now >= last_moved + quiet:
                return
            if until is not None and until():
                return
            timers = [
                timer
                for connection in self.connections
                if (timer := connection.get_timer()) is not None
            ]
            cap = last_moved + quiet if until is None else horizon
            if cap is not None:
                timers.append(cap)
            if not timers:
                return
            now = max(self.now, min(timers))
            # A due timer that changes nothing is a busy loop for a real driver.
            idle_fires = idle_fires + 1 if now == self.now else 0
            if idle_fires > 100:
                raise AssertionError(f"timers due at {now} make no progress")
            self.now = now
            for connection in self.connections:
                timer = connection.get_timer()
                if timer is not None and timer <= self.now:
                    connection.handle_timer(self.now)
            self._drain_events()
        raise AssertionError("the network did not settle within the time limit")

    def events_of(self, connection: BaseConnection, kind: type | None = None) -> list:
        events = self.events.get(connection, [])
        return [event for event in events if kind is None or isinstance(event, kind)]

    def _track(self, connection: BaseConnection) -> None:
        self.connections.append(connection)
        self.events.setdefault(connection, [])

    def _flush(self) -> bool:
        """Deliver every pending datagram between the two endpoints.

        Each datagram arrives from its ``Transmit.local_addr`` at its
        ``Transmit.remote_addr`` unless ``arrival`` says otherwise, so
        migration and preferred addresses show up as the peer would see them.
        """
        moved = False
        outgoing: list[tuple[Transmit, Endpoint]] = [
            (transmit, self.client_endpoint)
            for transmit in self.server_endpoint.datagrams_to_send()
        ]
        outgoing += [
            (transmit, self.server_endpoint)
            for transmit in self.client_endpoint.datagrams_to_send()
        ]
        for connection in list(self.connections):
            target = (
                self.server_endpoint if connection.is_client else self.client_endpoint
            )
            outgoing += [
                (transmit, target)
                for transmit in connection.datagrams_to_send(self.now, gso=self.gso)
            ]
        for transmit, target in outgoing:
            data, size = transmit.data, transmit.segment_size
            for offset in range(0, len(data), size):
                datagram = data[offset : offset + size]
                moved = True
                self.sent.append(datagram)
                if self.drop(datagram, transmit.remote_addr):
                    continue
                source, local_addr = self.arrival(transmit)
                result = target.receive_datagram(
                    datagram, source, self.now, local_addr=local_addr
                )
                if isinstance(result, Incoming):
                    accepted = self.accept_incoming(result)
                    if accepted is not None:
                        self.accepted = accepted
                        self._track(accepted)
        return moved

    def _drain_events(self) -> None:
        for connection in list(self.connections):
            for event in connection.events():
                self.events[connection].append(event)
                self.on_event(connection, event)
