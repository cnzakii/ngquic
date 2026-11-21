#ifndef EMBERLYN_GLUE_H
#define EMBERLYN_GLUE_H

#ifdef _WIN32
#  include <winsock2.h>
#  include <ws2tcpip.h>
#else
#  include <arpa/inet.h>
#  include <netinet/in.h>
#  include <sys/socket.h>
#endif

#include <ngtcp2/ngtcp2.h>
#include <ngtcp2/ngtcp2_crypto.h>
#include <ngtcp2/ngtcp2_crypto_boringssl.h>
#include <openssl/err.h>
#include <openssl/pem.h>
#include <openssl/rand.h>
#include <openssl/ssl.h>
#include <openssl/x509.h>

/* AWS-LC cannot detect fork() on macOS, so RAND_bytes reseeds from the OS
   on every call; arc4random_buf is the system's fork-safe CSPRNG there. */
#ifdef __APPLE__
#  include <stdlib.h>
#  define glue_random_bytes(dest, length) arc4random_buf((dest), (length))
#else
#  define glue_random_bytes(dest, length) ((void)RAND_bytes((dest), (length)))
#endif

/* The crypto helper callbacks are assigned in C because their function
   pointer types are long and only checked by the C compiler. */
/* Named AWS-LC callback types, so Cython can pass typed NULLs. */
typedef enum ssl_verify_result_t (*glue_custom_verify_cb)(SSL *, uint8_t *);
typedef int (*glue_cert_cb)(SSL *, void *);
typedef enum ssl_select_cert_result_t (*glue_select_certificate_cb)(
  const SSL_CLIENT_HELLO *);

static inline void glue_set_crypto_callbacks(ngtcp2_callbacks *cb,
                                             int server) {
  if (server) {
    cb->recv_client_initial = ngtcp2_crypto_recv_client_initial_cb;
  } else {
    cb->client_initial = ngtcp2_crypto_client_initial_cb;
    cb->recv_retry = ngtcp2_crypto_recv_retry_cb;
  }
  cb->recv_crypto_data = ngtcp2_crypto_recv_crypto_data_cb;
  cb->encrypt = ngtcp2_crypto_encrypt_cb;
  cb->decrypt = ngtcp2_crypto_decrypt_cb;
  cb->hp_mask = ngtcp2_crypto_hp_mask_cb;
  cb->update_key = ngtcp2_crypto_update_key_cb;
  cb->delete_crypto_aead_ctx = ngtcp2_crypto_delete_crypto_aead_ctx_cb;
  cb->delete_crypto_cipher_ctx = ngtcp2_crypto_delete_crypto_cipher_ctx_cb;
  cb->get_path_challenge_data2 = ngtcp2_crypto_get_path_challenge_data2_cb;
  cb->version_negotiation = ngtcp2_crypto_version_negotiation_cb;
}

#endif /* EMBERLYN_GLUE_H */
