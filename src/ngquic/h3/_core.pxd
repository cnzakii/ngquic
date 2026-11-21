"""C-level declarations of the HTTP/3 core.

Each class is declared in the ``.pxd`` beside the ``.pxi`` that implements it,
as in ngquic._core.
"""

from libc.stdint cimport int64_t, uint64_t

from .._core cimport BaseConnection, _Stream
from .includes cimport nghttp3 as nh


cdef class _Body
cdef class H3Connection


include "_h3/connection.pxd"
