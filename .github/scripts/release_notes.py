"""Print a version's CHANGELOG.md section as GitHub release notes.

GitHub keeps the line breaks of release notes, so wrapped paragraphs and list
items are joined into single lines. Exits non-zero if the section is missing
or empty. Standard library only.

    python3 .github/scripts/release_notes.py 1.2.3
    python3 .github/scripts/release_notes.py --self-test
"""

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[2] / "CHANGELOG.md"
# A line that starts a block of its own instead of continuing the one above:
# a heading, list item, table row, quote or code fence.
BLOCK = re.compile(r"#|\s*(?:[-*+] |\d+[.)] |\||>|```)")


def section(changelog: str, version: str) -> str | None:
    """Return the body of ``## [version] - date``, or None if it is empty."""
    match = re.search(
        rf"^## \[{re.escape(version)}\] - [^\n]*\n(.*?)(?=^## \[|\Z)",
        changelog,
        re.M | re.S,
    )
    return (match.group(1).strip() or None) if match else None


def unwrap(text: str) -> str:
    """Join each wrapped line onto the line it continues."""
    lines: list[str] = []
    fenced = False
    for line in text.splitlines():
        previous = lines[-1] if lines else ""
        if (
            fenced
            or not line.strip()
            or not previous.strip()
            or BLOCK.match(line)
            or re.match(r"#|\s*(?:\||```)", previous)
        ):
            lines.append(line)
        else:
            lines[-1] += " " + line.strip()
        if line.lstrip().startswith("```"):
            fenced = not fenced
    return "\n".join(lines)


def self_test() -> None:
    changelog = """# Changelog

## [Unreleased]

## [1.1.0] - 2026-01-02

Built on
libexample 2.0.

### Added

- A list item
  wrapped once.
  - A nested item
    wrapped.
1. A numbered item
   wrapped.

```console
pip install
example
```
| a | b |
| - | - |

## [1.0.0] - 2026-01-01
"""
    expected = """Built on libexample 2.0.

### Added

- A list item wrapped once.
  - A nested item wrapped.
1. A numbered item wrapped.

```console
pip install
example
```
| a | b |
| - | - |"""
    body = section(changelog, "1.1.0")
    assert body is not None
    assert unwrap(body) == expected, unwrap(body)
    assert section(changelog, "1.0.0") is None
    assert section(changelog, "1.0") is None
    assert section(changelog, "Unreleased") is None


def main(argv: list[str]) -> int:
    if argv == ["--self-test"]:
        self_test()
        return 0
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    body = section(CHANGELOG.read_text(encoding="utf-8"), argv[0])
    if body is None:
        print(f"{CHANGELOG.name} has no section for {argv[0]}", file=sys.stderr)
        return 1
    print(unwrap(body))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
