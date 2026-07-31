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

The independent Probe v2 Guest execution verified the immutable bundle and Candidate 05 identities, then produced `7 PASS / 5 FAIL / 1 BLOCKED`. W02, W03, W04, W06, W07, W12, W14 and M01 passed; W05 was correctly blocked by the Guest's disabled long-path policy. W08/W09/W10/W11 and W13 exposed validation-tool evidence, process, encoding, state-durability, and null-exclusion defects. The run did not prove a Candidate Runtime defect.

Failed-matrix closure Probe v3 is therefore limited to W05, W08, W09, W10, W11, a W12 evidence audit, W13 and an automated Contract Audit. Public modes propagate PASS as exit `0` and FAIL/BLOCKED as exit `2`. Tamper cases use bounded wrappers, independent roots and verified-owned cleanup; W09 writes every stage even when healthy start fails; W10 uses ASCII source and a controlled listener; W11 uses write-through/flush/re-read/hash state with a stable durability error and explicit graceful-versus-hard-reset classification; W12 records retry success; and W13 distinguishes existing exclusions from newly added exclusions. Candidate 05 remains immutable, Candidate 06 is not authorized or built, and Probe v3 still cannot support final acceptance.

The immutable Probe v3 artifact passed integrity review but its Guest execution contract was not authorized. Review found four tool-contract issues: W08 still shared one Runtime root across a multi-target loop; the audit checked presence rather than record/value identity; the public entry rewrote child BLOCKED as FAIL; and W13 described an unchanged set as absent.

Probe v3R1 closes those issues without changing Candidate 05 or Probe v3. Each W08 target is a separate public mode that requires a restored clean checkpoint and blocks on any existing Runtime lock/state, related process or candidate port without deleting it. Public results preserve the child result and code with an exact `PASS/0`, `FAIL/2`, `BLOCKED/2` contract. ContractAudit covers W05–W13, validates record/filename/schema/task/matrix/case/subcheck/result identity, meaningful values, strict-true context/fixtures, PASS aggregates, and a Candidate/Probe-v2/W12-SHA-bound supplemental W12 audit. W13 now has separate mandatory absence and unchanged subchecks; a real pre-existing exclusion makes absence BLOCKED while unchanged remains factual. Probe v3R1 remains diagnostic-only and awaits independent review; Candidate 06 remains unauthorized and unbuilt.

Independent review accepted the immutable Probe v3R1 artifact but withheld Guest execution because its advertised W08 aggregate path still re-entered the live tamper workflow and its W12 audit trusted an external extracted evidence directory. Probe v3R2 corrects only those two boundaries. Its manifest separates Guest-executable cases from host-only W08/W12/ContractAudit cases. W08 host aggregation reads five independently exported target records, rejects duplicate/unexpected/mismatched/non-PASS input, copies with create-new semantics, and binds five source hashes plus one canonical evidence-set hash without running Candidate code. W12 now verifies the original Probe v2 ZIP outer identity, normalized path safety, exact `57/57` internal sum closure, Candidate 05 binding, four W12 subchecks, recovery evidence, pointer/no-partial facts and optional mirror equality directly from immutable ZIP bytes. Probe v3R2 remains diagnostic-only and awaits independent review; Candidate 05 is unchanged and Candidate 06 remains unauthorized and unbuilt.

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
