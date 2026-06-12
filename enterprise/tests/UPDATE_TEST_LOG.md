# Upstream Update Test Log

Record diagnostics and smoke-test results after upstream updates.

## 2026-06-12 - Version 2026.06.11 compatibility drill

Issue: GitHub Issue #9, Task 3A.

Update window:

- Update date: 2026-06-12.
- Enterprise main baseline before branch: `920a6cd Merge pull request #6 from MEIS-DaCaiTou/feat/user-management-audit`.
- Update branch: `chore/upstream-update-compatibility`.
- Version before update: `2026.06.02.1`.
- Target version shown by the page: `v2026.06.11`.
- Actual version after update: `2026.06.11`.
- Upstream source commit: `hero8152/Infinite-Canvas@bc21b15` (`bc21b153dca05d922eb20cb225a705f502123a87`).

Pre-update checks:

- `git status`: clean on `chore/upstream-update-compatibility`.
- `/enterprise/health`: HTTP 200, `gateway=ok`, `upstream=ok`.
- `127.0.0.1:3001/api/app-info`: HTTP 200, version `2026.06.02.1`.
- Page update prompt: homepage update button displayed `v06.11`; hidden full version text confirmed `v2026.06.11`.
- `diagnose.ps1`: passed.
- `smoke.ps1`: passed.

Update method:

- Attempted the existing upstream update API first: `POST /api/update-from-github` with `auto_restart=false`.
- The existing update API could not complete because anonymous GitHub REST tree access returned HTTP 403 rate limit exceeded.
- Used a controlled manual sync from the configured upstream repository instead:
  - `git fetch upstream main`
  - replaced upstream-covered files from `upstream/main`: `main.py`, `VERSION`, `static/`
- This drill intentionally updated only upstream-covered files and did not change the updater implementation.

Files affected by upstream sync:

- `VERSION`
- `main.py`
- `static/` tracked updates, including HTML pages, canvas/smart-canvas JS and CSS, i18n JS, theme JS, and RunningHub provider metadata.
- New upstream static files staged for review: `static/js/history-bulk-manager.js`, `static/runninghub/thumbnails/workflow-2064542485938008065.jpg`, `static/update-notes.json`.

Enterprise area overwrite check:

- No unintended upstream overwrite was observed in `enterprise/`, `enterprise-static/`, `enterprise.env.example`, `enterprise/tests/`, or enterprise documentation.
- Runtime validation created local audit logs, login records, and test canvases; these are runtime data and must not be committed.

Post-update automated checks:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\test_start_stop.ps1 -StopExisting
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\diagnose.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\smoke.ps1
```

Results:

- `test_start_stop.ps1 -StopExisting`: passed; launcher started, health became ok, ports `8000/3001` listened, launcher stopped, ports released.
- `diagnose.ps1`: passed after update; project version `2026.06.11`; local and LAN health checks HTTP 200; upstream app-info HTTP 200.
- `smoke.ps1`: passed after update; health, login page, admin auth guard, and root auth/redirect checks passed.
- Manual restart after lifecycle test: `enterprise/launcher.py` started `127.0.0.1:3001` and `0.0.0.0:8000`.
- `/enterprise/health`: HTTP 200, `gateway=ok`, `upstream=ok`.
- `127.0.0.1:3001/api/app-info`: HTTP 200, version `2026.06.11`.

Post-update manual verification:

- Unauthenticated root path redirects to `/enterprise/login?next=/` with HTTP 307.
- Admin login succeeded.
- `/enterprise/admin` opened for admin.
- User management verified through live gateway API:
  - display name update succeeded and was restored;
  - non-current user disable succeeded and `is_active` became false;
  - re-enable succeeded and `is_active` became true;
  - password reset succeeded;
  - `user_disabled`, `user_enabled`, `user_profile_updated`, and `user_password_reset` audit entries appeared.
- `/enterprise/logs` opened in a real Playwright browser session.
- Logs pagination verified:
  - default page size: 20;
  - page sizes 10, 20, 50, 100 worked;
  - previous and next page worked at page size 20;
  - user filter, action filter, and combined filter worked.
- Normal user login succeeded after password reset.
- Normal user update/rollback APIs were blocked with admin-required status.
- Normal user canvas list was scoped to owned canvases.
- Normal user created a Smart Canvas; ownership was recorded in `user_canvas_map`.
- Existing/new Smart Canvas opened at `/static/smart-canvas.html?id=...`; page title loaded, browser console reported 0 errors, and no obvious permanent running state was observed.

Issues found:

- The built-in update API was blocked by GitHub anonymous REST rate limiting during this drill. Follow-up recommendation: add an authenticated GitHub token option or a documented git-fetch fallback for upstream update operations.
- Local development security warnings still appear when default `JWT_SECRET` or `ADMIN_PASSWORD` are used. This is expected from the security baseline and does not block local compatibility testing.
- Manual validation created runtime data (test canvas files, audit logs, media preview cache). These files are not part of the PR and must remain uncommitted.

Recommendation:

- Recommend merge for this compatibility update if reviewers accept the documented GitHub rate-limit caveat and the upstream-covered file changes.

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
