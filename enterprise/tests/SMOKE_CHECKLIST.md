# Upstream Update Smoke Checklist

Run this checklist after every upstream update.

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

## Manual Checks

- Open the LAN URL printed by the launcher.
- Confirm unauthenticated users land on `/enterprise/login`.
- Log in as an administrator and open `/enterprise/admin`.
- Log in as a normal user and confirm only owned canvases are visible.
- Create a new canvas as a normal user and confirm it is assigned to that user.
- Confirm ordinary users cannot see or use update/rollback controls.
- Confirm administrator update checks still work.
- Confirm `/enterprise/health` returns `gateway=ok` and `upstream=ok`.

## Files That Should Survive Upstream Updates

- `enterprise/`
- `enterprise-static/`
- `enterprise.env`
- `启动企业版.bat`
- `停止企业版.bat`
- `HANDOVER.md`
- `ENTERPRISE_DOCS.md`
