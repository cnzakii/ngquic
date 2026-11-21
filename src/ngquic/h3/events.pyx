# cython: embedsignature=True, freethreading_compatible=True, language_level=3
"""HTTP/3 message events; stream and connection events are the QUIC ones."""

from ..events cimport Event


cdef class RequestReceived(Event):
    """An HTTP/3 request header section arrived.

    Attributes:
        stream_id: Request stream; answer with ``send_response()``.
        headers: ``(name, value)`` byte pairs in received order, pseudo
            headers first; a field the sender marked never-indexed is a
            ``NeverIndexedHeader``.
        end_stream: Whether the request has no body.
    """

    __match_args__ = ("stream_id", "headers", "end_stream")

    def __init__(self, stream_id, headers, end_stream):
        self.stream_id = stream_id
        self.headers = headers
        self.end_stream = end_stream


cdef class ResponseReceived(Event):
    """The final response header section arrived.

    Attributes:
        stream_id: Request stream.
        headers: ``(name, value)`` byte pairs, ``:status`` first; a field
            the sender marked never-indexed is a ``NeverIndexedHeader``.
        end_stream: Whether the response has no body.
    """

    __match_args__ = ("stream_id", "headers", "end_stream")

    def __init__(self, stream_id, headers, end_stream):
        self.stream_id = stream_id
        self.headers = headers
        self.end_stream = end_stream


cdef class InformationalResponseReceived(Event):
    """An interim 1xx response arrived; the final response follows.

    Attributes:
        stream_id: Request stream.
        headers: ``(name, value)`` byte pairs, ``:status`` first; a field
            the sender marked never-indexed is a ``NeverIndexedHeader``.
    """

    __match_args__ = ("stream_id", "headers")

    def __init__(self, stream_id, headers):
        self.stream_id = stream_id
        self.headers = headers


cdef class TrailersReceived(Event):
    """A trailer section arrived; it ends the message.

    Attributes:
        stream_id: Request stream.
        headers: ``(name, value)`` byte pairs; a field the sender marked
            never-indexed is a ``NeverIndexedHeader``.
    """

    __match_args__ = ("stream_id", "headers")

    def __init__(self, stream_id, headers):
        self.stream_id = stream_id
        self.headers = headers


cdef class DataReceived(Event):
    """Message body data arrived in order.

    When ``TransportConfig.auto_flow_control`` is ``False``, return the
    credit with ``H3Connection.consume_received_data()``.

    Attributes:
        stream_id: Request stream.
        data: Body bytes; empty only when it ends the message.
        end_stream: Whether the message body is complete.
    """

    __match_args__ = ("stream_id", "data", "end_stream")

    def __init__(self, stream_id, data, end_stream):
        self.stream_id = stream_id
        self.data = data
        self.end_stream = end_stream


cdef class DatagramReceived(Event):
    """An HTTP/3 datagram (RFC 9297) arrived for a request stream.

    Datagrams are unreliable and unordered; their meaning belongs to the
    request's extension, such as CONNECT-UDP. A request without datagram
    semantics should be reset with ``H3ErrorCode.H3_DATAGRAM_ERROR``.

    Attributes:
        stream_id: Request stream the datagram belongs to.
        data: The HTTP datagram payload, possibly empty.
    """

    __match_args__ = ("stream_id", "data")

    def __init__(self, stream_id, data):
        self.stream_id = stream_id
        self.data = data


cdef class GoAwayReceived(Event):
    """The peer started a graceful shutdown with GOAWAY.

    Attributes:
        id: On a client, the first request stream the server will not
            process; requests on lower streams still complete. ``2**62 - 4``
            is a notice that a final GOAWAY follows. On a server, the last
            push ID the client allows (RFC 9114 5.2); nghttp3 sends no
            server push, so only the shutdown itself matters.
    """

    __match_args__ = ("id",)

    def __init__(self, id):
        self.id = id


cdef class SettingsReceived(Event):
    """The peer's SETTINGS frame arrived.

    Attributes:
        settings: The peer's ``H3Settings``.
    """

    __match_args__ = ("settings",)

    def __init__(self, settings):
        self.settings = settings


cdef class OriginReceived(Event):
    """A server listed the origins it is authoritative for (RFC 9412).

    Attributes:
        origins: ASCII serialized origins, such as ``b"https://example.com"``.
    """

    __match_args__ = ("origins",)

    def __init__(self, origins):
        self.origins = origins
