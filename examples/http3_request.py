"""An HTTP/3 client sends one GET and a server answers it, in memory."""

import time

from localhost_certs import CA_PEM, cert_chain_files

import ngquic
from ngquic.h3 import (
    ConnectionTerminated,
    DataReceived,
    H3Config,
    H3Connection,
    H3ErrorCode,
    HandshakeCompleted,
    RequestReceived,
    ResponseReceived,
)

# --8<-- [start:tls]
server_tls = ngquic.TLSContext(ngquic.Role.SERVER)
with cert_chain_files() as (certfile, keyfile):
    server_tls.load_cert_chain(certfile, keyfile)
server_tls.set_alpn_protocols(["h3"])

client_tls = ngquic.TLSContext(ngquic.Role.CLIENT)
client_tls.load_verify_locations(cadata=CA_PEM)
client_tls.set_alpn_protocols(["h3"])
# --8<-- [end:tls]

# --8<-- [start:connect]
server_endpoint = ngquic.Endpoint(("127.0.0.1", 4433))
client_endpoint = ngquic.Endpoint(("127.0.0.1", 50000))
client = client_endpoint.connect(
    server_endpoint.local_addr,
    time.monotonic(),
    tls=client_tls,
    server_name="localhost",
    h3=H3Config(),
)
server: H3Connection | None = None


def exchange() -> None:
    """Carry every queued datagram across, client first, then server."""
    global server
    now = time.monotonic()
    for transmit in client.datagrams_to_send(now):
        incoming = server_endpoint.receive_datagram(
            transmit.data, client_endpoint.local_addr, now
        )
        if isinstance(incoming, ngquic.Incoming):
            server = incoming.accept(tls=server_tls, h3=H3Config())
    assert server is not None, "the server endpoint saw no connection attempt"
    for transmit in server.datagrams_to_send(now):
        client_endpoint.receive_datagram(transmit.data, server_endpoint.local_addr, now)


# --8<-- [end:connect]


# --8<-- [start:server]
def serve(server: H3Connection) -> None:
    """Answer every complete request with a short text body."""
    for event in server.events():
        match event:
            case RequestReceived(stream_id, headers, end_stream=True):
                fields = dict(headers)
                method, path = fields[b":method"], fields[b":path"]
                print(f"server received {method.decode()} {path.decode()}")
                server.send_response(
                    stream_id,
                    [(b":status", b"200"), (b"content-type", b"text/plain")],
                )
                server.send_data(stream_id, b"Hello over HTTP/3\n", end_stream=True)
            case ConnectionTerminated(reason, error_code, by_peer=True):
                print(f"server saw the client close: {reason.name} {error_code:#x}")


# --8<-- [end:server]

# --8<-- [start:client]
done = False
body = b""
while not done:
    exchange()
    serve(server)
    for event in client.events():
        match event:
            case HandshakeCompleted():
                client.send_request(
                    [
                        (b":method", b"GET"),
                        (b":scheme", b"https"),
                        (b":authority", b"localhost"),
                        (b":path", b"/hello"),
                    ],
                    end_stream=True,
                )
            case ResponseReceived(headers=headers):
                print(f"client received {dict(headers)[b':status'].decode()}")
            case DataReceived(data=data, end_stream=end_stream):
                body += data
                done = end_stream
print(f"client received body {body!r}")
# --8<-- [end:client]

# --8<-- [start:close]
client.close(H3ErrorCode.H3_NO_ERROR)
exchange()
serve(server)
# --8<-- [end:close]
