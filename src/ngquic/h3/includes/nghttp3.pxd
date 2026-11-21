from libc.stddef cimport ptrdiff_t
from libc.stdint cimport int32_t, int64_t, uint8_t, uint32_t, uint64_t


cdef extern from "nghttp3/nghttp3.h":
    ctypedef ptrdiff_t nghttp3_ssize

    ctypedef struct nghttp3_conn:
        pass

    ctypedef struct nghttp3_rcbuf:
        pass

    ctypedef struct nghttp3_mem:
        void *user_data
        void *(*malloc)(size_t size, void *user_data) noexcept nogil
        void (*free)(void *ptr, void *user_data) noexcept nogil
        void *(*calloc)(size_t nmemb, size_t size, void *user_data) noexcept nogil
        void *(*realloc)(void *ptr, size_t size, void *user_data) noexcept nogil

    ctypedef struct nghttp3_vec:
        uint8_t *base
        size_t len

    ctypedef struct nghttp3_nv:
        const uint8_t *name
        const uint8_t *value
        size_t namelen
        size_t valuelen
        uint8_t flags

    ctypedef struct nghttp3_pri:
        uint32_t urgency
        uint8_t inc

    ctypedef struct nghttp3_proto_settings:
        uint64_t max_field_section_size
        size_t qpack_max_dtable_capacity
        size_t qpack_blocked_streams
        uint8_t enable_connect_protocol
        uint8_t h3_datagram

    ctypedef struct nghttp3_settings:
        uint64_t max_field_section_size
        size_t qpack_max_dtable_capacity
        size_t qpack_encoder_max_dtable_capacity
        size_t qpack_blocked_streams
        uint8_t enable_connect_protocol
        uint8_t h3_datagram
        const nghttp3_vec *origin_list
        uint64_t glitch_ratelim_burst
        uint64_t glitch_ratelim_rate

    ctypedef struct nghttp3_info:
        const char *version_str

    ctypedef nghttp3_ssize (*nghttp3_read_data_callback)(
        nghttp3_conn *conn, int64_t stream_id, nghttp3_vec *vec, size_t veccnt,
        uint32_t *pflags, void *conn_user_data, void *stream_user_data,
    ) noexcept

    ctypedef struct nghttp3_data_reader:
        nghttp3_read_data_callback read_data

    ctypedef int (*nghttp3_acked_stream_data)(
        nghttp3_conn *conn, int64_t stream_id, uint64_t datalen,
        void *conn_user_data, void *stream_user_data,
    ) noexcept
    ctypedef int (*nghttp3_stream_close2)(
        nghttp3_conn *conn, uint32_t flags, int64_t stream_id,
        uint64_t rx_app_error_code, uint64_t tx_app_error_code,
        void *conn_user_data, void *stream_user_data,
    ) noexcept
    ctypedef int (*nghttp3_recv_data)(
        nghttp3_conn *conn, int64_t stream_id, const uint8_t *data,
        size_t datalen, void *conn_user_data, void *stream_user_data,
    ) noexcept
    ctypedef int (*nghttp3_deferred_consume)(
        nghttp3_conn *conn, int64_t stream_id, size_t consumed,
        void *conn_user_data, void *stream_user_data,
    ) noexcept
    ctypedef int (*nghttp3_begin_headers)(
        nghttp3_conn *conn, int64_t stream_id, void *conn_user_data,
        void *stream_user_data,
    ) noexcept
    ctypedef int (*nghttp3_recv_header)(
        nghttp3_conn *conn, int64_t stream_id, int32_t token,
        nghttp3_rcbuf *name, nghttp3_rcbuf *value, uint8_t flags,
        void *conn_user_data, void *stream_user_data,
    ) noexcept
    ctypedef int (*nghttp3_end_headers)(
        nghttp3_conn *conn, int64_t stream_id, int fin, void *conn_user_data,
        void *stream_user_data,
    ) noexcept
    ctypedef int (*nghttp3_end_stream)(
        nghttp3_conn *conn, int64_t stream_id, void *conn_user_data,
        void *stream_user_data,
    ) noexcept
    ctypedef int (*nghttp3_stop_sending)(
        nghttp3_conn *conn, int64_t stream_id, uint64_t app_error_code,
        void *conn_user_data, void *stream_user_data,
    ) noexcept
    ctypedef int (*nghttp3_reset_stream)(
        nghttp3_conn *conn, int64_t stream_id, uint64_t app_error_code,
        void *conn_user_data, void *stream_user_data,
    ) noexcept
    ctypedef int (*nghttp3_shutdown)(
        nghttp3_conn *conn, int64_t id, void *conn_user_data,
    ) noexcept
    ctypedef int (*nghttp3_recv_settings2)(
        nghttp3_conn *conn, const nghttp3_proto_settings *settings,
        void *conn_user_data,
    ) noexcept
    ctypedef int (*nghttp3_recv_origin)(
        nghttp3_conn *conn, const uint8_t *origin, size_t originlen,
        void *conn_user_data,
    ) noexcept
    ctypedef int (*nghttp3_end_origin)(
        nghttp3_conn *conn, void *conn_user_data,
    ) noexcept
    ctypedef void (*nghttp3_rand)(uint8_t *dest, size_t destlen) noexcept

    ctypedef struct nghttp3_callbacks:
        nghttp3_acked_stream_data acked_stream_data
        nghttp3_recv_data recv_data
        nghttp3_deferred_consume deferred_consume
        nghttp3_begin_headers begin_headers
        nghttp3_recv_header recv_header
        nghttp3_end_headers end_headers
        nghttp3_begin_headers begin_trailers
        nghttp3_recv_header recv_trailer
        nghttp3_end_headers end_trailers
        nghttp3_stop_sending stop_sending
        nghttp3_end_stream end_stream
        nghttp3_reset_stream reset_stream
        nghttp3_shutdown shutdown
        nghttp3_recv_origin recv_origin
        nghttp3_end_origin end_origin
        nghttp3_rand rand
        nghttp3_recv_settings2 recv_settings2
        nghttp3_stream_close2 stream_close2

    int NGHTTP3_ERR_WOULDBLOCK
    int NGHTTP3_ERR_STREAM_NOT_FOUND
    int NGHTTP3_ERR_INVALID_STATE
    int NGHTTP3_ERR_INVALID_ARGUMENT
    int NGHTTP3_ERR_NOMEM
    int NGHTTP3_ERR_H3_EXCESSIVE_LOAD
    int NGHTTP3_ERR_CALLBACK_FAILURE
    int NGHTTP3_ERR_MALFORMED_HTTP_HEADER
    int32_t NGHTTP3_QPACK_TOKEN_HOST
    uint8_t NGHTTP3_NV_FLAG_NONE
    uint8_t NGHTTP3_NV_FLAG_NEVER_INDEX
    uint32_t NGHTTP3_DATA_FLAG_EOF
    uint32_t NGHTTP3_DATA_FLAG_NO_END_STREAM
    uint32_t NGHTTP3_STREAM_CLOSE_FLAG_RX_APP_ERROR_CODE_SET
    uint32_t NGHTTP3_STREAM_CLOSE_FLAG_TX_APP_ERROR_CODE_SET

    const nghttp3_info *nghttp3_version(int least_version)
    const char *nghttp3_strerror(int liberr)
    uint64_t nghttp3_err_infer_quic_app_error_code(int liberr)
    int nghttp3_check_header_name(const uint8_t *name, size_t len)
    int nghttp3_check_header_value(const uint8_t *value, size_t len)
    nghttp3_vec nghttp3_rcbuf_get_buf(const nghttp3_rcbuf *rcbuf)

    void nghttp3_settings_default(nghttp3_settings *settings)
    int nghttp3_conn_client_new(
        nghttp3_conn **pconn, const nghttp3_callbacks *callbacks,
        const nghttp3_settings *settings, const nghttp3_mem *mem, void *user_data,
    )
    int nghttp3_conn_server_new(
        nghttp3_conn **pconn, const nghttp3_callbacks *callbacks,
        const nghttp3_settings *settings, const nghttp3_mem *mem, void *user_data,
    )
    void nghttp3_conn_del(nghttp3_conn *conn)
    int nghttp3_conn_bind_control_stream(nghttp3_conn *conn, int64_t stream_id)
    int nghttp3_conn_bind_qpack_streams(
        nghttp3_conn *conn, int64_t qenc_stream_id, int64_t qdec_stream_id,
    )
    void nghttp3_conn_set_max_client_streams_bidi(
        nghttp3_conn *conn, uint64_t max_streams,
    )
    void nghttp3_conn_set_max_concurrent_streams(
        nghttp3_conn *conn, size_t max_concurrent_streams,
    )
    nghttp3_ssize nghttp3_conn_read_stream2(
        nghttp3_conn *conn, int64_t stream_id, const uint8_t *src, size_t srclen,
        int fin, uint64_t ts,
    )
    nghttp3_ssize nghttp3_conn_writev_stream(
        nghttp3_conn *conn, int64_t *pstream_id, int *pfin, nghttp3_vec *vec,
        size_t veccnt,
    )
    int nghttp3_conn_add_write_offset(nghttp3_conn *conn, int64_t stream_id, size_t n)
    int nghttp3_conn_add_ack_offset(nghttp3_conn *conn, int64_t stream_id, uint64_t n)
    void nghttp3_conn_block_stream(nghttp3_conn *conn, int64_t stream_id)
    int nghttp3_conn_unblock_stream(nghttp3_conn *conn, int64_t stream_id)
    void nghttp3_conn_shutdown_stream_write(nghttp3_conn *conn, int64_t stream_id)
    int nghttp3_conn_shutdown_stream_read(nghttp3_conn *conn, int64_t stream_id)
    int nghttp3_conn_resume_stream(nghttp3_conn *conn, int64_t stream_id)
    int nghttp3_conn_close_stream2(
        nghttp3_conn *conn, uint32_t flags, int64_t stream_id,
        uint64_t rx_app_error_code, uint64_t tx_app_error_code,
    )
    int nghttp3_conn_submit_request(
        nghttp3_conn *conn, int64_t stream_id, const nghttp3_nv *nva, size_t nvlen,
        const nghttp3_data_reader *dr, void *stream_user_data,
    )
    int nghttp3_conn_submit_info(
        nghttp3_conn *conn, int64_t stream_id, const nghttp3_nv *nva, size_t nvlen,
    )
    int nghttp3_conn_submit_response(
        nghttp3_conn *conn, int64_t stream_id, const nghttp3_nv *nva, size_t nvlen,
        const nghttp3_data_reader *dr,
    )
    int nghttp3_conn_submit_trailers(
        nghttp3_conn *conn, int64_t stream_id, const nghttp3_nv *nva, size_t nvlen,
    )
    int nghttp3_conn_submit_shutdown_notice(nghttp3_conn *conn)
    int nghttp3_conn_shutdown(nghttp3_conn *conn)
    int nghttp3_conn_is_drained2(const nghttp3_conn *conn)
    int nghttp3_conn_set_stream_user_data(
        nghttp3_conn *conn, int64_t stream_id, void *stream_user_data,
    )
    int nghttp3_conn_set_client_stream_priority(
        nghttp3_conn *conn, int64_t stream_id, const uint8_t *data, size_t datalen,
    )
    int nghttp3_conn_set_server_stream_priority(
        nghttp3_conn *conn, int64_t stream_id, const nghttp3_pri *pri,
    )
    int nghttp3_conn_get_stream_priority2(
        const nghttp3_conn *conn, nghttp3_pri *dest, int64_t stream_id,
    )
    int nghttp3_pri_parse_priority(nghttp3_pri *dest, const uint8_t *value, size_t len)

    const uint8_t *nghttp3_get_uvarint(uint64_t *dest, const uint8_t *p)
    size_t nghttp3_get_uvarintlen(const uint8_t *p)
    uint8_t *nghttp3_put_uvarint(uint8_t *p, uint64_t n)
    size_t nghttp3_put_uvarintlen(uint64_t n)
