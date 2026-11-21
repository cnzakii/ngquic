cdef class Transmit:
    """UDP payloads ready to send to one address.

    ``data`` is one UDP payload, or with ``datagrams_to_send(gso=True)``
    several of ``segment_size`` bytes, the last one possibly shorter, to send
    as one GSO train.
    """

    # Fields are declared in transmit.pxd.

    __match_args__ = ("data", "remote_addr", "segment_size")

    def __repr__(self):
        return (
            f"Transmit(size={len(self.data)}, remote_addr={self.remote_addr!r}, "
            f"segment_size={self.segment_size}, ecn={self.ecn})"
        )


cdef Transmit _transmit(
    bytes data, object remote, object local, Py_ssize_t segment, int ecn,
):
    cdef Transmit result = Transmit.__new__(Transmit)

    result.data = data
    result.remote_addr = remote
    result.local_addr = local
    result.segment_size = segment
    result.ecn = ecn
    return result
