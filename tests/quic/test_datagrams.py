import pytest
from support.network import SERVER_ADDR

from ngquic import (
    DatagramAcknowledged,
    DatagramError,
    DatagramLost,
    DatagramReceived,
    HandshakeConfirmed,
    TransportConfig,
)


def test_a_sender_can_use_datagrams_when_only_its_peer_advertises_support(network):
    network.server_transport = TransportConfig(max_datagram_frame_size=256)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))

    client.send_datagram(b"one-way")
    network.run(lambda: network.events_of(network.server, DatagramReceived))

    assert network.events_of(network.server, DatagramReceived) == [
        DatagramReceived(b"one-way", False)
    ]


def test_an_empty_datagram_is_delivered_as_a_message(network):
    network.server_transport = TransportConfig(max_datagram_frame_size=256)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))

    client.send_datagram(b"")
    network.run(lambda: network.events_of(network.server, DatagramReceived))

    assert network.events_of(network.server, DatagramReceived) == [
        DatagramReceived(b"", False)
    ]


def test_dropped_datagram_is_reported_lost_without_being_retransmitted(network):
    network.client_transport = TransportConfig(pmtud=False)
    network.server_transport = TransportConfig(
        max_datagram_frame_size=256, ack_threshold=1, pmtud=False
    )
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    network.advance(0.5)
    dropped = []

    def drop_first(data, destination):
        if destination == SERVER_ADDR and not dropped:
            dropped.append(data)
            return True
        return False

    delivered_ids = [client.send_datagram(b"before")]
    network.run(lambda: network.events_of(client, DatagramAcknowledged))
    network.drop = drop_first
    lost_id = client.send_datagram(b"lost")
    network.run(lambda: dropped)

    for index in range(4):
        payload = bytes([index])
        delivered_ids.append(client.send_datagram(payload))
        network.run(
            lambda: (
                len(network.events_of(network.server, DatagramReceived))
                == len(delivered_ids)
            )
        )
    network.advance(0.5)

    assert network.events_of(client, DatagramLost) == [DatagramLost(lost_id, True)]
    assert network.events_of(client, DatagramAcknowledged) == [
        DatagramAcknowledged(datagram_id) for datagram_id in delivered_ids
    ]
    assert network.events_of(network.server, DatagramReceived) == [
        DatagramReceived(payload, False)
        for payload in [b"before", b"\x00", b"\x01", b"\x02", b"\x03"]
    ]


@pytest.mark.parametrize("frame_limit", [256, 65535], ids=["frame-limit", "path-limit"])
def test_the_reported_datagram_payload_limit_is_sendable(network, frame_limit):
    network.client_transport = TransportConfig(pmtud=False)
    network.server_transport = TransportConfig(max_datagram_frame_size=frame_limit)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    limit = client.max_datagram_size
    assert limit is not None and limit > 0
    payload = b"x" * limit

    client.send_datagram(payload)
    network.run(lambda: network.events_of(network.server, DatagramReceived))

    assert network.events_of(network.server, DatagramReceived) == [
        DatagramReceived(payload, False)
    ]


def test_datagram_limit_respects_the_peer_udp_payload_limit(network):
    network.client_transport = TransportConfig(
        udp_payload_size_shaping=False, pmtud=False
    )
    network.server_transport = TransportConfig(
        max_udp_payload_size=1200, max_datagram_frame_size=65535
    )
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    size = client.max_datagram_size

    client.send_datagram(bytes(size))
    network.run(lambda: network.events_of(network.server, DatagramReceived))

    assert network.events_of(network.server, DatagramReceived) == [
        DatagramReceived(bytes(size), False)
    ]


# Type byte, then a 1-byte length below 64 and a 2-byte one from there.
@pytest.mark.parametrize(
    ("frame_limit", "payload"), [(3, 1), (65, 63), (66, 63), (67, 64)]
)
def test_the_datagram_payload_limit_is_exact(network, frame_limit, payload):
    network.server_transport = TransportConfig(max_datagram_frame_size=frame_limit)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))

    assert client.max_datagram_size == payload
    client.send_datagram(bytes(payload))
    network.run(lambda: network.events_of(network.server, DatagramReceived))
    assert network.events_of(network.server, DatagramReceived)


def test_a_frame_limit_too_small_for_any_payload_disables_datagrams(network):
    network.server_transport = TransportConfig(max_datagram_frame_size=1)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))

    assert client.max_datagram_size is None
    with pytest.raises(DatagramError, match="does not accept"):
        client.send_datagram(b"")


def test_the_datagram_queue_must_hold_at_least_one(network):
    network.client_transport = TransportConfig(max_datagram_queue=0)

    with pytest.raises(ValueError, match="max_datagram_queue"):
        network.connect()
