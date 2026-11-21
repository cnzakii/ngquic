"""HTTP/3 (RFC 9114) and QPACK (RFC 9204) over ngquic, powered by nghttp3.

Pass ``h3=H3Config()`` to ``Endpoint.connect()`` or ``Incoming.accept()`` to
get an ``H3Connection``. Everything an HTTP/3 application handles is exported
here, including the stream and connection events it shares with QUIC.
"""

from ..events import (
    ConnectionTerminated,
    DatagramAcknowledged,
    DatagramLost,
    EarlyDataRejected,
    Event,
    HandshakeCompleted,
    StopSendingReceived,
    StreamClosed,
    StreamReset,
    StreamsAvailable,
    StreamWritable,
)
from ._core import H3Connection, nghttp3_version, parse_priority
from .config import H3Config
from .enums import H3ErrorCode
from .events import (
    DatagramReceived,
    DataReceived,
    GoAwayReceived,
    InformationalResponseReceived,
    OriginReceived,
    RequestReceived,
    ResponseReceived,
    SettingsReceived,
    TrailersReceived,
)
from .types import H3Settings, Header, NeverIndexedHeader, Priority

__all__ = [
    "ConnectionTerminated",
    "DataReceived",
    "DatagramAcknowledged",
    "DatagramLost",
    "DatagramReceived",
    "EarlyDataRejected",
    "Event",
    "GoAwayReceived",
    "H3Config",
    "H3Connection",
    "H3ErrorCode",
    "H3Settings",
    "HandshakeCompleted",
    "Header",
    "InformationalResponseReceived",
    "NeverIndexedHeader",
    "OriginReceived",
    "Priority",
    "RequestReceived",
    "ResponseReceived",
    "SettingsReceived",
    "StopSendingReceived",
    "StreamClosed",
    "StreamReset",
    "StreamWritable",
    "StreamsAvailable",
    "TrailersReceived",
    "nghttp3_version",
    "parse_priority",
]
