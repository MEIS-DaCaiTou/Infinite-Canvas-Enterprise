# ENV-1B3 Candidate 07 strict Runtime repair report

Status: repository correction and development gates complete; the immutable Candidate 07 identity is published in the repository-external handoff and Draft PR after the evidence-bearing commit.

## Baseline and evidence

- Initial Head/tree: `33357a1f32d418f84cc36d586b5092fbb6111e9b` / `1eedccd5bca06dd154097babc46693919ddc2139`.
- Candidate 06 remains immutable as `ice-2026.07.6-33357a1f32d4-candidate-06`; its handoff SHA-256 remains `1def17c6446457b958dd278eed9b56a3dd6a91fedfdda564640da03ecbb8a09b`.
- The independently supplied narrow-closure evidence ZIP SHA-256 is `bfd9931dce66f8cd6d819d7b492a893cee539038e68136b0012bc96e12e4fef7`; its outer identity, 148/148 internal hashes, paths and Candidate bindings passed before use.
- Authoritative raw evidence was read from the ZIP's `ORIGINAL-MATRIX-EVIDENCE/EXTRACTED` and `RAW-NARROW-CLOSURE` W05/W08/W11/W14 records. Candidate 06 result: `10 PASS / 4 FAIL / 0 BLOCKED`.

## Strict correction scope

- W05: `enterprise/runtime/process.py` and the service-host spawn in `enterprise/runtime/control.py` pass explicit Win32 extended executable and current-directory paths while preserving canonical identity and public path redaction. A first unpublished staging lifecycle then proved that CPython preserves the `\\?\` namespace in `sys.prefix`/`sys.base_prefix` while reporting an ordinary `sys.executable`; `enterprise/runtime/python_identity.py` now normalizes only well-formed Win32 extended drive/UNC spellings before the unchanged reparse, containment and exact-root gates. The next unpublished lifecycle reached healthy ownership/readiness and exposed the same namespace spelling in CIM `ExecutablePath`; the validation kit canonicalizes that spelling before its existing exact fixed-Python comparison in lifecycle and verified-owned tamper cleanup. A final unpublished long-path fixture then proved two additional Windows-only read failures at a 261-character payload path: the standalone materialized verifier and the Runtime's unique Manifest v2 materialized-payload verifier. Both now use Win32 extended paths only for trusted file I/O after the existing logical path/reparse gates; the fixed CP314 long-path read and Manifest verification pass without weakening inventory, hash, containment or identity checks.
- W08 current-release: `enterprise/runtime/portable.py` treats `CurrentReleaseError` like other retained-context diagnostic/owned-stop failures. Status stays diagnostic; stop still requires the existing adopted lock/state/context plus live process identity.
- W08 payload: formal health now requests the same bounded full-payload verification as start/restart before reporting ready.
- W08 fixed Python: the five formal Batch wrappers call `enterprise/runtime/fixed_python_preflight.ps1` before CP314 loads. The ASCII, Windows PowerShell 5.1 script validates the declared `python314.dll` size/hash, returns stable single-line JSON/exit 2 for start/restart/health tamper, diagnostic exit 0 for status, and permits stop only after retained context, lock/state, creation time, executable and command-line identity all match. There is no system-Python fallback.
- W11: `enterprise/runtime/ownership.py`, `state.py`, `supervisor.py` and `control.py` bind a canonical supervisor command identity into reservation, adopted lock and state. Reconciliation uses an exclusive claim and exact rereads; it is permitted only when the bound supervisor/children are absent, required ports are clear and Release/Manifest/payload/enterprise/context identities all match. PID reuse, creation-time, executable, command or Release drift remains fail closed.
- W14: only the validation entry and final-identity script changed. `W14Prepare`/`W14Validate` run in a child Windows PowerShell 5.1 process with process-scoped `-ExecutionPolicy Bypass`; the parent policy is not modified, and failures identify module/path/read-only/external-root/offline/fixed-Python/tree/port stages.
- Candidate sequence handling was changed only from the closed `01-06` range to the closed, specifically authorized `01-07` range.

## Development gates

- Runtime/wrapper focused before artifact construction: `63 passed`, `0 failed`; the post-staging namespace correction gate was `89 passed`, `1 skipped`, `0 failed`.
- ENV-1B3 validation-kit/matrix-contract focused: post-Runtime rerun `95 passed`, `1 skipped`; process-path focused `40 passed`; matrix/materialization/Manifest regression `112 passed`, `5 skipped`; and final long-path verifier regression `107 passed`, `5 skipped` followed by `98 passed`, `1 skipped`; all had `0 failed`.
- STAB-1 supervisor/lifecycle: `19 passed`, `0 failed`.
- Manifest v2, Runtime provenance, build policy, current-release and static/audit regression: `247 passed`, `4 skipped`, `0 failed`, `2 warnings`.
- Windows PowerShell 5.1 parser and real-process tests: passed; the fixed-DLL preflight and W14 process-scoped module/path fixture both returned their frozen exit/result contracts.
- Compileall: `python -m compileall enterprise tools`, exit `0`, bytecode directed to a repository-external cache.
- APP_ROOT audit: `scanned=132`, `excluded=290`, `detected=387`, `mapped=387`; zero parse failures, uncovered sites, stale mappings, missing anchors and invalid flows; digest `c197d5f6ce697dd86ccc607ca6db26fc2785ae581b424f37c2eb296961ba2a1d`.
- Initial repository candidate suite: `735 collected`, `725 passed`, `10 skipped`, `0 failed`, `9 warnings`, exit `0`. The first unpublished staging lifecycle subsequently exposed the extended-prefix identity defect above, so publication was stopped and that tracked Runtime correction required a new final suite.
- Post-Runtime-correction enterprise suite: `736 collected`, `726 passed`, `10 skipped`, `0 failed`, `8 warnings`, exit `0`. The unpublished formal lifecycle then reached healthy Runtime but found the validation-only CIM namespace comparison defect, requiring the final validation-kit correction above.
- Post-tool-correction enterprise suite: `737 collected`, `727 passed`, `10 skipped`, `0 failed`, `8 warnings`, exit `0`. The unpublished W05 artifact gate then exposed the two bounded long-path read defects above, so this third run is historical rather than the final tracked source state.
- Final post-long-path-verifier enterprise suite: `740 collected`, `730 passed`, `10 skipped`, `0 failed`, `8 warnings`, exit `0`, CPython `3.11.9` x64. Interpreter switching remained false. The task therefore has four accurately disclosed full-suite runs; only the fourth represents the final tracked source state.

The development device has `LongPathsEnabled=0`; it did not change registry or policy. It reproduced the bounded extended-path process-creation primitive, successfully materialized and verified all 2,099 archive entries at a long test root, and proved fixed CP314 file I/O at a 261-character payload path. Candidate 07 build gates additionally execute the formal long-path lifecycle against the final artifact; the authoritative positive-policy acceptance remains the independent physical Windows retest.

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
