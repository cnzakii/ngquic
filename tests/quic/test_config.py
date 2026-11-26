"""Configuration and argument validation at the public boundary."""

import enum

import pytest
from support.network import SERVER_ADDR, Network

from ngquic import (
    Connection,
    ConnectionState,
    Endpoint,
    EndpointConfig,
    HandshakeConfirmed,
    PreferredAddress,
    TLSContext,
    TransportConfig,
    Version,
)


@pytest.mark.parametrize(
    ("transport", "error", "match"),
    [
        ("config", TypeError, "transport must be a TransportConfig"),
        (
            TransportConfig(max_data=1.5),  # ty: ignore[invalid-argument-type]
            TypeError,
            "max_data must be an integer",
        ),
        (TransportConfig(max_data=-1), ValueError, "max_data must be between"),
        (TransportConfig(idle_timeout=-1.0), ValueError, "idle_timeout"),
        (TransportConfig(idle_timeout=0.0), ValueError, "None disables it"),
        (TransportConfig(max_window=0), ValueError, "None disables it"),
        (TransportConfig(max_udp_payload_size=1199), ValueError, "at least 1200"),
        (TransportConfig(active_connection_id_limit=1), ValueError, "at least 2"),
        (TransportConfig(max_ack_delay=16.384), ValueError, "below 16.384"),
        (TransportConfig(pmtud_probes=()), ValueError, "pmtud_probes"),
        (TransportConfig(pmtud_probes=(1200,)), ValueError, "pmtud_probes"),
        (TransportConfig(pmtud_probes=(1500,)), ValueError, "pmtud_probes"),
        (TransportConfig(path_degrading_ptos=0), ValueError, "path_degrading_ptos"),
    ],
    ids=[
        "not-a-config",
        "float-integer",
        "negative-integer",
        "negative-duration",
        "zero-timeout",
        "zero-window",
        "small-udp-payload",
        "one-connection-id",
        "long-ack-delay",
        "no-probes",
        "probe-at-minimum",
        "probe-above-tx-limit",
        "zero-degrading-ptos",
    ],
)
def test_connect_rejects_an_invalid_transport(network, transport, error, match):
    with pytest.raises(error, match=match):
        network.connect(transport=transport)


def test_pmtud_probes_set_the_probed_payload_sizes(server_tls, client_tls):
    network = Network(
        server_tls=server_tls,
        client_tls=client_tls,
        server_transport=TransportConfig(pmtud=False),
        client_transport=TransportConfig(pmtud_probes=(1300, 1400)),
        gso=False,
    )
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))

    network.advance(1.0)

    assert max(len(datagram) for datagram in network.sent) == 1400


@pytest.mark.parametrize(
    ("config", "error", "match"),
    [
        ("config", TypeError, "config must be an EndpointConfig"),
        (EndpointConfig(connection_id_length=7), ValueError, "between 8 and 20"),
        (EndpointConfig(connection_id_length=21), ValueError, "between 0 and 20"),
        (EndpointConfig(preferred_versions=()), ValueError, "must not be empty"),
        (
            EndpointConfig(preferred_versions=(Version.V1,) * 9),
            ValueError,
            "at most 8 versions",
        ),
        (EndpointConfig(secret=b"x" * 31), ValueError, "at least 32 bytes"),
        (
            EndpointConfig(preferred_address="127.0.0.1"),  # ty: ignore[invalid-argument-type]
            TypeError,
            "must be a PreferredAddress",
        ),
        (
            EndpointConfig(preferred_address=PreferredAddress(ipv6=("127.0.0.1", 1))),
            ValueError,
            "ipv6 must be an IPv6 address",
        ),
    ],
    ids=[
        "not-a-config",
        "short-connection-id",
        "long-connection-id",
        "no-versions",
        "too-many-versions",
        "short-secret",
        "preferred-address-type",
        "preferred-ipv6-family",
    ],
)
def test_endpoint_rejects_an_invalid_config(config, error, match):
    with pytest.raises(error, match=match):
        Endpoint(SERVER_ADDR, config)


@pytest.mark.parametrize(
    ("address", "error", "match"),
    [
        ((b"127.0.0.1", 4433), TypeError, "host must be a str"),
        (("::1", 4433, -1, 0), ValueError, "flowinfo"),
        (("::1", 4433, 0, 1 << 32), ValueError, "scope_id"),
        (("0.0.0.0", 0), ValueError, "name a port"),
    ],
    ids=["bytes-host", "negative-flowinfo", "large-scope-id", "no-port"],
)
def test_endpoint_rejects_an_invalid_address(address, error, match):
    with pytest.raises(error, match=match):
        Endpoint(address)


def test_a_datagram_needs_a_local_port(network):
    with pytest.raises(ValueError, match="name a port"):
        network.client_endpoint.receive_datagram(
            bytes(1200), SERVER_ADDR, 1.0, local_addr=("127.0.0.1", 0)
        )


def test_connect_requires_a_client_context(network):
    with pytest.raises(ValueError, match="client TLSContext"):
        network.client_endpoint.connect(SERVER_ADDR, 1.0, tls=network.server_tls)


def test_accept_requires_a_server_context(network):
    network.accept = lambda incoming: incoming.accept(tls=network.client_tls)

    with pytest.raises(ValueError, match="server TLSContext"):
        network.connect()
        network.run()


def test_server_name_must_be_a_string(network):
    with pytest.raises(TypeError, match="server_name must be a str"):
        network.connect(server_name=b"localhost")


# An empty name would leave the certificate's host unchecked.
def test_a_trailing_dot_is_dropped_from_the_server_name(network):
    client = network.connect(server_name="localhost\u3002")

    network.run(lambda: network.events_of(client, HandshakeConfirmed))

    assert client.server_name == "localhost\u3002"
    assert client.state is ConnectionState.ESTABLISHED


# U+2024 encodes to a leading dot, which would match any subdomain.
@pytest.mark.parametrize("name", ["", "local\0host", "\u2024localhost"])
def test_server_name_must_be_a_host_name(network, name):
    with pytest.raises(ValueError, match="cannot be empty, start with a dot"):
        network.connect(server_name=name)


def test_server_name_must_fit_the_tls_extension(network):
    with pytest.raises(ValueError, match="not a host name TLS accepts"):
        network.connect(server_name=".".join(["a" * 63] * 5))


def test_an_ip_address_tls_cannot_parse_is_never_left_unverified(network):
    # macOS reads leading zeros as 127.0.0.1, which AWS-LC refuses to match.
    try:
        client = network.connect(server_name="127.000.000.001")
    except ValueError as error:
        assert "not an IP address TLS accepts" in str(error)
        return
    network.run()

    assert not network.events_of(client, HandshakeConfirmed)


def test_server_name_may_be_a_str_subclass(network):
    class Host(str, enum.Enum):
        LOCAL = "localhost"

    client = network.connect(server_name=Host.LOCAL)
    network.run(lambda: network.events_of(client, HandshakeConfirmed))

    assert client.state is ConnectionState.ESTABLISHED


# The codec's reason reads "label empty or too long" before Python 3.13.
@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("a" * 64 + ".example", "too long"),
        ("a..b", "label empty"),
        (".localhost", "label empty"),
        ("..", "label empty"),
    ],
)
def test_server_name_labels_must_be_valid(network, name, reason):
    with pytest.raises(ValueError, match="is not a valid host name: ") as error:
        network.connect(server_name=name)

    assert reason in str(error.value)
    assert not isinstance(error.value, UnicodeError)


# ngtcp2 asserts these, and a release build would carry on regardless.
@pytest.mark.parametrize(
    ("transport", "match"),
    [
        (TransportConfig(initial_rtt=0.0), "initial_rtt must be positive"),
        (TransportConfig(initial_rtt=1e-10), "initial_rtt must be positive"),
        (TransportConfig(active_connection_id_limit=9), "active_connection_id_limit"),
    ],
    ids=["zero-rtt", "rounds-to-zero", "cid-limit"],
)
def test_transport_values_ngtcp2_cannot_take_are_refused(network, transport, match):
    with pytest.raises(ValueError, match=match):
        network.connect(transport=transport)


def test_the_first_version_must_be_a_preferred_one(client_tls):
    endpoint = Endpoint(
        ("127.0.0.1", 50000), EndpointConfig(preferred_versions=(Version.V1,))
    )

    with pytest.raises(ValueError, match="not in preferred_versions"):
        endpoint.connect(
            SERVER_ADDR,
            1.0,
            tls=client_tls,
            server_name="localhost",
            version=Version.V2,
        )


def test_tls_context_requires_a_role():
    with pytest.raises(TypeError, match="role must be a Role"):
        TLSContext("client")  # ty: ignore[invalid-argument-type]


@pytest.mark.parametrize("now", [-1.0, float("nan"), 1.8e10])
def test_time_must_be_a_non_negative_monotonic_second_count(network, now):
    client = network.connect()

    with pytest.raises(ValueError, match="now must be a non-negative"):
        client.datagrams_to_send(now)


def test_an_earlier_now_counts_as_the_latest_one(network):
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeConfirmed))
    earlier = network.now
    network.now += 0.5
    client.update_key(network.now)

    # A driver that read its clock before handling events passes this.
    client.datagrams_to_send(earlier)
    client.handle_timer(earlier)
    network.run()

    assert client.state == ConnectionState.ESTABLISHED


def test_datagrams_to_send_needs_a_positive_budget(network):
    client = network.connect()

    with pytest.raises(ValueError, match="max_datagrams must be positive"):
        client.datagrams_to_send(network.now, max_datagrams=0)


@pytest.mark.parametrize(
    ("reason", "error"),
    [("bye", TypeError), (b"x" * 1025, ValueError)],
    ids=["str", "too-long"],
)
def test_close_validates_the_reason_phrase(network, reason, error):
    client = network.connect()

    with pytest.raises(error, match="reason must be"):
        client.close(reason=reason)


def test_connections_come_from_endpoints():
    with pytest.raises(TypeError, match=r"Endpoint\.connect"):
        Connection()


@pytest.mark.parametrize(
    ("ticket", "match"),
    [
        (b"\x02\x00\x00\x00\x00", "not a ticket"),
        (b"\x01\x00\x00\x00\x10abc", "truncated"),
        (b"\x01\x00\x00\x00\x03abc", "no valid TLS session"),
    ],
    ids=["wrong-format", "truncated", "garbage-session"],
)
def test_connect_rejects_an_unusable_session_ticket(network, ticket, match):
    with pytest.raises(ValueError, match=match):
        network.connect(session_ticket=ticket)
