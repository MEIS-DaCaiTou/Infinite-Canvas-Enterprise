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
W42 是 `writable_probe.probe_writable_root`。Audit：`scanned=90`、`excluded=239`、`detected=299`、
`mapped=299`、`parse_failures=0`、`uncovered=0`、`stale=0`。Digest：
`464b2eef086b6fea37daf810d3b9f0551de652763f23028df799f8affb81e1ab`。

## L. 测试

隔离 B1 fixture suite：`53 passed`。B1 加 static/audit regression：`83 passed, 2 warnings`。ENV-1B2P：
`70 passed`；ENV-1B1B PathRoots：`55 passed, 3 skipped`；current-release：`52 passed`；OPS direct scripts
均 exit `0`。所有命令设置 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 与 `PYTHONDONTWRITEBYTECODE=1`，不监听
B1 端口、不访问网络。

全量 `enterprise/tests` 在当前可用的 embedded development interpreter 下结果为 `305 passed, 3 skipped,
4 failed, 8 warnings`。四项失败均为该 interpreter 的 `._pth` 忽略子进程 `PYTHONPATH`：两项 B1B
subprocess integration 无法从 cwd import `enterprise`，supervisor 的两项则无法加载其 `sitecustomize`
probe 并在 lifecycle start 阶段失败。B1 纯模块不修改这些旧 lifecycle 或 test harness，未为改变该
环境限制安装/升级依赖或 Runtime。真实 bundled Python fixture 测试为 `false`；本机结果不是 GitHub CI。

## M. Git / PR

本报告将在本次 Draft PR 建立后补充 commit、PR URL、Base/Head、checks 与最终工作树状态。

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
