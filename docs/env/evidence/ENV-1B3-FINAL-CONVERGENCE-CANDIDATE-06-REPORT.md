# ENV-1B3 final convergence and Candidate 06 report

Status: repository correction complete; Candidate 06 identity is published only in the immutable repository-external handoff and Draft PR after the evidence-bearing commit.

## Baseline and scope

- Initial Head: `6e6be22173700e9f4c572476712bae07211a976f`
- Initial tree: `c266184560d74f3b9fda6effc7cf88b2610c0ee7`
- Branch and PR: the existing ENV-1B3 branch and Draft PR #90
- Candidate 05 remained immutable and was not repacked, modified or removed.
- Candidate Runtime changed file: `enterprise/runtime/portable.py`. Prior Guest evidence did not establish a Runtime defect; the final local clean-root fixture did, as described below.
- Probe framework expansion stopped. No Probe v3R3 or replacement evidence platform was created.

## Final convergence

The validation kit now uses one shared, narrow diagnostic-manifest semantic gate. It binds the current manifest through the adjacent `SHA256SUMS`, then verifies task, Candidate, handoff, materialized-verifier and diagnostic-only booleans without hard-coding historical Probe schema names.

W05 preserves distinct long-path disabled, materialization, fixed-Python I/O, lifecycle and APP_ROOT-change errors. W08 adds a bounded healthy-pre-target checkpoint and retains five separately executable tamper targets. W09 accepts only a complete install root, rejects overlap and uses the Release's fixed CP314 interpreter for a long-path-aware, tree-verified copy. W10 derives upstream and gateway ports from formal status/config identity and tests recovery after each real-port conflict. W11 uses independent stopped/running journals with write-through, flush, parse, atomic commit and final-hash stages. W13 proves archive-lock fail-closed behavior, no partial/pointer pollution, same-Candidate recovery, Defender enabled/real-time scan and no newly added exclusion.

The first final-candidate lifecycle fixture also isolated a real clean-profile Runtime defect. After a successful materialization and after preserving an unrelated stale local fixture state, the fixed CP314 launcher reached the real portable preflight but failed because a new Windows profile had no `RUNTIME_ROOT`; writable probes ran before any directory-preparation call. The minimal correction creates only the five derived portable writable roots with existing pre-use/post-create no-reparse checks, then runs the unchanged self-cleaning probes. A dedicated regression removes all five roots and proves preflight recreates and probes them. No controller, supervisor, ownership, Manifest or activation behavior changed.

## Development evidence

- Initial ENV-1B3 focused validation tests: `92 passed`, `1 skipped`, `0 failed`.
- Initial Manifest v2 and APP_ROOT regression: `86 passed`, `4 skipped`, `0 failed`, `2 warnings`.
- Post-Runtime-correction focused regression: `199 passed`, `5 skipped`, `0 failed` across writable probe, portable preflight/lifecycle identity, ENV-1B3 validation kit and Manifest v2 tests.
- Windows PowerShell 5.1 parsing/integration: passed within the focused set.
- Compileall: exit `0`, with bytecode directed to a repository-external temporary cache.
- APP_ROOT audit: `scanned=131`, `excluded=290`, `detected=384`, `mapped=384`; zero parse failures, uncovered sites, stale mappings, missing anchors and invalid flows; digest `4d8d78573e7c6f1981b2e3939443ee0f5259099f27e3228299d2d880c80fdeb1`.
- Direct OPS scripts: both exit `0`.
- Final enterprise suite after the clean-profile Runtime correction: `708 passed`, `10 skipped`, `0 failed`, `8 warnings`, exit `0`; it was run once on the final code content with the dedicated CPython 3.11.9 x64 development interpreter.
- Interpreter switching: false.

## Boundaries

```text
clean_Windows_validation=false
ENV_1B3_completed=false
Candidate_05_preserved=true
Candidate_Runtime_modified=true
Release_activation_implemented=false
OPS_3B_implemented=false
formal_Release_created=false
Production_Baseline_approved=false
production_approved=false
production_validation=false
production_device_touched_by_codex=false
Ready=false
merged=false
```

Candidate 06 remains a validation candidate, not a formal Release or production deployment. Its independent physical-Windows W01-W14 matrix is the next gate.
