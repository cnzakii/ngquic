"""Drive two endpoints by hand: datagrams, events and timers on a virtual clock."""

from localhost_certs import CA_PEM, cert_chain_files

import ngquic

server_tls = ngquic.TLSContext(ngquic.Role.SERVER)
with cert_chain_files() as (certfile, keyfile):
    server_tls.load_cert_chain(certfile, keyfile)
server_tls.set_alpn_protocols(["echo"])
client_tls = ngquic.TLSContext(ngquic.Role.CLIENT)
client_tls.load_verify_locations(cadata=CA_PEM)
client_tls.set_alpn_protocols(["echo"])


# --8<-- [start:network]
class Network:
    """Endpoints joined by a lossless link, on a clock that jumps to timers."""

    def __init__(self, *endpoints: ngquic.Endpoint) -> None:
        self.now = 0.0
        self.endpoints = {endpoint.local_addr: endpoint for endpoint in endpoints}
        self.connections: list[ngquic.Connection] = []

    def flush(self) -> bool:
        """Deliver every datagram due now; return whether any moved."""
        transmits: list[ngquic.Transmit] = []
        for endpoint in self.endpoints.values():
            transmits += endpoint.datagrams_to_send()
        for connection in self.connections:
            transmits += connection.datagrams_to_send(self.now)
        for transmit in transmits:
            destination = self.endpoints[transmit.remote_addr]
            result = destination.receive_datagram(
                transmit.data, transmit.local_addr, self.now
            )
            if isinstance(result, ngquic.Incoming):
                server = result.accept(tls=server_tls)
                if server is not None:
                    self.connections.append(server)
        return bool(transmits)

    def wait(self) -> bool:
        """Move the clock to the earliest timer and run it; False if none."""
        timers = [
            (timer, connection)
            for connection in self.connections
            if (timer := connection.get_timer()) is not None
        ]
        if not timers:
            return False
        self.now = max(self.now, min(timer for timer, _ in timers))
        for timer, connection in timers:
            if timer <= self.now:
                connection.handle_timer(self.now)
        return True


# --8<-- [end:network]

# --8<-- [start:run]
server_endpoint = ngquic.Endpoint(("127.0.0.1", 4433))
client_endpoint = ngquic.Endpoint(("127.0.0.1", 50000))
network = Network(server_endpoint, client_endpoint)
client = client_endpoint.connect(
    server_endpoint.local_addr, network.now, tls=client_tls, server_name="localhost"
)
network.connections.append(client)
closed_at = pto = 0.0

while True:
    moved = network.flush()
    for connection in network.connections:
        side = "client" if connection is client else "server"
        for event in connection.events():
            print(side, type(event).__name__)
            match event:
                case ngquic.HandshakeCompleted() if connection is client:
                    stream_id = client.open_stream()
                    client.send_stream_data(stream_id, b"ping", end_stream=True)
                case ngquic.StreamDataReceived() if connection is not client:
                    connection.send_stream_data(
                        event.stream_id, event.data, end_stream=event.end_stream
                    )
                case ngquic.StreamDataReceived(end_stream=True):
                    client.close()
                    closed_at, pto = network.now, client.pto
    if not moved and not network.wait():
        break
# --8<-- [end:run]

# --8<-- [start:after]
server = network.connections[1]
states = f"client {client.state.name}, server {server.state.name}"
print(f"{states} {(network.now - closed_at) / pto:.0f} PTOs after close()")
print(f"endpoints hold {server_endpoint.connections + client_endpoint.connections}")
# --8<-- [end:after]
