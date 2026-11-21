cdef class _Stream:
    """Data a stream holds until the peer acknowledges it.

    ``chunks[head:]`` covers stream offsets ``[head_offset, end)``. Offsets
    below ``acked`` are released; ``[acked, sent)`` waits for acknowledgement;
    ``[sent, end)`` starts at ``chunks[cursor][cursor_pos]``. ngtcp2 reports
    acknowledgements as a growing contiguous prefix, so chunks are only freed
    from the front.
    """

    # Fields and C methods are declared in stream.pxd.

    def __cinit__(self):
        self.chunks = []

    cdef size_t vectors(self, ng.ngtcp2_vec *vecs, bint *covers_end):
        cdef Py_ssize_t index = self.cursor
        cdef Py_ssize_t offset = self.cursor_pos
        cdef Py_ssize_t count = len(self.chunks)
        cdef size_t used = 0
        cdef bytes chunk

        while index < count and used < _MAX_VECS:
            chunk = <bytes>self.chunks[index]
            vecs[used].base = <uint8_t *>PyBytes_AS_STRING(chunk) + offset
            vecs[used].len = PyBytes_GET_SIZE(chunk) - offset
            used += 1
            index += 1
            offset = 0
        covers_end[0] = index == count
        return used

    cdef void advance(self, size_t length):
        cdef Py_ssize_t remaining

        self.sent += length
        while length:
            remaining = (
                PyBytes_GET_SIZE(<bytes>self.chunks[self.cursor]) - self.cursor_pos
            )
            if <Py_ssize_t>length >= remaining:
                length -= remaining
                self.cursor += 1
                self.cursor_pos = 0
            else:
                self.cursor_pos += length
                length = 0

    cdef void acknowledge(self, uint64_t length):
        cdef Py_ssize_t size

        self.acked += length
        while self.head < self.cursor:
            size = PyBytes_GET_SIZE(<bytes>self.chunks[self.head])
            if self.head_offset + size > self.acked:
                break
            self.chunks[self.head] = None
            self.head_offset += size
            self.head += 1
        # Compact once the released prefix dominates, keeping removal amortized O(1).
        if self.head >= 32 and self.head * 2 >= len(self.chunks):
            del self.chunks[:self.head]
            self.cursor -= self.head
            self.head = 0

    cdef void abandon(self):
        """Stop sending; ngtcp2 dropped the unacknowledged data with the reset."""
        self.chunks = []
        self.head = self.cursor = self.cursor_pos = 0
        self.head_offset = self.acked = self.end = self.sent
        self.fin_queued = self.fin_sent
        self.send_closed = True
        self.paused = False


cdef class _ScheduledStream(_Stream):
    """A raw QUIC stream, sent in round-robin order by ``Connection``."""

    # Fields are declared in stream.pxd.
