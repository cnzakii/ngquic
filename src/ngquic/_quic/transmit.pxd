# UDP payloads a connection or endpoint hands back. Implemented in transmit.pxi.


cdef class Transmit:
    cdef readonly bytes data
    cdef readonly object remote_addr
    cdef readonly object local_addr
    cdef readonly Py_ssize_t segment_size
    cdef readonly int ecn


cdef Transmit _transmit(
    bytes data, object remote, object local, Py_ssize_t segment, int ecn,
)
