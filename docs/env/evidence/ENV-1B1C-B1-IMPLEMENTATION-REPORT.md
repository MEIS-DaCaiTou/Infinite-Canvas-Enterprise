# ENV-1B1C-B1 Implementation Report

## A. 起始状态

- Worktree：独立 ENV-1B1C task worktree（本机绝对路径不写入仓库）。
- Branch：`env/env-1b1c-runtime-entrypoint-self-check`。
- Base：`main@4d9cc4ef3d6a0f6ed956c2dda6303e9cc3b99b89`；PR #83 已合并。
- 长期 main：`main@4d9cc4ef3d6a0f6ed956c2dda6303e9cc3b99b89`。
- 本次使用既有本机开发解释器运行隔离 pytest；没有安装、下载或修改 Python Runtime。

## B. Changed Files

新增七个 `enterprise/runtime` 纯模块和七个对应隔离测试；更新 audit、状态/路线/边界文档，新增
ENV-1B1C 实施记录。本轮不修改 `main.py`、现有 Runtime lifecycle、Batch / PowerShell、`static/`、
`python/`、`requirements.txt` 或 `VERSION`。

## C. Stage A 冻结修正

```text
formal_launcher_direct_script_frozen=true
portable_operator_root_overrides_forbidden=true
startup_core_files=python.exe,pythonw.exe,python310.dll,python310.zip,python310._pth
candidate_id_required=false
portable_current_architecture=x64
status_mismatch_exit=0
health_mismatch_exit=2
restart_mismatch_blocked=true
owned_mismatch_stop_allowed=true
stopped_context_retained_as_diagnostic=true
real_bundled_python_fixture_available=false
```

## D–J. B1 纯契约与安全原语

`error_contract` 提供集中注册、immutable public payload、canonical JSON 和脱敏详情；未知 code
拒绝，portable exit code 仅为 0 或 2。`mode` 提供严格显式 mode。`runtime_manifest` 是 bounded
startup view：最大 1 MiB manifest、单文件 64 MiB、总 hash 128 MiB、严格 JSON / relative path /
reparse / ABI / architecture 检查，且明确 `runtime_provenance_promoted=false` 与
`Manifest_v2_implemented=false`。

`python_identity` 从显式 probe 规范化 CPython 3.10 / cp310 / x64，拒绝 PATH identity、pythonw、
ABI / 架构或 bytecode policy 不匹配，并只公开脱敏字段。`preflight` 是不可变且无副作用的
canonical result；它不创建 instance、lock、context 或进程。`launch_context` 使用 16 KiB strict
schema、canonical bytes、expected-existing identity、exclusive temp ownership、atomic replace 与目录
sync 分类。`writable_probe` 使用随机短名、exclusive create、fsync、identity cleanup 与 foreign
replacement 防护。它们都保留 TOCTOU 不能被纯路径协议完全消除的限制。

Release mismatch 只实现纯状态表：旧 Release formal command 拒绝；current stop 可处理 owned old
instance；status mismatch 为 exit 0；health / restart mismatch 为 exit 2 或 blocked。没有 controller
call site。

## K. Audit

W26 包含 `launch_context.publish_launch_context` 的 runtime control / diagnostic state primitive；
W42 是 `writable_probe.probe_writable_root`。R3 staged audit：`scanned=91`、`excluded=249`、`detected=299`、
`mapped=299`、`parse_failures=0`、`uncovered=0`、`stale=0`。Digest：
`464b2eef086b6fea37daf810d3b9f0551de652763f23028df799f8affb81e1ab`。

## K.1 R3 independent-review correction

R3 closes the nine B1 pure-contract blockers without adding a lifecycle caller.
Launch-context construction/read/publish now share a strict portable validator and canonical raw-byte gate; publish
rechecks target identity immediately before replacement but explicitly does **not** claim standalone compare-and-swap.
The future B2 caller still requires an external exclusive runtime lock and must account for residual TOCTOU.

`enterprise.path_safety` is the one fail-closed lexical reparse/containment implementation reused by manifest,
Python identity, launch context, writable probe and ENV-1B2P provenance.  Typed preflight cross-binds a manifest view,
Python identity and ordered successful probes.  Error details are immutable, Python prefixes bind to the expected
Runtime root without publishing paths, any live stop requires ownership, and manifest metadata / hard limits fail
closed.  R3 adds 19 named regression functions (46 collected parameterized cases).  The dedicated correction evidence
is [ENV-1B1C-B1-R3-CORRECTION-REPORT.md](ENV-1B1C-B1-R3-CORRECTION-REPORT.md).

```text
B1_BLOCKER_01_closed=true
B1_BLOCKER_02_closed=true
B1_BLOCKER_03_closed=true
B1_BLOCKER_04_closed=true
B1_BLOCKER_05_closed=true
B1_BLOCKER_06_closed=true
B1_BLOCKER_07_closed=true
B1_BLOCKER_08_closed=true
B1_BLOCKER_09_closed=true
external_exclusive_runtime_lock_required=true
standalone_atomic_compare_and_swap_claim=false
residual_TOCTOU_acknowledged=true
```

## K.2 R4 second-independent-review correction

R3's nine closure values above are historical Codex self-assessments; the
second independent review did not accept them as an approval. R4 corrects the
remaining pure-contract weaknesses without B2 integration: context temp
ownership now binds canonical bytes in addition to a file identity; writable
probes bind a one-call nonce token; broken symlinks are lexical existing
entries; Python prefix/base-prefix bind exactly to the Runtime root; manifest
source metadata is strict; preflight validates typed input invariants and
freezes warnings to `()`; and any unowned live instance is diagnostic-only for
status and blocked for every state-changing or health command. The dedicated
evidence is [ENV-1B1C-B1-R4-CORRECTION-REPORT.md](ENV-1B1C-B1-R4-CORRECTION-REPORT.md).

```text
ENV_1B1C_B1_R3_independent_review_passed=false
ENV_1B1C_B1_R4_required=true
ENV_1B1C_B2_started=false
external_exclusive_runtime_lock_required=true
standalone_atomic_compare_and_swap_claim=false
residual_TOCTOU_acknowledged=true
```

## L. 测试

默认 `python` 入口是 WindowsApps stub，未提供可用 pytest；因此使用现有 embedded development runner
执行隔离测试，并显式注入仓库根与已跟踪的测试-only `python-multipart` wheel（没有安装）。隔离 B1
fixture suite：`53 passed`。B1 加 static/audit regression：`83 passed, 2 warnings`。ENV-1B2P：
`70 passed`；ENV-1B1B PathRoots：`55 passed, 3 skipped`；current-release：`52 passed`；OPS direct scripts
均 exit `0`。所有命令设置 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 与 `PYTHONDONTWRITEBYTECODE=1`，不监听
B1 端口、不访问网络。

全量 `enterprise/tests` 不通过，且其退出码为 `1`。为避免把嵌入式解释器现象误写成“与本分支无关”，
使用同一个现有 embedded development interpreter（CPython 3.12.10 / pytest 8.4.2）、相同的
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` / `PYTHONDONTWRITEBYTECODE=1`、相同的 repository-root 和
已跟踪 test-only `python-multipart` wheel 注入方式，分别运行了 `origin/main` 与 PR Head 的完整
`enterprise/tests`。没有安装、下载或修改 Python Runtime。

| comparison target | result | failed nodeids | exit |
| --- | --- | --- | --- |
| `origin/main@4d9cc4e` | `252 passed, 3 skipped, 4 failed, 8 warnings` | 下列四项 | `1` |
| PR Head `35b4ab3` | `305 passed, 3 skipped, 4 failed, 9 warnings` | 与 base 相同的四项 | `1` |

四个共同失败节点及脱敏错误摘要为：

- `test_env_1b1b_app_path_integration.py::test_portable_roots_are_installed_before_main_import_and_keep_app_root_clean`：子进程无法 import `enterprise`；
- `test_env_1b1b_workflow_overlay.py::test_workflow_overlay_copies_before_config_and_never_deletes_shipped_source`：子进程无法 import `enterprise`；
- `test_stab_1_supervisor_logging.py::test_static_runtime_boundary`：`sitecustomize` logging-origin probe 未被加载；
- `test_stab_1_supervisor_logging.py::test_real_cli_lifecycle_and_acknowledgements`：isolated CLI lifecycle phase worker 在 `start` 阶段失败。

R3 在同一解释器和相同环境变量下重新完成了有效 Base/Head 对照：Base 为 `252 passed, 3 skipped,
4 failed, 8 warnings`，R3 Head 为 `351 passed, 3 skipped, 4 failed, 9 warnings`；有效 Base 使用 detached
Git worktree，避免 `git archive` 缺少 `.git` 造成 audit/upstream-sync 伪失败。`branch_regression_delta=0`：
PR failure-node set 减去 `origin/main` failure-node set 为空。该对照支持“本分支没有新增该四个失败节点”，
但不等于全量测试通过；`full_suite_passed=false`，独立验收仍未闭合。失败行为与该解释器的 `._pth`
不接受子进程 `PYTHONPATH` 的已观察限制相符，但本报告不把该环境解释提升为正式 bundled Runtime 验证。
真实 bundled Python fixture 测试为 `false`；本机结果不是 GitHub CI。

## M. Git / PR

已有实现 commits：`65b298891dca6556c8b147fb8a39974fde7c3e47`
(`feat(env): add runtime contract foundations`) 与 `35b4ab36758047f469ec48928c55a86933cb2d81`
(`docs(env): record ENV-1B1C B1 evidence`) 与 `5c735fb0815c091154c7ad8bd8e59b8b5eeba2e0`
(`docs(env): compare B1 full-suite baseline`)。PR body 链接到当前 PR Head 的固定 GitHub blob URL。
Draft PR：
`https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/84`；Base 为
`4d9cc4ef3d6a0f6ed956c2dda6303e9cc3b99b89`。PR 保持 `OPEN`、`Draft=true`、
`merged=false`、`mergeable=MERGEABLE`；`github_ci_verified=false`。禁止文件分支 diff exit code
均为 `0`；本次 evidence-only correction 后工作树应为 clean。

## N. 边界确认

```text
ENV_1B1C_B1_implementation_in_Draft_PR=true
ENV_1B1C_B2_started=false
portable_runtime_lifecycle_integrated=false
formal_portable_batch_created=false
controller_portable_mode_integrated=false
host_context_validation_integrated=false
child_context_validation_integrated=false
Runtime_rebuilt=false
Manifest_v2_implemented=false
Release_activation_implemented=false
OPS_3B_implemented=false
formal_Release_created=false
production_device_touched_by_codex=false
temporary_test_environment_accessed_by_codex=false
Ready=false
merged=false
```

## R5 trust-chain correction

R5 keeps this PR in Draft and closes the third-review B1 primitive findings:
manifest-to-executable hash binding, typed manifest byte limits, shared
Windows-safe release components, descriptor-first probe identity and nonce
cleanup, stable hash-read errors, symbolic public error details, explicit
portable identity roots with SOABI validation, and shared strict 3.10 version
validation. `decide_release_mismatch()` is release-gate-only and must not be
treated as final process, HTTP, context, or readiness health. See
[the R5 correction report](ENV-1B1C-B1-R5-CORRECTION-REPORT.md).

```text
ENV_1B1C_B1_R5_completed_in_Draft_PR=true
ENV_1B1C_B2_started=false
STOPPED_AFTER_B1_R5_AWAITING_INDEPENDENT_REVIEW=true
```

R5 reran the same full-suite comparison with the existing embedded development
interpreter: Base was `252 passed, 3 skipped, 4 failed, 8 warnings`; R5 Head
was `433 passed, 3 skipped, 4 failed, 9 warnings`. The same four failure
nodeids remained, so `branch_regression_delta=0`; this is not a full-suite
pass and is not GitHub CI evidence.

## R6 stable-error and type-encapsulation correction

R6 is limited to the six fourth-review primitive findings. It preserves the B1
no-lifecycle boundary while making malformed external input retain its original
stable code, requiring the preflight schema invariant, and making direct
`ErrorPayload` construction registry-bound and immutably sanitized. It adds
close-error classification for writable probes, lexical missing/reparse state
classification, and bounded ownership reads. The dedicated details and current
test evidence are in
[ENV-1B1C-B1-R6-CORRECTION-REPORT.md](ENV-1B1C-B1-R6-CORRECTION-REPORT.md).

```text
ENV_1B1C_B1_R6_completed_in_Draft_PR=true
ENV_1B1C_B2_started=false
STOPPED_AFTER_B1_R6_AWAITING_INDEPENDENT_REVIEW=true
```

## R7 bounded-reader and post-replace correction

R7 is the final scoped B1 convergence pass. It adds true bounded readers for
the Runtime Manifest (1 MiB) and Launch Context (16 KiB), including a single
overflow byte only; it preserves a stable uncertain-state contract after an
already-successful context replacement when directory durability cannot be
verified; and it makes duplicate manifest paths retain
`RUNTIME_MANIFEST_PATH_DUPLICATE` with only the symbolic `manifest_path`
detail. It does not add lifecycle wiring. The detailed evidence is
[ENV-1B1C-B1-R7-CORRECTION-REPORT.md](ENV-1B1C-B1-R7-CORRECTION-REPORT.md).

```text
ENV_1B1C_B1_R7_completed=true
ENV_1B1C_B2_started=false
STOPPED_AFTER_B1_R7_AWAITING_FINAL_INDEPENDENT_ACCEPTANCE=true
```

## R7 recovery evidence (current local run)

R7 continuation preserved the interrupted worktree externally and verified its
eight allowed files against the preservation bundle before making no rewrite of
the already-passing primitive implementation. `fetch --no-write-fetch-head`
and `ls-remote` confirmed the intended base and pre-correction branch head.
The current CPython 3.11.9 same-interpreter comparison reported base `256
passed, 3 skipped, 0 failed` and head `479 passed, 5 skipped, 0 failed`;
`branch_regression_delta=0`. This supersedes the historical R3/R5 local
comparison only for this recovery environment; it remains local evidence,
`github_ci_verified=false`, and `real_bundled_python_fixture_tests=false`.
