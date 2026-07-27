# ENV-1B1C：Runtime 入口与自检实施记录

- 状态：ENV-1B1C-B1 当前 Draft PR；仅为纯契约、安全原语和隔离测试基础。
- 基线：`main@4d9cc4ef3d6a0f6ed956c2dda6303e9cc3b99b89`（PR #83 merge commit）。
- 非生产事实：`production_device_touched_by_codex=false`；`temporary_test_environment_accessed_by_codex=false`。

## 已实现的 B1 基础

B1 新增的标准库模块为 `mode`、`error_contract`、`runtime_manifest`、`python_identity`、
`preflight`、`launch_context` 和 `writable_probe`。它们不导入 `enterprise.config`、controller、
host、child、supervisor、`main` 或 gateway，且测试只使用临时 fixture。

运行模式必须显式解析：`development` 可使用系统 Python 但不能形成 Release 证据；
`portable-release` 禁止系统 Python 与 PATH fallback；`server` 返回稳定的
`RUNTIME_MODE_NOT_IMPLEMENTED`。Runtime Manifest startup view 固定只验证五个文件：
`python.exe`、`pythonw.exe`、`python310.dll`、`python310.zip`、`python310._pth`。
`candidate_id_required=false`；ARM64 可被解析但当前 portable Windows target 仅批准 x64。R4 要求
source metadata 存在时为严格对象，`enterprise_commit` 存在时为精确 40 位小写十六进制。

Python identity 只接收显式 probe，输出只含 basename、摘要和脱敏 prefix identity。preflight
是不可变、canonical 的纯结果，不会创建 `instance_id`、reserve lock、写 context 或启动进程。
launch context 使用固定 `.new` 文件、exclusive create、file identity、atomic replace 和目录
sync 分类；只有调用方提供的已通过 preflight 与显式 `instance_id` 才能构造它。successful stop
后 context 可保留为受限诊断，但它本身不证明实例仍在运行。

writable probe 仅可对 DATA / LOG / RUNTIME / CACHE / TEMP roots 写入短时、每次调用唯一的
`ice-probe-v1:<nonce>\n` marker，
拒绝 APP_ROOT，并以 file identity 避免删除 foreign replacement。该设计提供 pre-use / post-create
检查，不声称消除全部 Windows TOCTOU。

## 冻结的后续入口契约

未来正式 portable launcher 必须以固定脚本 `enterprise/runtime/launcher.py` 作为 bootstrap，而
不是仅依赖 `python -m enterprise.runtime.launcher`。operator 不得覆盖 install root、LOCALAPPDATA、
Python executable、Runtime Manifest、expected manifest hash 或 launch context 等信任输入。

未来顺序固定为：preflight pass → 在内存生成 `instance_id` → 使用该 identity reserve lock →
构造并发布 launch context → 启动 host / child。B1 只提供其前置数据模型，未接入任何 lifecycle。

Release mismatch 纯判定冻结为：status mismatch exit 0 且标记 mismatch；health mismatch exit 2；
restart mismatch blocked；current Release 可 stop 一个有效 owned 的旧 Release 实例；非 current
Release 的 formal command 均拒绝。

## Audit

`launch_context.publish_launch_context` 映射到 W26（runtime control / diagnostic state）；新的
`writable_probe.probe_writable_root` 映射到 W42（runtime writable-root probe primitive）。R3 将 reparse
inspection 收口为共享 fail-closed path safety 原语，并对 context replace 保留“需要 B2 external exclusive
runtime lock、不能单独宣称 CAS”的边界。R3 staged Draft scan 为 `scanned=91`、`excluded=249`、
`detected=299`、`mapped=299`、parse failures / uncovered / stale 均为 `0`，site manifest digest 为
`464b2eef086b6fea37daf810d3b9f0551de652763f23028df799f8affb81e1ab`。

## 未实施边界

`portable_runtime_lifecycle_integrated=false`；`formal_portable_batch_created=false`；
`controller_portable_mode_integrated=false`；`host_context_validation_integrated=false`；
`child_context_validation_integrated=false`。B1 不创建 `launcher.py`，不修改 Batch、PowerShell、
`main.py`、controller、host、child、supervisor、health/readiness 或 stop/restart 生命周期。

`real_bundled_python_fixture_available=false`、`real_bundled_python_lifecycle_verified=false`；B1
不重建 Runtime、不实现 Manifest v2、Release activation、OPS-3B 或 formal Release，也不批准生产。

## R7 B1 纯原语收口

R7 将 Runtime Manifest 和 Launch Context 的读取限制为各自的最大字节数加一个 overflow
byte，避免外部文件造成无界读取；所有 open/read/close 失败仍映射为各模块既有的稳定错误。
Launch Context 在 `os.replace()` 已成功但目录同步失败时，返回
`LAUNCH_CONTEXT_DIRECTORY_SYNC_FAILED` 并要求调用方重新读取状态，而不删除新的 target 或
虚假回滚。重复 manifest path 使用稳定的
`RUNTIME_MANIFEST_PATH_DUPLICATE` 和符号 detail，不回显外部路径。

这些仍是 B1 的纯契约补正，不构成 portable lifecycle、formal Batch、Release activation 或生产批准。
