---
title: Batched UDP
description: Batched UDP system calls on a socket you own, for Linux and macOS.
---

# Batched UDP

`ngquic.udp` makes the system calls an event loop's datagram transport cannot:
segmented sends (GSO), coalesced and batched receives (GRO, `recvmmsg`), and
ECN and source-address control messages. The protocol core never depends on
it.

!!! note "Platforms"

    The module is built on Linux and macOS only. On Windows, `import ngquic.udp`
    raises `ImportError`; use your event loop's datagram transport instead.

::: ngquic.udp.UDPSocket

::: ngquic.udp.ReceivedDatagram
