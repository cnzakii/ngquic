from .enums import CloseReason
from .types import Address

class Event:
    """Base type for events produced by a connection."""

    __match_args__: tuple[str, ...] = ()

class HandshakeCompleted(Event):
    """The handshake completed and the peer is authenticated.

    Attributes:
        alpn_protocol: Negotiated application protocol.
        session_resumed: Whether a session ticket resumed the TLS session.
        early_data_accepted: Whether the server accepted 0-RTT data.
    """

    __match_args__ = ("alpn_protocol", "session_resumed", "early_data_accepted")
    def __init__(
        self,
        alpn_protocol: str | None,
        session_resumed: bool,
        early_data_accepted: bool,
    ) -> None: ...
    @property
    def alpn_protocol(self) -> str | None: ...
    @property
    def session_resumed(self) -> bool: ...
    @property
    def early_data_accepted(self) -> bool: ...

class HandshakeConfirmed(Event):
    """The peer confirmed the handshake; a client may now migrate."""

    __match_args__ = ()

class StreamDataReceived(Event):
    """Stream data arrived in order.

    Attributes:
        stream_id: Stream carrying the data.
        data: The data; empty only when it ends the stream.
        end_stream: Whether the peer finished sending on this stream.
        early: Whether any of it arrived in 0-RTT, before the handshake
            authenticated the peer.
    """

    __match_args__ = ("stream_id", "data", "end_stream", "early")
    def __init__(
        self, stream_id: int, data: bytes, end_stream: bool, early: bool
    ) -> None: ...
    @property
    def stream_id(self) -> int: ...
    @property
    def data(self) -> bytes: ...
    @property
    def end_stream(self) -> bool: ...
    @property
    def early(self) -> bool: ...

class StreamReset(Event):
    """The peer abandoned sending on a stream with RESET_STREAM.

    Attributes:
        stream_id: The reset stream.
        error_code: Application error code.
        final_size: Bytes the peer had sent on the stream.
    """

    __match_args__ = ("stream_id", "error_code", "final_size")
    def __init__(self, stream_id: int, error_code: int, final_size: int) -> None: ...
    @property
    def stream_id(self) -> int: ...
    @property
    def error_code(self) -> int: ...
    @property
    def final_size(self) -> int: ...

class StopSendingReceived(Event):
    """The peer asked this side to stop sending on a stream.

    The stream is reset with the same code.

    Attributes:
        stream_id: The stream.
        error_code: Application error code.
    """

    __match_args__ = ("stream_id", "error_code")
    def __init__(self, stream_id: int, error_code: int) -> None: ...
    @property
    def stream_id(self) -> int: ...
    @property
    def error_code(self) -> int: ...

class StreamClosed(Event):
    """Both directions of a stream finished and its state was released.

    Attributes:
        stream_id: The closed stream.
        receive_error_code: Code that cut the receiving direction short, or
            ``None`` if it ended normally.
        send_error_code: Code that cut the sending direction short, or
            ``None`` if it ended normally.
    """

    __match_args__ = ("stream_id", "receive_error_code", "send_error_code")
    def __init__(
        self,
        stream_id: int,
        receive_error_code: int | None,
        send_error_code: int | None,
    ) -> None: ...
    @property
    def stream_id(self) -> int: ...
    @property
    def receive_error_code(self) -> int | None: ...
    @property
    def send_error_code(self) -> int | None: ...

class StreamsAvailable(Event):
    """The peer allows more streams to be opened.

    Attributes:
        bidirectional: Bidirectional streams that can be opened now.
        unidirectional: Unidirectional streams that can be opened now.
    """

    __match_args__ = ("bidirectional", "unidirectional")
    def __init__(self, bidirectional: int, unidirectional: int) -> None: ...
    @property
    def bidirectional(self) -> int: ...
    @property
    def unidirectional(self) -> int: ...

class StreamWritable(Event):
    """A stream that reported back-pressure is down to its low mark or below.

    Attributes:
        stream_id: The stream.
    """

    __match_args__ = ("stream_id",)
    def __init__(self, stream_id: int) -> None: ...
    @property
    def stream_id(self) -> int: ...

class DatagramReceived(Event):
    """A DATAGRAM frame arrived.

    Attributes:
        data: Its payload.
        early: Whether it arrived in 0-RTT.
    """

    __match_args__ = ("data", "early")
    def __init__(self, data: bytes, early: bool) -> None: ...
    @property
    def data(self) -> bytes: ...
    @property
    def early(self) -> bool: ...

class DatagramAcknowledged(Event):
    """The peer acknowledged a DATAGRAM.

    Attributes:
        datagram_id: ID returned by ``send_datagram()``.
    """

    __match_args__ = ("datagram_id",)
    def __init__(self, datagram_id: int) -> None: ...
    @property
    def datagram_id(self) -> int: ...

class DatagramLost(Event):
    """A DATAGRAM was lost or dropped.

    Attributes:
        datagram_id: ID returned by ``send_datagram()``.
        sent: ``False`` if it was dropped before being sent: the queue was
            full, or the path's packet size shrank below the payload.
    """

    __match_args__ = ("datagram_id", "sent")
    def __init__(self, datagram_id: int, sent: bool) -> None: ...
    @property
    def datagram_id(self) -> int: ...
    @property
    def sent(self) -> bool: ...

class SessionTicketReceived(Event):
    """The server issued a ticket for resuming, and possibly 0-RTT.

    Attributes:
        ticket: Opaque value for ``Endpoint.connect(session_ticket=...)``.
    """

    __match_args__ = ("ticket",)
    def __init__(self, ticket: bytes) -> None: ...
    @property
    def ticket(self) -> bytes: ...

class NewTokenReceived(Event):
    """The server issued an address validation token.

    Attributes:
        token: Opaque value for ``Endpoint.connect(token=...)``.
    """

    __match_args__ = ("token",)
    def __init__(self, token: bytes) -> None: ...
    @property
    def token(self) -> bytes: ...

class EarlyDataRejected(Event):
    """The server rejected 0-RTT.

    Streams opened before the handshake are gone and their data must be resent.
    """

    __match_args__ = ()

class ClientHelloReceived(Event):
    """A server paused its handshake to let the application pick a certificate.

    Sent when the server ``TLSContext`` has ``defer_certificate_selection``
    enabled. The handshake continues after ``Connection.select_tls_context()``.

    Attributes:
        server_name: Server name the client sent (SNI), or ``None``.
        alpn_protocols: Application protocols the client offered.
    """

    __match_args__ = ("server_name", "alpn_protocols")
    def __init__(
        self, server_name: str | None, alpn_protocols: tuple[str, ...]
    ) -> None: ...
    @property
    def server_name(self) -> str | None: ...
    @property
    def alpn_protocols(self) -> tuple[str, ...]: ...

class PeerCertificateReceived(Event):
    """The handshake paused for the application to verify the peer.

    Sent when the ``TLSContext`` has ``defer_peer_verification`` enabled.
    The handshake continues after ``Connection.verify_peer_certificate()``.

    Attributes:
        chain: DER certificates as the peer sent them, leaf first; not
            verified.
    """

    __match_args__ = ("chain",)
    def __init__(self, chain: tuple[bytes, ...]) -> None: ...
    @property
    def chain(self) -> tuple[bytes, ...]: ...

class PathValidationStarted(Event):
    """Validation of a new network path started.

    Attributes:
        local_addr: Local address of the path.
        remote_addr: Remote address of the path.
        preferred_address: Whether the path leads to the server's preferred address.
    """

    __match_args__ = ("local_addr", "remote_addr", "preferred_address")
    def __init__(
        self, local_addr: Address, remote_addr: Address, preferred_address: bool
    ) -> None: ...
    @property
    def local_addr(self) -> Address: ...
    @property
    def remote_addr(self) -> Address: ...
    @property
    def preferred_address(self) -> bool: ...

class PathValidated(Event):
    """Validation of a network path finished.

    Attributes:
        local_addr: Local address of the path.
        remote_addr: Remote address of the path.
        preferred_address: Whether the path leads to the server's preferred address.
        success: Whether the peer answered on this path.
    """

    __match_args__ = ("local_addr", "remote_addr", "preferred_address", "success")
    def __init__(
        self,
        local_addr: Address,
        remote_addr: Address,
        preferred_address: bool,
        success: bool,
    ) -> None: ...
    @property
    def local_addr(self) -> Address: ...
    @property
    def remote_addr(self) -> Address: ...
    @property
    def preferred_address(self) -> bool: ...
    @property
    def success(self) -> bool: ...

class PathDegrading(Event):
    """Data in flight went unacknowledged for the configured probe timeouts.

    Reported once per stall to clients with
    ``TransportConfig.path_degrading_ptos`` set, after handshake
    confirmation; ``PathRecovered`` follows once the peer acknowledges again.
    The connection stays open: whether to stop opening streams on it is the
    caller's decision.
    """

    __match_args__ = ()

class PathRecovered(Event):
    """The peer acknowledged data again after ``PathDegrading``."""

    __match_args__ = ()

class ConnectionTerminated(Event):
    """The connection stopped carrying data.

    Attributes:
        reason: What ended it.
        error_code: Error code from the CONNECTION_CLOSE; ``ErrorCode`` for
            transport errors.
        frame_type: Frame type that caused a transport error, if known.
        reason_phrase: Reason phrase from the CONNECTION_CLOSE.
        by_peer: Whether the peer ended it.
    """

    __match_args__ = ("reason", "error_code", "frame_type", "reason_phrase", "by_peer")
    def __init__(
        self,
        reason: CloseReason,
        error_code: int,
        frame_type: int | None,
        reason_phrase: bytes,
        by_peer: bool,
    ) -> None: ...
    @property
    def reason(self) -> CloseReason: ...
    @property
    def error_code(self) -> int: ...
    @property
    def frame_type(self) -> int | None: ...
    @property
    def reason_phrase(self) -> bytes: ...
    @property
    def by_peer(self) -> bool: ...
