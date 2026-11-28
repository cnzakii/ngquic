"""Compare QUIC interop runner results with a baseline.

    compare.py RESULT... [--previous SUMMARY] [--save SUMMARY] [--report]
    compare.py RESULT... --unpassed

RESULT files are the runner's --json output; a test passes if any run of it
passed, so a retry adds a file. Runs that name ngquic-base, the pull
request's base run beside it, are the baseline; otherwise --previous gives
the summary an earlier run saved with --save. A test regressed when it passed
in the baseline and not here, so failures the baseline shares, a peer's or
the simulator's, never count.

Prints the regressed tests' names, comma-separated, for run.py --test.
--report also writes a table to the job summary and fails on a regression.
--unpassed prints instead the tests that did not pass, the only ones that
can have regressed, so that the base runs just those.
"""

import argparse
import json
import os
import sys
from pathlib import Path

NAME = "ngquic"
BASE = f"{NAME}-base"
RANK = {None: 0, "unsupported": 1, "failed": 2, "succeeded": 3}

Key = tuple[str, str, str]  # client, server, test
Outcomes = dict[Key, str | None]


def merge(paths: list[Path]) -> Outcomes:
    """Each test's best result over every run of it."""
    merged: Outcomes = {}
    for path in paths:
        data = json.loads(path.read_text())
        # One list of tests per pair, servers varying fastest.
        cells = iter(data["results"])
        for client in data["clients"]:
            for server in data["servers"]:
                for test in next(cells):
                    key = (client, server, test["name"])
                    if key not in merged or RANK[test["result"]] > RANK[merged[key]]:
                        merged[key] = test["result"]
    return merged


def split(merged: Outcomes) -> tuple[Outcomes, Outcomes]:
    """The runs of this change, and those of the base as if they were ngquic's."""
    current: Outcomes = {}
    baseline: Outcomes = {}
    for (client, server, test), result in merged.items():
        if BASE in (client, server):
            client, server = (name.replace(BASE, NAME) for name in (client, server))
            baseline[client, server, test] = result
        else:
            current[client, server, test] = result
    return current, baseline


def table(current: Outcomes, baseline: Outcomes, against: str) -> str:
    def names(tests: list[str]) -> str:
        return ", ".join(tests) or "-"

    lines = [
        f"Compared with {against}." if against else "No baseline: nothing can regress.",
        "",
        "| Client | Server | Passed | Failed | Unsupported | Regressed | Fixed |",
        "|---|---|---|---|---|---|---|",
    ]
    for pair in sorted({key[:2] for key in current}):
        tests = {key[2]: result for key, result in current.items() if key[:2] == pair}
        before = {test: baseline.get((*pair, test)) for test in tests}
        failed = [test for test, result in tests.items() if result in {"failed", None}]
        regressed = [
            t for t in tests if tests[t] != "succeeded" and before[t] == "succeeded"
        ]
        fixed = [
            t
            for t in tests
            if tests[t] == "succeeded" and before[t] not in {"succeeded", None}
        ]
        passed = sum(result == "succeeded" for result in tests.values())
        unsupported = sum(result == "unsupported" for result in tests.values())
        lines.append(
            f"| {pair[0]} | {pair[1]} | {passed} | {names(failed)} | {unsupported} "
            f"| {names(regressed)} | {names(fixed)} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", nargs="+", type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--save", type=Path)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--unpassed", action="store_true")
    args = parser.parse_args()

    current, baseline = split(merge(args.results))
    if args.unpassed:
        unpassed = {
            test for (*_, test), result in current.items() if result != "succeeded"
        }
        print(",".join(sorted(unpassed)))
        return 0
    against = "the base branch" if baseline else ""
    if args.previous:
        baseline = {
            tuple(row[:3]): row[3] for row in json.loads(args.previous.read_text())
        }
        against = "the previous run"
    regressed = {
        key
        for key, result in current.items()
        if result != "succeeded" and baseline.get(key) == "succeeded"
    }
    print(",".join(sorted({test for _, _, test in regressed})))

    if args.save:
        # A pair with no results this time, such as a job that timed out,
        # keeps its previous ones, so the next run still has a baseline.
        pairs = {key[:2] for key in current}
        saved = {k: v for k, v in baseline.items() if k[:2] not in pairs}
        saved.update(current)
        args.save.write_text(
            json.dumps(sorted([*key, result] for key, result in saved.items()))
        )
    if not args.report:
        return 0
    with Path(os.environ.get("GITHUB_STEP_SUMMARY", os.devnull)).open("a") as summary:
        summary.write(table(current, baseline, against))
    for client, server, test in sorted(regressed):
        print(
            f"::error::{test} regressed with client {client} and server {server}",
            file=sys.stderr,
        )
    return 1 if regressed else 0


if __name__ == "__main__":
    sys.exit(main())
