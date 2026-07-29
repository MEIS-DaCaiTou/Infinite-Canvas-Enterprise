# ENV-1B3 independent Windows validation kit

This kit is the single test-host interface for `ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE`. It uses Windows PowerShell and the candidate's own `APP_ROOT\python\python.exe`; it never falls back to PATH Python and does not require GitHub credentials or repository write access.

The artifact verifier preserves the Manifest v2 inventory's required ordinal path order when deriving its canonical tree identity and accepts legitimate zero-length files while continuing to reject negative sizes, duplicate paths and any archive/inventory mismatch.

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
