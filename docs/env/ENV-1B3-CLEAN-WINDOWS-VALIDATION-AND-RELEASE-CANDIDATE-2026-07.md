# ENV-1B3 clean Windows validation and Release Candidate

Status: implementation in one Draft PR; independent Windows test-host validation pending.

## Scope

ENV-1B3 establishes one reusable, Windows-native validation kit for an immutable Release Candidate built by the accepted Manifest v2 builder. The development device owns Git, candidate construction and evidence review. A separate Windows host owns the clean-host classification and W01-W14 execution. Candidate transfer is performed by the project owner; the development Codex neither connects to nor controls that host.

The formal test-host entry is `tools/validation/windows/env_1b3/Invoke-ENV1B3Validation.ps1`. The kit uses explicit absolute handoff, test and evidence roots; it does not depend on the current directory, GitHub credentials, system Python, network downloads, production configuration or user data. Candidate application commands continue to use the Release-bound `APP_ROOT/python/python.exe` chain.

## Matrix contract

`matrix.json` freezes stable case IDs W01-W14 for environment baseline, offline artifact verification/materialization, non-admin lifecycle, Unicode/space and long paths, read-only APP_ROOT/external roots, environment pollution, tamper, ownership, port conflict, reboot resume, low disk, file locks/security software and final clean-baseline identity. Every case produces bounded JSON with a stable result code. `FAIL` or `BLOCKED` prevents clean-Windows acceptance.

Destructive cases use copies or isolated fixtures. The kit never weakens verification, disables Defender, fills the system volume, kills foreign processes or reboots without explicit project-owner approval. `REBOOT-RESUME.json` records continuation state; the script itself does not reboot the host.

## Candidate boundary

Each candidate is built outside Git from an exact clean commit/tree using the existing Manifest v2 builder and accepted CPython 3.14 Runtime input. Candidate directories and sequences are immutable and are never overwritten. The handoff binds the Release archive, detached manifest, external inventory, payload/Runtime/static identities, validation matrix and exact independent-host taskbook.

Initial candidate evidence will remain repository-external. The Draft PR and candidate handoff carry its exact identity. A test-host evidence ZIP is accepted only if the task ID, candidate ID, artifact hashes, matrix completeness and independent-host classification all match.

Candidate 03 reached the independent physical host, where W01 classified that host as not clean before W01-W14 execution began. Its artifact preflight passed, but the baseline exposed two validation-tool defects: CIM `InstallDate` could already be a `System.DateTime`, and the public entrypoint could read an unset `$LASTEXITCODE` after a successful PowerShell-only verification step. The project owner authorized one governance-exception Candidate 04 to correct only those tool defects while Hyper-V clean-host preparation proceeds independently. Candidates 01-03 remain immutable and preserved; no independent Windows matrix result has been inherited from the invalid physical-host baseline.

Candidate 04 was transferred to a fresh Hyper-V Guest whose independent baseline established no usable system Python and a recorded BypassNRO deviation. W01 then stopped before the matrix because normal `where.exe` exit `1` was promoted by PowerShell error policy and a damaged uninstall record lacked `DisplayName`. The validation tool now handles both cases explicitly. The diagnostic-only W01 stabilization Probe subsequently passed twice on the restored Guest, while Candidate 04 remained unchanged and W02-W14 remained unexecuted. The first PASS was followed by a failure in an untracked host-side command that read UTF-8 JSON through the Windows PowerShell default ANSI code page; this was an orchestration-only issue, not a repository writer or W01 result failure. Candidate instructions now require explicit UTF-8 reads.

The project owner explicitly authorized Candidate 05 as the sole final Windows matrix candidate. Its immutable handoff binds the independently passed Probe Head and evidence hash, the clean Guest S0 checkpoint source and the final-candidate status. Candidates 01-04 and the Probe remain immutable and preserved. Candidate 05 still requires the independent Guest's complete W01-W14 matrix; no clean-Windows acceptance is claimed by this repository-side build step.

Candidate 05 then reached the restored independent Guest. Its outer/internal identities, W01, read-only W02 artifact verification, W12 and W13 passed, and the candidate remained unchanged. W02 materialization failed before W03-W11/W14 because the validation script incorrectly expected the repository build tool at `APP_ROOT/tools/build_release_manifest_v2.py`; the closed payload intentionally contains no `tools/` directory. This was a validation-tool responsibility defect, not a Release artifact identity failure.

The corrected boundary keeps the build tool excluded. A standalone standard-library verifier is SHA-bound in the validation kit/handoff and runs under the staged Release's fixed CP314 `python.exe -I -B`. Materialization now extracts to an owned `.partial` staging directory, copies the detached manifest, verifies every declared payload file plus exact closure/tree/Manifest identity, atomically moves the verified tree to the final Release directory, and commits `current-release.json` last. Injected extraction, verifier, final-move and pointer failures clean the owned staging/final/temp state and preserve any earlier pointer. A diagnostic-only Remaining Matrix Probe is used against the original immutable Candidate 05; it is not Candidate 06 and cannot support final acceptance.

Independent review accepted that first Probe's artifact integrity, standalone materialized verifier and pointer-last materialization design, but rejected its execution contract: multi-branch W09/W13 results could be overwritten; W11 lacked both stopped/running resume phases; W14 had no operator window for making APP_ROOT read-only; and W07/W08/W12/W13 evidence did not yet establish every mandatory matrix property. The original Probe remains immutable and is not authorized for Guest execution.

The replacement diagnostic Probe v2 binds the same unchanged Candidate 05 handoff and adds a versioned W01-W14 contract. Each case declares mandatory subchecks, execution context, fixtures, required evidence, stable codes and all-subchecks-PASS aggregation. Subchecks use exclusive, non-overwriting evidence files before one aggregate `Wxx.json` is emitted. Its public dispatcher exposes both W09 branches, all four W11 prepare/resume phases, two-stage W14 preparation/validation, actual low-space and archive-lock materialization checks, Defender scan/exclusion evidence, complete tamper command behavior and M01 atomicity. Probe v2 remains diagnostic-only, cannot support final acceptance and awaits independent Guest authorization; Candidate 06 has neither been authorized nor built.

## Current state and limits

```text
ENV_1B3_started=true
ENV_1B3_validation_kit_repository_implementation=true
ENV_1B3_completed=false
clean_Windows_validation=false
Release_candidate_independently_tested_on_separate_Windows_host=false

Release_activation_implemented=false
OPS_3B_implemented=false
formal_Release_created=false
formal_release_deployed=false
Production_Baseline_approved=false
production_approved=false
production_validation=false
```

Candidate sequence and artifact identity are recorded in each immutable repository-external handoff and in the Draft PR, rather than as a transient value in this tracked document. A Release Candidate is a validation artifact, not a formal Release, activation, deployment or Production Baseline.
