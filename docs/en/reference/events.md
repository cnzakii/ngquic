---
title: Events
description: Events a QUIC connection reports, grouped by what they concern.
---

# Events

`BaseConnection.events()` returns the events that occurred since the last call.
Each event is an immutable object with a readable `repr()`, and every event
class supports `match` on its main fields:

```python
for event in connection.events():
    match event:
        case ngquic.StreamDataReceived(stream_id, data, end_stream):
            ...
        case ngquic.ConnectionTerminated():
            ...
```

An `H3Connection` reports the handshake, path, stream-state and termination
events below, which `ngquic.h3` re-exports, but delivers request data as
`ngquic.h3.DataReceived` and DATAGRAMs as `ngquic.h3.DatagramReceived`; see
[HTTP/3](h3.md#events).

::: ngquic.Event

## Handshake and TLS

::: ngquic.HandshakeCompleted
    options:
      members: false

::: ngquic.HandshakeConfirmed

::: ngquic.ClientHelloReceived
    options:
      members: false

::: ngquic.PeerCertificateReceived
    options:
      members: false

::: ngquic.SessionTicketReceived
    options:
      members: false

::: ngquic.NewTokenReceived
    options:
      members: false

::: ngquic.EarlyDataRejected

## Streams

::: ngquic.StreamDataReceived
    options:
      members: false

::: ngquic.StreamReset
    options:
      members: false

::: ngquic.StopSendingReceived
    options:
      members: false

::: ngquic.StreamClosed
    options:
      members: false

::: ngquic.StreamsAvailable
    options:
      members: false

::: ngquic.StreamWritable
    options:
      members: false

## DATAGRAMs

::: ngquic.DatagramReceived
    options:
      members: false

::: ngquic.DatagramAcknowledged
    options:
      members: false

::: ngquic.DatagramLost
    options:
      members: false

## Paths

::: ngquic.PathValidationStarted
    options:
      members: false

::: ngquic.PathValidated
    options:
      members: false

::: ngquic.PathDegrading

::: ngquic.PathRecovered

## Termination

::: ngquic.ConnectionTerminated
    options:
      members: false
