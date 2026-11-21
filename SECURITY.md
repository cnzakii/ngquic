# Security Policy

## Supported Versions

Before the first release, reports against the latest `main` branch are
accepted. After the first release, security fixes are provided for the latest
released version of ngquic.

## Scope

ngquic is a QUIC and HTTP/3 protocol engine without network I/O. Report a
vulnerability when datagrams from a peer make it crash, read or write memory
it does not own, loop, or hold memory beyond a documented limit; when it
accepts a peer certificate that the configured `TLSContext` should reject;
or when it leaks key material or plaintext outside the documented key log.

The bundled ngtcp2, nghttp3 and AWS-LC have their own security policies;
report a flaw that lies entirely in one of them upstream, and here when it
affects how ngquic uses it. Callers own sockets, timeouts, connection and
request limits per peer, certificate storage and application policy.

## Reporting a Vulnerability

Report suspected vulnerabilities through
[GitHub private vulnerability reporting](https://github.com/cnzakii/ngquic/security/advisories/new).

Do not open a public issue or pull request for a suspected vulnerability.
Include the affected version, a minimal reproducer, and the potential impact.
Please allow reasonable time for investigation and a fix before public
disclosure.
