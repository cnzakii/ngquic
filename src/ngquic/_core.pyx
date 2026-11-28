# cython: embedsignature=True, freethreading_compatible=True, language_level=3

cimport cython
from cpython.buffer cimport (
    PyBUF_CONTIG_RO,
    Py_buffer,
    PyBuffer_Release,
    PyObject_GetBuffer,
)
from cpython.bytes cimport (
    PyBytes_AS_STRING,
    PyBytes_CheckExact,
    PyBytes_FromStringAndSize,
    PyBytes_GET_SIZE,
)
from cpython.mem cimport (
    PyMem_RawCalloc,
    PyMem_RawFree,
    PyMem_RawMalloc,
    PyMem_RawRealloc,
)
from cpython.object cimport PyObject
from libc.stdint cimport int64_t, uint8_t, uint16_t, uint32_t, uint64_t
from libc.math cimport INFINITY, nextafter
from libc.string cimport memcmp, memcpy, memset

import os
import sys
import warnings
from weakref import WeakValueDictionary
from ssl import (
    CERT_NONE,
    CERT_OPTIONAL,
    CERT_REQUIRED,
    Purpose,
    VerifyMode,
    get_default_verify_paths,
)
from collections import deque

from .includes cimport ngtcp2 as ng
from .events cimport (
    ConnectionTerminated,
    DatagramAcknowledged,
    DatagramLost,
    DatagramReceived,
    ClientHelloReceived,
    EarlyDataRejected,
    HandshakeCompleted,
    HandshakeConfirmed,
    NewTokenReceived,
    PathDegrading,
    PathRecovered,
    PathValidated,
    PathValidationStarted,
    PeerCertificateReceived,
    SessionTicketReceived,
    StopSendingReceived,
    StreamClosed,
    StreamDataReceived,
    StreamReset,
    StreamsAvailable,
    StreamWritable,
)

from .config import EndpointConfig, TransportConfig
from .enums import (
    CloseReason,
    ConnectionState,
    CongestionControl,
    ErrorCode,
    Role,
    Version,
)
from .exceptions import (
    ConnectionStateError,
    DatagramError,
    InternalError,
    StreamLimitError,
    StreamStateError,
    TLSError,
)
from .types import ConnectionStats, PreferredAddress, TransportParameters


cdef extern from "Python.h":
    # Raw forms let output be written in place and trimmed without a copy.
    PyObject *_new_bytes "PyBytes_FromStringAndSize"(
        const char *, Py_ssize_t
    ) except NULL
    int _PyBytes_Resize(PyObject **, Py_ssize_t) except -1
    char *_bytes_buffer "PyBytes_AS_STRING"(PyObject *)
    void Py_DECREF(PyObject *)


DEF _MAX_VECS = 16
# Linux UDP_SEGMENT accepts at most 64 segments (older kernels) in one send,
# whose payload is at most an IPv4 UDP datagram's (65535 - 20 - 8).
DEF _MAX_GSO_SEGMENTS = 64
DEF _MAX_GSO_BYTES = 65507
# Bytes a DATAGRAM frame and its 1-RTT packet need beside the payload: short
# header with the longest connection ID and packet number, AEAD tag, frame
# type and a 4-byte length.
DEF _DATAGRAM_OVERHEAD = 1 + 20 + 4 + 16 + 1 + 4
DEF _MAX_REASON_LENGTH = 1024


# Why a handshake waits for the application.
cdef enum:
    _PAUSE_NONE
    _PAUSE_SELECT
    _PAUSE_VERIFY
DEF _TICKET_FORMAT = 1
DEF _MAX_EARLY_PARAMS = 256
# Datagrams held for one undecided attempt: its first flight and 0-RTT.
DEF _MAX_HELD_DATAGRAMS = 16

cdef uint64_t _MAX_VARINT = (<uint64_t>1 << 62) - 1
cdef uint64_t _NO_EXPIRY = <uint64_t>-1
cdef double _NANOSECONDS = 1e9

_DEFAULT_TRANSPORT = TransportConfig()
_DEFAULT_ENDPOINT = EndpointConfig()
_ERROR_CODES = {code.value: code for code in ErrorCode}


def ngtcp2_version():
    return ng.ngtcp2_version(0).version_str.decode()


def tls_version():
    return ng.OpenSSL_version(0).decode()


include "_quic/convert.pxi"
include "_quic/tls.pxi"
include "_quic/stream.pxi"
include "_quic/transmit.pxi"
include "_quic/endpoint.pxi"
include "_quic/base.pxi"
include "_quic/connection.pxi"
include "_quic/callbacks.pxi"
