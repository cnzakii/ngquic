---
title: Overview
description: Public Python API of ngquic, organised by task.
---

# API reference

The QUIC API lives in the `ngquic` package; HTTP/3 in `ngquic.h3`, which builds
on it; batched UDP system calls in `ngquic.udp`, which is optional. Every method
works on state in memory: you pass in datagrams and the current time, and send
the datagrams that come back.

| If you need to… | Start with |
| --- | --- |
| listen for or start connections | [`Endpoint`](connections.md#ngquic.Endpoint), [`Endpoint.connect()`](connections.md#ngquic.Endpoint.connect) |
| decide whether to accept a client | [`Incoming`](connections.md#ngquic.Incoming): `accept()`, `retry()`, `refuse()`, `ignore()` |
| feed received datagrams | [`Endpoint.receive_datagram()`](connections.md#ngquic.Endpoint.receive_datagram) |
| collect datagrams to send | [`BaseConnection.datagrams_to_send()`](connections.md#ngquic.BaseConnection.datagrams_to_send), [`Endpoint.datagrams_to_send()`](connections.md#ngquic.Endpoint.datagrams_to_send) |
| drive timers | [`get_timer()`](connections.md#ngquic.BaseConnection.get_timer), [`handle_timer()`](connections.md#ngquic.BaseConnection.handle_timer) |
| react to the peer | [`events()`](connections.md#ngquic.BaseConnection.events) and the [event classes](events.md) |
| use streams and DATAGRAMs | [`Connection`](connections.md#ngquic.Connection) |
| speak HTTP/3 | [`H3Connection`](h3.md#ngquic.h3.H3Connection) |
| configure TLS | [`TLSContext`](tls.md#ngquic.TLSContext) |
| tune transport limits | [`TransportConfig`](config.md#ngquic.TransportConfig), [`EndpointConfig`](config.md#ngquic.EndpointConfig) |
| handle failures | [Exceptions](errors.md) and [`ConnectionTerminated`](events.md#ngquic.ConnectionTerminated) |
| send with GSO or read with GRO | [`ngquic.udp`](udp.md) |
