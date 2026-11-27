"""UDPSocket on real loopback sockets."""

import errno
import select
import selectors
import socket
import sys
import time
from types import SimpleNamespace

import pytest

from ngquic import (
    ConnectionState,
    Endpoint,
    Incoming,
    InternalError,
    StreamDataReceived,
    TransportConfig,
)

if sys.platform not in ("linux", "darwin"):
    pytest.skip("ngquic.udp is built on Linux and macOS", allow_module_level=True)

from ngquic.udp import UDPSocket

LOOPBACK_V4 = "127.0.0.1"
LOOPBACK_V6 = "::1"
MAPPED_V4 = "::ffff:127.0.0.1"
# socket.IP_PKTINFO from Python 3.13 on.
_LINUX_IP_PKTINFO = 8


def _bind(host, *scope):
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_DGRAM)
    try:
        sock.bind((host, 0, *scope))
    except OSError:
        sock.close()
        raise
    return sock


def _bind_loopback():
    try:
        return _bind(LOOPBACK_V6)
    except OSError:
        return _bind(LOOPBACK_V4)


def _dual_stack():
    sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    sock.bind(("::", 0))
    return sock


def _transmit(data, remote_addr, *, local_addr=None, segment_size=0, ecn=0):
    return SimpleNamespace(
        data=data,
        remote_addr=remote_addr,
        local_addr=local_addr,
        segment_size=segment_size,
        ecn=ecn,
    )


def _arrival(recv, destination):
    """The ``local_addr`` a datagram sent to ``destination`` reports at ``recv``."""
    host, port = destination[:2]
    if recv.family == socket.AF_INET:
        return (host.removeprefix("::ffff:"), port)
    if ":" not in host:
        host = "::ffff:" + host
    return (host, port, 0, 0)


def _receive(receiver, recv, count):
    """Read ``count`` datagrams; macOS queues loopback ones a moment late."""
    received = []
    while len(received) < count:
        assert select.select([recv], [], [], 1.0)[0], "datagram did not arrive"
        received += receiver.receive()
    return received


def _send_recv(send, recv, data, destination, **transmit):
    """Send ``data``; check each datagram arrives whole, in order, with its metadata."""
    sender, receiver = UDPSocket(send), UDPSocket(recv)
    sent = _transmit(data, destination, **transmit)
    size = sent.segment_size or len(data) or 1
    metadata = (send.getsockname()[1], _arrival(recv, destination), sent.ecn)
    expected = [
        (data[at : at + size], *metadata) for at in range(0, len(data), size)
    ] or [(b"", *metadata)]

    sender.send(sent)
    received = _receive(receiver, recv, len(expected))

    assert [
        (datagram.data, datagram.remote_addr[1], datagram.local_addr, datagram.ecn)
        for datagram in received
    ] == expected


def test_a_datagram_round_trips():
    with _bind_loopback() as send, _bind_loopback() as recv:
        _send_recv(send, recv, b"hello", recv.getsockname())


def _send_each(sender, receiver, recv, data, **transmit):
    for each in data:
        sender.send(_transmit(each, recv.getsockname(), ecn=1, **transmit))
        [datagram] = _receive(receiver, recv, 1)
        assert (datagram.data, datagram.ecn) == (each, 1)


@pytest.mark.parametrize(
    ("host", "elsewhere"),
    [
        (LOOPBACK_V4, "192.0.2.1"),
        (LOOPBACK_V6, "2001:db8::1"),
        (LOOPBACK_V4, "not an address"),
    ],
)
def test_a_connected_socket_sends_to_its_peer_from_its_own_address(host, elsewhere):
    with _bind(host) as send, _bind(host) as recv:
        send.connect(recv.getsockname())
        sender, receiver = UDPSocket(send), UDPSocket(recv)
        _send_each(
            sender, receiver, recv, [b"first", b"second"], local_addr=(elsewhere, 0)
        )


def test_a_connected_socket_refuses_another_destination():
    with (
        _bind(LOOPBACK_V4) as send,
        _bind(LOOPBACK_V4) as recv,
        _bind(LOOPBACK_V4) as other,
    ):
        send.connect(recv.getsockname())
        sender, receiver = UDPSocket(send), UDPSocket(recv)
        _send_each(sender, receiver, recv, [b"before"])

        with pytest.raises(ValueError, match="connected peer"):
            sender.send(_transmit(b"lost", other.getsockname()))

        _send_each(sender, receiver, recv, [b"after"])
        assert not select.select([other], [], [], 0.05)[0]


@pytest.mark.parametrize("family", [socket.AF_INET6, socket.AF_INET])
def test_an_unbound_socket_can_be_configured(family):
    with socket.socket(family, socket.SOCK_DGRAM) as sock:
        UDPSocket(sock)


def test_a_datagram_leaves_from_the_given_source_ip():
    with _bind_loopback() as send, _bind_loopback() as recv:
        _send_recv(
            send, recv, b"hello", recv.getsockname(), local_addr=send.getsockname()
        )


def _loopback_link_local():
    """The index of a loopback interface with the fe80::1 address, if any."""
    for name in ("lo0", "lo"):
        try:
            index = socket.if_nametoindex(name)
            _bind("fe80::1", 0, index).close()
        except OSError:
            continue
        return index
    return None


def test_a_link_local_destination_reports_its_interface():
    index = _loopback_link_local()
    if index is None:
        pytest.skip("loopback has no link-local address")
    with _bind("fe80::1", 0, index) as send, _bind("fe80::1", 0, index) as recv:
        sender, receiver = UDPSocket(send), UDPSocket(recv)
        sender.send(
            _transmit(b"hello", recv.getsockname(), local_addr=send.getsockname())
        )

        [datagram] = _receive(receiver, recv, 1)
        expected = ("fe80::1", recv.getsockname()[1], 0, index)

    assert datagram.local_addr == expected


@pytest.mark.parametrize("ecn", [1, 2], ids=["ect1", "ect0"])
@pytest.mark.parametrize("host", [LOOPBACK_V4, LOOPBACK_V6], ids=["ipv4", "ipv6"])
def test_ecn_bits_reach_the_receiver(host, ecn):
    with _bind(host) as send, _bind(host) as recv:
        _send_recv(send, recv, b"hello", recv.getsockname(), ecn=ecn)


@pytest.mark.parametrize("ecn", [1, 2], ids=["ect1", "ect0"])
@pytest.mark.parametrize("host", [LOOPBACK_V4, LOOPBACK_V6], ids=["ipv4", "ipv6"])
def test_ecn_bits_reach_a_dual_stack_receiver(host, ecn):
    with _dual_stack() as recv, _bind(host) as send:
        _send_recv(send, recv, b"hello", (host, recv.getsockname()[1]), ecn=ecn)


@pytest.mark.parametrize("ecn", [1, 2], ids=["ect1", "ect0"])
def test_ecn_bits_reach_an_ipv4_mapped_destination(ecn):
    with _dual_stack() as send, _bind(LOOPBACK_V4) as recv:
        _send_recv(send, recv, b"hello", (MAPPED_V4, recv.getsockname()[1]), ecn=ecn)


def test_a_dual_stack_socket_sends_from_its_own_any_address_to_ipv4():
    with _dual_stack() as send, _bind(LOOPBACK_V4) as recv:
        _send_recv(
            send,
            recv,
            b"hello",
            (MAPPED_V4, recv.getsockname()[1]),
            local_addr=send.getsockname(),
            ecn=2,
        )


def test_a_socket_bound_to_an_ipv4_mapped_address_reports_ipv6_addresses():
    with _bind(MAPPED_V4) as recv, _bind(LOOPBACK_V4) as send:
        receiver, port = UDPSocket(recv), recv.getsockname()[1]
        send.sendto(b"hello", (LOOPBACK_V4, port))
        [datagram] = _receive(receiver, recv, 1)
        receiver.send(_transmit(b"reply", datagram.remote_addr))

        assert (datagram.remote_addr, datagram.local_addr) == (
            (MAPPED_V4, send.getsockname()[1], 0, 0),
            (MAPPED_V4, port, 0, 0),
        )
        assert select.select([send], [], [], 1.0)[0]
        assert send.recv(16) == b"reply"


@pytest.mark.skipif(
    sys.platform != "linux", reason="Linux reports IP_PKTINFO on an IPv6 socket"
)
def test_a_dual_stack_socket_reports_an_ipv6_destination_with_ip_pktinfo_on():
    with _dual_stack() as recv, _bind(LOOPBACK_V4) as send:
        receiver, port = UDPSocket(recv), recv.getsockname()[1]
        recv.setsockopt(socket.IPPROTO_IP, _LINUX_IP_PKTINFO, 1)
        send.sendto(b"hello", (LOOPBACK_V4, port))
        [datagram] = _receive(receiver, recv, 1)

    assert datagram.local_addr == (MAPPED_V4, port, 0, 0)


@pytest.mark.skipif(
    sys.platform != "darwin", reason="only macOS refuses this send with EINVAL"
)
def test_a_send_refused_for_another_reason_keeps_ecn_on():
    with _dual_stack() as send, _bind(LOOPBACK_V4) as recv:
        with pytest.raises(OSError) as raised:
            # An IPv4 address on an IPv6 socket, refused with or without IP_TOS.
            UDPSocket(send).send(_transmit(b"refused", recv.getsockname()))
        assert raised.value.errno == errno.EINVAL

        _send_recv(send, recv, b"hello", (MAPPED_V4, recv.getsockname()[1]), ecn=2)


@pytest.mark.parametrize(
    ("data", "segment_size"),
    [
        (bytes(range(128)) * 63 + b"tail", 128),
        (bytes(range(128)) * 64, 128),
        (b"".join(bytes([index]) * 1200 for index in range(54)), 1200),
    ],
    ids=["64", "64-full", "64800-bytes"],
)
def test_a_segmented_send_arrives_as_separate_datagrams(data, segment_size):
    with _bind_loopback() as send, _bind_loopback() as recv:
        _send_recv(send, recv, data, recv.getsockname(), segment_size=segment_size)


def test_an_empty_datagram_is_sent_and_received():
    with _bind(LOOPBACK_V4) as send, _bind(LOOPBACK_V4) as recv:
        _send_recv(send, recv, b"", recv.getsockname())


def test_a_large_single_datagram_is_not_segmented():
    with _bind(LOOPBACK_V4) as send, _bind(LOOPBACK_V4) as recv:
        _send_recv(send, recv, b"\xcd" * 2048, recv.getsockname())


def test_selectors_wait_on_the_udp_socket_itself():
    with (
        _bind_loopback() as send,
        _bind_loopback() as recv,
        selectors.DefaultSelector() as sel,
    ):
        receiver = UDPSocket(recv)
        sel.register(receiver, selectors.EVENT_READ)
        UDPSocket(send).send(_transmit(b"hello", recv.getsockname()))

        ready = sel.select(timeout=1.0)

    assert [key.fileobj for key, _ in ready] == [receiver]


def test_receive_returns_nothing_when_no_datagram_waits():
    with _bind_loopback() as sock:
        assert UDPSocket(sock).receive() == []


def test_receive_returns_waiting_datagrams_in_order():
    with _bind_loopback() as send, _bind_loopback() as recv:
        sender, receiver = UDPSocket(send), UDPSocket(recv)
        for index in range(5):
            sender.send(_transmit(bytes([index]), recv.getsockname()))

        received = _receive(receiver, recv, 5)

    assert [datagram.data for datagram in received] == [bytes([i]) for i in range(5)]


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS SO_SNDBUF bug")
def test_send_buffer_stays_above_the_largest_datagram():
    with _bind_loopback() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 9216)
        UDPSocket(sock)

        size = sock.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF)

    assert size >= 65535 + 128


@pytest.mark.parametrize(
    ("options", "error", "match"),
    [
        ({"segment_size": 65536}, ValueError, "segment_size"),
        ({"ecn": 4}, ValueError, "ecn"),
        ({"data": b"x" * 65 * 100, "segment_size": 100}, ValueError, "64 datagrams"),
        ({"data": b"x" * 55 * 1200, "segment_size": 1200}, ValueError, "65507"),
        ({"local_addr": ("localhost", 0)}, ValueError, "IPv4 or IPv6"),
        ({"local_addr": ("::1", 0, 0, 2**32)}, ValueError, "scope_id"),
        ({"remote_addr": "::1"}, TypeError, "address must be"),
        ({"remote_addr": (b"::1", 1)}, TypeError, "host must be a str"),
        ({"remote_addr": ("::1", 65536)}, ValueError, "port"),
    ],
    ids=[
        "segment-size",
        "ecn",
        "segments",
        "bytes",
        "local-host",
        "local-scope",
        "remote-type",
        "remote-host-type",
        "remote-port",
    ],
)
def test_send_rejects_an_invalid_transmit(options, error, match):
    with _bind_loopback() as sock, pytest.raises(error, match=match):
        transmit = {"data": b"x", "remote_addr": sock.getsockname(), **options}
        UDPSocket(sock).send(_transmit(**transmit))


def test_a_refused_datagram_raises_the_system_error():
    with _bind(LOOPBACK_V4) as send, pytest.raises(PermissionError):
        # Broadcast without SO_BROADCAST.
        UDPSocket(send).send(_transmit(b"x", ("255.255.255.255", 9)))


def test_receive_into_rejects_an_invalid_time():
    with _bind(LOOPBACK_V4) as sock, pytest.raises(ValueError, match="now"):
        UDPSocket(sock).receive_into(Endpoint(sock.getsockname()), -1.0)


@pytest.mark.parametrize("call", ["receive", "receive_into"])
def test_an_icmp_error_on_a_connected_socket_surfaces_in_the_read(call):
    with _bind(LOOPBACK_V4) as closed:
        address = closed.getsockname()
    with _bind(LOOPBACK_V4) as sock:
        sock.connect(address)
        io = UDPSocket(sock)
        io.send(_transmit(b"x", address))
        assert select.select([sock], [], [], 1.0)[0], "no ICMP error arrived"

        with pytest.raises(ConnectionRefusedError):
            if call == "receive":
                io.receive()
            else:
                io.receive_into(Endpoint(sock.getsockname()), time.monotonic())


def test_a_received_datagram_prints_its_metadata():
    with _bind(LOOPBACK_V4) as send, _bind(LOOPBACK_V4) as recv:
        sender, receiver = UDPSocket(send), UDPSocket(recv)
        sender.send(_transmit(b"hello", recv.getsockname(), ecn=2))

        [datagram] = _receive(receiver, recv, 1)
        expected = (
            f"ReceivedDatagram(size=5, remote_addr={send.getsockname()!r}, "
            f"local_addr={recv.getsockname()!r}, ecn=2)"
        )

    assert repr(datagram) == expected


@pytest.mark.parametrize(
    ("family", "kind", "match"),
    [
        (socket.AF_INET, socket.SOCK_STREAM, "datagram socket"),
        (socket.AF_UNIX, socket.SOCK_DGRAM, "AF_INET"),
    ],
    ids=["stream", "unix"],
)
def test_a_socket_other_than_udp_is_rejected(family, kind, match):
    with socket.socket(family, kind) as sock, pytest.raises(TypeError, match=match):
        UDPSocket(sock)


def test_a_closed_socket_raises_the_system_error():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.close()

    with pytest.raises(OSError) as raised:
        UDPSocket(sock)
    assert raised.value.errno == errno.EBADF


def test_a_connection_transmit_goes_out_as_returned(client_tls):
    with _bind(LOOPBACK_V4) as send, _bind(LOOPBACK_V4) as recv:
        sender = UDPSocket(send)
        client = Endpoint(send.getsockname()).connect(
            recv.getsockname(), 1.0, tls=client_tls, server_name="localhost"
        )
        transmits = client.datagrams_to_send(1.0, gso=sender.gso)
        expected = [
            transmit.data[at : at + transmit.segment_size]
            for transmit in transmits
            for at in range(0, len(transmit.data), transmit.segment_size)
        ]

        for transmit in transmits:
            sender.send(transmit)
        received = []
        while len(received) < len(expected) and select.select([recv], [], [], 1.0)[0]:
            received.append(recv.recv(65535))

    assert received == expected


def _unknown_version_initial(scid):
    """A full-sized long-header datagram of a version no endpoint speaks."""
    header = b"\xc0" + bytes.fromhex("1a2a3a4a") + b"\x08" + bytes(8) + b"\x08" + scid
    return header + bytes(1200 - len(header))


def test_receive_into_handles_each_datagram_of_a_segmented_read():
    data = b"".join(_unknown_version_initial(bytes([index]) * 8) for index in range(20))
    with _bind(LOOPBACK_V4) as send, _bind(LOOPBACK_V4) as recv:
        endpoint = Endpoint(recv.getsockname())
        UDPSocket(send).send(_transmit(data, recv.getsockname(), segment_size=1200))
        receiver, replies = UDPSocket(recv), []
        while len(replies) < 20 and select.select([recv], [], [], 1.0)[0]:
            receiver.receive_into(endpoint, time.monotonic())
            replies += endpoint.datagrams_to_send()

    # Each Version Negotiation reply names the datagram's source connection ID.
    assert [reply.data[6:14] for reply in replies] == [
        bytes([index]) * 8 for index in range(20)
    ]


class _Link:
    """A client and a server endpoint on loopback sockets, on the real clock."""

    def __init__(self, server_tls, client_tls, host=LOOPBACK_V4, client_host=None):
        self.client_sock, self.server_sock = _bind(client_host or host), _bind(host)
        self.client_io = UDPSocket(self.client_sock)
        self.server_io = UDPSocket(self.server_sock)
        self.client_endpoint = Endpoint(self.client_sock.getsockname())
        self.server_endpoint = Endpoint(self.server_sock.getsockname())
        self.server_tls, self.client_tls = server_tls, client_tls
        self.clients, self.servers = [], []

    def connect(self, **options):
        client = self.client_endpoint.connect(
            self.server_sock.getsockname(),
            time.monotonic(),
            tls=self.client_tls,
            server_name="localhost",
            **options,
        )
        self.clients.append(client)
        return client

    def flush(self, connections=None):
        now = time.monotonic()
        for connection in (
            self.clients + self.servers if connections is None else connections
        ):
            if (timer := connection.get_timer()) is not None and timer <= now:
                connection.handle_timer(now)
            io = self.client_io if connection in self.clients else self.server_io
            for transmit in connection.datagrams_to_send(now, gso=io.gso):
                io.send(transmit)

    def serve(self):
        """Feed the server side: accept attempts and drain events."""
        for item in self.server_io.receive_into(self.server_endpoint, time.monotonic()):
            if isinstance(item, Incoming):
                self.servers.append(item.accept(tls=self.server_tls))
        for server in self.servers:
            server.events()

    def run(self, until, timeout=2.0):
        deadline = time.monotonic() + timeout
        while not until():
            assert time.monotonic() < deadline, "the link did not settle"
            self.flush()
            select.select([self.client_sock, self.server_sock], [], [], 0.01)
            self.serve()
            for client in self.clients:
                self.client_io.receive_into(self.client_endpoint, time.monotonic())
                client.events()
        self.flush()

    def close(self):
        self.client_sock.close()
        self.server_sock.close()


@pytest.fixture
def link(server_tls, client_tls):
    link = _Link(server_tls, client_tls)
    yield link
    link.close()


def _confirmed(link, **options):
    client = link.connect(**options)
    link.run(
        lambda: (
            len(link.servers) == len(link.clients)
            and client.state is ConnectionState.ESTABLISHED
        )
    )
    link.run(
        lambda: all(
            server.state is ConnectionState.ESTABLISHED for server in link.servers
        )
    )
    return client


def _receive_all(link, size):
    """Call receive_into until ``size`` bytes of stream data reached the clients."""
    calls, received = [], 0
    deadline = time.monotonic() + 2.0
    while received < size:
        assert time.monotonic() < deadline, "datagrams did not arrive"
        link.flush()
        select.select([link.client_sock], [], [], 0.01)
        calls.append(
            link.client_io.receive_into(link.client_endpoint, time.monotonic())
        )
        for item in calls[-1]:
            received += sum(
                len(event.data)
                for event in item.events()
                if isinstance(event, StreamDataReceived)
            )
    return calls


@pytest.mark.parametrize("host", [LOOPBACK_V4, LOOPBACK_V6])
def test_receive_into_returns_an_incoming_attempt(server_tls, client_tls, host):
    link = _Link(server_tls, client_tls, host)
    try:
        link.connect()
        link.flush()
        select.select([link.server_sock], [], [], 1.0)

        (incoming,) = link.server_io.receive_into(
            link.server_endpoint, time.monotonic()
        )
        client_addr = link.client_sock.getsockname()
    finally:
        link.close()

    assert isinstance(incoming, Incoming)
    assert incoming.remote_addr[:2] == client_addr[:2]


def _until_quiet(sock, read):
    """Call ``read()`` while datagrams keep arriving; what the calls returned."""
    results = []
    while select.select([sock], [], [], 0.2)[0]:
        results += read()
    return results


def test_a_retry_from_receive_into_validates_through_receive(server_tls, client_tls):
    link = _Link(server_tls, client_tls)
    server = link.server_endpoint
    try:
        link.connect()
        link.flush()
        [incoming] = _until_quiet(
            link.server_sock,
            lambda: link.server_io.receive_into(server, time.monotonic()),
        )
        assert isinstance(incoming, Incoming)
        incoming.retry()
        for transmit in server.datagrams_to_send():
            link.server_io.send(transmit)
        _until_quiet(
            link.client_sock,
            lambda: link.client_io.receive_into(link.client_endpoint, time.monotonic()),
        )
        link.flush()

        results = [
            server.receive_datagram(
                datagram.data,
                datagram.remote_addr,
                time.monotonic(),
                local_addr=datagram.local_addr,
            )
            for datagram in _until_quiet(link.server_sock, link.server_io.receive)
        ]
    finally:
        link.close()

    [validated] = [result for result in results if isinstance(result, Incoming)]
    assert validated.remote_address_validated


@pytest.mark.parametrize(
    ("host", "client_host"), [(LOOPBACK_V4, "0.0.0.0"), (LOOPBACK_V6, "::")]
)
def test_a_client_on_a_socket_bound_to_any_address_names_a_specific_one(
    server_tls, client_tls, host, client_host
):
    link = _Link(server_tls, client_tls, host, client_host)
    try:
        with pytest.raises(ValueError, match="specific address"):
            link.connect()
        _confirmed(link, local_addr=(host, link.client_sock.getsockname()[1]))
        (server,) = link.servers
        stream_id = server.open_stream(unidirectional=True)
        server.send_stream_data(stream_id, b"x" * 100, end_stream=True)
        link.flush()

        _receive_all(link, 100)
    finally:
        link.close()


def test_receive_into_returns_a_connection_once_however_many_datagrams_it_took(link):
    client = _confirmed(link)
    (server,) = link.servers
    stream_id = server.open_stream(unidirectional=True)
    for _ in range(5):
        server.send_stream_data(stream_id, b"x" * 100)
        link.flush()

    calls = _receive_all(link, 500)

    assert all(call == [client] for call in calls if call)


def test_a_failed_callback_surfaces_in_that_connections_events_only(link):
    failing = False

    def qlog(data, final):
        if failing:
            raise RuntimeError("disk full")

    broken = _confirmed(link, transport=TransportConfig(qlog=qlog))
    healthy = _confirmed(link)
    for server in link.servers:
        server.send_stream_data(server.open_stream(unidirectional=True), b"hello")
    link.flush()
    failing = True
    deadline = time.monotonic() + 2.0
    returned, received = set(), []

    while not (broken in returned and received) and time.monotonic() < deadline:
        # Pacing may hold the servers' datagrams until their timers; the
        # broken client must not write, which would raise on its own.
        link.flush(link.servers)
        select.select([link.client_sock], [], [], 0.01)
        for item in link.client_io.receive_into(link.client_endpoint, time.monotonic()):
            returned.add(item)
            if item is healthy:
                received += [
                    event.data
                    for event in healthy.events()
                    if isinstance(event, StreamDataReceived)
                ]

    assert broken in returned
    assert received == [b"hello"]
    with pytest.raises(InternalError, match="callback failed") as raised:
        broken.events()
    assert isinstance(raised.value.__cause__, RuntimeError)
    assert broken.state is ConnectionState.CLOSED
