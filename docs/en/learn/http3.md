---
title: Your first HTTP/3 request
description: Send a first HTTP/3 request and response with ngquic.h3, in memory.
---

# Make an HTTP/3 request

By the end of this tutorial you will have a script in which an HTTP/3 client
sends `GET /hello`, a server answers `200` with a short body, and the client
closes the connection. It runs in memory like the first tutorial: HTTP/3 uses
the same endpoints, datagrams, events and timers, and only the stream methods
change.

## Before you start

- Complete [Your first handshake](first-handshake.md). This tutorial works in
  the same `quic-tour` directory and imports its `localhost_certs.py`, from
  [Get a test certificate](first-handshake.md#get-a-test-certificate).
- The HTTP/3 module, `ngquic.h3`, comes with the same install; nothing more
  to add.

## Run the exchange

Save this program as `http3_request.py` in `quic-tour`, next to
`localhost_certs.py`:

```python title="http3_request.py"
--8<-- "examples/http3_request.py"
```

Run it:

```console
python http3_request.py
```

It prints:

```text
server received GET /hello
client received 200
client received body b'Hello over HTTP/3\n'
server saw the client close: APPLICATION_ERROR 0x100
```

The next five sections explain the program in parts, with code copied from
`http3_request.py`, so there is nothing more to type.

## Select h3 in TLS

```python
--8<-- "examples/http3_request.py:tls"
```

The TLS setup is the one from the first tutorial with one change: both sides
offer the ALPN protocol `h3`, which identifies HTTP/3
([RFC 9114 §3.2](https://www.rfc-editor.org/rfc/rfc9114#section-3.2)).

## Ask for an H3Connection

```python
--8<-- "examples/http3_request.py:connect"
```

Passing `h3=H3Config()` to `Endpoint.connect()` returns an `H3Connection`
instead of a `Connection`, and the server passes the same argument to
`Incoming.accept()`. The defaults of `H3Config` suit most programs; its fields
set the QPACK dynamic table, the largest header section accepted, extended
CONNECT and HTTP datagrams.

An `H3Connection` is driven exactly like a `Connection`:
`receive_datagram()` on the endpoint, then `events()`, `datagrams_to_send()`,
`get_timer()` and `handle_timer()` on the connection. `exchange()` is the
datagram loop from the first tutorial. Only the methods for streams change:
you send requests and responses, and ngquic manages the HTTP/3 control and
QPACK streams.

## Answer requests on the server

```python
--8<-- "examples/http3_request.py:server"
```

`RequestReceived` carries the request's `stream_id` and its `headers` as
`(name, value)` byte pairs, pseudo-header fields such as `:method` and `:path`
first. `end_stream=True` means the request has no body; a request with a body
arrives as `RequestReceived` followed by `DataReceived` events.

The server answers on the request's stream: `send_response()` sends the header
section, starting with `:status`, and `send_data()` sends the body.
`end_stream=True` on the last call ends the response. A response that ends
with trailers uses `send_trailers()` instead; one that ends after earlier
body chunks uses `end_stream()`.

## Send the request and read the response

```python
--8<-- "examples/http3_request.py:client"
```

The client sends its request once `HandshakeCompleted` arrives.
`send_request()` takes the four pseudo-header fields a request needs
([RFC 9114 §4.3.1](https://www.rfc-editor.org/rfc/rfc9114#section-4.3.1)),
opens a new request stream and returns its ID. `end_stream=True` says no body
follows.

The response arrives as `ResponseReceived` with the header section, then one
`DataReceived` per chunk of body. A body can arrive in any number of chunks,
so the client appends `event.data` until a chunk has `end_stream=True`. An
informational `1xx` response would arrive first as
`InformationalResponseReceived`, and trailers as `TrailersReceived`.

## Close the connection

```python
--8<-- "examples/http3_request.py:close"
```

An HTTP/3 connection closes with an HTTP/3 error code. `H3ErrorCode.H3_NO_ERROR`
(`0x100`) says nothing went wrong
([RFC 9114 §8.1](https://www.rfc-editor.org/rfc/rfc9114#section-8.1)). The
server's `ConnectionTerminated` reports it with `reason`
`CloseReason.APPLICATION_ERROR`, because the code belongs to the application
protocol rather than to QUIC.

!!! warning
    A peer may close or reset with a code that is not in `H3ErrorCode`:
    unknown codes mean `H3_NO_ERROR`
    ([RFC 9114 §9](https://www.rfc-editor.org/rfc/rfc9114#section-9)).
    Compare `error_code` with the enum rather than converting every value
    with `H3ErrorCode(...)`.

A client that is done closes as this one does. A server that wants to stop
taking requests without cutting off the ones in flight calls
`send_shutdown_notice()`, then `send_goaway()` a round trip or two later,
and closes once `is_drained` is true ([RFC 9114 §5.2](https://www.rfc-editor.org/rfc/rfc9114#section-5.2)).

## Next steps

- To run this over UDP, take `udp_echo.py` from [Run over UDP](udp.md), pass
  `h3=H3Config()` to `connect()` and `accept()`, and replace its event
  handling with the HTTP/3 handling above.
- The [HTTP/3 reference](../reference/h3.md) for `H3Connection`, `H3Config`,
  the HTTP/3 events and `H3ErrorCode`.
