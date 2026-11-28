"""Describe the machine a benchmark ran on, without identifying it.

Benchmark results are published in the README, so they record only what
explains the numbers: the CPU model, the operating system and architecture,
the Python version and build, the measured libraries' versions and the date.
They never
record host or user names, paths, the interpreter's location or the kernel
release, which can name a private build; check() refuses results holding a
field for any of them. Standard library only.

    python benchmarks/environment.py               # what this machine records
    python benchmarks/environment.py --self-test
"""

import datetime
import json
import platform
import subprocess
import sys
import sysconfig

# Field names, compared in lower case, that identify the machine or its user.
FORBIDDEN = frozenset(
    {
        "command",
        "cwd",
        "executable",
        "home",
        "hostname",
        "kernel",
        "node",
        "path",
        "python_executable",
        "release",
        "uname",
        "user",
        "username",
    }
)


def check(results: object) -> None:
    """Raise ValueError if a forbidden field appears anywhere in ``results``."""
    pending = [results]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            found = FORBIDDEN.intersection(str(key).lower() for key in item)
            if found:
                raise ValueError(f"identifying fields in results: {sorted(found)}")
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def cpu_model() -> str:
    if sys.platform == "darwin":
        result = subprocess.run(
            ("sysctl", "-n", "machdep.cpu.brand_string"),
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    # On Linux, platform.processor() names only the architecture.
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as cpuinfo:
            for line in cpuinfo:
                key, _, value = line.partition(":")
                if key.strip() == "model name" and value.strip():
                    return value.strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def collect(versions: dict[str, str]) -> dict:
    """Return the environment of a run that measures ``versions``."""
    environment = {
        "date": datetime.datetime.now(datetime.timezone.utc).date().isoformat(),
        "cpu": cpu_model(),
        "os": f"{platform.system()} {platform.machine()}",
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "free_threaded": bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
        "versions": versions,
    }
    check(environment)
    return environment


def self_test() -> None:
    environment = collect({"library": "1.0"})
    assert environment["versions"] == {"library": "1.0"}
    for identifying in ({"hostname": "box"}, {"runs": [{"meta": {"Path": "/"}}]}):
        try:
            check({"environment": environment, **identifying})
        except ValueError:
            continue
        raise AssertionError(f"accepted {identifying}")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
    else:
        print(json.dumps(collect({}), indent=2))
