<h1 align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://github.com/cnzakii/ngquic/raw/refs/heads/main/docs/overrides/assets/brand/ngquic-lockup-dark.svg">
    <img src="https://github.com/cnzakii/ngquic/raw/refs/heads/main/docs/overrides/assets/brand/ngquic-lockup-light.svg" height="56" alt="ngquic">
  </picture>
</h1>

<p align="center">
  <strong>A fast <a href="https://sans-io.readthedocs.io/">Sans-I/O</a> QUIC and HTTP/3 library for Python, powered by <a href="https://github.com/ngtcp2/ngtcp2">ngtcp2</a> and <a href="https://github.com/ngtcp2/nghttp3">nghttp3</a>.</strong>
</p>

<p align="center">
  <a href="https://github.com/cnzakii/ngquic/actions/workflows/ci.yml"><img src="https://github.com/cnzakii/ngquic/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://codecov.io/gh/cnzakii/ngquic"><img src="https://codecov.io/gh/cnzakii/ngquic/graph/badge.svg" alt="codecov"></a>
  <a href="https://codspeed.io/cnzakii/ngquic"><img src="https://img.shields.io/endpoint?url=https://codspeed.io/badge.json" alt="CodSpeed"></a>
  <a href="https://pypi.org/project/ngquic/"><img src="https://img.shields.io/pypi/v/ngquic.svg" alt="PyPI"></a>
  <a href="https://pypi.org/project/ngquic/"><img src="https://img.shields.io/pypi/pyversions/ngquic.svg" alt="Python versions"></a>
  <a href="https://github.com/cnzakii/ngquic/blob/main/pyproject.toml"><img src="https://img.shields.io/badge/free--threaded-3.14t%20%7C%203.15t-3776AB?logo=python&amp;logoColor=white" alt="Free-threaded CPython 3.14t and 3.15t"></a>
  <a href="https://github.com/cnzakii/ngquic/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
</p>

Build QUIC and HTTP/3 clients, servers, proxies, and protocol tools on the
sockets and event loop you already use. ngquic turns received datagrams into
events and your calls into datagrams to send; your code decides how and when
those datagrams move, and tells ngquic what time it is.

> ngquic is currently alpha software. Its public API may change before the
> first stable release.

## Why ngquic

- **Fast.** ngquic completes handshakes 4× faster than the pure-Python
  [aioquic](https://github.com/aiortc/aioquic), and moves data and requests
  24–80× faster. See [every measured scenario](#performance).
- **Proven protocol engines.** Packet protection, loss recovery, congestion
  control, flow control, and path validation come from
  [ngtcp2](https://github.com/ngtcp2/ngtcp2); HTTP/3 and QPACK come from
  [nghttp3](https://github.com/ngtcp2/nghttp3), the pair behind curl's HTTP/3.
  TLS 1.3 comes from [AWS-LC](https://github.com/aws/aws-lc), with
  post-quantum key exchange. CI runs the
  [QUIC interop runner](https://github.com/quic-interop/quic-interop-runner)
  against quic-go, quiche, msquic, and picoquic on every pull request and
  against every implementation it lists each week, and the
  [h3spec](https://github.com/kazu-yamamoto/h3spec) conformance suite.
- **Python-native and typed.** Immutable events with readable `repr()` and
  `match` support, Python exceptions, and precise stubs for editors and type
  checkers.
- **Fits any runtime.** ngquic never opens sockets or starts an event loop, so
  the same code works with asyncio, threads, Trio, or in-memory tests.

## Quick look

A client and a server exchange one stream in memory, with a certificate for
`localhost` signed by `ca.pem`. A real program sends each `transmit.data` to
`transmit.remote_addr` on its UDP socket and passes the datagrams it reads to
`receive_datagram()`.

```python
import time

import ngquic

server_tls = ngquic.TLSContext(ngquic.Role.SERVER)
server_tls.load_cert_chain("cert.pem", "key.pem")
server_tls.set_alpn_protocols(["echo"])
client_tls = ngquic.TLSContext(ngquic.Role.CLIENT)
client_tls.load_verify_locations(cafile="ca.pem")
client_tls.set_alpn_protocols(["echo"])

server_endpoint = ngquic.Endpoint(("127.0.0.1", 4433))
client_endpoint = ngquic.Endpoint(("127.0.0.1", 50000))
client = client_endpoint.connect(
    server_endpoint.local_addr, time.monotonic(),
    tls=client_tls, server_name="localhost",
)
server = None
replied = False

while not replied:
    now = time.monotonic()
    for transmit in client.datagrams_to_send(now):
        incoming = server_endpoint.receive_datagram(
            transmit.data, client_endpoint.local_addr, now
        )
        if isinstance(incoming, ngquic.Incoming):
            server = incoming.accept(tls=server_tls)
    for transmit in server.datagrams_to_send(now):
        client_endpoint.receive_datagram(
            transmit.data, server_endpoint.local_addr, now
        )

    for event in server.events():
        if isinstance(event, ngquic.StreamDataReceived):
            reply = event.data.upper()
            server.send_stream_data(event.stream_id, reply, end_stream=True)
    for event in client.events():
        match event:
            case ngquic.HandshakeCompleted():
                print(event)
                stream_id = client.open_stream()
                client.send_stream_data(stream_id, b"hello", end_stream=True)
            case ngquic.StreamDataReceived(end_stream=True):
                print(event)
                replied = True
```

```text
HandshakeCompleted(alpn_protocol='echo', session_resumed=False, early_data_accepted=False)
StreamDataReceived(stream_id=0, data=b'HELLO', end_stream=True, early=False)
```

## Installation

```console
python -m pip install ngquic
```

Or add it to a [uv](https://docs.astral.sh/uv/) project:

```console
uv add ngquic
```

ngquic supports CPython 3.10 through 3.15, including free-threaded 3.14t and
3.15t. Wheels bundle ngtcp2, nghttp3, and AWS-LC for Linux (glibc and musl),
macOS, and Windows on x86_64 and arm64, so no system library is needed; it
does not use Python's `ssl` module. Building from source needs CMake and a C
compiler; see [CONTRIBUTING.md][contributing-guide].

## What ngquic handles

An `Endpoint` owns one UDP address: it routes datagrams to connections by
connection ID, and answers new clients with Retry, address validation tokens,
version negotiation, and stateless resets. A server receives an `Incoming`
for each new connection attempt and decides to `accept()`, `retry()`,
`refuse()`, or `ignore()` it.

Each `Connection` runs QUIC version 1 or 2 (RFC 9000, 9001, 9002, 9369) in the
client or server role: bidirectional and unidirectional streams, unreliable
datagrams (RFC 9221), 0-RTT resumption, key updates, connection migration, an
early `PathDegrading` report when a path goes dark, and output batched for GSO.

Pass `h3=H3Config()` to `connect()` or `accept()` and you get an
`H3Connection` from `ngquic.h3` instead: requests, responses, trailers, and
graceful shutdown with QPACK (RFC 9114, 9204), priorities (RFC 9218), extended
CONNECT (RFC 9220), and HTTP datagrams (RFC 9297).

Your application owns sockets, the event loop, DNS, certificate storage, and
application timeouts. Calls are synchronous and never block on I/O. Each
`Transmit` is one UDP datagram unless you ask for `datagrams_to_send(gso=True)`,
for a socket that sends with Linux `UDP_SEGMENT`: then it carries several of
`segment_size` bytes. Split a GRO batch before `receive_datagram()`.

On Linux and macOS, `ngquic.udp.UDPSocket` makes those system calls on a socket
you own and wait on: segmented sends (GSO), batched and coalesced receives
(`recvmmsg`, GRO), ECN and destination addresses. Its `receive_into(endpoint,
now)` feeds an endpoint without a Python object per datagram.

## Running over UDP

A client sends a request on a real socket. `get_timer()` says when ngquic
next needs `handle_timer()`; `datagrams_to_send()` is called after every
input. To verify a public server, call `tls.load_default_certs()` in place of
loading `ca.pem`: it trusts what Python's `ssl` module trusts by default.

```python
import socket
import time

from ngquic import Endpoint, HandshakeCompleted, Role, TLSContext
from ngquic.h3 import DataReceived, H3Config, ResponseReceived

tls = TLSContext(Role.CLIENT)
tls.load_verify_locations(cafile="ca.pem")
tls.set_alpn_protocols(["h3"])

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("127.0.0.1", 0))
endpoint = Endpoint(sock.getsockname())
connection = endpoint.connect(
    ("127.0.0.1", 4433), time.monotonic(), tls=tls, server_name="localhost",
    h3=H3Config(),
)

done = False
while not done:
    for transmit in connection.datagrams_to_send(time.monotonic()):
        sock.sendto(transmit.data, transmit.remote_addr)

    timer = connection.get_timer()
    sock.settimeout(None if timer is None else max(timer - time.monotonic(), 0))
    try:
        data, address = sock.recvfrom(65535)
        endpoint.receive_datagram(data, address, time.monotonic())
    except (TimeoutError, BlockingIOError):  # BlockingIOError for a timeout of 0
        # The deadline this wait was armed for, as the timeout may end early.
        connection.handle_timer(max(timer, time.monotonic()))

    for event in connection.events():
        match event:
            case HandshakeCompleted():
                connection.send_request(
                    [(b":method", b"GET"), (b":scheme", b"https"),
                     (b":authority", b"localhost"), (b":path", b"/")],
                    end_stream=True,
                )
            case ResponseReceived():
                print(event.headers)
                done = event.end_stream
            case DataReceived():
                print(event.data)
                done = event.end_stream

connection.close()
for transmit in connection.datagrams_to_send(time.monotonic()):
    sock.sendto(transmit.data, transmit.remote_addr)
```

A server answers each `RequestReceived` with `send_response()`, then
`send_data()` and `end_stream()` or `send_trailers()`. It shuts down with
`send_shutdown_notice()` and `send_goaway()`, and closes with
`H3ErrorCode.H3_NO_ERROR` once `is_drained` is true.

## Threads

Drive an `Endpoint` and the connections it created from one thread at a time:
they share connection IDs and native state, and their methods take no locks.
Separate endpoints may run in parallel threads, including on free-threaded
CPython: ngquic declares free-threading support, so importing it does not turn
the GIL back on. A `TLSContext` may be shared by endpoints in different
threads once it is configured; change its settings only before passing it to
`connect()` or `accept()`. Configuration objects and events are immutable and
may cross threads freely.

## Performance

[`benchmarks/compare.py`][benchmark-script] runs a client and a server of the
same library in memory on one core, so the numbers are what the protocol work
costs, without sockets or an event loop. Scenarios follow the QUIC
performance draft as MsQuic's secnetperf runs it, and request latency follows
gRPC's benchmarking guide: one request in flight, then 64. Both libraries use
NewReno, 16 MiB flow-control windows, the same ECDSA P-256 certificate, and
AES-128-GCM. Each table compares one dimension; the last column is how many
times better ngquic does.

<!-- benchmark:start -->

**Handshakes per second** (higher is better)

|  | ngquic | aioquic | ngquic advantage |
|---|---:|---:|---:|
| QUIC | 4,435 | 989 | 4.5× |
| HTTP/3 | 3,987 | 867 | 4.6× |

**Bulk transfer, Gbit/s** (higher is better)

|  | ngquic | aioquic | ngquic advantage |
|---|---:|---:|---:|
| QUIC, download | 10.3 | 0.251 | 41.2× |
| QUIC, upload | 9.98 | 0.249 | 40.0× |
| HTTP/3, download | 9.50 | 0.213 | 44.5× |
| HTTP/3, upload | 9.71 | 0.216 | 44.9× |

**Requests per second** (higher is better)

|  | ngquic | aioquic | ngquic advantage |
|---|---:|---:|---:|
| QUIC, 1 in flight | 89,019 | 3,044 | 29.2× |
| QUIC, 64 in flight | 158,890 | 2,024 | 78.5× |
| HTTP/3, 1 in flight | 64,010 | 2,597 | 24.7× |
| HTTP/3, 64 in flight | 106,322 | 1,853 | 57.4× |

<details>
<summary>Request latency, datagrams, memory, and bytes on the wire</summary>

**Request latency, µs** (lower is better)

|  | ngquic | aioquic | ngquic advantage |
|---|---:|---:|---:|
| QUIC, P50, 1 in flight | 10.1 | 325 | 32.1× |
| QUIC, P99, 1 in flight | 13.2 | 725 | 54.7× |
| QUIC, P50, 64 in flight | 383 | 31,078 | 81.1× |
| QUIC, P99, 64 in flight | 509 | 51,375 | 100.9× |
| HTTP/3, P50, 1 in flight | 15.0 | 383 | 25.6× |
| HTTP/3, P99, 1 in flight | 19.2 | 608 | 31.7× |
| HTTP/3, P50, 64 in flight | 572 | 34,053 | 59.5× |
| HTTP/3, P99, 64 in flight | 723 | 51,806 | 71.6× |

**Datagrams per second** (higher is better)

|  | ngquic | aioquic | ngquic advantage |
|---|---:|---:|---:|
| QUIC | 798,645 | 32,540 | 24.5× |

**Memory per idle connection, KiB** (lower is better)

|  | ngquic | aioquic | ngquic advantage |
|---|---:|---:|---:|
| QUIC | 27.6 | 95.1 | 3.4× |
| HTTP/3 | 46.1 | 104 | 2.3× |

**Bytes on the wire per request** (lower is better)

|  | ngquic | aioquic | ngquic advantage |
|---|---:|---:|---:|
| QUIC, 1 in flight | 4,836 | 4,783 | 1.0× |
| QUIC, 64 in flight | 4,775 | 4,785 | 1.0× |
| HTTP/3, 1 in flight | 4,860 | 4,806 | 1.0× |
| HTTP/3, 64 in flight | 4,795 | 4,809 | 1.0× |

</details>

_Environment: ngquic 0.2.1 · ngtcp2 1.26.0 · nghttp3 1.19.0 · AWS-LC 5.15.0 · aioquic 1.8.0 · CPython 3.13.12 · Apple M4 · Darwin arm64 · 2026-11-28_

<!-- benchmark:end -->

These are protocol-layer measurements. End-to-end gains depend on how much of
your program's time goes to QUIC and HTTP/3 processing rather than sockets,
system calls, and application work.

## Related projects

[h11r](https://github.com/cnzakii/h11r) (HTTP/1.1) and [ngh2](https://github.com/cnzakii/ngh2) (HTTP/2)
are the other Sans-I/O protocol libraries for Python in this family.

## Contributing

See [CONTRIBUTING.md][contributing-guide] for development, testing, and
release guidance.

## License

ngquic is MIT licensed. Distributed wheels also contain ngtcp2 and nghttp3
under the MIT license and AWS-LC under its Apache 2.0, ISC, and MIT terms;
their license texts are included in every distribution.

[benchmark-script]: https://github.com/cnzakii/ngquic/blob/main/benchmarks/compare.py
[contributing-guide]: https://github.com/cnzakii/ngquic/blob/main/CONTRIBUTING.md
