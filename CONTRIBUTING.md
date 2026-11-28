# Contributing to ngquic

Bug fixes, tests, documentation, API feedback, performance improvements, and
changes that simplify the binding are welcome. Please open an issue before
adding public API or changing protocol behavior.

## Development Setup

You need Git, uv, CMake and a C compiler supported by CPython: Visual Studio
Build Tools on Windows, Xcode Command Line Tools on macOS, or the platform
compiler toolchain on Linux. AWS-LC also needs NASM on `PATH` on Windows
x86_64, and the clang-cl toolset (Visual Studio's "C++ Clang tools"
component, selected with `CMAKE_ARGS="-T ClangCL"`) on Windows Arm64. Clone
the ngtcp2, nghttp3 and AWS-LC submodules with the repository:

```console
git clone --recurse-submodules <repository-url> ngquic
cd ngquic
uv sync --locked
uv run --locked pre-commit install
```

`.python-version` sets the development interpreter. Building from source
compiles AWS-LC and ngtcp2 statically into `ngquic._core` and nghttp3
into `ngquic.h3._core`; to link a system
AWS-LC instead, pass `-C cmake.define.EMBERLYN_SYSTEM_AWS_LC=ON` to the build.

## Checks

Run the same static checks as the pre-commit hook, then the tests and both
distribution formats:

```console
uv run --locked pre-commit run --all-files
uv run --locked pytest
uv build
```

CI runs the same checks and adds what a laptop cannot: the tests on every
supported Python and platform, in Alpine for the musllinux wheels, and under
AddressSanitizer and UBSan, a coverage floor over the traced Cython modules,
a wheel rebuilt from the sdist,
[h3spec](https://github.com/kazu-yamamoto/h3spec) against the interop peer
(a failure outside its expected-failure table fails), and on pull requests
the [QUIC interop runner](https://github.com/quic-interop/quic-interop-runner)
against other implementations, with the base branch's endpoint beside it:
a test fails the job only if it passed on the base and fails twice here.
The interop jobs are not required checks; a weekly run against every
implementation catches regressions on main. Changes to the build or the
vendored libraries also build every release wheel.

The coverage floor, `fail_under` in `pyproject.toml`, is the measured total
rounded down, minus one point, and never below 90. The pull request that
raises the total raises the floor to match; the floor is never lowered.
Codecov likewise fails a pull request that lowers the total by more than one
point from its base.

Add or update tests for observable behavior changes. Keep public exports,
type stubs, documentation and native behavior synchronized.

## Documentation

The site is built with Zensical from `zensical.toml`. English pages live in
`docs/en` and are the source; every other language mirrors them page for page
under `docs/<lang>`, as [docs/translating/README.md](docs/translating/README.md)
describes. The API reference is generated from the type stubs, and tutorial
code is included from `examples/`, which `tests/test_examples.py` runs. Build
every language into `site/` and preview them together:

```console
uv run --locked --group docs python docs/build.py --strict
python -m http.server --directory site
```

Theme colors, fonts and the logo live in `docs/overrides/assets`.

## Code Conventions

### Scope

- Derive behavior from the QUIC RFCs and the ngtcp2 contract. When a change
  follows an RFC section, ngtcp2 documentation or another implementation,
  cite it in the pull request.
- Prefer the standard library and existing dependencies. Add a dependency
  only for a current need.
- Before 1.0, an incorrect design is replaced directly, without
  compatibility aliases or shims.

### Boundaries

- Validate once where data enters from outside: the arguments of public
  methods and configuration. Datagrams from the network go to ngtcp2, which
  validates them; do not parse packets in the binding except where the
  endpoint must route them before a connection exists.
- Inside the binding, trust the value. Do not add checks that restate type
  hints unless they stabilize a public error contract.
- Avoid copies and repeated conversions on per-packet and per-stream paths:
  hold `bytes` instead of copying them, write output into preallocated
  `bytes`, and build events in C without calling their Python constructors.

### Naming and Data

- Public names follow Python conventions and describe QUIC behavior, not C
  binding mechanics. Methods mirror the standard library where one exists,
  such as `TLSContext.load_cert_chain` from `ssl.SSLContext`.
- Protocol activity is reported as events returned by `Connection.events()`,
  not as callbacks. A callback is acceptable only where the caller must
  answer synchronously inside the handshake; discuss it first.
- Configuration is frozen dataclasses validated when a connection or endpoint
  is created. Events are Cython `cdef class` types with a `.pyi` stub.
- Times are monotonic seconds as `float`, on the caller's clock. Durations in
  configuration are seconds.

### Style

- Ruff formats and lints Python, ty checks types, and cython-lint checks
  Cython.
- Order class members: class attributes, `__init__` and alternate
  constructors, properties, public methods, protocol methods such as
  `__repr__`, then private methods.
- Separate the logical steps of a function with a single blank line.
- Comments state what the code does, or why when the code cannot show it.
  They do not discuss alternatives or history. Docstrings state the
  contract: what a method returns, raises and owns.

## Tests

A test states one claim about a contract and fails when that claim breaks.

### What to Test

- Start from a contract the code owns: a public docstring, an RFC
  requirement the binding is responsible for, a lifecycle promise, or an
  error the caller can act on.
- Name the plausible wrong implementation the test would catch; if no
  realistic bug fails it, do not write it.
- Do not test ngtcp2 or AWS-LC internals, private helpers, or annotation
  spelling. Do test that the binding wires them correctly.
- Take edge cases from the input domain and the states the contract defines:
  boundaries, lifecycle states, loss and reordering, and values another QUIC
  implementation produces.

### Tests Never Justify Defensive Code

Do not add guards, `isinstance` checks or fallback branches to `src` so that
a test passes with an impossible input.

### How to Write a Test

- Name the test as its claim:
  `test_restarted_server_resets_the_client_statelessly`.
- Separate arrange, act and assert with single blank lines, and assert the
  whole observable result with equality where possible.
- Use `pytest.raises` with the specific exception and a `match` on the part
  the caller relies on, and `pytest.mark.parametrize` with readable ids for
  one rule over many inputs.
- Connections talk over the shared in-memory network on a virtual clock
  that jumps to the next timer: wait for an event, let time pass, assert
  exactly the time a timeout promises, and inject loss there. Real sockets
  and the real clock are for what only the system can show, such as UDP
  socket options.
- Interoperability tests run aioquic in the same process on the same virtual
  clock. Add one when a change affects bytes on the wire. aioquic is an
  optional dependency (the `interop` group): a test file that needs it starts
  with `pytest.importorskip("aioquic")` so free-threaded builds, where it does
  not install, still run the rest.
- ngtcp2 and nghttp3 allocate through Python's raw allocator, so the
  allocation-failure tests fail one allocation of a call at a time with CPython's `_testcapi.set_nomemory()`, inside or outside
  the native libraries. uv-managed interpreters leave `_testcapi` out and skip
  these tests; CI's sanitizer and coverage jobs run them on setup-python's
  interpreter, and locally `--python` with a python.org or Homebrew build
  does.
- Put a test where its claim comes from: `tests/quic` or `tests/h3` for a
  documented behavior, `tests/rfc/...` for an RFC requirement, citing the
  section in the module docstring. A strict `xfail` with
  `reason="RFC NNNN S.S: ..."` records a requirement ngquic does not meet
  yet.
- Warnings are errors. For a contract whose failure is costly, such as a
  lifecycle or a wire format, break the code once by hand and confirm that a
  test fails.

## Benchmarks

CodSpeed measures the benchmarks in `tests/benchmarks` on every pull request
and reports changes against `main`. Run them locally with:

```console
uv run --locked pytest tests/benchmarks --codspeed
```

The comparison the README publishes, `benchmarks/compare.py`, runs ngquic
against aioquic: a client and a server of one library joined in memory on a
virtual clock, so the numbers are protocol work on one core, without sockets
or an event loop. It measures handshakes, bulk transfer, requests per second
with their latency, datagrams, memory per idle connection and bytes on the
wire, each the median of five rounds after a warm-up; its module docstring
lists the terms both libraries are held to.

`compare.py --readme` writes the README's tables and environment line
between `<!-- benchmark:start -->` and `<!-- benchmark:end -->`; never edit
them by hand. Measure a committed checkout on an otherwise idle machine:

```console
uv run --locked --group compare python benchmarks/compare.py --readme
```

`benchmarks/environment.py` records the environment with the results: the
CPU model, the operating system and architecture, the Python version and
implementation and whether it is free-threaded, the measured libraries'
versions and the date. It never records host or user names, paths, the
interpreter's location or the kernel release, and `--readme` refuses a
partial run.

Refresh the results for each release, and include before and after
measurements in a pull request that claims a performance change.

## Releases

ngquic publishes final releases as `X.Y.Z`: increment `X` for incompatible
public changes after 1.0, `Y` for backward-compatible functionality (and,
before 1.0, intentional incompatible changes), and `Z` for fixes. Every
release updates `src/ngquic/_version.py` and records the vendored ngtcp2,
nghttp3 and AWS-LC versions. Its CHANGELOG section, dated, opens the GitHub
release notes, above the list of pull requests, so write it for users;
`python3 .github/scripts/release_notes.py X.Y.Z` prints the notes as they
will appear, and the release stops before publishing if the section is
missing.

Wheels are built for 64-bit CPython on Linux (manylinux and musllinux),
macOS and Windows, each on x86_64 and Arm64; 32-bit wheels are not built.

By contributing, you agree that your contribution is licensed under the
project's [MIT License](LICENSE).
