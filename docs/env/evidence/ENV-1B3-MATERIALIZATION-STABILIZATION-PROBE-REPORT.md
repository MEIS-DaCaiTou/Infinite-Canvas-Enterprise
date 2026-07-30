# ENV-1B3 materialization stabilization Probe report

Status: repository correction implemented; diagnostic Guest evidence pending.

## Input evidence

- Candidate 05 test-host evidence outer SHA-256: `b78cb3a9ba529b152f4fb94d159ac3de47cf5d6db42e6073938b1bef09a82716`.
- Internal `SHA256SUMS`: `29/29` matched.
- Candidate identity, developer Head/tree and S0/S1 checkpoint identity matched.
- W01 and read-only W02 artifact verification passed; W02 materialization failed; W12/W13 passed; Candidate content remained unchanged.
- Failure classification: `VALIDATION_TOOL_DEFECT`. The closed payload contains zero `tools/` entries, while the old materializer incorrectly required `APP_ROOT/tools/build_release_manifest_v2.py`.

## Correction

- `verify_materialized_release.py` is a standalone, standard-library-only, read-only verifier in the validation kit. It imports no repository module, does not access the network and does not write APP_ROOT.
- It validates strict inventory schema/count/size/tree, every file size and SHA-256, exact file closure, duplicate/case-fold/path/reparse safety, detached/embedded Manifest identity and fixed CP314 executable identity.
- Future candidate handoffs bind its exact filename and SHA-256. The Candidate 05 diagnostic Probe binds the verifier in `PROBE-MANIFEST.json` without modifying or repackaging Candidate 05.
- Atomic order is `.partial` extraction → detached Manifest copy → external verification → final directory move → exclusive pointer temp → pointer commit.
- Injected extraction/verifier/final-move/pointer failures preserve an existing pointer (or leave it absent), remove owned `.partial`/final/temp artifacts, and do not start a process.
- Windows PowerShell 5.1 wrapper invocation uses a controlled native process boundary, ASCII-safe Unicode filename construction and live CIM process-path checks for supervisor/upstream/gateway fixed-Python identity.

## Developer evidence

- Materialized-verifier and Windows-kit focused tests: `44 passed / 1 platform skip`.
- Manifest v2 artifact-closure regression: `56 passed / 4 platform skips`.
- APP_ROOT audit: `scanned=113`, `excluded=280`, `detected=374`, `mapped=374`, no parse/uncovered/stale/missing-anchor/invalid-flow findings; digest `8e1f01dc49f135da57af5ab424d92bdb65a0cbf40fa1eb45904702d215b18a85`.
- `compileall enterprise tools`: passed.
- Original Candidate 05 handoff ZIP remained SHA-256 `a2f9e7ccb9cb78960ca69eb984c8d669288146e80a438427efc2e4952daec3b6`.
- Original Candidate 05 materialized through the new external verifier: `2098` archive entries, payload tree `3e1578ffdefef658ebd4fe01c6f92d3c667612d919bd8474feb05ed64cfc7047`.
- Local W03 fixture: start/status/health/stop all exit `0`; readiness, ownership, three live fixed-CP314 executable paths, port release and APP_ROOT unchanged all passed.
- Final enterprise full suite was not run; it remains gated on the final independent Windows matrix.

## Boundaries

```text
diagnostic_only=true
not_a_release_candidate=true
cannot_support_final_acceptance=true
Candidate_06_built=false
clean_Windows_validation=false
ENV_1B3_completed=false
Ready=false
merged=false
production_device_touched_by_codex=false
temporary_test_environment_accessed_by_codex=false
```
