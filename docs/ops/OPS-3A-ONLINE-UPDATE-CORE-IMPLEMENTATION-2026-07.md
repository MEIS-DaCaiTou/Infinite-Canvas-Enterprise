# OPS-3A: Online Update Core Implementation (2026-07)

## Scope

Draft PR #77 implements trusted release preparation only. It was validated only
with temporary directories, temporary SQLite data, and loopback HTTP fixtures.
It does not mean any production release has been checked, fetched, staged, or
applied.

Implemented flow:

```text
check-update -> fetch-release -> stage-release -> prepare-online-update
```

All downloads, reports, logs, and staging output are written only to an
explicit existing OPS workspace outside the application root. The application
root is read only for `VERSION` and a small plan fingerprint.

Not implemented: `apply-upgrade`, replacement of production files, version
switching, rollback, restore, service lifecycle control, database migration
apply, Update Center UI, HTTP OPS API, remote execution, or arbitrary shell.

## Modules

| Path | Responsibility |
| --- | --- |
| `versions.py` | Strict `YYYY.MM.N` parsing and comparison. |
| `manifest.py` | Exact `ops-release-manifest-v1` validation and duplicate-key rejection. |
| `providers.py` and `http_client.py` | Fixed GitHub Releases source plus loopback-only local fixture, with host, TLS, redirect, size, and timeout controls. |
| `download.py` | Streaming size/SHA-256 validation and non-overwriting atomic publication. |
| `staging.py` | ZIP preflight, bounded new-directory extraction, and independent archive-to-staging revalidation. |
| `jobs.py` | Monotonic job state, workspace JSON reports, and redacted JSONL logs. |
| `service.py` | Framework-independent preparation service for future allowlisted callers. |
| `runner.py` | Thin local CLI adapter. |

## Manifest v1

The manifest is UTF-8 JSON with no duplicate keys and exactly these fields:

```json
{
  "schema_version": "ops-release-manifest-v1",
  "release_version": "2026.07.7",
  "source_commit": "<40 lowercase hex characters>",
  "source_tree": "<40 lowercase hex characters>",
  "generated_at": "2026-07-14T00:00:00Z",
  "archive": {
    "filename": "Infinite-Canvas-Enterprise-release-<source_commit>.zip",
    "size_bytes": 1,
    "sha256": "<64 lowercase hex characters>"
  },
  "package": {
    "file_count": 1,
    "root_prefix": "Infinite-Canvas-Enterprise-<source_commit>"
  },
  "compatibility": {
    "minimum_current_version": "",
    "maximum_current_version": "",
    "requires_database_migration": false,
    "migration_ids": []
  },
  "release_notes": ""
}
```

Provider tag/version, manifest version, archive name, archive size, and archive
SHA-256 must bind. An explicit `release_id` is still accepted only if its target
version is strictly newer than the current version. Draft, malformed historical,
and incomplete GitHub release records are skipped as bounded redacted provider
diagnostics, so they cannot suppress a later complete candidate. Prereleases
remain excluded by default and require an explicit local CLI flag.

## Commands

Run the directly executed local runner with a pre-created workspace outside the
application root. The GitHub repository is fixed in code. The local fixture
provider is only for testing and rehearsal; its HTTP URLs are loopback-only.

```powershell
python .\enterprise\ops\runner.py check-update --app-root <app-root> --workspace <ops-workspace>
python .\enterprise\ops\runner.py fetch-release --app-root <app-root> --workspace <ops-workspace>
python .\enterprise\ops\runner.py stage-release --app-root <app-root> --workspace <ops-workspace> --manifest <workspace-manifest> --archive <workspace-archive>
python .\enterprise\ops\runner.py prepare-online-update --app-root <app-root> --workspace <ops-workspace> --stage-report <stage-report> --backup-manifest <backup-manifest> --data-check-report <data-check-report>
```

`fetch-release` creates `downloads/<job-id>/`; `stage-release` creates a fresh
`staging/<job-id>/`; reports go to `reports/<job-id>.json`; JSONL events go to
`<ops-workspace>/jobs.jsonl`. Existing destinations are never overwritten.

## State, Plans, and Security Failure

States are `created`, `checking`, `metadata_ready`, `downloading`, `verifying`,
`staging`, `staged`, `planned`, and `failed`. A completed or failed job cannot
advance. Reports record only non-secret versions, hashes, staging facts,
migration summaries, blockers, warnings, and explicit `not_executed` facts.

`prepare-online-update` requires a successful stage report *inside the explicit
workspace*, an executed SQLite backup manifest, and a usable data-check report.
It records the report paths and SHA-256 values in the plan, then reconstructs
the evidence before planning: the stage report, manifest, archive, staging
directory, file count, staged file bytes, and shared validation result must
still agree. A report is never an authority to skip artifact validation.

The backup manifest must be `kind=backup-manifest`, bind to the selected app
root, name `data/enterprise.db`, prove a fresh executed SQLite backup, and bind
both current source and actual backup database size/SHA-256 plus source journal
mode. The data-check report must be `kind=data-check-report`, bind to the same
app root, have `pass` or `warn` status, and is SHA-256 bound. Missing, stale,
forged, mismatched, or mutated evidence produces a blocked plan.

- Approved HTTPS hosts and every redirect are validated; local HTTP is limited
  to fixture loopback hosts. On an origin-changing redirect, `Authorization`,
  `Cookie`, and other credential-like request headers are stripped before the
  redirected request is sent.
- Metadata/archive sizes and timeouts are bounded. Archives stream to a
  job-owned temporary file, then size and SHA-256 must pass before publication.
- ZIP policy rejects traversal, absolute/drive/UNC/mixed-separator paths,
  alternate data streams, control characters, trailing dots/spaces, Windows
  device names, symlink/reparse entries, NFC/case-folded normalized duplicates,
  wrong roots, ZIP bombs, and count/expanded-size limits.
- Extraction targets only a new staging directory and invokes the shared
  release validator. Runtime data, env files, logs, and credential-like files
  remain hard policy failures.
- Persisted job fields use validated scalar evidence; remote bodies,
  credentials, and arbitrary prior-report warning text are not written.

## Validation

`enterprise/tests/test_ops_3a_online_update.py` covers the provider, manifest,
bounded loopback HTTP and cross-origin credential stripping, atomic download,
Windows ZIP defences, staging revalidation, evidence-bound plans, version
downgrade blocking, backup/data-check proof validation, jobs, and direct-runner
compatibility entirely in temporary directories. Existing
`test_ops_runner.py` and `test_ops_windows_wrappers.py` remain regression
coverage. No test opens this checkout's `data/enterprise.db` or writes a
repository runtime path.
