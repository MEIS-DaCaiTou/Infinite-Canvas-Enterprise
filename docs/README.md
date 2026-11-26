# Infinite Canvas Enterprise 文档索引

更新时间：2026-11-25

2026-11-25 后续工作 MKT-02：官网公开多尺寸模块、独立面板／个人预设、原任务与两种尺寸复杂服装真实补验见[同一集成记录](./ops/PRODUCT-INTEGRATION-FIXES-2026-10-13.md#mkt-02)。真实调用按要求暂用贞贞，追加 3 元授权后累计 13 元；拆层遮挡仍未通过。动态状态只见 CURRENT，MKT-01.D／MKT-02.D 与 MKT-03–07 顺序只见[唯一路线图](./roadmap/DEVELOPMENT-ROADMAP-2026-2027.md#marketing-node-batches)，无新增任务文档。

2026-11-25 当前业务工作 MKT-01：营销图层分离的官网依据、原页面／真实鼠标、复杂服装双渠道回执及质量缺口统一登记到[原产品集成记录](./ops/PRODUCT-INTEGRATION-FIXES-2026-10-13.md#mkt-01)。贞贞参数差异与方舟欠费分别记录；本地实现不等于同等效果认可或正式发行。后续 MKT-01.D 和其余六项只见[唯一路线图](./roadmap/DEVELOPMENT-ROADMAP-2026-2027.md#marketing-node-batches)。

2026-11-24 后续范围 SUP-04.S55：已批准 Seedream 5.5 方舟官方／贞贞双渠道和方舟图片调用模块化。当前本地实现、协议／权限／原任务归档、真实账号上限拒绝与浏览器待验收项见[同一产品集成记录](./ops/PRODUCT-INTEGRATION-FIXES-2026-10-13.md#sup-04-s55)；下一任务只在唯一路线图 S55 与 MKT-01–07 登记，其他供应商仍待定。源码、正式发行、生产部署分开。

2026-11-24 最新范围：贞贞固定供应商选择与独立模块按 SUP-03.Z 本地验收收口，其他供应商待定且不阻塞。设置、中英文／主题、部门三 Key 与原任务／Alpha 的证据以及供应商质量／容量边界见[原产品集成记录](./ops/PRODUCT-INTEGRATION-FIXES-2026-10-13.md#sup-03-z)；下一业务任务仍只见唯一路线图。

2026-11-24 SUP-03.3.R 的 Responses 原任务受理／恢复修复与协议迁移见[原产品集成记录](./ops/PRODUCT-INTEGRATION-FIXES-2026-10-13.md#sup-03-3-responses)。动态进展、职责和下一步仍分别见 CURRENT、架构／ADR 和唯一路线图，没有新增独立报告或任务清单。

2026-11-23 SUP-03.2 已将标准 Images／Agnes JSON 请求和编辑文件作用域从大型入口迁出；原页面、旧画布、权限、原任务续查及结果归档证据继续写入[同一产品集成记录](./ops/PRODUCT-INTEGRATION-FIXES-2026-10-13.md#sup-03-2)。当前状态、架构、工作编号和剩余路径沿用下方唯一入口，不另建重构任务清单。

2026-11-23 SUP-02 按负责人最新指令撤销 API 限流，保留素材、原页面和恢复修复；部门多密钥／多供应商容量方案先沟通。当前职责、批次及验收已同步原架构／ADR／路线图，[更正记录](./ops/PRODUCT-INTEGRATION-FIXES-2026-10-13.md#sup-02-no-throttle)明确此前低并发演练已撤回，不作为当前事实。

2026-11-21 SUP-01 的本地参数实现和原页面验证已记入[原产品集成记录](./ops/PRODUCT-INTEGRATION-FIXES-2026-10-13.md#sup-01)。动态状态继续见 CURRENT，后续批次继续见唯一路线图；没有新增报告或第二份任务清单。

2026-11-20 新增[供应商适配 ADR](./decisions/ADR-PROVIDER-001-MODEL-COMPATIBILITY-AND-EXECUTION-BOUNDARIES-2026-11.md)，接入原架构、状态、工作流和[唯一路线图 4.2.1](./roadmap/DEVELOPMENT-ROADMAP-2026-2027.md#provider-compatibility-batches)。职责与契约、批次顺序、实际验证分别沿用对应事实源。

2026-10-31维护范围：受管152份Markdown/文本资料完成角色登记与规则扫描，现行入口按当前候选和GitHub状态修订；历史/evidence/法律资源不改成当前事实。文档/PR清理的逐项原因、范围与未验证项集中在[原审查记录](./ops/DOC-3-DOCUMENT-SYSTEM-AUDIT-2026-10.md#2026-10-31-开发前状态清理与pr盘点)，不新增状态副本。

维护责任：产品负责人维护范围决定/现场反馈；开发者维护本次实现对应的状态、架构、接口/配置和Wiki；发行负责人维护准确版本/PR/CI/Release和升级范围；评审者核对依据及文档检查。历史记录保留作者时点，冻结证据/许可证不可随进度重写。受管资料角色以登记表为准。


本文是唯一导航入口。[文档登记表](./document-register.json) 列出受管理 Markdown／文本资料的角色；[审查记录](./ops/DOC-3-DOCUMENT-SYSTEM-AUDIT-2026-10.md) 记录历次整改范围及限制。main、开发候选、正式发行和现场反馈分别标注；文档数量不等于现行规则数量。

## 1. 每个问题只有一个事实源

| 需要回答 | 唯一入口 | 使用边界 |
| --- | --- | --- |
| 到哪里了：本地/PR/主线/发布/现场 | [当前项目状态](./CURRENT_PROJECT_STATUS.md) | 带核验日期的快照，不外推生产批准 |
| 现在如何运行、模块与数据在哪里 | [当前架构](../ARCHITECTURE.md) | 当前实现与目标明确分开 |
| 接下来按什么顺序开发 | [开发路线图](./roadmap/DEVELOPMENT-ROADMAP-2026-2027.md) | 唯一任务顺序和阶段验收 |
| 产品需求与范围是什么、哪些仍待确认 | [范围锁定与需求基线](../PROJECT_SCOPE_LOCK.md) | 唯一需求入口；下属追踪表/契约草案不另立路线图 |
| 长期产品原则 | [项目章程](../PROJECT_CHARTER.md) | 章程不复制详细需求或任务队列 |
| 完整安装、更新、恢复如何设计 | [ADR-DELIVERY-001](./decisions/ADR-DELIVERY-001-UNIFIED-INSTALL-UPDATE-LIFECYCLE-2026-10.md) | 已认可设计；实现状态回到项目状态 |
| 供应商能力与执行边界如何设计 | [ADR-PROVIDER-001](./decisions/ADR-PROVIDER-001-MODEL-COMPATIBILITY-AND-EXECUTION-BOUNDARIES-2026-11.md) | 标明提议、批准与已有实现；批次只见路线图 |
| 哪些代码/数据能改 | [代码边界](../CODE_BOUNDARIES.md) | 修改、临时产物与数据保护规范 |
| 怎样开发、验证和汇报 | [开发工作流](../CODEX_WORKFLOW.md) / [测试说明](../enterprise/tests/README.md) | 流程 / 执行命令，优先定向验证 |
| 安全要求 | [安全基线](../SECURITY_BASELINE.md) | 不以页面按钮或安装确认代替授权 |
| 查源码与接口 | [Code Wiki](./code-wiki/README.md) | 代码参考，不是第二份状态表/路线图 |

根目录 [README](../README.md) 是项目入口，[ENTERPRISE_DOCS](../ENTERPRISE_DOCS.md) 是快速开发指南；两者链接事实源，不复制整份状态和规划。

贡献与反馈导航见 [CONTRIBUTING](../CONTRIBUTING.md)，开发规则仍以本索引列出的权威文档为准。

## 2. 分层与读法

- **权威文件**：按上表回答各自问题；固定 SHA 只代表核验时点。
- **决策**：`docs/decisions/` 保存原则、原因与替代关系。Accepted 表示决定有效，不能当作实现或部署完成。
- **代码/操作参考**：Code Wiki、测试说明、集成工具 README 等；运行命令要说明源码、旧安装或已交付产品模式，不能混用。
- **实施记录**：`docs/security/`、`docs/data/`、`docs/ops/`、`docs/env/` 的历史 PR、测试和故障记录。文中的“当前/下一步/未合并”只属于记录时点。
- **冻结证据**：`docs/env/evidence/` 的原始验收结果，不能为美化进度改写结果、SHA 或限制。
- **历史方案/来源**：旧蓝图、旧路线、旧上游运行教程。顶部标注替代入口；不再控制现行任务。
- **产品/法律资源**：许可证、依赖声明、vendor 清单和运行时提示词。它们不是规划文档，不能当“无效文档”删除。

场景 Runbook 只在满足其前提、具有明确授权时使用。旧 CLI 激活手册不是普通客户的安装或升级流程；不执行未知结构上的命令。

历史收口依据（2026-10-09）：[开发基线对齐记录](./ops/DEVELOPMENT-BASELINE-CLOSEOUT-2026-10-09.md)、[10.1 固定发行记录](./ops/MAINTENANCE-2026.10.1-RELEASE-RECORD.md)、[主线生命周期诊断实施](./ops/RUNTIME-UPDATE-LIFECYCLE-2026-10-09.md)。它们是有时点的证据/运维参考，不是第二份状态表，也不授权执行旧现场任务书。

## 3. 决定与历史的读法

- 现行范围、架构与顺序分别只看[范围](../PROJECT_SCOPE_LOCK.md)、[架构](../ARCHITECTURE.md)和[路线图](./roadmap/DEVELOPMENT-ROADMAP-2026-2027.md)；资产与客户端方向集中在[架构 7.7](../ARCHITECTURE.md#77-资产与跨客户端演进方向2026-10-31目标设计)，不等于已交付。
- [需求决策登记](./decisions/REQUIREMENTS-DECISION-REGISTER.md)、[统一交付 ADR](./decisions/ADR-DELIVERY-001-UNIFIED-INSTALL-UPDATE-LIFECYCLE-2026-10.md)及其他 ADR 保留决定和适用边界；[追踪规则](./requirements/TRACEABILITY-CONTRACT.md)与[N37 草案](./requirements/N37-ASSET-INTEROP-CONTRACT-DRAFT.md)不是第二条路线。
- 旧路线、蓝图、交接与发行记录保留为历史证据；当前状态以[状态入口](./CURRENT_PROJECT_STATUS.md)及实时仓库核验为准，不将旧时点待办直接派工。

## 4. 原有重复入口与分支差异

主线已经删除 `AGENT_CONTEXT.md`、`HANDOVER.md`、`PROJECT_HANDOFF_FOR_NEW_AGENT.md`、`DEVELOPMENT_PLAN.md`、`docs/upstream/README.upstream.md` 等旧交接入口，可从 Git 历史审计。**这是主线事实，不表示所有维护分支都已删除。**

客户维护线仍有文档差异；回归主线时采用本索引与登记表，不把旧队列原样复活，也不把主线新记录丢弃。保留有价值的实施证据并分类，不能将原始历史文档伪装成当前规划。

## 5. 后续维护规范

维护责任按职责划分，不预设具体个人：产品负责人确认范围、现场反馈与业务取舍；负责相应改动的开发者同步状态/架构/接口/配置与 Code Wiki，核对源码、准确版本和文档登记；发行负责人维护发行记录及升级适用范围；评审者核对证据和文档检查结果。角色可由同一人承担，但状态、批准和验收不能互相代替。历史记录作者保留原时点，后续修正附带日期、来源和适用范围，不重写冻结证据。

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
python -B tools/check_docs.py
python -B -m unittest discover -s enterprise/tests -p test_documentation_contract.py
```

上例使用已确认的开发解释器；当前业务开发与CI基线为 CPython 3.14.6，文档检查仅需标准库，也可用可用的其他兼容解释器。不把商店别名空输出当成功。检查不启动/停止服务或访问客户数据。其完整范围见 [审查记录](./ops/DOC-3-DOCUMENT-SYSTEM-AUDIT-2026-10.md)。
