---
title: Your first handshake
description: Install ngquic, then run a QUIC client and server that complete a handshake and echo one stream in memory.
---

# Complete your first handshake

By the end of this tutorial you will have a Python script in which a QUIC
client and a QUIC server complete a TLS 1.3 handshake, and the server echoes
one stream back in upper case. No socket is opened: your code carries every
datagram from one side to the other, which is what ngquic expects a real
program to do too.

## Before you start

- CPython 3.10 or newer, and a terminal.

## Install ngquic

Create a directory for the tutorials and install ngquic there. Every script
on these pages goes in this directory.

=== "uv"

    ```console
    uv init --bare quic-tour
    cd quic-tour
    uv add ngquic
    ```

    The tutorials run scripts with `python`; in a uv project, type `uv run`
    in its place, as in `uv run first_handshake.py`.

=== "pip"

    ```console
    mkdir quic-tour
    cd quic-tour
    python -m venv .venv
    source .venv/bin/activate
    python -m pip install ngquic
    ```

    On Windows, activate the environment with `.venv\Scripts\activate`.

Wheels bundle ngtcp2, nghttp3 and AWS-LC for Linux, macOS and Windows, so no
system library is needed.

## Get a test certificate

QUIC always runs TLS 1.3 ([RFC 9001](https://www.rfc-editor.org/rfc/rfc9001)),
so even a local test needs a server certificate. Save the file below as
`localhost_certs.py` in `quic-tour`; every tutorial imports it. It holds a
certificate for `localhost` and `127.0.0.1`, the CA that signed it, and
`cert_chain_files()`, which writes the certificate and key to a temporary
directory.

```python title="localhost_certs.py"
--8<-- "examples/localhost_certs.py"
```

!!! warning
    The private key in this file is published. Use it for these examples
    only; a real server loads its own certificate and key.

## Run the exchange

Save this program as `first_handshake.py` in `quic-tour`, next to
`localhost_certs.py`:

```python title="first_handshake.py"
--8<-- "examples/first_handshake.py"
```

Run it:

```console
python first_handshake.py
```

It prints:

```text
HandshakeCompleted(alpn_protocol='echo', session_resumed=False, early_data_accepted=False)
server received b'hello' on stream 0
StreamDataReceived(stream_id=0, data=b'HELLO', end_stream=True, early=False)
```

The next three sections explain the program part by part. Their code is
copied from `first_handshake.py`, so there is nothing more to type.

## Configure TLS on both sides

```python
--8<-- "examples/first_handshake.py:tls"
```

A `TLSContext` is created for one `Role`. `load_cert_chain()` reads the
server's certificate and key from files, as `ssl.SSLContext` does; the
certificate files may be deleted once it returns. The client trusts the CA
that signed the certificate, passed as a string with
`load_verify_locations(cadata=...)`.

Both contexts call `set_alpn_protocols()`. QUIC requires the two sides to agree
on an application protocol during the handshake
([RFC 9001 §8.1](https://www.rfc-editor.org/rfc/rfc9001#section-8.1)), and the
handshake fails without one. `echo` is a name this example made up; HTTP/3
uses `h3`.

## Create endpoints and start the client

```python
--8<-- "examples/first_handshake.py:connect"
```

An `Endpoint` stands for one local UDP address. It routes each received
datagram to its connection by connection ID, and on a server it reports new
connection attempts. Here the addresses are only labels: nothing is bound.

`Endpoint.connect()` creates the client `Connection` and queues its first
flight. It takes the current time as `now`; every ngquic call that can start
or run a timer does. `server_name` is sent in the TLS handshake and matched
against the server certificate.

## Carry datagrams and handle events

```python
--8<-- "examples/first_handshake.py:loop"
```

Each pass of the loop does the same three things:

1. `datagrams_to_send(now)` returns the `Transmit` objects a connection wants
   sent now. Each holds one UDP payload in `data` and its destination in
   `remote_addr`.
2. The other side's `Endpoint.receive_datagram()` takes the payload, the
   address it came from and `now`. For the first datagram of a new connection
   it returns an `Incoming`, and the server calls `accept()` with its TLS
   context to get its own `Connection`.
3. `events()` returns what happened since the last call, in protocol order.

The client gets `HandshakeCompleted` when its side of the handshake is done,
with the agreed ALPN protocol. It then opens a stream with `open_stream()` and
sends `b"hello"` with `end_stream=True`, which also ends its sending
direction. Stream 0 is the first bidirectional stream a client opens
([RFC 9000 §2.1](https://www.rfc-editor.org/rfc/rfc9000#section-2.1)).

The server gets `StreamDataReceived` and answers on the same stream ID. When
the client sees `StreamDataReceived` with `end_stream=True`, the reply is
complete.

!!! note
    This loop never waits, so it ignores timers. Without loss, no
    retransmission is needed. The next tutorial adds the timer that a real
    program must run.

## Recap

- A `TLSContext` per side, both offering the same ALPN protocol.
- An `Endpoint` per local address; `connect()` starts a client connection and
  `Incoming.accept()` a server one.
- Your code moves each `Transmit` from `datagrams_to_send()` to the other
  side's `receive_datagram()`, then reads `events()`.

## Next steps

- [Understand the sans-I/O model](protocol-model.md) adds timers, closes the
  connection, and shows what your program owns.
- The [API reference](../reference/connections.md) for `Endpoint`,
  `Connection` and `Incoming`, and the [TLS reference](../reference/tls.md)
  for `TLSContext`.
