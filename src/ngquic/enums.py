from enum import Enum, IntEnum


class Role(Enum):
    """The local side of a TLS context.

    Attributes:
        CLIENT: Starts connections.
        SERVER: Accepts connections.
    """

    CLIENT = "client"
    SERVER = "server"


class Version(IntEnum):
    """QUIC versions ngtcp2 supports, from the IANA "QUIC Versions" registry.

    Version ``0x00000000`` is reserved for Version Negotiation packets and
    is not a version a connection uses.

    See RFC 9000, section 15:
    https://www.rfc-editor.org/rfc/rfc9000.html#section-15
    RFC 9369, section 3:
    https://www.rfc-editor.org/rfc/rfc9369.html#section-3

    Attributes:
        V1: QUIC version 1 (RFC 9000).
        V2: QUIC version 2 (RFC 9369): version 1 with different constants,
            to keep middleboxes from ossifying on version 1.
    """

    V1 = 0x00000001
    V2 = 0x6B3343CF


class CongestionControl(IntEnum):
    """Congestion control algorithms ngtcp2 implements (``ngtcp2_cc_algo``).

    See RFC 9002, section 7:
    https://www.rfc-editor.org/rfc/rfc9002.html#section-7

    Attributes:
        RENO: NewReno as RFC 9002 section 7 describes it for QUIC.
        CUBIC: CUBIC (RFC 9438); ngtcp2's default.
        BBR: BBR version 2, which models bandwidth and round-trip time
            instead of reacting to loss; not an RFC.
    """

    RENO = 0
    CUBIC = 1
    BBR = 2


class ConnectionState(IntEnum):
    """Lifecycle of a connection.

    Attributes:
        HANDSHAKING: The handshake has not completed.
        ESTABLISHED: The handshake has completed.
        CLOSING: This side closed the connection and answers late packets
            with its CONNECTION_CLOSE until the closing period ends.
        DRAINING: The peer closed the connection; nothing more is sent until
            the draining period ends.
        CLOSED: The connection holds no protocol state and needs no timer.
    """

    HANDSHAKING = 0
    ESTABLISHED = 1
    CLOSING = 2
    DRAINING = 3
    CLOSED = 4


class CloseReason(IntEnum):
    """Why a connection terminated: ``ConnectionTerminated.reason``.

    The ways a connection ends are those of RFC 9000, section 10:
    https://www.rfc-editor.org/rfc/rfc9000.html#section-10

    Attributes:
        TRANSPORT_ERROR: A CONNECTION_CLOSE frame with a transport error code.
        APPLICATION_ERROR: A CONNECTION_CLOSE frame with an application error
            code.
        IDLE_TIMEOUT: The idle timeout expired; nothing was sent (section
            10.1).
        HANDSHAKE_TIMEOUT: The handshake did not complete in time; a local
            limit, not a protocol state.
        STATELESS_RESET: The peer sent a stateless reset (section 10.3).
        VERSION_NEGOTIATION: The server offers no version this client
            supports (section 6).
    """

    TRANSPORT_ERROR = 0
    APPLICATION_ERROR = 1
    IDLE_TIMEOUT = 2
    HANDSHAKE_TIMEOUT = 3
    STATELESS_RESET = 4
    VERSION_NEGOTIATION = 5


class ErrorCode(IntEnum):
    """QUIC transport error codes, from the IANA registry of that name.

    They are carried in a CONNECTION_CLOSE frame of type 0x1c and apply to
    the whole connection. The multipath codes of RFC 10069 are left out:
    ngtcp2 does not implement multipath, so they are never negotiated.

    See RFC 9000, section 20.1:
    https://www.rfc-editor.org/rfc/rfc9000.html#section-20.1
    RFC 9368, section 10.2:
    https://www.rfc-editor.org/rfc/rfc9368.html#section-10.2

    Attributes:
        NO_ERROR: The connection is closed abruptly in the absence of any
            error.
        INTERNAL_ERROR: The endpoint encountered an internal error and
            cannot continue with the connection.
        CONNECTION_REFUSED: The server refused to accept a new connection.
        FLOW_CONTROL_ERROR: The endpoint received more data than it
            permitted in its advertised data limits.
        STREAM_LIMIT_ERROR: A frame named a stream identifier beyond the
            advertised stream limit for that stream type.
        STREAM_STATE_ERROR: A frame arrived for a stream that was not in a
            state permitting it.
        FINAL_SIZE_ERROR: Stream data exceeded the established final size,
            or a final size was lower than the data already received or
            differed from the one already established.
        FRAME_ENCODING_ERROR: A frame was badly formatted, such as one of
            unknown type.
        TRANSPORT_PARAMETER_ERROR: Transport parameters were badly
            formatted, invalid, missing a mandatory one, included a
            forbidden one, or otherwise in error.
        CONNECTION_ID_LIMIT_ERROR: The peer provided more connection IDs
            than the advertised ``active_connection_id_limit``.
        PROTOCOL_VIOLATION: A protocol compliance error not covered by a
            more specific code.
        INVALID_TOKEN: A server received a client Initial with an invalid
            Token field.
        APPLICATION_ERROR: The application or application protocol closed
            the connection.
        CRYPTO_BUFFER_EXCEEDED: More data arrived in CRYPTO frames than can
            be buffered.
        KEY_UPDATE_ERROR: The endpoint detected errors in performing key
            updates (RFC 9001, section 6).
        AEAD_LIMIT_REACHED: The confidentiality or integrity limit of the
            connection's AEAD algorithm was reached.
        NO_VIABLE_PATH: The network path cannot support QUIC, typically
            because its MTU is too small.
        VERSION_NEGOTIATION_ERROR: Compatible version negotiation failed
            (RFC 9368).
        CRYPTO_ERROR: The cryptographic handshake failed. The range
            ``0x0100``-``0x01ff`` carries a TLS alert as ``CRYPTO_ERROR +
            alert`` (RFC 9001, section 4.8); this member is its start.
    """

    NO_ERROR = 0x00
    INTERNAL_ERROR = 0x01
    CONNECTION_REFUSED = 0x02
    FLOW_CONTROL_ERROR = 0x03
    STREAM_LIMIT_ERROR = 0x04
    STREAM_STATE_ERROR = 0x05
    FINAL_SIZE_ERROR = 0x06
    FRAME_ENCODING_ERROR = 0x07
    TRANSPORT_PARAMETER_ERROR = 0x08
    CONNECTION_ID_LIMIT_ERROR = 0x09
    PROTOCOL_VIOLATION = 0x0A
    INVALID_TOKEN = 0x0B
    APPLICATION_ERROR = 0x0C
    CRYPTO_BUFFER_EXCEEDED = 0x0D
    KEY_UPDATE_ERROR = 0x0E
    AEAD_LIMIT_REACHED = 0x0F
    NO_VIABLE_PATH = 0x10
    VERSION_NEGOTIATION_ERROR = 0x11
    CRYPTO_ERROR = 0x0100
