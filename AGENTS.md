# ngquic Repository Guidance

Read [CONTRIBUTING.md](CONTRIBUTING.md) first: its setup, checks, code
conventions and test rules apply to every change. This file adds what an
agent needs beyond them.

## Product Boundary

- `ngquic` is a Sans-I/O QUIC library for Python (RFC 8999, 9000, 9001,
  9002, 9221, 9287, 9368, 9369), implemented as a Cython binding over the
  vendored ngtcp2 and AWS-LC sources. HTTP/3 (RFC 9114, 9204, 9218, 9220, 9297, 9412) lives in
  `ngquic.h3` over the vendored nghttp3; the QUIC API stays usable without
  it. Other application protocols build on it and do not live here.
- ngtcp2 owns connection and stream state, packet protection, loss recovery,
  congestion control, flow control windows, PMTUD, key update and path
  validation. AWS-LC owns the TLS 1.3 handshake. Do not reimplement native
  behavior in the binding without a demonstrated need.
- The binding owns what ngtcp2 leaves to its application: the endpoint
  (connection ID demultiplexing, Retry, address validation tokens, version
  negotiation, stateless reset), keeping unacknowledged stream data, flow
  control credit, the closing and draining periods, and timers expressed on
  the caller's clock. It also owns Python-facing objects, event and error
  translation, buffer lifetimes, configuration mapping, type information and
  packaging.
- Sockets, event loops, GSO/GRO and ECN system calls, DNS, certificate
  storage policy and application timeouts stay outside this package: callers
  pass datagrams, addresses and `now` in, and send what comes out.
  `TLSContext.load_default_certs()` trusts only what `ssl` trusts by default,
  read through the `ssl` module, so its meaning matches `ssl.SSLContext`.

## Repository Map

- `src/ngquic`: the QUIC package. Python API (`config`, `enums`, `types`,
  `exceptions`, `events`) and stubs at the top. The native module `_core.pyx`
  is the only one that links ngtcp2 and AWS-LC; it and `_core.pxd` only list
  the fragments in `_quic/`, where each class has its declaration (`.pxd`:
  fields and C methods) beside its implementation (`.pxi`), as uvloop and
  asyncpg do. `_core.pxd` is the C interface for protocol layers:
  `BaseConnection` fields, stream protocol hooks and the ngtcp2 calls they
  may make. C library declarations live in `includes/` (`ngtcp2.pxd`,
  `glue.h`).
- `src/ngquic/h3`: the HTTP/3 package, the same shape. Its native module
  `_core.pyx` (fragments in `_h3/`, nghttp3 declarations in `includes/`)
  links only nghttp3 and subclasses `BaseConnection`. Dependencies point one
  way: `h3` imports QUIC, QUIC imports `h3` only inside `connect()` and
  `accept()` when `h3=` is given.
- Inside a fragment: class docstring, construction, public properties and
  methods in `# ----` sections in the same order as the `.pyi`, then hooks
  and private C helpers; the `.pxd` follows the `.pxi` order.
- `vendor/ngtcp2`, `vendor/nghttp3`, `vendor/aws-lc`: pinned upstream Git
  submodules; update them as dependencies, never by editing vendored source
  in place.
- `.github/workflows`: `ci.yml` runs the local gate, the tests on every
  supported Python and platform, the sanitizers and coverage, and on pull
  requests the interop runner against the base branch's endpoint, and runs
  monthly as well; `interop.yml` runs main against every interop runner
  implementation weekly, both through the composite action in
  `.github/actions/interop-runner`; `codspeed.yml` tracks the benchmarks;
  `release.yml` builds
  wheels with cibuildwheel (configured in `pyproject.toml`) and publishes
  `v*` tags to PyPI. Dependabot updates uv and Actions pins monthly; the
  vendored submodules are updated by hand to release tags.
- `tests`: `quic/` and `h3/` hold behavior tests by feature; `rfc/quic/` and
  `rfc/h3/` hold one file per RFC (`test_rfcNNNN_<topic>.py`) whose module
  docstring names the sections it covers; `interop/` runs aioquic and
  aioquic.h3 as in-process peers, and holds `peer.py`, ngquic on real UDP
  sockets, which h3spec (`test_h3spec.py`) and the QUIC interop runner image
  (`runner/`, with `compare.py`, which judges the runner's results) drive; `robustness/` covers error paths and resource
  cleanup; `benchmarks/` holds the CodSpeed workloads, which run once as
  plain tests without `--codspeed`. Shared helpers live in `support/`
  (`network.Network`, the in-memory link on a virtual clock; `h3.H3Network`;
  aioquic peers and raw HTTP/3 frames; `certs/`, fixed test-only
  certificates that `generate.sh` recreates); test files import helpers only
  from `support`, never from each other, and fixtures live in `conftest.py`.
- `benchmarks/compare.py`: ngquic against aioquic, by hand, not in CI.
- `*.local.md`: untracked design notes, including the ngtcp2 and nghttp3 API
  coverage tables with the reason each hidden or unused API stays hidden.

## Change Rules

- Read affected callers, tests, exports, stubs and configuration before
  editing. Update runtime behavior, `__init__.py` exports, `.pyi` files and
  tests together when a Python contract changes.
- Use the ngtcp2 public API the way its examples and mature users (curl's
  `cf-ngtcp2`) do. Back protocol and ngtcp2 claims with RFCs, ngtcp2
  documentation or pinned source; treat quinn, quiche and aioquic as observed
  practice, not authority.
- When ngtcp2 exposes a capability that the public API does not, record the
  reason in the API coverage notes.
- Native callbacks run inside ngtcp2 or AWS-LC. They never raise: they store
  the exception and return an error code, and the public method that drove
  them re-raises it. Releasing native state calls back only the qlog writer
  (`ngtcp2_conn_del()` writes the final record), so only it checks for a
  released connection; `nghttp3_conn_del()` and `SSL_free()` call none of
  ours, and every other callback runs inside a read, write or timer call
  that needs a live connection.
- ngtcp2 and nghttp3 allocate through `PyMem_Raw*`. Store a Python object
  where the binding owns it before handing its pointer to native code
  (stream user data): a `MemoryError` in between would leave the library a
  dangling pointer. `tests/robustness/test_allocation_failure.py` fails each
  allocation of a call in turn.
- Treat pointers ngtcp2 hands to callbacks as callback-scoped unless the
  upstream API guarantees a longer lifetime. Stream data passed to ngtcp2
  stays alive until `acked_stream_data_offset` covers it.
- Ruff and ty do not validate Cython source. Binding changes must also pass
  `cython-lint`, compile, and run the relevant tests.
- Keep generated C files, build output, local environments, editor state,
  temporary reports and personal instructions out of version control.

Work is complete only after the relevant focused tests and the local gate in
CONTRIBUTING.md pass.
