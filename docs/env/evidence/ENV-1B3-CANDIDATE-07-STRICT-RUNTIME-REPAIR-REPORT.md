# ENV-1B3 Candidate 07 strict Runtime repair report

Status: repository correction and development gates complete; the immutable Candidate 07 identity is published in the repository-external handoff and Draft PR after the evidence-bearing commit.

## Baseline and evidence

- Initial Head/tree: `33357a1f32d418f84cc36d586b5092fbb6111e9b` / `1eedccd5bca06dd154097babc46693919ddc2139`.
- Candidate 06 remains immutable as `ice-2026.07.6-33357a1f32d4-candidate-06`; its handoff SHA-256 remains `1def17c6446457b958dd278eed9b56a3dd6a91fedfdda564640da03ecbb8a09b`.
- The independently supplied narrow-closure evidence ZIP SHA-256 is `bfd9931dce66f8cd6d819d7b492a893cee539038e68136b0012bc96e12e4fef7`; its outer identity, 148/148 internal hashes, paths and Candidate bindings passed before use.
- Authoritative raw evidence was read from the ZIP's `ORIGINAL-MATRIX-EVIDENCE/EXTRACTED` and `RAW-NARROW-CLOSURE` W05/W08/W11/W14 records. Candidate 06 result: `10 PASS / 4 FAIL / 0 BLOCKED`.

## Strict correction scope

- W05: `enterprise/runtime/process.py` and the service-host spawn in `enterprise/runtime/control.py` pass explicit Win32 extended executable and current-directory paths while preserving canonical identity and public path redaction.
- W08 current-release: `enterprise/runtime/portable.py` treats `CurrentReleaseError` like other retained-context diagnostic/owned-stop failures. Status stays diagnostic; stop still requires the existing adopted lock/state/context plus live process identity.
- W08 payload: formal health now requests the same bounded full-payload verification as start/restart before reporting ready.
- W08 fixed Python: the five formal Batch wrappers call `enterprise/runtime/fixed_python_preflight.ps1` before CP314 loads. The ASCII, Windows PowerShell 5.1 script validates the declared `python314.dll` size/hash, returns stable single-line JSON/exit 2 for start/restart/health tamper, diagnostic exit 0 for status, and permits stop only after retained context, lock/state, creation time, executable and command-line identity all match. There is no system-Python fallback.
- W11: `enterprise/runtime/ownership.py`, `state.py`, `supervisor.py` and `control.py` bind a canonical supervisor command identity into reservation, adopted lock and state. Reconciliation uses an exclusive claim and exact rereads; it is permitted only when the bound supervisor/children are absent, required ports are clear and Release/Manifest/payload/enterprise/context identities all match. PID reuse, creation-time, executable, command or Release drift remains fail closed.
- W14: only the validation entry and final-identity script changed. `W14Prepare`/`W14Validate` run in a child Windows PowerShell 5.1 process with process-scoped `-ExecutionPolicy Bypass`; the parent policy is not modified, and failures identify module/path/read-only/external-root/offline/fixed-Python/tree/port stages.
- Candidate sequence handling was changed only from the closed `01-06` range to the closed, specifically authorized `01-07` range.

## Development gates

- Runtime/wrapper focused: `63 passed`, `0 failed`.
- ENV-1B3 validation-kit/matrix-contract focused: `87 passed`, `0 failed`.
- STAB-1 supervisor/lifecycle: `19 passed`, `0 failed`.
- Manifest v2, Runtime provenance, build policy, current-release and static/audit regression: `247 passed`, `4 skipped`, `0 failed`, `2 warnings`.
- Windows PowerShell 5.1 parser and real-process tests: passed; the fixed-DLL preflight and W14 process-scoped module/path fixture both returned their frozen exit/result contracts.
- Compileall: `python -m compileall enterprise tools`, exit `0`, bytecode directed to a repository-external cache.
- APP_ROOT audit: `scanned=132`, `excluded=290`, `detected=387`, `mapped=387`; zero parse failures, uncovered sites, stale mappings, missing anchors and invalid flows; digest `c197d5f6ce697dd86ccc607ca6db26fc2785ae581b424f37c2eb296961ba2a1d`.
- Final enterprise suite: `735 collected`, `725 passed`, `10 skipped`, `0 failed`, `9 warnings`, exit `0`, CPython `3.11.9` x64; this was the task's single final full-suite run.

The development device has `LongPathsEnabled=0`; it did not change registry or policy. It reproduced and verified the bounded extended-path process-creation primitive and created a complete 2,111-file long-path fixture with fixed CP314. Candidate 07 build gates must additionally execute the formal long-path lifecycle against the final artifact; the authoritative positive-policy acceptance remains the independent physical Windows retest.

## Boundaries and next gate

```text
Candidate_06_preserved=true
Candidate_07_repository_correction_completed=true
Candidate_07_affected_cases_windows_retest_passed=false
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
Ready=false
merged=false
```

The only next gate is `CANDIDATE_07_AFFECTED_CASES_WINDOWS_RETEST` for W05, W08 `current_release`/`payload`/`python314.dll`, W11 running-state reboot and W14. No new Probe, Candidate 08 or production action is authorized.
