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

## Current Upstream Baseline

- Upstream repository: `hero8152/Infinite-Canvas`
- Current enterprise baseline: `2026.06.12`
- Last recorded upstream commit: `9fb9a908c78f6d9e23fcfc03b7cf5d8b77ff3e0e`

## Intentional Difference

The upstream repository currently tracks `python/`.

This enterprise repository keeps `python/` and `python.zip` as local runtime artifacts through `.gitignore`. Do not add them in an upstream sync PR unless a separate issue explicitly changes the runtime distribution policy.
