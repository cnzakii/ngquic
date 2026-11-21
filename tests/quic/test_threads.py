import subprocess
import sys
import sysconfig
from concurrent.futures import ThreadPoolExecutor

import pytest
from support.network import Network

from ngquic import HandshakeCompleted, StreamDataReceived

PAYLOAD = bytes(range(256)) * 1024


def _echo(connection, event):
    if isinstance(event, StreamDataReceived) and not connection.is_client:
        connection.send_stream_data(
            event.stream_id, event.data, end_stream=event.end_stream
        )


def _transfer(server_tls, client_tls) -> bytes:
    network = Network(server_tls, client_tls, on_event=_echo)
    client = network.connect()
    network.run(lambda: network.events_of(client, HandshakeCompleted))
    stream_id = client.open_stream()
    client.send_stream_data(stream_id, PAYLOAD, end_stream=True)
    network.run(
        lambda: any(
            event.end_stream for event in network.events_of(client, StreamDataReceived)
        )
    )
    return b"".join(
        event.data for event in network.events_of(client, StreamDataReceived)
    )


def test_endpoints_in_separate_threads_share_tls_contexts(server_tls, client_tls):
    with ThreadPoolExecutor(8) as pool:
        echoes = list(pool.map(lambda _: _transfer(server_tls, client_tls), range(16)))

    assert echoes == [PAYLOAD] * 16


@pytest.mark.skipif(
    not sysconfig.get_config_var("Py_GIL_DISABLED"),
    reason="free-threaded CPython only",
)
def test_importing_does_not_enable_the_gil():
    # A fresh interpreter: an extension the tests import (aioquic) may enable it.
    code = "import ngquic, ngquic.h3, sys; print(sys._is_gil_enabled())"
    result = subprocess.run(
        [sys.executable, "-W", "error", "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout == "False\n"
