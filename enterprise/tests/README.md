# Enterprise Test Scripts

This folder is the only place for project diagnostic and smoke-test scripts.

Before adding or changing scripts, read:

- `../../AGENT_CONTEXT.md`
- `../../ENTERPRISE_DOCS.md`
- `SMOKE_CHECKLIST.md`

## Scripts

- `diagnose.ps1` checks local version, selected LAN IP, listening ports, proxy settings, and health endpoints.
- `smoke.ps1` runs non-destructive HTTP smoke checks against a running enterprise gateway.
- `test_start_stop.ps1` verifies the launcher lifecycle: stop old listeners, start the enterprise launcher, wait for health, terminate the launcher, and confirm `3001/8000` are released.
- `test_ownership_isolation.py` runs non-destructive ownership isolation checks with a temporary SQLite database and temporary canvas/conversation files.
- `test_smart_canvas_logs.js` verifies Smart Canvas legacy log normalization, merge behavior, and async task completion logging hooks without calling a model provider.
- `SMOKE_CHECKLIST.md` is the manual checklist to run after every upstream update.
- `BROWSER_REGRESSION_CHECKLIST.md` is the browser-level enterprise regression checklist for login, roles, admin console, entry governance, canvas, conversations, assets, and upstream-sync review.
- `browser-regression.md` describes the minimal automation plan for future browser-level regression scripts.
- `UPDATE_TEST_LOG.md` records the actual result after each upstream update test pass.
- `../../ENTERPRISE_ISOLATION_MATRIX.md` is the data-domain and API permission source of truth for Task 3G follow-up isolation tests.
- `../../ENTERPRISE_PERMISSION_DESIGN.md` defines page permissions, administrator switches, phased delivery, and the A/B/admin acceptance contract.

Run scripts from the project root unless a script says otherwise.

Do not place ad-hoc diagnostic or smoke-test scripts in the project root, `static/`, or other upstream-owned folders. Keep them here so upstream updates and Git reviews stay clean.

For every Task 3G implementation PR, add or extend a focused test here before changing access behavior. Use temporary SQLite databases and temporary data files only. The minimum regression roles are normal user A, normal user B, and administrator; cover list filtering, direct-ID denial, resource URLs, refresh/re-login persistence, and WebSocket delivery where applicable.
