---
title: Endpoints and connections
description: Endpoints, incoming connection attempts and QUIC connections in ngquic.
---

# Endpoints and connections

An `Endpoint` owns one local address and routes datagrams to its connections. Clients get a connection from `Endpoint.connect()`; servers get an `Incoming` for each new client and decide what to do with it. See [the protocol model](../learn/protocol-model.md) for how the pieces fit.

## Endpoint

::: ngquic.Endpoint

::: ngquic.Incoming

::: ngquic.Transmit

## Connections

`Connection` and [`H3Connection`](h3.md#ngquic.h3.H3Connection) share everything in `BaseConnection`. `Connection` adds streams and DATAGRAMs for applications that use QUIC directly.

::: ngquic.BaseConnection

::: ngquic.Connection

::: ngquic.ConnectionState
    options:
      members: false

## Addresses and statistics

::: ngquic.Address

::: ngquic.ConnectionStats
    options:
      members: false

::: ngquic.TransportParameters
    options:
      members: false

::: ngquic.PreferredAddress
    options:
      members: false
