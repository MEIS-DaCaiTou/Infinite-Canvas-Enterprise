# ADR-ENV-005：正式入口、自检和执行模式

- 状态：Accepted
- 决策日期：2026-07-16
- 事实基线：`main@396cccc68d63bd16393a2cb72d24e4a48fcf47cb`
- 实施状态：已决策，ENV-1B1C 尚未开始

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

ENV-1B1B 当前 Draft PR 只实现 PathRoots 与 current-release pointer 的纯状态/路径原语。它不会从
pointer 启动服务、选择 `PYTHON_RUNTIME`、回退 PATH Python 或改变 supervisor entrypoint。上述
绑定、自检与 fail-closed launcher 行为仍完整属于 ENV-1B1C，当前未开始。
