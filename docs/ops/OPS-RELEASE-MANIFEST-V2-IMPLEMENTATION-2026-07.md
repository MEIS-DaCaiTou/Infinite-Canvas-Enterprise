# OPS Release Manifest v2 repository implementation

Date: 2026-07-29
Baseline: `main@ea71a9a73c80244f679487c35a960ceea7732876`

## Status

- `OPS_RELEASE_MANIFEST_V2_repository_implementation_independently_accepted=true`
- `Manifest_v2_repository_implementation=true`
- `Release_candidate_payload_buildable=true`
- `Release_candidate_payload_offline_verifiable=true`
- `portable_startup_bound_to_Manifest_v2=true`
- `original_independent_review_blockers_closed=5`
- `remaining_code_blockers=0`
- `remaining_evidence_blockers=0`
- `remaining_test_blockers=0`
- `ops_release_manifest_v1_unchanged=true`
- `runtime_manifest_v1_preserved=true`
- `Manifest_v2_implemented=true` means the independently accepted repository implementation; it does not mean activation or production approval.
- `ENV_1B3_started=false`
- `clean_Windows_validation=false`
- `Release_activation_implemented=false`
- `OPS_3B_implemented=false`
- `formal_Release_created=false`
- `Production_Baseline_approved=false`
- `production_approved=false`
- `production_validation=false`

## Contract and topology

`ops-release-manifest-v2` is a new strict, canonical, exact-key schema. It does not modify the frozen `ops-release-manifest-v1` parser/model used by OPS-3A, and it does not replace `enterprise-windows-runtime-manifest-v1`, which remains the bounded Python startup view.

The authoritative v2 manifest is detached from the ZIP. The ZIP contains exactly one declared top-level Release root and the complete payload inventory—no embedded authoritative manifest and no root-prefix outsiders. Materialization first verifies the detached manifest, external inventory and every archive entry, extracts into a new directory, copies the exact manifest and inventory bytes as materialization metadata, then re-verifies the materialized payload.

The fixed release ID algorithm is `ice-<tracked VERSION>-<enterprise commit first 12>`. Enterprise commit/tree and `SOURCE_DATE_EPOCH` come from one clean exact Git HEAD. Operator release-ID or trust-root overrides are not accepted.

## Bound evidence

The manifest independently binds:

- enterprise and upstream repository/commit/tree/version identities;
- the exact Git-tracked Release payload-policy bytes, SHA-256 and Git blob identity, with every declared include required to exist and the application-source inventory cross-bound entry-for-entry to the global payload inventory;
- deterministic archive name/root/hash/size/global inventory/tree;
- accepted CPython 3.14.6 / cp314 Runtime Manifest v1, Runtime tree/archive/provenance, source policy, dependency lock, wheelhouse, installed closure and dependency graph;
- CycloneDX 1.6 SBOM and dependency edges, including one explicit component for every vendored frontend library/font set actually present in the payload;
- a Git-tracked third-party component policy, exact payload paths and hashes, machine-readable license evidence plus human notice; SBOM and license component sets are equal, distribution metadata without a license declaration is unresolved, and `unresolved_count=0` is derived rather than asserted (`legal_review_complete=false`);
- ENV-1B1A deterministic static builder record and source/output trees;
- config metadata without values or secrets;
- normalized empty-database schema snapshot and Git-tracked migration identifiers.

The configuration contract covers exactly the twelve current operator inputs, including `ENTERPRISE_REPO_URL`, `ENTERPRISE_UPDATE_ENABLED`, and `ENTERPRISE_HIDE_UPSTREAM_AUTHOR`; an AST drift test rejects additions or removals. It contains classifications only—never values, secrets, computed paths, or local machine identities.

DATA-1/restore remain incomplete, so the database contract is deliberately fixed to `migration_compatibility=unclassified`, `rollback_classification=unclassified`, and `ops3b_activation_eligible=false`.

## Portable trust chain

Portable start/restart now bind `current-release.json.manifest_sha256` to raw `APP_ROOT/release-manifest.json`, validate v2 and the complete materialized payload before Runtime Manifest v1/Python/probes, then propagate these fields through StartupPreflight v2, Launch Context v2, STAB-1 lock/state/supervisor ownership and readiness:

- `release_manifest_sha256`
- `release_payload_tree_sha256`
- `enterprise_commit`
- `enterprise_tree`

Host/child validation uses the retained immutable context and startup-critical hashes rather than rehashing the entire APP_ROOT. Status can report a damaged current manifest without authorizing start. Stop can still stop an actually owned retained instance using context/lock/state/process identity; a foreign instance remains fail-closed.

Both minimum compatibility fields are strict positive integers and are enforced against the single repository constant `PORTABLE_RELEASE_CONTRACT_VERSION=2` before portable startup can proceed. A future contract is rejected with the stable `PORTABLE_RELEASE_CONTRACT_UNSUPPORTED` code; status remains diagnostic and the existing owned retained-context stop boundary is unchanged.

## Builder and verifier boundaries

`tools/build_release_manifest_v2.py` exposes explicit-path `build`, `verify`, `materialize-fixture`, `verify-materialized`, and `inspect` operations. It writes only to a new caller-owned output root, performs no activation, and never writes formal INSTALL_ROOT/STATE_ROOT. The payload is exported from Git rather than copied from a dirty worktree. The existing static builder and accepted ENV-1B2B Runtime evidence are reused; this task does not rebuild the Runtime.

Detached manifest, inventory and archive inputs, materialized APP_ROOT, and builder/materializer roots use the shared path-safety primitives for regular-file, no-reparse-ancestor, containment and root-overlap checks. Git symlink modes, archive symlink/reparse entries, duplicate/case-fold collisions and traversal paths fail closed. Host and child retained-context validation reaches the same path-safe Manifest reader.

The concentrated correction reproduced and closed all five independent-review blockers. Focused evidence is `104 passed, 4 platform skips` for Release v2/portable/lifecycle/wrapper tests and `30 passed, 2 warnings` for static/audit. The audit result is `scanned=100`, `detected=mapped=368`, with parse/uncovered/stale/missing/invalid all zero and digest `b237e92a27ff6da88f70a6e542743ef0a6a6228fff7d5f9a9e47430cdd78299b`.

## Independent acceptance and final regression baseline

- `full_repository_regression_passed=true`
- `full_repository_regression_interpreter=CPython 3.11.9 x64`
- `collected=624`
- `executed=624`
- `passed=615`
- `skipped=9`
- `failed=0`
- `omitted=0`
- `extra=0`
- `duplicate=0`
- `aggregate_exit=0`
- `interpreter_switching=false`
- `github_ci_verified=false`

The earlier three failing nodes were reproduced as effects of a non-canonical host test environment. They passed with the complete 624/624 aggregate in the dedicated development test environment; this classification is an environment finding, not a repository, Runtime, or PR code failure.

Environment facts:

- `dedicated_dev_test_environment_established=true`
- `legacy_upstream_python_restored=true`
- `legacy_upstream_python_identity=CPython 3.10.11 x64`
- `accepted_CP314_Runtime_unchanged=true`
- `python_deletion_actor=not_proven`
- `host_python_maintenance_side_effect_recorded=true`

The host Python maintenance side effect was recorded without modifying this PR, contaminating the dedicated development virtual environment, or changing the accepted CP314 Runtime.

External Build A/B, real CP314 formal-entry fixture, final test aggregates and hashes are review evidence under the repository-external task artifact root and are not committed here.
