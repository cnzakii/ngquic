"""RFC 9000 section 6 and RFCs 8999, 9368 and 9369: version negotiation."""

import pytest

# Optional: aioquic needs pylsqpack, which has no free-threaded build yet.
pytest.importorskip("aioquic")

from aioquic.quic import events as aio
from aioquic.quic.packet import (
    encode_quic_version_negotiation,
)
from support.aioquic import their_client
from support.network import CLIENT_ADDR, SERVER_ADDR

from ngquic import (
    Endpoint,
    EndpointConfig,
    HandshakeConfirmed,
    Incoming,
    NewTokenReceived,
    StreamDataReceived,
    Version,
)


def test_server_does_not_answer_version_negotiation(network):
    negotiation = encode_quic_version_negotiation(
        source_cid=b"source00",
        destination_cid=b"dest0000",
        supported_versions=[1] * 300,
    )

    result = network.server_endpoint.receive_datagram(
        negotiation, CLIENT_ADDR, network.now
    )

    assert (result, network.server_endpoint.datagrams_to_send()) == (None, [])


@pytest.mark.parametrize("version", [Version.V1, Version.V2], ids=["v1", "v2"])
def test_initial_for_a_disabled_version_needs_a_full_sized_datagram(network, version):
    other = Version.V2 if version == Version.V1 else Version.V1
    network.server_endpoint = Endpoint(
        SERVER_ADDR, EndpointConfig(preferred_versions=(other,))
    )
    client = network.connect(version=version)
    [initial] = client.datagrams_to_send(network.now, max_datagrams=1)
    assert len(initial.data) >= 1200

    result = network.server_endpoint.receive_datagram(
        initial.data[:1199], CLIENT_ADDR, network.now
    )

    assert (result, network.server_endpoint.datagrams_to_send()) == (None, [])


def test_aioquic_v2_client_delivers_stream_data_to_ngquic(
    server_tls, aio_client_config
):
    aio_client_config.supported_versions = [int(Version.V2)]
    link = their_client(server_tls, aio_client_config)
    link.run(lambda: link.theirs_of(aio.HandshakeCompleted))
    stream_id = link.theirs.get_next_available_stream_id()

    link.theirs.send_stream_data(stream_id, b"v2 stream", end_stream=True)
    link.run(lambda: link.ours_of(StreamDataReceived))

    assert link.ours_of(StreamDataReceived) == [
        StreamDataReceived(stream_id, b"v2 stream", True, False)
    ]


def test_compatible_negotiation_preserves_the_original_version_through_retry(network):
    network.server_endpoint = Endpoint(
        SERVER_ADDR,
        EndpointConfig(
            preferred_versions=(Version.V2,),
            available_versions=(Version.V1, Version.V2),
        ),
    )
    versions = []

    def accept(attempt):
        versions.append((attempt.version, attempt.remote_address_validated))
        if not attempt.remote_address_validated:
            attempt.retry()
            return None
        return attempt.accept(tls=network.server_tls)

    network.accept = accept
    client = network.connect(version=Version.V1)

    network.run(lambda: network.events_of(client, HandshakeConfirmed))

    assert (set(versions), client.version, network.server.version) == (
        {(Version.V1, False), (Version.V1, True)},
        Version.V2,
        Version.V2,
    )


def test_aioquic_v2_client_receives_stream_data_after_ngquic_updates_its_keys(
    server_tls, aio_client_config
):
    aio_client_config.supported_versions = [int(Version.V2)]
    link = their_client(server_tls, aio_client_config)
    link.run(lambda: link.ours_of(HandshakeConfirmed))
    link.run(limit=0.5)
    stream_id = link.ours.open_stream()

    link.ours.update_key(link.now)
    link.ours.send_stream_data(stream_id, b"after v2 key update", end_stream=True)
    link.run(lambda: link.theirs_of(aio.StreamDataReceived))

    assert link.theirs_of(aio.StreamDataReceived) == [
        aio.StreamDataReceived(b"after v2 key update", True, stream_id)
    ]


def test_compatibly_negotiated_new_token_validates_a_direct_v2_connection(network):
    network.server_endpoint = Endpoint(
        SERVER_ADDR,
        EndpointConfig(
            preferred_versions=(Version.V2,),
            available_versions=(Version.V1, Version.V2),
        ),
    )
    first = network.connect(version=Version.V1)
    network.run(lambda: network.events_of(first, NewTokenReceived))
    [issued] = network.events_of(first, NewTokenReceived)
    second = network.connect(version=Version.V2, token=issued.token)
    [initial] = second.datagrams_to_send(network.now, max_datagrams=1)

    attempt = network.server_endpoint.receive_datagram(
        initial.data, CLIENT_ADDR, network.now
    )

    assert isinstance(attempt, Incoming)
    assert (attempt.version, attempt.remote_address_validated) == (Version.V2, True)
