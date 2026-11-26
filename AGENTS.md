# ngquic Repository Guidance

Read [CONTRIBUTING.md](CONTRIBUTING.md) first: its setup, checks, code
conventions and test rules apply to every change. This file adds what an
agent needs beyond them.

## Product Boundary

- `ngquic` is a sans-I/O QUIC library for Python (RFC 8999, 9000, 9001,
  9002, 9221, 9287, 9368, 9369): a Cython binding over vendored ngtcp2 and
  AWS-LC. HTTP/3 (RFC 9114, 9204, 9218, 9220, 9297, 9412) lives in
  `ngquic.h3` over vendored nghttp3; the QUIC API stays usable without it.
  Other application protocols build on ngquic and do not live here.
- ngtcp2 owns connection and stream state, packet protection, loss
  recovery, congestion control, flow control windows, PMTUD, key update and
  path validation; AWS-LC owns the TLS 1.3 handshake. Do not reimplement
  native behavior in the binding without a demonstrated need.
- The binding owns what ngtcp2 leaves to its application: the endpoint
  (connection ID demultiplexing, Retry, address validation tokens, version
  negotiation, stateless reset), unacknowledged stream data, flow control
  credit, the closing and draining periods, and timers on the caller's
  clock. It also owns the Python objects, event and error translation,
  buffer lifetimes, configuration mapping, type stubs and packaging.
- Sockets, event loops, DNS, certificate storage policy and application
  timeouts stay outside: callers pass datagrams, addresses and `now` in, and
  send what comes out. The optional `ngquic.udp` makes the batched UDP
  system calls on a socket the caller owns; the protocol core never depends
  on it.
- RFCs, ngtcp2 documentation and pinned source are authority. ngtcp2's
  examples and mature users (curl) show how its API is meant to be used;
  quinn, quiche and aioquic are observed practice, evidence about tradeoffs
  rather than specification.

## Design Rules

- Dependencies point one way: `h3` builds on QUIC, optional modules build on
  the core, and neither adds modes or flags to what it builds on.
- Share a conversion or helper rather than copying it; two copies of one
  rule drift apart.
- An error surfaces on the object the caller holds, so the caller knows
  what failed; one connection's failure never escapes a call that serves
  several.
- Public API grows only for a caller who needs it. Anything ngtcp2 offers
  that the API does not expose has its reason recorded in the untracked API
  coverage notes.
- Platform-specific code builds and runs only where it is implemented, and
  its tests skip elsewhere with a stated reason.
- Each native class keeps its declaration (`.pxd`) beside its
  implementation (`.pxi`); members follow the order of the `.pyi` stub.
- Vendored libraries are pinned upstream releases, never edited in place.

## Native Code Rules

- Callbacks from ngtcp2, nghttp3 and AWS-LC never raise: they store the
  exception and return an error code, and the binding raises it once
  control is back with the caller.
- The libraries allocate through Python's raw allocator, so any allocation
  can fail: store a Python object where the binding owns it before handing
  its pointer to native code.
- A pointer from native code is valid only as long as its API documents;
  copy what must outlive that. Data handed to ngtcp2 stays alive until
  ngtcp2 is done with it.
- Build lists in Cython with loops, not comprehensions: Cython 3.3 releases
  a comprehension's item twice when appending it fails.
- Ruff and ty do not check Cython: binding changes must also pass
  `cython-lint`, compile, and run the relevant tests.

## Working Rules

- Read the affected implementation, its callers, tests, exports, stubs and
  configuration before editing. Establish the requested outcome and its
  non-goals before adding files or abstractions.
- Open an issue or ask before adding public API or changing protocol
  behavior, as CONTRIBUTING.md asks.
- A Python contract changes in its runtime code, exports, stub, tests and
  changelog together.
- Tests import shared helpers only from the support package, never from
  each other; fixtures live in `conftest.py`.
- Verify platform-specific behavior on that platform. For a fix, break the
  code once by hand and confirm a test fails.
- Run the checks of CONTRIBUTING.md on what you touch, and report exactly
  which ran and their results. Never claim that a check passed without
  running it.
- Keep generated output, local environments, editor state, temporary
  reports and personal instructions out of version control.
