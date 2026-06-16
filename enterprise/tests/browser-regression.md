# Browser Regression Automation Plan

This document defines the minimal browser-level automation plan for Infinite Canvas Enterprise. It complements `BROWSER_REGRESSION_CHECKLIST.md`; the checklist is the source of truth for acceptance coverage, while this document describes how to automate the safest subset over time.

## Goals

- Keep regression verification repeatable after Codex context compression.
- Avoid committing secrets, real runtime data, browser cookies, or generated artifacts.
- Start with non-destructive checks and only automate destructive lifecycle checks when disposable test users are available.
- Keep all regression scripts and notes under `enterprise/tests/`.

## Current Automated Baseline

The existing non-destructive baseline remains mandatory:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\diagnose.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\smoke.ps1
```

When service interruption is acceptable, also run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\test_start_stop.ps1 -StopExisting
```

These scripts verify process health and basic HTTP guards. They do not replace browser-level role, DOM, console, or workflow checks.

## Proposed Automation Tiers

### Tier 0: Required HTTP Baseline

- Run `diagnose.ps1`.
- Run `smoke.ps1`.
- Confirm `/enterprise/health` reports `gateway=ok` and `upstream=ok`.
- Confirm root and admin paths enforce login.

### Tier 1: Read-Only Browser Smoke

Use a fresh browser profile or incognito context.

- Open `/enterprise/login`.
- Verify login page renders.
- Log in as admin.
- Open `/enterprise/admin`.
- Open `/enterprise/logs`.
- Open root homepage.
- Verify project homepage link points to `https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise`.
- Verify admin sees enterprise-controlled update wording when an update entry is visible.
- Log out.
- Log in as a normal user.
- Verify normal user cannot open `/enterprise/admin`.
- Verify normal user does not see update buttons, upstream update prompts, or upstream author social links.
- Verify a normal user request to `/api/update-from-github` returns 403.
- Capture blocking console errors only; do not store sensitive request headers.

### Tier 2: Controlled Lifecycle Browser Smoke

Run only with disposable test users and explicit acceptance that local runtime data will change.

- Admin creates a disposable user.
- Admin edits display name.
- Admin resets password.
- Admin disables and enables the user.
- Admin changes role and restores it.
- Verify audit logs contain the expected user-management actions.
- Normal test user creates a canvas.
- Verify the canvas appears in that user's list.
- Verify another normal user does not see that canvas.
- Open and save the canvas.
- Open Smart Canvas and verify there are no blocking console errors.

### Tier 3: Upstream Sync Regression

Run after every upstream sync PR.

- Verify root `README.md` remains the enterprise entrypoint.
- Verify upstream README is kept only under `docs/upstream/README.upstream.md` when synchronized.
- Verify enterprise entry governance still applies to the updated upstream `static/index.html`.
- Verify ordinary users still cannot see or call update capabilities.
- Verify newly added upstream resource, output, update, or asset APIs are reviewed against enterprise permission boundaries.
- Record all findings in `enterprise/tests/UPDATE_TEST_LOG.md`.

## Stable Targets To Inspect

The following selectors or paths are useful for browser checks. They come from the current enterprise and upstream shell and must be rechecked after upstream syncs:

- `/enterprise/login`
- `/enterprise/admin`
- `/enterprise/logs`
- `/enterprise/profile`
- `/`
- `/static/canvas.html`
- `/static/smart-canvas.html`
- Project homepage button: `#github-entry-btn`
- Upstream author/social area: `.author-box`
- Update action area: update buttons and version prompts governed by the enterprise gateway injection

If upstream DOM changes remove or rename these selectors, update the browser regression notes and verify `enterprise/gateway.py` still applies enterprise entry governance.

## Credential Handling

Browser automation must never hard-code real credentials.

Acceptable sources:

- Local untracked `enterprise.env`.
- One-time environment variables set in the terminal.
- A manually created disposable test account.

Forbidden:

- Committing passwords.
- Committing API keys, provider tokens, cookies, or screenshots containing secrets.
- Writing test credentials into Markdown files.

## Result Artifacts

- Do not commit screenshots, videos, browser traces, HAR files, or console dumps by default.
- If artifacts are needed for debugging, save them under a temporary or ignored output path and summarize the result in `enterprise/tests/UPDATE_TEST_LOG.md`.
- Sanitize any copied Network or Console output before placing it in docs or PR descriptions.

## Suggested Future Script Shape

A future browser automation script may be added only after review. It should:

- live under `enterprise/tests/`;
- read credentials from local environment only;
- fail fast on missing credentials;
- collect console errors;
- use disposable users for destructive user-management checks;
- clean up or disable disposable accounts at the end;
- never require third-party image generation APIs to pass;
- output a concise pass/fail summary that can be pasted into `UPDATE_TEST_LOG.md`.

Suggested future command name:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\browser-regression.ps1
```

This command is intentionally not added in the current task. The current task establishes the checklist and automation plan first.
