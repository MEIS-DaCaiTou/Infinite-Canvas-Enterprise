# ENV-1B1C-B1-R3 Correction Report

## Scope and baseline

This correction pass addresses the nine pure-contract blockers found by the
independent PR #84 review.  It remains a Draft-PR-only B1 change: it does not
wire a controller, host, child, supervisor, process, Batch launcher or
`main.py`, and it does not access a production or temporary-test device.

```text
base=main@4d9cc4ef3d6a0f6ed956c2dda6303e9cc3b99b89
starting_head=a193a8a96ed4006db08610698259162862faaa03
ENV_1B1C_B2_started=false
production_device_touched_by_codex=false
temporary_test_environment_accessed_by_codex=false
```

## Review-blocker closure

| blocker | closure |
| --- | --- |
| 01 Launch Context schema | A single strict validator now protects direct construction, reader, builder and publisher.  It requires portable-release, a safe release ID, `releases/<release_id>`, CPython 3.10, cp310, x64, fixed bytecode policy, five SHA-256 values and exact canonical raw bytes. |
| 02 Context replacement race | The publisher revalidates the expected target state after owned-temp fsync and before replace.  This is not claimed to be compare-and-swap: an external exclusive runtime lock remains required in B2 and residual TOCTOU is acknowledged. |
| 03 Path/reparse safety | `enterprise.path_safety` is the shared fail-closed lexical inspector used by Runtime Manifest, Python identity, launch context, writable probe and runtime provenance.  Inspection failures, file/ancestor reparse points and first relative components reject. |
| 04 Writable probe errors | Missing root, create, write, flush, fsync, inspection, ownership and cleanup paths map to stable redacted contract codes.  Suffixes are exactly `[a-z0-9]{8,64}`. |
| 05 Stop ownership | Every live-instance stop requires `owned_instance_valid`; the result now separately exposes launcher mismatch, running mismatch, running presence and ownership validity. |
| 06 Typed preflight | The builder accepts only typed mode, manifest view, Python identity and ordered successful probe results, then cross-binds version, ABI, x64 architecture, bytecode policy, root labels and registered warning codes. |
| 07 Error payload | Details are stored immutably, public details are defensive copies and unsafe correlation IDs/details use the error-contract layer rather than launch-context semantics. |
| 08 Manifest limits | The eight-record hard limit is executed; 3.10 version syntax and optional `candidate_id` are strict; ARM64 reaches stable unsupported-architecture handling in preflight. |
| 09 Python Runtime binding | Probe executable, prefix and base-prefix are verified under an explicit Runtime root.  Prefix identities bind normalized full paths without exposing them publicly. |

```text
B1_BLOCKER_01_closed=true
B1_BLOCKER_02_closed=true
B1_BLOCKER_03_closed=true
B1_BLOCKER_04_closed=true
B1_BLOCKER_05_closed=true
B1_BLOCKER_06_closed=true
B1_BLOCKER_07_closed=true
B1_BLOCKER_08_closed=true
B1_BLOCKER_09_closed=true
external_exclusive_runtime_lock_required=true
standalone_atomic_compare_and_swap_claim=false
residual_TOCTOU_acknowledged=true
```

## Reproduction and tests

R3 added 19 named regression functions (46 collected parameterized cases) for
T01--T09.  Before the fixes, the focused launch-context/writable-probe/error
group recorded `21 failed, 23 passed`; a concurrent full focused reproduction
recorded `25 failed, 68 passed` while the typed-preflight API was being
introduced.  Those are expected pre-fix failures, not final results.

Using the existing local embedded development interpreter with
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` and `PYTHONDONTWRITEBYTECODE=1`:

```text
B1 pure-contract plus ENV-1B2P regression=169 passed, 1 pytest-cache warning
all seven B1 pure-contract files=99 passed, 7 pytest-cache warnings
branch enterprise/tests=351 passed, 3 skipped, 4 failed, 9 warnings, exit=1
base enterprise/tests=252 passed, 3 skipped, 4 failed, 8 warnings, exit=1
branch_regression_delta=0
full_suite_passed=false
github_ci_verified=false
real_bundled_python_fixture_tests=false
```

The valid Base comparison used a detached Git worktree, rather than a
`git archive` extraction, because audit and upstream-sync tests explicitly
need `.git`.  The four common failures are the previously documented two
subprocess imports of `enterprise`, the `sitecustomize` logging-origin probe,
and the isolated CLI lifecycle start worker.  They are retained as failures;
they are not claimed to pass or to be a formal bundled-Runtime result.

## Audit and boundaries

W26 remains launch-context control/diagnostic state; W42 remains the distinct
writable-root probe primitive.  The audit is a tracked-source drift gate, not
a proof that no unknown dynamic write exists.  Final staged statistics and the
frozen digest are recorded in the implementation report after the correction
commit is assembled.

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
STOPPED_AFTER_B1_R3_AWAITING_INDEPENDENT_REVIEW=true
```
