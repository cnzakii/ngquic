"""RFC 9000 sections 8.2 and 9: path validation and migration."""

import pytest

# Optional: aioquic needs pylsqpack, which has no free-threaded build yet.
pytest.importorskip("aioquic")

from aioquic.buffer import Buffer
from aioquic.quic.packet import pull_quic_header
from support.network import CLIENT_ADDR, SERVER_ADDR

from ngquic import (
    Endpoint,
    EndpointConfig,
    HandshakeConfirmed,
    NewTokenReceived,
    PathValidated,
    PreferredAddress,
    StreamDataReceived,
    TransportConfig,
)


def test_path_validation_probes_use_a_fresh_destination_connection_id(network):
    network.client_transport = TransportConfig(pmtud=False, grease_quic_bit=False)
    network.server_transport = TransportConfig(pmtud=False, grease_quic_bit=False)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.advance(0.5)
    client.send_stream_data(client.open_stream(), b"before migrating")
    [old] = client.datagrams_to_send(network.now, max_datagrams=1)
    cid_length = network.server_endpoint.config.connection_id_length
    old_cid = pull_quic_header(
        Buffer(data=old.data), host_cid_length=cid_length
    ).destination_cid
    network.server_endpoint.receive_datagram(old.data, CLIENT_ADDR, network.now)
    network.advance(0.5)
    new_addr = ("127.0.0.1", 50001)

    client.migrate(new_addr, network.now)
    [probe] = client.datagrams_to_send(network.now, max_datagrams=1)
    new_cid = pull_quic_header(
        Buffer(data=probe.data), host_cid_length=cid_length
    ).destination_cid

    assert (probe.local_addr, new_cid == old_cid) == (new_addr, False)


def test_client_path_validation_starts_with_a_1200_byte_datagram(network):
    network.client_transport = TransportConfig(pmtud=False, grease_quic_bit=False)
    network.server_transport = TransportConfig(pmtud=False, grease_quic_bit=False)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.advance(0.5)
    new_addr = ("127.0.0.1", 50001)

    client.migrate(new_addr, network.now)
    [probe] = client.datagrams_to_send(network.now, max_datagrams=1)

    assert (probe.local_addr, len(probe.data) >= 1200) == (new_addr, True)


def test_failed_preferred_address_validation_keeps_the_original_server_path(network):
    preferred = ("127.0.0.2", 4434)
    network.server_endpoint = Endpoint(
        SERVER_ADDR, EndpointConfig(preferred_address=PreferredAddress(ipv4=preferred))
    )
    network.drop = lambda data, destination: destination == preferred
    client = network.connect()
    network.run(lambda: network.events_of(client, PathValidated))
    assert network.events_of(client, PathValidated) == [
        PathValidated(CLIENT_ADDR, preferred, True, False)
    ]
    stream_id = client.open_stream()
    destinations = []

    def record_destination(data, destination):
        destinations.append(destination)
        return destination == preferred

    network.drop = record_destination

    client.send_stream_data(stream_id, b"original path", end_stream=True)
    network.run(lambda: network.events_of(network.server, StreamDataReceived))

    assert set(destinations) - {CLIENT_ADDR} == {SERVER_ADDR}


def test_server_sends_a_new_address_token_after_validating_migration(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, NewTokenReceived))
    new_addr = ("127.0.0.2", 50001)

    client.migrate(new_addr, network.now)
    network.run(lambda: network.events_of(network.server, PathValidated))
    [validation] = network.events_of(network.server, PathValidated)
    if validation != PathValidated(SERVER_ADDR, new_addr, False, True):
        pytest.fail(f"migration did not validate: {validation!r}")
    network.advance(0.5)

    assert len(network.events_of(client, NewTokenReceived)) == 2
