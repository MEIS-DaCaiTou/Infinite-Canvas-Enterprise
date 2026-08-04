# ENV-1B3 Candidate 08 final two-issue correction report

Status: repository correction and development gates complete. Candidate 08 remains unbuilt until commit, push, and the live Draft-PR gate pass. This report is Codex development evidence, not independent Windows acceptance.

## Evidence intake

- Candidate 07 affected-case evidence ZIP SHA-256: `fd3462f3ffcdcf3ce4355b30ab031fd386d7e2d4adadf96587a8aa316716b297`.
- Internal `SHA256SUMS`: `39/39`; no unsafe path, symlink, case-fold collision, missing entry, unbound entry, or hash mismatch.
- Candidate 07 identity remained `ice-2026.07.6-7066ee985035-candidate-07`; its handoff SHA-256 remained `054b0580dd20380e4ed831d9638a8932fa40f9403aaf8ae0a56a0d90070596a9`, and `candidate_modified=false`.
- Affected-case result: `4 PASS / 2 FAIL / 0 BLOCKED`; effective W01-W14 result: `12 PASS / 2 FAIL / 0 BLOCKED`.

## Fixed-Python status terminal diagnostic

Candidate 07 proved that the preflight emitted one valid `PORTABLE_FIXED_PYTHON_INTEGRITY_INVALID` status JSON line but returned `0`, so `查看企业版状态.bat` continued into the corrupted CP314 executable and ended with NTSTATUS `0xC000012F`. The correction gives the private preflight-to-wrapper contract three meanings: `0=continue`, `2=blocked`, and `3=terminal diagnostic already emitted`. Only the status wrapper maps private `3` to public `0` and exits without loading CP314. Start, restart, and health keep stable blocked JSON and exit `2`; stop retains verified-owned-stop behavior and otherwise returns the existing deterministic ownership rejection. No system-Python fallback was added.

## W14 exact failure localization

The original combined block reported only `app_root_path`. Candidate 08 splits `state_schema`, `candidate_id`, `release_id`, `app_root_path`, `pointer_sha256`, `app_root_tree_read`, and `app_root_tree_sha256`, with bounded public comparison evidence and user-profile path redaction. Hash evidence contains hashes only; path evidence retains drive, suffix, namespace, trailing-separator, case, and canonical spelling.

The development reproduction followed Candidate 07 handoff verification/materialization, APP_ROOT ACL conversion, external writable roots, and a process-scoped Windows PowerShell 5.1 `Bypass`. It reproduced the actual comparison as `app_root_tree_read`: the old recursive ACL command removed child-file inherited ACEs, and reading `ARCHITECTURE.md` returned access denied. After explicitly granting read-and-execute to every APP_ROOT child while retaining no write access, all seven identity comparisons passed and validation advanced to the expected development-host-only `offline_context` boundary. Therefore no APP_ROOT, pointer, or tree comparison was weakened. `W14Prepare` now explicitly requires read-and-execute on every APP_ROOT directory and file and a readable payload-file check before `W14Validate`; a complete offline/non-admin fixture passes the remaining W14 chain.

## Development verification

- Initial failing reproduction: `9 failed`, covering both exact issues before implementation.
- Narrow fixed-Python/W14 tests: `12 passed`.
- Full wrapper/validation-kit/matrix focused group: `115 passed`.
- Fixed-Python, identity, preflight, W14, materialization, and Manifest v2 regression group: `257 passed / 6 skipped / 0 failed`.
- Windows PowerShell 5.1 parser: `31` scripts, `0` parse errors; actual Batch and child-process tests passed.
- `python -m compileall enterprise tools`: exit `0`, with repository-external bytecode cache.
- APP_ROOT audit: `scanned=132`, `excluded=291`, `detected=387`, `mapped=387`; parse failures, uncovered sites, stale mappings, missing anchors, and invalid flows all `0`; digest `c197d5f6ce697dd86ccc607ca6db26fc2785ae581b424f37c2eb296961ba2a1d`.
- Final enterprise suite: `739 passed / 10 skipped / 0 failed / 9 warnings`, exit `0`; this was the only full-suite run for Candidate 08 source convergence.

## Boundaries

```text
Candidate_07_preserved=true
Candidate_08_built=false
Candidate_09_built=false
Candidate_Runtime_unrelated_subsystems_changed=false
clean_Windows_validation=false
ENV_1B3_completed=false
Release_activation_implemented=false
OPS_3B_implemented=false
formal_Release_created=false
Production_Baseline_approved=false
production_approved=false
production_validation=false
production_device_touched_by_codex=false
temporary_test_environment_accessed_by_codex=false
Draft=true
Ready=false
merged=false
```
