# Release And Source Change Smoke Checklist

Run this checklist after changes to the canvas core, Gateway, static UI, Release payload, Runtime, or update path.

## Automated Checks

From the project root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\diagnose.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\smoke.ps1
```

For launcher lifecycle verification:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\test_start_stop.ps1 -StopExisting
```

Record the repository commit, `VERSION`, Release identity and command results in the PR or implementation record before continuing feature work.

## Manual Checks

- Open the LAN URL printed by the launcher.
- Confirm unauthenticated users land on `/enterprise/login`.
- Log in as an administrator and open `/enterprise/admin`.
- Log in as a normal user and confirm only owned canvases are visible.
- Create a new canvas as a normal user and confirm it is assigned to that user.
- Confirm ordinary users cannot see or use update/rollback controls.
- Confirm administrator update checks still work.
- Confirm `/enterprise/health` returns `gateway=ok` and `upstream=ok`.
- Open an existing Smart Canvas and confirm no stale LLM nodes remain visually stuck in `running` state after a hard refresh.
- Run one small LLM prompt node with a known working model and confirm it finishes or reports an error without staying in a permanent spinner state.

## Files And Data That Must Survive Product Updates

- `enterprise/`
- `enterprise-static/`
- `enterprise.env`
- `启动企业版.bat`
- `停止企业版.bat`
- `ENTERPRISE_DOCS.md`
- `docs/CURRENT_PROJECT_STATUS.md`
- `docs/roadmap/DEVELOPMENT-ROADMAP-2026-2027.md`
- customer `DATA_ROOT`, `CONFIG_ROOT`, task metadata and owned assets
