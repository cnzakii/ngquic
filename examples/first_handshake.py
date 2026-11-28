"""A QUIC client and server complete a handshake and echo one stream in memory."""

import time

from localhost_certs import CA_PEM, cert_chain_files

import ngquic

# --8<-- [start:tls]
server_tls = ngquic.TLSContext(ngquic.Role.SERVER)
with cert_chain_files() as (certfile, keyfile):
    server_tls.load_cert_chain(certfile, keyfile)
server_tls.set_alpn_protocols(["echo"])

client_tls = ngquic.TLSContext(ngquic.Role.CLIENT)
client_tls.load_verify_locations(cadata=CA_PEM)
client_tls.set_alpn_protocols(["echo"])
# --8<-- [end:tls]

# --8<-- [start:connect]
server_endpoint = ngquic.Endpoint(("127.0.0.1", 4433))
client_endpoint = ngquic.Endpoint(("127.0.0.1", 50000))
client = client_endpoint.connect(
    server_endpoint.local_addr,
    time.monotonic(),
    tls=client_tls,
    server_name="localhost",
)
server = None
# --8<-- [end:connect]

# --8<-- [start:loop]
replied = False
while not replied:
    now = time.monotonic()
    for transmit in client.datagrams_to_send(now):
        incoming = server_endpoint.receive_datagram(
            transmit.data, client_endpoint.local_addr, now
        )
        if isinstance(incoming, ngquic.Incoming):
            server = incoming.accept(tls=server_tls)
    assert server is not None, "the server endpoint saw no connection attempt"
    for transmit in server.datagrams_to_send(now):
        client_endpoint.receive_datagram(transmit.data, server_endpoint.local_addr, now)

    for event in server.events():
        if isinstance(event, ngquic.StreamDataReceived):
            print(f"server received {event.data!r} on stream {event.stream_id}")
            server.send_stream_data(
                event.stream_id, event.data.upper(), end_stream=True
            )
    for event in client.events():
        match event:
            case ngquic.HandshakeCompleted():
                print(event)
                stream_id = client.open_stream()
                client.send_stream_data(stream_id, b"hello", end_stream=True)
            case ngquic.StreamDataReceived(end_stream=True):
                print(event)
                replied = True
# --8<-- [end:loop]
