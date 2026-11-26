# cython: embedsignature=True, freethreading_compatible=True, language_level=3


cdef class Event:
    """Base type for events produced by a connection."""

    __match_args__ = ()

    def __repr__(self):
        """Return a representation containing the public event fields."""
        # Not a comprehension: Cython 3.3 frees a comprehension's item twice
        # when appending it fails.
        fields = []
        for name in type(self).__match_args__:
            fields.append(f"{name}={getattr(self, name)!r}")
        return f"{type(self).__name__}({', '.join(fields)})"

    def __eq__(self, other):
        """Compare events of the same type field by field."""
        if type(other) is not type(self):
            return NotImplemented
        return all(
            getattr(self, name) == getattr(other, name)
            for name in type(self).__match_args__
        )

    __hash__ = None


cdef class HandshakeCompleted(Event):
    """The handshake completed and the peer is authenticated.

    Attributes:
        alpn_protocol: Negotiated application protocol.
        session_resumed: Whether a session ticket resumed the TLS session.
        early_data_accepted: Whether the server accepted 0-RTT data.
    """

    __match_args__ = ("alpn_protocol", "session_resumed", "early_data_accepted")

    def __init__(self, alpn_protocol, session_resumed, early_data_accepted):
        self.alpn_protocol = alpn_protocol
        self.session_resumed = session_resumed
        self.early_data_accepted = early_data_accepted


cdef class HandshakeConfirmed(Event):
    """The peer confirmed the handshake; a client may now migrate.
    """

    __match_args__ = ()


cdef class StreamDataReceived(Event):
    """Stream data arrived in order.

    Attributes:
        stream_id: Stream carrying the data.
        data: The data; empty only when it ends the stream.
        end_stream: Whether the peer finished sending on this stream.
        early: Whether any of it arrived in 0-RTT, before the handshake
            authenticated the peer.
    """

    __match_args__ = ("stream_id", "data", "end_stream", "early")

    def __init__(self, stream_id, data, end_stream, early):
        self.stream_id = stream_id
        self.data = data
        self.end_stream = end_stream
        self.early = early


cdef class StreamReset(Event):
    """The peer abandoned sending on a stream with RESET_STREAM.

    Attributes:
        stream_id: The reset stream.
        error_code: Application error code.
        final_size: Bytes the peer had sent on the stream.
    """

    __match_args__ = ("stream_id", "error_code", "final_size")

    def __init__(self, stream_id, error_code, final_size):
        self.stream_id = stream_id
        self.error_code = error_code
        self.final_size = final_size


cdef class StopSendingReceived(Event):
    """The peer asked this side to stop sending on a stream.

    The stream is reset with the same code.

    Attributes:
        stream_id: The stream.
        error_code: Application error code.
    """

    __match_args__ = ("stream_id", "error_code")

    def __init__(self, stream_id, error_code):
        self.stream_id = stream_id
        self.error_code = error_code


cdef class StreamClosed(Event):
    """Both directions of a stream finished and its state was released.

    Attributes:
        stream_id: The closed stream.
        receive_error_code: Code that cut the receiving direction short, or
            ``None`` if it ended normally.
        send_error_code: Code that cut the sending direction short, or
            ``None`` if it ended normally.
    """

    __match_args__ = ("stream_id", "receive_error_code", "send_error_code")

    def __init__(self, stream_id, receive_error_code, send_error_code):
        self.stream_id = stream_id
        self.receive_error_code = receive_error_code
        self.send_error_code = send_error_code


cdef class StreamsAvailable(Event):
    """The peer allows more streams to be opened.

    Attributes:
        bidirectional: Bidirectional streams that can be opened now.
        unidirectional: Unidirectional streams that can be opened now.
    """

    __match_args__ = ("bidirectional", "unidirectional")

    def __init__(self, bidirectional, unidirectional):
        self.bidirectional = bidirectional
        self.unidirectional = unidirectional


cdef class StreamWritable(Event):
    """A stream that reported back-pressure is down to its low mark or below.

    Attributes:
        stream_id: The stream.
    """

    __match_args__ = ("stream_id",)

    def __init__(self, stream_id):
        self.stream_id = stream_id


cdef class DatagramReceived(Event):
    """A DATAGRAM frame arrived.

    Attributes:
        data: Its payload.
        early: Whether it arrived in 0-RTT.
    """

    __match_args__ = ("data", "early")

    def __init__(self, data, early):
        self.data = data
        self.early = early


cdef class DatagramAcknowledged(Event):
    """The peer acknowledged a DATAGRAM.

    Attributes:
        datagram_id: ID returned by ``send_datagram()``.
    """

    __match_args__ = ("datagram_id",)

    def __init__(self, datagram_id):
        self.datagram_id = datagram_id


cdef class DatagramLost(Event):
    """A DATAGRAM was lost or dropped.

    Attributes:
        datagram_id: ID returned by ``send_datagram()``.
        sent: ``False`` if it was dropped before being sent: the queue was
            full, or the path's packet size shrank below the payload.
    """

    __match_args__ = ("datagram_id", "sent")

    def __init__(self, datagram_id, sent):
        self.datagram_id = datagram_id
        self.sent = sent


cdef class SessionTicketReceived(Event):
    """The server issued a ticket for resuming, and possibly 0-RTT.

    Attributes:
        ticket: Opaque value for ``Endpoint.connect(session_ticket=...)``.
    """

    __match_args__ = ("ticket",)

    def __init__(self, ticket):
        self.ticket = ticket


cdef class NewTokenReceived(Event):
    """The server issued an address validation token.

    Attributes:
        token: Opaque value for ``Endpoint.connect(token=...)``.
    """

    __match_args__ = ("token",)

    def __init__(self, token):
        self.token = token


cdef class EarlyDataRejected(Event):
    """The server rejected 0-RTT.

    Streams opened before the handshake are gone and their data must be resent.
    """

    __match_args__ = ()


cdef class ClientHelloReceived(Event):
    """A server paused its handshake to let the application pick a certificate.

    Sent when the server ``TLSContext`` has ``defer_certificate_selection``
    enabled. The handshake continues after ``Connection.select_tls_context()``.

    Attributes:
        server_name: Server name the client sent (SNI), or ``None``.
        alpn_protocols: Application protocols the client offered.
    """

    __match_args__ = ("server_name", "alpn_protocols")

    def __init__(self, server_name, alpn_protocols):
        self.server_name = server_name
        self.alpn_protocols = alpn_protocols


cdef class PeerCertificateReceived(Event):
    """The handshake paused for the application to verify the peer.

    Sent when the ``TLSContext`` has ``defer_peer_verification`` enabled.
    The handshake continues after ``Connection.verify_peer_certificate()``.

    Attributes:
        chain: DER certificates as the peer sent them, leaf first; not
            verified.
    """

    __match_args__ = ("chain",)

    def __init__(self, chain):
        self.chain = chain


cdef class PathValidationStarted(Event):
    """Validation of a new network path started.

    Attributes:
        local_addr: Local address of the path.
        remote_addr: Remote address of the path.
        preferred_address: Whether the path leads to the server's preferred address.
    """

    __match_args__ = ("local_addr", "remote_addr", "preferred_address")

    def __init__(self, local_addr, remote_addr, preferred_address):
        self.local_addr = local_addr
        self.remote_addr = remote_addr
        self.preferred_address = preferred_address


cdef class PathValidated(Event):
    """Validation of a network path finished.

    Attributes:
        local_addr: Local address of the path.
        remote_addr: Remote address of the path.
        preferred_address: Whether the path leads to the server's preferred address.
        success: Whether the peer answered on this path.
    """

    __match_args__ = ("local_addr", "remote_addr", "preferred_address", "success")

    def __init__(self, local_addr, remote_addr, preferred_address, success):
        self.local_addr = local_addr
        self.remote_addr = remote_addr
        self.preferred_address = preferred_address
        self.success = success


cdef class PathDegrading(Event):
    """Data in flight went unacknowledged for the configured probe timeouts.

    Reported once per stall to clients with
    ``TransportConfig.path_degrading_ptos`` set, after handshake
    confirmation; ``PathRecovered`` follows once the peer acknowledges again.
    The connection stays open: whether to stop opening streams on it is the
    caller's decision.
    """

    __match_args__ = ()


cdef class PathRecovered(Event):
    """The peer acknowledged data again after ``PathDegrading``."""

    __match_args__ = ()


cdef class ConnectionTerminated(Event):
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

    def __init__(self, reason, error_code, frame_type, reason_phrase, by_peer):
        self.reason = reason
        self.error_code = error_code
        self.frame_type = frame_type
        self.reason_phrase = reason_phrase
        self.by_peer = by_peer
