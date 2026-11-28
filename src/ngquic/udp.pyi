"""Batched UDP I/O on a socket the caller owns, for Linux and macOS.

The protocol stays sans-I/O; this module makes the system calls an event
loop's datagram transport cannot: segmented sends (GSO), coalesced and
batched receives (GRO, ``recvmmsg``), ECN and source address control
messages.
"""

import socket
import sys
from typing import Protocol, final, type_check_only

from typing_extensions import Buffer

from ._core import BaseConnection, Endpoint, Incoming
from .types import Address

# The module is built only where its socket calls are implemented.
if sys.platform != "win32":
    @type_check_only
    class _Transmit(Protocol):
        @property
        def data(self) -> Buffer: ...
        @property
        def remote_addr(self) -> Address: ...
        @property
        def local_addr(self) -> Address | None: ...
        @property
        def segment_size(self) -> int: ...
        @property
        def ecn(self) -> int: ...

    @final
    class ReceivedDatagram:
        """A UDP datagram ``UDPSocket.receive()`` read.

        Its fields are the arguments of ``Endpoint.receive_datagram()``.
        """

        __match_args__ = ("data", "remote_addr")
        @property
        def data(self) -> bytes: ...
        @property
        def remote_addr(self) -> Address: ...
        @property
        def local_addr(self) -> Address | None: ...
        @property
        def ecn(self) -> int: ...

    @final
    class UDPSocket:
        """Batched sends and receives for QUIC on a UDP socket the caller owns.

        The caller binds, waits on and closes ``sock``: wait for it to become
        readable or writable with ``loop.add_reader()`` and ``loop.add_writer()``
        (asyncio, uvloop), ``wait_readable()`` (trio, anyio) or ``selectors``.

        Wrapping makes the socket non-blocking, turns off IP fragmentation
        (RFC 9000, section 14) and turns on ECN, destination address reports
        and, on Linux, GSO and GRO; leave its options to this object from then
        on. Further receive metadata, such as timestamps, takes room that reads
        may then lack, and such reads are dropped. A socket connected before
        wrapping sends only to its peer; later ``connect()`` calls are not
        followed.

        Not safe to use from several threads at once.

        Args:
            sock: An ``AF_INET`` or ``AF_INET6`` datagram socket.

        Raises:
            TypeError: If ``sock`` is not such a socket.
            OSError: If the system refuses a required socket option.
        """

        def __init__(self, sock: socket.socket) -> None: ...
        @property
        def gso(self) -> bool:
            """Whether the kernel splits segmented sends.

            Pass it to ``datagrams_to_send(gso=...)``. It turns ``False`` for good
            if the network card refuses a segmented send.
            """

        def fileno(self) -> int:
            """Return the socket's file descriptor.

            ``selectors`` and ``loop.add_reader()`` take this object as they take
            the socket.
            """

        def send(self, transmit: _Transmit) -> None:
            """Send a ``Transmit`` from ``datagrams_to_send()``.

            Its datagrams go out in one segmented send where ``gso`` allows,
            otherwise one by one. ``local_addr`` chooses the source address of a
            socket bound to ``0.0.0.0`` or ``::``; a connected socket ignores it.
            If the system refuses a datagram after the first, that one and the
            rest are dropped, as QUIC recovers lost packets.

            Args:
                transmit: A ``Transmit``, or an object with the same attributes:
                    ``data`` holding at most 64 datagrams and 65,507 bytes.

            Raises:
                BlockingIOError: If the socket buffer is full; nothing was sent.
                    Send it again once the socket is writable.
                ValueError: If ``remote_addr`` is not the connected peer, or
                    ``data``, ``segment_size`` or ``ecn`` is out of range.
                OSError: If the system refuses the first datagram, such as
                    ``EMSGSIZE`` for a path MTU probe the interface cannot carry,
                    or an ICMP error reported on a connected socket.
            """

        def receive(self) -> list[ReceivedDatagram]:
            """Read the datagrams waiting.

            One call makes at most 8 reads, so that a busy socket lets the event
            loop serve others; with GRO one read holds up to 64 datagrams.

            Returns:
                The datagrams in arrival order; empty when none was waiting.

            Raises:
                OSError: If the first read fails, such as with an ICMP error on
                    a connected socket.
            """

        def receive_into(
            self, endpoint: Endpoint, now: float
        ) -> list[BaseConnection | Incoming]:
            """Read the datagrams waiting into ``endpoint``.

            The batched ``endpoint.receive_datagram()``, without a Python object
            per datagram; reads as ``receive()`` does.

            Args:
                endpoint: The endpoint the socket serves.
                now: Current monotonic time in seconds.

            Returns:
                Each ``Connection`` that took datagrams, to read its ``events()``
                and send, and each ``Incoming`` attempt, to accept or refuse,
                once, in the order their first datagram arrived; empty when none
                was waiting.

            Raises:
                OSError: If the first read fails.
                MemoryError: The datagrams not yet processed are lost, which QUIC
                    recovers from.
            """
