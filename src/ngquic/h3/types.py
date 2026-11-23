from dataclasses import dataclass
from typing import NamedTuple, TypeAlias


class NeverIndexedHeader(NamedTuple):
    """A header field QPACK must never add to a dynamic table (RFC 9204 7.1.3).

    Use it for secrets such as ``authorization`` or ``cookie`` values.

    Attributes:
        name: Lowercase field name.
        value: Field value.
    """

    name: bytes
    value: bytes


Header: TypeAlias = tuple[bytes, bytes] | NeverIndexedHeader
"""An HTTP field as a ``(name, value)`` pair of bytes."""


@dataclass(frozen=True, slots=True)
class Priority:
    """RFC 9218 extensible priority parameters.

    Attributes:
        urgency: From 0 (most urgent) to 7.
        incremental: Whether the response is useful as it arrives.
    """

    urgency: int = 3
    incremental: bool = False


@dataclass(frozen=True, kw_only=True, slots=True)
class H3Settings:
    """HTTP/3 settings a peer announced (RFC 9114 7.2.4, RFC 9204 5).

    Attributes:
        max_field_section_size: Largest header section the peer accepts.
        qpack_max_dtable_capacity: Dynamic table capacity the peer's
            decoder allows.
        qpack_blocked_streams: Streams the peer lets this side's encoder
            block.
        enable_connect_protocol: Whether the peer accepts extended CONNECT.
        h3_datagram: Whether the peer accepts HTTP datagrams (RFC 9297).
    """

    max_field_section_size: int
    qpack_max_dtable_capacity: int
    qpack_blocked_streams: int
    enable_connect_protocol: bool
    h3_datagram: bool
