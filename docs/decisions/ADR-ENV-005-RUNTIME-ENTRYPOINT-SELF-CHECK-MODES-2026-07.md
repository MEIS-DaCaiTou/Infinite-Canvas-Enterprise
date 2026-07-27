# ADR-ENV-005：正式入口、自检和执行模式

- 状态：Accepted
- 决策日期：2026-07-16
- 事实基线：`main@396cccc68d63bd16393a2cb72d24e4a48fcf47cb`
- 实施状态：已决策；ENV-1B1C-A 架构门禁已完成，ENV-1B1C-B1 纯契约、安全原语和隔离测试已由 PR #84 合并并通过独立验收；正式生命周期仍未接入。

## 运行模式

| 模式 | 用途 | Python 规则 |
| --- | --- | --- |
| `development` | 开发、静态检查和明确测试 | 可显式使用系统 Python |
| `portable-release` | 当前 Windows 正式发行方式 | 只允许当前 Release 内 Python |
| `server` | 未来 Linux / container adapter | 只保留契约，本阶段不实施 |

模式必须显式解析。未声明正式 Release 时不得根据解释器是否存在自动猜测模式。

## 决策

1. Windows `portable-release` 的 start / stop / restart / status / health / foreground / host / child / process 必须使用同一个已验证的 `PYTHON_RUNTIME`。
2. `.bat`、runtime controller、host、child 和 process helper 均不得静默回退 PATH Python、`py` 或 `sys.executable`。
3. Release Python 缺失、版本错误、ABI 不匹配、manifest 不匹配或必要依赖缺失时 fail closed。
4. `development` 可以显式选择系统 Python，但输出必须标识 development mode，且不能据此形成 Release 验证结论。
5. launcher 在 Python 不可用时仍应通过批处理提供稳定、脱敏的错误分类和日志位置。

## 自检分层

### 启动快速自检

每次 service-host 启动执行，使用 Python 标准库完成：

- mode、APP_ROOT、PYTHON_RUNTIME 和 `sys.executable` 绑定。
- Python 实现、精确版本、架构和 ABI。
- runtime / release manifest schema 与哈希绑定。
- 必需模块可导入。
- CONFIG_ROOT、DATA_ROOT、LOG_ROOT、RUNTIME_ROOT 权限。
- APP_ROOT 只读门禁与上游版本兼容。
- 不输出 secret、环境变量值或完整敏感路径。

### 完整运行时审计

独立命令执行全部文件、wheel、lock、SBOM 和归档哈希检查。该检查不得在每次 child 重启时重复，以免把完整文件树哈希引入恢复热路径。

## 后果

- 生产行为不再取决于机器 PATH 和偶然安装的依赖。
- runtime supervisor 的角色重启复用同一已验证解释器。
- 测试报告必须明确解释器和运行模式，系统 Python 结果不能替代 Release Python 结果。

## 与 ENV-1B1B 的接口边界

ENV-1B1B 已由 PR #83 合并，只实现 PathRoots 与 current-release pointer 的纯状态/路径原语。它不会从
pointer 启动服务、选择 `PYTHON_RUNTIME`、回退 PATH Python 或改变 supervisor entrypoint。上述
绑定、自检与 fail-closed launcher 行为仍完整属于 ENV-1B1C，尚未接入运行时入口。

在 C1 correction pass 中，development CLI 保持 supervisor 日志回落既有外部 `RUNTIME_ROOT`，不将其
迁回 `APP_ROOT/logs/runtime`；仅隔离 portable fixture 可显式注入 `LOG_ROOT/runtime`。这不是正式
portable 入口协议，也不改变本 ADR 对 ENV-1B1C 的边界。

## ENV-1B1C-B1 实施边界

PR #84 合并的 B1 范围只冻结并测试后续入口所需的纯模型：显式 `development`、`portable-release` 和
`server` mode（`server` fail closed）；固定五个 startup core files：`python.exe`、`pythonw.exe`、
`python310.dll`、`python310.zip`、`python310._pth`；`candidate_id` 为可选 metadata；当前 portable
Windows target 仅批准 x64，ARM64 可解析但不获批准。Python identity 仅来自显式 probe，禁止 PATH
fallback、`pythonw.exe`、错误 ABI 或不满足 bytecode policy 的 identity。

未来启动顺序固定为：preflight pass → 在内存生成 `instance_id` → 用该 identity reserve lock →
构造并发布 launch context → 启动 host / child。B1 的 launch context 仅为 `RUNTIME_ROOT` 下的原子
发布原语；successful stop 后可保留为受限诊断，不能单独证明运行中 ownership。writable-root probe
只允许 DATA / LOG / RUNTIME / CACHE / TEMP roots，明确拒绝 APP_ROOT。

B1 不创建 `launcher.py`、不修改 Batch / PowerShell、也不接入 controller、host、child、supervisor、
`main.py` 或 gateway。未来正式 Batch 必须调用固定脚本 `enterprise/runtime/launcher.py`，不得将
`python -m enterprise.runtime.launcher` 作为唯一 bootstrap；operator 也不得覆盖 install root、
LOCALAPPDATA、Python、Runtime Manifest 或 launch context 等信任输入。

## 2026-07-27 implementation-status addendum

PR #84 source Head `afa03af45da938549a1e62e36df8de11d7c82867` 已通过 squash merge commit
`d3885a92968e68f35500318977341c94612ab2a2` 进入 `main`。独立验收只接受 B1 的 Runtime mode、stable
error contract、Runtime Manifest startup view、Python identity、StartupPreflightResult、Launch Context、
writable-root probe、release/ownership gate 和共享 path-safety primitives；最终记录见
[ENV-1B1C-B1 Final Acceptance / Closeout](../env/evidence/ENV-1B1C-B1-FINAL-ACCEPTANCE-CLOSEOUT-2026-07-27.md)。

本 addendum 不改变 ADR 的 Accepted 状态、决策日期、原始事实基线或任何规范性规则。ENV-1B1C-B2 尚未
开始；portable launcher、controller/host/child 生命周期接线、固定 Release Python 真实启动链、最终
health/readiness、Manifest v2、activation、formal Release、Production Baseline 和 production validation
均未实现。
