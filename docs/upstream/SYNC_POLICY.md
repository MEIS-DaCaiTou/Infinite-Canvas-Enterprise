# Upstream Sync Policy

This repository follows [hero8152/Infinite-Canvas](https://github.com/hero8152/Infinite-Canvas) while maintaining an enterprise multi-user layer.

## Homepage Boundary

The root `README.md` is the Enterprise project entry point.

It must always describe:

- the Enterprise project direction
- the enterprise gateway architecture
- startup and health-check paths
- Codex / Agent reading order
- enterprise vs upstream code boundaries
- upstream synchronization rules
- security and testing entry points

The upstream README must not directly overwrite the root `README.md`.

The in-app project homepage entry must also remain an Enterprise entry point:

- default target: `https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise`
- ordinary users must not see upstream one-click update prompts or upstream author/social links
- upstream project links may be retained only as administrator-facing reference material or repository documentation

After every upstream sync, verify that the Enterprise gateway injection still governs `static/index.html` project entry, version/update UI, and upstream author visibility. If upstream changes the homepage DOM IDs or update scripts, fix the Enterprise injection in the same sync PR before merge.

## Preserving Upstream README

If the upstream README is useful during an upstream sync, preserve it at:

```text
docs/upstream/README.upstream.md
```

That file must keep a notice at the top saying it is the upstream README and is not the Enterprise project entry point.

## Sync PR Requirements

Every upstream sync PR must state:

- upstream source repository and commit
- upstream `VERSION`
- enterprise branch version before sync
- files synced
- files intentionally not synced
- enterprise files checked for accidental overwrite
- automated test results
- manual verification results when applicable
- risks
- rollback plan
- whether the Enterprise homepage/update governance was rechecked

## Current Upstream Baseline

- Upstream repository: `hero8152/Infinite-Canvas`
- Current enterprise baseline: `2026.06.23`
- Last recorded upstream commit: `0da3ff9ae0477e6e18b7c241020c2ce8cb0d5c73`

The 2026.06.23 sync found that upstream did not yet include the Enterprise PR #21 Smart Canvas log compatibility work. The sync therefore retains only the documented minimal compatibility hooks in `static/js/smart-canvas.js`; future upstream syncs must rerun `enterprise/tests/test_smart_canvas_logs.js` before deciding whether the local patch can be removed.

## Intentional Difference

The upstream repository currently tracks `python/`.

This enterprise repository keeps `python/` and `python.zip` as local runtime artifacts through `.gitignore`. Do not add them in an upstream sync PR unless a separate issue explicitly changes the runtime distribution policy.
