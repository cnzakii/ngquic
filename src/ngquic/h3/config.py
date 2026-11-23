from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True, slots=True)
class H3Config:
    """HTTP/3 settings of one connection (RFC 9114, RFC 9204).

    Attributes:
        max_field_section_size: Largest header section accepted, announced
            as SETTINGS_MAX_FIELD_SECTION_SIZE; ``None`` announces no limit.
        qpack_max_dtable_capacity: QPACK dynamic table capacity the peer's
            encoder may use; ``0`` disables the dynamic table for headers
            this side receives.
        qpack_encoder_max_dtable_capacity: Upper bound of the dynamic table
            this side's encoder uses, within the peer's capacity.
        qpack_blocked_streams: Streams the peer's encoder may leave blocked
            on dynamic table updates.
        enable_connect_protocol: Whether a server accepts extended CONNECT
            (RFC 9220), which carries ``:protocol``.
        h3_datagram: Whether this side accepts HTTP/3 datagrams (RFC 9297),
            announced as SETTINGS_H3_DATAGRAM; needs
            ``TransportConfig.max_datagram_frame_size``.
        origins: Origins a server announces in an ORIGIN frame (RFC 9412),
            such as ``b"https://example.com"``; ``None`` sends none.
        glitch_rate_limit: Token bucket ``(burst, per_second)`` for peer
            behavior that costs resources without making progress: up to
            ``burst`` such events at once, refilled by ``per_second`` each
            second; exceeding it closes the connection.
    """

    max_field_section_size: int | None = None
    qpack_max_dtable_capacity: int = 4096
    qpack_encoder_max_dtable_capacity: int = 4096
    qpack_blocked_streams: int = 100
    enable_connect_protocol: bool = False
    h3_datagram: bool = False
    origins: tuple[bytes, ...] | None = None
    glitch_rate_limit: tuple[int, int] = (1000, 33)
