"""The echo exchange over localhost with ngquic.udp batched I/O (Linux, macOS)."""

import selectors
import socket
import sys
import time

from localhost_certs import CA_PEM, cert_chain_files

import ngquic

# --8<-- [start:imports]
if sys.platform == "win32":
    sys.exit("ngquic.udp is built on Linux and macOS only")

from ngquic.udp import UDPSocket

# --8<-- [end:imports]

server_tls = ngquic.TLSContext(ngquic.Role.SERVER)
with cert_chain_files() as (certfile, keyfile):
    server_tls.load_cert_chain(certfile, keyfile)
server_tls.set_alpn_protocols(["echo"])
client_tls = ngquic.TLSContext(ngquic.Role.CLIENT)
client_tls.load_verify_locations(cadata=CA_PEM)
client_tls.set_alpn_protocols(["echo"])

# --8<-- [start:sockets]
server_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
server_sock.bind(("127.0.0.1", 0))
client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
client_sock.bind(("127.0.0.1", 0))
server_udp = UDPSocket(server_sock)
client_udp = UDPSocket(client_sock)

endpoints = {
    server_udp: ngquic.Endpoint(server_sock.getsockname()),
    client_udp: ngquic.Endpoint(client_sock.getsockname()),
}
selector = selectors.DefaultSelector()
for udp in endpoints:
    selector.register(udp, selectors.EVENT_READ, data=udp)

client = endpoints[client_udp].connect(
    server_sock.getsockname(),
    time.monotonic(),
    tls=client_tls,
    server_name="localhost",
)
connections: list[tuple[UDPSocket, ngquic.Connection]] = [(client_udp, client)]
# --8<-- [end:sockets]


# --8<-- [start:send]
def send_all() -> None:
    """Send what every endpoint and connection has queued."""
    for udp, endpoint in endpoints.items():
        for transmit in endpoint.datagrams_to_send():
            udp.send(transmit)
    now = time.monotonic()
    for udp, connection in connections:
        for transmit in connection.datagrams_to_send(now, gso=udp.gso):
            udp.send(transmit)


# --8<-- [end:send]


# --8<-- [start:receive]
def receive(udp: UDPSocket) -> None:
    """Pass every datagram waiting on ``udp`` to its endpoint."""
    for result in udp.receive_into(endpoints[udp], time.monotonic()):
        if isinstance(result, ngquic.Incoming):
            server = result.accept(tls=server_tls)
            if server is not None:
                connections.append((udp, server))


# --8<-- [end:receive]

# --8<-- [start:loop]
replied = False
while not replied:
    send_all()

    deadlines = [
        (timer, connection)
        for _, connection in connections
        if (timer := connection.get_timer()) is not None
    ]
    earliest = min((timer for timer, _ in deadlines), default=None)
    timeout = None if earliest is None else max(earliest - time.monotonic(), 0)
    ready = selector.select(timeout)
    for key, _ in ready:
        receive(key.data)

    now = time.monotonic()
    if not ready and earliest is not None:
        # The wait may end a little early; run the timer it was armed for.
        now = max(now, earliest)
    for timer, connection in deadlines:
        if timer <= now:
            connection.handle_timer(now)

    for _, connection in connections:
        for event in connection.events():
            match event:
                case ngquic.HandshakeCompleted() if connection is client:
                    print(event)
                    stream_id = client.open_stream()
                    client.send_stream_data(stream_id, b"hello", end_stream=True)
                case ngquic.StreamDataReceived() if connection is not client:
                    print(f"server received {event.data!r} on stream {event.stream_id}")
                    connection.send_stream_data(
                        event.stream_id, event.data.upper(), end_stream=True
                    )
                case ngquic.StreamDataReceived(end_stream=True):
                    print(event)
                    replied = True
# --8<-- [end:loop]

# --8<-- [start:close]
client.close()
send_all()
selector.close()
server_sock.close()
client_sock.close()
# --8<-- [end:close]
