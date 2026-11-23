# Raw streams and DATAGRAMs, and the round-robin stream scheduler. Implemented
# in connection.pxi.


cdef class Connection(BaseConnection):
    cdef _ScheduledStream _active_head
    cdef _ScheduledStream _active_tail

    # ---- internals
    cdef _ScheduledStream _sendable(self, int64_t stream_id)
    cdef void _activate(self, _ScheduledStream stream)
    cdef void _deactivate(self, _ScheduledStream stream)
    cdef void _written(
        self, _ScheduledStream stream, ng.ngtcp2_ssize length, uint32_t flags,
    )
