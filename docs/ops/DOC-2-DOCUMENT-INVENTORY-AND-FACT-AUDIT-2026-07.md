# DOC-2：文档清单与事实审计（2026-07）

- 审计日期：2026-07-16
- 审计基线：`main@396cccc68d63bd16393a2cb72d24e4a48fcf47cb`
- 审计范围：基线中 62 份受 Git 管理的 Markdown、文本依赖/运行说明和 `enterprise.env.example`
- 本 PR 新增输出：本审计、`docs/README.md` 和 6 份 ADR
- 删除历史文档：0

## 分类定义

| 分类 | 含义 |
| --- | --- |
| A | `CURRENT_FACT_SOURCE`，当前唯一事实或决策源 |
| B | `CURRENT_REFERENCE`，内容有效但不是唯一事实源 |
| C | `STALE_NEEDS_UPDATE`，当前事实、SHA、PR、版本或路径过期 |
| D | `SUPERSEDED_HISTORICAL`，历史记录仍有价值 |
| E | `DUPLICATE_OR_CONFLICTING`，与事实源重复或冲突，需要替代标记 |
| F | `PLANNED_NOT_IMPLEMENTED`，规划内容必须明确未实现 |
| G | `IMPLEMENTED_NOT_RECORDED`，代码已实现但当前文档未同步 |
| H | `UNKNOWN_NEEDS_REVIEW`，无法从 Git、代码或 PR 确认 |

## 审计时分类统计

| A | B | C | D | E | F | G | H | 合计 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 3 | 31 | 6 | 9 | 6 | 2 | 5 | 0 | 62 |

C 和 G 项已在本轮同步；E 项保留文件并增加替代关系。H 为 0，没有因事实无法核验而需要项目负责人裁决的文档。

## 当前事实核验

- 当前 main：`396cccc68d63bd16393a2cb72d24e4a48fcf47cb`。
- PR #77 已合并，merge commit `1430e2d7389c66d82d8f93d3c306451a22a51d3c`。
- PR #78 已合并，merge commit `a00a2fd2807b41a9fee3c267ee1116986b52fd7e`。
- PR #79 已合并，merge commit `396cccc68d63bd16393a2cb72d24e4a48fcf47cb`。
- OPS-3A、Windows supervisor、独立角色恢复、固定 lifecycle CLI、持久日志、runtime state、Job Object、PyJWT 依赖声明和 detached service-host 修复已进入 main。
- 以上不代表生产已切换 supervisor、生产 migration 已执行、正式 Windows Release 已发布、OPS-3B 已实现或 Windows Service 已安装。

## 全量清单

“基线”表示文档描述的主要时点；“处理”表示 DOC-2 的结果。

| 文档 | 用途 | 类别 | 事实基线 | 替代 / 当前来源 | 本轮处理 |
| --- | --- | --- | --- | --- | --- |
| `新手运行与使用教程.md` | 上游用户教程 | B | 上游功能参考 | `README.md` 负责企业入口 | 保留 |
| `运行说明.txt` | 上游简短运行说明 | B | 上游历史入口 | `README.md` | 保留 |
| `AGENT_CONTEXT.md` | 旧 Agent 当前上下文 | E | `2026-07-08` / `73a645f` | `docs/README.md`、CURRENT_PROJECT_STATUS | 标记 superseded |
| `ARCHITECTURE.md` | 当前运行架构摘要 | C | `a095ce2e` | 本文件 + ADR-ENV-001 | 更新到当前 main/runtime |
| `CODE_BOUNDARIES.md` | 代码与数据边界 | A | 当前边界 | ADR-ENV-003/004 | 增加 ENV 决策链接 |
| `CODEX_WORKFLOW.md` | Agent / PR 工作流 | B | 当前工作流 | `docs/README.md` | 保留 |
| `DEVELOPMENT_PLAN.md` | 旧阶段计划 | E | 3G / U-2 时代 | 当前 roadmap | 标记 superseded |
| `docs/architecture/ARCH-2A-ARCHITECTURE-ASSESSMENT-AND-EVOLUTION-2026-07.md` | 旧基线详细评估 | C | `a095ce2e` | ADR-ENV-001 至 005 | 保留评估，增加当前状态说明 |
| `docs/architecture/ENTERPRISE-ARCHITECTURE-BLUEPRINT-2026-07.md` | 企业架构蓝图 | C | `a095ce2e` | ADR + 当前状态 | 同步 runtime / OPS 事实 |
| `docs/bugs/U2-HISTORY-REFRESH-LOSS-INVESTIGATION.md` | 已关闭缺陷调查 | D | PR #62 前后 | 当前状态 | 保留历史 |
| `docs/CURRENT_PROJECT_STATUS.md` | 当前实施事实源 | G | 缺 PR #78/#79 完成事实 | 唯一当前事实源 | 全量同步 |
| `docs/decisions/ADR-0001-enterprise-gateway-over-upstream.md` | 早期 Gateway 决策 | E | 2026-06-11 | ADR-ENV-001 | 标记 superseded |
| `docs/decisions/ADR-3g-7b-user-delete-data-cleanup.md` | 用户删除治理决策 | B | 3G-7B | 安全实施文档 | 保留 |
| `docs/decisions/ADR-current-architecture-and-next-stage.md` | 早期总体架构决策 | E | 2026-07-08 | ADR-ENV-001、当前 roadmap | 标记 superseded |
| `docs/decisions/ADR-SEC-1A-SUPER-ADMIN-CAPABILITY-GOVERNANCE-2026-07.md` | 安全治理 ADR | A | PR #71 | 当前安全决策源 | 保留 |
| `docs/deployment/DOCKER-1PANEL-DEPLOYMENT-BLUEPRINT-2026-07.md` | Linux / Docker 规划 | F | 规划 | ADR-ENV-004/005 | 强化未实现标识 |
| `docs/enterprise-ownership-model.md` | owner 模型 | B | 3G owner 基线 | CURRENT_PROJECT_STATUS | 保留 |
| `docs/enterprise-resource-path-matrix.md` | 资源路径矩阵 | B | 3G 资源治理 | 隔离矩阵 | 保留 |
| `docs/manual-acceptance-checklist.md` | 手工验收 | B | 3G 早期 | tests README | 保留 |
| `docs/manual-acceptance-enterprise-e2e.md` | 企业 E2E 矩阵 | B | 3G-7B | tests README | 保留 |
| `docs/ops/OPS-0-PRODUCTION-INVENTORY-2026-07.md` | 当时生产只读盘点 | D | 2026-07-09 | CURRENT_PROJECT_STATUS | 保留历史，不推导当前生产 |
| `docs/ops/OPS-1-PRODUCTION-UPGRADE-GOVERNANCE-DESIGN-2026-07.md` | 升级治理设计 | D | OPS-1 | ADR-OPS-006、OPS roadmap | 保留历史 |
| `docs/ops/OPS-2A-PRODUCTION-OPS-TOOLKIT-2026-07.md` | OPS-2A 实施参考 | B | PR #67 | OPS roadmap | 保留 |
| `docs/ops/OPS-2B-WINDOWS-OPS-WRAPPER-2026-07.md` | OPS-2B 实施参考 | B | PR #69 | OPS roadmap | 保留 |
| `docs/ops/OPS-3A-ONLINE-UPDATE-CORE-IMPLEMENTATION-2026-07.md` | OPS-3A 实施说明 | G | 仍写 Draft PR #77 | OPS roadmap | 更新为 merged |
| `docs/ops/OPS-3A-ONLINE-UPDATE-CORE-TASK-2026-07.md` | OPS-3A 原任务书 | D | PR #77 之前 | OPS-3A implementation | 标记 historical / implemented |
| `docs/ops/OPS-ROADMAP-2026-07.md` | 当前 OPS 路线 | G | 缺 PR #77/#78 合并 | ADR-OPS-006 | 同步并加入 ENV 前置 |
| `docs/ops/PRODUCTION-UI-DELTA-RECONCILIATION-2026-07.md` | PR #76 UI delta 记录 | D | PR #76 | 当前状态 | 保留历史 |
| `docs/ops/STAB-1-SUPERVISOR-LOGGING-IMPLEMENTATION-2026-07.md` | runtime 实施说明 | G | 缺 PR #78/#79 合并 | 当前状态 | 同步 merged / hotfix |
| `docs/ops/STAB-1-SUPERVISOR-LOGGING-TASK-2026-07.md` | STAB-1 原任务书 | D | PR #78 之前 | STAB implementation | 标记 historical / implemented |
| `docs/roadmap/DEVELOPMENT-ROADMAP-2026-2027.md` | 当前总体路线 | C | `a095ce2e` | ENV / OPS ADR | 更新为 ENV-1B 路线 |
| `docs/runbooks/SEC-1B2-PRODUCTION-ACTIVATION-RUNBOOK-2026-07.md` | 本机生产人工 runbook | B | SEC-1B2 | 当前安全文档 | 保留，未执行事实不变 |
| `docs/security/SEC-1B1-ROLE-AUTH-VERSION-IMPLEMENTATION-2026-07.md` | SEC-1B1 实施 | B | PR #72 | CURRENT_PROJECT_STATUS | 保留 |
| `docs/security/SEC-1B2-CONTROLLED-ACTIVATION-BOOTSTRAP-2026-07.md` | SEC-1B2 实施 | B | PR #75 | runbook | 保留 |
| `docs/security/SEC-1C0-SUPER-ADMIN-TRANSITIONAL-PROTECTION-2026-07.md` | SEC-1C0 实施 | B | PR #74 | 当前安全路线 | 保留 |
| `docs/security/SEC-1F0-MANDATORY-SECURITY-AUDIT-IMPLEMENTATION-2026-07.md` | SEC-1F0 实施 | B | PR #73 | 当前安全路线 | 保留 |
| `docs/upstream/README.upstream.md` | 上游 README 镜像 | B | 上游参考 | SYNC_POLICY | 保留 |
| `docs/upstream/SYNC_POLICY.md` | 上游同步事实源 | A | U-2 / 2026.07.6 | 当前上游政策 | 增加 ENV 冻结例外 |
| `docs/upstream/U-2-CONTROLLED-SYNC-2026-07.md` | U-2 实施记录 | D | PR #61/#62 | SYNC_POLICY | 保留历史 |
| `docs/upstream/UPSTREAM-SYNC-AUDIT-2026-07.md` | U-1 审计 | D | PR #60 前后 | SYNC_POLICY | 保留历史 |
| `ENTERPRISE_DOCS.md` | 企业开发规范 | B | 当前参考 | CODE_BOUNDARIES | 保留 |
| `ENTERPRISE_ISOLATION_MATRIX.md` | 数据域隔离矩阵 | B | U-2 / 3G | tests README | 保留 |
| `ENTERPRISE_PERMISSION_DESIGN.md` | 权限设计参考 | B | SEC-1A 前 | ADR SEC-1A | 保留参考，不作为当前 Capability 完成证明 |
| `enterprise.env.example` | 配置字段示例 | B | 当前配置 | ADR-ENV-004/005 | 保留，不含真实 secret |
| `enterprise/requirements.txt` | 企业附加依赖说明 | B | 当前依赖 | ADR-ENV-002 | 保留，正式锁尚未实现 |
| `enterprise/tests/BROWSER_REGRESSION_CHECKLIST.md` | 浏览器回归清单 | B | 当前测试参考 | tests README | 保留 |
| `enterprise/tests/browser-regression.md` | 浏览器自动化规划 | F | 规划 | tests README | 明确未完成全自动化 |
| `enterprise/tests/README.md` | 测试事实源 | G | 仍写 Draft PR #78 | 当前测试文件 | 更新 merged 状态 |
| `enterprise/tests/SMOKE_CHECKLIST.md` | 上游同步 smoke | B | 当前参考 | tests README | 保留 |
| `enterprise/tests/UPDATE_TEST_LOG.md` | 历史测试日志 | D | 多次上游同步 | tests README | 保留历史 |
| `HANDOVER.md` | 旧 Codex 交接 | E | 2026.06.01 | docs/README、CURRENT_PROJECT_STATUS | 标记 superseded |
| `MAC-使用说明.md` | 上游 macOS 说明 | B | 上游参考 | README | 保留，不代表企业 macOS 支持 |
| `PROJECT_CHARTER.md` | 项目定位章程 | B | 当前定位 | ADR-ENV-001 | 增加当前事实源链接 |
| `PROJECT_HANDOFF_FOR_NEW_AGENT.md` | 旧新 Agent 交接包 | E | `2026-07-08` / `73a645f` | docs/README | 标记 superseded |
| `PROJECT_SCOPE_LOCK.md` | 项目范围与禁止边界 | C | U-2 / PR #63 | CURRENT_PROJECT_STATUS、roadmap | 同步 ENV-1B 当前范围 |
| `README.md` | 仓库入口 | C | `73a645f` 和旧 launcher 说明 | docs/README、当前状态 | 更新入口和 main |
| `requirements.txt` | 基础依赖声明 | B | 当前代码 | ADR-ENV-002 | 保留；不是正式锁文件 |
| `SECURITY_BASELINE.md` | 安全配置边界 | B | 当前参考 | ADR SEC-1A / security docs | 保留 |
| `static/system-prompts/infinite-canvas-prompt-templates.md` | 业务提示词 | B | 业务资源 | 非架构事实源 | 保留，不修改 static |
| `static/vendor/MANIFEST.md` | 前端 vendor 资产清单 | B | 当前静态资产 | 非架构事实源 | 保留，不修改 static |
| `tools/chrome-local-asset-importer/README.md` | Chrome 工具说明 | B | 工具参考 | 非主项目事实源 | 保留 |
| `tools/photoshop-asset-connector/README.md` | Photoshop 工具说明 | B | 工具参考 | 非主项目事实源 | 保留 |

## 本轮新增文档

| 文档 | 类别 | 说明 |
| --- | --- | --- |
| `docs/README.md` | A | 文档事实源与导航 |
| 本文 | A | 全量清单、分类和处理记录 |
| `docs/decisions/ADR-ENV-001-...md` | A | 模块化单体决策 |
| `docs/decisions/ADR-ENV-002-...md` | A | Python runtime / provenance 决策 |
| `docs/decisions/ADR-ENV-003-...md` | A | 不可变 Release / static 决策 |
| `docs/decisions/ADR-ENV-004-...md` | A | 路径根与版本目录决策 |
| `docs/decisions/ADR-ENV-005-...md` | A | 正式入口和自检决策 |
| `docs/decisions/ADR-OPS-006-...md` | A | Manifest v2 与数据库回滚决策 |

## 过期和冲突事实处理摘要

1. PR #77、#78、#79 状态统一为已合并，并记录 merge commit。
2. `396cccc...` 成为当前文档事实基线；`a095ce2e`、`73a645f` 等只保留历史语义。
3. Windows supervisor、角色独立恢复、lifecycle CLI、日志、state、Job Object 和 service-host hotfix 记录为仓库已实现，但不写成生产已切换。
4. ENV-1、Manifest v2、OPS-3B、Windows Service、Linux deployment、PostgreSQL、Redis、durable queue 和多实例继续标为未实现。
5. CPython `0xC0000005` 仅记录可观测和恢复边界，不声明根因已解决。
6. 当前文档入口收敛到 `docs/README.md`，旧交接和旧 ADR 保留历史并添加替代标识。

## 指定过期模式复核

| 模式 | 复核结果 | 分类 |
| --- | --- | --- |
| `Draft PR #77/#78/#79`、`PR #78 继续复核` | 当前事实源已无此类状态；本文清单中的命中只记录“审计前为何需要更新” | 正确审计引用 |
| `a095ce2e` | PR #69 merge / ARCH-2A 历史核对基线；当前事实源明确标为历史 | 正确历史引用 |
| `a00a2fd` | PR #78 的真实 merge commit | 正确当前引用 |
| `73a645f2` | 仅保留在已标记 superseded 的交接/计划或 U-2 历史记录 | 正确历史引用 |
| Docker、PostgreSQL、Redis、OPS-3B、Linux、Windows Service | 全部以规划或未实现语义出现 | 规划说明 |
| CPython `0xC0000005` | 只描述证据记录与恢复边界，不声明根因已解决 | 当前边界 |
| production migrated / 正式 Release 已发布 | 当前事实源明确否定 | 当前边界 |
| system Python 正式运行 / 复制开发目录部署 | ADR 明确禁止作为正式契约 | 已决策未实施 |

## 仍需后续实现而非文档决策的问题

- 受支持的新 Python 目标版本由 ENV-1B2 兼容验证决定。
- current-release.json、路径 adapter、static 构建器和正式自检尚未实现。
- Manifest v2、DATA-1、restore rehearsal 和 OPS-3B 尚未实现。
- 这些是已明确的后续实现门禁，不是无法确认的文档事实。
