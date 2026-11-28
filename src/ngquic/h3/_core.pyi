"""HTTP/3 connections: nghttp3 driven by BaseConnection's stream protocol hooks.

Only nghttp3 is linked here; QUIC operations go through BaseConnection
methods because ngtcp2 and AWS-LC live inside ngquic._core.
"""

from collections.abc import Iterable
from typing import final

from typing_extensions import Buffer

from .._core import BaseConnection
from .enums import H3ErrorCode
from .types import H3Settings, Header, Priority

def nghttp3_version() -> str:
    """Return the version of the bundled nghttp3 library."""

def parse_priority(field_value: Buffer) -> Priority:
    """Parse a Priority field value (RFC 9218), such as ``b"u=1, i"``.

    Parameters the value leaves out keep their defaults.

    Raises:
        ValueError: If the value is not a valid Priority field.
    """

@final
class H3Connection(BaseConnection):
    """A QUIC connection speaking HTTP/3 (RFC 9114) through nghttp3.

    Created by ``Endpoint.connect(..., h3=H3Config())`` or
    ``Incoming.accept(..., h3=H3Config())``; drive it like any connection.
    nghttp3 owns framing, QPACK, the control streams and stream scheduling;
    request bodies are queued here without copying ``bytes`` and released
    once acknowledged. Requests and responses report through ``events()``
    in the same queue as connection events.
    """

    @property
    def remote_settings(self) -> H3Settings | None: ...
    def send_request(
        self, headers: Iterable[Header], *, end_stream: bool = False
    ) -> int:
        """Open a request stream and send its header section.

        Before the handshake completes this needs a resumed session that
        allows 0-RTT; otherwise wait for ``HandshakeCompleted``.

        Args:
            headers: ``(name, value)`` byte pairs, pseudo headers first;
                names are sent in lowercase.
            end_stream: Whether the request has no body; otherwise send it
                with ``send_data()`` and finish with ``end_stream()`` or
                ``send_trailers()``.

        Returns:
            The request stream ID.

        Raises:
            StreamLimitError: If the server allows no more requests yet;
                ``StreamsAvailable`` reports new credit.
            ConnectionStateError: If the server is shutting down, the
                connection is closing or closed, or the request is an
                extended CONNECT the server has not enabled.
            ValueError: If a header is invalid or the request is malformed
                (RFC 9114, section 4.3.1), as a server would find it.
        """

    @property
    def bidi_streams_available(self) -> int:
        """Requests the server lets this client send now.

        0 on a server and once the server sent GOAWAY; ``StreamsAvailable``
        reports when it grows.
        """

    def send_response(
        self, stream_id: int, headers: Iterable[Header], *, end_stream: bool = False
    ) -> None:
        """Send the final response header section on a request stream.

        Args:
            stream_id: Stream of a ``RequestReceived``.
            headers: ``(name, value)`` byte pairs, ``:status`` first;
                names are sent in lowercase.
            end_stream: Whether the response has no body.

        Raises:
            StreamStateError: If the stream is not an open request or
                already has a response.
            ValueError: If a header is invalid, or ``:status`` is missing or
                not a final status code.
        """

    def send_informational_response(
        self, stream_id: int, headers: Iterable[Header]
    ) -> None:
        """Send an interim 1xx response before the final one.

        Raises:
            StreamStateError: If the stream cannot take a response now.
            ValueError: If a header is invalid, or ``:status`` is missing or
                not 1xx; HTTP/3 has no 101.
        """

    def send_data(
        self, stream_id: int, data: Buffer, *, end_stream: bool = False
    ) -> bool:
        """Queue message body data.

        ``bytes`` are held without copying until the peer acknowledges them;
        other buffers are copied once.

        Returns:
            ``False`` once the stream holds more than
            ``stream_write_buffer_high`` bytes; wait for ``StreamWritable``
            before queuing more.

        Raises:
            StreamStateError: If the message has no body or finished.
        """

    def end_stream(self, stream_id: int) -> None:
        """Finish the message after its queued body."""

    def send_trailers(self, stream_id: int, headers: Iterable[Header]) -> None:
        """Finish the message with a trailer section after its queued body.

        Raises:
            StreamStateError: If the message has no body or finished.
            ValueError: If a header is invalid or a pseudo-header.
        """

    def reset_stream(
        self,
        stream_id: int,
        error_code: int = H3ErrorCode.H3_REQUEST_CANCELLED,  # noqa: PYI011 - documented default
    ) -> None:
        """Abort a request in both directions (RFC 9114 4.1.1).

        Raises:
            ValueError: If ``stream_id`` is not a request stream ID; HTTP/3
                closes the connection when a critical stream is reset.
        """

    def stop_sending(
        self,
        stream_id: int,
        error_code: int = H3ErrorCode.H3_NO_ERROR,  # noqa: PYI011 - documented default
    ) -> None:
        """Stop reading a request body, as a server that already answered may.

        Raises:
            ValueError: If ``stream_id`` is not a request stream ID.
        """

    def consume_received_data(self, stream_id: int, amount: int) -> None:
        """Return flow-control credit for body data the application processed.

        Only needed when ``TransportConfig.auto_flow_control`` is ``False``.
        """

    def queued_body_size(self, stream_id: int | None = None) -> int:
        """Return body bytes held for sending: unsent plus unacknowledged."""

    def send_shutdown_notice(self) -> None:
        """Announce a coming GOAWAY; call ``send_goaway()`` an RTT or two later.

        Raises:
            ConnectionStateError: If GOAWAY was already sent; a notice would
                raise its ID, which RFC 9114 5.2 forbids.
        """

    def send_goaway(self) -> None:
        """Start a graceful shutdown with GOAWAY (RFC 9114 5.2).

        A server refuses requests it has not started and finishes the rest;
        once ``is_drained``, close the connection with ``H3_NO_ERROR``. A
        client's GOAWAY limits server push, which nghttp3 never enables, so
        a client closes once its own requests finish.
        """

    @property
    def is_drained(self) -> bool:
        """Whether a server sent GOAWAY and finished every request it accepted.

        Always ``False`` on a client.
        """

    def send_priority_update(self, stream_id: int, field_value: Buffer) -> None:
        """Ask the server to reprioritize a request, as ``b"u=1, i"``."""

    def set_stream_priority(self, stream_id: int, priority: Priority) -> None:
        """Schedule a response with ``priority``, overriding the client's signal."""

    def get_stream_priority(self, stream_id: int) -> Priority | None:
        """Return a request's current ``Priority``, or ``None`` if it is gone."""

    def send_datagram(self, stream_id: int, data: Buffer) -> int:
        """Queue an HTTP/3 datagram for a request stream.

        Both sides must enable ``H3Config.h3_datagram``; the peer's choice
        arrives with ``SettingsReceived``. The request's extension, such as
        CONNECT-UDP, gives datagrams their meaning.

        Returns:
            An ID reported by ``DatagramAcknowledged`` or ``DatagramLost``.

        Raises:
            DatagramError: If HTTP/3 datagrams are not negotiated or ``data``
                exceeds ``max_datagram_size(stream_id)``.
            StreamStateError: If the stream has no open message to send on:
                a server answers first, and nothing follows ``end_stream``.
            ValueError: If ``stream_id`` is not a request stream ID.
        """

    def max_datagram_size(self, stream_id: int) -> int | None:
        """Largest datagram payload sendable now on a request stream.

        Returns:
            The size in bytes, or ``None`` if HTTP/3 datagrams are not
            negotiated or the peer's QUIC limits leave no room.

        Raises:
            ValueError: If ``stream_id`` is not a request stream ID.
        """
