from libc.stdint cimport int64_t

from ..events cimport Event


cdef class RequestReceived(Event):
    cdef readonly int64_t stream_id
    cdef readonly tuple headers
    cdef readonly bint end_stream

cdef class ResponseReceived(Event):
    cdef readonly int64_t stream_id
    cdef readonly tuple headers
    cdef readonly bint end_stream

cdef class InformationalResponseReceived(Event):
    cdef readonly int64_t stream_id
    cdef readonly tuple headers

cdef class TrailersReceived(Event):
    cdef readonly int64_t stream_id
    cdef readonly tuple headers

cdef class DataReceived(Event):
    cdef readonly int64_t stream_id
    cdef readonly bytes data
    cdef readonly bint end_stream

cdef class DatagramReceived(Event):
    cdef readonly int64_t stream_id
    cdef readonly bytes data

cdef class GoAwayReceived(Event):
    cdef readonly int64_t id

cdef class SettingsReceived(Event):
    cdef readonly object settings

cdef class OriginReceived(Event):
    cdef readonly tuple origins
