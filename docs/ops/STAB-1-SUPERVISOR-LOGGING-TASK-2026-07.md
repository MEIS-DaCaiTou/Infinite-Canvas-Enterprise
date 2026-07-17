# STAB-1 / OPS-L1：Windows 进程监督与持久化日志任务（2026-07）

> **状态：历史任务书，已实施。** PR #78 已合并，PR #79 已合并 detached service-host 启动修复；当前事实见 [STAB-1 实施文档](./STAB-1-SUPERVISOR-LOGGING-IMPLEMENTATION-2026-07.md)。本文“已确认现状”描述的是实施前故障，不代表当前 main。

## 目标

修复企业版当前“启动窗口关闭即停服、任一子进程退出即全体清理、无自动恢复、无持久日志”的生产稳定性缺陷，并为后续 OPS-3B 在线升级切换提供可靠的服务生命周期基础。

## 已确认现状

当前 `enterprise/launcher.py`：

- 以当前前台控制台为生命周期宿主。
- Windows Job Object 与 launcher 绑定，关闭窗口会结束 launcher 并清理 3001/8000。
- launcher 启动 upstream 后只等待 gateway；`gateway.wait()` 返回即进入 `finally`，终止 gateway 与 upstream。
- 没有子进程监督重启、退避、崩溃循环保护或状态文件。
- uvicorn 使用 warning 日志级别，stdout/stderr 未形成可靠持久日志。
- 8000 已被占用时只提示已有服务，不验证 3001、健康状态或进程归属。

生产事件还确认过 bundled Python 的 Windows 原生 `0xc0000005` 崩溃。因此本任务不能只隐藏窗口，必须补齐监督、日志、恢复和诊断闭环。

## 本 PR 必须实现

### 1. 独立 supervisor 核心

新增可测试的 supervisor 模块，launcher 只作为交互入口，不把全部逻辑继续堆入 `launcher.py`。

建议结构：

```text
enterprise/runtime/
  __init__.py
  supervisor.py
  logging.py
  health.py
  state.py
```

允许根据现有风格调整。

### 2. 子进程监督

分别监督：

- upstream：`127.0.0.1:3001`
- gateway：`0.0.0.0:8000`

要求：

- 记录启动时间、PID、父 PID、命令角色、退出码、退出时间。
- 任一子进程异常退出时，不直接无条件结束另一个健康进程。
- 对异常子进程执行有限次数自动重启。
- 指数或分级退避，带最大退避值。
- 滑动时间窗内超过阈值后进入 `crash_loop`，停止自动重启并输出明确状态。
- 正常人工停止不得触发自动重启。
- upstream 重启后，gateway 应继续存活；健康检查恢复后服务恢复可用。
- gateway 重启不得无条件杀掉 upstream。
- supervisor 自身退出时按受控顺序停止子进程。
- 子进程不得成为孤儿。
- 不使用任意 shell；命令参数为固定白名单数组。

### 3. 启动门禁

启动前检查：

- 3001/8000 监听状态。
- 已有监听 PID、命令行、可执行文件路径和进程归属。
- `/api/app-info`、`/enterprise/health` 的实际健康状态。
- 区分：完整健康实例、gateway-only、upstream-only、陌生进程占端口、残留半实例。

不得仅因 8000 已监听就认为服务健康。

首版对陌生占用或半实例必须 fail closed，只报告，不自动结束陌生进程。

### 4. 持久化日志

默认写入应用根目录外可配置的日志根；开发默认可使用 `logs/`，生产可由环境配置为 OPS 日志目录。

最少生成：

```text
launcher.log
supervisor.log
upstream.stdout.log
upstream.stderr.log
gateway.stdout.log
gateway.stderr.log
health.log
crash-events.jsonl
runtime-state.json
```

要求：

- UTC 时间、角色、PID、事件、退出码、重启序号。
- stdout/stderr 分离落盘。
- 日志轮转与保留数量限制。
- 文件创建使用安全路径，拒绝写入运行数据目录和 secret 文件路径。
- 不记录密码、Authorization、Cookie、API Key、JWT、环境变量值或完整请求正文。
- Python traceback 能完整保存。
- 原生退出无法提供 traceback 时仍记录 Windows exit code 与进程元数据。
- JSONL 必须结构化、单行、可追加、敏感字段脱敏。

### 5. 运行状态文件

原子写入 `runtime-state.json`，至少包含：

```json
{
  "schema_version": "runtime-supervisor-state-v1",
  "supervisor_pid": 0,
  "state": "starting|healthy|degraded|restarting|crash_loop|stopping|stopped",
  "started_at": "UTC",
  "updated_at": "UTC",
  "upstream": {
    "pid": 0,
    "state": "...",
    "restart_count": 0,
    "last_exit_code": null,
    "last_exit_at": null,
    "health": "ok|failed|unknown"
  },
  "gateway": {}
}
```

不得包含环境变量或 secret。

### 6. 健康检查

- TCP 监听检查。
- upstream `/api/app-info`。
- gateway `/enterprise/health`。
- 启动成功需在超时内通过健康检查。
- 运行期按固定间隔检查。
- 短暂失败与连续失败阈值分离，避免网络抖动触发重启。
- 只在明确“进程已退出”或连续健康失败达到阈值时进入恢复逻辑。
- 所有超时、间隔和阈值需有安全默认值及合理上限。

### 7. 交互与后台运行

本 PR 提供两种明确模式：

- `foreground`：关闭窗口等同人工停止，保留现有可理解行为。
- `service-host`：无交互输入、无自动打开浏览器、适合 Windows 服务包装器或任务计划程序托管。

不得伪装成已经安装 Windows Service。正式服务安装/卸载可放后续部署 PR，但 service-host 必须可以被 NSSM、WinSW 或 Windows Task Scheduler 安全托管。

禁止通过关闭普通浏览器或管理 UI 触发服务停止。

### 8. 与 OPS-3B 的接口

提供固定、可审计的生命周期接口：

```text
status
start
stop
restart
health
```

本 PR 可先提供本地 CLI/service API，但：

- 不允许任意命令参数。
- 不实现网页远程执行。
- 不实现 apply-upgrade。
- 不实现 rollback。
- 不执行数据库 migration。
- 不直接替换生产版本。

### 9. Windows 原生崩溃证据

新增只读崩溃摘要采集接口：

- 记录子进程负数/Windows 异常退出码。
- 可选读取当前进程退出上下文，不要求管理员权限。
- 不读取或上传 dump。
- 不自动读取全部 Windows Event Log。
- 文档说明如何由生产 Codex 关联 WER/Event ID 1000/1001。

## 测试要求

全部测试使用临时目录、短生命周期 fixture 子进程和本地 HTTP fixture，不操作生产。

最低覆盖：

1. upstream 正常启动、gateway 正常启动、状态 healthy。
2. upstream 异常退出后仅重启 upstream，gateway 不被无条件终止。
3. gateway 异常退出后仅重启 gateway，upstream 保持。
4. 连续崩溃进入 crash_loop，不无限拉起。
5. 人工 stop 不触发重启。
6. supervisor 退出时两个子进程受控停止。
7. 启动超时与健康检查失败。
8. gateway-only / upstream-only / 陌生端口占用 fail closed。
9. 完整健康旧实例识别。
10. stdout/stderr 持久化。
11. 日志轮转。
12. runtime-state 原子更新和状态迁移。
13. 日志敏感字段脱敏。
14. Windows 风格退出码记录。
15. foreground 与 service-host 行为差异。
16. 不打开浏览器的 service-host。
17. 不使用 shell=True。
18. 现有 launcher 基本启动回归。
19. 现有 enterprise gateway/upstream 测试回归。
20. OPS-3A、SEC 与隔离回归不得被破坏。

## 验收门槛

开发完成后必须：

- PR 保持 Draft，未经审查不得合并。
- 给出 changed-file 清单。
- 给出状态机与重启策略。
- 给出日志格式与脱敏策略。
- 给出完整测试结果。
- `git diff --check`、`git show --check` 通过。
- 变更范围 secret/runtime scan 通过。
- 明确确认未触碰生产。

生产副本验收后才可进入基准版本：

- 连续运行 72 小时。
- 3001/8000 无需人工保持控制台窗口。
- 模拟 upstream 崩溃可自动恢复。
- 模拟 gateway 崩溃可自动恢复。
- crash loop 可被阻断并有完整日志。
- 当前生产数据未被修改。
- 生产日志可完整解释每次退出与重启。

## 明确不做

- 不处理 Windows 系统蓝屏或 Defender 本身故障。
- 不声称修复 CPython `0xc0000005` 根因。
- 不安装第三方 Windows 服务管理器。
- 不实现 OPS-3B apply-upgrade/rollback。
- 不实现 OPS-3C Update Center。
- 不修改生产数据或 secrets。
