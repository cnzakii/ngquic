"""Handshakes over asyncio's own datagram transports, on every platform."""

import asyncio
import socket
import sys
from typing import cast

import pytest
from support.h3 import h3_tls

from ngquic import Endpoint, HandshakeConfirmed, Incoming, Role
from ngquic.h3 import H3Config


def _loopback(host):
    try:
        with socket.socket(
            socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_DGRAM
        ) as sock:
            sock.bind((host, 0))
    except OSError:
        pytest.skip(f"no {host} loopback")
    return host


class _Side(asyncio.DatagramProtocol):
    """One endpoint on an asyncio transport, driving its connections."""

    endpoint: Endpoint
    transport: asyncio.DatagramTransport

    def __init__(self, loop, accept=None):
        self.loop = loop
        self.accept = accept or self.refuse
        self.closed = loop.create_future()
        self.connected = False
        self.connections = []
        self.events = []
        self.timer = None

    @staticmethod
    def refuse(incoming):
        raise AssertionError(f"unexpected connection attempt {incoming!r}")

    def connection_made(self, transport):
        # Python 3.10's transports do not derive from DatagramTransport.
        self.transport = cast(asyncio.DatagramTransport, transport)

    def datagram_received(self, data, addr):
        result = self.endpoint.receive_datagram(data, addr, self.loop.time())
        if isinstance(result, Incoming):
            self.connections.append(self.accept(result))
        self.flush()

    def error_received(self, exc):
        self.events.append(exc)

    def connection_lost(self, exc):
        self.closed.set_result(exc)

    def flush(self):
        now = self.loop.time()
        for transmit in self.endpoint.datagrams_to_send():
            self.transport.sendto(transmit.data, transmit.remote_addr)
        deadline = None
        for connection in self.connections:
            self.events += connection.events()
            for transmit in connection.datagrams_to_send(now):
                self.transport.sendto(
                    transmit.data, None if self.connected else transmit.remote_addr
                )
            timer = connection.get_timer()
            if timer is not None and (deadline is None or timer < deadline):
                deadline = timer
        if self.timer is not None:
            self.timer.cancel()
        if deadline is not None:
            self.timer = self.loop.call_at(deadline, self.expire, deadline)

    def expire(self, deadline):
        now = max(deadline, self.loop.time())
        for connection in self.connections:
            timer = connection.get_timer()
            if timer is not None and timer <= now:
                connection.handle_timer(now)
        self.flush()


async def _handshake(host, server_tls, client_tls, h3):
    loop = asyncio.get_running_loop()
    options = {"h3": H3Config()} if h3 else {}
    sock = socket.socket(
        socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_DGRAM
    )
    sock.bind((host, 0))
    server = _Side(
        loop, accept=lambda incoming: incoming.accept(tls=server_tls, **options)
    )
    server_transport, _ = await loop.create_datagram_endpoint(lambda: server, sock=sock)
    server_addr = server_transport.get_extra_info("sockname")
    server.endpoint = Endpoint(server_addr)

    # Connected, as asyncio connects a socket given remote_addr.
    client = _Side(loop)
    client_transport, _ = await loop.create_datagram_endpoint(
        lambda: client, remote_addr=server_addr[:2], family=sock.family
    )
    client.connected = True
    client.endpoint = Endpoint(client_transport.get_extra_info("sockname"))
    now = loop.time()
    connection = (
        client.endpoint.connect(
            server_addr, now, tls=client_tls, server_name="localhost", h3=H3Config()
        )
        if h3
        else client.endpoint.connect(
            server_addr, now, tls=client_tls, server_name="localhost"
        )
    )
    client.connections.append(connection)
    client.flush()

    async def confirmed():
        while not any(isinstance(e, HandshakeConfirmed) for e in client.events):
            await asyncio.sleep(0.01)

    try:
        await asyncio.wait_for(confirmed(), 5)
    finally:
        for side in (client, server):
            if side.timer is not None:
                side.timer.cancel()
        # abort(), as close() makes the proactor wait for a send in flight.
        client_transport.abort()
        server_transport.abort()
        # The proactor closes a transport on a later iteration.
        await asyncio.wait([client.closed, server.closed], timeout=5)
    return client, server


@pytest.mark.skipif(
    sys.platform == "win32" and sys.version_info < (3, 12),
    reason="the proactor of Python 3.11 never closes a datagram transport",
)
@pytest.mark.parametrize("h3", [False, True], ids=["quic", "h3"])
@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_a_handshake_completes_over_asyncio_datagram_transports(
    host, h3, certificates, server_tls, client_tls
):
    if h3:
        server_tls = h3_tls(certificates, Role.SERVER)
        client_tls = h3_tls(certificates, Role.CLIENT)
    client, server = asyncio.run(
        _handshake(_loopback(host), server_tls, client_tls, h3)
    )

    assert [e for e in client.events + server.events if isinstance(e, Exception)] == []
