# cython: embedsignature=True, freethreading_compatible=True, language_level=3
"""HTTP/3 connections: nghttp3 driven by BaseConnection's stream protocol hooks.

Only nghttp3 is linked here; QUIC operations go through BaseConnection
methods because ngtcp2 and AWS-LC live inside ngquic._core.
"""

from cpython.buffer cimport (
    PyBUF_CONTIG_RO,
    Py_buffer,
    PyBuffer_Release,
    PyObject_GetBuffer,
)
from cpython.bytes cimport (
    PyBytes_AS_STRING,
    PyBytes_Check,
    PyBytes_CheckExact,
    PyBytes_FromStringAndSize,
    PyBytes_GET_SIZE,
)
from libc.stdint cimport SIZE_MAX, int32_t, int64_t, uint8_t, uint32_t, uint64_t
from libc.stdlib cimport free, malloc
from libc.string cimport memcpy, memset

from ..includes cimport ngtcp2 as ng
from .._core cimport (
    _CLOSING,
    _native_error,
    _owned_bytes,
    _random_bytes,
    _raw_calloc,
    _raw_free,
    _raw_malloc,
    _raw_realloc,
    _stream_id,
    _uint,
)
from .includes cimport nghttp3 as nh
from .events cimport (
    DatagramReceived,
    DataReceived,
    GoAwayReceived,
    InformationalResponseReceived,
    OriginReceived,
    RequestReceived,
    ResponseReceived,
    SettingsReceived,
    TrailersReceived,
)

from ..exceptions import (
    ConnectionStateError,
    DatagramError,
    InternalError,
    StreamLimitError,
    StreamStateError,
)
from .config import H3Config
from .enums import H3ErrorCode
from .types import H3Settings, NeverIndexedHeader, Priority


DEF _MAX_VECS = 16

cdef uint64_t _MAX_VARINT = (<uint64_t>1 << 62) - 1
cdef nh.nghttp3_mem _MEM = nh.nghttp3_mem(
    user_data=NULL, malloc=_raw_malloc, free=_raw_free, calloc=_raw_calloc,
    realloc=_raw_realloc,
)
# Request stream IDs divided by four, as HTTP/3 datagrams carry them.
cdef uint64_t _MAX_QUARTER_STREAM_ID = (<uint64_t>1 << 60) - 1


def nghttp3_version():
    """Return the version of the bundled nghttp3 library."""
    return nh.nghttp3_version(0).version_str.decode()


def parse_priority(field_value):
    """Parse a Priority field value (RFC 9218), such as ``b"u=1, i"``.

    Parameters the value leaves out keep their defaults.

    Raises:
        ValueError: If the value is not a valid Priority field.
    """
    cdef bytes value = _owned_bytes(field_value)
    cdef object default = Priority()
    cdef nh.nghttp3_pri pri

    pri.urgency = default.urgency
    pri.inc = default.incremental
    if nh.nghttp3_pri_parse_priority(
        &pri, <const uint8_t *>PyBytes_AS_STRING(value), PyBytes_GET_SIZE(value),
    ) != 0:
        raise ValueError(f"invalid Priority field value {value!r}")
    return Priority(pri.urgency, bool(pri.inc))


include "_h3/connection.pxi"
include "_h3/callbacks.pxi"
