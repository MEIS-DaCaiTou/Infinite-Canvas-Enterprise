# ENV-1B3 Failed Matrix Closure Probe v3

## Input evidence

- Probe v2 Guest evidence SHA-256: `7f7da28693beb5e3ef1c4c5c79a9be28cabee1308ac2cffcf04cc89c698ec8ae`.
- Internal `SHA256SUMS`: 57 of 57 verified.
- Probe developer Head: `9193ed1c2c2ce06f59d2ddf014ec8eeeb219f94c`.
- Candidate: `ice-2026.07.6-52bcc5f711ab-candidate-05`.
- Candidate handoff SHA-256: `a2f9e7ccb9cb78960ca69eb984c8d669288146e80a438427efc2e4952daec3b6`.
- Candidate content was not modified; S0/S1 checkpoint identities were preserved.

The complete execution context and original W08-W13 evidence were reviewed, including the all-zero 832-byte `REBOOT-RESUME.json`. Probe v2 reported 7 PASS, 5 FAIL and 1 BLOCKED. The failures demonstrate validation-tool defects; they do not establish a Candidate Runtime defect.

## Corrections

- Public Probe v3 modes execute in bounded Windows PowerShell 5.1 child processes. PASS returns process exit 0; FAIL and BLOCKED return 2.
- W08 arrayizes `Compare-Object`, bounds every wrapper, records every target/stage/exit/process/failure field, uses independent roots and only verified-owned cleanup.
- W09 records fixture copy, healthy start, retained-context stop, foreign identity/rejection/survival, identity restore, owned cleanup and port release. Early failure retains runtime/lock/state/context diagnostics and marks `candidate_runtime_defect_proven=false`.
- W10 constructs wrapper names from Unicode code points and records a real controlled-listener result.
- W11 state uses `FileStream` write-through, `Flush(true)`, close, JSON re-read, SHA-256, atomic replace and post-commit verification. Resume rejects missing, zero, all-zero, malformed, hash-mismatched or identity-mismatched state with `ENV1B3_REBOOT_STATE_DURABILITY_FAILED` or the stable identity error. Graceful Guest reboot and Hyper-V hard reset are separate classifications.
- W12 recovery evidence contains `retry_after_cleanup_passed`.
- W13 ignores null/blank exclusions, compares real exclusions case-insensitively, and separately records scan completion, unchanged exclusions and whether a permanent exclusion was added.
- W05 records `LongPathsEnabled`, longest path length, fixed CP314 real file I/O, PowerShell materialization and lifecycle results. A disabled OS policy remains BLOCKED and is not changed by the tool.
- `ContractAudit` verifies the manifest-bound contract SHA, mandatory/unexpected/duplicate subchecks, required evidence/context/fixtures and aggregate consistency.

## Boundaries

`diagnostic_only=true`, `not_a_release_candidate=true`, `cannot_support_final_acceptance=true`, and `production_approved=false`.

Candidate 05 and Probes v1/v2 remain unchanged. Candidate 06 was not built. The enterprise full suite was not run at this diagnostic stage. Independent Guest execution is still required.

The APP_ROOT write audit remains `scanned=121`, `excluded=286`, `detected=383`, `mapped=383`, with zero parse failures, uncovered sites, stale mappings, missing anchors or invalid flows. Its frozen digest is `46e39d7a83266b880eda2cbb5d94b9220c0872707761a5962384e8651a8de3e5`; Probe evidence remains caller-owned repository-external W45.
