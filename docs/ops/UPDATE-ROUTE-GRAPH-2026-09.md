# Update Route Graph (2026-09)

## Purpose and boundary

The Update Center must not infer compatibility merely because a target version is newer. A published route declaration names exact source Release identities, Manifest hashes, database schema hashes, the minimum source updater contract, migration mode, and target channel. The operator chooses a target; the server plans a path. Every hop still runs the existing Manifest v2, inventory, database, backup, restart, and recovery checks. A route declaration is not a substitute for those checks.

`upgrade-routes-v1.json` is an optional fourth GitHub Release asset. Its GitHub SHA-256 digest is checked on download, and its target Manifest SHA-256, Release ID, version, and stable/development stage are cross-checked against the existing Manifest v2 asset. This preserves the old three-asset Manifest v2 format and does not make the published 09.6 updater reject new releases merely because they have an extra asset. Missing, invalid, ambiguous, or mismatched route assets are never interpreted as a safe direct upgrade.

The 2026.09.7 development Release has an additive route asset declaring only `ice-2026.09.6-8f65c5cd328f` as an allowed same-schema source. It does not modify that Release's ZIP, Manifest, or inventory. The declaration is **not** a production-approved stable bridge and does not claim that arbitrary 09.6 installations share the tested legacy schema.

## Current implementation

- `enterprise/ops/update/upgrade_routes.py` validates canonical declarations and plans the shortest exact-identity path. Stable selection never traverses a development intermediate. It rejects guessed edges, schema/Manifest mismatches, unsupported updater contracts, duplicate target identities, and routes beyond eight hops.
- `enterprise/ops/update/route_catalog.py` verifies route and Manifest assets, requires the current pointer's Release ID and Manifest hash to match the installed Release, and checks the installed SQLite schema against that Release's database evidence before advertising a path.
- `GET /enterprise/api/update-mvp/check` distinguishes `direct`, `requires_intermediate`, `route_missing`, `route_invalid`, `source_unverified`, and `path_unavailable`. The legacy `update_available` flag now means a directly reachable stable release, not merely a larger version number.
- The management page explains each status and disables the upgrade button unless the selected Release is directly reachable. `POST /enterprise/api/update-mvp/prepare` repeats the exact source and route checks, then binds the downloaded target Manifest and database schema evidence to the declaration before making a READY job; the existing update service rechecks the database contract before switching.
- `tools/build_upgrade_routes.py` builds a route asset from a fully verified target Release and fully verified materialized source Release roots. Release owners must review every declared source and updater contract. The tool never derives compatibility from version order alone.

## Explicitly not complete

This first slice **does not execute a multi-hop path under one authorization**. A target whose path contains an intermediate is shown with its route but remains blocked; the UI does not pretend the update will run automatically. A persistent coordinator across process restarts, scoped authorization for all hops, verified prefetch, and per-hop resume/rollback evidence are required before enabling one-confirmation multi-hop execution. Never store an administrator password in browser/session storage or state files to bridge process restarts.

The current GitHub candidate listing reads at most the latest 50 releases and the planner allows at most eight hops. Older installations whose required bridge has fallen outside that bounded catalog will fail closed, not receive a guessed path. Before promising a one-year-skip experience, add bounded pagination or a signed/verified route index, catalog caching, and a real multi-hop coordinator with targeted long-gap drills.

Before releasing a schema-changing target, publish and test a stable same-schema bridge for stable customers if one is required. A development prerelease such as 09.7 must not silently become a mandatory stable-channel intermediate. Each allowed source→target edge needs an install-copy drill using exact published assets, including source data preservation, target start, failure rollback, and `RECOVERY_REQUIRED` behavior. A completed first hop followed by a failed later hop is a safe partial-chain state, not a claim of all-or-nothing rollback to the original version.

No customer device, independent clean Windows host, or real multi-hop execution was exercised by this route-graph change. Targeted tests and a mocked management-page render are implementation evidence only.
