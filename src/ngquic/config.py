from collections.abc import Callable
from dataclasses import dataclass

from .enums import CongestionControl, Version
from .types import PreferredAddress


@dataclass(frozen=True, kw_only=True, slots=True)
class TransportConfig:
    """Per-connection transport behavior and limits.

    Values are validated when a connection is created. Durations are in
    seconds and sizes in bytes.

    Attributes:
        max_data: Connection-level receive window first advertised to the
            peer.
        max_stream_data_bidi_local: Receive window of bidirectional streams
            this side opens.
        max_stream_data_bidi_remote: Receive window of bidirectional streams
            the peer opens.
        max_stream_data_uni: Receive window of unidirectional streams the
            peer opens.
        max_streams_bidi: Bidirectional streams the peer may have open at
            once. A closed peer stream returns its credit automatically. An
            HTTP/3 client advertises 0: HTTP/3 servers open no bidirectional
            streams (RFC 9114, section 6.1).
        max_streams_uni: Unidirectional streams the peer may have open at
            once.
        max_window: Upper bound of the connection receive window when
            auto-tuning grows it; ``None`` disables auto-tuning.
        max_stream_window: Upper bound of each stream receive window when
            auto-tuning grows it; ``None`` disables auto-tuning.
        auto_flow_control: Whether received data returns flow-control credit
            as soon as it is delivered. When ``False``, return it with
            ``consume_received_data()`` (``Connection`` and ``H3Connection``).
        stream_write_buffer_high: Bytes a stream may hold, unsent or unacknowledged,
            before ``Connection.send_stream_data()`` or ``H3Connection.send_data()``
            reports back-pressure.
        stream_write_buffer_low: Bytes at or below which a paused stream reports
            ``StreamWritable``; ``None`` means a quarter of the high mark.
        idle_timeout: Idle timeout advertised to the peer; ``None`` disables it.
        handshake_timeout: Time allowed for the handshake; ``None`` disables it.
        keep_alive_interval: Idle time after which a PING keeps the
            connection alive; ``None`` disables keep-alive.
        path_degrading_ptos: Probe timeouts that data in flight may wait
            for acknowledgment progress before a client reports
            ``PathDegrading``, at least 1; ``None`` disables it. The
            default of 4 matches Google quiche.
        initial_rtt: Round-trip time assumed before the first measurement.
        max_ack_delay: Maximum time this side delays acknowledgements.
        ack_delay_exponent: Exponent used to encode ACK delays.
        ack_threshold: Ack-eliciting packets received before an immediate
            acknowledgement.
        max_udp_payload_size: Largest UDP payload this side accepts.
        max_tx_udp_payload_size: Largest UDP payload this side sends after
            path MTU discovery.
        pmtud: Whether to probe for a larger path MTU.
        pmtud_probes: UDP payload sizes to probe, smallest first; ``None``
            uses ngtcp2's defaults.
        udp_payload_size_shaping: Whether outgoing packets stay at the
            validated path MTU instead of the full buffer size.
        active_connection_id_limit: Connection IDs this side stores for
            the peer.
        disable_active_migration: Whether the peer must not migrate.
        use_preferred_address: Whether a client moves to the server's
            preferred address of the same address family once the
            handshake is confirmed. The move keeps the local address, so
            it needs a socket that is not connected to the first one.
        congestion_control: Congestion control algorithm.
        max_datagram_frame_size: Largest DATAGRAM frame accepted; ``None``
            disables DATAGRAM support.
        max_datagram_queue: Unsent DATAGRAMs held, at least 1; the oldest is
            dropped when a new one exceeds it.
        grease_quic_bit: Whether to advertise support for greasing the QUIC
            bit, RFC 9287.
        glitch_rate_limit: Token bucket ``(burst, per_second)`` for peer
            behavior that costs resources without making progress: up to
            ``burst`` such events at once, refilled by ``per_second`` each
            second; exceeding it closes the connection.
        write_stream_data_threshold: Smallest STREAM frame payload written
            when flow control allows less than the queued data.
        qlog: Receives qlog JSON-SEQ fragments and whether each is the final
            one, or ``None`` to disable qlog.
    """

    max_data: int = 1 << 20
    max_stream_data_bidi_local: int = 256 << 10
    max_stream_data_bidi_remote: int = 256 << 10
    max_stream_data_uni: int = 256 << 10
    max_streams_bidi: int = 100
    max_streams_uni: int = 3
    max_window: int | None = 6 << 20
    max_stream_window: int | None = 6 << 20
    auto_flow_control: bool = True
    stream_write_buffer_high: int = 1 << 20
    stream_write_buffer_low: int | None = None
    idle_timeout: float | None = 30.0
    handshake_timeout: float | None = None
    keep_alive_interval: float | None = None
    path_degrading_ptos: int | None = 4
    initial_rtt: float = 0.333
    max_ack_delay: float = 0.025
    ack_delay_exponent: int = 3
    ack_threshold: int = 2
    max_udp_payload_size: int = 65527
    max_tx_udp_payload_size: int = 1452
    pmtud: bool = True
    pmtud_probes: tuple[int, ...] | None = None
    udp_payload_size_shaping: bool = True
    active_connection_id_limit: int = 2
    disable_active_migration: bool = False
    use_preferred_address: bool = True
    congestion_control: CongestionControl = CongestionControl.CUBIC
    max_datagram_frame_size: int | None = None
    max_datagram_queue: int = 64
    grease_quic_bit: bool = True
    glitch_rate_limit: tuple[int, int] = (10000, 330)
    write_stream_data_threshold: int = 0
    qlog: Callable[[bytes, bool], None] | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class EndpointConfig:
    """Behavior of an endpoint that routes datagrams for many connections.

    Attributes:
        preferred_versions: Versions this side prefers, most preferred
            first. A client that receives Version Negotiation reconnects
            with the first of these the server offers.
        available_versions: Versions a server accepts and lists in Version
            Negotiation, and advertises for compatible version negotiation
            (RFC 9368); ``None`` means ``preferred_versions``.
        connection_id_length: Length of the connection IDs this side issues,
            from 8 to 20 bytes.
        secret: Key for address validation tokens and stateless reset
            tokens, at least 32 bytes. Endpoints that share a load-balanced
            address must share it; ``None`` generates one per endpoint.
        retry_token_lifetime: Seconds a Retry token stays valid.
        new_token_lifetime: Seconds a NEW_TOKEN token stays valid.
        issue_new_tokens: Whether servers send NEW_TOKEN after the handshake
            so clients can skip address validation next time.
        stateless_reset: Whether to answer packets for unknown connections
            with a stateless reset.
        preferred_address: Addresses servers ask clients to migrate to.
    """

    preferred_versions: tuple[Version, ...] = (Version.V1, Version.V2)
    available_versions: tuple[Version, ...] | None = None
    connection_id_length: int = 18
    secret: bytes | None = None
    retry_token_lifetime: float = 10.0
    new_token_lifetime: float = 86400.0
    issue_new_tokens: bool = True
    stateless_reset: bool = True
    preferred_address: PreferredAddress | None = None
