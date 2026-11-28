# Changelog

User-visible changes to ngquic are recorded here.

## [Unreleased]

### Fixed

- The Windows wheels typed `ngquic.udp` as available, though it is built only
  on Linux and macOS: its stub now declares nothing on Windows.

## [0.2.0] - 2026-11-28

Built on ngtcp2 1.26.0, nghttp3 1.19.0 and AWS-LC 5.15.0, as 0.1.0.

### Added

- `PathDegrading`: a client reports data in flight that waited
  `TransportConfig.path_degrading_ptos` probe timeouts (default 4, as in
  Google quiche) without acknowledgment progress, so it can stop opening
  streams on a black-holed path before the idle timeout. `PathRecovered`
  follows once the peer acknowledges again.

- `ngquic.udp.UDPSocket` (Linux and macOS): batched UDP I/O on a socket
  the caller owns and waits on, for asyncio, uvloop, trio or selectors.
  `send()` sends a `Transmit` (GSO where the kernel offers it, datagram by
  datagram otherwise), `receive()` reads with `recvmmsg` and GRO, and
  `receive_into()` feeds an `Endpoint` without a Python object per datagram,
  returning the connections and attempts to handle. Sockets are set up for
  QUIC: ECN, destination address and interface, no IP fragmentation. A
  socket connected before wrapping sends only to its peer, as asyncio does.

### Changed

- A protocol callback that fails while `Endpoint.receive_datagram()`
  delivers a datagram drops only its connection, which is returned as
  usual; its next `events()` raises the `InternalError`, instead of
  `receive_datagram()`. A qlog writer failing on the final notice, when
  no call is left to fail, goes to `sys.unraisablehook` instead of escaping
  from whichever call ended the connection.
- `Endpoint`, `connect(local_addr=...)`, `migrate()` and
  `receive_datagram(local_addr=...)` reject a local address with port 0:
  pass the bound socket's address, such as `sock.getsockname()`.
- A client's local address must be a specific one: `connect()` and
  `migrate()` reject `0.0.0.0`, `::` and `::ffff:0.0.0.0`, which also
  rules out connecting from an endpoint bound to one without `local_addr`.
  Datagrams arriving on such a socket report the interface's address,
  which ngtcp2 took for an unknown path and dropped. Connect the socket
  and pass `sock.getsockname()`, as ngtcp2's own client does.

### Fixed

- A client whose restart in another version after Version Negotiation
  failed, for example on an allocation, was left half released, and its
  next call could crash; it is now closed.
- An allocation failure while a list was built in native code, such as
  the versions of a Version Negotiation packet, could crash the process:
  Cython 3.3 releases a comprehension's item twice when appending it
  fails (cython/cython#8162).

## [0.1.0] - 2026-11-23

### Added

- QUIC version 1 and 2 over ngtcp2 and AWS-LC: streams, unreliable
  datagrams, 0-RTT resumption, Retry and address validation tokens,
  stateless reset, connection migration and output batched for GSO.
- HTTP/3 over nghttp3 in `ngquic.h3`: QPACK, priorities, extended CONNECT
  and HTTP datagrams.
