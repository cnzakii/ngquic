"""Compare the protocol engines of ngquic and aioquic, over QUIC and HTTP/3.

Both stacks are Sans-I/O, so each scenario joins a client and a server of
one stack in memory on a virtual clock: the numbers are what the protocol
work costs one core, with no sockets or event loop. The scenarios are those
of the QUIC performance draft (draft-banks-quic-performance) as MsQuic's
secnetperf runs them: a client stream's first 8 bytes ask the server for that
many response bytes. Requests per second follow gRPC's benchmarking guide:
one request in flight for latency, 64 for throughput, each with P50 and P99.

Both stacks run NewReno with 16 MiB flow-control windows on the same ECDSA
P-256 certificate; both negotiate AES-128-GCM where the CPU has AES
instructions. Memory per idle connection is what tracemalloc sees: Python
objects, and for ngquic also ngtcp2 and nghttp3, which allocate through
Python; neither stack's TLS library is counted. Run on an idle machine, and
quote numbers only with the environment the report prints.

    uv run --group compare python benchmarks/compare.py
"""

import argparse
import gc
import json
import platform
import statistics
import sys
import time
import tracemalloc
from collections.abc import Callable
from pathlib import Path

from aioquic import __version__ as aioquic_version
from aioquic.buffer import Buffer
from aioquic.h3 import events as aio_h3
from aioquic.h3.connection import H3Connection as AioH3
from aioquic.quic import events as aio
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.connection import QuicConnection
from aioquic.quic.packet import pull_quic_header

import ngquic
from ngquic import (
    CongestionControl,
    DatagramReceived,
    Endpoint,
    HandshakeConfirmed,
    Incoming,
    Role,
    StreamDataReceived,
    TLSContext,
    TransportConfig,
)
from ngquic.h3 import (
    DataReceived,
    H3Config,
    RequestReceived,
    ResponseReceived,
)

CERTS = Path(__file__).parents[1] / "tests" / "support" / "certs"
CLIENT, SERVER = ("127.0.0.1", 50000), ("127.0.0.1", 4433)
WINDOW = 16 << 20
# secnetperf's request-response example: -up:512 -down:4kb.
REQUEST, RESPONSE = 512, 4096
DATAGRAM = 1000
_ZEROS = bytes(256 << 20)


def payload(size: int) -> bytes:
    """``size`` zero bytes; cached so no scenario times an allocation."""
    return _ZEROS[:size] if size < len(_ZEROS) else bytes(size)


# ---- one client and one server of one stack, on a virtual clock


class Pair:
    """A connected client and server; subclasses speak one stack and protocol."""

    def __init__(self) -> None:
        self.now = 1.0
        self.wire = 0
        self.received: dict[int, int] = {}
        self.finished: dict[int, float] = {}
        self.wanted: dict[int, int] = {}
        self.datagrams = 0

    def run(self, until: Callable[[], object]) -> None:
        while not until():
            if self.exchange():
                continue
            timers = [timer for timer in self.timers() if timer is not None]
            if not timers:
                raise RuntimeError("the pair stalled")
            self.now = max(self.now, min(timers))
            self.fire()

    def done(self, stream_id: int) -> bool:
        return stream_id in self.finished

    def complete(self, stream_id: int) -> None:
        self.finished[stream_id] = time.perf_counter()

    # Subclasses: connect(), request(up, down) -> stream_id, send_datagram(),
    # exchange() -> moved, timers(), fire().


class QuicPair(Pair):
    h3: H3Config | None = None
    alpn = "perf"

    def __init__(self) -> None:
        super().__init__()
        self.client_endpoint = Endpoint(CLIENT)
        self.server_endpoint = Endpoint(SERVER)
        self.server = None
        self.client = self.connect_client()
        self.pending: dict[int, bytes] = {}

    def connect_client(self):
        if self.h3 is None:
            return self.client_endpoint.connect(
                SERVER,
                self.now,
                tls=TLS[Role.CLIENT, self.alpn],
                server_name="localhost",
                transport=TRANSPORT,
            )
        return self.client_endpoint.connect(
            SERVER,
            self.now,
            tls=TLS[Role.CLIENT, self.alpn],
            server_name="localhost",
            transport=TRANSPORT,
            h3=self.h3,
        )

    def connect(self) -> None:
        confirmed = []
        self.on_client = lambda event: (
            confirmed.append(event) if isinstance(event, HandshakeConfirmed) else None
        )
        self.run(lambda: confirmed and self.server is not None)
        self.on_client = self.client_event

    def accept(self, incoming: Incoming):
        if self.h3 is None:
            return incoming.accept(tls=TLS[Role.SERVER, self.alpn], transport=TRANSPORT)
        return incoming.accept(
            tls=TLS[Role.SERVER, self.alpn], transport=TRANSPORT, h3=self.h3
        )

    def exchange(self) -> bool:
        moved = False
        for transmit in self.client.datagrams_to_send(self.now):
            moved = True
            self.wire += len(transmit.data)
            result = self.server_endpoint.receive_datagram(
                transmit.data, CLIENT, self.now
            )
            if isinstance(result, Incoming):
                self.server = self.accept(result)
        if self.server is not None:
            for transmit in self.server.datagrams_to_send(self.now):
                moved = True
                self.wire += len(transmit.data)
                self.client_endpoint.receive_datagram(transmit.data, SERVER, self.now)
            for event in self.server.events():
                self.server_event(event)
        for event in self.client.events():
            self.on_client(event)
        return moved

    def timers(self):
        return [self.client.get_timer()] + (
            [self.server.get_timer()] if self.server is not None else []
        )

    def fire(self) -> None:
        for connection in (self.client, self.server):
            if connection is not None:
                timer = connection.get_timer()
                if timer is not None and timer <= self.now:
                    connection.handle_timer(self.now)

    def request(self, up: int, down: int) -> int:
        stream_id = self.client.open_stream()
        self.wanted[stream_id] = down
        self.received[stream_id] = 0
        self.client.send_stream_data(
            stream_id, down.to_bytes(8, "big") + payload(up), end_stream=True
        )
        return stream_id

    def client_event(self, event) -> None:
        if isinstance(event, StreamDataReceived):
            self.received[event.stream_id] += len(event.data)
            if event.end_stream:
                self.complete(event.stream_id)

    def server_event(self, event) -> None:
        if isinstance(event, StreamDataReceived):
            head = self.pending.get(event.stream_id, b"")
            if len(head) < 8:
                self.pending[event.stream_id] = head + event.data[: 8 - len(head)]
            if event.end_stream:
                down = int.from_bytes(self.pending.pop(event.stream_id), "big")
                self.server.send_stream_data(
                    event.stream_id, payload(down), end_stream=True
                )
        elif isinstance(event, DatagramReceived):
            self.datagrams += 1

    def send_datagram(self) -> None:
        self.client.send_datagram(payload(DATAGRAM))


class H3Pair(QuicPair):
    h3 = H3Config()
    alpn = "h3"

    def request(self, up: int, down: int) -> int:
        stream_id = self.client.send_request(
            [
                (b":method", b"POST"),
                (b":scheme", b"https"),
                (b":authority", b"localhost"),
                (b":path", b"/%d" % down),
            ]
        )
        self.wanted[stream_id] = down
        self.received[stream_id] = 0
        self.client.send_data(stream_id, payload(up), end_stream=True)
        return stream_id

    def client_event(self, event) -> None:
        if isinstance(event, DataReceived):
            self.received[event.stream_id] += len(event.data)
            if event.end_stream:
                self.complete(event.stream_id)
        elif isinstance(event, ResponseReceived) and event.end_stream:
            self.complete(event.stream_id)

    def server_event(self, event) -> None:
        if isinstance(event, RequestReceived):
            self.pending[event.stream_id] = dict(event.headers)[b":path"]
            if not event.end_stream:
                return
        elif not (isinstance(event, DataReceived) and event.end_stream):
            return
        down = int(self.pending.pop(event.stream_id)[1:])
        self.server.send_response(event.stream_id, [(b":status", b"200")])
        self.server.send_data(event.stream_id, payload(down), end_stream=True)


class AioquicPair(Pair):
    alpn = "perf"

    def __init__(self) -> None:
        super().__init__()
        self.client = QuicConnection(configuration=aio_config(True, self.alpn))
        self.client.connect(SERVER, now=self.now)
        self.server: QuicConnection | None = None
        self.pending: dict[int, bytes] = {}
        self.handshake = False

    def connect(self) -> None:
        self.run(lambda: self.handshake and self.server is not None)

    def created(self) -> None:
        """Run once the server connection exists."""

    def exchange(self) -> bool:
        moved = False
        for data, _ in self.client.datagrams_to_send(self.now):
            moved = True
            self.wire += len(data)
            if self.server is None:
                header = pull_quic_header(Buffer(data=data), host_cid_length=8)
                self.server = QuicConnection(
                    configuration=aio_config(False, self.alpn),
                    original_destination_connection_id=header.destination_cid,
                )
                self.created()
            self.server.receive_datagram(data, CLIENT, self.now)
        if self.server is not None:
            for data, _ in self.server.datagrams_to_send(self.now):
                moved = True
                self.wire += len(data)
                self.client.receive_datagram(data, SERVER, self.now)
            while (event := self.server.next_event()) is not None:
                self.server_event(event)
        while (event := self.client.next_event()) is not None:
            self.client_event(event)
        return moved

    def timers(self):
        return [self.client.get_timer()] + (
            [self.server.get_timer()] if self.server is not None else []
        )

    def fire(self) -> None:
        for connection in (self.client, self.server):
            if connection is not None:
                timer = connection.get_timer()
                if timer is not None and timer <= self.now:
                    connection.handle_timer(self.now)

    def request(self, up: int, down: int) -> int:
        stream_id = self.client.get_next_available_stream_id()
        self.wanted[stream_id] = down
        self.received[stream_id] = 0
        self.client.send_stream_data(
            stream_id, down.to_bytes(8, "big") + payload(up), end_stream=True
        )
        return stream_id

    def client_event(self, event) -> None:
        if isinstance(event, aio.HandshakeCompleted):
            self.handshake = True
        elif isinstance(event, aio.StreamDataReceived):
            self.received[event.stream_id] += len(event.data)
            if event.end_stream:
                self.complete(event.stream_id)

    def server_event(self, event) -> None:
        assert self.server is not None
        if isinstance(event, aio.StreamDataReceived):
            head = self.pending.get(event.stream_id, b"")
            if len(head) < 8:
                self.pending[event.stream_id] = head + event.data[: 8 - len(head)]
            if event.end_stream:
                down = int.from_bytes(self.pending.pop(event.stream_id), "big")
                self.server.send_stream_data(
                    event.stream_id, payload(down), end_stream=True
                )
        elif isinstance(event, aio.DatagramFrameReceived):
            self.datagrams += 1

    def send_datagram(self) -> None:
        self.client.send_datagram_frame(payload(DATAGRAM))


class AioquicH3Pair(AioquicPair):
    alpn = "h3"

    def __init__(self) -> None:
        super().__init__()
        self.client_h3 = AioH3(self.client)
        self.server_h3: AioH3 | None = None

    def created(self) -> None:
        assert self.server is not None
        self.server_h3 = AioH3(self.server)

    def request(self, up: int, down: int) -> int:
        stream_id = self.client.get_next_available_stream_id()
        self.wanted[stream_id] = down
        self.received[stream_id] = 0
        self.client_h3.send_headers(
            stream_id,
            [
                (b":method", b"POST"),
                (b":scheme", b"https"),
                (b":authority", b"localhost"),
                (b":path", b"/%d" % down),
            ],
        )
        self.client_h3.send_data(stream_id, payload(up), end_stream=True)
        return stream_id

    def client_event(self, event) -> None:
        if isinstance(event, aio.HandshakeCompleted):
            self.handshake = True
        for h3_event in self.client_h3.handle_event(event):
            if isinstance(h3_event, aio_h3.DataReceived):
                self.received[h3_event.stream_id] += len(h3_event.data)
            if (
                isinstance(h3_event, (aio_h3.DataReceived, aio_h3.HeadersReceived))
                and h3_event.stream_ended
            ):
                self.complete(h3_event.stream_id)

    def server_event(self, event) -> None:
        assert self.server_h3 is not None
        for h3_event in self.server_h3.handle_event(event):
            if isinstance(h3_event, aio_h3.HeadersReceived):
                self.pending[h3_event.stream_id] = dict(h3_event.headers)[b":path"]
            if (
                isinstance(h3_event, (aio_h3.DataReceived, aio_h3.HeadersReceived))
                and h3_event.stream_ended
            ):
                down = int(self.pending.pop(h3_event.stream_id)[1:])
                self.server_h3.send_headers(h3_event.stream_id, [(b":status", b"200")])
                self.server_h3.send_data(
                    h3_event.stream_id, payload(down), end_stream=True
                )


# ---- configuration shared by every pair

TRANSPORT = TransportConfig(
    max_data=WINDOW,
    max_stream_data_bidi_local=WINDOW,
    max_stream_data_bidi_remote=WINDOW,
    max_window=WINDOW,
    max_stream_window=WINDOW,
    max_streams_bidi=1000,
    stream_write_buffer_high=1 << 40,
    congestion_control=CongestionControl.RENO,
    max_datagram_frame_size=65535,
    max_datagram_queue=1 << 20,
)


def ngquic_tls() -> dict:
    contexts = {}
    for alpn in ("perf", "h3"):
        server = TLSContext(Role.SERVER)
        server.load_cert_chain(str(CERTS / "cert.pem"), str(CERTS / "key.pem"))
        server.set_alpn_protocols([alpn])
        client = TLSContext(Role.CLIENT)
        client.load_verify_locations(cafile=str(CERTS / "ca.pem"))
        client.set_alpn_protocols([alpn])
        contexts[Role.SERVER, alpn] = server
        contexts[Role.CLIENT, alpn] = client
    return contexts


TLS = ngquic_tls()


def aio_config(is_client: bool, alpn: str) -> QuicConfiguration:
    config = QuicConfiguration(
        is_client=is_client,
        alpn_protocols=[alpn],
        congestion_control_algorithm="reno",
        max_data=WINDOW,
        max_stream_data=WINDOW,
        max_datagram_frame_size=65535,
    )
    if is_client:
        config.server_name = "localhost"
        config.load_verify_locations(str(CERTS / "ca.pem"))
    else:
        config.load_cert_chain(str(CERTS / "cert.pem"), str(CERTS / "key.pem"))
    return config


# ---- scenarios: each returns {metric: value}


def handshakes(kind: type[Pair], count: int) -> dict:
    start = time.process_time()
    for _ in range(count):
        kind().connect()
    return {"handshakes/s": count / (time.process_time() - start)}


def transfer(kind: type[Pair], size: int, *, upload: bool) -> dict:
    pair = kind()
    pair.connect()
    start = time.process_time()
    stream_id = pair.request(size, 0) if upload else pair.request(0, size)
    pair.run(lambda: pair.done(stream_id))
    return {"Gbit/s": size * 8 / (time.process_time() - start) / 1e9}


def requests(kind: type[Pair], count: int, in_flight: int) -> dict:
    pair = kind()
    pair.connect()
    started: dict[int, float] = {}
    latencies: list[float] = []
    sent = 0

    def refill() -> bool:
        nonlocal sent
        latencies.extend(
            pair.finished[stream_id] - started.pop(stream_id)
            for stream_id in [s for s in started if pair.done(s)]
        )
        while len(started) < in_flight and sent < count:
            started[pair.request(REQUEST, RESPONSE)] = time.perf_counter()
            sent += 1
        return len(latencies) == count

    wire = pair.wire
    start = time.process_time()
    pair.run(refill)
    elapsed = time.process_time() - start
    quantiles = statistics.quantiles(latencies, n=100)
    return {
        "requests/s": count / elapsed,
        "P50 µs": quantiles[49] * 1e6,
        "P99 µs": quantiles[98] * 1e6,
        "wire bytes/request": (pair.wire - wire) / count,
    }


def datagrams(kind: type[Pair], count: int) -> dict:
    pair = kind()
    pair.connect()
    start = time.process_time()
    for _ in range(count):
        pair.send_datagram()
    pair.run(lambda: pair.datagrams == count)
    return {"datagrams/s": count / (time.process_time() - start)}


def idle_memory(kind: type[Pair], count: int) -> dict:
    gc.collect()
    tracemalloc.start()
    before = tracemalloc.get_traced_memory()[0]
    pairs = []
    for _ in range(count):
        pair = kind()
        pair.connect()
        pairs.append(pair)
    gc.collect()
    traced = tracemalloc.get_traced_memory()[0] - before
    tracemalloc.stop()
    # A pair is a client and a server connection.
    return {"KiB/connection": traced / count / 2 / 1024}


LOWER_IS_BETTER = {"P50 µs", "P99 µs", "wire bytes/request", "KiB/connection"}


def scenarios(quick: bool) -> list[tuple[str, Callable[[type[Pair]], dict], bool]]:
    scale = 10 if quick else 1
    bulk = (64 << 20) // scale
    return [
        ("handshakes", lambda k: handshakes(k, 200 // scale), True),
        ("download", lambda k: transfer(k, bulk, upload=False), True),
        ("upload", lambda k: transfer(k, bulk, upload=True), True),
        ("requests, 1 in flight", lambda k: requests(k, 2000 // scale, 1), True),
        ("requests, 64 in flight", lambda k: requests(k, 20000 // scale, 64), True),
        ("datagrams", lambda k: datagrams(k, 50000 // scale), False),
        ("idle connections", lambda k: idle_memory(k, 500 // scale), True),
    ]


STACKS = {
    "QUIC": {"ngquic": QuicPair, "aioquic": AioquicPair},
    "HTTP/3": {"ngquic": H3Pair, "aioquic": AioquicH3Pair},
}


def measure(rounds: int, quick: bool, stacks_wanted: set[str], only: str) -> list[dict]:
    """Median of ``rounds`` runs after one warm-up, alternating the stacks."""
    rows = []
    for protocol, all_stacks in STACKS.items():
        stacks = {
            name: kind for name, kind in all_stacks.items() if name in stacks_wanted
        }
        for name, scenario, both in scenarios(quick):
            if (protocol == "HTTP/3" and not both) or only not in name:
                continue
            samples: dict[str, list[dict]] = {stack: [] for stack in stacks}
            for round_ in range(rounds + 1):
                for stack, kind in stacks.items():
                    result = scenario(kind)
                    if round_:
                        samples[stack].append(result)
            for metric in next(iter(samples.values()))[0]:
                values = {
                    stack: statistics.median(sample[metric] for sample in runs)
                    for stack, runs in samples.items()
                }
                rows.append(
                    {"protocol": protocol, "scenario": name, "metric": metric, **values}
                )
            print(f"  {protocol} {name}", file=sys.stderr)
    return rows


def environment() -> dict:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "ngquic": ngquic.__version__,
        "ngtcp2": ngquic.ngtcp2_version(),
        "tls": ngquic.tls_version(),
        "aioquic": aioquic_version,
    }


def advantage(row: dict) -> float:
    """How many times better ngquic does, whichever way the metric points."""
    ratio = row["ngquic"] / row["aioquic"]
    return 1 / ratio if row["metric"] in LOWER_IS_BETTER else ratio


# One table per dimension, so each compares like with like:
# (title, lower is better, [(scenario, metric, row label)]).
TABLES = [
    ("Handshakes per second", False, [("handshakes", "handshakes/s", "")]),
    (
        "Bulk transfer, Gbit/s",
        False,
        [("download", "Gbit/s", "download"), ("upload", "Gbit/s", "upload")],
    ),
    (
        "Requests per second",
        False,
        [
            ("requests, 1 in flight", "requests/s", "1 in flight"),
            ("requests, 64 in flight", "requests/s", "64 in flight"),
        ],
    ),
    (
        "Request latency, µs",
        True,
        [
            ("requests, 1 in flight", "P50 µs", "P50, 1 in flight"),
            ("requests, 1 in flight", "P99 µs", "P99, 1 in flight"),
            ("requests, 64 in flight", "P50 µs", "P50, 64 in flight"),
            ("requests, 64 in flight", "P99 µs", "P99, 64 in flight"),
        ],
    ),
    ("Datagrams per second", False, [("datagrams", "datagrams/s", "")]),
    (
        "Memory per idle connection, KiB",
        True,
        [("idle connections", "KiB/connection", "")],
    ),
    (
        "Bytes on the wire per request",
        True,
        [
            ("requests, 1 in flight", "wire bytes/request", "1 in flight"),
            ("requests, 64 in flight", "wire bytes/request", "64 in flight"),
        ],
    ),
]


def number(value: float) -> str:
    return f"{value:,.0f}" if value >= 100 else f"{value:#.3g}"


def report(rows: list[dict], env: dict) -> str:
    found = {(row["protocol"], row["scenario"], row["metric"]): row for row in rows}
    stacks = [stack for stack in ("ngquic", "aioquic") if stack in rows[0]]
    both = len(stacks) == 2
    lines = []
    for title, lower, entries in TABLES:
        table = [
            (f"{protocol}, {label}" if label else protocol, found[key])
            for protocol in STACKS
            for scenario, metric, label in entries
            if (key := (protocol, scenario, metric)) in found
        ]
        if not table:
            continue
        direction = "lower" if lower else "higher"
        header = ["", *stacks, *(["ngquic advantage"] if both else [])]
        lines += [
            f"**{title}** ({direction} is better)",
            "",
            "| " + " | ".join(header) + " |",
            "|---|" + "---:|" * (len(header) - 1),
        ]
        for label, row in table:
            cells = [number(row[stack]) for stack in stacks]
            if both:
                cells.append(f"{advantage(row):.1f}\N{MULTIPLICATION SIGN}")
            lines.append(f"| {label} | " + " | ".join(cells) + " |")
        lines.append("")
    lines.append(", ".join(f"{key} {value}" for key, value in env.items()))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--quick", action="store_true", help="a tenth of the work")
    parser.add_argument("--json", type=Path, help="write the results as JSON")
    parser.add_argument(
        "--stack", choices=["ngquic", "aioquic"], help="measure one stack only"
    )
    parser.add_argument("--only", default="", help="scenarios whose name has this")
    args = parser.parse_args()
    env = environment()
    stacks = {args.stack} if args.stack else {"ngquic", "aioquic"}
    rows = measure(args.rounds, args.quick, stacks, args.only)
    print(report(rows, env))
    if args.json:
        args.json.write_text(
            json.dumps({"environment": env, "results": rows}, indent=2)
        )


if __name__ == "__main__":
    main()
