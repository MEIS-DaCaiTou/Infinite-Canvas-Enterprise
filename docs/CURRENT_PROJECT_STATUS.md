# Infinite Canvas Enterprise 当前项目状态

更新时间：2026-10-16
核验对象：main@6d9d77d（#162 任务中心已独立复审后合并）、合并后主线 CI；正式 10.2 的准确包及 10.1 → 10.2 升级/恢复证据继续沿用。v2026.10.2 已正式发布为 Latest，10.1 保持不可变；本轮未操作客户/生产设备。

## 1. 开发基线、发行与现场必须分开

| 层级 | 本次事实 | 不能据此声称 |
| --- | --- | --- |
| 主线核验基点 | `main@6d9d77dc07c5a2b655e2002536a653e285033d69`；#123、#137–#142、#146–#159、#161、#162 已合并；#153 发布目录分页与完整性已进入主线；服务器及 500+/200+ 长期约束随 #152 入主线 | 主线能力已随正式 10.1 全部交付、所有历史来源均兼容 |
| 最近已完成 main CI | main6d9d77d 的 [Enterprise/Runtime 38694777075](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/38694777075) 与 [文档 38694777090](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/38694777090) 最终 SUCCESS；固定 EXE opt-in SKIPPED。历史： 发行源码 7da593b 的 Enterprise/Runtime 38497837123、文档 38497837116 SUCCESS；main01c 的 [Enterprise/Runtime 38499949781](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/38499949781) 失败作业唯一重试后最终 SUCCESS，文档 38499949813 SUCCESS；opt-in SKIPPED。旧 main32c 与 main01c 的首次失败及各自唯一失败作业重试保留，不能改称首次通过 | 用 PR CI 替代 main CI；跳过门禁等于已验收 |
| 开发基线收口 | #146 选择性接回 10.1 同源页面提示和数据库 v2 迁移/构建契约，保留主线安全治理、任务回执、原生入口和恢复保护；准确整合范围与验证见 [收口记录](./ops/DEVELOPMENT-BASELINE-CLOSEOUT-2026-10-09.md) | 整条维护分支已合并；任意历史安装已受支持 |
| 主线诊断/恢复增量 | #147、#148 已合并。#148 工作包 B 完成精确 Job/READY、源进程 lease、接受竞争和超时恢复保护；310 项关联回归通过。代码 `6002300eff5fd4750f84bfe684b41a739c541120` 的本机固定 EXE 合成三门禁通过、测试进程/端口清理确认；准确最终 Head `fd8303337ea22bab91d4d1eb84606dcaa410f4ca` 三项常规 CI 及独立审查通过，2026-10-10 合并；[实施与验证记录](./ops/RUNTIME-UPDATE-LIFECYCLE-2026-10-09.md) | 已进入正式 10.1、所有安装副本或客户环境已验收、现场旧失败根因已确定 |
| 正式 Release | [v2026.10.2](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/releases/tag/v2026.10.2)，Latest、非预发布；`ice-2026.10.2-7da593b52f3d`，准确 source `7da593b52f3d487033e3ab1771142bfed891f316`，2026-10-14 发布，共 10 项资产 | 10.2 已部署客户、所有来源均兼容；覆盖旧 10.1 资产 |
| 生产单设备 | 负责人在固定 EXE 停止/重新启动 09.9 后，通过更新中心升级成功；导出日志确认 2026-10-09 北京时间 01:46:41 作业成功、目标 10.1、01:49 时 Runtime healthy | 所有设备都可升级、历史崩溃彻底解决或零停机 |
| 测试单设备 | 负责人确认固定 EXE 启动 09.9 并运行一段时间后，更新中心升级 10.1 成功；截图显示正确超管标签 | 等同于生产全量数据和持续运行验收 |
| 10.2 诊断候选 | [PR #145](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/145) OPEN/Draft，基于维护线；提交 `83e18c44357ec491dced0d6ba70bc4e691e420e1` | 已合并 main、正式发布或修复了现场失败根因 |
| 开发/候选版本 | `VERSION=2026.10.2` 对应本轮已发布修复版；准确 source/tree、构建与正式 10.1 升级/恢复结果已记录，见 [发行记录](./ops/RELEASE-2026.10.2-RECORD.md) | 仅修改版本号等于已经发布、客户验收或获准生产操作 |

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

以下是 2026-10-14 核验快照；#154/#155/#156 已合并，#123/#157/#158 及发行元数据 #159 已分别合并。合并源码不等于正式 Release 或客户验收。

| 候选 | 准确功能提交与 CI | 实现及限制 |
| --- | --- | --- |
| [#154 C5](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/154)，MERGED | `64c2adff3358e7f806d3cf04a26d86639597e573`；Enterprise/Runtime/文档三项 SUCCESS | 经核验的目标 Python 更新执行器接管、旧来源兼容和失败恢复；完整副本四类证据见 [C5](./ops/VERIFIED-UPDATER-HANDOFF-2026-10-11.md)，不包含原生工具替换和自动多跳 |
| [#155 C6/C7](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/155)，MERGED | `7029e1d1fdda7ecf962cf9e9a4f15cadf5dcc16c`；Enterprise/Runtime/原生 EXE/Setup/文档四项 SUCCESS | 离线升级、保留数据跨版本重装、原生工具及最多 8 跳连续执行/检查点；已合并为 `3e0deeae`，C5 前置已合并为 `11c9a38c`。限定 GUI 已有合成副本证据；在线检查点继续在本机仍被 handoff Job 资格阻断，见 [C6](./ops/OFFLINE-RETAINED-UPGRADE-2026-10-12.md)、[C7](./ops/ONLINE-UPGRADE-SEQUENCE-2026-10-12.md) |
| [#156 产品集成修复](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/156)，MERGED | 功能基点 `4bdd9a16074abac86ce47fc1e81b55bfb12cf63c`；Enterprise/Runtime/文档三项 SUCCESS。最终 Head `5b90391f30e0cfde4e15dd4d4b23c3ca2f5d13f5` 合并为 `e89a288fe`，对应 main 常规 CI 已成功 | 12 个已确认 Zhenzhen JSON 图像模型/别名内置能力与请求构造、个人模型列表、后台操作确认、素材扩展同源接线；范围见 [实现记录](./ops/PRODUCT-INTEGRATION-FIXES-2026-10-13.md) |

| [#123 付费止损与原任务续查](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/123)，MERGED | 整合 Head `fe4e5493d29925a7ee9231cd75826cf95f7c4f4d` 独立审查通过，合并 `32c67400`；PR Enterprise 失败作业唯一重试后 SUCCESS，首次失败记录保留；Runtime/文档 SUCCESS | 画布保存重开后查询已受理的原图像任务，不重新付费提交；归档失败保留原 ID 可续查，不等于统一任务中心/费用账本 |
| [#157 正式 Windows 启动与在线更新](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/157)，MERGED | Head `551f433db51444be2c96dec225b6479b8a854f00`；Enterprise/Runtime/原生 EXE/文档四项 SUCCESS | 现有固定入口正式启动方式的更新交接与失败恢复提示；启动不强制升级，更新需管理员确认；未覆盖 GUI 范围继续保留 |
| [ComfyUI 单图输入修复（#158 已合并）](./ops/COMFY-WORKFLOW-INPUT-REPAIR-2026-10-14.md) | 合并 `b41dd3b4`；独立审查通过，定向字段/实际级联调用者、静态闭包与受控 Browser/HTTP 证据；整合运行字节等价，main CI 仍单独核对 | 纠正 filename_prefix、直接兼容旧配置、两类画布共用映射和准确缺图提醒；受控协议闭环，客户 GPU/自定义节点尚未验证 |

三包已随准确 v2026.10.2 正式发行；固定 EXE real gates 的自动 opt-in 为 SKIPPED；已有真实副本证据不因 CI 跳过被抹除，也不因此外推全部客户。

[#157](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/157) `551f433db51444be2c96dec225b6479b8a854f00` 四项常规 CI 最终 SUCCESS，独立审查后已合并为 `519b1da0`；固定入口真实单跳及自动恢复证据保留，仍保留 C7 历史/GUI 限制。启动使用当前版本、不自动更新，管理员按需单独确认；该能力已进入准确 10.2 正式包；不能写成正式 10.1 原包能力。

[#123](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/123) 已独立审查并合并，最终整合 Head `fe4e549`。供应商 ID 在轮询前持久化，两类画布共享“查询结果”；批量成员和旧部分缓存通过本地归档核验，归档失败不伪报成功。实际 main 钩子与模拟供应商 GUI、独立审查修正及准确 CI 见[完整证据](./ops/PAID-SUBMISSION-STOPLOSS-2026-10-13.md)。尚未保存供应商 ID 的受理窗口、完整任务中心/费用账本及 Responses 后台 ID 长期恢复仍有边界。

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

当前已按负责人批准进入 **阶段 4.2 持久任务与供应商闭环**；阶段 3 仅继续处理实际迭代阻断，唯一实施顺序见[路线图](./roadmap/DEVELOPMENT-ROADMAP-2026-2027.md)。

1. #146–#153 的主线基础、固定入口、缓存清理、同版保留数据卸载/重装和目录分页已完成合并；C4 不再重复开发或重跑已有充分证据的测试。#148 的失败与最终合成三门禁、C2/C3 的限定证据继续保留。
2. #154/#155 已按负责人授权核查准确 Head 并合并，包含目标执行器、离线/在线连续升级、原生工具和检查点恢复；没有将开发端核查称为新增独立审查。main 的 #155 历史在线交接阻断仍保留原证据；#157 已按一种正式固定入口启动方式完成候选收口及必要恢复提示，独立审查后已合并，不继续扩展任意受限宿主矩阵。合成两跳成功不证明真实整机重启和所有在线续接已通过。
3. GUI 状态按准确来源分列：#152 的历史卸载 Yes 点击仍缺证据；C6 后续合成安装副本已有标准卸载确认和限定跨版本重装 GUI 证据，代码已合入 main。不能把这两者写成全面通过或全部未验证；未知来源、未来 Schema、未列 GUI 和客户设备范围继续保留限制。
4. #156 处理实际使用问题；管理员创建确认在 main 已有表单，旧正式 10.1 与现行主线契约不同。普通管理员不能因此获得创建管理员的权限。长期供应商适配由项目维护，普通用户在节点设置个人模型列表，不承担接口模板配置。真实付费、Chrome 扩展宿主与 PS 企业登录仍未验收。
5. [#123](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/123) 已合并；画布回执和局部止损不是统一 Task/Attempt、费用账本、预算及完整查询恢复。按路线图推进，已受理任务不自动重复付费。
6. 当前企业部署为单台 Windows 主机。专业服务器/云、500+/200+ 保留长期架构约束；Linux、容器、PostgreSQL、多实例和容量实施待负责人后续需求，当前只提前保持可复用业务边界。负责人已批准 v2026.10.2 修复版的审查合并、准确发行包与正式 10.1 升级/恢复验证后发布；没有整体重构或客户生产操作授权。
7. 安装维护以已有设备正常迭代、数据保护和必要恢复为目标；按完整工程包交付，减少相关技术债，复用有效测试，不以数量、哈希或额外框架作为成果。

负责人于 2026-10-14 将 ComfyUI 画布无法运行列为当前优先完整工作包：按现有交互解除创作阻断，证据与边界见 [修复记录](./ops/COMFY-WORKFLOW-INPUT-REPAIR-2026-10-14.md)。#123/#157/#158 均已分别独立审查并合并，准确 10.2 包成功升级与必要失败回退均通过。本轮发行已完成，目录回验结果见第 7 节；后续按唯一路线图进入可靠任务与供应商工作，不继续扩展安装矩阵。

### 10.2 反馈后的 ComfyUI 续修候选

负责人批准「ComfyUI 工作流节点调用修复与适配」，当前从 main@ef4c1e4 开发在 codex/comfy-workflow-adapter-20261014；尚未合并/发布。修复设置页双输入状态覆盖、上传/运行竞争和旧结果误导；指定后端贯穿上传/提交/查询/归档，复用既有回执续查与多类型结果，新增模块及兼容范围见 [续修记录](./ops/COMFY-WORKFLOW-INPUT-REPAIR-2026-10-14.md#102-测试设备反馈后的续修候选2026-10-14)。当前单台、未来同配置多台；本包不增加自动调度。真实 GPU 工作流、用户网络和全部清单类型尚未逐项验收，正式版仍为 10.2。

## 6. 本轮证据来源与限制

- 2026-10-09 定向 GitHub CLI/API 核验 main、#123/#136/#142–#147 和 v2026.10.1；#147 Head `222b2dfd8adc2c1237ff8d38cddd3093640139ba` 的三个 CI 检查通过，按准确 Head 合并为 `a5a6aa10b7882c46f129ec6df854239ee111da18`。明确使用企业仓库，避免本地 gh 默认指向历史 upstream。
- 负责人提供的生产 `update-diagnostics.zip`、`canvas-native-20261009-015017.zip` 已作本地只读核验；文件 SHA、采集时间与摘录边界见收口记录。不提交原始客户日志、数据库、密钥或业务材料。
- 本轮开发定向测试和隔离浏览器验证只证明受影响源码契约；没有真实生产启停、付费模型调用、Release 发布或资产替换。
- 历史数据/安装/Runtime 与 GUI 验收证据继续在对应实施记录保存；文档检查不能证明生产稳定性。
- 2026-10-10 定向重新核验 main、#123/#136/#145/#149 和 Latest Release；三个历史候选仍 OPEN，Latest 仍 v2026.10.1。随后 #148 精确最终 Head 的常规 CI、独立审查通过，合并点为 `d95e256f068a014064f299a3655f2c1758f7b3cd`。未发布 Release、未操作生产；工作包 C 的分支证据与合并/发行结果分列。
- 2026-10-11 核对 #151/#152 的独立技术审查 COMMENT、main 合并 commit 及新 main 四项常规 CI 最终 SUCCESS；本地 main 非强制快进到 `1d8dd490`，原目录历史分支和其他工作区未提交修改保留。C4 工程证据见其记录，不重复验证 C2/C3 已充分证明且未修改的安装链路。

- 2026-10-13 再核对 main bc33339、#154/#155/#156 的准确提交及成功 CI、Latest v2026.10.1；本次维护全部现行文档入口、Code Wiki 与追踪登记，不重新执行业务回归。历史源码目录的独立提交、其他工作区和未提交文件保持；文档同步不产生合并、发行或客户操作许可。

- 2026-10-13 负责人明确授权无阻断候选合并：#154 合并 `11c9a38c070035e890f0cc3ff7dad3215c5dd737`，#155 合并 `3e0deeae1d737d01300708a5783c303b8d496351`。复用准确 Head 成功 CI 和既有完整副本证据；#156 正在与新主线整合，整合后的 CI 与最新 main CI 单独核对，不沿用旧主线成功结论。前端页面/产品交互变更先向负责人提供入口、流程和效果方案。

- C7 根据负责人加快完整工程交付的要求集中实现；93 项已有受影响检查、11 项新增不同场景、冻结原生资产实际组装核验和内置 Browser 关键操作集中记录。未重复旧安装/卸载全套；本地历史分支、容量提交 f996b3e 和其他工作区未提交修改保留。新增真实副本证据在 C7b 分列：2/2 协调器成功、1/2 中断持久恢复、实际 Browser 继续被宿主阻断后确认停止；业务数据和安装身份核对通过。三处失败状态修复及 15 项本轮定向检查已完成；冻结合成包的源码基点与新修复分列。最终 Head/CI 以 #155 和集中索引为准，不授权发行或生产操作。

- 2026-10-13 按负责人要求继续阶段 4.1：现有 #123 重新同步 main，转为 Draft，提取付费提交规则到独立供应商模块，补齐异常成功响应、已受理查询中断和原任务身份保留；[工程记录](./ops/PAID-SUBMISSION-STOPLOSS-2026-10-13.md)。关联模拟/回执 13 项通过。该候选未合并，完整任务中心与费用账本尚未完成。

- #156 的整合 Head `5b90391` 三项常规 CI 最终 SUCCESS，按负责人授权合并为 `e89a288fe1ce8e5066ebebe1971e69bf5d4c7945`；本地主目录 main 安全快进到该点，历史分支/其他工作区保留。#154 与 #155 各合并点的自动 CI 已最终 SUCCESS。最新 e89a288 的 main CI 在运行，不能以 PR 通过替代；最终结果更新在 PR 证据/集中交付中。

## 7. 2026-10-14 准确发行验收补记

发行 source `7da593b52f3d487033e3ab1771142bfed891f316`、tree `46fe3ba334e6b4ec4437746dd0c2c51848fb9f7a`，Release ID `ice-2026.10.2-7da593b52f3d`。#159 合并 `01c29773` 与该 source 树完全相同，source 已可达 main；不是用后续文档提交冒充包来源。

开发机普通 Windows 桌面使用正式 10.1 BAT 和包内 Python/launcher，认证更新 HTTP 执行真实 worker。成功作业 `d3c3b910f5bc47929d9794fd2319f63d` SUCCEEDED，准确 10.2 healthy；独立副本目标端口冲突作业 `ac800cb3641b447bb660a9134cb59d37` ROLLED_BACK，准确 10.1 healthy。两者原账号登录、后台、业务行以及 5 个配置/画布/素材文件保持一致。没有将启动/健康结果替换成 mock。

来源数据库使用正式 10.1 已发布的准确旧库备份/登记 API 预置为 READY v2/30 对象，备份验证与业务行保留通过，对应正式 09.9 → 10.1 的已登记契约。10.1 裸新装 API 缺账本的数据库直接准备被拒绝，**不宣称裸库可直接在线升级**，不手工补账本或绕过身份检查。原生/Setup 同源双构建一致、未签名；发行路由仅允许准确 10.1 v2 来源，不外推其他历史版本、完整 GUI、GPU/真实付费或客户设备。详细结果见[发行记录](./ops/RELEASE-2026.10.2-RECORD.md)。

2026-10-14 公开回验：10.2 Latest、非预发布，10 项准确资产均已上传/回验，10.1 四资产身份未变。仍运行正式 10.1 的隔离更新中心已返回 `update_available=true` / `direct` / 最新稳定 10.2。首次目录读取 `route_invalid` 的记录保留，具体读取异常未确认，重新读取通过且未修改包/路由。该结果不代表已在客户生产执行升级。

### 2026-10-15 已批准的 ComfyUI 输入输出增量候选

继续 Draft #161，基于 main@ef4c1e4。可变图片组、同步动态插槽、提示词用途、文本正文/下载附件合一、现有 Prompt 节点复用和选定结果保留已在开发工作区实现；设置页、测试画布及两类正式画布共用模块。文本弹窗已按负责人反馈对齐既定视觉。定向检查与 loopback Browser 证据、实际 GPU/下载事件等限制见 [续修记录](./ops/COMFY-WORKFLOW-INPUT-REPAIR-2026-10-14.md#可变图片文本复用与结果保留续修2026-10-15)。三项常规 CI 的 a14726d SUCCESS 只对应此前 Head，新 Head 以 PR 检查为准。未合并/发布，正式 Release 仍为 v2026.10.2。

### 2026-10-15 ComfyUI 收口与任务中心后续包

上节“候选/未合并”是审查前快照。#161 的实现者以外代理复核发现输入归属、普通 HTTP 下 UUID、LLM 文本读取、分组旧默认值及切换后端上传残留五项缺口，已在 `13c796e74997a7fa488377358d701942ffdbbe77` 修正并独立复审；准确 Head 三项常规 CI 成功后 squash 合并为 `6603550c4ad367b031de34e53cc9b488bd207140`。本地主目录已安全快进，其他 worktree/修改保留。主线 CI 已单独核对最终成功；正式 Release 仍是 10.2，未把 #161 当已发布能力。

负责人批准按唯一 [路线图 4.2](./roadmap/DEVELOPMENT-ROADMAP-2026-2027.md#42-持久任务中心与独立供应商适配) 继续。[PR #162 已合并](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/162)，开发分支 `codex/durable-task-center-20261015`：在现有画布日志增加本人“生成任务”页签，复用持久回执与 SQLite 归属映射；状态筛选、详情、图文结果和原任务续查共用模块，两类画布均接入。补充提交/受理/归档阶段、脱敏错误、供应商报告用量和最近核对事实；Zhenzhen 图像 GET/鉴权构造与通用状态解析继续移出 main。准确 Head b61b564 已由独立代理复审通过（三项发现均关闭），三项 PR CI SUCCESS 后合并为 main6d9d77d；合并后主线 CI 另行核验最终 SUCCESS。审查记录为 COMMENT，不冒充不同账号的 GitHub Approval。不宣称完整任务调度、全供应商恢复或费用账本完成，详见 [任务工程记录](./ops/PAID-SUBMISSION-STOPLOSS-2026-10-13.md#2026-10-15-持久任务中心与供应商边界续包)。本轮没有新发行、生产操作或整体架构重构。

### 2026-10-15 自动恢复与常用供应商闭环候选

任务中心审查交付已先完成；后续按唯一路线图 4.2，在 codex/task-auto-recovery-20261015 推进已有受理 ID 的后台续查。Zhenzhen 图像和 ComfyUI 原任务不依赖浏览器轮询；启动从同一个 v1 journal 重建调度，运行中跟踪失败后登记续查；并发 2、正常间隔 5 秒、瞬态失败退避至最多 300 秒。认证/配置/归属/未知回包需要人工核对，不自动重新生成。维护标记存在时不领取新查询，停止时取消查询并保留原身份。现有日志任务详情补充自动状态/下次查询/暂停原因，没有新页面或用户模板。

本候选复用原归档、单飞和 Comfy 查询领取，仍由单个 Upstream 执行，未完成独立 Worker 进程、多实例或全部 GPT/视频供应商。准确证据及重启演练发现/修正见 [同一任务记录](./ops/PAID-SUBMISSION-STOPLOSS-2026-10-13.md#2026-10-15-已受理任务自动恢复候选)。尚未独立审查、合并或发布；正式 v2026.10.2 保持不变。


### 2026-10-16 视频持久任务与原任务续查候选

本次重新核对 origin/main 为 `39f4b02d232142c4ede66f0133b759b32178d70f`，主线 [Enterprise/Runtime 38833185811](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/38833185811) 与 [文档 38833185665](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/38833185665) 最终 SUCCESS。上方 main6d9d77d 是历史核验快照，G0–G3 后续已合入 main；#163 与 #168 保持 Draft，本地主目录与旧工作区保持原状。

按负责人授权继续唯一路线图 4.2，视频候选分支 `codex/video-task-recovery-20261016` 基于 #163 Head `0a6db0f36edcb18fb352f7ab5768684a3334a666`，独立堆叠交付，不复制或改写 #163。两类画布的视频生成先登记本人持久任务，已有 HTTP 提交在收到 ID 后原子保存地址/协议绑定；复用既有调度器、归属表与 v1 journal，刷新或重启后可在现有“日志 → 生成任务 → API 视频”查看结果和继续查询原任务。没有新页面、数据库 Schema、计费算法或付费自动重提。

通用视频、Agnes、APIMart、火山及玉玉沿用现有请求和查询协议，实际可恢复以取得已绑定 ID 为前提；即梦 CLI 排队保留原 submit_id 和既有专用查询路径，RunningHub 等未接入本次 HTTP 回执钩子的协议不据此宣称自动恢复。提交结果不明且无 ID、配置/协议变化和未知回包需人工核对。实现、定向验证及限制复用 [同一任务记录](./ops/PAID-SUBMISSION-STOPLOSS-2026-10-13.md#2026-10-16-视频持久任务与原任务续查候选)。本候选尚未合并或发布，正式 Release 仍为 v2026.10.2。
