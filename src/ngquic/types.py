from dataclasses import dataclass
from typing import TypeAlias

Address: TypeAlias = tuple[str, int] | tuple[str, int, int, int]
"""An IP address and port, as asyncio datagram endpoints report them."""


@dataclass(frozen=True, kw_only=True, slots=True)
class ConnectionStats:
    """Round-trip, congestion and traffic statistics of a connection.

    A snapshot of ngtcp2's ``ngtcp2_conn_info``. Times are in seconds and
    sizes in bytes; counters cover the whole connection. RTT estimation
    follows RFC 9002, section 5:
    https://www.rfc-editor.org/rfc/rfc9002.html#section-5

    Attributes:
        latest_rtt: The latest RTT sample, not adjusted by acknowledgment
            delay.
        min_rtt: The minimum RTT seen so far, not adjusted by acknowledgment
            delay.
        smoothed_rtt: The smoothed RTT.
        rtt_variance: The mean deviation of observed RTT samples.
        congestion_window: Bytes the sender may have in flight.
        slow_start_threshold: Congestion window size at which slow start
            ends.
        bytes_in_flight: Bytes of sent packets not yet acknowledged.
        packets_sent: QUIC packets sent.
        bytes_sent: Sum of the lengths of QUIC packets sent.
        packets_received: QUIC packets received, excluding discarded ones.
        bytes_received: Sum of the lengths of QUIC packets received.
        packets_lost: QUIC packets declared lost, excluding PMTU probes.
        bytes_lost: Sum of the lengths of QUIC packets declared lost.
        pings_received: PING frames received.
        packets_discarded: QUIC packets discarded.
    """

    latest_rtt: float
    min_rtt: float
    smoothed_rtt: float
    rtt_variance: float
    congestion_window: int
    slow_start_threshold: int
    bytes_in_flight: int
    packets_sent: int
    bytes_sent: int
    packets_received: int
    bytes_received: int
    packets_lost: int
    bytes_lost: int
    pings_received: int
    packets_discarded: int


@dataclass(frozen=True, kw_only=True, slots=True)
class PreferredAddress:
    """Addresses a server asks clients to move to after the handshake.

    RFC 9000 section 9.6. The server must also receive datagrams on these
    addresses and pass them to the same ``Endpoint``.

    Attributes:
        ipv4: IPv4 address and port, or ``None``.
        ipv6: IPv6 address and port, or ``None``.
    """

    ipv4: Address | None = None
    ipv6: Address | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class TransportParameters:
    """Transport parameters the peer announced in its handshake.

    Names match the ``TransportConfig`` fields that produce them on this
    side; the wire names follow in parentheses. Durations are in seconds and
    sizes in bytes. See RFC 9000, section 18.2:
    https://www.rfc-editor.org/rfc/rfc9000.html#section-18.2

    Attributes:
        max_data: Connection flow control limit (``initial_max_data``).
        max_stream_data_bidi_local: Flow control limit for bidirectional
            streams this peer opens (``initial_max_stream_data_bidi_local``).
        max_stream_data_bidi_remote: Flow control limit for bidirectional
            streams opened toward this peer
            (``initial_max_stream_data_bidi_remote``).
        max_stream_data_uni: Flow control limit for unidirectional streams
            opened toward this peer (``initial_max_stream_data_uni``).
        max_streams_bidi: Bidirectional streams the peer lets this side open
            (``initial_max_streams_bidi``).
        max_streams_uni: Unidirectional streams the peer lets this side open
            (``initial_max_streams_uni``).
        idle_timeout: The peer's idle timeout (``max_idle_timeout``);
            ``None`` means none.
        max_udp_payload_size: Largest UDP payload the peer accepts
            (``max_udp_payload_size``).
        active_connection_id_limit: Connection IDs the peer is willing to
            store (``active_connection_id_limit``).
        ack_delay_exponent: Exponent the peer uses to encode the ACK Delay
            field (``ack_delay_exponent``).
        max_ack_delay: Longest time the peer delays acknowledgments
            (``max_ack_delay``).
        max_datagram_frame_size: Largest DATAGRAM frame the peer accepts,
            or ``None`` if it accepts none (RFC 9221, section 3).
        disable_active_migration: Whether the peer forbids migrating to a
            new address during the connection
            (``disable_active_migration``).
        grease_quic_bit: Whether the peer accepts packets with the fixed
            bit cleared (RFC 9287, section 3).
        preferred_address: Addresses the server asks the client to move to
            (``preferred_address``, server only).
    """

    max_data: int
    max_stream_data_bidi_local: int
    max_stream_data_bidi_remote: int
    max_stream_data_uni: int
    max_streams_bidi: int
    max_streams_uni: int
    idle_timeout: float | None
    max_udp_payload_size: int
    active_connection_id_limit: int
    ack_delay_exponent: int
    max_ack_delay: float
    max_datagram_frame_size: int | None
    disable_active_migration: bool
    grease_quic_bit: bool
    preferred_address: PreferredAddress | None
