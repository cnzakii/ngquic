class QUICError(Exception):
    """Base class for errors raised by ngquic."""


class ConnectionStateError(QUICError):
    """The connection cannot perform the operation in its current state."""


class StreamLimitError(QUICError):
    """The peer allows no more streams of the requested type yet."""


class StreamStateError(QUICError):
    """The stream does not exist or cannot perform the operation."""


class DatagramError(QUICError):
    """The peer does not accept the DATAGRAM, or it is too large."""


class TLSError(QUICError, OSError):
    """TLS configuration failed, such as loading a certificate or key.

    An ``OSError``, as ``ssl.SSLError`` is, so code that catches ``OSError``
    around ``ssl`` file loading catches this too.
    """


class InternalError(QUICError):
    """ngtcp2 or AWS-LC failed in a way the caller cannot correct."""
