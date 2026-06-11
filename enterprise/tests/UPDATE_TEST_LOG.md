# Upstream Update Test Log

Record diagnostics and smoke-test results after upstream updates.

## 2026-06-11 · Version 2026.06.02.1

Commands run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\diagnose.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\smoke.ps1
```

Result:

- `diagnose.ps1`: passed for local health and upstream app-info.
- `smoke.ps1`: passed.
- `127.0.0.1:8000/enterprise/health`: HTTP 200.
- `127.0.0.1:3001/api/app-info`: HTTP 200, version `2026.06.02.1`.
- Listening ports: `0.0.0.0:8000`, `127.0.0.1:3001`.
- LAN address selected: `11.0.1.98`.
- Proxy note: Windows proxy `127.0.0.1:7897` affects normal requests to `11.0.1.98`; `curl --noproxy` returns HTTP 200.
- Static HTML resource version parameters were synchronized from `2026.06.02` to `2026.06.02.1` to refresh browser cache.

Not run in this pass:

- `test_start_stop.ps1 -StopExisting`, because it intentionally stops current `8000/3001` services.

## 2026-06-03 · Version 2026.06.02.1

Commands run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\diagnose.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\smoke.ps1
```

Result:

- `diagnose.ps1`: passed for local health and upstream app-info.
- `smoke.ps1`: passed.
- `127.0.0.1:8000/enterprise/health`: HTTP 200.
- `127.0.0.1:3001/api/app-info`: HTTP 200, version `2026.06.02.1`.
- Listening ports: `0.0.0.0:8000`, `127.0.0.1:3001`.
- LAN address selected: `11.0.1.98`.
- Proxy note: Windows proxy `127.0.0.1:7897` affects normal requests to `11.0.1.98`; `curl --noproxy` returns HTTP 200.

Not run in this pass:

- `test_start_stop.ps1 -StopExisting`, because it intentionally stops current `8000/3001` services.
