# Upstream Sync Policy

This repository follows [hero8152/Infinite-Canvas](https://github.com/hero8152/Infinite-Canvas) while maintaining an enterprise multi-user layer.

## ENV-1 Change Freeze

Normal upstream feature synchronization is frozen while ENV-1 establishes immutable releases, path roots, runtime provenance, and fail-closed entrypoints. A critical upstream security fix may be evaluated separately and introduced through a narrowly scoped, reviewed sync. The exception does not permit unrelated feature drift or bypass ENV validation gates.

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
- Current enterprise upstream baseline: `2026.07.6`
- Last verified enterprise code baseline: `396cccc68d63bd16393a2cb72d24e4a48fcf47cb`; resolve the current repository HEAD from GitHub `main`.
- Last controlled upstream target commit: `f1dd6834a72f3e7ff8340be05a84347d931e9cb9`

U-1 documented that the enterprise repository had no usable merge-base for a normal upstream merge. U-2 therefore used a controlled, patch-style sync to the fixed upstream target `f1dd6834a72f3e7ff8340be05a84347d931e9cb9`, not a direct merge, rebase, or broad cherry-pick.

U-2 explicitly skipped `API/.env`, `python/`, `CLI/` output, `assets/`, `output/`, `data/asset_library.json`, runtime databases, env files, tokens, cookies, keys, and local logs. U-2-F2 then fixed the history type inconsistency exposed after sync: zimage cloud history is saved as `zimage`, Enhance ModelScope history is saved as `enhance`, and Klein remains `klein`.

## Intentional Difference

The upstream repository currently tracks `python/`.

This enterprise repository keeps `python/` and `python.zip` as local runtime artifacts through `.gitignore`. Do not add them in an upstream sync PR unless a separate issue explicitly changes the runtime distribution policy.
