# ENV-1B3 independent Windows validation kit

This kit is the single test-host interface for `ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE`. It uses Windows PowerShell and the candidate's own `APP_ROOT\python\python.exe`; it never falls back to PATH Python and does not require GitHub credentials or repository write access.

The artifact verifier preserves the Manifest v2 inventory's required ordinal path order when deriving its canonical tree identity and accepts legitimate zero-length files while continuing to reject negative sizes, duplicate paths and any archive/inventory mismatch.

Materialization keeps Release construction separate from verification. It extracts only to `install/staging/<release_id>.partial`, copies the detached manifest, and runs the SHA-bound standalone `verify_materialized_release.py` under the staged Release's fixed `python/python.exe -I -B`. The verifier is part of the validation kit, imports no repository modules, performs no network or write operation, and checks the exact payload closure, hashes, sizes, path safety, Manifest identity and payload-tree identity. Only a verified staging tree is atomically moved to `install/releases/<release_id>`; `current-release.json` is committed last through an exclusive temporary file. Failure removes the owned staging/final tree and pointer temp while preserving any earlier pointer.

The environment baseline normalizes both CIM `System.DateTime` and DMTF-string install dates to invariant UTC. Missing or invalid values remain nullable diagnostics and cannot produce a clean-host PASS. The public entrypoint treats PowerShell script success independently from native executable exit codes, so strict mode never consumes an unset or stale `$LASTEXITCODE`; scripts that invoke native tools capture that tool's exit code immediately.

W01 invokes the fixed system `where.exe` through a controlled process wrapper: stdout, stderr and the current process exit code are captured independently; exit `0` means found, exit `1` is normal absence, and other codes fail closed. WindowsApps command aliases are recorded but do not count as usable external Python. Uninstall inventory reads inspect the `DisplayName` property before accessing it, so missing, null or blank values are ignored under strict mode. A recorded BypassNRO choice makes the baseline non-pristine but does not by itself invalidate a clean Windows Runtime baseline.

## Safety boundary

- Work only under explicit absolute `HandoffRoot`, `TestRoot`, and `EvidenceRoot` paths.
- Keep the handoff input immutable. Materialization and tamper cases use new directories or copies.
- Never use production configuration, credentials, databases, addresses, or user data.
- Application lifecycle tests run as a standard non-administrator user. Administrator work is limited to snapshot, ACL, isolated-volume, and test-user preparation.
- Do not disable Defender, add permanent exclusions, download dependencies, install system Python, or edit candidate payload files to make a case pass.
- W11 reboot happens only after the user explicitly approves it. The kit writes `REBOOT-RESUME.json`; it does not reboot by itself.
- W12 requires a user-provided isolated low-space volume. It never fills the system volume.

## Entry point

Run from any current directory:

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\validation-kit\Invoke-ENV1B3Validation.ps1 `
  -Mode Full `
  -HandoffRoot <HANDOFF_ROOT> `
  -TestRoot <TEST_ROOT> `
  -EvidenceRoot <EVIDENCE_ROOT> `
  -CleanHostClassification fresh_vm_snapshot
```

`Mode=Full` performs the non-destructive initial sequence and emits stable per-case JSON. Continue through the same entrypoint with `UnicodeLifecycle`, `LongPathMaterialize`, `Permission`, `OfflinePollution`, `Tamper`, `OwnedStop`, `ForeignStop`, `PortConflict`, `RebootPrepare`/`RebootResume`, `LowDisk`, `ArchiveLock`, and `DefenderStatus`; fixture-dependent modes require the matching explicit root parameter. The named scripts are internal case implementations, not a second public interface. `Mode=FinalIdentity` is reserved for the approved final-identity subset after a valid `FINALIZATION-DELTA.json` inheritance decision.

The authoritative case list and stable script mapping are in `matrix.json`. Each case record contains `case_id`, preconditions/action evidence, stable result/code, and bounded summaries. Raw machine names, usernames, secrets, environment values, and unnecessary absolute paths are excluded.

## Required sequence

1. Entry `Mode=Full` for W01-W03 on a new test root.
2. Entry `UnicodeLifecycle`, `LongPathMaterialize`, `Permission`, and `OfflinePollution` for W04-W07.
3. Entry `Tamper`, `OwnedStop`, and `ForeignStop` for W08-W09, always on copies.
4. Entry `PortConflict`, `LowDisk`, `ArchiveLock`, and `DefenderStatus` for W10/W12/W13 with isolated fixtures.
5. Entry `RebootPrepare` before and `RebootResume` after a user-approved reboot for W11.
6. Entry `Export` only after W01-W14 all have PASS records.

Any mandatory `FAIL` or `BLOCKED` prevents `clean_Windows_validation=true`.

Candidate sequences 01-03 are the original bounded allowance. Sequence 04 is accepted only under the project-owner governance exception recorded after Candidate 03 exposed validation-tool defects before the clean-host matrix began; the generator does not accept later sequences.

`New-W01StabilizationProbe.ps1` builds a repository-external diagnostic bundle containing only the W01 module, collector, Probe entry, manifest and SHA256SUMS. The Probe is explicitly not a Release Candidate and cannot support final acceptance; its fixture mode exists only for developer-side regression, while the independent Guest runs the entry without fixture injection.

Candidate 05 is the project-owner-authorized final validation candidate. `New-CandidateHandoff.ps1` requires its independently passed W01 Probe Head, Probe evidence SHA-256 and `S0-WIN11-CLEAN-RUNTIME-BASELINE` checkpoint source and records them in `CANDIDATE-HANDOFF.json`. Test-host orchestration must read JSON with `Get-Content -Raw -Encoding UTF8` or byte-level UTF-8 decoding; Windows PowerShell's default ANSI code page is not an evidence parser.

`New-RemainingMatrixProbe.ps1` creates a repository-external diagnostic-only bundle for Candidate 05. It binds the original immutable handoff ZIP and the standalone materialized verifier, supports W02-W11/W14 plus M01 injected-failure atomicity, and is explicitly neither a Release Candidate nor evidence capable of final acceptance.

That first Remaining Matrix Probe remains preserved as an integrity-valid materialization diagnostic, but its public interface is not a complete W02-W14 execution contract. `New-RemainingMatrixProbeV2.ps1` creates the replacement diagnostic bundle without changing or repacking Candidate 05. Its versioned `matrix-contracts.json` names every mandatory subcheck, required context/fixture/evidence field, stable error code and all-subchecks-PASS aggregation rule. Subcheck evidence is written once under `subchecks/<case>/<subcheck>.json`; a later mode cannot overwrite an earlier branch.

The Probe v2 public entry is `Invoke-RemainingMatrixProbeV2.ps1`. It exposes `W02`, `W03`, `W04`, `W05`, `W06`, `W07`, `W08`, `W09`, `W10`, `W11StoppedPrepare`, `W11StoppedResume`, `W11RunningPrepare`, `W11RunningResume`, `W12`, `W13`, `W14Prepare`, `W14Validate`, and `M01`. W11 requires an approved Guest restart or controlled abnormal termination between its prepare/resume phases. W14 requires the test-host operator to make the returned materialized APP_ROOT read-only for the standard application user after `W14Prepare` and before `W14Validate`. W12 requires an isolated non-system small VHDX; W13 keeps Defender enabled and adds no permanent exclusion. Probe v2 is diagnostic-only, is not Candidate 06, cannot support final acceptance, and must not be used until its independent execution-contract review authorizes Guest execution.

Probe v3 is generated by `New-FailedMatrixClosureProbeV3.ps1` after the independent Probe v2 Guest run. Its only public entry is `Invoke-FailedMatrixClosureProbeV3.ps1`, with modes `W05`, `W08`, `W09`, `W10`, four explicit W11 phases, `W12EvidenceAudit`, `W13`, and `ContractAudit`. Every public mode runs its implementation in a bounded Windows PowerShell 5.1 child and returns process exit `0` only for PASS; FAIL and BLOCKED return `2`. `ContractAudit` verifies the hash-bound contract, mandatory and unexpected subchecks, case-fold duplicates, required fields/context/fixtures, and aggregate consistency. W11 uses durable write-through state and distinguishes `graceful_guest_reboot` from diagnostic `hyperv_hard_reset`. Probe v3 remains diagnostic-only and cannot support final acceptance.

Independent execution-contract review accepted the immutable Probe v3 ZIP but did not authorize Guest execution. `New-FailedMatrixClosureProbeV3R1.ps1` creates the correction without overwriting v3. Its formal W08 entries are `W08Pointer`, `W08ReleaseManifest`, `W08RuntimeManifest`, `W08Payload`, and `W08PythonDll`; `W08Aggregate` exists only for host-side aggregation and is not a Guest diagnostic entry. Before each target, the tool verifies that the shared Runtime lock/state, related processes, and candidate ports are clean. A dirty baseline is BLOCKED and is never cleaned to make the test pass.

For W08, restore the same Probe pre-target checkpoint, execute exactly one target, export its exclusive subcheck, restore the checkpoint, and repeat. Merge the five target subchecks only after all five independent runs, then run `ContractAudit`. The v3R1 public entry parses the child's final JSON and preserves PASS/FAIL/BLOCKED plus the child code; only timeout, malformed output, or exit/result disagreement receives a public-entry error. The audit validates every record and aggregate identity, meaningful required values, strict-true context/fixture fields, and the manifest-bound W12 supplemental evidence. W13 separately reports `permanent_exclusions_absent` and `permanent_exclusions_unchanged`; existing exclusions are not removed or renamed as absent.

Probe v3R2 replaces the untrusted v3R1 host aggregation path without modifying the immutable v3R1 ZIP. `PROBE-MANIFEST.json` separates `guest_executable_cases` from `host_only_cases`. `W08HostAggregate` reads exactly five exported target roots, validates each exclusive PASS record and its required context/fixture/evidence, copies each record with create-new semantics, records all five source SHA-256 values, and emits a canonical evidence-set SHA before completing W08. It never calls Tamper, launches the Candidate, accesses APP_ROOT, or cleans Runtime state. The old `W08Aggregate` mode is deprecated and returns `ENV1B3_DEPRECATED_W08_AGGREGATE_MODE`.

The v3R2 W12 audit reads the immutable Probe v2 Guest evidence ZIP directly. It verifies the outer SHA-256, normalized safe paths, no symlink/case-fold collision, exact internal `SHA256SUMS` closure (`57/57`), Candidate 05 identity, the W12 aggregate and four subchecks, recovery W02, pointer/no-partial facts, and retry success. An optional extracted mirror is accepted only when every required byte hash matches the ZIP. `ContractAudit` additionally binds W08's host-only source hashes/evidence-set identity and W12's source ZIP, Candidate handoff, aggregate/subcheck/recovery/evidence-set hashes.

Run every Probe v2 mode through the root entry, never an internal script:

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\Invoke-RemainingMatrixProbeV2.ps1 `
  -Mode <W02|...|W14Validate|M01> `
  -CandidateHandoffZip <CANDIDATE_05_HANDOFF_ZIP> `
  -HandoffRoot <EXTRACTED_CANDIDATE_05_HANDOFF_ROOT> `
  -TestRoot <CASE_TEST_ROOT> `
  -EvidenceRoot <CASE_EVIDENCE_ROOT>
```

Mode-specific contract fixtures remain explicit: W06 adds `-DeniedRoot`; W08/W09 add `-SourceInstallRoot` and `-CaseRoot`; W10 adds the controlled `-Port`; W12 adds `-IsolatedLowDiskRoot`. The entry derives Candidate identity and the ordinary APP_ROOT only from the hash-bound handoff when those optional values are omitted.
