# TLS configuration shared by connections. Implemented in tls.pxi.


cdef class TLSContext:
    cdef ng.SSL_CTX *_ctx
    cdef readonly object role
    cdef bint _server
    cdef bytes _alpn
    cdef object _verify_mode
    cdef bint _check_hostname
    cdef object _keylog_filename
    cdef bint _early_data
    cdef bint _defer_selection
    cdef bint _defer_verification

    cdef int _add_pem(self, bytes data) except -1
    cdef int _add_der(self, bytes data) except -1
