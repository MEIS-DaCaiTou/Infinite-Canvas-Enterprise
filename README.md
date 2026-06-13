# Infinite Canvas Enterprise

Infinite Canvas Enterprise is the enterprise multi-user edition built on top of the upstream open-source project [hero8152/Infinite-Canvas](https://github.com/hero8152/Infinite-Canvas).

This repository is not a new standalone canvas product. Its only long-term direction is to make Infinite Canvas safe and maintainable for teams, LAN deployments, and server environments with enterprise authentication, authorization, ownership, and audit controls.

## Core Capabilities

- Enterprise login authentication with JWT Cookie sessions.
- User management for administrators.
- Permission isolation for normal users.
- Canvas ownership through enterprise mapping.
- Conversation ownership through enterprise mapping.
- Audit logs for key enterprise operations.
- Enterprise gateway in front of the upstream app.
- LAN and server deployment flow.
- Controlled upstream synchronization and compatibility validation.

## Runtime Architecture

```text
LAN / server users
        |
        | HTTP + enterprise_token Cookie
        v
Enterprise Gateway
enterprise/gateway.py
0.0.0.0:8000
        |
        | reverse proxy + auth + user context + filtering
        v
Upstream Infinite Canvas
main.py
127.0.0.1:3001
```

The enterprise gateway is the external entry point. The upstream app should stay bound to `127.0.0.1:3001` and should not be exposed directly to LAN users.

## Quick Start

Windows startup:

```powershell
.\启动企业版.bat
```

Stop services:

```powershell
.\停止企业版.bat
```

Common paths:

- App entry: `http://127.0.0.1:8000/`
- Admin console: `/enterprise/admin`
- Health check: `/enterprise/health`
- Login page: `/enterprise/login`

The enterprise launcher starts both services:

- Enterprise gateway: `0.0.0.0:8000`
- Internal upstream: `127.0.0.1:3001`

## Required Reading For Codex / Agents

Before any development or maintenance task, read these documents first:

1. `PROJECT_CHARTER.md`
2. `AGENT_CONTEXT.md`
3. `ARCHITECTURE.md`
4. `CODE_BOUNDARIES.md`
5. `CODEX_WORKFLOW.md`
6. `DEVELOPMENT_PLAN.md`
7. `ENTERPRISE_DOCS.md`
8. The current GitHub Issue text

This is mandatory because the enterprise layer and upstream layer have different ownership and update rules.

## Development Boundaries

Enterprise features should be implemented first in:

- `enterprise/`
- `enterprise-static/`
- `enterprise/tests/`
- enterprise documentation

The following are upstream-covered areas and should not be used as normal enterprise feature entry points:

- `main.py`
- `static/`
- `workflows/`
- `VERSION`
- `tools/`
- `packages/`
- root upstream helper scripts and upstream reference docs

Changes to upstream-covered files are allowed only for controlled upstream syncs or clearly documented minimal upstream bug fixes.

## Upstream Synchronization

Current upstream baseline: `2026.06.12`

Upstream source: [hero8152/Infinite-Canvas](https://github.com/hero8152/Infinite-Canvas)

Rules:

- Upstream sync must be delivered through an independent branch and PR.
- Upstream sync must run compatibility checks before merge.
- Upstream sync PRs must clearly list synced files, intentionally skipped files, test results, risks, and rollback plan.
- The root `README.md` must remain the Enterprise project entry point.
- The upstream README must not directly overwrite this file again.
- If the upstream README needs to be preserved, sync it to `docs/upstream/README.upstream.md`.

More detail: `docs/upstream/SYNC_POLICY.md`.

## Enterprise Entry And Updates

The in-app project homepage entry must point to the Enterprise repository:

- [MEIS-DaCaiTou/Infinite-Canvas-Enterprise](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise)

The upstream project remains credited and referenced in repository documentation, but it should not be the default in-app project homepage for enterprise users.

Update governance:

- Normal users must not see or trigger one-click update, update-to-version prompts, rollback, or update connectivity checks.
- Update-related upstream APIs are protected by the enterprise gateway and require administrator permission.
- Administrators may use the update entry only as an Enterprise controlled maintenance capability.
- The gateway keeps upstream auto-restart disabled for update requests so the Enterprise `3001/8000` process model remains controlled by the Enterprise launcher.

## Upstream README

The upstream README is kept only as reference material:

- `docs/upstream/README.upstream.md`

That document is not the homepage for this enterprise repository.

## Security Notes

Before production deployment:

- Create local `enterprise.env` from `enterprise.env.example`.
- Change `JWT_SECRET`.
- Change `ADMIN_PASSWORD`.
- Review repository visibility and collaborator permissions.

Never commit:

- real API keys
- real tokens
- real cookies
- `enterprise.env`
- real databases
- runtime data under `data/`
- local media preview caches

See `SECURITY_BASELINE.md` for the full baseline.

## Testing

Non-destructive diagnostics:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\diagnose.ps1
```

Smoke test:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\smoke.ps1
```

Manual checklist after upstream updates:

- `enterprise/tests/SMOKE_CHECKLIST.md`

Startup/stop lifecycle tests may interrupt the running service. Run them only when that interruption is acceptable.

## Current Maintenance Status

- Enterprise gateway: `0.0.0.0:8000`
- Internal upstream: `127.0.0.1:3001`
- Current upstream baseline: `2026.06.12`
- Enterprise tests live in `enterprise/tests/`
- Runtime data and secrets must stay out of Git
