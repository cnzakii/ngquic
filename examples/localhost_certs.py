"""A certificate for localhost and the CA that signed it, for the examples only.

The private key is public: never use it outside these examples. A real server
loads its own files with ``TLSContext.load_cert_chain()``, and a real client
trusts its CAs with ``load_verify_locations()`` or ``load_default_certs()``.
The PEM text is that of the test suite, which ``tests/support/certs`` makes.
"""

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

CA_PEM = """\
-----BEGIN CERTIFICATE-----
MIIBejCCASGgAwIBAgIUAWpHktr0wVtpQY4PpT9qguLn8J8wCgYIKoZIzj0EAwIw
EjEQMA4GA1UEAwwHdGVzdCBjYTAgFw0yNjExMjExNDMzMzFaGA8yMTI2MTAyODE0
MzMzMVowEjEQMA4GA1UEAwwHdGVzdCBjYTBZMBMGByqGSM49AgEGCCqGSM49AwEH
A0IABEgOgwNP4pUXkdWWxpPG+8uiryJ8hyWM50Q2Fxoe3TBWNE3/e6Im/M30Z+sP
qKsZMZQQJG7WZo2Uh52T2bIM4UyjUzBRMB0GA1UdDgQWBBRPZ2eF5ZW0wonP8j2r
tDI05QbCEjAfBgNVHSMEGDAWgBRPZ2eF5ZW0wonP8j2rtDI05QbCEjAPBgNVHRMB
Af8EBTADAQH/MAoGCCqGSM49BAMCA0cAMEQCICHOqBQbUXiA8EZQA7bWTyFOyY46
A7Gica6coaxgxtGxAiAoMfbHMQqQnx2YjQ82KVEbVP1ybQIAIoYT+UPImZlS8A==
-----END CERTIFICATE-----
"""

CERT_PEM = """\
-----BEGIN CERTIFICATE-----
MIIBiTCCAS6gAwIBAgIUMCH1MYUJ06lTREPlPGHg2PyAFi4wCgYIKoZIzj0EAwIw
EjEQMA4GA1UEAwwHdGVzdCBjYTAgFw0yNjExMjExNDMzMzFaGA8yMTI2MTAyODE0
MzMzMVowFDESMBAGA1UEAwwJbG9jYWxob3N0MFkwEwYHKoZIzj0CAQYIKoZIzj0D
AQcDQgAEXtuRedHk6nIN9PbAGxCLoWTL16fZO1xHRAVV6C0+3n/hQVgvQEyPO2Rs
1r5XXx/CdNLn1JyuVywtWV1ZqDj0faNeMFwwGgYDVR0RBBMwEYIJbG9jYWxob3N0
hwR/AAABMB0GA1UdDgQWBBQW2lA4VtoNlC7T/kBXHf5g0nygozAfBgNVHSMEGDAW
gBRPZ2eF5ZW0wonP8j2rtDI05QbCEjAKBggqhkjOPQQDAgNJADBGAiEA/pI/hbk7
oqtR21lmzhvqsiZjxeGWfaMhVwo/y30EbvMCIQCB3WeXjENRNA/i/C44nscGDWER
2f5CPprKF2pbJXoeKg==
-----END CERTIFICATE-----
"""

KEY_PEM = """\
-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQg+RUzRk+WAPc+6N3D
kXKShwjlvTmSSW+Ymu8SWDP/68ihRANCAARe25F50eTqcg309sAbEIuhZMvXp9k7
XEdEBVXoLT7ef+FBWC9ATI87ZGzWvldfH8J00ufUnK5XLC1ZXVmoOPR9
-----END PRIVATE KEY-----
"""


@contextmanager
def cert_chain_files() -> Iterator[tuple[str, str]]:
    """Write the certificate and key to temporary files; yield their paths."""
    with tempfile.TemporaryDirectory() as directory:
        certfile = Path(directory, "cert.pem")
        keyfile = Path(directory, "key.pem")
        certfile.write_text(CERT_PEM)
        keyfile.write_text(KEY_PEM)
        yield str(certfile), str(keyfile)
