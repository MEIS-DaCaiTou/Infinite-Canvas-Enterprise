# ENV-1B1C-B1-R6 Correction Report

## Scope and baseline

R6 corrects only the six B1 pure-contract findings from the fourth independent
review. It neither starts B2 nor connects a controller, host, child,
supervisor, process command, Batch launcher, or `main.py`.

```text
base=4d9cc4ef3d6a0f6ed956c2dda6303e9cc3b99b89
r5_head=3d95d272e15298f08813df049147f06b967bf3cf
github_ci_verified=false
real_bundled_python_fixture_tests=false
```

## Corrected contract boundaries

1. Invalid ABI, architecture, and manifest-path inputs now use static public
   labels (`python_abi`, `architecture`, `manifest_path`). The detail sanitizer
   therefore cannot replace their registered stable code with
   `ERROR_CONTRACT_INVALID`.
2. `StartupPreflightResult` rejects every schema other than
   `env-1b1c-startup-preflight-v1`; a malformed result cannot be used to build a
   launch context.
3. `ErrorPayload.__post_init__` now verifies the registry definition, schema,
   status, correlation identifier, and sanitized immutable details. Direct
   construction cannot bypass the factory contract or retain a caller-owned
   mutable mapping.
4. Writable-probe `with`/close failures map to
   `WRITABLE_PROBE_CLOSE_FAILED`; final cleanup remains ownership-bound and does
   not remove a foreign replacement.
5. Shared lexical inspection distinguishes `missing`, `regular`, `reparse`, and
   `inspection_failed`. Ordinary missing runtime manifests and Python executables
   reach their respective MISSING codes; dangling links and inspection failures
   remain fail-closed reparse/inspection failures.
6. Launch-context and writable-probe ownership verification read at most
   `expected_length + 1` bytes. Oversized foreign files are unowned and retained.

The release-mismatch pure model also removes its unreachable duplicate stop
ownership branch without changing the frozen state table.

## Verification

The R6 focused B1 suite ran with the existing embedded development interpreter,
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, and `PYTHONDONTWRITEBYTECODE=1`:

```text
focused_passed=195
focused_failed=0
focused_skipped=2
posix_pure_contract_tests_verified=false
```

Focused provenance / PathRoots / current-release / static regressions:

```text
passed=216
failed=0
skipped=3
warnings=2
```

`test_ops_runner.py` and `test_ops_3a_online_update.py` are direct-execution
checks, not pytest collections; each exited `0`. `compileall enterprise tools`
exited `0` with its bytecode cache redirected to a temporary directory.

The same interpreter full-suite comparison remains non-passing:

| target | result | exit |
| --- | --- | --- |
| current Head before the R6 commit | 456 passed, 5 skipped, 4 failed, 8 warnings | 1 |
| detached `origin/main` base | 250 passed, 3 skipped, 6 failed, 8 warnings | 1 |

The four Head failures are a subset of Base's failures: two subprocess imports
of `enterprise` and two embedded-interpreter supervisor probes. The fresh Base
run also had two additional timing-sensitive supervisor failures. Therefore
`branch_regression_delta=0`, but `full_suite_passed=false`; this is local
comparison evidence only, not GitHub CI or bundled-Runtime evidence.

## Audit

The tracked APP_ROOT audit reports:

```text
scanned=91
excluded=251
detected=299
mapped=299
parse_failures=0
uncovered=0
stale=0
digest=464b2eef086b6fea37daf810d3b9f0551de652763f23028df799f8affb81e1ab
```

`W26` continues to own launch-context persistent runtime control/diagnostic
state; `W42` continues to own the writable-root probe primitive. R6 changes no
flow mapping or digest.

## R6 closure self-assessment

```text
R5_REVIEW_BLOCKER_01_closed=true
R5_REVIEW_BLOCKER_02_closed=true
R5_REVIEW_BLOCKER_03_closed=true
R5_REVIEW_BLOCKER_04_closed=true
R5_REVIEW_BLOCKER_05_closed=true
R5_REVIEW_BLOCKER_06_closed=true

ENV_1B1C_B1_R6_completed=true
ENV_1B1C_B2_started=false
portable_runtime_lifecycle_integrated=false
formal_portable_batch_created=false
Runtime_rebuilt=false
Manifest_v2_implemented=false
Release_activation_implemented=false
OPS_3B_implemented=false
formal_Release_created=false
production_device_touched_by_codex=false
temporary_test_environment_accessed_by_codex=false
Ready=false
merged=false
STOPPED_AFTER_B1_R6_AWAITING_INDEPENDENT_REVIEW=true
```

These values are Codex implementation and local-test evidence only; they are
not an independent acceptance or authorization to enter B2.
