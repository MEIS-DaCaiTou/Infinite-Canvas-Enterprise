# Infinite Canvas Enterprise 当前项目状态

更新时间：2026-10-11
核验对象：GitHub 主线、相关 PR/CI、正式 Release、开发机固定 EXE 合成演练，以及负责人此前提供的两台设备升级结果和生产诊断包。没有连接或操作生产设备；客户运行状态仍以既有采集时点为准。

## 1. 开发基线、发行与现场必须分开

| 层级 | 本次事实 | 不能据此声称 |
| --- | --- | --- |
| 主线核验基点 | `main@1d8dd4902aa3297a274f2e13b2e333e75d34a1c3`；#137–#142、#146–#150 以及缓存清理 [#151](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/151)、保留数据卸载/同版重装 [#152](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/152) 已合并；专业服务器及 500+/200+ 约束随 #152 入主线 | 主线全部能力已随 10.1 正式交付；长期设计约束已经实施 |
| 新 main CI | 上述准确 main 的 [Enterprise/Runtime](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/38136292887)、[固定 EXE](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/38136292912)、[文档](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/38136292885) 共四项常规检查 SUCCESS；真实固定 EXE opt-in 为 SKIPPED | 用 PR CI 替代 main CI；把跳过门禁或静默卸载写成完整 GUI 验收 |
| 开发基线收口 | #146 选择性接回 10.1 同源页面提示和数据库 v2 迁移/构建契约，保留主线安全治理、任务回执、原生入口和恢复保护；准确整合范围与验证见 [收口记录](./ops/DEVELOPMENT-BASELINE-CLOSEOUT-2026-10-09.md) | 整条维护分支已合并；任意历史安装已受支持 |
| 主线诊断/恢复增量 | #147、#148 已合并。#148 工作包 B 完成精确 Job/READY、源进程 lease、接受竞争和超时恢复保护；310 项关联回归通过。代码 `6002300eff5fd4750f84bfe684b41a739c541120` 的本机固定 EXE 合成三门禁通过、测试进程/端口清理确认；准确最终 Head `fd8303337ea22bab91d4d1eb84606dcaa410f4ca` 三项常规 CI 及独立审查通过，2026-10-10 合并；[实施与验证记录](./ops/RUNTIME-UPDATE-LIFECYCLE-2026-10-09.md) | 已进入正式 10.1、所有安装副本或客户环境已验收、现场旧失败根因已确定 |
| 正式 Release | [v2026.10.1](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/releases/tag/v2026.10.1)，Latest、非预发布；`ice-2026.10.1-bf1143a7bc54`，提交 `bf1143a7bc54ac24d53b9e7d7db5a9b50da8b57c`，2026-10-08 发布 | 将该不可变包覆盖为新的 main 源码 |
| 生产单设备 | 负责人在固定 EXE 停止/重新启动 09.9 后，通过更新中心升级成功；导出日志确认 2026-10-09 北京时间 01:46:41 作业成功、目标 10.1、01:49 时 Runtime healthy | 所有设备都可升级、历史崩溃彻底解决或零停机 |
| 测试单设备 | 负责人确认固定 EXE 启动 09.9 并运行一段时间后，更新中心升级 10.1 成功；截图显示正确超管标签 | 等同于生产全量数据和持续运行验收 |
| 10.2 诊断候选 | [PR #145](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/145) OPEN/Draft，基于维护线；提交 `83e18c44357ec491dced0d6ba70bc4e691e420e1` | 已合并 main、正式发布或修复了现场失败根因 |
| 开发版本标记 | 收口基点的 `VERSION=2026.08.5` 是历史源码标记，未在本任务伪造为 10.1/10.2；后续发行单独确定版本及准确 commit/tree/Manifest | 可把当前开发源码当作该标记对应的客户旧包构建交付 |

后续通用开发以 main 为唯一来源；维护线的已发布 refs/资产只作不可变发行来源及历史兼容证据。新版本构建、路由、发布与生产升级分别授权，不因本轮收口自动发生。

## 2. 已合并主线的主要能力

| 工作 | 证据 | 范围 |
| --- | --- | --- |
| Runtime 可靠性 | [#108](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/108) | liveness/readiness、降级/退避、进程所有权、阻塞隔离和画布任务回执基础 |
| 浏览器与路由安全 | [#119](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/119)，#111 CLOSED | 未知请求/事件拒绝、同源写入、登录限流和静态/跳转/Cookie 边界 |
| 数据迁移与恢复 | [#120](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/120)、[#121](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/121)、[#130](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/130) | Manifest 绑定的备份、前向迁移、数据库/指针恢复和旧库登记；不明状态阻断 |
| 更新与恢复体验 | #124–#127、#129、#131 | 故障演练、恢复核验/审计解除阻断、一次确认进度、正式/开发通道及准确路径检查；不是自动多跳 |
| 固定入口与安装 | #137–#140 | 文档体系、固定 C# 入口、实例身份、新装与入口修复、安装副本/真实 EXE 启停验证 |
| 同版程序修复与图形维护 | [#141](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/141)、[#142](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/142) | 同 Release 程序/Python 修复、中断恢复、持久阶段及 v4 图形接线；不升级业务、不接管未知安装 |
| 安装维护 C2/C3 | [#151](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/151)、[#152](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/152) | 显式归属缓存清理、实例标准卸载、保留数据与程序恢复副本、同版重装和中断恢复；卸载确认按钮点击仍未验收 |

历史记录的“未合并”只代表记录时点。#142 于 10-05 合并为 `a54bdbec348c49fa9eed12cac0bf861241ef5c0b`；真实副本/入口验证及 GUI 限制仍见 [DELIVERY-1](./ops/DELIVERY-1-FIXED-NATIVE-ENTRY-2026-10.md)，不能以源码接线冒充客户图形操作验收。

## 3. 10.1 发布与生产反馈

固定资产、兼容源和验证限制见 [10.1 发布记录](./ops/MAINTENANCE-2026.10.1-RELEASE-RECORD.md)。09.9 保留为历史正式源，不再写成最新正式发行。

- 两次早期生产更新失败后均恢复健康 09.9；失败生命周期缺少 stage/errno 等字段，原采集标为 `not_recorded`。成功后的数据不能用旧失败备份覆盖。
- 本次生产成功作业 `c9d8f14994de4074b7529e88cc20b7d2`：准确源 `ice-2026.09.9-54f9e67d1643` → 目标 `ice-2026.10.1-bf1143a7bc54`，结果 `SYSTEM_UPDATE_SUCCEEDED`；约 68 秒。
- 导出快照确认实际 10.1 Runtime、Gateway/Upstream HTTP 200 和重启计数 0；页面显示 12 个用户、Aidan02 为超级管理员。原密码与治理身份此前已核验，不重新初始化账号。
- 相同维护版本在 EXE 重建启动上下文后成功，说明 10.1 不是普遍无法启动；但尚未证明早前失败根因就是启动上下文，不能将相关性当因果。
- 成功切换仍记录 `graceful_timeout` 后的拥有者清理，`supervisor_exit_confirmed=false`。这不是“完全优雅退出”的证据。
- 导出含空正文 `Broadcast error:` 与图片比例不受支持的 Provider 500；这些 stdout 条目没有各自时间，不能断言都是升级后的问题或服务崩溃。不得自动重提付费任务。
- EXE 诊断包只有 `worker_exit_code=0` 等摘要，不足以证明完整启动/恢复链路。
- 09.9 上线时的 15 分钟备份、原每分钟监控至 10-12 15:49 已有现场成功反馈，依赖账号登录；本次 10.1 导出未含这些调度实际成功记录，升级后的接续状态仍待对应记录确认，不写成已重新验证。

## 4. 历史兼容与通用工具

[PR #136](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/136) 仍 OPEN/Draft、基于维护分支；工具预发布 [2026.09.9-unified-upgrader.1](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/releases/tag/2026.09.9-unified-upgrader.1) 固定目标 09.9，不是后续所有版本自动升级器。

历史目录登记 08.1–08.4、09.4–09.9（09.7 为开发），涉及精确 18 对象源及已激活安全治理的 28 对象变体，09.9/10.1 为 30 对象、schema v2。数量不是兼容身份；完整 DDL、登记/审计、源码/Manifest/运行环境和未完成恢复均需核验。28 对象特定桥接及历史目录继续留在冻结维护来源，不因本轮通用 v2 基础收敛默认开放普通更新中心路径。

未知 TEST 加修复部署曾需单独接管；该现场任务不是通用安装支持范围。不支持旧 TEST 与新版同时写同一库，亦未实现新旧双向同步或业务写入后任意无损降级。

## 5. 当前阶段与下一步边界

当前仍是 **阶段 3：统一安装与在线升级体验收敛**，顺序只在 [路线图](./roadmap/DEVELOPMENT-ROADMAP-2026-2027.md) 维护。

1. 基线已由 #146 收口，诊断/恢复增量 #147/#148 已合并，需求基线 #149 已入档且不授权新业务代码。#148 的早前完整演练失败及受限 Job 停机前阻断证据保留；同一工作包已补齐交接/接受/清理保护，并在开发机普通桌面上下文通过固定 EXE、HTTP 授权、成功升级、自动恢复及持续失败安全阻断三项合成门禁。安装维护 C 的入口持久恢复、缓存清理及同版卸载/重装已由 #150–#152 合入主线，现继续阶段 3 剩余工程能力。不自动发行；不能将开发机复现直接认定为旧现场唯一根因。
2. 同版入口修复 v2 的 #150 已合并；本机 9 场景、准确源码与限制见 [入口恢复记录](./ops/ENTRY-REPAIR-RECOVERY-2026-10-10.md)。C2 [维护准备包安全清理](./ops/MAINTENANCE-CACHE-LIFECYCLE-2026-10-11.md) 的准确 Head `e1aca8a2acc6f99029e0be2404f1e9e10ec70d78` 经独立技术审查后，以 #151 合并为 `bdace2a35e10e07c268d0ca7eaf6050f2411d5ad`。四项常规 PR CI 成功，opt-in 为 SKIPPED；已有本机完整准备包 4 场景及限定 GUI 证据复用，没有重跑该包全套门禁。
3. C3 [保留数据卸载/重装](./ops/RETAINED-UNINSTALL-REINSTALL-2026-10-11.md) 的 #152 已调整到 main 基线，经独立技术审查后合并为上述新 main。当前用户/实例的标准 Windows 卸载、同卷程序恢复副本、保留原数据/配置/身份/指针的同 Release 重装及持久 fence/显式恢复进入主线。关联回归 211 passed / 1 skipped、完整副本三场景、最终候选两次一致构建、真实登记卸载器静默退出 0、GUI 同版重装等证据继续复用。**标准卸载确认按钮点击仍未验收**，不把静默执行改写为完整 GUI 验收；跨版本重装、旧 v1/未知锁接管、长期容量治理及完整安装维护 GUI 仍待完成。代码合并未发布新 Release，未授权客户/生产操作。
4. 当前按唯一路线图 3.3 推进完整 C4 [发布目录分页、完整性和安全缓存](./ops/UPDATE-CATALOG-PAGINATION-2026-10-11.md)，从上述新 main 的独立工作区开发，覆盖共用 v1/v2 目录、条件核验、失败阻断、API 和实际更新页面。main 核验点仍为最近 50 Release，C4 分支将目录扩为最多 1000 条、每次全页核验；最多 8 跳仍只是规划上限，没有一次授权自动多跳。更新器自身更新与完整业务维护态仍待落实，正式版不强制经过开发版。
5. [#123](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/123) 付费提交止损仍 OPEN；回执基础不是统一持久任务、费用账本、预算及对账。
6. SQLite＋文件/JSON 的 Windows 单机/LAN 仍是当前部署；专业企业服务器和云服务器生产部署、500 名以上员工/200 名以上峰值活跃创作是已确认长期约束，见 [需求决策登记](./decisions/REQUIREMENTS-DECISION-REGISTER.md#6-2026-10-11-专业服务器与云端生产部署定位补充)。Linux/容器/云端支持、PostgreSQL、完整资源 CAS/员工桌面、SSO/Agent 委托、远程采集与长期支持政策未交付。不以部门 Owner 宣称跨企业 SaaS 隔离，不以账号数推算容量。
7. 没有付费签名或独立干净设备前置预算；未签名风险仍披露。代码/文档收口不修改这些产品边界。

## 6. 本轮证据来源与限制

- 2026-10-09 定向 GitHub CLI/API 核验 main、#123/#136/#142–#147 和 v2026.10.1；#147 Head `222b2dfd8adc2c1237ff8d38cddd3093640139ba` 的三个 CI 检查通过，按准确 Head 合并为 `a5a6aa10b7882c46f129ec6df854239ee111da18`。明确使用企业仓库，避免本地 gh 默认指向历史 upstream。
- 负责人提供的生产 `update-diagnostics.zip`、`canvas-native-20261009-015017.zip` 已作本地只读核验；文件 SHA、采集时间与摘录边界见收口记录。不提交原始客户日志、数据库、密钥或业务材料。
- 本轮开发定向测试和隔离浏览器验证只证明受影响源码契约；没有真实生产启停、付费模型调用、Release 发布或资产替换。
- 历史数据/安装/Runtime 与 GUI 验收证据继续在对应实施记录保存；文档检查不能证明生产稳定性。
- 2026-10-10 定向重新核验 main、#123/#136/#145/#149 和 Latest Release；三个历史候选仍 OPEN，Latest 仍 v2026.10.1。随后 #148 精确最终 Head 的常规 CI、独立审查通过，合并点为 `d95e256f068a014064f299a3655f2c1758f7b3cd`。未发布 Release、未操作生产；工作包 C 的分支证据与合并/发行结果分列。
- 2026-10-11 核对 #151/#152 的独立技术审查 COMMENT、main 合并 commit 及新 main 四项常规 CI 最终 SUCCESS；本地 main 非强制快进到 `1d8dd490`，原目录历史分支和其他工作区未提交修改保留。C4 工程证据见其记录，不重复验证 C2/C3 已充分证明且未修改的安装链路。
