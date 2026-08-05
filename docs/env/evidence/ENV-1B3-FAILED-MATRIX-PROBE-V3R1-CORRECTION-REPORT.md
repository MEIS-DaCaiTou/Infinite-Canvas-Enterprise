# ENV-1B3 Failed Matrix Probe v3R1 Correction

## Review input

The immutable Probe v3 ZIP SHA-256 is `b5554ae8fc422df7cd94f784f109c3c4893047c54cf04c871fdd8910062cabff`. Its artifact integrity passed, but independent review withheld Guest execution for four execution-contract blockers. Probe v3 is preserved and is not overwritten.

Candidate 05 remains `ice-2026.07.6-52bcc5f711ab-candidate-05`, bound to handoff SHA-256 `a2f9e7ccb9cb78960ca69eb984c8d669288146e80a438427efc2e4952daec3b6`. Candidate 06 is not authorized or built.

## Corrections

1. W08 has five independent public target modes. Each checks the shared Runtime lock, state, related processes and candidate ports before copying or starting anything. A dirty baseline emits `ENV1B3_W08_RUNTIME_BASELINE_DIRTY`, result BLOCKED and exit 2; it is not cleaned. Each target writes only its matching exclusive subcheck. The test-host workflow restores the same pre-target checkpoint between modes before host-side aggregation.
2. The v3R1 public entry parses the child's final JSON. It preserves PASS/FAIL/BLOCKED and the child code under the exact `0/2` contract. Only timeout, invalid JSON/result, or exit/result disagreement receives `ENV1B3_PUBLIC_MODE_TIMEOUT`, `ENV1B3_PUBLIC_MODE_OUTPUT_INVALID`, or `ENV1B3_PUBLIC_MODE_EXIT_CONTRACT_INVALID`.
3. ContractAudit covers W05, W08, W09, W10, W11, W12 and W13. It validates subcheck schema/task/matrix/case/subcheck/filename/result identity; rejects null or blank required values; requires context and fixtures to equal boolean true; and requires a PASS aggregate with the exact all-PASS mandatory set.
4. W12 supplemental evidence binds Candidate 05, the Probe v2 Guest evidence ZIP SHA, the original W12 aggregate SHA and successful retry evidence. ContractAudit verifies all four bindings.
5. W13 has separate `permanent_exclusions_absent` and `permanent_exclusions_unchanged` mandatory subchecks. Null/blank values normalize away. A real pre-existing exclusion produces absence BLOCKED, while an unchanged before/after set independently passes. The tool never deletes or changes existing exclusions.

## Developer verification

- Matrix-contract and public-entry focused tests: 24 passed.
- Validation-kit, materialized-verifier, Manifest v2 and APP_ROOT audit regression group: 130 passed, 5 skipped, 2 warnings.
- Staged-file APP_ROOT audit regression: 30 passed, 2 warnings.
- `python -m compileall enterprise tools`: exit 0.
- The final enterprise full suite was not run, as required while Candidate 06 remains unauthorized.

## Boundaries

The v3R1 bundle remains `diagnostic_only=true`, `not_a_release_candidate=true`, `cannot_support_final_acceptance=true`, and `production_approved=false`. Candidate 01–05 and Probes v1/v2/v3 remain preserved. The final enterprise suite is intentionally deferred. No production or temporary business test environment was accessed.
