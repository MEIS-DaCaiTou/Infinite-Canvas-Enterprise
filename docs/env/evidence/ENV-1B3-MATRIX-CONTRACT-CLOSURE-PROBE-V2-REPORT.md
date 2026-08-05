# ENV-1B3 Remaining Matrix Probe v2 correction report

Status: repository correction implemented; independent Guest execution not authorized by this report.

## Scope and preserved evidence

The original Remaining Matrix Probe remains immutable. Its ZIP integrity, Candidate 05 binding, standalone materialized verifier, partial-staging verification, atomic final move, pointer-last commit and M01 fault-injection direction were accepted. It is not authorized for Guest execution because its public interface and aggregate evidence could not prove the full remaining matrix contract.

Candidate 05 is unchanged and is not repacked by Probe v2. Candidate 06 is not authorized and was not built.

## Contract closure

`matrix-contracts.json` provides a versioned contract for W01-W14. Every case declares mandatory subchecks, execution context, fixtures, required evidence fields, aggregation semantics, non-overwrite policy and stable result codes. `Write-ENV1B3SubcheckResult` uses exclusive files below `subchecks/<case>/`; `Complete-ENV1B3CaseResult` emits PASS only when every declared mandatory subcheck exists and passed.

The public Probe v2 dispatcher exposes W02-W10, four explicit W11 phases, W12, W13, two explicit W14 phases and M01. It does not require the test host to call internal scripts directly.

## Closed review items

- W07 records PATH exclusion for Candidate Python, polluted Python environment variables, fixed Release Python identity, offline network classification and candidate-process non-loopback connection count.
- W08 executes start/restart/health fail-closed checks, diagnostic status, no-new-process checks, retained-owned stop and foreign-process survival for each required tamper target.
- W09 aggregates retained owned stop, foreign stop rejection, foreign survival and restored owned cleanup without result overwrite.
- W11 persists Candidate/APP_ROOT/pointer/ownership identity across stopped and running prepare/resume phases. A real restart or approved controlled abnormal termination remains a Guest action.
- W12 uses a bounded isolated non-system volume for artifact/materialization/writable-root low-space behavior, pointer atomicity and same-Candidate recovery.
- W13 invokes real artifact/materialization behavior while the archive is locked, verifies recovery after lock release, and records Defender real-time state, controlled scan result, detection/quarantine state and permanent-exclusion absence.
- W14 separates verify/materialize from the later read-only, offline, standard-user lifecycle so the test host can apply APP_ROOT ACLs between phases.

## Development evidence and limits

Development fixtures exercised W02 materialization, W03 formal lifecycle and M01 fault atomicity with Candidate 05. Contract/schema/dispatcher/non-overwrite tests run under the dedicated development interpreter, and every validation-kit PowerShell file parses under Windows PowerShell 5.1. A diagnostic W11 run confirmed status remains available after controlled process loss; Candidate 05 currently blocks restart before controller stale-lock recovery, so this report does not claim a Guest W11 PASS or silently weaken that gate. The Probe exists to obtain independent classification of such platform/runtime behavior.

No final enterprise full suite is run at this stage. No production or temporary business test environment is accessed.

The staged tracked APP_ROOT audit result is `scanned=121`, `excluded=286`, `detected=383`, `mapped=383`; parse failures, uncovered sites, stale mappings, missing anchors and invalid flow IDs are all zero. The frozen manifest digest is `2e610db12cc7816e1cd62f5cb20b7ece6c1eb58f6919390c3620928d82f6878e`. All new validation-kit evidence writes remain caller-owned repository-external W45 operations.

```text
remaining_probe_v1_integrity_passed=true
remaining_probe_v1_materialization_fix_passed=true
remaining_probe_v1_matrix_contract_passed=false

remaining_probe_v2_repository_contract_implemented=true
remaining_probe_v2_guest_execution_authorized=false
candidate_05_preserved=true
candidate_06_authorized=false
candidate_06_built=false

clean_Windows_validation=false
ENV_1B3_completed=false
Ready=false
merged=false
production_device_touched_by_codex=false
temporary_test_environment_accessed_by_codex=false
```
