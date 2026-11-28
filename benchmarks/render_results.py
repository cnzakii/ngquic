"""Render the README's performance tables from compare.py's results.

compare.py --readme writes everything between the README's benchmark markers
from here, so that part of the README is never edited by hand.
"""

START, END = "<!-- benchmark:start -->", "<!-- benchmark:end -->"
STACKS = ("ngquic", "aioquic")
PROTOCOLS = ("QUIC", "HTTP/3")
LOWER_IS_BETTER = {"P50 µs", "P99 µs", "wire bytes/request", "KiB/connection"}
# One table per dimension, so each compares like with like:
# (title, lower is better, [(scenario, metric, row label)]).
TABLES = [
    ("Handshakes per second", False, [("handshakes", "handshakes/s", "")]),
    (
        "Bulk transfer, Gbit/s",
        False,
        [("download", "Gbit/s", "download"), ("upload", "Gbit/s", "upload")],
    ),
    (
        "Requests per second",
        False,
        [
            ("requests, 1 in flight", "requests/s", "1 in flight"),
            ("requests, 64 in flight", "requests/s", "64 in flight"),
        ],
    ),
    (
        "Request latency, µs",
        True,
        [
            ("requests, 1 in flight", "P50 µs", "P50, 1 in flight"),
            ("requests, 1 in flight", "P99 µs", "P99, 1 in flight"),
            ("requests, 64 in flight", "P50 µs", "P50, 64 in flight"),
            ("requests, 64 in flight", "P99 µs", "P99, 64 in flight"),
        ],
    ),
    ("Datagrams per second", False, [("datagrams", "datagrams/s", "")]),
    (
        "Memory per idle connection, KiB",
        True,
        [("idle connections", "KiB/connection", "")],
    ),
    (
        "Bytes on the wire per request",
        True,
        [
            ("requests, 1 in flight", "wire bytes/request", "1 in flight"),
            ("requests, 64 in flight", "wire bytes/request", "64 in flight"),
        ],
    ),
]
# The README shows the first tables; the rest fold under this summary.
SHOWN = 3
SUMMARY = "Request latency, datagrams, memory, and bytes on the wire"


def number(value: float) -> str:
    return f"{value:,.0f}" if value >= 100 else f"{value:#.3g}"


def advantage(row: dict) -> float:
    """How many times better ngquic does, whichever way the metric points."""
    ratio = row["ngquic"] / row["aioquic"]
    return 1 / ratio if row["metric"] in LOWER_IS_BETTER else ratio


def table(title: str, lower: bool, rows: list[tuple[str, dict]]) -> list[str]:
    stacks = [stack for stack in STACKS if stack in rows[0][1]]
    both = len(stacks) == len(STACKS)
    header = ["", *stacks, *(["ngquic advantage"] if both else [])]
    lines = [
        f"**{title}** ({'lower' if lower else 'higher'} is better)",
        "",
        "| " + " | ".join(header) + " |",
        "|---|" + "---:|" * (len(header) - 1),
    ]
    for label, row in rows:
        cells = [number(row[stack]) for stack in stacks]
        if both:
            cells.append(f"{advantage(row):.1f}\N{MULTIPLICATION SIGN}")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return [*lines, ""]


def environment_line(env: dict) -> str:
    python = f"{env['implementation']} {env['python']}"
    if env["free_threaded"]:
        python += " free-threaded"
    parts = [
        *(f"{name} {version}" for name, version in env["versions"].items()),
        python,
        env["cpu"],
        env["os"],
        env["date"],
    ]
    return f"_Environment: {' · '.join(parts)}_"


def render(results: dict) -> str:
    """Return the Markdown tables and environment line for ``results``."""
    found = {(r["protocol"], r["scenario"], r["metric"]): r for r in results["results"]}
    tables = []
    for title, lower, entries in TABLES:
        rows = [
            (f"{protocol}, {label}" if label else protocol, found[key])
            for protocol in PROTOCOLS
            for scenario, metric, label in entries
            if (key := (protocol, scenario, metric)) in found
        ]
        tables.append(table(title, lower, rows) if rows else [])
    lines = [line for lines in tables[:SHOWN] for line in lines]
    if folded := [line for lines in tables[SHOWN:] for line in lines]:
        lines += ["<details>", f"<summary>{SUMMARY}</summary>", "", *folded]
        lines += ["</details>", ""]
    return "\n".join([*lines, environment_line(results["environment"])]) + "\n"


def replace_marked(document: str, section: str) -> str:
    """Return ``document`` with the text between the markers replaced."""
    before, start, rest = document.partition(START)
    _, end, after = rest.partition(END)
    if not start or not end:
        raise ValueError(f"{START} and {END} not found")
    return f"{before}{START}\n\n{section}\n{END}{after}"
