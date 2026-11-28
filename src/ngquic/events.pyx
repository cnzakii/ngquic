# cython: embedsignature=True, freethreading_compatible=True, language_level=3


cdef class Event:
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
    __match_args__ = ("alpn_protocol", "session_resumed", "early_data_accepted")

    def __init__(self, alpn_protocol, session_resumed, early_data_accepted):
        self.alpn_protocol = alpn_protocol
        self.session_resumed = session_resumed
        self.early_data_accepted = early_data_accepted


cdef class HandshakeConfirmed(Event):
    __match_args__ = ()


cdef class StreamDataReceived(Event):
    __match_args__ = ("stream_id", "data", "end_stream", "early")

    def __init__(self, stream_id, data, end_stream, early):
        self.stream_id = stream_id
        self.data = data
        self.end_stream = end_stream
        self.early = early


cdef class StreamReset(Event):
    __match_args__ = ("stream_id", "error_code", "final_size")

    def __init__(self, stream_id, error_code, final_size):
        self.stream_id = stream_id
        self.error_code = error_code
        self.final_size = final_size


cdef class StopSendingReceived(Event):
    __match_args__ = ("stream_id", "error_code")

    def __init__(self, stream_id, error_code):
        self.stream_id = stream_id
        self.error_code = error_code


cdef class StreamClosed(Event):
    __match_args__ = ("stream_id", "receive_error_code", "send_error_code")

    def __init__(self, stream_id, receive_error_code, send_error_code):
        self.stream_id = stream_id
        self.receive_error_code = receive_error_code
        self.send_error_code = send_error_code


cdef class StreamsAvailable(Event):
    __match_args__ = ("bidirectional", "unidirectional")

    def __init__(self, bidirectional, unidirectional):
        self.bidirectional = bidirectional
        self.unidirectional = unidirectional


cdef class StreamWritable(Event):
    __match_args__ = ("stream_id",)

    def __init__(self, stream_id):
        self.stream_id = stream_id


cdef class DatagramReceived(Event):
    __match_args__ = ("data", "early")

    def __init__(self, data, early):
        self.data = data
        self.early = early


cdef class DatagramAcknowledged(Event):
    __match_args__ = ("datagram_id",)

    def __init__(self, datagram_id):
        self.datagram_id = datagram_id


cdef class DatagramLost(Event):
    __match_args__ = ("datagram_id", "sent")

    def __init__(self, datagram_id, sent):
        self.datagram_id = datagram_id
        self.sent = sent


cdef class SessionTicketReceived(Event):
    __match_args__ = ("ticket",)

    def __init__(self, ticket):
        self.ticket = ticket


cdef class NewTokenReceived(Event):
    __match_args__ = ("token",)

    def __init__(self, token):
        self.token = token


cdef class EarlyDataRejected(Event):
    __match_args__ = ()


cdef class ClientHelloReceived(Event):
    __match_args__ = ("server_name", "alpn_protocols")

    def __init__(self, server_name, alpn_protocols):
        self.server_name = server_name
        self.alpn_protocols = alpn_protocols


cdef class PeerCertificateReceived(Event):
    __match_args__ = ("chain",)

    def __init__(self, chain):
        self.chain = chain


cdef class PathValidationStarted(Event):
    __match_args__ = ("local_addr", "remote_addr", "preferred_address")

    def __init__(self, local_addr, remote_addr, preferred_address):
        self.local_addr = local_addr
        self.remote_addr = remote_addr
        self.preferred_address = preferred_address


cdef class PathValidated(Event):
    __match_args__ = ("local_addr", "remote_addr", "preferred_address", "success")

    def __init__(self, local_addr, remote_addr, preferred_address, success):
        self.local_addr = local_addr
        self.remote_addr = remote_addr
        self.preferred_address = preferred_address
        self.success = success


cdef class PathDegrading(Event):
    __match_args__ = ()


cdef class PathRecovered(Event):
    __match_args__ = ()


cdef class ConnectionTerminated(Event):
    __match_args__ = ("reason", "error_code", "frame_type", "reason_phrase", "by_peer")

    def __init__(self, reason, error_code, frame_type, reason_phrase, by_peer):
        self.reason = reason
        self.error_code = error_code
        self.frame_type = frame_type
        self.reason_phrase = reason_phrase
        self.by_peer = by_peer
