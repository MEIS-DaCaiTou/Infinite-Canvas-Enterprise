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
