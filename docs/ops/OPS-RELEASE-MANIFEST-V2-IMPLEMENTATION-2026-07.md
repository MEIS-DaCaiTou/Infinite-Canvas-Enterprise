# OPS Release Manifest v2 repository implementation

Date: 2026-07-28
Baseline: `main@ea71a9a73c80244f679487c35a960ceea7732876`

## Status

- `Manifest_v2_repository_implementation_present=true`
- `Manifest_v2_independent_acceptance_pending=true`
- `ops_release_manifest_v1_unchanged=true`
- `runtime_manifest_v1_preserved=true`
- `Manifest_v2_implemented=true` means repository implementation in this Draft PR; it does not mean activation or production approval.
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
- deterministic archive name/root/hash/size/global inventory/tree;
- accepted CPython 3.14.6 / cp314 Runtime Manifest v1, Runtime tree/archive/provenance, source policy, dependency lock, wheelhouse, installed closure and dependency graph;
- CycloneDX 1.6 SBOM and dependency edges;
- machine-readable third-party license inventory plus human notice (`unresolved_count=0`, `legal_review_complete=false`);
- ENV-1B1A deterministic static builder record and source/output trees;
- config metadata without values or secrets;
- normalized empty-database schema snapshot and Git-tracked migration identifiers.

DATA-1/restore remain incomplete, so the database contract is deliberately fixed to `migration_compatibility=unclassified`, `rollback_classification=unclassified`, and `ops3b_activation_eligible=false`.

## Portable trust chain

Portable start/restart now bind `current-release.json.manifest_sha256` to raw `APP_ROOT/release-manifest.json`, validate v2 and the complete materialized payload before Runtime Manifest v1/Python/probes, then propagate these fields through StartupPreflight v2, Launch Context v2, STAB-1 lock/state/supervisor ownership and readiness:

- `release_manifest_sha256`
- `release_payload_tree_sha256`
- `enterprise_commit`
- `enterprise_tree`

Host/child validation uses the retained immutable context and startup-critical hashes rather than rehashing the entire APP_ROOT. Status can report a damaged current manifest without authorizing start. Stop can still stop an actually owned retained instance using context/lock/state/process identity; a foreign instance remains fail-closed.

## Builder and verifier boundaries

`tools/build_release_manifest_v2.py` exposes explicit-path `build`, `verify`, `materialize-fixture`, `verify-materialized`, and `inspect` operations. It writes only to a new caller-owned output root, performs no activation, and never writes formal INSTALL_ROOT/STATE_ROOT. The payload is exported from Git rather than copied from a dirty worktree. The existing static builder and accepted ENV-1B2B Runtime evidence are reused; this task does not rebuild the Runtime.

External Build A/B, real CP314 formal-entry fixture, final test aggregates and hashes are review evidence under the repository-external task artifact root and are not committed here.
