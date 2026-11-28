---
title: Run over UDP
description: Run the echo exchange over real UDP sockets on localhost, then switch to ngquic.udp batched I/O on Linux and macOS.
---

# Run over UDP

By the end of this tutorial you will have the echo exchange of the first
tutorial running over two UDP sockets on `127.0.0.1`, driven by a `selectors`
loop that waits for a datagram or the next timer on the real monotonic clock.
You will then make a copy that uses `ngquic.udp`, which batches the socket
calls on Linux and macOS.

## Before you start

- Complete [Your first handshake](first-handshake.md) and
  [Understand the sans-I/O model](protocol-model.md). This tutorial works in
  the same `quic-tour` directory and imports its `localhost_certs.py`, from
  [Get a test certificate](first-handshake.md#get-a-test-certificate).
- The last section needs Linux or macOS. The rest runs on any platform.

## Run the exchange over sockets

Save this program as `udp_echo.py` in `quic-tour`, next to
`localhost_certs.py`:

```python title="udp_echo.py"
--8<-- "examples/udp_echo.py"
```

Run it:

```console
python udp_echo.py
```

It prints the same three lines as the in-memory version:

```text
HandshakeCompleted(alpn_protocol='echo', session_resumed=False, early_data_accepted=False)
server received b'hello' on stream 0
StreamDataReceived(stream_id=0, data=b'HELLO', end_stream=True, early=False)
```

The TLS setup is the one from the first tutorial. The next five sections
explain the rest in parts, with code copied from `udp_echo.py`, so there is
nothing more to type until [the last section](#batch-system-calls-with-ngquicudp).

## Give each socket an endpoint

```python
--8<-- "examples/udp_echo.py:sockets"
```

Each socket binds to port 0, so the system picks a free port, and each
`Endpoint` takes the bound address from `getsockname()`. The endpoint must know
its real address: it is part of every path ngtcp2 tracks. The sockets are
non-blocking and registered with a selector, so one thread can wait on both.

The program keeps each connection next to the socket it sends from: the
client's own, and for the server, the socket its `Incoming` arrived on.

## Send after every input

```python
--8<-- "examples/udp_echo.py:send"
```

`send_all()` sends the endpoints' stateless replies and then every
connection's `Transmit` objects with `sendto()`. Each `Transmit` is one UDP
payload unless you ask for segments, as
[the last section](#batch-system-calls-with-ngquicudp) does.

## Read everything that is waiting

```python
--8<-- "examples/udp_echo.py:receive"
```

`receive()` reads until the socket would block, passing each payload to
`Endpoint.receive_datagram()` with the sender's address and the current time.
Read 65,535 bytes at a time so a datagram is never truncated.

## Wait for a datagram or a timer

```python
--8<-- "examples/udp_echo.py:loop"
```

Before it waits, the loop asks every connection for `get_timer()` and turns the
earliest deadline into the selector's timeout. After the wait, a connection
whose deadline has passed gets `handle_timer()`.

Pass `handle_timer()` the deadline it was armed for when the wait ended by
timeout: a selector or event loop may wake up slightly early, and a `now`
before the deadline does nothing. Do not ask `get_timer()` again at that
point, because input since the wait began can move the deadline later.

The event handling is the same as in the first tutorial.

## Close and release the sockets

```python
--8<-- "examples/udp_echo.py:close"
```

`close()` queues CONNECTION_CLOSE, and one more `send_all()` puts it on the
wire. The program then exits without running the closing period. A long-lived
program keeps driving the connection's timer until it reaches
`ConnectionState.CLOSED`, as [the previous tutorial](protocol-model.md)
showed.

!!! warning
    QUIC forbids IP fragmentation
    ([RFC 9000 §14](https://www.rfc-editor.org/rfc/rfc9000#section-14)).
    A plain socket keeps the system's setting, which differs between
    platforms. `ngquic.udp.UDPSocket` turns fragmentation off for you.

## Batch system calls with ngquic.udp

`ngquic.udp` makes the batched UDP system calls an event loop's datagram
transport does not, on a socket you create, bind, wait on and close. It is
built on Linux and macOS only; on Windows, importing it fails, so keep the
plain socket loop above there.

| Platform | What `UDPSocket` adds |
| --- | --- |
| Linux | segmented sends (GSO), batched receives with `recvmmsg` and coalesced ones (GRO), ECN, destination addresses |
| macOS | reads in a loop in C without returning to Python, ECN, destination addresses; no GSO or GRO |
| Windows | not available |

Copy `udp_echo.py` to `udp_batched.py` in `quic-tour` and make four changes;
the highlighted lines are the ones that differ.
First, add `import sys` to the imports at the top, then import `UDPSocket`
after the platform check, below `import ngquic`:

```python hl_lines="1 2 4"
--8<-- "examples/udp_batched.py:imports"
```

Second, wrap each socket in a `UDPSocket` and key the endpoints by it. This
replaces the code shown in
[Give each socket an endpoint](#give-each-socket-an-endpoint):

```python hl_lines="5 6 9 10 13 14 16"
--8<-- "examples/udp_batched.py:sockets"
```

Wrapping makes the socket non-blocking and sets its options for QUIC, so the
`setblocking()` call goes away; leave the socket's options to the wrapper from
then on. A `UDPSocket` has `fileno()`, so the selector waits on it directly.

Third, send and receive through the wrapper. These replace `send_all()` and
`receive()`:

```python hl_lines="3 5 7 8 9"
--8<-- "examples/udp_batched.py:send"
```

```python hl_lines="1 2 3 7"
--8<-- "examples/udp_batched.py:receive"
```

`UDPSocket.send()` takes a `Transmit` as it is. `datagrams_to_send(gso=...)`
lets one `Transmit` carry several payloads of `segment_size` bytes, and
`UDPSocket.gso` says whether the kernel splits them; it is `False` on macOS.

`UDPSocket.receive_into(endpoint, now)` reads what is waiting and feeds it to
the endpoint without a Python object per datagram. It returns each connection
that took datagrams and each `Incoming` attempt, once, in arrival order. When
you need the datagrams themselves, `receive()` returns `ReceivedDatagram`
objects whose fields are the arguments of `receive_datagram()`.

Fourth, close the sockets themselves at the end. The endpoints are now keyed
by `UDPSocket`, which has no `close()`: the socket stays yours to close.

```python hl_lines="4 5"
--8<-- "examples/udp_batched.py:close"
```

The loop between `receive()` and the close stays as it is. Run the copy:

```console
python udp_batched.py
```

It prints the same three lines as `udp_echo.py`.

!!! note
    `UDPSocket.send()` raises `BlockingIOError` when the socket buffer is full
    and sends nothing. A program that sends more than this example waits for
    the socket to become writable and sends that `Transmit` again.

## Next steps

- [Make an HTTP/3 request](http3.md) sends a request and a response over the
  same kind of connection.
- The [batched UDP reference](../reference/udp.md) for `UDPSocket`, and the
  [API reference](../reference/connections.md) for `get_timer()` and
  `handle_timer()`.
