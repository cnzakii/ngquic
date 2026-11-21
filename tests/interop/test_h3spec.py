"""h3spec, an independent checker of QUIC and HTTP/3 error handling.

h3spec (https://github.com/kazu-yamamoto/h3spec) sends malformed frames and
streams to a server over UDP and checks the error it closes with. CI installs
it for the ``h3spec`` job; elsewhere this test skips.
"""

import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

H3SPEC = shutil.which("h3spec")
PEER = Path(__file__).parent / "peer.py"
CERTS = Path(__file__).parents[1] / "support" / "certs"

# h3spec cases that fail today, and why. The test fails when a case outside
# this table fails or a case in it passes, so the table stays current.
EXPECTED_FAILURES = {
    "treats a repeated setting identifier as an error whatever its value": (
        "nghttp3 1.19.0 keeps the last value of a repeated setting"
    ),
    "MUST send H3_ID_ERROR if CANCEL_PUSH names a push ID not allowed": (
        "nghttp3 1.19.0 answers H3_FRAME_UNEXPECTED"
    ),
    "MUST send H3_ID_ERROR if MAX_PUSH_ID goes down": (
        "nghttp3 1.19.0 answers H3_FRAME_ERROR"
    ),
    "MUST send H3_FRAME_ERROR if MAX_PUSH_ID has octets after its push ID": (
        "nghttp3 1.19.0 ignores bytes after the push ID"
    ),
    "MUST NOT buffer an over-long frame on a control stream": (
        "nghttp3 1.19.0 skips unknown frames of any length"
    ),
}


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.mark.h3spec
@pytest.mark.skipif(H3SPEC is None, reason="h3spec is not installed")
def test_h3spec_failures_are_the_known_ones(tmp_path):
    assert H3SPEC is not None
    port = free_port()
    server = subprocess.Popen(
        [
            sys.executable,
            PEER,
            "server",
            "--h3",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--cert",
            CERTS / "cert.pem",
            "--key",
            CERTS / "key.pem",
            "--root",
            tmp_path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert server.stdout is not None
        assert server.stdout.readline().startswith(b"listening")
        result = subprocess.run(
            [H3SPEC, "127.0.0.1", str(port), "--no-validate"],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    finally:
        server.terminate()
        _, errors = server.communicate(timeout=10)

    # The numbered failure summary reads the same whatever the locale.
    failed = set(
        re.findall(
            r"^\s+\d+\) (?:QUIC|HTTP/3) servers (.+) \[[^\]]+\]$", result.stdout, re.M
        )
    )
    assert re.search(r"\d+ examples", result.stdout), result.stdout + result.stderr
    assert failed == set(EXPECTED_FAILURES), errors
