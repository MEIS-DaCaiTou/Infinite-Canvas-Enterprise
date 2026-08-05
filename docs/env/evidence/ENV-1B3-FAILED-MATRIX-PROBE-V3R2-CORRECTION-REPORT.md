# ENV-1B3 Failed Matrix Probe v3R2 Correction

## Review input

Probe v3R1 artifact integrity passed, but independent review did not authorize Guest execution. Two execution-contract blockers remained: its `W08Aggregate` path could re-enter `Invoke-TamperMatrix.ps1 -Mode All`, and its W12 audit did not derive the complete W12 evidence set directly from the immutable Probe v2 evidence ZIP.

Candidate 05 remains `ice-2026.07.6-52bcc5f711ab-candidate-05`, bound to handoff SHA-256 `a2f9e7ccb9cb78960ca69eb984c8d669288146e80a438427efc2e4952daec3b6`. The source Probe v2 Guest evidence ZIP is bound to SHA-256 `7f7da28693beb5e3ef1c4c5c79a9be28cabee1308ac2cffcf04cc89c698ec8ae`. Candidate 06 remains unauthorized and unbuilt.

## Corrections

1. `W08HostAggregate` is host-only and process-free. It reads five exclusive exported target records, validates schema/task/matrix/case/subcheck/result/code and required evidence/context/fixture facts, rejects duplicate or unexpected inputs, copies with create-new semantics, records every source SHA-256, emits a canonical evidence-set SHA-256, and only then completes W08.
2. `PROBE-MANIFEST.json` separates Guest-executable and host-only modes. The legacy `W08Aggregate` public mode is deprecated and always returns `ENV1B3_DEPRECATED_W08_AGGREGATE_MODE`; it cannot dispatch Tamper `All`.
3. W12 evidence is read directly from the bound Probe v2 ZIP. The audit normalizes slash styles before collision checking, rejects unsafe paths and symlinks, verifies exact `57/57` `SHA256SUMS` closure, validates Candidate 05/handoff/modified state, and binds aggregate, four subchecks, recovery evidence, pointer/no-partial facts, retry success and a canonical evidence-set SHA.
4. An optional W12 extracted mirror is never authoritative; every required mirror file must byte-match the corresponding bound ZIP member.
5. ContractAudit requires the host-only W08 aggregation marker, five declared source hashes, recomputed copied-record hashes, W08 evidence-set SHA, and the complete W12 ZIP/Candidate/aggregate/subcheck/recovery/evidence-set binding.

## Developer verification

- Consolidated matrix/validation-kit/materialized-verifier/Manifest v2/APP_ROOT audit regression: 175 passed, 5 skipped, 2 warnings.
- The matrix focused subset includes real Windows PowerShell 5.1 parsing and process invocation.
- The supplied Probe v2 Guest evidence ZIP passed the direct v3R2 audit: outer SHA matched, internal `SHA256SUMS` verified `57/57`, Candidate 05 was unchanged, W12 aggregate SHA-256 was `d89b0787b1a748330e1438b2b648ae2801eeac462dcf0f7624e005349ed83253`, and the canonical W12 evidence-set SHA-256 was `a8f0ebcb8c267d4c2a686f7bfe873a367a0207e512f330398b8c7bda6a3ba31b`.
- `python -m compileall enterprise tools`: exit 0.
- The final enterprise full suite was not run, as required while Candidate 06 remains unauthorized.

## Boundaries

Probe v3R2 remains `diagnostic_only=true`, `not_a_release_candidate=true`, `cannot_support_final_acceptance=true`, and `production_approved=false`. Candidate 01–05 and Probes v1/v2/v3/v3R1 remain preserved. The enterprise full suite remains intentionally deferred. No production or temporary business test environment was accessed.
