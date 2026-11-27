# Conversions between Python values and ngtcp2 types. Implemented in convert.pxi.
# Those declared here are shared with the other native modules.


cdef class _AddressCache:
    cdef ng.ngtcp2_sockaddr_union native
    cdef ng.ngtcp2_socklen length
    cdef object value

    cdef object get(self, const ng.ngtcp2_addr *address)


cdef ng.ngtcp2_tstamp _timestamp(double now) except? 0
cdef uint64_t _uint(object value, str name, uint64_t maximum) except? 0
cdef int64_t _stream_id(object value) except -1
cdef bytes _owned_bytes(object data)
cdef int _to_sockaddr(
    object address, ng.ngtcp2_sockaddr_union *out, ng.ngtcp2_socklen *outlen,
) except -1
