# Enterprise Test Scripts

This folder is the only place for project diagnostic and smoke-test scripts.

Before adding or changing scripts, read:

- `../../PROJECT_HANDOFF_FOR_NEW_AGENT.md`
- `../../AGENT_CONTEXT.md`
- `../../ENTERPRISE_DOCS.md`
- `SMOKE_CHECKLIST.md`

## Scripts

- `diagnose.ps1` checks local version, selected LAN IP, listening ports, proxy settings, and health endpoints.
- `smoke.ps1` runs non-destructive HTTP smoke checks against a running enterprise gateway.
- `test_start_stop.ps1` accepts a temporary runtime root, random ports and the fixed fixture-child wrapper for a non-production lifecycle check. It refuses to kill existing listeners, verifies short-lived CLI start, restart ACK/PID generation changes and owned-only stop/port release.
- `test_stab_1_supervisor_logging.py` verifies STAB-1 with a temporary runtime root, random fixture ports and local HTTP child processes: role-isolated restart, crash-loop blocking, reserved/adopted lock cleanup, instance-bound ACKs, graceful wrapper shutdown, owned-child fallback after Job termination, state atomicity, stream persistence, extended redaction, rotation, port gate classification, and no-shell/no-browser runtime source boundaries.
- `test_ops_runner.py` verifies the OPS-2A command runner with temporary app roots, including inventory, source-bound SQLite backup manifest/copy, data-check, release validation, upgrade-plan generation, and JSONL job logs.
- `test_ops_3a_online_update.py` verifies OPS-3A trusted release metadata and bounded generic provider diagnostics, strict `ops-release-manifest-v1`, repository-bound GitHub Asset API downloads with metadata/asset-specific private-request headers and cross-host credential stripping, atomic download with stable redacted failure detail codes, Windows-safe ZIP traversal/ADS/device-name/control-character/duplicate/ZIP-bomb rejection, fresh staging revalidation, source-tree and compatibility-bound evidence, SQLite-header/sidecar preparation with no database side effects, source-bound backup and data-check evidence, newer-only release selection, redacted structured jobs, non-executing preparation plans, and direct-runner compatibility using temporary directories only.
- `test_sec_1b1_role_auth.py` verifies legacy/new users schemas, including LEGACY `is_admin=NULL` to raw READY `is_admin=0` normalization, explicit role/auth migration planning and rollback, current-state JWT principals, auth-version session invalidation, and existing admin/feature/WebSocket compatibility using temporary SQLite databases only.
- `test_sec_1f0_security_audit.py` verifies the explicit mandatory security-audit migration, append-only triggers, actor validation, caller-owned transactions, fail-closed writes, recursive sensitive-field rejection, and bounded JSON context using temporary SQLite databases only.
- `test_sec_1c0_super_admin_protection.py` verifies the transitional actor-first role matrix, principal auth-version binding, missing-target non-enumeration, raw main.users readback integrity, denied-audit classification, READY legacy-create rejection, post-authorization PBKDF2 execution, username-conflict/create-error contracts, atomic mandatory audit, last-active-super-admin protection, legacy-mutator rejection, and TEMP-users resistance using temporary SQLite databases only.
- `test_sec_1b2_activation_bootstrap.py` verifies main-schema migration qualification, caller-owned SEC-1B1/SEC-1F0 transactions, LEGACY NULL administrator-flag normalization and post-migration READY integrity gates, immutable lifecycle DDL and duplicate-key/type-sensitive bootstrap-audit matching, source-bound formal backups, WAL-to-DELETE preparation with structured external data/schema-change reports, read-only plan validation before any execute prompt, durable commit-state reporting, local-only runner surface and session-impact confirmation, full LEGACY-to-ACTIVE rehearsal, dynamic token invalidation, supported resume states, lock rejection, and rollback injection using temporary SQLite databases only.
- `ready_user_fixture.py` is test-only SQL setup for normal users in explicit temporary ROLE_AUTH_READY databases; it is not a production creation path.
- `test_ownership_isolation.py` runs non-destructive ownership isolation checks with a temporary SQLite database and temporary project/canvas/conversation files, including A/B/admin project owner, project-list, canvas-move, and direct-ID denial cases.
- `test_smart_canvas_logs.js` verifies Smart Canvas legacy log normalization, merge behavior, and async task completion logging hooks without calling a model provider.
- `SMOKE_CHECKLIST.md` is the manual checklist to run after every upstream update.
- `BROWSER_REGRESSION_CHECKLIST.md` is the browser-level enterprise regression checklist for login, roles, admin console, entry governance, canvas, conversations, assets, and upstream-sync review.
- `browser-regression.md` describes the minimal automation plan for future browser-level regression scripts.
- `UPDATE_TEST_LOG.md` records the actual result after each upstream update test pass.
- `../../ENTERPRISE_ISOLATION_MATRIX.md` is the data-domain and API permission source of truth for Task 3G follow-up isolation tests.
- `../../ENTERPRISE_PERMISSION_DESIGN.md` defines page permissions, administrator switches, phased delivery, and the A/B/admin acceptance contract.
- `../../PROJECT_HANDOFF_FOR_NEW_AGENT.md` records the current main handoff state, PR #18-#24 timeline, and the next recommended Task 3G sequence for a new Codex conversation.

Run scripts from the project root unless a script says otherwise.

Do not place ad-hoc diagnostic or smoke-test scripts in the project root, `static/`, or other upstream-owned folders. Keep them here so upstream updates and Git reviews stay clean.

For every Task 3G implementation PR, add or extend a focused test here before changing access behavior. Use temporary SQLite databases and temporary data files only. The minimum regression roles are normal user A, normal user B, and administrator; cover list filtering, direct-ID denial, resource URLs, refresh/re-login persistence, and WebSocket delivery where applicable.
