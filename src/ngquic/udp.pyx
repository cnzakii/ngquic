# cython: embedsignature=True, freethreading_compatible=True, language_level=3

from cpython.buffer cimport (
    PyBUF_CONTIG_RO,
    Py_buffer,
    PyBuffer_Release,
    PyObject_GetBuffer,
)
from cpython.bytes cimport PyBytes_FromStringAndSize
from cpython.mem cimport PyMem_RawFree, PyMem_RawMalloc
from libc.stdint cimport uint8_t, uint16_t

from .includes cimport ngtcp2 as ng
from ._core cimport _AddressCache, _timestamp, _to_sockaddr, Endpoint

import errno
import os
import socket


cdef extern from "udp.h" nogil:
    int UDP_BATCH
    int UDP_SLOT
    int UDP_MAX_SEGMENTS
    int UDP_MAX_PAYLOAD

    ctypedef struct udp_addr:
        ng.ngtcp2_sockaddr_union addr
        ng.ngtcp2_socklen len

    ctypedef struct udp_state:
        bint gso

    ctypedef struct udp_message:
        udp_addr remote
        udp_addr local
        const unsigned char *data
        size_t length
        uint16_t segment_size
        uint8_t ecn

    ctypedef struct udp_received:
        udp_addr remote
        udp_addr local
        unsigned char *data
        size_t length
        size_t stride
        uint8_t ecn

    ctypedef struct udp_batch:
        unsigned char *buffers
        udp_received received[8]  # UDP_BATCH

    int udp_configure(int fd, bint connected, udp_state *state)
    bint udp_same_address(const udp_addr *a, const udp_addr *b)
    int udp_send(udp_state *state, int fd, const udp_message *message)
    int udp_receive(udp_state *state, udp_batch *batch, int fd)
    bint udp_would_block(int error)


# A cache key no address equals, None included.
cdef object _NO_ADDRESS = object()


cdef class ReceivedDatagram:
    cdef readonly bytes data
    cdef readonly object remote_addr
    cdef readonly object local_addr
    cdef readonly int ecn

    __match_args__ = ("data", "remote_addr")

    def __repr__(self):
        return (
            f"ReceivedDatagram(size={len(self.data)}, "
            f"remote_addr={self.remote_addr!r}, local_addr={self.local_addr!r}, "
            f"ecn={self.ecn})"
        )


cdef class UDPSocket:
    cdef object _sock
    cdef udp_state _state
    cdef udp_batch *_batch
    # The connected peer, for the check in send().
    cdef object _peer
    cdef udp_addr _peer_native
    # Addresses of the last send, kept native with the tuples they came from.
    cdef udp_message _message
    cdef object _remote_key
    cdef object _local_key
    # Tuples of the last addresses received.
    cdef _AddressCache _senders
    cdef _AddressCache _destinations

    def __cinit__(self):
        self._batch = NULL
        self._remote_key = _NO_ADDRESS
        self._senders = _AddressCache()
        self._destinations = _AddressCache()

    def __init__(self, sock):
        cdef int rv

        if not isinstance(sock, socket.socket) or sock.type != socket.SOCK_DGRAM:
            raise TypeError("sock must be a datagram socket")
        if sock.family not in (socket.AF_INET, socket.AF_INET6):
            raise TypeError("sock must be an AF_INET or AF_INET6 socket")
        try:
            self._peer = sock.getpeername()
        except OSError as error:
            if error.errno != errno.ENOTCONN:
                raise
        else:
            _to_sockaddr(self._peer, &self._peer_native.addr, &self._peer_native.len)
        sock.setblocking(False)
        rv = udp_configure(sock.fileno(), self._peer is not None, &self._state)
        if rv != 0:
            raise OSError(-rv, os.strerror(-rv))
        self._sock = sock

    def __dealloc__(self):
        if self._batch != NULL:
            PyMem_RawFree(self._batch.buffers)
            PyMem_RawFree(self._batch)

    # ---- properties

    @property
    def gso(self):
        return self._state.gso

    # ---- methods

    def fileno(self):
        return self._sock.fileno()

    def send(self, transmit):
        cdef Py_buffer view
        cdef int rv
        cdef int fd = self._sock.fileno()
        cdef object remote_addr = transmit.remote_addr
        cdef object local_addr = transmit.local_addr
        cdef Py_ssize_t segment_size = transmit.segment_size
        cdef int ecn = transmit.ecn

        if not 0 <= segment_size <= 0xFFFF:
            raise ValueError("segment_size must be between 0 and 65535")
        if not 0 <= ecn <= 3:
            raise ValueError("ecn must be between 0 and 3")
        if remote_addr is not self._remote_key and remote_addr != self._remote_key:
            # Cleared first: a rejected address leaves the native one half written.
            self._remote_key = _NO_ADDRESS
            _to_sockaddr(
                remote_addr, &self._message.remote.addr, &self._message.remote.len,
            )
            if self._peer is not None and not udp_same_address(
                &self._message.remote, &self._peer_native,
            ):
                raise ValueError(
                    f"remote_addr must be the connected peer {self._peer!r}, "
                    f"not {remote_addr!r}"
                )
            self._remote_key = remote_addr
        if local_addr is None or self._peer is not None:
            self._message.local.len = 0
            self._local_key = None
        elif local_addr is not self._local_key and local_addr != self._local_key:
            self._local_key = _NO_ADDRESS
            _to_sockaddr(
                local_addr, &self._message.local.addr, &self._message.local.len,
            )
            self._local_key = local_addr

        PyObject_GetBuffer(transmit.data, &view, PyBUF_CONTIG_RO)
        try:
            if view.len > UDP_MAX_PAYLOAD or (
                segment_size and view.len > segment_size * UDP_MAX_SEGMENTS
            ):
                raise ValueError(
                    "data must hold at most 64 datagrams and 65507 bytes"
                )
            self._message.data = <const unsigned char *>view.buf
            self._message.length = view.len
            self._message.segment_size = <uint16_t>segment_size
            self._message.ecn = <uint8_t>ecn
            with nogil:
                rv = udp_send(&self._state, fd, &self._message)
        finally:
            self._message.data = NULL
            PyBuffer_Release(&view)
        if rv != 0:
            # OSError picks the subclass: BlockingIOError for EAGAIN.
            raise OSError(-rv, os.strerror(-rv))

    def receive(self):
        cdef int count = self._read()
        cdef int index
        cdef size_t offset, size
        cdef udp_received *received
        cdef ng.ngtcp2_addr remote, local
        cdef ReceivedDatagram datagram
        cdef list result = []

        for index in range(count):
            received = &self._batch.received[index]
            remote_addr, local_addr = self._addresses(received, &remote, &local)
            offset = 0
            while True:
                size = min(received.stride, received.length - offset)
                datagram = ReceivedDatagram.__new__(ReceivedDatagram)
                datagram.data = PyBytes_FromStringAndSize(
                    <const char *>received.data + offset, size,
                )
                datagram.remote_addr = remote_addr
                datagram.local_addr = local_addr
                datagram.ecn = received.ecn
                result.append(datagram)
                offset += size
                if offset >= received.length:
                    break
        return result

    def receive_into(self, Endpoint endpoint not None, double now):
        cdef ng.ngtcp2_tstamp ts = _timestamp(now)
        cdef int count = self._read()
        cdef int index
        cdef size_t offset, size
        cdef udp_received *received
        cdef ng.ngtcp2_addr remote, local
        cdef dict ready = {}

        for index in range(count):
            received = &self._batch.received[index]
            remote_addr, local_addr = self._addresses(received, &remote, &local)
            offset = 0
            while True:
                size = min(received.stride, received.length - offset)
                result = endpoint._receive(
                    received.data + offset, size, &remote, remote_addr,
                    NULL if local_addr is None else &local, local_addr,
                    received.ecn, ts,
                )
                if result is not None:
                    ready[result] = None
                offset += size
                if offset >= received.length:
                    break
        return list(ready)

    # ---- private

    cdef int _read(self) except -1:
        """Read into the batch; how many reads it holds."""
        cdef int fd = self._sock.fileno()
        cdef int count

        if self._batch == NULL:
            self._allocate()
        with nogil:
            count = udp_receive(&self._state, self._batch, fd)
        if count >= 0:
            return count
        if udp_would_block(-count):
            return 0
        raise OSError(-count, os.strerror(-count))

    cdef int _allocate(self) except -1:
        cdef udp_batch *batch = <udp_batch *>PyMem_RawMalloc(sizeof(udp_batch))

        if batch == NULL:
            raise MemoryError()
        batch.buffers = <unsigned char *>PyMem_RawMalloc(<size_t>UDP_BATCH * UDP_SLOT)
        if batch.buffers == NULL:
            PyMem_RawFree(batch)
            raise MemoryError()
        self._batch = batch

    cdef tuple _addresses(
        self, udp_received *received, ng.ngtcp2_addr *remote, ng.ngtcp2_addr *local,
    ):
        """Point ``remote`` and ``local`` at a read's addresses; their tuples,
        ``None`` for a destination the system did not report."""
        remote.addr = &received.remote.addr.sa
        remote.addrlen = received.remote.len
        local.addr = &received.local.addr.sa
        local.addrlen = received.local.len
        return (
            self._senders.get(remote),
            self._destinations.get(local) if local.addrlen else None,
        )
