import ssl
from collections.abc import Iterable
from os import PathLike
from typing import TypeAlias, final, overload

from typing_extensions import Buffer

from .config import EndpointConfig, TransportConfig
from .enums import ConnectionState, Role, Version
from .events import Event
from .h3._core import H3Connection
from .h3.config import H3Config
from .types import Address, ConnectionStats, TransportParameters

_Path: TypeAlias = str | bytes | PathLike[str] | PathLike[bytes]

def ngtcp2_version() -> str:
    """Return the version of the bundled ngtcp2 library."""

def tls_version() -> str:
    """Return the version of the bundled TLS library."""

@final
class TLSContext:
    """TLS 1.3 settings shared by many connections.

    Method names and meanings follow ``ssl.SSLContext``. Configure a context
    before handing it to connections; later changes reach new connections.

    Args:
        role: Whether the context starts or accepts connections.

    Raises:
        TypeError: If ``role`` is not a ``Role``.
        TLSError: If AWS-LC cannot create the context.
    """

    def __init__(self, role: Role) -> None: ...
    @property
    def role(self) -> Role: ...
    verify_mode: int
    """Whether and how the peer certificate is verified, as ``ssl.VerifyMode``."""

    check_hostname: bool
    """Whether clients match the server certificate against ``server_name``."""

    keylog_filename: _Path | None
    """File that receives TLS secrets in NSS key log format, or ``None``."""

    early_data: bool
    """Whether servers accept 0-RTT data from resumed clients."""

    num_tickets: int
    """Session tickets a server sends after each handshake, at most 16."""

    defer_certificate_selection: bool
    """Whether servers pause each handshake at ``ClientHelloReceived``.

    The application then picks the certificate, for example by server
    name, with ``Connection.select_tls_context()``.
    """

    defer_peer_verification: bool
    """Whether the application verifies peer certificates itself.

    Each handshake pauses at ``PeerCertificateReceived`` until
    ``Connection.verify_peer_certificate()``. This replaces the built-in
    chain and host name checks, so ``check_hostname`` must be off.
    """

    def load_cert_chain(
        self,
        certfile: _Path,
        keyfile: _Path | None = None,
        password: str | bytes | None = None,
    ) -> None:
        """Load this side's certificate chain and private key from PEM files.

        Args:
            certfile: Path of the certificate chain, leaf first.
            keyfile: Path of the private key; ``None`` reads it from
                ``certfile``.
            password: Password of an encrypted private key.

        Raises:
            TLSError: If a file cannot be read or the key does not match.
        """

    def load_verify_locations(
        self,
        cafile: _Path | None = None,
        capath: _Path | None = None,
        cadata: str | Buffer | None = None,
    ) -> None:
        """Trust the certificate authorities in a file, directory or buffer.

        Args:
            cafile: Path of concatenated PEM certificates.
            capath: Directory of hashed PEM certificates.
            cadata: PEM text, or DER bytes of one or more certificates.

        Raises:
            TypeError: If no source is given.
            TLSError: If a source cannot be read.
        """

    def load_default_certs(self, purpose: ssl.Purpose = ...) -> None:
        """Trust the system's certificate authorities, as ``ssl`` does.

        On Windows this loads the ``CA`` and ``ROOT`` system stores, keeping
        certificates trusted for ``purpose``; everywhere it then calls
        ``set_default_verify_paths()``.

        Args:
            purpose: ``ssl.Purpose.SERVER_AUTH`` to verify servers,
                ``ssl.Purpose.CLIENT_AUTH`` to verify clients.

        Raises:
            TypeError: If ``purpose`` is not an ``ssl.Purpose``.
        """

    def set_default_verify_paths(self) -> None:
        """Trust the certificate file and directory ``ssl`` trusts by default.

        These are ``SSL_CERT_FILE`` and ``SSL_CERT_DIR`` when set, otherwise
        the defaults of the OpenSSL Python was built with, as
        ``ssl.get_default_verify_paths()`` reports; missing ones are skipped.
        """

    def set_alpn_protocols(self, protocols: Iterable[str]) -> None:
        """Set application protocols, most preferred first.

        QUIC requires ALPN: a handshake fails unless both sides share one.

        Raises:
            ValueError: If a protocol is empty or longer than 255 bytes.
        """

    def set_groups(self, groups: Iterable[str]) -> None:
        """Set key exchange groups, such as ``["X25519MLKEM768", "X25519"]``.

        Raises:
            TLSError: If a group is unknown.
        """

@final
class Transmit:
    """UDP payloads ready to send to one address.

    ``data`` is one UDP payload, or with ``datagrams_to_send(gso=True)``
    several of ``segment_size`` bytes, the last one possibly shorter, to send
    as one GSO train.
    """

    __match_args__ = ("data", "remote_addr", "segment_size")
    @property
    def data(self) -> bytes: ...
    @property
    def remote_addr(self) -> Address: ...
    @property
    def local_addr(self) -> Address: ...
    @property
    def segment_size(self) -> int: ...
    @property
    def ecn(self) -> int: ...

@final
class Endpoint:
    """Routes datagrams of one local address to their connections.

    Both clients and servers use an endpoint. Drive an endpoint and all of its
    connections from one thread or task at a time.

    Args:
        local_addr: Address the datagrams arrive at and leave from, port
            included, such as the bound socket's ``getsockname()``.
        config: Endpoint behavior.

    Raises:
        TypeError: If an argument has the wrong type.
        ValueError: If ``local_addr`` or a configuration value is invalid.
    """

    def __init__(
        self, local_addr: Address, config: EndpointConfig | None = None
    ) -> None: ...
    @property
    def config(self) -> EndpointConfig: ...
    @property
    def local_addr(self) -> Address: ...
    @property
    def connections(self) -> int:
        """Number of connections that still hold protocol state."""

    @overload
    def connect(
        self,
        remote_addr: Address,
        now: float,
        *,
        tls: TLSContext,
        server_name: str | None = None,
        transport: TransportConfig | None = None,
        session_ticket: bytes | None = None,
        token: bytes | None = None,
        local_addr: Address | None = None,
        version: Version = ...,
        h3: None = None,
    ) -> Connection:
        """Start a client connection.

        The first flight is ready from ``Connection.datagrams_to_send()``.

        Args:
            remote_addr: Server address.
            now: Current monotonic time in seconds.
            tls: Client TLS context.
            server_name: Name sent as SNI and, with ``tls.check_hostname``,
                matched against the server certificate. An IP address is
                matched but not sent; other names are encoded with IDNA,
                as ``ssl`` encodes them, without a trailing dot.
            transport: Transport behavior.
            session_ticket: Ticket from ``SessionTicketReceived`` to resume,
                allowing 0-RTT streams before the handshake completes. Pass
                it only for the ``server_name`` it was received from:
                resumption skips the certificate check, as with ``ssl``.
            token: Token from ``NewTokenReceived`` that lets the server skip
                address validation.
            local_addr: Local address of the path; defaults to the
                endpoint's. A specific address, such as ``getsockname()``
                of a socket connected to ``remote_addr``.
            version: QUIC version of the first flight.
            h3: ``H3Config`` to speak HTTP/3 on this connection; the result
                is then an ``H3Connection``. ``tls`` must offer ``"h3"``.

        Returns:
            A ``Connection``, or an ``H3Connection`` when ``h3`` is given.

        Raises:
            TypeError: If an argument has the wrong type.
            ValueError: If an argument or configuration value is invalid.
        """

    @overload
    def connect(
        self,
        remote_addr: Address,
        now: float,
        *,
        tls: TLSContext,
        server_name: str | None = None,
        transport: TransportConfig | None = None,
        session_ticket: bytes | None = None,
        token: bytes | None = None,
        local_addr: Address | None = None,
        version: Version = ...,
        h3: H3Config,
    ) -> H3Connection: ...
    def receive_datagram(
        self,
        data: Buffer,
        remote_addr: Address,
        now: float,
        *,
        local_addr: Address | None = None,
        ecn: int = 0,
    ) -> BaseConnection | Incoming | None:
        """Process a UDP payload that arrived from ``remote_addr``.

        Args:
            data: One UDP payload; split a GRO batch before passing it in.
            remote_addr: Address it came from.
            now: Current monotonic time in seconds.
            local_addr: Address it arrived at; defaults to the endpoint's.
            ecn: ECN bits from the IP header.

        Returns:
            The connection that consumed it, whose next ``events()`` raises
            ``InternalError`` if a protocol callback failed and dropped it;
            an ``Incoming`` connection attempt to accept or refuse; or
            ``None`` if it was dropped, answered statelessly, or belongs to
            an ``Incoming`` already returned and not yet decided (a
            retransmitted Initial or 0-RTT), which then processes it on
            ``accept()``.
        """

    def datagrams_to_send(self) -> list[Transmit]:
        """Return stateless replies: Version Negotiation, Retry, refusals and resets."""

@final
class Incoming:
    """A client's first datagram for a connection that does not exist yet.

    Decide once: ``accept()``, ``retry()``, ``refuse()`` or ``ignore()``.

    Attributes:
        remote_addr: Client address.
        local_addr: Local address it arrived at.
        version: QUIC version the client chose.
        remote_address_validated: Whether a valid Retry or NEW_TOKEN token
            proves the client owns ``remote_addr``.
    """

    @property
    def remote_addr(self) -> Address: ...
    @property
    def local_addr(self) -> Address: ...
    @property
    def version(self) -> Version: ...
    @property
    def remote_address_validated(self) -> bool: ...
    @overload
    def accept(
        self,
        *,
        tls: TLSContext,
        transport: TransportConfig | None = None,
        h3: None = None,
    ) -> Connection | None:
        """Create the server connection and process the client's datagrams.

        Args:
            tls: Server TLS context.
            transport: Transport behavior.
            h3: ``H3Config`` to speak HTTP/3 on this connection; the result
                is then an ``H3Connection``. ``tls`` must select ``"h3"``.

        Returns:
            The connection, or ``None`` if ngtcp2 dropped the attempt or
            required address validation, in which case a Retry was queued
            on the endpoint.

        Raises:
            ValueError: If ``tls`` is not a server context or a configuration
                value is invalid.
            ConnectionStateError: If this attempt was already decided.
        """

    @overload
    def accept(
        self,
        *,
        tls: TLSContext,
        transport: TransportConfig | None = None,
        h3: H3Config,
    ) -> H3Connection | None: ...
    def retry(self) -> None:
        """Ask the client to prove its address with a Retry packet."""

    def refuse(self, error_code: int = ...) -> None:
        """Close the attempt with a CONNECTION_CLOSE carrying ``error_code``."""

    def ignore(self) -> None:
        """Drop the attempt without answering."""

class BaseConnection:
    """What every QUIC connection offers, whatever runs on its streams.

    Connections come from ``Endpoint.connect()`` and ``Incoming.accept()``:
    ``Connection`` exposes raw streams, ``H3Connection`` HTTP/3. After feeding
    input, read ``events()``, then send ``datagrams_to_send()`` and re-arm the
    timer from ``get_timer()``. Peer misbehavior never raises; it ends the
    connection with ``ConnectionTerminated``.
    """

    @property
    def is_client(self) -> bool: ...
    @property
    def server_name(self) -> str | None: ...
    def events(self) -> list[Event]:
        """Return and clear the events produced since the last call.

        Returns:
            Events in protocol order.

        Raises:
            Exception: Once, what failed while the endpoint delivered a
                datagram to this connection: ``InternalError`` when a
                protocol callback failed, which dropped the connection.
        """

    def datagrams_to_send(
        self, now: float, *, max_datagrams: int = 64, gso: bool = False
    ) -> list[Transmit]:
        """Return UDP payloads to send now.

        Pacing may hold packets back; ``get_timer()`` covers the moment they
        become due.

        Args:
            now: Current monotonic time in seconds.
            max_datagrams: Upper bound of UDP payloads returned.
            gso: Whether a ``Transmit`` may carry several payloads, for a
                socket that sends them with UDP generic segmentation offload
                (Linux ``UDP_SEGMENT``); by default each carries exactly one.

        Returns:
            Transmits in sending order.

        Raises:
            ValueError: If ``max_datagrams`` is not positive.
        """

    def get_timer(self) -> float | None:
        """Return when ``handle_timer()`` must run, on the clock of ``now``.

        Returns:
            Monotonic time in seconds, or ``None`` when no timer is needed.
        """

    def handle_timer(self, now: float) -> None:
        """Run due timers: loss recovery, acknowledgements, idle and closing.

        A call before ``get_timer()`` is due does nothing. Event loops may fire
        a timer slightly early (asyncio by up to its clock resolution), so a
        timer callback passes ``max(deadline, now)`` with the ``deadline`` it
        was armed for. Never a fresh ``get_timer()``: input since arming can
        move the deadline later, and a ``now`` past the real time expires
        timers early and stays, since time never goes back here.
        """

    def close(
        self, error_code: int = 0, reason: bytes = b"", *, application: bool = True
    ) -> None:
        """Close the connection immediately with CONNECTION_CLOSE.

        QUIC has no graceful close at the transport layer; finish streams
        first or use the application protocol's own shutdown. The packet is
        produced by the next ``datagrams_to_send()``. Closing a connection
        that is already closing does nothing.

        Args:
            error_code: Application error code, or a transport ``ErrorCode``
                when ``application`` is ``False``.
            reason: Short diagnostic reason phrase.
            application: Whether ``error_code`` is an application code.
        """

    def migrate(
        self, local_addr: Address, now: float, *, validate: bool = True
    ) -> None:
        """Move a client connection to a new local address.

        Datagrams the new socket receives are then passed with its address
        as ``local_addr``.

        Args:
            local_addr: New local address, a specific one with its port;
                the remote address is unchanged.
            now: Current monotonic time in seconds.
            validate: Whether to validate the new path before using it.

        Raises:
            ConnectionStateError: If migration is not possible now: before
                the handshake is confirmed, when the peer disabled active
                migration, or without a spare connection ID.
            ValueError: If ``local_addr`` is the current local address, an
                unspecified one such as ``0.0.0.0``, or names no port.
        """

    def update_key(self, now: float) -> None:
        """Start a key update; ngtcp2 also updates keys itself before AEAD limits."""

    def select_tls_context(self, tls: TLSContext, now: float) -> None:
        """Continue a handshake paused at ``ClientHelloReceived``.

        ``tls`` supplies the certificate, ALPN choice and 0-RTT setting.
        Client certificate checks and session tickets stay with the context
        the connection was accepted with.

        Args:
            tls: Server context to complete the handshake with.
            now: Current monotonic time in seconds.

        Raises:
            ConnectionStateError: If no certificate selection is pending.
            ValueError: If ``tls`` is not a server context.
        """

    def verify_peer_certificate(self, accepted: bool, now: float) -> None:
        """Continue a handshake paused at ``PeerCertificateReceived``.

        Args:
            accepted: Whether the peer's certificate chain is trusted; a
                rejection fails the handshake with a bad_certificate alert.
            now: Current monotonic time in seconds.

        Raises:
            ConnectionStateError: If no peer verification is pending.
        """

    @property
    def state(self) -> ConnectionState:
        """Lifecycle state as ``ConnectionState``."""

    @property
    def local_addr(self) -> Address:
        """Local address of the current path."""

    @property
    def remote_addr(self) -> Address:
        """Remote address of the current path."""

    @property
    def version(self) -> Version | None:
        """Negotiated QUIC version; ``None`` before it is known and after close."""

    @property
    def alpn_protocol(self) -> str | None:
        """Negotiated application protocol, or ``None`` before the handshake."""

    @property
    def peer_certificate(self) -> bytes | None:
        """DER certificate the peer presented, or ``None``."""

    @property
    def peer_transport_parameters(self) -> TransportParameters | None:
        """``TransportParameters`` the peer announced; ``None`` until they arrive."""

    @property
    def pto(self) -> float:
        """Current probe timeout in seconds."""

    @property
    def stats(self) -> ConnectionStats:
        """Round-trip, congestion and traffic statistics."""

@final
class Connection(BaseConnection):
    """A QUIC connection whose application uses streams and DATAGRAMs directly."""

    def open_stream(self, *, unidirectional: bool = False) -> int:
        """Open a stream; before the handshake only after 0-RTT resumption.

        Returns:
            The stream ID.

        Raises:
            StreamLimitError: If the peer allows no more streams of this type
                yet; ``StreamsAvailable`` reports new credit.
            ConnectionStateError: If the connection is closing or closed.
        """

    def send_stream_data(
        self, stream_id: int, data: Buffer, *, end_stream: bool = False
    ) -> bool:
        """Queue data on a stream.

        ``bytes`` are held without copying until the peer acknowledges them;
        other buffers are copied once.

        Args:
            stream_id: The stream.
            data: Bytes-like data, possibly empty.
            end_stream: Whether this finishes the sending direction.

        Returns:
            ``False`` once the stream holds more than
            ``stream_write_buffer_high`` bytes; wait for ``StreamWritable``
            before queuing more.

        Raises:
            StreamStateError: If the stream does not exist or its sending
                direction finished.
            ConnectionStateError: If the connection is closing or closed.
        """

    def end_stream(self, stream_id: int) -> None:
        """Finish the sending direction of a stream after its queued data."""

    def reset_stream(self, stream_id: int, error_code: int) -> None:
        """Abandon sending on a stream with RESET_STREAM; unsent data is dropped."""

    def stop_sending(self, stream_id: int, error_code: int) -> None:
        """Ask the peer to stop sending on a stream with STOP_SENDING."""

    def consume_received_data(self, stream_id: int, amount: int) -> None:
        """Return flow-control credit for data the application processed.

        Only needed when ``TransportConfig.auto_flow_control`` is ``False``.
        """

    def queued_size(self, stream_id: int | None = None) -> int:
        """Return bytes held for sending: unsent plus unacknowledged."""

    def send_capacity(self, stream_id: int | None = None) -> int:
        """Return bytes the peer's flow control allows on a stream or the connection."""

    def stream_loss_count(self, stream_id: int) -> int:
        """Return how many packets carrying this stream were declared lost."""

    def send_datagram(self, data: Buffer) -> int:
        """Queue an unreliable DATAGRAM frame.

        Returns:
            An ID reported by ``DatagramAcknowledged`` or ``DatagramLost``.

        Raises:
            DatagramError: If the peer does not accept DATAGRAM frames or
                ``data`` exceeds ``max_datagram_size``.
            ConnectionStateError: If the connection is closing or closed.
        """

    @property
    def max_datagram_size(self) -> int | None:
        """Largest DATAGRAM payload sendable now; ``None`` if the peer accepts none."""

    @property
    def bidi_streams_available(self) -> int:
        """Bidirectional streams that can be opened now."""

    @property
    def uni_streams_available(self) -> int:
        """Unidirectional streams that can be opened now."""
