"""ngquic on real UDP sockets, for h3spec and the QUIC interop runner.

The server answers HTTP/0.9 (``hq-interop``) or HTTP/3 GET requests from a
directory; the client downloads URLs into one. The interop runner selects the
behavior with ``TESTCASE`` and exits 127 for test cases this peer does not
implement (https://github.com/quic-interop/quic-interop-runner). Datagrams go
through ``ngquic.udp``, so the runner also covers GSO, GRO and ECN.

    python peer.py server --port 4433 --cert cert.pem --key key.pem --h3
    python peer.py client --h3 --output downloads https://localhost:4433/file
"""

import argparse
import asyncio
import collections
import itertools
import os
import socket
import ssl
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ngquic import (
    BaseConnection,
    ConnectionState,
    ConnectionTerminated,
    Endpoint,
    EndpointConfig,
    HandshakeConfirmed,
    Incoming,
    Role,
    SessionTicketReceived,
    StreamDataReceived,
    StreamLimitError,
    StreamsAvailable,
    TLSContext,
    Transmit,
    TransportConfig,
    Version,
)
from ngquic.h3 import DataReceived, H3Config, H3Connection, RequestReceived
from ngquic.udp import UDPSocket

UNSUPPORTED = 127
# The endpoint test cases the runner passes in TESTCASE that this peer runs.
# Runner tests share them: handshakeloss runs "multiconnect", rebind-port and
# amplificationlimit run "transfer", longrtt runs "handshake". The settings for
# each follow ngtcp2's own endpoint, vendor/ngtcp2/interop/run_endpoint.sh.
SUPPORTED = {
    "handshake",
    "transfer",
    "retry",
    "resumption",
    "zerortt",
    "http3",
    "keyupdate",
    "multiconnect",
    "v2",
    "ecn",
}
QLOG_FILES = itertools.count()

# Receives each event of its connection, or the exception that ended it.
Handler = Callable[[Any, object], None]


class Peer:
    """Drive one endpoint and its connections from a UDP socket in asyncio."""

    def __init__(self, sock: socket.socket) -> None:
        self.loop = asyncio.get_running_loop()
        self.endpoint: Endpoint | None = None
        self.handlers: dict[BaseConnection, Handler] = {}
        self.on_incoming: Callable[[Incoming], None] = lambda incoming: None
        self.timer: asyncio.TimerHandle | None = None
        self.sock = sock
        self.io = UDPSocket(sock)
        # Transmits waiting for the socket to become writable.
        self.unsent: collections.deque[Transmit] = collections.deque()
        self.loop.add_reader(self.io, self.readable)

    def add(self, connection: BaseConnection, handler: Handler) -> None:
        self.handlers[connection] = handler

    def readable(self) -> None:
        assert self.endpoint is not None
        try:
            ready = self.io.receive_into(self.endpoint, self.loop.time())
        except OSError:
            # An ICMP error, as asyncio's error_received() would see it.
            return
        for item in ready:
            if isinstance(item, Incoming):
                try:
                    self.on_incoming(item)
                except Exception as error:
                    print(f"{item!r} not accepted: {error!r}", file=sys.stderr)
        self.flush()

    def flush(self) -> None:
        assert self.endpoint is not None
        now = self.loop.time()
        for transmit in self.endpoint.datagrams_to_send():
            self.send(transmit)
        for connection, handler in list(self.handlers.items()):
            try:
                for event in connection.events():
                    handler(connection, event)
                for transmit in connection.datagrams_to_send(now, gso=self.io.gso):
                    self.send(transmit)
            except Exception as error:
                self.dropped(connection, error)
            if connection.state == ConnectionState.CLOSED:
                del self.handlers[connection]
        if self.timer is not None:
            self.timer.cancel()
        timers = [
            timer
            for connection in self.handlers
            if (timer := connection.get_timer()) is not None
        ]
        self.timer = self.loop.call_at(min(timers), self.fire) if timers else None

    def fire(self) -> None:
        now = self.loop.time()
        for connection in list(self.handlers):
            timer = connection.get_timer()
            if timer is not None and timer <= now:
                try:
                    connection.handle_timer(now)
                except Exception as error:
                    self.dropped(connection, error)
        self.flush()

    def dropped(self, connection: BaseConnection, error: Exception) -> None:
        """Serving ``connection`` failed: close it, and let the others go on."""
        print(f"{connection!r} failed: {error!r}", file=sys.stderr)
        self.handlers[connection](connection, error)
        # Flushed until closed, with no more events for the handler.
        self.handlers[connection] = lambda connection, event: None
        if connection.state < ConnectionState.CLOSING:
            connection.close()

    def send(self, transmit: Transmit) -> None:
        self.unsent.append(transmit)
        if len(self.unsent) == 1:
            self.writable()

    def writable(self) -> None:
        """Send what waits, in order, until the socket buffer fills."""
        while self.unsent:
            try:
                self.io.send(self.unsent[0])
            except BlockingIOError:
                self.loop.add_writer(self.io, self.writable)
                return
            except OSError:
                pass  # Lost, which QUIC recovers from.
            self.unsent.popleft()
        self.loop.remove_writer(self.io)


def transport_config(role: Role, testcase: str) -> TransportConfig:
    """ngtcp2's interop settings for ``testcase``, and qlog files when QLOGDIR is set."""
    directory = os.environ.get("QLOGDIR")
    qlog = None
    if directory:
        Path(directory).mkdir(parents=True, exist_ok=True)
        path = Path(directory) / f"{os.getpid()}-{next(QLOG_FILES)}.sqlog"

        def qlog(data: bytes, final: bool) -> None:
            with path.open("ab") as file:
                file.write(data)

    # The examples' seven connection IDs: a peer that changes paths wants an
    # unused one. Congestion control and the initial RTT keep ngquic's
    # defaults rather than the endpoint's --cc bbr --initial-rtt 100ms, so
    # the runner measures what applications get.
    settings: dict[str, Any] = {"active_connection_id_limit": 7, "qlog": qlog}
    if role is Role.CLIENT:
        # The example client's receive windows (examples/client_base.h).
        settings.update(
            max_data=24 << 20,
            max_stream_data_bidi_local=16 << 20,
            max_stream_data_uni=16 << 20,
            max_streams_uni=100,
        )
    else:
        # More unidirectional streams than HTTP/3 needs, so h3spec can open extras.
        settings["max_streams_uni"] = 16
    if testcase == "zerortt":
        # --no-pmtud: probes would count against zerortt's 1-RTT byte budget.
        settings["pmtud"] = False
    elif testcase == "ecn":
        # --no-pmtud, as ngtcp2's endpoint runs ecn.
        settings["pmtud"] = False
    elif testcase == "multiconnect":
        settings.update(idle_timeout=180.0, handshake_timeout=180.0)
    return TransportConfig(**settings)


def tls_context(role: Role, alpn: str, args) -> TLSContext:
    tls = TLSContext(role)
    tls.set_alpn_protocols([alpn])
    if role is Role.SERVER:
        tls.load_cert_chain(args.cert, args.key)
        tls.early_data = True
    else:
        tls.check_hostname = False
        tls.verify_mode = ssl.CERT_NONE
        # ngtcp2's example client lists X25519MLKEM768 last, which BoringSSL
        # never offers a key share for; AWS-LC adds one for the first
        # post-quantum group listed (ssl_setup_key_shares), splitting the
        # ClientHello across two Initials that the loss tests cannot recover
        # in time. Leave it out to offer what ngtcp2's client does.
        tls.set_groups(["X25519", "P-256", "P-384", "P-521"])
    if keylog := os.environ.get("SSLKEYLOGFILE"):
        tls.keylog_filename = keylog
    return tls


def open_peer(host: str, port: int) -> tuple[Peer, Any]:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_DGRAM)
    sock.bind((host, port))
    return Peer(sock), sock.getsockname()


# ---- server


async def serve(args) -> None:
    testcase = os.environ.get("TESTCASE", "http3" if args.h3 else "transfer")
    if testcase not in SUPPORTED:
        sys.exit(UNSUPPORTED)
    h3 = args.h3 or testcase == "http3"
    root = Path(args.root)
    # --preferred-versions v2
    versions = (
        (Version.V2, Version.V1) if testcase == "v2" else (Version.V1, Version.V2)
    )
    peer, local = open_peer(args.host, args.port)
    peer.endpoint = Endpoint(local, EndpointConfig(preferred_versions=versions))
    tls = tls_context(Role.SERVER, "h3" if h3 else "hq-interop", args)

    def body(path: str) -> bytes | None:
        target = (root / path.lstrip("/")).resolve()
        if root.resolve() not in target.parents or not target.is_file():
            return None
        return target.read_bytes()

    requests: dict[tuple[BaseConnection, int], bytes] = {}

    def on_hq(connection, event) -> None:
        if not isinstance(event, StreamDataReceived):
            return
        key = (connection, event.stream_id)
        requests[key] = requests.get(key, b"") + event.data
        if event.end_stream:
            line = requests.pop(key).split(b"\r\n")[0].decode()
            data = body(line.removeprefix("GET ").strip()) or b""
            connection.send_stream_data(event.stream_id, data, end_stream=True)

    def on_h3(connection, event) -> None:
        if not isinstance(event, RequestReceived):
            return
        path = dict(event.headers).get(b":path", b"/").decode()
        data = body(path)
        if data is None:
            connection.send_response(
                event.stream_id, [(b":status", b"404")], end_stream=True
            )
            return
        connection.send_response(
            event.stream_id,
            [(b":status", b"200"), (b"content-length", str(len(data)).encode())],
        )
        connection.send_data(event.stream_id, data, end_stream=True)

    def on_incoming(incoming: Incoming) -> None:
        if testcase == "retry" and not incoming.remote_address_validated:
            incoming.retry()
            return
        # A config per connection: each gets its own qlog file.
        transport = transport_config(Role.SERVER, testcase)
        if h3:
            connection = incoming.accept(tls=tls, transport=transport, h3=H3Config())
        else:
            connection = incoming.accept(tls=tls, transport=transport)
        if connection is not None:
            peer.add(connection, on_h3 if h3 else on_hq)

    peer.on_incoming = on_incoming
    print(f"listening on {local}", flush=True)
    await asyncio.Event().wait()


# ---- client


async def fetch(
    peer: Peer,
    urls: list[str],
    args,
    h3: bool,
    ticket: bytes | None,
    *,
    early: bool,
    key_update: bool,
) -> bytes | None:
    """Download ``urls`` on one connection; return its last session ticket."""
    assert peer.endpoint is not None
    first = urlsplit(urls[0])
    host, port = first.hostname or "localhost", first.port or 443
    address = socket.getaddrinfo(host, port, type=socket.SOCK_DGRAM)[0][4]
    remote = (str(address[0]), int(address[1]))
    output = Path(args.output)
    done = asyncio.Event()
    received: dict[int, list[bytes]] = {}
    names: dict[int, str] = {}
    tickets: list[bytes] = []
    finished: set[int] = set()
    tls = tls_context(Role.CLIENT, "h3" if h3 else "hq-interop", args)
    now, transport = peer.loop.time(), transport_config(Role.CLIENT, args.testcase)
    if h3:
        connection = peer.endpoint.connect(
            remote,
            now,
            tls=tls,
            server_name=host,
            transport=transport,
            session_ticket=ticket,
            h3=H3Config(),
        )
    else:
        connection = peer.endpoint.connect(
            remote,
            now,
            tls=tls,
            server_name=host,
            transport=transport,
            session_ticket=ticket,
        )

    waiting = list(reversed(urls))

    def request() -> None:
        """Send what the stream limit allows; StreamsAvailable resumes the rest."""
        while waiting:
            path = urlsplit(waiting[-1]).path or "/"
            try:
                if isinstance(connection, H3Connection):
                    stream_id = connection.send_request(
                        [
                            (b":method", b"GET"),
                            (b":scheme", b"https"),
                            (b":authority", host.encode()),
                            (b":path", path.encode()),
                        ],
                        end_stream=True,
                    )
                else:
                    stream_id = connection.open_stream()
                    connection.send_stream_data(
                        stream_id, f"GET {path}\r\n".encode(), end_stream=True
                    )
            except StreamLimitError:
                return
            waiting.pop()
            names[stream_id] = Path(path).name

    def complete(stream_id: int) -> None:
        (output / names[stream_id]).write_bytes(b"".join(received.pop(stream_id, [])))
        finished.add(stream_id)
        if len(finished) == len(urls) and (tickets or not args.wait_ticket):
            connection.close()

    def on_event(connection, event) -> None:
        if isinstance(event, HandshakeConfirmed):
            if key_update:
                connection.update_key(peer.loop.time())
            request()
        elif isinstance(event, StreamsAvailable):
            request()
        elif isinstance(event, SessionTicketReceived):
            tickets.append(event.ticket)
            if len(finished) == len(urls):
                connection.close()
        elif isinstance(event, (StreamDataReceived, DataReceived)):
            received.setdefault(event.stream_id, []).append(event.data)
            if event.end_stream:
                complete(event.stream_id)
        elif isinstance(event, (ConnectionTerminated, Exception)):
            done.set()

    peer.add(connection, on_event)
    if early:
        request()
    peer.flush()
    await done.wait()
    if len(finished) != len(urls):
        sys.exit(1)
    return tickets[-1] if tickets else None


async def download(args) -> None:
    testcase = os.environ.get("TESTCASE", "http3" if args.h3 else "transfer")
    if testcase not in SUPPORTED:
        sys.exit(UNSUPPORTED)
    args.testcase = testcase
    urls = args.urls or os.environ.get("REQUESTS", "").split()
    h3 = args.h3 or testcase == "http3"
    first = urlsplit(urls[0])
    family, _, _, _, remote = socket.getaddrinfo(
        first.hostname, first.port or 443, type=socket.SOCK_DGRAM
    )[0]
    # A client names a specific local address. Take the one the route to the
    # server uses, as ngtcp2's client does, and bind to it instead of
    # connecting: the server's preferred address is another destination.
    with socket.socket(family, socket.SOCK_DGRAM) as route:
        route.connect(remote)
        host = route.getsockname()[0]
    sock = socket.socket(family, socket.SOCK_DGRAM)
    sock.bind((host, 0))
    peer, local = Peer(sock), sock.getsockname()
    # -v 0x1 always; --available-versions v2,v1 for v2.
    versions = (
        (Version.V2, Version.V1) if testcase == "v2" else (Version.V1, Version.V2)
    )
    peer.endpoint = Endpoint(local, EndpointConfig(preferred_versions=versions))
    Path(args.output).mkdir(parents=True, exist_ok=True)
    options = {"key_update": testcase == "keyupdate", "early": False}
    if testcase == "multiconnect":
        for url in urls:
            await fetch(peer, [url], args, h3, None, **options)
    elif testcase in ("resumption", "zerortt"):
        args.wait_ticket = True
        ticket = await fetch(peer, urls[:1], args, h3, None, **options)
        args.wait_ticket = False
        options["early"] = testcase == "zerortt"
        await fetch(peer, urls[1:], args, h3, ticket, **options)
    else:
        await fetch(peer, urls, args, h3, None, **options)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    roles = parser.add_subparsers(dest="role", required=True)
    server = roles.add_parser("server")
    server.add_argument("--host", default="::")
    server.add_argument("--port", type=int, default=443)
    server.add_argument("--cert", default="/certs/cert.pem")
    server.add_argument("--key", default="/certs/priv.key")
    server.add_argument("--root", default="/www")
    server.add_argument("--h3", action="store_true")
    client = roles.add_parser("client")
    client.add_argument("--output", default="/downloads")
    client.add_argument("--h3", action="store_true")
    client.add_argument("urls", nargs="*")
    args = parser.parse_args()
    args.wait_ticket = False
    asyncio.run(serve(args) if args.role == "server" else download(args))


if __name__ == "__main__":
    main()
