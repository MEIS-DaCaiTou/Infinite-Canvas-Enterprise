# OPS 路线图（2026-07）

更新时间：2026-07-17

最后一次代码事实核对基线：`main@396cccc68d63bd16393a2cb72d24e4a48fcf47cb`；当前 repository HEAD 以 GitHub `main` 为准。文档专用 PR #80 不改变运行时代码事实。OPS-3A 与 STAB-1 / OPS-L1 已合并；OPS-3B 尚未开始，并后置于不可变 Release、路径根、Runtime evidence、Manifest v2、DATA-1 和 restore rehearsal。生产路线以 [ADR-OPS-007](../decisions/ADR-OPS-007-GREENFIELD-PRODUCTION-BASELINE-AND-LEGACY-NON-MIGRATION-2026-07.md) 为准：不原地升级或迁移旧生产；OPS-3B 仓库实现和隔离演练是 Production Baseline 前置门禁，首次真实生产执行则只服务 Greenfield 新生产部署后的版本迭代。完整顺序以 [总体路线图](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md) 为准。

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

## 3. OPS-2A / OPS-2B 旧生产历史验证

项目负责人曾在旧生产本地人工完成以下只读 / 非破坏性试运行：

1. `inventory`
2. `check-data`
3. `backup` dry-run

这些结果证明当时工具可以读取旧生产状态；旧生产盘点、`check-data` warning 和正式备份继续作为历史运维证据保存，但不再是旧到新迁移输入或 Production Baseline 门禁。旧生产不再执行原地升级。任何生产命令仍只能由项目负责人在生产主机人工执行，Codex 不直接访问生产主机。

项目负责人随后已单独确认并在旧生产本地完成一次 `backup --execute`；成功仅证明当次历史备份命令成功，不代表 restore 可用，也不授权将该备份导入新生产。

`validate-release` / `prepare-upgrade` 需要 release 包、backup manifest、data-check report 等前置输入，不会自动执行生产升级；未来新生产必须使用其自身的新基线证据，不能复用旧生产报告或备份。

仍禁止：

- 生产目录 `git pull`。
- 直接覆盖升级。
- `apply-upgrade`。
- `rollback`。
- 自动修复 owner map。
- 删除生产数据。
- 修改 frpc / frps / 1Panel 配置。

## 4. OPS-2B Windows 封装边界

OPS-2B 已将生产侧 OPS-2A 命令封装成稳定的 Windows PowerShell wrapper，降低复制粘贴、多行反引号和系统 `python` 缺失带来的人工操作风险。它在旧生产的历史执行不授权迁移、升级或修复旧数据。

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

OPS-3A repository implementation was merged by PR #77 at
`1430e2d7389c66d82d8f93d3c306451a22a51d3c`. It adds a fixed trusted
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

- OPS-3B：在 Production Baseline 批准前完成 repository implementation，并使用 Fresh Install Bootstrap 建立的全新隔离数据完成 controlled `apply-upgrade`、switch、health、rollback 和 restore 演练；不用于旧生产原地升级。
- OPS-3C：在 Production Baseline 后单独实现 Update Center page and allowlisted backend OPS API；不是首次生产部署前置条件。
- 维护窗口确认。
- 二次确认。
- audit log。
- job log 展示。

OPS-3C 才开始接入网页 Update Center。网页端只能调用白名单 OPS API，不得执行任意 shell。

OPS-3B 仓库实现后置于不可变 Release、Manifest v2、DATA-1、Fresh Install Bootstrap、正式 backup、restore rehearsal、migration compatibility 和 Runtime lifecycle 验证，但必须在 Production Baseline 批准前完成。旧生产 OPS-2A / OPS-2B 结果只保留历史证据，不能满足这些门禁。

### Greenfield 新生产 OPS 边界

Production Baseline 获批前必须在干净 Windows 环境使用全新数据库、账号和配置完成：

- Fresh Install Bootstrap；该能力尚未实现，SEC-1B2 不能替代。
- 首次启动、status / health 与业务验收。
- 针对全新基线数据的正式 backup execute 和 restore rehearsal。
- OPS-3B repository implementation。
- 使用 Fresh Install Bootstrap 建立的全新隔离数据，完成 Release Candidate 之间的 apply / switch / health / rollback / restore 演练。
- 配置、数据库、JSON、资源和启动链路恢复验证。

这些是尚未完成的开发或隔离环境基线资格门禁，不表示新生产已经部署或发生生产执行。Production Baseline 获批时必须已经具备经过验证的持续升级和失败恢复能力。OPS-3B 的首次真实生产执行只能发生在 Greenfield 新生产部署后，并由项目负责人在生产设备本地执行；新生产业务验收通过后，旧生产的停止、归档或删除仍需项目负责人单独授权。

### STAB-1 / OPS-L1 Supervisor Foundation

STAB-1 repository implementation was merged by PR #78 at
`a00a2fd2807b41a9fee3c267ee1116986b52fd7e`; PR #79 at
`396cccc68d63bd16393a2cb72d24e4a48fcf47cb` fixed detached service-host
startup. The implementation adds a local-only,
role-isolated `3001`/`8000` supervisor, persistent redacted logs, atomic
runtime state, full process identity, generation-bound command acknowledgements,
graceful child shutdown and Windows Job Object ownership.  Its fixture tests
use temporary processes and random local ports only.  An isolated development
device run with temporary roots, database, ports and dependencies verified
real upstream/gateway startup, endpoint health, restart-to-stop ACK/host exit,
idempotent stop, start-to-stop reuse and independent role recovery.  `PyJWT`
is now declared because `enterprise.auth` imports `jwt`. This does not install
a Windows Service, execute a production lifecycle command,
implement remote process control, or add OPS-3B update apply/rollback capability.

Implementation details: `docs/ops/STAB-1-SUPERVISOR-LOGGING-IMPLEMENTATION-2026-07.md`.

## 6. OPS-L 边界

| 阶段 | 目标 |
| --- | --- |
| OPS-L1 | 本地日志：STAB-1 PR #78 已增加 supervisor / child / health / crash 持久日志基础；完整 access / app / error / security 统一体系仍未完成。 |
| OPS-L2 | 远程日志推送，必须脱敏。 |
| OPS-L3 | 后台日志查询。 |
| OPS-L4 | 集中日志平台适配。 |

当前已有 `usage_logs` 审计表和 Windows runtime 持久日志；跨业务域统一 access / app / error / security 日志以及远程推送仍是后续规划。

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

新生产的数据治理仍应先报告、再确认、再执行。任何归属修复、隔离、归档或删除都必须可审计。上述能力不得默认扩展为旧数据导入、旧 owner map 修复或旧数据库升级；除非项目负责人通过新决策明确授权，不为待退役旧生产创建此类任务。

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

OPS-4 / 后续升级演练使用 Greenfield 新基线数据，后置于 Fresh Install Bootstrap、正式备份、restore rehearsal 和回滚方案复核；旧生产 dry-run 不再构成上线输入。
