from libc.stdint cimport int64_t, uint64_t


cdef class Event:
    pass


cdef class HandshakeCompleted(Event):
    cdef readonly object alpn_protocol
    cdef readonly bint session_resumed
    cdef readonly bint early_data_accepted

cdef class HandshakeConfirmed(Event):
    pass

cdef class StreamDataReceived(Event):
    cdef readonly int64_t stream_id
    cdef readonly bytes data
    cdef readonly bint end_stream
    cdef readonly bint early

cdef class StreamReset(Event):
    cdef readonly int64_t stream_id
    cdef readonly uint64_t error_code
    cdef readonly uint64_t final_size

cdef class StopSendingReceived(Event):
    cdef readonly int64_t stream_id
    cdef readonly uint64_t error_code

cdef class StreamClosed(Event):
    cdef readonly int64_t stream_id
    cdef readonly object receive_error_code
    cdef readonly object send_error_code

cdef class StreamsAvailable(Event):
    cdef readonly uint64_t bidirectional
    cdef readonly uint64_t unidirectional

cdef class StreamWritable(Event):
    cdef readonly int64_t stream_id

cdef class DatagramReceived(Event):
    cdef readonly bytes data
    cdef readonly bint early

cdef class DatagramAcknowledged(Event):
    cdef readonly uint64_t datagram_id

cdef class DatagramLost(Event):
    cdef readonly uint64_t datagram_id
    cdef readonly bint sent

cdef class SessionTicketReceived(Event):
    cdef readonly bytes ticket

cdef class NewTokenReceived(Event):
    cdef readonly bytes token

cdef class EarlyDataRejected(Event):
    pass

cdef class ClientHelloReceived(Event):
    cdef readonly object server_name
    cdef readonly tuple alpn_protocols

cdef class PeerCertificateReceived(Event):
    cdef readonly tuple chain

cdef class PathValidationStarted(Event):
    cdef readonly object local_addr
    cdef readonly object remote_addr
    cdef readonly bint preferred_address

cdef class PathValidated(Event):
    cdef readonly object local_addr
    cdef readonly object remote_addr
    cdef readonly bint preferred_address
    cdef readonly bint success

cdef class ConnectionTerminated(Event):
    cdef readonly object reason
    cdef readonly object error_code
    cdef readonly object frame_type
    cdef readonly bytes reason_phrase
    cdef readonly bint by_peer
