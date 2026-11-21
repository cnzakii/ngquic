#!/bin/sh
# Regenerates the test certificates with OpenSSL 3. They are test-only: the
# keys are public, and the certificates stay valid for a century so the
# suite never depends on the date. Run from this directory.
set -eu
days=36500
ec="-newkey ec -pkeyopt ec_paramgen_curve:P-256 -noenc"

openssl req -x509 $ec -keyout ca.key -out ca.pem -days $days \
  -subj "/CN=test ca" -addext "basicConstraints=critical,CA:TRUE"
openssl req -x509 $ec -keyout other_ca.key -out other_ca.pem -days $days \
  -subj "/CN=other ca" -addext "basicConstraints=critical,CA:TRUE"
openssl req $ec -keyout key.pem -out cert.csr -subj "/CN=localhost"
openssl x509 -req -in cert.csr -CA ca.pem -CAkey ca.key -days $days \
  -extfile /dev/stdin -out cert.pem <<'EXT'
subjectAltName = DNS:localhost, IP:127.0.0.1
EXT
# The same key, encrypted, for load_cert_chain(password=...).
openssl pkcs8 -topk8 -in key.pem -out key_encrypted.pem -passout pass:secret
rm ca.key other_ca.key cert.csr
