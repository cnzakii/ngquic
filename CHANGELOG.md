# Changelog

User-visible changes to ngquic are recorded here.

## [Unreleased]

## [0.1.0] - 2026-11-23

### Added

- QUIC version 1 and 2 over ngtcp2 and AWS-LC: streams, unreliable
  datagrams, 0-RTT resumption, Retry and address validation tokens,
  stateless reset, connection migration and output batched for GSO.
- HTTP/3 over nghttp3 in `ngquic.h3`: QPACK, priorities, extended CONNECT
  and HTTP datagrams.
