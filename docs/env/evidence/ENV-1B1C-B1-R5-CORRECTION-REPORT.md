# ENV-1B1C-B1-R5 Correction Report

## Scope

R5 is a Draft-PR-only correction of the eight B1 pure-contract trust-chain
findings in the third independent review. It does not wire any controller,
host, child, supervisor, process, Batch, launcher, `main.py`, or lifecycle.

```text
base=main@4d9cc4ef3d6a0f6ed956c2dda6303e9cc3b99b89
R4_head=84343594992a31cf5bd2f4732546a87ca0725dd4
ENV_1B1C_B2_started=false
production_device_touched_by_codex=false
temporary_test_environment_accessed_by_codex=false
```

## R5 remediation

1. Preflight now binds the unique `python.exe` startup-record SHA-256 to
   `PythonIdentity.executable_sha256`, using
   `STARTUP_PREFLIGHT_PYTHON_MANIFEST_MISMATCH` on disagreement.
2. The parser and typed startup view share one exact-five-record, 64 MiB
   per-file and 128 MiB total limit validator.
3. Preflight and Launch Context reuse the ENV-1B1B Windows-safe release
   component validator; current-release regression covers the same rejected
   device names, trailing ambiguity, separators, and colon forms.
4. Writable probes take initial identity from the exclusive-create descriptor.
   On identity failure, cleanup only accepts the one-call nonce token; an
   unprovable replacement is retained rather than deleted.
5. Runtime core and executable open/read/close errors are mapped to stable
   redacted read-failure codes.
6. Public error details now use only bounded symbolic labels/basenames and
   recursively reject path-like values.
7. Portable Python identity requires explicit executable and Runtime-root
   inputs; optional SOABI is either absent or exactly CPython 3.10 Windows x64
   compatible.
8. Manifest, identity, preflight, and Launch Context use the same strict
   CPython 3.10 version invariant.

`decide_release_mismatch()` is frozen as a **release/ownership gate only**.
`allowed=true` is not process, HTTP, context, or readiness health; B2 must
perform those checks separately.

## Test and audit evidence

R5 first added failing adversarial cases. Before implementation they produced
`122 passed, 27 failed`; after implementation the focused R5/B1B-current
subset produced `221 passed, 1 warning`. Final B1 plus ENV-1B2P focused
regression produced `242 passed, 1 warning` using the existing embedded
development interpreter, plugin autoload disabled, bytecode disabled, and the
tracked test-only `python-multipart` wheel. No package was installed or
downloaded.

```text
focused_passed=242
focused_failed=0
base_full_suite=252 passed, 3 skipped, 4 failed, 8 warnings, exit=1
head_full_suite=433 passed, 3 skipped, 4 failed, 9 warnings, exit=1
branch_regression_delta=0
full_suite_passed=false
audit_scanned=91
audit_excluded=250
audit_detected=299
audit_mapped=299
audit_parse_failures=0
audit_uncovered=0
audit_stale=0
audit_missing_anchors=0
audit_digest=464b2eef086b6fea37daf810d3b9f0551de652763f23028df799f8affb81e1ab
github_ci_verified=false
real_bundled_python_fixture_tests=false
posix_pure_contract_tests_verified=false
```

## Review-status boundary

```text
R4_REVIEW_BLOCKER_01_closed=true
R4_REVIEW_BLOCKER_02_closed=true
R4_REVIEW_BLOCKER_03_closed=true
R4_REVIEW_BLOCKER_04_closed=true
R4_REVIEW_BLOCKER_05_closed=true
R4_REVIEW_BLOCKER_06_closed=true
R4_REVIEW_BLOCKER_07_closed=true
R4_REVIEW_BLOCKER_08_closed=true
release_gate_scope_frozen=true

ENV_1B1C_B1_R5_completed=true
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
```

The closure fields above are Codex implementation and local-test evidence,
not independent acceptance. PR #84 remains Draft until a new independent
review completes.
