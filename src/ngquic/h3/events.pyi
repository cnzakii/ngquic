"""HTTP/3 message events; stream and connection events are the QUIC ones."""

from ..events import Event
from .types import H3Settings

class RequestReceived(Event):
    """An HTTP/3 request header section arrived.

    Attributes:
        stream_id: Request stream; answer with ``send_response()``.
        headers: ``(name, value)`` byte pairs in received order, pseudo
            headers first; a field the sender marked never-indexed is a
            ``NeverIndexedHeader``.
        end_stream: Whether the request has no body.
    """

    __match_args__ = ("stream_id", "headers", "end_stream")
    def __init__(
        self, stream_id: int, headers: tuple[tuple[bytes, bytes], ...], end_stream: bool
    ) -> None: ...
    @property
    def stream_id(self) -> int: ...
    @property
    def headers(self) -> tuple[tuple[bytes, bytes], ...]: ...
    @property
    def end_stream(self) -> bool: ...

class ResponseReceived(Event):
    """The final response header section arrived.

    Attributes:
        stream_id: Request stream.
        headers: ``(name, value)`` byte pairs, ``:status`` first; a field
            the sender marked never-indexed is a ``NeverIndexedHeader``.
        end_stream: Whether the response has no body.
    """

    __match_args__ = ("stream_id", "headers", "end_stream")
    def __init__(
        self, stream_id: int, headers: tuple[tuple[bytes, bytes], ...], end_stream: bool
    ) -> None: ...
    @property
    def stream_id(self) -> int: ...
    @property
    def headers(self) -> tuple[tuple[bytes, bytes], ...]: ...
    @property
    def end_stream(self) -> bool: ...

class InformationalResponseReceived(Event):
    """An interim 1xx response arrived; the final response follows.

    Attributes:
        stream_id: Request stream.
        headers: ``(name, value)`` byte pairs, ``:status`` first; a field
            the sender marked never-indexed is a ``NeverIndexedHeader``.
    """

    __match_args__ = ("stream_id", "headers")
    def __init__(
        self, stream_id: int, headers: tuple[tuple[bytes, bytes], ...]
    ) -> None: ...
    @property
    def stream_id(self) -> int: ...
    @property
    def headers(self) -> tuple[tuple[bytes, bytes], ...]: ...

class TrailersReceived(Event):
    """A trailer section arrived; it ends the message.

    Attributes:
        stream_id: Request stream.
        headers: ``(name, value)`` byte pairs; a field the sender marked
            never-indexed is a ``NeverIndexedHeader``.
    """

    __match_args__ = ("stream_id", "headers")
    def __init__(
        self, stream_id: int, headers: tuple[tuple[bytes, bytes], ...]
    ) -> None: ...
    @property
    def stream_id(self) -> int: ...
    @property
    def headers(self) -> tuple[tuple[bytes, bytes], ...]: ...

class DataReceived(Event):
    """Message body data arrived in order.

    When ``TransportConfig.auto_flow_control`` is ``False``, return the
    credit with ``H3Connection.consume_received_data()``.

    Attributes:
        stream_id: Request stream.
        data: Body bytes; empty only when it ends the message.
        end_stream: Whether the message body is complete.
    """

    __match_args__ = ("stream_id", "data", "end_stream")
    def __init__(self, stream_id: int, data: bytes, end_stream: bool) -> None: ...
    @property
    def stream_id(self) -> int: ...
    @property
    def data(self) -> bytes: ...
    @property
    def end_stream(self) -> bool: ...

class DatagramReceived(Event):
    """An HTTP/3 datagram (RFC 9297) arrived for a request stream.

    Datagrams are unreliable and unordered; their meaning belongs to the
    request's extension, such as CONNECT-UDP. A request without datagram
    semantics should be reset with ``H3ErrorCode.H3_DATAGRAM_ERROR``.

    Attributes:
        stream_id: Request stream the datagram belongs to.
        data: The HTTP datagram payload, possibly empty.
    """

    __match_args__ = ("stream_id", "data")
    def __init__(self, stream_id: int, data: bytes) -> None: ...
    @property
    def stream_id(self) -> int: ...
    @property
    def data(self) -> bytes: ...

class GoAwayReceived(Event):
    """The peer started a graceful shutdown with GOAWAY.

    Attributes:
        id: On a client, the first request stream the server will not
            process; requests on lower streams still complete. ``2**62 - 4``
            is a notice that a final GOAWAY follows. On a server, the last
            push ID the client allows (RFC 9114 5.2); nghttp3 sends no
            server push, so only the shutdown itself matters.
    """

    __match_args__ = ("id",)
    def __init__(self, id: int) -> None: ...
    @property
    def id(self) -> int: ...

class SettingsReceived(Event):
    """The peer's SETTINGS frame arrived.

    Attributes:
        settings: The peer's ``H3Settings``.
    """

    __match_args__ = ("settings",)
    def __init__(self, settings: H3Settings) -> None: ...
    @property
    def settings(self) -> H3Settings: ...

class OriginReceived(Event):
    """A server listed the origins it is authoritative for (RFC 9412).

    Attributes:
        origins: ASCII serialized origins, such as ``b"https://example.com"``.
    """

    __match_args__ = ("origins",)
    def __init__(self, origins: tuple[bytes, ...]) -> None: ...
    @property
    def origins(self) -> tuple[bytes, ...]: ...
