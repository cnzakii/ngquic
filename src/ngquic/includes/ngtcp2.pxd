from libc.stddef cimport ptrdiff_t
from libc.stdint cimport int64_t, uint8_t, uint16_t, uint32_t, uint64_t


cdef extern from "glue.h":
    # Sockets: only the fields the address conversion touches. The family is
    # declared int: sa_family_t is POSIX, Windows calls it ADDRESS_FAMILY.
    ctypedef unsigned int socklen_t

    cdef struct sockaddr:
        int sa_family

    cdef struct in_addr:
        pass

    cdef struct in6_addr:
        pass

    cdef struct sockaddr_in:
        int sin_family
        uint16_t sin_port
        in_addr sin_addr

    cdef struct sockaddr_in6:
        int sin6_family
        uint16_t sin6_port
        uint32_t sin6_flowinfo
        in6_addr sin6_addr
        uint32_t sin6_scope_id

    int AF_INET
    int AF_INET6
    uint16_t htons(uint16_t)
    uint16_t ntohs(uint16_t)
    uint32_t htonl(uint32_t)
    uint32_t ntohl(uint32_t)
    int inet_pton(int af, const char *src, void *dst)
    const char *inet_ntop(int af, const void *src, char *dst, socklen_t size)

    # AWS-LC types.
    ctypedef struct SSL_CTX:
        pass

    ctypedef struct SSL:
        pass

    ctypedef struct SSL_METHOD:
        pass

    ctypedef struct SSL_SESSION:
        pass

    ctypedef struct X509:
        pass

    ctypedef struct X509_STORE:
        pass

    ctypedef struct X509_VERIFY_PARAM:
        pass

    ctypedef struct BIO:
        pass

    ctypedef struct EVP_PKEY:
        pass

    ctypedef struct CRYPTO_BUFFER:
        pass

    ctypedef struct stack_st_CRYPTO_BUFFER "STACK_OF(CRYPTO_BUFFER)":
        pass

    ctypedef struct SSL_CLIENT_HELLO:
        SSL *ssl

    enum ssl_verify_result_t:
        ssl_verify_ok
        ssl_verify_invalid
        ssl_verify_retry

    enum ssl_select_cert_result_t:
        ssl_select_cert_success
        ssl_select_cert_retry
        ssl_select_cert_error

    ctypedef ssl_verify_result_t (*glue_custom_verify_cb)(
        SSL *ssl, uint8_t *out_alert
    ) noexcept
    ctypedef int (*glue_cert_cb)(SSL *ssl, void *arg) noexcept
    ctypedef ssl_select_cert_result_t (*glue_select_certificate_cb)(
        const SSL_CLIENT_HELLO *hello
    ) noexcept

    # ngtcp2 core types.
    ctypedef ptrdiff_t ngtcp2_ssize
    ctypedef uint64_t ngtcp2_tstamp
    ctypedef uint64_t ngtcp2_duration
    ctypedef sockaddr ngtcp2_sockaddr
    ctypedef socklen_t ngtcp2_socklen

    ctypedef struct ngtcp2_conn:
        pass

    ctypedef struct ngtcp2_mem:
        void *user_data
        void *(*malloc)(size_t size, void *user_data) noexcept nogil
        void (*free)(void *ptr, void *user_data) noexcept nogil
        void *(*calloc)(size_t nmemb, size_t size, void *user_data) noexcept nogil
        void *(*realloc)(void *ptr, size_t size, void *user_data) noexcept nogil

    # Enums so Cython accepts them as array sizes.
    enum:
        NGTCP2_MAX_UDP_PAYLOAD_SIZE
        NGTCP2_MAX_TX_UDP_PAYLOAD_SIZE
        NGTCP2_CRYPTO_MAX_RETRY_TOKENLEN2
        NGTCP2_CRYPTO_MAX_REGULAR_TOKENLEN

    int NGTCP2_STATELESS_RESET_TOKENLEN

    ctypedef struct ngtcp2_cid:
        size_t datalen
        uint8_t data[20]

    ctypedef struct ngtcp2_vec:
        uint8_t *base
        size_t len

    ctypedef struct ngtcp2_addr:
        ngtcp2_sockaddr *addr
        ngtcp2_socklen addrlen

    ctypedef struct ngtcp2_path:
        ngtcp2_addr local
        ngtcp2_addr remote
        void *user_data

    ctypedef union ngtcp2_sockaddr_union:
        sockaddr sa
        sockaddr_in in4 "in"
        sockaddr_in6 in6

    ctypedef struct ngtcp2_path_storage:
        ngtcp2_path path
        ngtcp2_sockaddr_union local_addrbuf
        ngtcp2_sockaddr_union remote_addrbuf

    ctypedef struct ngtcp2_pkt_info:
        uint8_t ecn

    ctypedef struct ngtcp2_pkt_hd:
        ngtcp2_cid dcid
        ngtcp2_cid scid
        const uint8_t *token
        size_t tokenlen
        uint32_t version
        uint8_t type

    ctypedef struct ngtcp2_version_cid:
        uint32_t version
        const uint8_t *dcid
        size_t dcidlen
        const uint8_t *scid
        size_t scidlen

    ctypedef enum ngtcp2_ccerr_type:
        NGTCP2_CCERR_TYPE_TRANSPORT
        NGTCP2_CCERR_TYPE_APPLICATION
        NGTCP2_CCERR_TYPE_VERSION_NEGOTIATION
        NGTCP2_CCERR_TYPE_IDLE_CLOSE
        NGTCP2_CCERR_TYPE_DROP_CONN
        NGTCP2_CCERR_TYPE_RETRY

    ctypedef struct ngtcp2_ccerr:
        ngtcp2_ccerr_type type
        uint64_t error_code
        uint64_t frame_type
        const uint8_t *reason
        size_t reasonlen

    ctypedef struct ngtcp2_stateless_reset_token:
        uint8_t data[16]

    ctypedef struct ngtcp2_pkt_stateless_reset2:
        ngtcp2_stateless_reset_token token

    ctypedef enum ngtcp2_cc_algo:
        NGTCP2_CC_ALGO_RENO
        NGTCP2_CC_ALGO_CUBIC
        NGTCP2_CC_ALGO_BBR

    ctypedef enum ngtcp2_token_type:
        NGTCP2_TOKEN_TYPE_UNKNOWN
        NGTCP2_TOKEN_TYPE_RETRY
        NGTCP2_TOKEN_TYPE_NEW_TOKEN

    ctypedef void (*ngtcp2_qlog_write)(
        void *user_data, uint32_t flags, const void *data, size_t datalen
    ) noexcept

    ctypedef struct ngtcp2_settings:
        ngtcp2_qlog_write qlog_write
        ngtcp2_cc_algo cc_algo
        ngtcp2_tstamp initial_ts
        ngtcp2_duration initial_rtt
        size_t max_tx_udp_payload_size
        const uint8_t *token
        size_t tokenlen
        ngtcp2_token_type token_type
        uint64_t max_window
        uint64_t max_stream_window
        size_t ack_thresh
        uint8_t no_tx_udp_payload_size_shaping
        ngtcp2_duration handshake_timeout
        const uint32_t *preferred_versions
        size_t preferred_versionslen
        const uint32_t *available_versions
        size_t available_versionslen
        uint32_t original_version
        uint8_t no_pmtud
        const uint16_t *pmtud_probes
        size_t pmtud_probeslen
        uint64_t glitch_ratelim_burst
        uint64_t glitch_ratelim_rate
        size_t write_stream_data_thresh

    ctypedef struct ngtcp2_preferred_addr:
        ngtcp2_cid cid
        sockaddr_in ipv4
        sockaddr_in6 ipv6
        uint8_t ipv4_present
        uint8_t ipv6_present
        uint8_t stateless_reset_token[16]

    ctypedef struct ngtcp2_transport_params:
        ngtcp2_preferred_addr preferred_addr
        uint8_t preferred_addr_present
        ngtcp2_cid original_dcid
        ngtcp2_cid retry_scid
        uint64_t initial_max_stream_data_bidi_local
        uint64_t initial_max_stream_data_bidi_remote
        uint64_t initial_max_stream_data_uni
        uint64_t initial_max_data
        uint64_t initial_max_streams_bidi
        uint64_t initial_max_streams_uni
        ngtcp2_duration max_idle_timeout
        uint64_t max_udp_payload_size
        uint64_t active_connection_id_limit
        uint64_t ack_delay_exponent
        ngtcp2_duration max_ack_delay
        uint64_t max_datagram_frame_size
        uint8_t disable_active_migration
        uint8_t original_dcid_present
        uint8_t retry_scid_present
        uint8_t stateless_reset_token_present
        uint8_t stateless_reset_token[16]
        uint8_t grease_quic_bit

    ctypedef struct ngtcp2_conn_info:
        ngtcp2_duration latest_rtt
        ngtcp2_duration min_rtt
        ngtcp2_duration smoothed_rtt
        ngtcp2_duration rttvar
        uint64_t cwnd
        uint64_t ssthresh
        uint64_t bytes_in_flight
        uint64_t pkt_sent
        uint64_t bytes_sent
        uint64_t pkt_recv
        uint64_t bytes_recv
        uint64_t pkt_lost
        uint64_t bytes_lost
        uint64_t ping_recv
        uint64_t pkt_discarded

    ctypedef enum ngtcp2_connection_id_status_type:
        NGTCP2_CONNECTION_ID_STATUS_TYPE_ACTIVATE
        NGTCP2_CONNECTION_ID_STATUS_TYPE_DEACTIVATE

    ctypedef enum ngtcp2_path_validation_result:
        NGTCP2_PATH_VALIDATION_RESULT_SUCCESS
        NGTCP2_PATH_VALIDATION_RESULT_FAILURE
        NGTCP2_PATH_VALIDATION_RESULT_ABORTED

    # Callbacks implemented by the binding.
    ctypedef struct ngtcp2_rand_ctx:
        void *native_handle

    ctypedef void (*ngtcp2_rand)(
        uint8_t *dest, size_t destlen, const ngtcp2_rand_ctx *rand_ctx
    ) noexcept
    ctypedef int (*ngtcp2_handshake_completed)(
        ngtcp2_conn *conn, void *user_data
    ) noexcept
    ctypedef enum ngtcp2_encryption_level:
        NGTCP2_ENCRYPTION_LEVEL_HANDSHAKE
        NGTCP2_ENCRYPTION_LEVEL_1RTT
    ctypedef int (*ngtcp2_recv_key)(
        ngtcp2_conn *conn, ngtcp2_encryption_level level, void *user_data
    ) noexcept
    ctypedef int (*ngtcp2_recv_stream_data)(
        ngtcp2_conn *conn, uint32_t flags, int64_t stream_id, uint64_t offset,
        const uint8_t *data, size_t datalen, void *user_data,
        void *stream_user_data,
    ) noexcept
    ctypedef int (*ngtcp2_acked_stream_data_offset)(
        ngtcp2_conn *conn, int64_t stream_id, uint64_t offset, uint64_t datalen,
        void *user_data, void *stream_user_data,
    ) noexcept
    ctypedef int (*ngtcp2_stream_close2)(
        ngtcp2_conn *conn, uint32_t flags, int64_t stream_id,
        uint64_t rx_app_error_code, uint64_t tx_app_error_code,
        void *user_data, void *stream_user_data,
    ) noexcept
    ctypedef int (*ngtcp2_stream_reset)(
        ngtcp2_conn *conn, int64_t stream_id, uint64_t final_size,
        uint64_t app_error_code, void *user_data, void *stream_user_data,
    ) noexcept
    ctypedef int (*ngtcp2_recv_stop_sending)(
        ngtcp2_conn *conn, int64_t stream_id, uint64_t app_error_code,
        void *user_data, void *stream_user_data,
    ) noexcept
    ctypedef int (*ngtcp2_extend_max_streams)(
        ngtcp2_conn *conn, uint64_t max_streams, void *user_data
    ) noexcept
    ctypedef int (*ngtcp2_extend_max_stream_data)(
        ngtcp2_conn *conn, int64_t stream_id, uint64_t max_data,
        void *user_data, void *stream_user_data,
    ) noexcept
    ctypedef int (*ngtcp2_get_new_connection_id2)(
        ngtcp2_conn *conn, ngtcp2_cid *cid, ngtcp2_stateless_reset_token *token,
        size_t cidlen, void *user_data,
    ) noexcept
    ctypedef int (*ngtcp2_remove_connection_id)(
        ngtcp2_conn *conn, const ngtcp2_cid *cid, void *user_data
    ) noexcept
    ctypedef int (*ngtcp2_connection_id_status2)(
        ngtcp2_conn *conn, ngtcp2_connection_id_status_type type, uint64_t seq,
        const ngtcp2_cid *cid, const ngtcp2_stateless_reset_token *token,
        void *user_data,
    ) noexcept
    ctypedef int (*ngtcp2_recv_datagram)(
        ngtcp2_conn *conn, uint32_t flags, const uint8_t *data, size_t datalen,
        void *user_data,
    ) noexcept
    ctypedef int (*ngtcp2_datagram_status)(
        ngtcp2_conn *conn, uint64_t dgram_id, void *user_data
    ) noexcept
    ctypedef int (*ngtcp2_recv_new_token)(
        ngtcp2_conn *conn, const uint8_t *token, size_t tokenlen,
        void *user_data,
    ) noexcept
    ctypedef int (*ngtcp2_recv_stateless_reset2)(
        ngtcp2_conn *conn, const ngtcp2_pkt_stateless_reset2 *sr,
        void *user_data,
    ) noexcept
    ctypedef int (*ngtcp2_path_validation)(
        ngtcp2_conn *conn, uint32_t flags, const ngtcp2_path *path,
        const ngtcp2_path *fallback_path, ngtcp2_path_validation_result res,
        void *user_data,
    ) noexcept
    ctypedef int (*ngtcp2_begin_path_validation)(
        ngtcp2_conn *conn, uint32_t flags, const ngtcp2_path *path,
        const ngtcp2_path *fallback_path, void *user_data,
    ) noexcept
    ctypedef int (*ngtcp2_tls_early_data_rejected)(
        ngtcp2_conn *conn, void *user_data
    ) noexcept
    ctypedef ngtcp2_ssize (*ngtcp2_write_pkt)(
        ngtcp2_conn *conn, ngtcp2_path *path, ngtcp2_pkt_info *pi,
        uint8_t *dest, size_t destlen, ngtcp2_tstamp ts, void *user_data,
    ) noexcept

    ctypedef int (*ngtcp2_recv_version_negotiation)(
        ngtcp2_conn *conn, const ngtcp2_pkt_hd *hd, const uint32_t *sv, size_t nsv,
        void *user_data,
    ) noexcept
    ctypedef int (*ngtcp2_select_preferred_addr)(
        ngtcp2_conn *conn, ngtcp2_path *dest, const ngtcp2_preferred_addr *paddr,
        void *user_data,
    ) noexcept

    ctypedef int (*ngtcp2_stream_open)(
        ngtcp2_conn *conn, int64_t stream_id, void *user_data
    ) noexcept

    ctypedef struct ngtcp2_callbacks:
        ngtcp2_recv_version_negotiation recv_version_negotiation
        ngtcp2_select_preferred_addr select_preferred_addr
        ngtcp2_handshake_completed handshake_completed
        ngtcp2_handshake_completed handshake_confirmed
        ngtcp2_recv_stream_data recv_stream_data
        ngtcp2_acked_stream_data_offset acked_stream_data_offset
        ngtcp2_extend_max_streams extend_max_local_streams_bidi
        ngtcp2_extend_max_streams extend_max_local_streams_uni
        ngtcp2_extend_max_streams extend_max_remote_streams_bidi
        ngtcp2_rand rand
        ngtcp2_remove_connection_id remove_connection_id
        ngtcp2_path_validation path_validation
        ngtcp2_stream_reset stream_reset
        ngtcp2_extend_max_stream_data extend_max_stream_data
        ngtcp2_recv_new_token recv_new_token
        ngtcp2_recv_datagram recv_datagram
        ngtcp2_datagram_status ack_datagram
        ngtcp2_datagram_status lost_datagram
        ngtcp2_tls_early_data_rejected tls_early_data_rejected
        ngtcp2_begin_path_validation begin_path_validation
        ngtcp2_recv_stateless_reset2 recv_stateless_reset2
        ngtcp2_get_new_connection_id2 get_new_connection_id2
        ngtcp2_connection_id_status2 dcid_status2
        ngtcp2_recv_stop_sending recv_stop_sending
        ngtcp2_stream_close2 stream_close2
        ngtcp2_stream_open stream_open
        ngtcp2_recv_key recv_rx_key
        ngtcp2_recv_key recv_tx_key

    void glue_set_crypto_callbacks(ngtcp2_callbacks *cb, int server)
    void glue_random_bytes(uint8_t *dest, size_t length)

    # Error codes and flags.
    int NGTCP2_ERR_INVALID_ARGUMENT
    int NGTCP2_ERR_INVALID_STATE
    int NGTCP2_ERR_STREAM_ID_BLOCKED
    int NGTCP2_ERR_STREAM_DATA_BLOCKED
    int NGTCP2_ERR_STREAM_SHUT_WR
    int NGTCP2_ERR_STREAM_NOT_FOUND
    int NGTCP2_ERR_CRYPTO
    int NGTCP2_ERR_RECV_VERSION_NEGOTIATION
    int NGTCP2_ERR_CLOSING
    int NGTCP2_ERR_DRAINING
    int NGTCP2_ERR_CONN_ID_BLOCKED
    int NGTCP2_ERR_WRITE_MORE
    int NGTCP2_ERR_RETRY
    int NGTCP2_ERR_DROP_CONN
    int NGTCP2_ERR_VERSION_NEGOTIATION
    int NGTCP2_ERR_HANDSHAKE_TIMEOUT
    int NGTCP2_ERR_IDLE_CLOSE
    int NGTCP2_ERR_NOMEM
    int NGTCP2_ERR_CALLBACK_FAILURE

    uint32_t NGTCP2_WRITE_STREAM_FLAG_MORE
    uint32_t NGTCP2_WRITE_STREAM_FLAG_FIN
    uint32_t NGTCP2_WRITE_STREAM_FLAG_PADDING
    uint32_t NGTCP2_WRITE_DATAGRAM_FLAG_MORE
    uint32_t NGTCP2_WRITE_DATAGRAM_FLAG_PADDING
    uint32_t NGTCP2_STREAM_DATA_FLAG_FIN
    uint32_t NGTCP2_STREAM_DATA_FLAG_0RTT
    uint32_t NGTCP2_DATAGRAM_FLAG_0RTT
    uint32_t NGTCP2_STREAM_CLOSE2_FLAG_RX_APP_ERROR_CODE_SET
    uint32_t NGTCP2_STREAM_CLOSE2_FLAG_TX_APP_ERROR_CODE_SET
    uint32_t NGTCP2_PATH_VALIDATION_FLAG_PREFERRED_ADDR
    uint32_t NGTCP2_PATH_VALIDATION_FLAG_NEW_TOKEN

    # Functions; several are macros over the *_versioned symbols.
    ctypedef struct ngtcp2_info:
        int version_num
        const char *version_str

    const ngtcp2_info *ngtcp2_version(int least_version)
    const char *ngtcp2_strerror(int liberr)
    int ngtcp2_is_bidi_stream(int64_t stream_id)

    void ngtcp2_settings_default(ngtcp2_settings *settings)
    void ngtcp2_transport_params_default(ngtcp2_transport_params *params)
    ngtcp2_ssize ngtcp2_transport_params_encode(
        uint8_t *dest, size_t destlen, const ngtcp2_transport_params *params
    )

    int ngtcp2_pkt_decode_version_cid(
        ngtcp2_version_cid *dest, const uint8_t *data, size_t datalen,
        size_t short_dcidlen,
    )
    int ngtcp2_accept(ngtcp2_pkt_hd *dest, const uint8_t *pkt, size_t pktlen)
    ngtcp2_ssize ngtcp2_pkt_write_version_negotiation(
        uint8_t *dest, size_t destlen, uint8_t unused_random,
        const uint8_t *dcid, size_t dcidlen, const uint8_t *scid,
        size_t scidlen, const uint32_t *sv, size_t nsv,
    )
    ngtcp2_ssize ngtcp2_pkt_write_stateless_reset2(
        uint8_t *dest, size_t destlen, const ngtcp2_stateless_reset_token *token,
        const uint8_t *rand, size_t randlen,
    )

    int ngtcp2_conn_client_new(
        ngtcp2_conn **pconn, const ngtcp2_cid *dcid, const ngtcp2_cid *scid,
        const ngtcp2_path *path, uint32_t client_chosen_version,
        const ngtcp2_callbacks *callbacks, const ngtcp2_settings *settings,
        const ngtcp2_transport_params *params, const ngtcp2_mem *mem,
        void *user_data,
    )
    int ngtcp2_conn_server_new(
        ngtcp2_conn **pconn, const ngtcp2_cid *dcid, const ngtcp2_cid *scid,
        const ngtcp2_path *path, uint32_t client_chosen_version,
        const ngtcp2_callbacks *callbacks, const ngtcp2_settings *settings,
        const ngtcp2_transport_params *params, const ngtcp2_mem *mem,
        void *user_data,
    )
    void ngtcp2_conn_del(ngtcp2_conn *conn)
    int ngtcp2_conn_read_pkt(
        ngtcp2_conn *conn, const ngtcp2_path *path, const ngtcp2_pkt_info *pi,
        const uint8_t *pkt, size_t pktlen, ngtcp2_tstamp ts,
    )
    ngtcp2_ssize ngtcp2_conn_write_aggregate_pkt2(
        ngtcp2_conn *conn, ngtcp2_path *path, ngtcp2_pkt_info *pi,
        uint8_t *buf, size_t buflen, size_t *pgsolen, ngtcp2_write_pkt write_pkt,
        size_t num_pkts, ngtcp2_tstamp ts,
    )
    ngtcp2_ssize ngtcp2_conn_writev_stream(
        ngtcp2_conn *conn, ngtcp2_path *path, ngtcp2_pkt_info *pi,
        uint8_t *dest, size_t destlen, ngtcp2_ssize *pdatalen, uint32_t flags,
        int64_t stream_id, const ngtcp2_vec *datav, size_t datavcnt,
        ngtcp2_tstamp ts,
    )
    ngtcp2_ssize ngtcp2_conn_writev_datagram(
        ngtcp2_conn *conn, ngtcp2_path *path, ngtcp2_pkt_info *pi,
        uint8_t *dest, size_t destlen, int *paccepted, uint32_t flags,
        uint64_t dgram_id, const ngtcp2_vec *datav, size_t datavcnt,
        ngtcp2_tstamp ts,
    )
    ngtcp2_ssize ngtcp2_conn_write_connection_close(
        ngtcp2_conn *conn, ngtcp2_path *path, ngtcp2_pkt_info *pi,
        uint8_t *dest, size_t destlen, const ngtcp2_ccerr *ccerr,
        ngtcp2_tstamp ts,
    )
    ngtcp2_tstamp ngtcp2_conn_get_expiry2(const ngtcp2_conn *conn)
    int ngtcp2_conn_handle_expiry(ngtcp2_conn *conn, ngtcp2_tstamp ts)
    ngtcp2_duration ngtcp2_conn_get_pto2(const ngtcp2_conn *conn)
    int ngtcp2_conn_open_bidi_stream(
        ngtcp2_conn *conn, int64_t *pstream_id, void *stream_user_data
    )
    int ngtcp2_conn_open_uni_stream(
        ngtcp2_conn *conn, int64_t *pstream_id, void *stream_user_data
    )
    int ngtcp2_conn_shutdown_stream(
        ngtcp2_conn *conn, uint32_t flags, int64_t stream_id,
        uint64_t app_error_code,
    )
    int ngtcp2_conn_shutdown_stream_write(
        ngtcp2_conn *conn, uint32_t flags, int64_t stream_id,
        uint64_t app_error_code,
    )
    int ngtcp2_conn_shutdown_stream_read(
        ngtcp2_conn *conn, uint32_t flags, int64_t stream_id,
        uint64_t app_error_code,
    )
    int ngtcp2_conn_extend_max_stream_offset(
        ngtcp2_conn *conn, int64_t stream_id, uint64_t datalen
    )
    void ngtcp2_conn_extend_max_offset(ngtcp2_conn *conn, uint64_t datalen)
    void ngtcp2_conn_extend_max_streams_bidi(ngtcp2_conn *conn, size_t n)
    void ngtcp2_conn_extend_max_streams_uni(ngtcp2_conn *conn, size_t n)
    int ngtcp2_conn_set_stream_user_data(
        ngtcp2_conn *conn, int64_t stream_id, void *stream_user_data
    )
    const ngtcp2_transport_params *ngtcp2_conn_get_local_transport_params(
        ngtcp2_conn *conn
    )
    uint64_t ngtcp2_conn_get_streams_bidi_left2(const ngtcp2_conn *conn)
    uint64_t ngtcp2_conn_get_streams_uni_left2(const ngtcp2_conn *conn)
    uint64_t ngtcp2_conn_get_max_data_left2(const ngtcp2_conn *conn)
    uint64_t ngtcp2_conn_get_max_data_left_write_thresh(const ngtcp2_conn *conn)
    uint64_t ngtcp2_conn_get_max_stream_data_left2(
        const ngtcp2_conn *conn, int64_t stream_id
    )
    size_t ngtcp2_conn_get_stream_loss_count2(
        const ngtcp2_conn *conn, int64_t stream_id
    )
    const ngtcp2_ccerr *ngtcp2_conn_get_ccerr2(const ngtcp2_conn *conn)
    uint8_t ngtcp2_conn_get_tls_alert2(const ngtcp2_conn *conn)
    void ngtcp2_ccerr_set_liberr(
        ngtcp2_ccerr *ccerr, int liberr, const uint8_t *reason, size_t reasonlen
    )
    void ngtcp2_ccerr_set_tls_alert(
        ngtcp2_ccerr *ccerr, uint8_t tls_alert, const uint8_t *reason,
        size_t reasonlen,
    )
    void ngtcp2_ccerr_set_application_error(
        ngtcp2_ccerr *ccerr, uint64_t error_code, const uint8_t *reason,
        size_t reasonlen,
    )
    void ngtcp2_ccerr_set_transport_error(
        ngtcp2_ccerr *ccerr, uint64_t error_code, const uint8_t *reason,
        size_t reasonlen,
    )
    int ngtcp2_conn_continue_handshake(ngtcp2_conn *conn, ngtcp2_tstamp ts)
    uint32_t ngtcp2_select_version(
        const uint32_t *preferred_versions, size_t preferred_versionslen,
        const uint32_t *offered_versions, size_t offered_versionslen,
    )
    void ngtcp2_conn_set_tls_native_handle(
        ngtcp2_conn *conn, void *tls_native_handle
    )
    int ngtcp2_conn_is_local_stream2(const ngtcp2_conn *conn, int64_t stream_id)
    void ngtcp2_conn_get_conn_info2(
        const ngtcp2_conn *conn, ngtcp2_conn_info *cinfo
    )
    uint32_t ngtcp2_conn_get_negotiated_version2(const ngtcp2_conn *conn)
    uint32_t ngtcp2_conn_get_client_chosen_version2(const ngtcp2_conn *conn)
    const ngtcp2_path *ngtcp2_conn_get_path2(const ngtcp2_conn *conn)
    size_t ngtcp2_conn_get_max_tx_udp_payload_size2(const ngtcp2_conn *conn)
    size_t ngtcp2_conn_get_send_quantum2(const ngtcp2_conn *conn)
    void ngtcp2_conn_update_pkt_tx_time(ngtcp2_conn *conn, ngtcp2_tstamp ts)
    size_t ngtcp2_conn_get_path_max_tx_udp_payload_size2(
        const ngtcp2_conn *conn
    )
    const ngtcp2_transport_params *ngtcp2_conn_get_remote_transport_params2(
        const ngtcp2_conn *conn
    )
    int ngtcp2_conn_submit_new_token(
        ngtcp2_conn *conn, const uint8_t *token, size_t tokenlen
    )
    int ngtcp2_conn_initiate_key_update(ngtcp2_conn *conn, ngtcp2_tstamp ts)
    int ngtcp2_conn_initiate_migration(
        ngtcp2_conn *conn, const ngtcp2_path *path, ngtcp2_tstamp ts
    )
    int ngtcp2_conn_initiate_immediate_migration(
        ngtcp2_conn *conn, const ngtcp2_path *path, ngtcp2_tstamp ts
    )
    void ngtcp2_conn_set_keep_alive_timeout(
        ngtcp2_conn *conn, ngtcp2_duration timeout
    )
    ngtcp2_tstamp ngtcp2_conn_get_timestamp(const ngtcp2_conn *conn)
    ngtcp2_ssize ngtcp2_conn_encode_0rtt_transport_params2(
        const ngtcp2_conn *conn, uint8_t *dest, size_t destlen
    )
    int ngtcp2_conn_decode_and_set_0rtt_transport_params(
        ngtcp2_conn *conn, const uint8_t *data, size_t datalen
    )

    # Crypto helper.
    ctypedef ngtcp2_conn *(*ngtcp2_crypto_get_conn)(
        ngtcp2_crypto_conn_ref *conn_ref
    ) noexcept

    ctypedef struct ngtcp2_crypto_conn_ref:
        ngtcp2_crypto_get_conn get_conn
        void *user_data

    uint8_t NGTCP2_CRYPTO_TOKEN_MAGIC_RETRY2
    uint8_t NGTCP2_CRYPTO_TOKEN_MAGIC_REGULAR

    int ngtcp2_crypto_boringssl_configure_server_context(SSL_CTX *ssl_ctx)
    int ngtcp2_crypto_boringssl_configure_client_context(SSL_CTX *ssl_ctx)
    int ngtcp2_crypto_generate_stateless_reset_token(
        uint8_t *token, const uint8_t *secret, size_t secretlen,
        const ngtcp2_cid *cid,
    )
    ngtcp2_ssize ngtcp2_crypto_generate_retry_token2(
        uint8_t *token, const uint8_t *secret, size_t secretlen,
        uint32_t version, const ngtcp2_sockaddr *remote_addr,
        ngtcp2_socklen remote_addrlen, const ngtcp2_cid *retry_scid,
        const ngtcp2_cid *odcid, ngtcp2_tstamp ts,
    )
    int ngtcp2_crypto_verify_retry_token2(
        ngtcp2_cid *odcid, const uint8_t *token, size_t tokenlen,
        const uint8_t *secret, size_t secretlen, uint32_t version,
        const ngtcp2_sockaddr *remote_addr, ngtcp2_socklen remote_addrlen,
        const ngtcp2_cid *dcid, ngtcp2_duration timeout, ngtcp2_tstamp ts,
    )
    ngtcp2_ssize ngtcp2_crypto_generate_regular_token2(
        uint8_t *token, const uint8_t *secret, size_t secretlen,
        const ngtcp2_sockaddr *remote_addr, ngtcp2_socklen remote_addrlen,
        const void *data, size_t datalen, ngtcp2_tstamp ts,
    )
    ngtcp2_ssize ngtcp2_crypto_verify_regular_token2(
        void *data, size_t max_datalen, const uint8_t *token, size_t tokenlen,
        const uint8_t *secret, size_t secretlen,
        const ngtcp2_sockaddr *remote_addr, ngtcp2_socklen remote_addrlen,
        ngtcp2_duration timeout, ngtcp2_tstamp ts,
    )
    ngtcp2_ssize ngtcp2_crypto_write_retry(
        uint8_t *dest, size_t destlen, uint32_t version, const ngtcp2_cid *dcid,
        const ngtcp2_cid *scid, const ngtcp2_cid *odcid, const uint8_t *token,
        size_t tokenlen,
    )
    ngtcp2_ssize ngtcp2_crypto_write_connection_close(
        uint8_t *dest, size_t destlen, uint32_t version, const ngtcp2_cid *dcid,
        const ngtcp2_cid *scid, uint64_t error_code, const uint8_t *reason,
        size_t reasonlen,
    )

    # AWS-LC.
    int SSL_VERIFY_NONE
    int SSL_VERIFY_PEER
    int SSL_VERIFY_FAIL_IF_NO_PEER_CERT
    int SSL_TLSEXT_ERR_OK
    int SSL_TLSEXT_ERR_ALERT_FATAL
    int SSL_SESS_CACHE_CLIENT
    int SSL_SESS_CACHE_NO_INTERNAL
    int X509_FILETYPE_PEM

    const SSL_METHOD *TLS_client_method()
    const SSL_METHOD *TLS_server_method()
    SSL_CTX *SSL_CTX_new(const SSL_METHOD *method)
    void SSL_CTX_free(SSL_CTX *ctx)
    int SSL_CTX_set_app_data(SSL_CTX *ctx, void *arg)
    void *SSL_CTX_get_app_data(const SSL_CTX *ctx)
    int SSL_CTX_use_certificate_chain_file(SSL_CTX *ctx, const char *file)
    int SSL_CTX_use_PrivateKey_file(SSL_CTX *ctx, const char *file, int type)
    void SSL_CTX_set_default_passwd_cb_userdata(SSL_CTX *ctx, void *data)
    int SSL_CTX_load_verify_locations(
        SSL_CTX *ctx, const char *ca_file, const char *ca_dir
    )
    X509_STORE *SSL_CTX_get_cert_store(const SSL_CTX *ctx)
    int X509_STORE_add_cert(X509_STORE *store, X509 *x509)
    void SSL_CTX_set_verify(SSL_CTX *ctx, int mode, void *callback)
    void SSL_CTX_set_custom_verify(
        SSL_CTX *ctx, int mode, glue_custom_verify_cb callback
    )
    void SSL_CTX_set_cert_cb(SSL_CTX *ctx, glue_cert_cb cb, void *arg)
    void SSL_CTX_set_select_certificate_cb(SSL_CTX *ctx, glue_select_certificate_cb cb)
    int SSL_early_callback_ctx_extension_get(
        const SSL_CLIENT_HELLO *hello, uint16_t extension_type,
        const uint8_t **out_data, size_t *out_len,
    )
    SSL_CTX *SSL_set_SSL_CTX(SSL *ssl, SSL_CTX *ctx)
    const stack_st_CRYPTO_BUFFER *SSL_get0_peer_certificates(const SSL *ssl)
    size_t sk_CRYPTO_BUFFER_num(const stack_st_CRYPTO_BUFFER *sk)
    CRYPTO_BUFFER *sk_CRYPTO_BUFFER_value(const stack_st_CRYPTO_BUFFER *sk, size_t i)
    const uint8_t *CRYPTO_BUFFER_data(const CRYPTO_BUFFER *buf)
    size_t CRYPTO_BUFFER_len(const CRYPTO_BUFFER *buf)
    uint16_t TLSEXT_TYPE_application_layer_protocol_negotiation
    uint8_t SSL_AD_BAD_CERTIFICATE
    int SSL_CTX_set1_groups_list(SSL_CTX *ctx, const char *groups)
    void SSL_CTX_set_alpn_select_cb(
        SSL_CTX *ctx,
        int (*cb)(SSL *ssl, const uint8_t **out, uint8_t *out_len,
                  const uint8_t *input, unsigned int in_len, void *arg) noexcept,
        void *arg,
    )
    void SSL_CTX_set_keylog_callback(
        SSL_CTX *ctx, void (*cb)(const SSL *ssl, const char *line) noexcept
    )
    int SSL_CTX_set_session_cache_mode(SSL_CTX *ctx, int mode)
    void SSL_CTX_sess_set_new_cb(
        SSL_CTX *ctx, int (*new_session_cb)(SSL *ssl, SSL_SESSION *session) noexcept
    )
    int SSL_CTX_set_num_tickets(SSL_CTX *ctx, size_t num_tickets)
    size_t SSL_CTX_get_num_tickets(const SSL_CTX *ctx)
    SSL *SSL_new(SSL_CTX *ctx)
    void SSL_free(SSL *ssl)
    SSL_CTX *SSL_get_SSL_CTX(const SSL *ssl)
    int SSL_set_app_data(SSL *ssl, void *arg)
    void *SSL_get_app_data(const SSL *ssl)
    void SSL_set_connect_state(SSL *ssl)
    void SSL_set_accept_state(SSL *ssl)
    int SSL_set_tlsext_host_name(SSL *ssl, const char *name)
    int SSL_set_alpn_protos(SSL *ssl, const uint8_t *protos, size_t protos_len)
    void SSL_get0_alpn_selected(
        const SSL *ssl, const uint8_t **out_data, unsigned int *out_len
    )
    const char *SSL_get_servername(const SSL *ssl, int type)
    int TLSEXT_NAMETYPE_host_name
    X509_VERIFY_PARAM *SSL_get0_param(SSL *ssl)
    int X509_VERIFY_PARAM_set1_host(
        X509_VERIFY_PARAM *param, const char *name, size_t name_len
    )
    int X509_VERIFY_PARAM_set1_ip_asc(X509_VERIFY_PARAM *param, const char *ipasc)
    X509 *SSL_get_peer_certificate(const SSL *ssl)
    int i2d_X509(X509 *x509, uint8_t **outp)
    X509 *d2i_X509(X509 **out, const uint8_t **inp, long length)
    void X509_free(X509 *x509)
    void SSL_set_early_data_enabled(SSL *ssl, int enabled)
    void SSL_set_shed_handshake_config(SSL *ssl, int enable)
    int SSL_set_quic_early_data_context(
        SSL *ssl, const uint8_t *context, size_t context_len
    )
    int SSL_set_session_id_context(
        SSL *ssl, const uint8_t *sid_ctx, size_t sid_ctx_len
    )
    SSL_SESSION *SSL_get_session(const SSL *ssl)
    int SSL_SESSION_set1_id_context(
        SSL_SESSION *session, const uint8_t *sid_ctx, size_t sid_ctx_len
    )
    int SSL_early_data_accepted(const SSL *ssl)
    int SSL_session_reused(const SSL *ssl)
    int SSL_set_session(SSL *ssl, SSL_SESSION *session)
    int SSL_SESSION_early_data_capable(const SSL_SESSION *session)
    int SSL_SESSION_to_bytes(
        const SSL_SESSION *in_, uint8_t **out_data, size_t *out_len
    )
    SSL_SESSION *SSL_SESSION_from_bytes(
        const uint8_t *in_, size_t in_len, const SSL_CTX *ctx
    )
    void SSL_SESSION_free(SSL_SESSION *session)
    void OPENSSL_free(void *ptr)

    BIO *BIO_new_mem_buf(const void *buf, ptrdiff_t len)
    int BIO_free(BIO *bio)
    X509 *PEM_read_bio_X509(BIO *bp, X509 **x, void *cb, void *u)

    unsigned long ERR_peek_last_error()
    void ERR_clear_error()
    void ERR_error_string_n(unsigned long e, char *buf, size_t len)

    const char *OpenSSL_version(int which)
