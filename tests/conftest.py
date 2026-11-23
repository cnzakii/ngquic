from dataclasses import dataclass
from pathlib import Path

import pytest
from support.h3 import H3Network, h3_tls
from support.network import ALPN, Network

from ngquic import (
    Role,
    TLSContext,
)

# Test-only keys and century-long certificates; generate.sh recreates them.
CERTS = Path(__file__).parent / "support" / "certs"


@dataclass(frozen=True)
class Certificates:
    ca: str = str(CERTS / "ca.pem")
    cert: str = str(CERTS / "cert.pem")
    key: str = str(CERTS / "key.pem")
    # key.pem encrypted with the password "secret".
    encrypted_key: str = str(CERTS / "key_encrypted.pem")
    other_ca: str = str(CERTS / "other_ca.pem")


@pytest.fixture(scope="session")
def certificates() -> Certificates:
    return Certificates()


@pytest.fixture
def server_tls(certificates) -> TLSContext:
    context = TLSContext(Role.SERVER)
    context.load_cert_chain(certificates.cert, certificates.key)
    context.set_alpn_protocols([ALPN])
    return context


@pytest.fixture
def client_tls(certificates) -> TLSContext:
    context = TLSContext(Role.CLIENT)
    context.load_verify_locations(cafile=certificates.ca)
    context.set_alpn_protocols([ALPN])
    return context


@pytest.fixture
def network(server_tls, client_tls) -> Network:
    return Network(server_tls=server_tls, client_tls=client_tls)


@pytest.fixture
def h3_network(certificates) -> H3Network:
    return H3Network(
        server_tls=h3_tls(certificates, Role.SERVER),
        client_tls=h3_tls(certificates, Role.CLIENT),
    )


# aioquic is optional (no free-threaded build), so it is imported on use.
@pytest.fixture
def aio_server_config(certificates):
    from support.aioquic import aioquic_server_config

    return aioquic_server_config(certificates)


@pytest.fixture
def aio_client_config(certificates):
    from support.aioquic import aioquic_client_config

    return aioquic_client_config(certificates)
