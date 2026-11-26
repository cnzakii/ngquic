# Endpoint and server-side connection attempts. Implemented in endpoint.pxi.


cdef class Endpoint:
    cdef readonly object config
    cdef readonly object local_addr
    cdef ng.ngtcp2_sockaddr_union _local
    cdef ng.ngtcp2_socklen _local_len
    cdef ng.ngtcp2_sockaddr_union _remote
    cdef ng.ngtcp2_socklen _remote_len
    cdef object _remote_key
    cdef dict _cids
    cdef object _undecided
    cdef dict _reset_tokens
    cdef set _connections
    cdef list _stateless
    cdef bytes _secret
    cdef size_t _cid_len
    cdef uint32_t _preferred[_MAX_VERSIONS]
    cdef size_t _preferred_len
    cdef uint32_t _available[_MAX_VERSIONS]
    cdef size_t _available_len
    cdef ng.ngtcp2_duration _retry_lifetime
    cdef ng.ngtcp2_duration _token_lifetime
    cdef bint _issue_tokens
    cdef bint _stateless_reset
    cdef ng.ngtcp2_preferred_addr _preferred_addr
    cdef bint _has_preferred_addr

    cdef object _receive(
        self, const uint8_t *packet, size_t length, const ng.ngtcp2_addr *remote,
        object remote_addr, const ng.ngtcp2_addr *local, object local_addr,
        uint8_t ecn, ng.ngtcp2_tstamp ts,
    )
    cdef object _process(
        self, const uint8_t *packet, size_t length, ng.ngtcp2_path *path,
        object remote_addr, object local_addr, uint8_t ecn, ng.ngtcp2_tstamp ts,
    )
    cdef BaseConnection _deliver(
        self, BaseConnection connection, const uint8_t *packet, size_t length,
        ng.ngtcp2_path *path, uint8_t ecn, ng.ngtcp2_tstamp ts,
    )
    cdef Incoming _incoming(
        self, ng.ngtcp2_pkt_hd *hd, bytes key, const uint8_t *packet, size_t length,
        ng.ngtcp2_path *path, object remote_addr, object local_addr, uint8_t ecn,
        ng.ngtcp2_tstamp ts,
    )
    cdef bint _accepts(self, uint32_t version)
    cdef int _send_version_negotiation(
        self, ng.ngtcp2_version_cid *vc, object remote_addr, object local_addr,
    ) except -1
    cdef int _send_stateless_reset(
        self, ng.ngtcp2_version_cid *vc, size_t received, object remote_addr,
        object local_addr,
    ) except -1
    cdef int _refuse(
        self, ng.ngtcp2_pkt_hd *hd, uint64_t error_code, object remote_addr,
        object local_addr,
    ) except -1
    cdef int _queue(
        self, const uint8_t *data, Py_ssize_t length, object remote_addr,
        object local_addr,
    ) except -1
    cdef int _register(self, BaseConnection connection, bytes key) except -1
    cdef void _unregister(self, BaseConnection connection)


cdef class Incoming:
    cdef Endpoint _endpoint
    cdef ng.ngtcp2_pkt_hd _hd
    cdef bytes _dcid_key
    cdef bytes _datagram
    cdef list _extra
    cdef bytes _token
    cdef ng.ngtcp2_token_type _token_type
    cdef ng.ngtcp2_cid _odcid
    cdef ng.ngtcp2_sockaddr_union _remote
    cdef ng.ngtcp2_socklen _remote_len
    cdef ng.ngtcp2_sockaddr_union _local
    cdef ng.ngtcp2_socklen _local_len
    cdef uint8_t _ecn
    cdef ng.ngtcp2_tstamp _ts
    cdef bint _decided
    cdef object __weakref__
    cdef readonly object remote_addr
    cdef readonly object local_addr
    cdef readonly object version
    cdef readonly bint remote_address_validated

    cdef int _decide(self) except -1
