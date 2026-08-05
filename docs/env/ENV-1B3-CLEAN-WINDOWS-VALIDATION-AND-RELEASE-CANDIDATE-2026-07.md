# ENV-1B3 clean Windows validation and Release Candidate

Status: completed and merged by PR #90; independent Windows W01-W14 validation passed.

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

Final convergence stops further Probe-framework expansion and preserves all earlier immutable Candidates and Probes. The final validation kit now validates diagnostic manifests by their task/candidate/handoff/verifier/boolean semantics plus the current bundle `SHA256SUMS` binding, without coupling materialization to historical Probe schema names. W05 exercises a materialized path longer than 260 characters with the fixed Release Python before lifecycle; W08 has a bounded healthy-pre-target preparation record and five separately executable tamper targets; W09 requires and copies a complete install root using the fixed CP314 interpreter with long-path semantics; W10 derives both required ports from formal status/config identity; W11 uses separate stopped/running durable journals; and W13 proves fail-closed archive locking followed by same-Candidate recovery while keeping Defender enabled and adding no exclusion.

The final clean-root development fixture then established one narrow Runtime defect that prior Guest evidence had not proven: a fresh Windows profile has no per-user Runtime/cache/temp directories, but portable preflight probed its five writable roots before any later directory-preparation call. The corrected preflight creates only those derived roots under the existing pre-use/post-create no-reparse protocol and then executes the unchanged self-cleaning writable probes. Controller, supervisor, ownership, Manifest and activation behavior remain unchanged. Candidate 06 remains a repository-external artifact that may be published only after the final development gates pass; its exact post-commit identity belongs in the immutable handoff and Draft PR rather than being predicted here.

Candidate 06 subsequently completed the independent Windows matrix with `10 PASS / 4 FAIL / 0 BLOCKED`. Candidate 07 closed W05, W08 `current_release`/`payload`, and W11, then its independent affected-case retest produced `4 PASS / 2 FAIL / 0 BLOCKED` (`12 PASS / 2 FAIL / 0 BLOCKED` effective W01-W14): only W08 `python314.dll` status and W14 remained. Candidate 08 is the final strictly bounded correction. Its status preflight uses an internal terminal-diagnostic result so the Batch wrapper returns public status exit `0` without loading damaged CP314. W14 now reports separate schema, Candidate, Release, APP_ROOT, pointer, tree-read and tree-hash comparisons. Development reproduction localized the old generic W14 result to child files made unreadable by the test-host ACL operation, not to an APP_ROOT/pointer/tree semantic mismatch; the handoff contract now requires recursive read-and-execute without write before validation, while all identity checks remain fail closed. Candidates 06 and 07 remain immutable. At Candidate 08 handoff time, only the independent physical-Windows retest of W08 `python314.dll` and W14 remained; the final acceptance below supersedes that historical pending state.

## Final acceptance

PR #90 merged to `main` as `105f3ca47f81207d2820fbd9acfa0a6d7b65770a`, preserving tree `5a5fd040974ca9f74f0b2aa916edbb20c42dbd67` from evidence-bearing Head `7593abdd54db55a137a9e8501dd01012d0ec3bab`. The accepted immutable Candidate is `ice-2026.07.6-7593abdd54db-candidate-08`, Release ID `ice-2026.07.6-7593abdd54db`.

Artifact identity:

```text
handoff_sha256=f267f047c0338e6973ad159ba02839cf2816ae5ce5445121a6d2087e0967c23e
release_archive_sha256=a48450cbe18804f9b849e456272e154087b0988e84621e12bed61e7c3c0a41df
detached_manifest_sha256=100ee4dd87aae2b4c91058fd76240d3529f6db2a90c5fee5dbff56e4e07de7f5
external_inventory_sha256=3351c7a53918f5f343b7fc1efc46983ed8bc47027a19462d0c3cc36b91387f7c
payload_tree_sha256=b4be84d7504eedf31a337460f44d99ef1f97d74686ddadba1ef681e2eb2b1581
runtime_tree_sha256=8962745ff0cc17029ffdf6d9a667a4abe6f5553a96d2952dd71ccabdefdceb03
static_tree_sha256=df3052f9bc2b90069e7bf1762bacc5088c555f2b1b1cbd2d535a78b830bffd2c
```

The final physical-Windows evidence bundle `ENV-1B3-ice-2026.07.6-7593abdd54db-candidate-08-FINAL-TWO-CASES-WINDOWS-RETEST-EVIDENCE.zip` is `32,843` bytes with SHA-256 `5138f17a77b94d16657b138546ab323406c23e0c820a5a3fd751615b2fd90c57` and internal closure `34/34`. W08 `python314.dll` and W14 both passed, producing the final effective W01-W14 result `14 PASS / 0 FAIL / 0 BLOCKED`. The test host did not modify the Candidate or repository; original checkpoints were preserved, Guest networking was restored, the physical host was not rebooted, and production was untouched.

Developer regression remained distinct from physical-host validation: CPython 3.11.9 x64 ran `739 passed / 10 skipped / 0 failed / 9 warnings`; no collected count was recorded and `github_ci_verified=false`. The compact identity and boundary record is [ENV-1B3 Final Acceptance / Closeout](./evidence/ENV-1B3-FINAL-ACCEPTANCE-CLOSEOUT-2026-08-05.md).

## Current state and limits

```text
ENV_1B3_started=true
ENV_1B3_validation_kit_repository_implementation=true
ENV_1B3_completed=true
clean_Windows_validation=true
Release_candidate_independently_tested_on_separate_Windows_host=true
Candidate_08_immutable=true
Candidate_08_physical_windows_validation_passed=true
first_clean_Windows_RC_accepted=true

Release_activation_implemented=false
OPS_3B_implemented=false
formal_Release_created=false
formal_release_deployed=false
Production_Baseline_approved=false
production_approved=false
production_validation=false
production_deployment=false
github_ci_verified=false
```

Candidate 01–07 and the diagnostic Probes remain historical immutable repository-external artifacts; Candidate 08 is the accepted clean-Windows RC. A Release Candidate is a validation artifact, not a formal Release, activation, deployment or Production Baseline. The next active gates are DATA-1 and Fresh Install Bootstrap.
