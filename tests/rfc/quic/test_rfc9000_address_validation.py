"""RFC 9000 section 8: address validation and its wire behavior."""

from pathlib import Path

import pytest

# Optional: aioquic needs pylsqpack, which has no free-threaded build yet.
pytest.importorskip("aioquic")

from aioquic.buffer import Buffer
from aioquic.quic.packet import QuicPacketType, pull_quic_header
from support.network import CLIENT_ADDR, SERVER_ADDR

from ngquic import Incoming, NewTokenReceived


def test_client_sends_a_full_sized_initial_at_its_first_probe_timeout(network):
    network.gso = False
    network.client_tls.set_groups(["X25519"])
    network.connect()
    network.drop = lambda data, destination: destination == SERVER_ADDR
    network.run(lambda: network.sent)
    [_first_flight] = network.sent
    flight_end = len(network.sent)

    network.run(lambda: len(network.sent) > flight_end)
    [probe, *_] = network.sent[flight_end:]
    header = pull_quic_header(Buffer(data=probe))

    assert (header.packet_type, min(map(len, network.sent)) >= 1200) == (
        QuicPacketType.INITIAL,
        True,
    )


def test_retry_token_is_retained_on_initial_retransmission(network):
    network.gso = False
    network.client_tls.set_groups(["X25519"])
    client = network.connect()
    [initial] = client.datagrams_to_send(network.now, max_datagrams=1)
    attempt = network.server_endpoint.receive_datagram(
        initial.data, CLIENT_ADDR, network.now
    )
    assert isinstance(attempt, Incoming)
    attempt.retry()
    [retry] = network.server_endpoint.datagrams_to_send()
    token = pull_quic_header(Buffer(data=retry.data)).token
    assert token != b""
    network.client_endpoint.receive_datagram(retry.data, SERVER_ADDR, network.now)
    network.drop = lambda data, destination: destination == SERVER_ADDR
    network.run(lambda: network.sent)
    [_first_flight] = network.sent
    flight_end = len(network.sent)

    network.run(lambda: len(network.sent) > flight_end)
    [probe, *_] = network.sent[flight_end:]
    header = pull_quic_header(Buffer(data=probe))

    assert header.token == token


def test_new_token_validates_the_same_client_ip_after_a_port_change(network):
    first = network.connect()
    network.run(lambda: network.events_of(first, NewTokenReceived))
    [issued] = network.events_of(first, NewTokenReceived)
    other_port = (CLIENT_ADDR[0], CLIENT_ADDR[1] + 1)
    second = network.connect(token=issued.token, local_addr=other_port)
    [initial] = second.datagrams_to_send(network.now, max_datagrams=1)

    attempt = network.server_endpoint.receive_datagram(
        initial.data, other_port, network.now
    )

    assert isinstance(attempt, Incoming)
    assert (attempt.remote_addr, attempt.remote_address_validated) == (other_port, True)


def test_server_handshake_respects_the_unvalidated_address_budget(
    network, certificates, tmp_path
):
    network.client_tls.set_groups(["X25519"])
    chain = tmp_path / "long-chain.pem"
    chain.write_bytes(Path(certificates.cert).read_bytes() * 16)
    first = network.connect()
    network.run(lambda: network.events_of(first, NewTokenReceived))
    [issued] = network.events_of(first, NewTokenReceived)
    network.server_tls.load_cert_chain(chain, certificates.key)
    client = network.connect()
    [initial] = client.datagrams_to_send(network.now, max_datagrams=1)
    validated_client = network.connect(token=issued.token)
    [with_token] = validated_client.datagrams_to_send(network.now, max_datagrams=1)

    def first_flight_size(transmit):
        attempt = network.server_endpoint.receive_datagram(
            transmit.data, CLIENT_ADDR, network.now
        )
        assert isinstance(attempt, Incoming)
        server = attempt.accept(tls=network.server_tls)
        assert server is not None
        return sum(len(d.data) for d in server.datagrams_to_send(network.now))

    unvalidated = first_flight_size(initial)
    validated = first_flight_size(with_token)

    budget = 3 * len(initial.data)
    assert (0 < unvalidated <= budget, validated > budget) == (True, True), (
        unvalidated,
        validated,
        budget,
    )


def test_simultaneous_connections_receive_distinct_new_tokens(network):
    first = network.connect()
    second = network.connect(local_addr=(CLIENT_ADDR[0], CLIENT_ADDR[1] + 1))

    network.run(
        lambda: (
            network.events_of(first, NewTokenReceived)
            and network.events_of(second, NewTokenReceived)
        )
    )
    tokens = {
        event.token
        for connection in (first, second)
        for event in network.events_of(connection, NewTokenReceived)
    }

    assert len(tokens) == 2
