# OPS 路线图（2026-07）

## 1. OPS 总目标

OPS 目标是将生产运维从人工复制和手动命令，演进为：

- 一键准备。
- 计划驱动执行。
- 自动备份。
- 自动盘点。
- 自动数据检查。
- 自动生成升级计划。
- 本地结构化日志。
- 可回滚。
- 可审计。
- 可兼容 Docker / 1Panel / PostgreSQL / 对象存储。

OPS 的核心不是让网页端直接执行任意命令，而是用计划、备份、校验、日志和回滚点约束高危生产动作。

## 2. OPS-2A 边界

OPS-2A 已完成并合并，PR #67，merge commit `7f8586ca90f74a8a172ff9ab2af390099c4cdbc5`。

OPS-2A 实现：

- ops-runner。
- inventory。
- backup。
- check-data。
- validate-release。
- prepare-upgrade。
- OPS job 本地结构化日志。
- upgrade-plan。
- backup manifest。
- data-check report。

OPS-2A 不实现：

- apply-upgrade 正式执行。
- rollback 正式执行。
- PostgreSQL 正式迁移。
- 永久删除生产文件。
- 自动修复 owner map。
- 修改 frpc / frps / 1Panel 配置。
- Update Center 页面内执行。

OPS-2A 是生产运维工具套件第一版，优先解决“看清楚、备得住、校验过、能计划”的问题。

OPS-2A 实现与命令说明见：`docs/ops/OPS-2A-PRODUCTION-OPS-TOOLKIT-2026-07.md`。

OPS-2A 已进入 main 不代表生产已升级，不代表 `apply-upgrade` / `rollback` 已实现，也不代表 Docker / 1Panel / PostgreSQL 已实现。

## 3. OPS-2A 合并后生产侧 dry-run 验证

下一步不是生产升级，而是生产侧只读 / 非破坏性试运行验证：

1. `inventory`
2. `check-data`
3. `backup` dry-run

本阶段只收集报告和确认工具能在生产侧读取当前状态。生产命令必须由项目负责人在生产主机人工执行，Codex 不直接访问生产主机。

`backup --execute` 需要单独确认，不在 OPS-2A 合并后状态同步 PR 中触发。

`validate-release` / `prepare-upgrade` 需要 release 包、backup manifest、data-check report 等前置输入，不会自动执行生产升级。

仍禁止：

- 生产目录 `git pull`。
- 直接覆盖升级。
- `apply-upgrade`。
- `rollback`。
- 自动修复 owner map。
- 删除生产数据。
- 修改 frpc / frps / 1Panel 配置。

## 4. OPS-2B Windows 封装边界

OPS-2B 目标是把生产侧 OPS-2A 命令封装成稳定的 Windows PowerShell wrapper，降低复制粘贴、多行反引号和系统 `python` 缺失带来的人工操作风险。

OPS-2B 实现：

- `run-ops2a-prod-dryrun.ps1`：顺序执行 `inventory`、`check-data`、`backup` dry-run。
- `run-ops2a-backup-execute.ps1`：在显式确认后只执行 `backup --execute`。
- 使用生产目录 bundled Python：`<AppRoot>\python\python.exe`。
- 直接执行工具目录 runner：`<ToolsRoot>\enterprise\ops\runner.py`。
- 输出 OPS 报告和 `jobs.jsonl` 路径，便于项目负责人脱敏回传。

OPS-2B 不实现：

- 生产升级。
- `apply-upgrade`。
- `rollback`。
- `validate-release` / `prepare-upgrade` 自动执行。
- Docker / 1Panel / PostgreSQL 实际实现。
- 数据修复、数据删除或 owner map 自动修复。
- Update Center UI 接入。

OPS-2B 文档见：`docs/ops/OPS-2B-WINDOWS-OPS-WRAPPER-2026-07.md`。

## 5. OPS-3 边界

### OPS-3A Online Update Core

OPS-3A repository implementation is in Draft PR #77. It adds a fixed trusted
release-provider boundary, strict manifest validation, bounded download, safe
Windows-aware staging, evidence-bound local preparation jobs, and a
non-executing online-update plan. Its implementation tests use local workspaces
only.

OPS-3A does not execute a production check, download, staging operation, or
upgrade. It does not implement `apply-upgrade`, rollback, restore, service
lifecycle control, database migration apply, a web OPS API, or an Update Center
UI. Those actions remain separately gated follow-up work.

Implementation details: `docs/ops/OPS-3A-ONLINE-UPDATE-CORE-IMPLEMENTATION-2026-07.md`.

OPS-3 规划：

- OPS-3B: controlled `apply-upgrade` and rollback design after separate review.
- OPS-3C: Update Center page and allowlisted backend OPS API.
- 维护窗口确认。
- 二次确认。
- audit log。
- job log 展示。

OPS-3 才开始接入网页 Update Center。网页端只能调用白名单 OPS API，不得执行任意 shell。

OPS-3 后置于 OPS-2A / OPS-2B 生产侧 dry-run 验证和必要的 OPS-L1 / OPS-D1 设计确认。

### STAB-1 / OPS-L1 Supervisor Foundation

STAB-1 repository implementation is in Draft PR #78.  It adds a local-only,
role-isolated `3001`/`8000` supervisor, persistent redacted logs, atomic
runtime state, fixed lifecycle CLI and Windows Job Object ownership.  Its
tests use temporary fixture processes and random local ports only.  It does not
install a Windows Service, execute a production lifecycle command, implement
remote process control, or add OPS-3B update apply/rollback capability.

Implementation details: `docs/ops/STAB-1-SUPERVISOR-LOGGING-IMPLEMENTATION-2026-07.md`.

## 6. OPS-L 边界

| 阶段 | 目标 |
| --- | --- |
| OPS-L1 | 本地日志：access / app / error / security / ops job JSONL；STAB-1 Draft PR #78 增加 runtime supervisor/child/health/crash 持久日志基础。 |
| OPS-L2 | 远程日志推送，必须脱敏。 |
| OPS-L3 | 后台日志查询。 |
| OPS-L4 | 集中日志平台适配。 |

当前已有 `usage_logs` 审计表，但完整本地日志和远程推送仍是后续规划。

OPS-L1 / OPS-D1 设计可与 OPS-2A 生产侧 dry-run 验证并行推进。

## 7. OPS-D 边界

OPS-D 规划：

- Docker / 1Panel 设计。
- Dockerfile。
- Compose。
- 1Panel 部署手册。
- PostgreSQL / MinIO / Redis 生产化。

OPS-D 不应跳过 OPS 备份、日志和回滚设计。容器化不是绕过数据治理的理由。

## 8. OPS 与数据治理

数据治理规划：

- data-check。
- owner map 巡检。
- orphan 文件。
- missing 文件。
- cleanup plan。
- quarantine。
- repair plan。
- 管理员确认后执行。
- 不自动永久删除。

生产数据治理应先报告、再确认、再执行。任何归属修复、隔离、归档或删除都必须可审计。

## 9. OPS 与安全边界

OPS 安全边界：

- 不直接 `git pull`。
- 不 `checkout main`。
- 不 `reset --hard`。
- 不覆盖生产 `data/`、`assets/`、`history.json`、env 文件。
- 高危操作必须有备份、计划、日志、回滚。
- 网页端不得执行任意 shell。
- OPS API 必须管理员鉴权。
- 高危功能必须 feature flag 控制。
- 远程日志不得泄露敏感信息。

OPS 能力上线后仍必须保持 Draft PR、主对话复核和项目负责人验收流程。

OPS-4 生产升级演练后置于生产侧 dry-run 验证、备份策略确认和回滚方案复核。
