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
- `test_start_stop.ps1` verifies the launcher lifecycle: stop old listeners, start the enterprise launcher, wait for health, terminate the launcher, and confirm `3001/8000` are released.
- `test_ops_runner.py` verifies the OPS-2A command runner with temporary app roots, including inventory, backup manifest/copy, data-check, release validation, upgrade-plan generation, and JSONL job logs.
- `test_sec_1b1_role_auth.py` verifies legacy/new users schemas, explicit role/auth migration planning and rollback, current-state JWT principals, auth-version session invalidation, and existing admin/feature/WebSocket compatibility using temporary SQLite databases only.
- `test_sec_1f0_security_audit.py` verifies the explicit mandatory security-audit migration, append-only triggers, actor validation, caller-owned transactions, fail-closed writes, recursive sensitive-field rejection, and bounded JSON context using temporary SQLite databases only.
- `test_sec_1c0_super_admin_protection.py` verifies the transitional actor-first role matrix, principal auth-version binding, missing-target non-enumeration, main.users affected-row and transaction-local readback integrity, denied-audit classification, create-error redaction, atomic mandatory audit, last-active-super-admin protection, legacy-mutator rejection, and TEMP-users resistance using temporary SQLite databases only.
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
