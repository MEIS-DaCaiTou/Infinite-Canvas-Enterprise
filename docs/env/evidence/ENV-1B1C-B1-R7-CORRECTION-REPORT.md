# ENV-1B1C-B1-R7：有界读取与替换后语义补正报告

## 范围与结论

R7 仅收口第五轮独立复核确认的三个 B1 纯原语缺口：Runtime Manifest
和 Launch Context 的真正有界读取、Launch Context 原子替换成功后的不确定状态
语义，以及重复 manifest 路径的稳定公开错误码。本补正未接入 controller、host、
child、supervisor、process、Batch、launcher、真实 health lifecycle 或 `main.py`。

```text
R6_REVIEW_BLOCKER_01_closed=true
R6_REVIEW_BLOCKER_02_closed=true
R6_REVIEW_BLOCKER_03_closed=true

bounded_manifest_read_verified=true
bounded_launch_context_read_verified=true
post_replace_uncertain_state_verified=true
duplicate_manifest_path_stable_code_verified=true

B1_known_blockers_remaining=0
ENV_1B1C_B2_started=false
portable_runtime_lifecycle_integrated=false
formal_portable_batch_created=false
Runtime_rebuilt=false
Manifest_v2_implemented=false
Release_activation_implemented=false
OPS_3B_implemented=false
formal_Release_created=false
production_device_touched_by_codex=false
temporary_test_environment_accessed_by_codex=false
```

`B1_known_blockers_remaining=0` 仅是本次三项范围内的 Codex 实现自评，不替代独立验收。

## R7-T01：Runtime Manifest 有界读取

`runtime_manifest._read_manifest_bounded()` 以二进制显式打开文件，以固定小块循环读取，
并把累计请求量严格限制在 `manifest_max_bytes + 1`（1 MiB + 1）以内。它不使用
`Path.read_bytes()`、不使用无参数 `read()`，一旦取得第一个 overflow byte 即停止。

- 空文件或超过限制：`RUNTIME_MANIFEST_SIZE_INVALID`；
- open、read 或 close 的 I/O 故障：`RUNTIME_MANIFEST_READ_FAILED`；
- 缺失文件仍保持 `RUNTIME_MANIFEST_MISSING`。

受控 fake handle 测试覆盖恰好上限、上限加一、远大于上限的虚拟流和 open/read/close
故障，并检查每个 `read(size)` 请求与累计请求量；测试不分配超大输入。

## R7-T02：Launch Context 有界读取

`launch_context._read_context_bounded()` 使用相同的单一 overflow byte 协议，但其最大值为
16 KiB。它不调用 `Path.read_bytes()` 或无参数 `read()`。

- 空文件或超过限制：`LAUNCH_CONTEXT_SIZE_INVALID`；
- open、read 或 close 的 I/O 故障：`LAUNCH_CONTEXT_INVALID`。

测试同样覆盖精确上限、上限加一、远大于上限的虚拟流和各 I/O 故障，并断言累计读取请求
不超过 `16 KiB + 1`。

## R7-T03：replace 后的 uncertain state

`publish_launch_context()` 显式维护 `target_replaced`。仅在 `os.replace()` 成功后，目录
同步的 path-safety、open 或 fsync 故障才统一映射到
`LAUNCH_CONTEXT_DIRECTORY_SYNC_FAILED`。该稳定错误的公开契约包含：

```text
pointer_or_context_may_have_changed=true
reread_state_required=true
```

此时不会删除已替换的 target，调用方必须重新读取权威 context；实现不会尝试自动回滚。
若 `os.replace()` 本身失败，仍为 `LAUNCH_CONTEXT_WRITE_FAILED`，不错误设置上述
post-replace 标志。外部 exclusive runtime lock 仍是 B2 的要求；本原语不声称 standalone
atomic compare-and-swap 或消除 residual TOCTOU。

## R7-T04：重复 Manifest 路径

重复的规范化 manifest path 现在总是返回 `RUNTIME_MANIFEST_PATH_DUPLICATE`，无论原始
路径中有斜杠、空格或其它会被公共 detail sanitizer 拒绝的字符。公开 `details` 只含稳定的
符号标签 `manifest_path`，不回显外部路径。

## 测试与边界

使用已有 embedded development interpreter、`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 与
`PYTHONDONTWRITEBYTECODE=1` 执行。R7 新增的有界 reader / post-replace / duplicate-path
对抗测试已包含在 B1 focused suite；所有测试使用临时 fixture，不监听端口、不启动业务服务、
不访问网络或外部 Runtime artifact。

R7 完成后仍须独立复核本任务三项、分支范围与回归证据：

```text
ENV_1B1C_B1_R7_completed=true
ENV_1B1C_B2_started=false
STOPPED_AFTER_B1_R7_AWAITING_FINAL_INDEPENDENT_ACCEPTANCE=true
```

## Recovery continuation and local evidence

The interrupted R7 worktree was preserved outside Git before continuation.
The preserved payload matched the eight current R7 files byte-for-byte. Remote
baseline verification used `git fetch --no-write-fetch-head` and `git
ls-remote`; both confirmed `main@4d9cc4ef3d6a0f6ed956c2dda6303e9cc3b99b89`
and the pre-correction branch head `62453edbad2b790f4f4c31563a8cafee68205286`.
No ACL was changed and no destructive recovery command was used.

With `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` and `PYTHONDONTWRITEBYTECODE=1`, the
two R7 target files produced `93 passed, 1 skipped`; the complete B1 focused
set produced `214 passed, 2 skipped`. Same-interpreter full-suite comparison
using CPython 3.11.9 was: base `256 passed, 3 skipped, 8 warnings`, head
`479 passed, 5 skipped, 8 warnings`; both exited 0, so
`branch_regression_delta=0` and `full_suite_passed=true` for this local run.
These are Codex-reported local results, not GitHub CI or a real bundled-Python
lifecycle verification.

```text
focused_passed=214
focused_failed=0
focused_skipped=2
base_passed=256
base_skipped=3
base_failed=0
head_passed=479
head_skipped=5
head_failed=0
branch_regression_delta=0
full_suite_passed=true
github_ci_verified=false
real_bundled_python_fixture_tests=false
posix_pure_contract_tests_verified=false
destructive_git_recovery_used=false
automatic_stash_used=false
ACL_modified=false
user_files_deleted=false
```
