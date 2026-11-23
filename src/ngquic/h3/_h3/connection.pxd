# HTTP/3 connections and the message bodies nghttp3 sends. Implemented in
# connection.pxi.


cdef class _Body(_Stream):
    # A trailer section follows the body instead of FIN.
    cdef bint trailers


cdef class H3Connection(BaseConnection):
    cdef nh.nghttp3_conn *_h3
    cdef object _config
    # nghttp3 reads the ORIGIN payload until the connection is freed.
    cdef bytes _origin_payload
    # Fields of header sections still arriving, by stream.
    cdef dict _receiving
    # Streams whose last header section already reported end_stream.
    cdef set _finished
    # Request streams whose receiving side is open: HTTP/3 datagrams for any
    # other stream are dropped (RFC 9297 2.1).
    cdef set _readable
    # Streams with data parked in nghttp3 until connection credit returns.
    cdef set _credit_blocked
    # Connection credit when the last of them was parked: only more unparks.
    cdef uint64_t _parked_left
    # Client-initiated bidirectional streams the server allows in total.
    cdef uint64_t _max_requests
    # Origins of an ORIGIN frame still arriving.
    cdef list _origins
    # The nghttp3 error a header callback found, which nghttp3 does not check:
    # a Host that differs from :authority (RFC 9114 4.3.1), or a section past
    # max_field_section_size (4.2.2). 0 for none.
    cdef int _violation
    # max_field_section_size, which nghttp3 leaves to the application; 0 for
    # none. The bytes of each section still arriving count against it.
    cdef uint64_t _field_section_limit
    cdef dict _field_section_size
    # The peer sent GOAWAY; nghttp3 then refuses every new request.
    cdef bint _goaway_received
    # This side sent GOAWAY, after which a shutdown notice is refused.
    cdef bint _goaway_sent
    cdef readonly object remote_settings

    # ---- internals
    cdef int _start(self) except -1
    cdef int _start_early(self) except -1
    cdef void _drop_h3(self)
    cdef int _h3_failed(self, int rv) except -1
    cdef int64_t _h3_datagram_limit(self, int64_t stream_id)
    cdef int _require_ready(self) except -1
    cdef int _require_server(self, str message) except -1
    cdef _Body _body(self, int64_t stream_id)
    cdef int _emit_end(self, int64_t stream_id) except -1
