"""Allocation failures inside one call, in Python objects or in ngtcp2 and nghttp3.

The native libraries allocate through Python's raw domain, so CPython's
``_testcapi.set_nomemory()`` fails the n-th allocation of a call wherever it
happens. Each case raises ``MemoryError`` (``InternalError`` from it when a
callback failed and dropped the connection) or ends the connection with
``ConnectionTerminated``; nothing corrupts, dangles or stalls.
"""

import subprocess
import sys
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

# Allocations one call makes at most in these scenarios.
MAX_ALLOCATIONS = 1000
# Calls in a row that no failure reaches before the sweep ends.
UNTOUCHED_RUN = 20
# Time for the pacer to release a full congestion window after the handshake.
PACING = 0.001


def run_isolated(scenario: str) -> None:
    testcapi = pytest.importorskip("_testcapi")
    if not hasattr(testcapi, "set_nomemory"):
        pytest.skip("CPython allocation-failure hooks are unavailable")

    # The hooks affect the whole interpreter, including the test runner.
    result = subprocess.run(
        [sys.executable, __file__, scenario],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "scenario",
    [
        "connect",
        "server-first-flight",
        "client-first-flight",
        "version-negotiation",
        "stream-send",
        "stream-write",
        "stream-read",
        "h3-connect",
        "h3-request",
        "h3-write",
        "h3-read",
    ],
)
def test_an_allocation_failure_raises_or_ends_the_connection(scenario):
    run_isolated(scenario)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parents[1]))
    from support.h3 import POST, H3Network, h3_tls, received_body
    from support.network import ALPN, Network

    from ngquic import (
        Connection,
        ConnectionState,
        ConnectionTerminated,
        Endpoint,
        EndpointConfig,
        HandshakeConfirmed,
        Incoming,
        InternalError,
        Role,
        SessionTicketReceived,
        StreamDataReceived,
        TLSContext,
        Version,
    )
    from ngquic.h3 import H3Config, RequestReceived, ResponseReceived, SettingsReceived

    testcapi = import_module("_testcapi")
    certs = Path(__file__).parents[1] / "support" / "certs"
    body = bytes(100_000)

    def quic_network() -> Network:
        server_tls = TLSContext(Role.SERVER)
        server_tls.load_cert_chain(str(certs / "cert.pem"), str(certs / "key.pem"))
        server_tls.set_alpn_protocols([ALPN])
        client_tls = TLSContext(Role.CLIENT)
        client_tls.load_verify_locations(cafile=str(certs / "ca.pem"))
        client_tls.set_alpn_protocols([ALPN])
        return Network(server_tls=server_tls, client_tls=client_tls)

    def h3_network() -> H3Network:
        class Paths:
            cert = str(certs / "cert.pem")
            key = str(certs / "key.pem")
            ca = str(certs / "ca.pem")

        return H3Network(
            server_tls=h3_tls(Paths, Role.SERVER),
            client_tls=h3_tls(Paths, Role.CLIENT),
        )

    def failing(call: Callable[[], Any], allocation: int) -> tuple[bool, Any]:
        """Run ``call`` with its ``allocation``-th allocation failing."""
        testcapi.set_nomemory(allocation, allocation + 1)
        try:
            return False, call()
        except MemoryError:
            return True, None
        except InternalError as error:
            # A callback's failure drops its connection (see AGENTS.md).
            assert isinstance(error.__cause__, MemoryError), error
            return True, None
        finally:
            testcapi.remove_mem_hooks()

    def ended(network: Network) -> bool:
        return any(
            network.events_of(connection, ConnectionTerminated)
            or connection.state == ConnectionState.CLOSED
            for connection in network.connections
        )

    def deliver(network: Network, transmits, endpoint, source) -> Any:
        """Deliver datagrams; return what the first one returned."""
        results = [
            endpoint.receive_datagram(
                transmit.data[offset : offset + transmit.segment_size],
                source,
                network.now,
                local_addr=transmit.remote_addr,
            )
            for transmit in transmits
            for offset in range(0, len(transmit.data), transmit.segment_size)
        ]
        return results[0]

    def surfaced(network: Network) -> bool:
        """Drain events; whether a delivery's callback failure surfaced there."""
        try:
            network._drain_events()
        except InternalError as error:
            # A failing callback drops its connection; events() raises.
            assert isinstance(error.__cause__, MemoryError), error
            return True
        except MemoryError:
            return True
        return False

    def handshake(network: Network) -> Connection:
        client = network.connect()
        network.run(lambda: network.events_of(client, HandshakeConfirmed))
        return client

    def open_client(network: Network, allocation: int, **options) -> tuple[bool, Any]:
        """Connect with one failing allocation, then retry if it failed."""

        def connect():
            return network.client_endpoint.connect(
                network.server_addr,
                network.now,
                tls=network.client_tls,
                server_name="localhost",
                **options,
            )

        failed, client = failing(connect, allocation)
        if failed:
            client = connect()
        network._track(client)
        return failed, client

    def check_connect(allocation: int) -> bool:
        network = quic_network()
        failed, client = open_client(network, allocation)
        network.run(lambda: network.events_of(client, HandshakeConfirmed))
        assert network.events_of(client, HandshakeConfirmed)
        return failed or ended(network)

    def check_server_first_flight(allocation: int) -> bool:
        network = quic_network()
        client = network.connect()
        flight = client.datagrams_to_send(network.now)

        def receive():
            incoming = deliver(
                network, flight, network.server_endpoint, network.client_addr
            )
            assert isinstance(incoming, Incoming)
            accepted = network.accept_incoming(incoming)
            assert accepted is not None
            network.accepted = accepted
            network._track(accepted)

        failed, _ = failing(receive, allocation)
        # The client repeats its first flight after a loss.
        network.run(lambda: network.events_of(client, HandshakeConfirmed))
        assert network.events_of(client, HandshakeConfirmed) or ended(network)
        return failed or ended(network)

    def check_client_first_flight(allocation: int) -> bool:
        network = quic_network()
        client = network.connect()
        incoming = deliver(
            network,
            client.datagrams_to_send(network.now),
            network.server_endpoint,
            network.client_addr,
        )
        server = network.accept_incoming(incoming)
        assert server is not None
        network.accepted = server
        network._track(server)
        reply = server.datagrams_to_send(network.now)
        failed, _ = failing(
            lambda: deliver(
                network, reply, network.client_endpoint, network.server_addr
            ),
            allocation,
        )
        failed = surfaced(network) or failed
        network.run(
            lambda: network.events_of(client, HandshakeConfirmed) or ended(network)
        )
        assert network.events_of(client, HandshakeConfirmed) or ended(network)
        return failed or ended(network)

    def check_version_negotiation(allocation: int) -> bool:
        """A client restarting in the server's version, dropping 0-RTT streams."""
        network = quic_network()
        network.server_tls.early_data = True
        first = handshake(network)
        network.run(lambda: network.events_of(first, SessionTicketReceived))
        ticket = network.events_of(first, SessionTicketReceived)[-1].ticket
        network.server_endpoint = Endpoint(
            network.server_addr, EndpointConfig(preferred_versions=(Version.V2,))
        )
        client = network.connect(session_ticket=ticket)
        client.send_stream_data(client.open_stream(), b"early")
        deliver(
            network,
            client.datagrams_to_send(network.now),
            network.server_endpoint,
            network.client_addr,
        )
        negotiation = network.server_endpoint.datagrams_to_send()
        failed, _ = failing(
            lambda: deliver(
                network, negotiation, network.client_endpoint, network.server_addr
            ),
            allocation,
        )
        failed = surfaced(network) or failed
        network.run(
            lambda: (
                network.events_of(client, HandshakeConfirmed)
                or client.state == ConnectionState.CLOSED
            )
        )
        assert (
            network.events_of(client, HandshakeConfirmed)
            or client.state == ConnectionState.CLOSED
        )
        return failed or client.state == ConnectionState.CLOSED

    def transferred(network: Network, client, stream_id: int) -> bool:
        received = b"".join(
            event.data
            for event in network.events_of(network.server, StreamDataReceived)
            if event.stream_id == stream_id
        )
        return received == body or ended(network)

    def check_stream_send(allocation: int) -> bool:
        network = quic_network()
        client = handshake(network)
        stream_id = client.open_stream()
        failed, _ = failing(
            lambda: client.send_stream_data(stream_id, body, end_stream=True),
            allocation,
        )
        if failed:
            client.send_stream_data(stream_id, body, end_stream=True)
        network.run()
        assert transferred(network, client, stream_id)
        return failed or ended(network)

    def check_stream_write(allocation: int) -> bool:
        network = quic_network()
        client = handshake(network)
        stream_id = client.open_stream()
        client.send_stream_data(stream_id, body, end_stream=True)
        network.now += PACING
        failed, out = failing(lambda: client.datagrams_to_send(network.now), allocation)
        if not failed:
            deliver(network, out, network.server_endpoint, network.client_addr)
        network.run()
        assert transferred(network, client, stream_id)
        return failed or ended(network)

    def check_stream_read(allocation: int) -> bool:
        network = quic_network()
        client = handshake(network)
        stream_id = client.open_stream()
        client.send_stream_data(stream_id, body, end_stream=True)
        network.now += PACING
        out = client.datagrams_to_send(network.now)
        failed, _ = failing(
            lambda: deliver(network, out, network.server_endpoint, network.client_addr),
            allocation,
        )
        failed = surfaced(network) or failed
        network.run()
        assert transferred(network, client, stream_id)
        return failed or ended(network)

    def check_h3_connect(allocation: int) -> bool:
        network = h3_network()
        failed, client = open_client(network, allocation, h3=H3Config())
        network.run(lambda: network.events_of(client, SettingsReceived))
        assert network.events_of(client, SettingsReceived)
        return failed or ended(network)

    def h3_client(network: H3Network):
        client = network.connect_h3()
        network.run(lambda: network.events_of(client, SettingsReceived))
        network.on_event = lambda connection, event: (
            connection.send_response(event.stream_id, [(b":status", b"200")])
            if isinstance(event, RequestReceived)
            and connection.state == ConnectionState.ESTABLISHED
            else None
        )
        return client

    def answered(network: H3Network, client, stream_id: int) -> bool:
        responded = any(
            event.stream_id == stream_id
            for event in network.events_of(client, ResponseReceived)
        )
        return (
            responded
            and len(received_body(network, network.h3_server, stream_id)) == len(body)
        ) or ended(network)

    def check_h3_request(allocation: int) -> bool:
        network = h3_network()
        client = h3_client(network)

        def request():
            stream_id = client.send_request(POST)
            client.send_data(stream_id, body, end_stream=True)
            return stream_id

        failed, stream_id = failing(request, allocation)
        if failed and client.state >= ConnectionState.CLOSING:
            # nghttp3 failed to queue the request, which it deems fatal.
            network.run()
            return True
        if failed:
            # The failure may come after the request took its stream.
            stream_id = request()
        network.run()
        assert answered(network, client, stream_id)
        return failed or ended(network)

    def check_h3_write(allocation: int) -> bool:
        network = h3_network()
        client = h3_client(network)
        stream_id = client.send_request(POST)
        client.send_data(stream_id, body, end_stream=True)
        network.now += PACING
        failed, out = failing(lambda: client.datagrams_to_send(network.now), allocation)
        if not failed:
            deliver(network, out, network.server_endpoint, network.client_addr)
        network.run()
        assert answered(network, client, stream_id)
        return failed or ended(network)

    def check_h3_read(allocation: int) -> bool:
        network = h3_network()
        client = h3_client(network)
        stream_id = client.send_request(POST)
        client.send_data(stream_id, body, end_stream=True)
        network.now += PACING
        out = client.datagrams_to_send(network.now)
        failed, _ = failing(
            lambda: deliver(network, out, network.server_endpoint, network.client_addr),
            allocation,
        )
        failed = surfaced(network) or failed
        network.run()
        assert answered(network, client, stream_id)
        return failed or ended(network)

    check = {
        "connect": check_connect,
        "server-first-flight": check_server_first_flight,
        "client-first-flight": check_client_first_flight,
        "version-negotiation": check_version_negotiation,
        "stream-send": check_stream_send,
        "stream-write": check_stream_write,
        "stream-read": check_stream_read,
        "h3-connect": check_h3_connect,
        "h3-request": check_h3_request,
        "h3-write": check_h3_write,
        "h3-read": check_h3_read,
    }[sys.argv[1]]
    # Some failures are tolerated (a cache that stays small), so the sweep ends
    # only after a run of calls that no failure reached.
    untouched = 0
    for allocation in range(MAX_ALLOCATIONS):
        try:
            untouched = 0 if check(allocation) else untouched + 1
        except BaseException as error:
            raise AssertionError(f"allocation {allocation}") from error
        if untouched == UNTOUCHED_RUN:
            break
    else:
        raise AssertionError(f"the call still fails after {MAX_ALLOCATIONS}")
