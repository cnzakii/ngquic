"""tests/interop/runner/compare.py, which gates the interop runner jobs."""

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent / "runner" / "compare.py"


def result(
    path: Path, clients: list[str], servers: list[str], *cells: dict[str, str]
) -> Path:
    """A runner --json file: one {test: result} per pair, servers varying fastest."""
    tests = [
        [{"name": name, "result": value} for name, value in cell.items()]
        for cell in cells
    ]
    path.write_text(
        json.dumps({"clients": clients, "servers": servers, "results": tests})
    )
    return path


def compare(
    *args: Path | str, summary: Path | None = None
) -> subprocess.CompletedProcess[str]:
    # Windows cannot start a process without its environment.
    env = {**os.environ, "GITHUB_STEP_SUMMARY": str(summary or os.devnull)}
    return subprocess.run(
        [sys.executable, SCRIPT, *map(str, args)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_only_what_passed_on_the_base_regresses(tmp_path: Path) -> None:
    run = result(
        tmp_path / "run.json",
        ["ngquic", "ngquic-base"],
        ["quic-go"],
        {
            "handshake": "succeeded",
            "transfer": "failed",
            "rebind-port": "failed",
            "ecn": "unsupported",
        },
        {
            "handshake": "succeeded",
            "transfer": "succeeded",
            "rebind-port": "failed",
            "ecn": "unsupported",
        },
    )
    summary = tmp_path / "summary.md"

    assert compare(run).stdout == "transfer\n"
    report = compare(run, "--report", summary=summary)
    assert report.returncode == 1
    assert "transfer regressed with client ngquic and server quic-go" in report.stderr
    assert (
        "| ngquic | quic-go | 1 | transfer, rebind-port | 1 | transfer | - |"
        in summary.read_text()
    )


def test_a_passing_retry_clears_a_regression(tmp_path: Path) -> None:
    run = result(
        tmp_path / "run.json",
        ["quic-go"],
        ["ngquic", "ngquic-base"],
        {"transfer": "failed"},
        {"transfer": "succeeded"},
    )
    retry = result(
        tmp_path / "retry.json", ["quic-go"], ["ngquic"], {"transfer": "succeeded"}
    )

    report = compare(run, retry, "--report")
    assert (report.returncode, report.stdout) == (0, "\n")


def test_without_a_baseline_nothing_regresses(tmp_path: Path) -> None:
    run = result(tmp_path / "run.json", ["ngquic"], ["quiche"], {"transfer": "failed"})
    summary = tmp_path / "summary.md"

    report = compare(run, "--report", summary=summary)
    assert (report.returncode, report.stdout) == (0, "\n")
    assert summary.read_text().startswith("No baseline")


def test_a_saved_summary_is_the_next_runs_baseline(tmp_path: Path) -> None:
    first = result(
        tmp_path / "first.json",
        ["ngquic", "quiche"],
        ["ngquic"],
        {"transfer": "succeeded", "zerortt": "failed"},
        {"transfer": "succeeded", "zerortt": "failed"},
    )
    saved = tmp_path / "saved.json"
    assert compare(first, "--save", saved).returncode == 0

    later = result(
        tmp_path / "later.json",
        ["ngquic", "quiche"],
        ["ngquic"],
        {"transfer": "succeeded", "zerortt": "succeeded"},
        {"transfer": "failed", "zerortt": "failed"},
    )
    summary = tmp_path / "summary.md"
    report = compare(later, "--previous", saved, "--report", summary=summary)
    assert (report.returncode, report.stdout) == (1, "transfer\n")
    assert "| ngquic | ngquic | 2 | - | 0 | - | zerortt |" in summary.read_text()


def test_a_pair_without_results_keeps_its_previous_ones(tmp_path: Path) -> None:
    first = result(
        tmp_path / "first.json",
        ["ngquic", "quiche"],
        ["ngquic"],
        {"transfer": "succeeded"},
        {"transfer": "succeeded"},
    )
    saved = tmp_path / "saved.json"
    compare(first, "--save", saved)
    # quiche's job timed out and left nothing this time.
    later = result(
        tmp_path / "later.json", ["ngquic"], ["ngquic"], {"transfer": "failed"}
    )
    again = tmp_path / "again.json"

    report = compare(later, "--previous", saved, "--save", again)

    assert report.stdout == "transfer\n"
    assert ["quiche", "ngquic", "transfer", "succeeded"] in json.loads(
        again.read_text()
    )
