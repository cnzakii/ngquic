from enum import IntEnum


class H3ErrorCode(IntEnum):
    """HTTP/3 error codes, from the IANA "HTTP/3 Error Codes" registry.

    They close a connection, reset a stream or stop reading one. Error codes
    of the form ``0x1f * N + 0x21`` are reserved for greasing, and unknown
    codes are treated as ``H3_NO_ERROR`` (RFC 9114, section 9), so a
    received code may be a plain ``int`` outside this enum.

    See RFC 9114, section 8.1:
    https://www.rfc-editor.org/rfc/rfc9114.html#section-8.1
    RFC 9204, section 6:
    https://www.rfc-editor.org/rfc/rfc9204.html#section-6
    RFC 9297, section 5.2:
    https://www.rfc-editor.org/rfc/rfc9297.html#section-5.2

    Attributes:
        H3_NO_ERROR: No error: the connection or stream needs to be closed,
            but there is no error to signal.
        H3_GENERAL_PROTOCOL_ERROR: The peer violated protocol requirements
            in a way that does not match a more specific error code, or
            the endpoint declines to use the more specific one.
        H3_INTERNAL_ERROR: An internal error occurred in the HTTP stack.
        H3_STREAM_CREATION_ERROR: The peer created a stream that the
            endpoint will not accept.
        H3_CLOSED_CRITICAL_STREAM: A stream required by the HTTP/3
            connection was closed or reset.
        H3_FRAME_UNEXPECTED: A frame was received that is not permitted in
            the current state or on the current stream.
        H3_FRAME_ERROR: A frame failed to satisfy layout requirements or
            had an invalid size.
        H3_EXCESSIVE_LOAD: The peer exhibits a behavior that might be
            generating excessive load.
        H3_ID_ERROR: A stream ID or push ID was used incorrectly, such as
            exceeding a limit, reducing a limit, or being reused.
        H3_SETTINGS_ERROR: The payload of a SETTINGS frame has an error.
        H3_MISSING_SETTINGS: No SETTINGS frame was received at the
            beginning of the control stream.
        H3_REQUEST_REJECTED: A server rejected a request without performing
            any application processing; the client may retry it.
        H3_REQUEST_CANCELLED: The request or its response is cancelled.
        H3_REQUEST_INCOMPLETE: The client's stream terminated without
            containing a fully formed request.
        H3_MESSAGE_ERROR: An HTTP message was malformed and cannot be
            processed.
        H3_CONNECT_ERROR: The TCP connection established in response to a
            CONNECT request was reset or abnormally closed.
        H3_VERSION_FALLBACK: The requested operation cannot be served over
            HTTP/3; the peer should retry over HTTP/1.1.
        QPACK_DECOMPRESSION_FAILED: The decoder failed to interpret an
            encoded field section and cannot continue decoding it.
        QPACK_ENCODER_STREAM_ERROR: The decoder failed to interpret an
            encoder instruction received on the encoder stream.
        QPACK_DECODER_STREAM_ERROR: The encoder failed to interpret a
            decoder instruction received on the decoder stream.
        H3_DATAGRAM_ERROR: A datagram or Capsule Protocol parse error; also
            aborts a request that has no semantics for HTTP datagrams.
    """

    # RFC 9114
    H3_NO_ERROR = 0x0100
    H3_GENERAL_PROTOCOL_ERROR = 0x0101
    H3_INTERNAL_ERROR = 0x0102
    H3_STREAM_CREATION_ERROR = 0x0103
    H3_CLOSED_CRITICAL_STREAM = 0x0104
    H3_FRAME_UNEXPECTED = 0x0105
    H3_FRAME_ERROR = 0x0106
    H3_EXCESSIVE_LOAD = 0x0107
    H3_ID_ERROR = 0x0108
    H3_SETTINGS_ERROR = 0x0109
    H3_MISSING_SETTINGS = 0x010A
    H3_REQUEST_REJECTED = 0x010B
    H3_REQUEST_CANCELLED = 0x010C
    H3_REQUEST_INCOMPLETE = 0x010D
    H3_MESSAGE_ERROR = 0x010E
    H3_CONNECT_ERROR = 0x010F
    H3_VERSION_FALLBACK = 0x0110
    # RFC 9204
    QPACK_DECOMPRESSION_FAILED = 0x0200
    QPACK_ENCODER_STREAM_ERROR = 0x0201
    QPACK_DECODER_STREAM_ERROR = 0x0202
    # RFC 9297
    H3_DATAGRAM_ERROR = 0x33
