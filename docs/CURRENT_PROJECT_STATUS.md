# Infinite Canvas Enterprise 当前项目状态

更新时间：2026-10-14
核验对象：GitHub main@519b1da0、#157 已合并与 #123/#158 准确候选 Head/最终 CI、正式 v2026.10.1，以及本轮 ComfyUI 修复候选和隔离回环 Browser/HTTP 证据。未发布新 Release 或操作客户部署。

## 1. 开发基线、发行与现场必须分开

| 层级 | 本次事实 | 不能据此声称 |
| --- | --- | --- |
| 主线核验基点 | `main@519b1da0fd859310b104eb4e8e58398cbe83317c`；#137–#142、#146–#157 已合并；#153 发布目录分页与完整性已进入主线；服务器及 500+/200+ 长期约束随 #152 入主线 | #123 或本轮 ComfyUI 候选已合并；主线能力已随正式 10.1 全部交付 |
| 最新 main CI | 准确 519b1da0 的 [Enterprise/Runtime](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/38433978677)、[文档](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/38433978679) 三项检查最终 SUCCESS；真实固定 EXE opt-in SKIPPED；原生检查 38433978817 SUCCESS | 用 PR CI 替代 main CI；跳过门禁等于已验收 |
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
| 安装维护 C2/C3 | [#151](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/151)、[#152](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/152) | 显式归属缓存清理、实例标准卸载、保留数据与程序恢复副本、同版重装和中断恢复；C3 原记录保留当时的 GUI 限制，标准卸载两项确认按钮已在 C6 本机合成来源补验收 |

| 安装维护 C4 | [#153](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/153) | 共用 v1/v2 分页目录、每次全页条件核验、最多 1000 条的完整性边界及失败阻断；连续执行与验证范围由 C7 单独记录 |

### 最新完整工作包的合并与候选状态

以下是 2026-10-14 核验快照；#154/#155/#156 已合并，#123 和本轮 ComfyUI 修复仍分列候选，#157 已合并。合并源码不等于正式 Release 或客户验收。

| 候选 | 准确功能提交与 CI | 实现及限制 |
| --- | --- | --- |
| [#154 C5](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/154)，MERGED | `64c2adff3358e7f806d3cf04a26d86639597e573`；Enterprise/Runtime/文档三项 SUCCESS | 经核验的目标 Python 更新执行器接管、旧来源兼容和失败恢复；完整副本四类证据见 [C5](./ops/VERIFIED-UPDATER-HANDOFF-2026-10-11.md)，不包含原生工具替换和自动多跳 |
| [#155 C6/C7](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/155)，MERGED | `7029e1d1fdda7ecf962cf9e9a4f15cadf5dcc16c`；Enterprise/Runtime/原生 EXE/Setup/文档四项 SUCCESS | 离线升级、保留数据跨版本重装、原生工具及最多 8 跳连续执行/检查点；已合并为 `3e0deeae`，C5 前置已合并为 `11c9a38c`。限定 GUI 已有合成副本证据；在线检查点继续在本机仍被 handoff Job 资格阻断，见 [C6](./ops/OFFLINE-RETAINED-UPGRADE-2026-10-12.md)、[C7](./ops/ONLINE-UPGRADE-SEQUENCE-2026-10-12.md) |
| [#156 产品集成修复](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/156)，MERGED | 功能基点 `4bdd9a16074abac86ce47fc1e81b55bfb12cf63c`；Enterprise/Runtime/文档三项 SUCCESS。最终 Head `5b90391f30e0cfde4e15dd4d4b23c3ca2f5d13f5` 合并为 `e89a288fe`，对应 main 常规 CI 已成功 | 12 个已确认 Zhenzhen JSON 图像模型/别名内置能力与请求构造、个人模型列表、后台操作确认、素材扩展同源接线；范围见 [实现记录](./ops/PRODUCT-INTEGRATION-FIXES-2026-10-13.md) |

| [#123 付费止损与原任务续查](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/123)，OPEN/Draft | Head `5384a2ac9801d69a95264ceeb2626fc3115c946f`；Enterprise/Runtime/文档三项 SUCCESS | 画布保存重开后查询已受理的原图像任务，不重新付费提交；仍待独立审查，不等于统一任务中心/费用账本 |
| [#157 正式 Windows 启动与在线更新](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/157)，MERGED | Head `551f433db51444be2c96dec225b6479b8a854f00`；Enterprise/Runtime/原生 EXE/文档四项 SUCCESS | 现有固定入口正式启动方式的更新交接与失败恢复提示；启动不强制升级，更新需管理员确认；未覆盖 GUI 范围继续保留 |
| [ComfyUI 单图输入修复候选](./ops/COMFY-WORKFLOW-INPUT-REPAIR-2026-10-14.md) | 分支 `codex/comfy-workflow-input-fix-20261013`；定向字段/后端、静态闭包及本机 Browser/HTTP 验证；GitHub 候选 CI 单列 | 纠正 filename_prefix、直接兼容旧配置、两类画布共用映射和准确缺图提醒；受控协议闭环，客户 GPU/自定义节点尚未验证 |

三包均未发布，固定 EXE real gates 的自动 opt-in 为 SKIPPED；已有真实副本证据不因 CI 跳过被抹除，也不因此外推全部客户。

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

当前是 **阶段 3 收口与既有创作阻断修复**，唯一实施顺序见[路线图](./roadmap/DEVELOPMENT-ROADMAP-2026-2027.md)。

1. #146–#153 的主线基础、固定入口、缓存清理、同版保留数据卸载/重装和目录分页已完成合并；C4 不再重复开发或重跑已有充分证据的测试。#148 的失败与最终合成三门禁、C2/C3 的限定证据继续保留。
2. #154/#155 已按负责人授权核查准确 Head 并合并，包含目标执行器、离线/在线连续升级、原生工具和检查点恢复；没有将开发端核查称为新增独立审查。main 的 #155 历史在线交接阻断仍保留原证据；#157 已按一种正式固定入口启动方式完成候选收口及必要恢复提示，独立审查后已合并，不继续扩展任意受限宿主矩阵。合成两跳成功不证明真实整机重启和所有在线续接已通过。
3. GUI 状态按准确来源分列：#152 的历史卸载 Yes 点击仍缺证据；C6 后续合成安装副本已有标准卸载确认和限定跨版本重装 GUI 证据，代码已合入 main。不能把这两者写成全面通过或全部未验证；未知来源、未来 Schema、未列 GUI 和客户设备范围继续保留限制。
4. #156 处理实际使用问题；管理员创建确认在 main 已有表单，旧正式 10.1 与现行主线契约不同。普通管理员不能因此获得创建管理员的权限。长期供应商适配由项目维护，普通用户在节点设置个人模型列表，不承担接口模板配置。真实付费、Chrome 扩展宿主与 PS 企业登录仍未验收。
5. [#123](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/123) 仍 OPEN/Draft，Head `7e6d90b8`；画布回执和局部止损不是统一 Task/Attempt、费用账本、预算及完整查询恢复。按路线图推进，已受理任务不自动重复付费。
6. 当前企业部署为单台 Windows 主机。专业服务器/云、500+/200+ 保留长期架构约束；Linux、容器、PostgreSQL、多实例和容量实施待负责人后续需求，当前只提前保持可复用业务边界。没有整体重构、新 Release 或生产操作授权。
7. 安装维护以已有设备正常迭代、数据保护和必要恢复为目标；按完整工程包交付，减少相关技术债，复用有效测试，不以数量、哈希或额外框架作为成果。

负责人于 2026-10-14 将 ComfyUI 画布无法运行列为当前优先完整工作包：按现有交互解除创作阻断，证据与边界见 [修复记录](./ops/COMFY-WORKFLOW-INPUT-REPAIR-2026-10-14.md)。#123/#157 不夹带合并，随后按唯一路线图推进可靠任务与供应商工作。

## 6. 本轮证据来源与限制

- 2026-10-09 定向 GitHub CLI/API 核验 main、#123/#136/#142–#147 和 v2026.10.1；#147 Head `222b2dfd8adc2c1237ff8d38cddd3093640139ba` 的三个 CI 检查通过，按准确 Head 合并为 `a5a6aa10b7882c46f129ec6df854239ee111da18`。明确使用企业仓库，避免本地 gh 默认指向历史 upstream。
- 负责人提供的生产 `update-diagnostics.zip`、`canvas-native-20261009-015017.zip` 已作本地只读核验；文件 SHA、采集时间与摘录边界见收口记录。不提交原始客户日志、数据库、密钥或业务材料。
- 本轮开发定向测试和隔离浏览器验证只证明受影响源码契约；没有真实生产启停、付费模型调用、Release 发布或资产替换。
- 历史数据/安装/Runtime 与 GUI 验收证据继续在对应实施记录保存；文档检查不能证明生产稳定性。
- 2026-10-10 定向重新核验 main、#123/#136/#145/#149 和 Latest Release；三个历史候选仍 OPEN，Latest 仍 v2026.10.1。随后 #148 精确最终 Head 的常规 CI、独立审查通过，合并点为 `d95e256f068a014064f299a3655f2c1758f7b3cd`。未发布 Release、未操作生产；工作包 C 的分支证据与合并/发行结果分列。
- 2026-10-11 核对 #151/#152 的独立技术审查 COMMENT、main 合并 commit 及新 main 四项常规 CI 最终 SUCCESS；本地 main 非强制快进到 `1d8dd490`，原目录历史分支和其他工作区未提交修改保留。C4 工程证据见其记录，不重复验证 C2/C3 已充分证明且未修改的安装链路。

- 2026-10-13 再核对 main bc33339、#154/#155/#156 的准确提交及成功 CI、Latest v2026.10.1；本次维护全部现行文档入口、Code Wiki 与追踪登记，不重新执行业务回归。历史源码目录的独立提交、其他工作区和未提交文件保持；文档同步不产生合并、发行或客户操作许可。

- 2026-10-13 负责人明确授权无阻断候选合并：#154 合并 `11c9a38c070035e890f0cc3ff7dad3215c5dd737`，#155 合并 `3e0deeae1d737d01300708a5783c303b8d496351`。复用准确 Head 成功 CI 和既有完整副本证据；#156 正在与新主线整合，整合后的 CI 与最新 main CI 单独核对，不沿用旧主线成功结论。前端页面/产品交互变更先向负责人提供入口、流程和效果方案。
