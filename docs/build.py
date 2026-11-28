"""Build the documentation: English into site/, then each translation.

zensical.toml configures the English site. Every docs/translating/<lang>.toml
names a translation in docs/<lang>/; its site is built from the same
configuration with that file's values applied, into site/<lang>/. Arguments
are passed to every ``zensical build``, so ``--strict`` checks all languages.
Needs Python 3.11 or newer (``tomllib``); the docs build uses .python-version.
"""

import subprocess
import sys
from pathlib import Path
from typing import Any

import tomli_w
import tomllib

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "zensical.toml"
TRANSLATIONS = ROOT / "docs" / "translating"


def translated(
    config: dict[str, Any], lang: str, values: dict[str, Any]
) -> dict[str, Any]:
    """Return the configuration of one translation."""
    project = config["project"]
    project["docs_dir"] = f"docs/{lang}"
    project["site_dir"] = f"site/{lang}"
    project["site_url"] = project["site_url"].rstrip("/") + f"/{lang}/"
    project["site_description"] = values["site_description"]
    project["theme"]["language"] = lang

    sections = values["sections"]

    def label(items: list[Any]) -> list[Any]:
        out = []
        for item in items:
            if isinstance(item, dict):
                ((name, children),) = item.items()
                out.append({sections[name]: label(children)})
            else:
                out.append(item)
        return out

    project["nav"] = label(project["nav"])
    toggles = values["palette"]["toggle_names"]
    for option, name in zip(project["theme"]["palette"], toggles, strict=True):
        option["toggle"]["name"] = name
    return config


def build(config_file: Path, args: list[str]) -> None:
    command = ["zensical", "build", "-f", str(config_file), *args]
    subprocess.run(command, cwd=ROOT, check=True)


def main(args: list[str]) -> None:
    # The English build replaces site/, so it runs before the translations.
    build(CONFIG, args)
    for values_file in sorted(TRANSLATIONS.glob("*.toml")):
        lang = values_file.stem
        config = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
        values = tomllib.loads(values_file.read_text(encoding="utf-8"))
        # Written beside zensical.toml, since relative paths resolve from it.
        generated = ROOT / f".zensical.{lang}.toml"
        generated.write_text(
            tomli_w.dumps(translated(config, lang, values)), encoding="utf-8"
        )
        try:
            build(generated, args)
        finally:
            generated.unlink()


if __name__ == "__main__":
    main(sys.argv[1:])
