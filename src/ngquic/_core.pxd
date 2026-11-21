"""C-level interface of the QUIC core, for protocol layers such as ngquic.h3.

A layer subclasses ``BaseConnection`` and overrides its stream protocol hooks;
it reaches ngtcp2 only through ``BaseConnection`` methods, since the native
libraries live inside this module. Each class is declared in the ``.pxd``
beside the ``.pxi`` that implements it.
"""

from libc.stdint cimport int64_t, uint8_t, uint16_t, uint32_t, uint64_t

from .includes cimport ngtcp2 as ng


cdef enum:
    # Versions an endpoint prefers or accepts, at most.
    _MAX_VERSIONS = 8
    # enums.ConnectionState in C for hot-path checks; BaseConnection.state maps
    # them back by value, so the lifecycle tests catch a mismatch.
    _HANDSHAKING = 0
    _ESTABLISHED = 1
    _CLOSING = 2
    _DRAINING = 3
    _CLOSED = 4


cdef class _AddressCache
cdef class TLSContext
cdef class Transmit
cdef class _Stream
cdef class _ScheduledStream
cdef class Endpoint
cdef class Incoming
cdef class BaseConnection
cdef class Connection


include "_quic/convert.pxd"
include "_quic/tls.pxd"
include "_quic/stream.pxd"
include "_quic/transmit.pxd"
include "_quic/endpoint.pxd"
include "_quic/base.pxd"
include "_quic/connection.pxd"
