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

CI runs the same checks, the tests on every supported Python and platform
and under AddressSanitizer and UBSan, and rebuilds a wheel from the sdist.
Its `h3spec` job checks QUIC and HTTP/3 error handling with
[h3spec](https://github.com/kazu-yamamoto/h3spec) against `tests/interop/peer.py`;
a failure outside the expected-failure table in `tests/interop/test_h3spec.py`
fails it. On pull requests its `interop` jobs run the
[QUIC interop runner](https://github.com/quic-interop/quic-interop-runner)
between ngquic's endpoint image (`tests/interop/runner/`) and quic-go,
quiche, msquic and picoquic in both roles, with the base branch's image
beside it; `tests/interop/runner/compare.py` fails a job only for a test that
passed on the base and fails twice here. They are not required checks. The
weekly `interop.yml` runs main against every implementation the runner lists
and fails on a test that passed in the previous week's run.
Its coverage job traces the Cython modules
(`-C cmake.define.EMBERLYN_COVERAGE=ON`) and fails below the `fail_under`
floor in `pyproject.toml`. CodSpeed measures `tests/benchmarks` on every pull
request; run them locally with `uv run --locked pytest tests/benchmarks
--codspeed`.
`benchmarks/compare.py` compares the protocol engine with aioquic over QUIC
and HTTP/3 (throughput, requests per second with latency, handshakes,
datagrams, memory per idle connection); run it by hand with
`uv run --locked --group compare python benchmarks/compare.py`.
Changes to the build or the vendored libraries also build every release
wheel with cibuildwheel, configured in `pyproject.toml`.

Add or update tests for observable behavior changes. Keep public exports,
type stubs, documentation and native behavior synchronized. Include
reproducible measurements for performance claims.

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
- Connections talk over `support.network.Network`, an in-memory link on a
  virtual clock that jumps to the next timer. Wait for an event with `run(until)`,
  let time pass with `advance(seconds)`, and assert exactly the time a
  timeout promises. Inject loss with `drop`.
- Interoperability tests run aioquic in the same process on the same virtual
  clock. Add one when a change affects bytes on the wire. aioquic is an
  optional dependency (the `interop` group): a test file that needs it starts
  with `pytest.importorskip("aioquic")` so free-threaded builds, where it does
  not install, still run the rest.
- ngtcp2 and nghttp3 allocate through Python's raw allocator, so
  `tests/robustness/test_allocation_failure.py` fails one allocation of a
  call at a time with CPython's `_testcapi.set_nomemory()`, inside or outside
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

## Releases

ngquic publishes final releases as `X.Y.Z`: increment `X` for incompatible
public changes after 1.0, `Y` for backward-compatible functionality (and,
before 1.0, intentional incompatible changes), and `Z` for fixes. Every
release updates `src/ngquic/_version.py` and records the vendored ngtcp2,
nghttp3 and AWS-LC versions.

By contributing, you agree that your contribution is licensed under the
project's [MIT License](LICENSE).
