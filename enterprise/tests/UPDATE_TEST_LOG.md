# Upstream Update Test Log

Record diagnostics and smoke-test results after upstream updates.

## 2026-06-23 - Task 3U controlled upstream sync

Update window:

- Branch: `chore/upstream-sync-2026-06-23`.
- Enterprise version before sync: `2026.06.12`.
- Enterprise main included PR #21 (`09f376d` / `87dae90`) before synchronization.
- Upstream source: `hero8152/Infinite-Canvas@0da3ff9ae0477e6e18b7c241020c2ce8cb0d5c73`.
- Upstream target version and synchronized version: `2026.06.23`.
- Update method: `git fetch upstream main`, then a controlled replacement of changed upstream-covered files only.

Sync scope and protection:

- Synced: `VERSION`, `main.py`, changed files under `static/`, and changed files under `tools/`, including the upstream Photoshop asset connector.
- Already equal to upstream and therefore unchanged: `workflows/`, `packages/`, `requirements.txt`, `get-pip.py`, `run.bat`, and upstream install/login/run helper scripts.
- Not synced: root `README.md` (Enterprise entry point retained), `python/`, `python.zip`, `enterprise.env`, `API/.env`, runtime provider configuration, databases, canvases, conversations, histories, media previews, and generated assets.
- Protected and retained: `enterprise/`, `enterprise-static/`, `enterprise/tests/`, Enterprise documentation, `enterprise.env.example`, and the Enterprise README boundary.

PR #21 Smart Canvas compatibility review:

- Upstream `static/js/smart-canvas.js` did not contain equivalent PR #21 hooks.
- Retained as a minimal migration: legacy log normalization on load/save, log preservation during canvas conflict merge, and log recording after recovered/manual image-task or Jimeng completion.
- `enterprise/tests/test_smart_canvas_logs.js` passed against the synchronized upstream file. The local compatibility patch cannot yet be removed.

Automated checks:

- `python -m py_compile main.py enterprise\\gateway.py enterprise\\interceptors.py enterprise\\db.py enterprise\\admin_api.py enterprise\\config.py`: passed.
- `python .\\enterprise\\tests\\test_ownership_isolation.py`: passed.
- `node --check .\\static\\js\\smart-canvas.js`: passed.
- `node .\\enterprise\\tests\\test_smart_canvas_logs.js`: passed.
- `enterprise\\tests\\diagnose.ps1`: passed; gateway `0.0.0.0:8000`, internal upstream `127.0.0.1:3001`, health and app-info both returned `2026.06.23`.
- `enterprise\\tests\\smoke.ps1`: passed.
- Existing Playwright ownership regression: passed with administrator plus disposable normal users A/B; it verified canvas, conversation, `/assets/output`, `/api/download-output`, `/api/view`, Enterprise project entry, and normal-user update API `403` behavior. It created only ignored runtime test users, canvas data, and a test image.

Browser checks:

- Administrator login and `/enterprise/admin` opened normally.
- Administrator project-homepage button opened `https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise`; administrator update wording was `企业版更新到 v2026.06.23`.
- Normal-user browser regression confirmed no upstream update UI, Enterprise project entry, and `POST /api/update-from-github` returned `403`.
- Legacy Smart Canvas `Task3E2 Output Persistence` displayed its existing successful generation log and still displayed it after reload.
- Existing new Smart Canvas log displayed after reload.
- No provider generation was submitted during this synchronization. The recovered-task logging path is covered by the no-provider regression test; a real old-canvas generation/relogin check remains a Draft PR manual acceptance item.

Risks and follow-up:

- The browser recorded one non-blocking `MutationObserver.observe` initialization error from upstream vendor/startup code while Smart Canvas remained usable. It is recorded for upstream follow-up, not changed in this sync.
- Upstream now includes `/api/projects`, `/api/image-jpeg`, and `/api/canvas-comfy-tasks`. Their isolation effect, plus online/history/material/WebSocket surfaces, is Task 3G design input only and is not implemented here.

Recommendation:

- Recommend merge after review, with the documented real-provider legacy-canvas log acceptance check performed before or immediately after deployment.

## 2026-06-13 - Version 2026.06.12 corrected full upstream sync

Issue: GitHub Issue #9, Task 3A continuation for PR #10 review feedback.

Update window:

- Update date: 2026-06-13.
- Update branch: `chore/upstream-update-compatibility`.
- Original update baseline: `2026.06.02.1`.
- PR branch version before this correction: `2026.06.11`.
- Current upstream version: `2026.06.12`.
- Actual version after correction: `2026.06.12`.
- Current upstream commit: `hero8152/Infinite-Canvas@9fb9a90` (`9fb9a908c78f6d9e23fcfc03b7cf5d8b77ff3e0e`, `Update README.md`).

Problem found:

- The first PR #10 pass synchronized `main.py`, `VERSION`, and `static/` to `2026.06.11`.
- A later upstream check showed `hero8152/Infinite-Canvas` had moved to `2026.06.12` and included additional source/runtime helper files that were not yet present in the enterprise branch.

Pre-correction records:

- Enterprise PR branch `HEAD`: `4ee8a793bd9f67cf11face7e3a99393770aa049f`.
- PR branch `VERSION` before correction: `2026.06.11`.
- Upstream `main` after `git fetch upstream main`: `9fb9a908c78f6d9e23fcfc03b7cf5d8b77ff3e0e`.
- Upstream `VERSION`: `2026.06.12`.
- `/enterprise/health` before correction: HTTP 200, `gateway=ok`, `upstream=ok`.

File-tree comparison and sync strategy:

| Path | Strategy | Notes |
| --- | --- | --- |
| `VERSION` | Synced | Updated to upstream `2026.06.12`. |
| `main.py` | Synced | Replaced from upstream `main`. |
| `static/` | Synced | Replaced tracked static app files from upstream `main`. |
| `workflows/` | Synced | Replaced upstream workflow changes, including `workflows/Z-Image.json` and `workflows/Z-Image-Enhance.json`. |
| `tools/` | Synced | Added upstream Chrome local asset importer and Jimeng CLI helper scripts. |
| `packages/` | Synced | Added upstream wheel packages used by the upstream local dependency flow. |
| `requirements.txt` | Synced | Added upstream Python dependency manifest. |
| `get-pip.py` | Synced | Added upstream bootstrap helper. |
| `run.bat` | Synced | Added upstream Windows runtime entry. |
| `安装依赖.bat` | Synced | Added upstream Windows dependency installer. |
| `安装即梦CLI.bat` | Synced | Added upstream Jimeng CLI installer. |
| `安装即梦CLI.command` | Synced | Added upstream macOS Jimeng CLI installer. |
| `登录即梦CLI.bat` | Synced | Added upstream Jimeng CLI login helper. |
| `登录即梦CLI.command` | Synced | Added upstream macOS Jimeng CLI login helper. |
| `新手运行与使用教程.md` | Synced | Added upstream beginner guide. |
| `运行说明.txt` | Synced | Updated to upstream current instructions. |
| `README.md` | Synced | Added upstream README because upstream now tracks it. |
| `MAC-使用说明.md` | Synced | Updated to upstream current macOS instructions. |
| `mac-启动服务.command` | Synced | Updated to upstream current script. |
| `mac-修复权限.command` | Synced | Updated to upstream current script. |
| `mac-启动服务.sh` | Synced | Added upstream shell script. |
| `mac-安装依赖.sh` | Synced | Added upstream shell script. |
| `赞赏.png` | Synced | Added upstream image asset. |
| `python/` | Not synced | Upstream tracks a bundled runtime, but this enterprise repo intentionally keeps `python/` and `python.zip` ignored as local runtime artifacts in `.gitignore`. The existing local `python/` is still used to run validation and must not be committed in this PR. |
| `API/` | Not applicable | Current upstream `main` does not contain `API/`; there is no upstream file-tree target to sync. |
| `启动企业版.bat`, `停止企业版.bat` | Enterprise equivalent retained | These are enterprise-specific wrappers for `enterprise/launcher.py` and stop handling, not upstream files. |

Enterprise area overwrite check:

- No enterprise backend code was overwritten by the upstream sync.
- No enterprise frontend code was overwritten by the upstream sync.
- `enterprise/`, `enterprise-static/`, `enterprise.env.example`, and `enterprise/tests/` remained enterprise-owned.
- This log, `AGENT_CONTEXT.md`, and `DEVELOPMENT_PLAN.md` were updated only to record the corrected compatibility pass.

Post-correction automated checks:

```powershell
git diff --name-only
git diff --check
python -m py_compile main.py enterprise\gateway.py enterprise\admin_api.py enterprise\db.py
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\diagnose.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\smoke.ps1
```

Results:

- `git diff --name-only`: executed; tracked upstream changes include `VERSION`, `main.py`, `static/`, `workflows/Z-Image.json`, `workflows/Z-Image-Enhance.json`, `MAC-使用说明.md`, `mac-启动服务.command`, `mac-修复权限.command`, and `运行说明.txt`. New upstream additions are visible in `git status` and are staged explicitly for commit.
- `git diff --check`: passed. Git reported line-ending warnings for upstream static files only.
- `python -m py_compile main.py enterprise\gateway.py enterprise\admin_api.py enterprise\db.py`: passed.
- Startup with system Python failed because the global environment lacked `jwt`; startup with the repo local runtime `.\python\python.exe enterprise\launcher.py --no-browser` succeeded. This confirms the local bundled runtime remains required for this workspace.
- `enterprise/launcher.py`: started `127.0.0.1:3001` and `0.0.0.0:8000`.
- `/enterprise/health`: HTTP 200, `gateway=ok`, `upstream=ok`.
- `127.0.0.1:3001/api/app-info`: HTTP 200, version `2026.06.12`.
- `diagnose.ps1`: passed for local health and upstream app-info. LAN health through normal proxy-aware request timed out on `11.0.1.98`, while `curl --noproxy` returned HTTP 200; this matches the known Windows proxy/LAN behavior.
- `smoke.ps1`: passed for health, login page, admin auth guard, and root auth/redirect checks.

Post-correction manual verification:

- Unauthenticated root path redirects to enterprise login with HTTP 307.
- Admin login succeeded.
- `/enterprise/admin` opened for admin.
- User management verified through the live gateway API:
  - display name update succeeded and was restored;
  - non-current user disable succeeded and `is_active` became false;
  - re-enable succeeded and `is_active` became true;
  - password reset succeeded;
  - `user_disabled`, `user_enabled`, `user_profile_updated`, and `user_password_reset` audit entries appeared.
- `/enterprise/logs` opened.
- Normal user login succeeded after password reset.
- Normal user update/rollback APIs were blocked with admin-required status.
- Normal user canvas list was scoped to owned canvases.
- Normal user created a Smart Canvas; ownership was recorded in `user_canvas_map`.
- Smart Canvas opened in a real Playwright browser session at `/static/smart-canvas.html?id=54b5f5c43c374c8cb42cad02a4dc4b06`; title loaded, canvas UI was present, browser console reported 0 errors, and no obvious permanent running state was observed. The only matched `running` text was the normal `运行` button label.

Issues found:

- The previous sync target was stale because upstream moved from `2026.06.11` to `2026.06.12` before review completed.
- The original sync scope was too narrow and omitted upstream helper/runtime source paths such as `tools/`, `packages/`, root scripts, and upstream docs.
- The enterprise repo intentionally does not commit `python/` even though upstream tracks it, because this project treats it as a local runtime artifact.
- Windows proxy settings can still affect normal browser/request access to selected LAN IPs; `curl --noproxy` verified the service itself is reachable.
- Manual validation created runtime data (test canvas files, audit logs, media preview cache). These files are not part of the PR and must remain uncommitted.

Recommendation:

- Recommend merge after review if reviewers accept the documented `python/` runtime policy and the expanded upstream file sync scope.

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
