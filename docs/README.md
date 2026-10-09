# Infinite Canvas Enterprise 文档索引

更新时间：2026-10-09

本文是唯一导航入口。[文档登记表](./document-register.json) 列出仓库全部受管理 Markdown／文本资料的角色；[本轮审查](./ops/DOC-3-DOCUMENT-SYSTEM-AUDIT-2026-10.md) 记录整改依据。文档数量不等于现行规则数量。

## 1. 每个问题只有一个事实源

| 需要回答 | 唯一入口 | 使用边界 |
| --- | --- | --- |
| 到哪里了：本地/PR/主线/发布/现场 | [当前项目状态](./CURRENT_PROJECT_STATUS.md) | 带核验日期的快照，不外推生产批准 |
| 现在如何运行、模块与数据在哪里 | [当前架构](../ARCHITECTURE.md) | 当前实现与目标明确分开 |
| 接下来按什么顺序开发 | [开发路线图](./roadmap/DEVELOPMENT-ROADMAP-2026-2027.md) | 唯一任务顺序和阶段验收 |
| 产品包含什么、不包含什么 | [范围锁定](../PROJECT_SCOPE_LOCK.md) / [项目章程](../PROJECT_CHARTER.md) | 产品边界 / 长期原则，不另建任务队列 |
| 完整安装、更新、恢复如何设计 | [ADR-DELIVERY-001](./decisions/ADR-DELIVERY-001-UNIFIED-INSTALL-UPDATE-LIFECYCLE-2026-10.md) | 已认可设计；实现状态回到项目状态 |
| 哪些代码/数据能改 | [代码边界](../CODE_BOUNDARIES.md) | 修改、临时产物与数据保护规范 |
| 怎样开发、验证和汇报 | [开发工作流](../CODEX_WORKFLOW.md) / [测试说明](../enterprise/tests/README.md) | 流程 / 执行命令，优先定向验证 |
| 安全要求 | [安全基线](../SECURITY_BASELINE.md) | 不以页面按钮或安装确认代替授权 |
| 查源码与接口 | [Code Wiki](./code-wiki/README.md) | 代码参考，不是第二份状态表/路线图 |

根目录 [README](../README.md) 是项目入口，[ENTERPRISE_DOCS](../ENTERPRISE_DOCS.md) 是快速开发指南；两者链接事实源，不复制整份状态和规划。

## 2. 分层与读法

- **权威文件**：按上表回答各自问题；固定 SHA 只代表核验时点。
- **决策**：`docs/decisions/` 保存原则、原因与替代关系。Accepted 表示决定有效，不能当作实现或部署完成。
- **代码/操作参考**：Code Wiki、测试说明、集成工具 README 等；运行命令要说明源码、旧安装或已交付产品模式，不能混用。
- **实施记录**：`docs/security/`、`docs/data/`、`docs/ops/`、`docs/env/` 的历史 PR、测试和故障记录。文中的“当前/下一步/未合并”只属于记录时点。
- **冻结证据**：`docs/env/evidence/` 的原始验收结果，不能为美化进度改写结果、SHA 或限制。
- **历史方案/来源**：旧蓝图、旧路线、旧上游运行教程。顶部标注替代入口；不再控制现行任务。
- **产品/法律资源**：许可证、依赖声明、vendor 清单和运行时提示词。它们不是规划文档，不能当“无效文档”删除。

场景 Runbook 只在满足其前提、具有明确授权时使用。旧 CLI 激活手册不是普通客户的安装或升级流程；不执行未知结构上的命令。

本轮收口依据：[开发基线对齐记录](./ops/DEVELOPMENT-BASELINE-CLOSEOUT-2026-10-09.md)、[10.1 固定发行记录](./ops/MAINTENANCE-2026.10.1-RELEASE-RECORD.md)、[主线生命周期诊断实施](./ops/RUNTIME-UPDATE-LIFECYCLE-2026-10-09.md)。它们是有时点的证据/运维参考，不是第二份状态表，也不授权执行旧现场任务书。

## 3. 当前关键决定

- [统一产品/安装/更新生命周期](./decisions/ADR-DELIVERY-001-UNIFIED-INSTALL-UPDATE-LIFECYCLE-2026-10.md)：长期保留 SQLite 单机；团队服务端目标 PostgreSQL；员工客户端本地缓存；共用更新引擎和稳定入口。
- [模块化单体](./decisions/ADR-ENV-001-MODULAR-MONOLITH-MIDTERM-ARCHITECTURE-2026-07.md)、[不可变程序版本](./decisions/ADR-ENV-003-IMMUTABLE-RELEASE-STATIC-CACHE-2026-07.md)、[路径根](./decisions/ADR-ENV-004-PATH-ROOTS-AND-RELEASE-DIRECTORY-2026-07.md)、[Manifest/恢复](./decisions/ADR-OPS-006-RELEASE-MANIFEST-V2-DATABASE-ROLLBACK-2026-07.md)、[高风险权限治理](./decisions/ADR-SEC-1A-SUPER-ADMIN-CAPABILITY-GOVERNANCE-2026-07.md) 继续提供相应约束；文内实施状态是历史快照。
- [旧 Greenfield-only 决策](./decisions/ADR-OPS-007-GREENFIELD-PRODUCTION-BASELINE-AND-LEGACY-NON-MIGRATION-2026-07.md) 的产品范围已被统一交付 ADR 替代，不再拒绝所有旧客户迁移。
- [旧运维路线](./ops/OPS-ROADMAP-2026-07.md) 和 [旧企业蓝图](./architecture/ENTERPRISE-ARCHITECTURE-BLUEPRINT-2026-07.md) 仅作历史材料；当前顺序只认唯一路线图。

## 4. 原有重复入口与分支差异

主线已经删除 `AGENT_CONTEXT.md`、`HANDOVER.md`、`PROJECT_HANDOFF_FOR_NEW_AGENT.md`、`DEVELOPMENT_PLAN.md`、`docs/upstream/README.upstream.md` 等旧交接入口，可从 Git 历史审计。**这是主线事实，不表示所有维护分支都已删除。**

客户维护线仍有文档差异；回归主线时采用本索引与登记表，不把旧队列原样复活，也不把主线新记录丢弃。保留有价值的实施证据并分类，不能将原始历史文档伪装成当前规划。

## 5. 后续维护规范

1. 一次任务只更新受影响事实源；只有阶段/测试入口改变时才改对应路线图/测试说明，避免纯拼写修改也扩散成全仓更新。
2. 实现 PR 记录准确 Base/Head、通道、兼容、升级/恢复和验证范围；main、维护分支、Release、客户单设备结果分别写。
3. 新增、移动或改名 Markdown／文本资料时同步登记表，说明为何不能复用现有入口。不得增加第二份动态状态、重复路线图或每次会话交接包。
4. ADR 更改原则时写明被替代条款；实施状态更新不改写原始验收结论。冻结证据/法律资源的内容变更需要独立理由和审查。
5. 运行命令不得包含真实凭据或客户数据；测试目录、构建产物、下载与备份不进入文档树或盘符根目录。
6. 每轮完成时报告“已完成、验证证据、剩余风险、下一轮”；不把文档检查当业务运行测试。
7. 以轻量文档检查防止漏登记、断链和重复事实源；不能用它判断全部语义正确、外链可达或客户版本兼容。
8. 不设独立干净 Windows 设备或付费签名预算前置条件；保留已有 CI、定向故障测试与必要现场回归，不无理由重跑 PR 全套门禁。

从仓库根运行：

```powershell
py -3.11 -B tools/check_docs.py
py -3.11 -B -m unittest discover -s enterprise/tests -p test_documentation_contract.py
```

上例用于已有 Python 3.11 的 Windows 开发环境，不是客户安装步骤；其他环境使用已确认的 Python 解释器，不把商店别名空输出当成功。无需安装项目业务依赖，检查只读，不启动/停止服务或访问客户数据。其完整范围见 [审查记录](./ops/DOC-3-DOCUMENT-SYSTEM-AUDIT-2026-10.md)。
