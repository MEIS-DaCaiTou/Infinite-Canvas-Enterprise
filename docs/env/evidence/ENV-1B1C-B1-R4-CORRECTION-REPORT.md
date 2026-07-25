# ENV-1B1C-B1-R4 Correction Report

## Scope

R4 is a Draft-PR-only correction of pure B1 contract primitives after the
second independent review. It does not wire a controller, host, child,
supervisor, process, Batch launcher, `main.py`, or a real lifecycle. It does
not access production or a temporary-test device.

```text
base=main@4d9cc4ef3d6a0f6ed956c2dda6303e9cc3b99b89
R3_head=0d7f9a283f673b427fa54dc9bfc7b612f393b62b
ENV_1B1C_B2_started=false
production_device_touched_by_codex=false
temporary_test_environment_accessed_by_codex=false
```

## Second-review corrections

| review blocker | R4 correction |
| --- | --- |
| 01 temp/probe identity reuse | File IDs are now only one part of ownership. Context publication requires a regular non-reparse lexical entry, the original identity, exact length and exact canonical bytes after target revalidation. Probe deletion requires its one-call cryptographic nonce token and identity. A foreign replacement with a mocked reused ID remains untouched and fails closed. |
| 02 broken symlink existence | Context target and `.new` checks use `lstat` lexical existence; a broken symlink is an existing invalid entry, never an absent target. |
| 03 Python root binding | Portable identity binds executable exactly to `runtime_root/python.exe`, and both `prefix` and `base_prefix` exactly to the existing non-reparse Runtime root directory. |
| 04 manifest metadata | Missing `source` is allowed. A present source must be an object, and a present `enterprise_commit` must be exactly 40 lowercase hexadecimal characters. |
| 05 forged typed models | The preflight builder validates RuntimeMode, startup view, PythonIdentity and each WritableProbeResult invariant before cross-binding. |
| 06 warning contract | B1 freezes warnings to the empty tuple. Failure error codes cannot be represented as successful preflight warnings. |
| 07 untrusted live instance | A live instance without valid ownership blocks start, restart, health and stop; status is exit 0 diagnostic with `ownership_untrusted=true`. |

`enterprise.path_safety.assert_no_reparse_ancestors` additionally inspects the
lexical anchor/root where the platform exposes it. ENV-1B2P provenance now
uses that shared ancestor helper while preserving its existing leaf
fault-injection seam.

## Ownership and TOCTOU boundary

```text
external_exclusive_runtime_lock_required=true
standalone_atomic_compare_and_swap_claim=false
residual_TOCTOU_acknowledged=true
```

The byte/token verification closes the deterministic replacement/reused-file-ID
case. It does not claim that a pure pathname protocol eliminates every actor
that can race operating-system replacement; B2 must supply external exclusive
runtime ownership before it uses this publisher.

## R4 evidence status

The R3 closure statements are historical Codex self-assessments, not an
independent acceptance result. R4 records remediation and test evidence for a
new independent review only.

```text
R3_REVIEW_BLOCKER_01_closed=true
R3_REVIEW_BLOCKER_02_closed=true
R3_REVIEW_BLOCKER_03_closed=true
R3_REVIEW_BLOCKER_04_closed=true
R3_REVIEW_BLOCKER_05_closed=true
R3_REVIEW_BLOCKER_06_closed=true
R3_REVIEW_BLOCKER_07_closed=true
R3_REVIEW_BLOCKER_08_closed=true
R3_REVIEW_BLOCKER_09_closed=true
ENV_1B1C_B1_R4_completed_in_Draft_PR=true
ENV_1B1C_B1_R4_completed=true
ENV_1B1C_B2_started=false
```

## Tests and audit

All pure-contract tests used the existing Windows embedded development
interpreter with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`,
`PYTHONDONTWRITEBYTECODE=1`, repository-root injection and the already tracked
test-only `python-multipart` wheel. No package was installed or downloaded.

```text
focused_passed=123
focused_failed=0
focused_skipped=0
ENV_1B2P_regression=70 passed
PathRoots_current_release_static_regression=137 passed, 3 skipped
OPS_direct_scripts=2 exit-0 scripts
branch_full_suite=373 passed, 5 skipped, 4 failed, 9 warnings, exit=1
base_full_suite=252 passed, 3 skipped, 4 failed, 8 warnings, exit=1
branch_regression_delta=0
full_suite_passed=false
github_ci_verified=false
real_bundled_python_fixture_tests=false
posix_pure_contract_tests_verified=false
```

The four Base/Head-common failures remain the two embedded-interpreter
subprocess `enterprise` import failures, the `sitecustomize` logging-origin
probe, and the isolated supervisor CLI-start worker. They are retained as
failures, not converted into a passing result. One earlier Head full-suite run
also timed out at `test_windows_process_smoke`; an immediate standalone rerun
passed, and the final Head full-suite rerun returned the common four-failure
set above. The focused suite has no platform skips: when a real Windows
symlink cannot be created, its lexical-existence policy uses a controlled
`lstat` fault injection. Identity-reuse tests do not depend on the operating
system reusing file IDs.

```text
audit_scanned=91
audit_excluded=249
audit_parse_failures=0
audit_detected=299
audit_mapped=299
audit_uncovered=0
audit_stale=0
audit_missing_anchors=0
audit_digest=464b2eef086b6fea37daf810d3b9f0551de652763f23028df799f8affb81e1ab
```

## Boundaries retained

```text
portable_runtime_lifecycle_integrated=false
formal_portable_batch_created=false
controller_portable_mode_integrated=false
host_context_validation_integrated=false
child_context_validation_integrated=false
Runtime_rebuilt=false
Manifest_v2_implemented=false
Release_activation_implemented=false
OPS_3B_implemented=false
formal_Release_created=false
Ready=false
merged=false
```
