# Infinite Canvas Enterprise 文档索引

更新时间：2026-09-21

本文是仓库文档的唯一导航入口。文档必须区分：动态 `origin/main`、未合并分支、GitHub Release、单台客户设备现场结果和通用生产批准；这些状态不能合并表述。

## 1. 先读什么

| 顺序 | 文档 | 只负责回答 |
| --- | --- | --- |
| 1 | [当前项目状态](./CURRENT_PROJECT_STATUS.md) | 已实现、分支中、已发布、现场验证和未实现分别是什么 |
| 2 | [当前架构](../ARCHITECTURE.md) | 当前运行拓扑、数据边界和架构限制 |
| 3 | [开发路线图](./roadmap/DEVELOPMENT-ROADMAP-2026-2027.md) | 后续任务顺序、依赖和阶段验收条件 |
| 4 | [代码边界](../CODE_BOUNDARIES.md) | 哪些位置可以修改、哪些数据不得提交 |
| 5 | [Code Wiki](./code-wiki/README.md) | 模块、关键类/函数、依赖、运行和测试导航 |
| 6 | [测试说明](../enterprise/tests/README.md) | 可执行验证入口与破坏性边界 |

根目录 [README](../README.md) 面向项目入口，[CODEX_WORKFLOW](../CODEX_WORKFLOW.md) 面向开发流程，[ENTERPRISE_DOCS](../ENTERPRISE_DOCS.md) 是企业层快速开发指南；三者不得复制完整当前状态或另建路线图。

## 2. 固定实施顺序

唯一有效的产品演进顺序是：

> 安全修复 → 数据升级能力 → 在线升级体验 → 部门与任务 → 资源缓存与桌面壳 → PostgreSQL 及高可用 → 企业集成

这条顺序的核心原因是：所有新增业务表、部门账本、任务记录和缓存元数据，都必须先具备可验证、可恢复、可回滚的数据库升级路径，才能安全交付给现有客户。其它文档不得另设相互竞争的阶段编号或开发路线。

## 3. 文档分层

### A. 当前事实源

- [CURRENT_PROJECT_STATUS.md](./CURRENT_PROJECT_STATUS.md)
- [ARCHITECTURE.md](../ARCHITECTURE.md)
- [DEVELOPMENT-ROADMAP-2026-2027.md](./roadmap/DEVELOPMENT-ROADMAP-2026-2027.md)
- [PROJECT_SCOPE_LOCK.md](../PROJECT_SCOPE_LOCK.md)
- [CODE_BOUNDARIES.md](../CODE_BOUNDARIES.md)
- [SECURITY_BASELINE.md](../SECURITY_BASELINE.md)

只有这些文件可以陈述“当前是什么”和“下一步做什么”。固定 SHA 只代表记录时点，不得被解释为永久当前值。

### B. 决策记录

`docs/decisions/` 保存不可轻易回退的架构与运维决定。ADR 的 `Accepted` 只表示决策生效，不表示实现、发布或生产部署已经完成。

当前关键决策包括：

- [模块化单体中期架构](./decisions/ADR-ENV-001-MODULAR-MONOLITH-MIDTERM-ARCHITECTURE-2026-07.md)
- [不可变 Release 与静态资源策略](./decisions/ADR-ENV-003-IMMUTABLE-RELEASE-STATIC-CACHE-2026-07.md)
- [路径根与版本目录](./decisions/ADR-ENV-004-PATH-ROOTS-AND-RELEASE-DIRECTORY-2026-07.md)
- [Manifest v2 与数据库回滚](./decisions/ADR-OPS-006-RELEASE-MANIFEST-V2-DATABASE-ROLLBACK-2026-07.md)
- [超级管理员高风险能力治理](./decisions/ADR-SEC-1A-SUPER-ADMIN-CAPABILITY-GOVERNANCE-2026-07.md)

### C. 实施与验收记录

- `docs/security/`：已经实施或审查的安全工作。
- `docs/data/`：数据库 migration、backup、restore 基础。
- `docs/ops/`：Release、Runtime、更新、安装和现场收敛记录。
- `docs/env/`：可复现 Runtime、路径根、入口和环境验证。
- `docs/env/evidence/`：只读验收证据，不作为当前任务入口。
- `docs/runbooks/`：明确场景下的操作手册。

记录型文档保留历史原貌；如果结论被替代，在顶部写明替代文档，不在正文中悄悄改写历史。

### D. 历史来源材料

`docs/upstream/` 只记录项目历史来源及 2026 年 7 月已经完成的受控同步。来源代码已冻结为历史基线，项目后续独立演进；该目录不得再被当作当前同步计划或开发门禁。

## 4. 已清理的旧入口

以下根目录文档曾包含 2026 年 6–7 月的状态、旧上游同步约束和重复任务队列，现已从工作树删除；需要审计时可从 Git 历史读取：

- `AGENT_CONTEXT.md`
- `HANDOVER.md`
- `PROJECT_HANDOFF_FOR_NEW_AGENT.md`
- `DEVELOPMENT_PLAN.md`
- `docs/upstream/README.upstream.md`

删除这些文件不会删除实现或验收证据；它只取消过时文档作为开发入口的资格。

## 5. 维护规则

1. 实现 PR 必须同步更新 `CURRENT_PROJECT_STATUS`、路线图对应阶段和测试说明。
2. 规划内容使用“计划/未实现”，不能使用完成时态。
3. 文档中的 Git 状态必须注明核验日期、分支/PR/Release 身份。
4. 客户现场结果必须注明适用设备和版本，不能外推为所有环境。
5. 不再新增 Agent 交接包、重复开发计划或根目录状态日志；统一更新本索引指向的事实源。
6. 不在文档中保存 secret、真实令牌、客户数据、本机运行目录或临时诊断内容。
7. 项目负责人已取消独立 Windows 主机验收门禁；CI 限制、未覆盖场景和人工验证仍须准确披露。
8. 上游来源归属和许可证继续保留，但“持续同步上游”不再是产品约束。
