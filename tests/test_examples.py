"""The scripts in examples/, which the Learn pages include, print what they show."""

import runpy
import sys
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).parents[1] / "examples"


ECHO = (
    "HandshakeCompleted(alpn_protocol='echo', session_resumed=False, "
    "early_data_accepted=False)\n"
    "server received b'hello' on stream 0\n"
    "StreamDataReceived(stream_id=0, data=b'HELLO', end_stream=True, early=False)\n"
)


UDP_BATCHED = pytest.param(
    "udp_batched.py",
    ECHO,
    id="udp-batched",
    marks=pytest.mark.skipif(
        sys.platform not in ("linux", "darwin"),
        reason="ngquic.udp is built on Linux and macOS",
    ),
)


@pytest.mark.parametrize(
    ("filename", "expected_output"),
    [
        pytest.param("first_handshake.py", ECHO, id="first-handshake"),
        pytest.param(
            "protocol_model.py",
            "client HandshakeCompleted\n"
            "client StreamsAvailable\n"
            "server HandshakeCompleted\n"
            "server HandshakeConfirmed\n"
            "server StreamsAvailable\n"
            "server StreamDataReceived\n"
            "client HandshakeConfirmed\n"
            "client NewTokenReceived\n"
            "client SessionTicketReceived\n"
            "client SessionTicketReceived\n"
            "client StreamDataReceived\n"
            "client StreamClosed\n"
            "client ConnectionTerminated\n"
            "server ConnectionTerminated\n"
            "client CLOSED, server CLOSED 3 PTOs after close()\n"
            "endpoints hold 0\n",
            id="protocol-model",
        ),
        pytest.param("udp_echo.py", ECHO, id="udp"),
        UDP_BATCHED,
        pytest.param(
            "http3_request.py",
            "server received GET /hello\n"
            "client received 200\n"
            "client received body b'Hello over HTTP/3\\n'\n"
            "server saw the client close: APPLICATION_ERROR 0x100\n",
            id="http3",
        ),
    ],
)
def test_example_prints_its_documented_output(
    filename: str,
    expected_output: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The examples import localhost_certs from their own directory.
    monkeypatch.syspath_prepend(str(EXAMPLES))

    runpy.run_path(str(EXAMPLES / filename), run_name="__main__")

    assert capsys.readouterr().out == expected_output
