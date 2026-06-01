# Enterprise Test Scripts

This folder is the only place for project diagnostic and smoke-test scripts.

## Scripts

- `diagnose.ps1` checks local version, selected LAN IP, listening ports, proxy settings, and health endpoints.
- `smoke.ps1` runs non-destructive HTTP smoke checks against a running enterprise gateway.
- `test_start_stop.ps1` verifies the launcher lifecycle: stop old listeners, start the enterprise launcher, wait for health, terminate the launcher, and confirm `3001/8000` are released.
- `SMOKE_CHECKLIST.md` is the manual checklist to run after every upstream update.

Run scripts from the project root unless a script says otherwise.
