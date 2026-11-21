# Send buffers of streams. Implemented in stream.pxi.


cdef class _Stream:
    cdef int64_t stream_id
    cdef list chunks
    cdef Py_ssize_t head
    cdef Py_ssize_t cursor
    cdef Py_ssize_t cursor_pos
    cdef uint64_t head_offset
    cdef uint64_t acked
    cdef uint64_t sent
    cdef uint64_t end
    cdef bint fin_queued
    cdef bint fin_sent
    cdef bint send_closed
    cdef bint paused

    cdef inline bint pending(self):
        return self.cursor < len(self.chunks) or (self.fin_queued and not self.fin_sent)

    cdef inline uint64_t held(self):
        return self.end - self.acked

    cdef size_t vectors(self, ng.ngtcp2_vec *vecs, bint *covers_end)
    cdef void advance(self, size_t length)
    cdef void acknowledge(self, uint64_t length)
    cdef void abandon(self)


cdef class _ScheduledStream(_Stream):
    # Stream data ngtcp2 refused until the peer raises the stream's limit.
    cdef bint blocked
    # Linked into Connection's round-robin list of streams with data to send.
    cdef bint active
    cdef _ScheduledStream prev
    cdef _ScheduledStream next
