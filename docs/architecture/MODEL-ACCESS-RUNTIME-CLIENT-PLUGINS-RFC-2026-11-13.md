# 模型动态接入、任务执行与多客户端插件联通：架构评审提案（RFC）

日期：2026-11-13  
状态：**PROPOSAL / DOCS_ONLY / IMPLEMENTATION_NOT_AUTHORIZED / REVIEW_REQUIRED**  
目标仓库：MEIS-DaCaiTou/Infinite-Canvas-Enterprise  
取材基线：企业版 main@22c4a9300198a9e348a9d5b28766217696aecfe8；比较对象 T8mars/T8-penguin-canvas main@8e84a2b5c2919b78f6e8f7e255e07445a31a6b44。该基线是本次只读设计快照，评审应再核对实时 Head。

> **定位**：记录产品负责人关于贞贞平台与 T8 模型调用方案比较后，要求进一步审视的五个技术方向，供开发设备 Codex 审核。**本文不是已批准的实现任务、API/DB 迁移计划、发布指令或新的唯一开发路线图。** 不更改 [项目范围锁定](../../PROJECT_SCOPE_LOCK.md)、[开发路线图](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md)、[代码边界](../../CODE_BOUNDARIES.md)、[项目章程](../../PROJECT_CHARTER.md) 的优先级与批准边界。

## 0. 总体判断与不可破坏的前提

**结论**：保留企业版既有 FastAPI/Enterprise Gateway、授权/凭据/持久任务/资产治理，**选择性借鉴** T8 的 Provider Adapter 和 Run → NodeRun → Attempt 表达；通过**受限的协议适配 + 声明式模型能力**实现已支持协议族的后台增模“零业务代码改动”，按模块边界渐进改造，而不是移植整个 T8 Node/Express 后端、复制一套账本或建通用脚本型插件框架。

- 当前企业版正式交付仍以 Windows 单机为基线，2026.11.1 已发布，客户现场验收与真实任务恢复应先按既定路线核对。Linux、专业服务器、员工桌面壳、PostgreSQL、HA、MCP 全面联动不代表已经交付。
- 员工 500+、峰值活跃创作 200+ 是长期容量**设计目标**，不是现有吞吐结果；活跃人数、同时受理数和同时付费生成数不能混为一谈。
- 保留**原业务数据事实源**及旧 API/旧供应商 ID/旧任务 ID/资产引用；迁移必须证明可回滚、可升级与中断恢复。未知供应商受理结果不可自动再付费提交。
- 2026-10-24 已退出当前范围的部门项目工作台、完整共享/费用页面、预算提醒等**不因本提案复活**。长期计费归属、配额/审计的底层治理能力与恢复 UI 是不同范围。
- 本 RFC 只提出最小协议适配/模型注册边界；现行规定的“常用供应商内置维护、临时模板兜底、不得预建通用参数语言/大型插件框架”仍有效。任何扩大为通用后台协议编排器的决策必须单独提交产品负责人审核。
- 审查以**当下 Diff 可定位问题**和真实证据为主，不新建独立审查队列、重复审查旧 PR 或无故跑重复全量测试。

## 1. 当前代码/来源证据与迁移约束

| 领域 | 企业版现有可复用边界（评审须按最新实际代码核对） | T8 值得参照的思路；不能照搬之处 |
| --- | --- | --- |
| 贞贞图片模型 | enterprise/providers/zhenzhen.py 中按模型族定义 IMAGE_FAMILIES 能力和请求差异；enterprise/provider_image_profiles.py 等既有调用契约 | T8 backend/src/providers/adapters.js 将多协议分派给 Adapter；不意味着任意新协议可纯配置 |
| 视频/同步异步 | enterprise/providers/zhenzhen_video.py、enterprise/providers/submission.py 及现有 main.py 路由 | T8 backend/src/routes/proxy.js 有多条具体供应商路径；不能假定统一一条 submit/status 就覆盖全部 |
| 任务与重启 | enterprise/canvas_task_journal.py、canvas_task_dispatch.py、task_credentials.py；已存在持久回执、恢复、防二次付费措施 | T8 backend/src/routes/projectRuns.js、services/runRecovery.js、Run/NodeRun/Attempt 具备可借鉴的状态组织；不可新增并行的第二套任务事实源 |
| 凭据、授权、收费 | Enterprise Gateway、credential_vault.py、task_credentials.py；按身份/凭据来源/受理证据核验 | T8 Adapter 层不替代企业用户、部门密钥、执行授权与可审计收费事实 |
| 资产/客户端 | 原资产服务、权限过滤、两类画布；UXP Photoshop 插件、Chrome 素材导入扩展已有源码 | 浏览器/桌面/插件只增加业务入口，不得各自实现授权、资产存档、任务保存器 |
| 产品演进 | PROJECT_CHARTER、PROJECT_SCOPE_LOCK、CODE_BOUNDARIES、正式路线图是当前依据 | T8 仅作为设计参考；其版本、稳定性、吞吐和能力覆盖需独立验证，不能继承结论 |

上游参照：
- [T8 Adapter 注册](https://github.com/T8mars/T8-penguin-canvas/blob/8e84a2b5c2919b78f6e8f7e255e07445a31a6b44/backend/src/providers/adapters.js)；
  [T8 Run 路由](https://github.com/T8mars/T8-penguin-canvas/blob/8e84a2b5c2919b78f6e8f7e255e07445a31a6b44/backend/src/routes/projectRuns.js)；
  [T8 恢复模块](https://github.com/T8mars/T8-penguin-canvas/blob/8e84a2b5c2919b78f6e8f7e255e07445a31a6b44/backend/src/services/runRecovery.js)。
- [本仓贞贞图像协议](../../enterprise/providers/zhenzhen.py)；
  [持久任务 Journal](../../enterprise/canvas_task_journal.py)；
  [任务派发](../../enterprise/canvas_task_dispatch.py)；
  [提交止损](../../enterprise/providers/submission.py)；
  [跨工具资产草案 N37](../requirements/N37-ASSET-INTEROP-CONTRACT-DRAFT.md)。

## 2. 方向一：动态模型接入——分级支持，不承诺“所有模型零代码”

### 2.1 兼容性等级及管理员体验

| 级别 | 例子（仅为协议类型举例） | 新增模型是否可做到前后端零改动 | 准入条件 |
| --- | --- | --- | --- |
| L1 同协议新模型 | 既有 OpenAI-compatible 同步文字/图片模型新增一个 model ID | **可行（目标能力，非当前已实现声明）** | 协议与鉴权、返回结构/任务语义全部兼容；能力元数据已覆盖 |
| L2 已内置供应商的新型号/参数 | 贞贞已知图片/视频请求族内的新型号 | **有条件** | 请求族/响应/参数表达能力、尺寸、引用图等确实落在现有 Adapter 与 Schema 中 |
| L3 新协议/非标准端点 | 新供应商签名、multipart、回调、非同构状态、任务签名 | **不可保证**，需受控开发/测试 Adapter | 统一权限、超时、幂等与查询语义可明确映射；协议安全验收 |
| L4 本地 GPU/工作流/交互工具 | 本地 ComfyUI、用户设备私网模型、软件操作 | **不可仅靠服务器配置** | 需要受控本地执行桥/Runner、设备授权与能力发现；与云模型分层 |

**不能保证“全部兼容”**：输入格式、图片/音频/视频、流式响应、异步回调、上传/蒙版、工作流图、错误语义、计价单位、签名授权及反向网络可达性差异是实质性的协议边界。名字类似不代表可互换。

管理员的目标流程：**注册供应商账号 → 选择现有协议/适配器版本 → 配置受限 API 地址/凭据 → 导入或选择模型 → 填能力与参数约束 → 测连接/模拟请求 → 按管理员授权发布 → 员工画布自动发现**。旧模型版本不能被管理员静默重定义成另一个协议；员工不需逐次填写供应商级 API 设置。允许继续保留既有个人模型就地设置体验，与企业预置列表共存。

### 2.2 控制面数据契约（逻辑结构，非批准建表）

| 对象 | 最小字段/约束 | 归属 |
| --- | --- | --- |
| ProviderAccount | id, provider_kind, protocol_id, adapter_version, base_url_ref, credential_ref, scope, enabled, timeout_policy_ref | 企业/部门/个人**已有授权与凭据治理**；密钥仅服务端可取，客户屏不回显 |
| ModelOffering | offering_id, account_id, provider_model_id, display_name, modality, lifecycle, capability_revision, published_at, visibility_scope | 管理端发布的**服务端权威目录**；模型 ID 与展示名分开 |
| CapabilityProfile | schema_version, input_types, output_types, param_schema, constraints, limits, sync_async_mode, query_capability, cancel_capability, pricing_reference | 版本化**受限能力描述**；不得包含管理员可执行脚本 |
| ModelInvocation | request_id, actor_id, source_canvas_id, offering_id, offering_revision, normalized_input_refs, idempotency_ref, governance_context | 应用层组装并绑定当时能力版本，不保存 API Key 原文 |
| ProviderReceipt | provider_task_id, submission_verdict, status_query_ref, output_refs, upstream_usage, raw_receipt_digest | 供应商事实记录；敏感原始响应需脱敏/按留存策略限制 |

**设计建议**：受限 JSON Schema 子集用于生成表单及校验：enum、string/number/bool、范围、必填、互斥和依赖规则可声明；文件引用、参考图集合、蒙版/分层输出、可视工作流等保留**专用 UI 组件和适配代码**。前端只显示能力允许的控件，服务端再次检验并生成供应商请求；不允许客户端直接提供任意请求 body/URL/headers 转发。

**灰度与兼容**：草稿/预览 → 已验证 → 已发布 → 已弃用 → 停用；能力修订不可修改历史 Run 快照。停用应阻止新提交，不抹除旧任务查询凭据和履历。发布/撤回全程审计。生产测试若计费须明确预算，优先合同/模拟响应和只读测试。

### 2.3 Adapter 最小接口

一个 Adapter 以供应商**协议语义**而非“单个型号一份实现”划分，按实际支持能力选择性提供：
- validate_config / probe（校验地址、协议与权限；probe 不得意外发起收费调用）；
- describe_capabilities（受限标准能力）；
- prepare_request（规范化输入 → 已验证上游请求，无任意脚本）；
- submit（必须区分**明确未发送 / 可能已受理 / 已收到外部任务 ID**）；
- query / reconcile（只读轮询、回调核对与防迟到结果污染）；
- cancel（仅支持时显式声明，不能将本地停止误称供应商已取消）；
- normalize_output / usage / error（映射受控状态、产物、计费证据，不猜测价格）。

同步、异步、流式、第三方工作流应分别声明模式；未知接口不伪装为某个已支持 Adapter。接口为逻辑契约，**不要求本次就创建全部方法或目录**。

## 3. 方向二：融合 T8 的 Run/NodeRun/Attempt——保留原任务事实源

### 3.1 概念映射

| 概念 | 用途 | 和既有系统关系 |
| --- | --- | --- |
| Run | 一次画布/工作流执行聚合，关联 actor、canvas/workflow、策略与幂等请求 | 可逐步为现有任务提供聚合视图，不替换原 Journal/Task identity |
| NodeRun | Run 中一个模型节点或工具节点的执行；单节点生成仍可有一个 NodeRun | 按实际画布执行链引入，不强制改造所有历史单生成任务 |
| ProviderAttempt | 该节点一次**外部付费提交意图/受理事实**，不等于 HTTP 重试次数 | 复用现有 submission 止损与 task_credentials，不独立扣费 |
| ProviderReceipt / ResultAsset | 已受理上游 ID、查询状态、结果媒体与归档的可核验证据 | 保留原任务 ID、原资产引用，缓存/投影不冒充权威状态 |

### 3.2 状态与安全不变量

提交状态应区分：**PREPARED → NOT_SENT / ACCEPTED / UNKNOWN_SUBMISSION / REJECTED**；运行状态允许 QUEUED、RUNNING、RECONCILING、SUCCEEDED、FAILED、CANCELLED（须区分“请求取消”和“上游确认取消”）。精确枚举与现存状态须由 Codex 审查后定稿，本文不是迁移规范。

1. 在网络收费调用**之前**持久化受控提交意图、actor、model/credential 快照和资源引用，沿用当前写入/锁与迁移安全原则。
2. 响应丢失、超时、连接重置、进程退出时，如不能证明未送达，则归类 UNKNOWN_SUBMISSION/RECONCILING，**不能自动再次提交收费请求**。上游 Idempotency-Key 仅在供应商确认支持且语义一致时才依赖。
3. 已收到 provider_task_id 后持久化并只读查询；查询/下载失败不等于前次生成未受理，也不得自动新建 Attempt。
4. “上游成功”不等于“媒体已归档/授权可读”。结果字节、哈希、资源归属、引用与可见性均一致才向画布提交 READY；归档失败保留可恢复证据。
5. Worker 重启时只领取可安全续查的任务；旧 Journal 可映射新版投影，不得临时“补造”历史上游回执或历史费用。模型修订、凭据版本、身份归属与调用证据随任务不可变。
6. WebSocket/SSE 只提供通知；客户端重连后按原 task_id 或版本化游标重新拉取服务端事实，不将推送视为持久事件账本。

**渐进融合**：既有模型请求路径与 UI 原样保持 → 在旧 API 内部委托统一 Application Service → 已知协议通过 Adapter 分派 → 在原 Journal/任务查询基础上引入 Run/NodeRun/Attempt 视图或必要字段 → 验证准确迁移/回滚 → 再开放画布新能力。**禁止旧任务账本与新 Run 表长期双写成两个权威源。**

## 4. 方向三：模块职责、依赖方向与不照搬清单

建议的**逻辑模块**（命名供审查，不能机械创建大量空目录）：

| 层 | 责任 | 不应承担 |
| --- | --- | --- |
| Enterprise Gateway / Policy | 认证、设备/用户/部门/资源权限、审计、租用与限流 | 供应商私有 JSON 与画布 UI 细节 |
| Model Catalog & Registry | 已审核的 ProviderAccount、Offering、能力修订发布/可见性 | 远程执行、凭据明文、历史结果 |
| Canvas / Workflow Application | 接收统一意图、校验资源引用和模型能力、创建任务、状态聚合 | HTTP 协议细节、磁盘私有路径 |
| Run Orchestration / Recovery | 持久排队、领取/恢复、状态机、Attempt/Receipt 关联 | 重新实现鉴权、第二套计费记录 |
| Provider Adapters | 每协议请求映射、签名/传输、同步异步查询、错误归一化 | 用户授权决定、资产正式发布 |
| Credential / Usage Binding | 既有凭据管理、执行上下文、费用/配额证据 | 硬编码在前端或第三方插件 |
| Asset Service / Repository | 结果归档、版本、哈希、上传/下载鉴权、引用和一致性 | 决定供应商计价/调度 |
| Client Connector / Local Bridge | 插件/设备能力受限暴露、本地缓存与操作回执 | 服务器任务/权限/资产的最终事实 |

依赖方向：**客户端/第三方 → Gateway → Application/Policy → Domain → Adapter/Repository**。HTTP、WebSocket、Runner、PS、Chrome、未来 MCP **都调用同一业务授权和存储服务**。内部接口可按完整的提交/查询/恢复/错误/凭据边界抽取，避免继续将新增模型分支堆进 main.py；也不拆成相互调用的微服务。

**明确不照搬 T8**：
- 不移植 T8 的 Express + SQLite 任务存储作为企业版另一个后端；
- 不照抄 T8 大型 proxy.js 的供应商分支或浏览器直接调用第三方；
- 不将 T8 的 Run/Attempt 数据表直接复制并与原 Journal 双主；
- 不照抄固定上游 API Key 的临时内存映射作为恢复依据；
- 不把“Adapter”理解为可加载管理员任意 JS/Python 插件；
- 不因 T8 有 API 便假定所有已接入模型具有相同收费、取消、重试语义。

## 5. 方向四：服务器—客户端—项目—资产的端到端目标结构

### 5.1 部署与权威边界

~~~text
Web 页面 / 未来员工桌面客户端 / Photoshop UXP / Chrome 扩展 / 外部 Agent
            |           TLS + 版本化业务 API
            v
 Enterprise Gateway（身份、授权、设备委托、审计、速率限制）
            |
            v
 Canvas/Workflow Application + Catalog + Durable Run/Task Service
            |                         |
            |                         +-- Provider Adapter → 受控云 API / 私网 ComfyUI
            |                         +-- Local Bridge 任务通道 → 用户本机工具/MCP Server
            v
 原持久元数据/任务事实（SQLite 单机；未来团队端可演进 PostgreSQL）
 原资产字节/媒体存储（本机可用；未来可替换共享存储）
~~~

- **服务器为权威**：身份、部门关系/访问政策、模型发布、供应商凭据、Run/Attempt/Receipt、正式资产/版本与可见性、费用证据和审计。
- **Web/桌面客户端**：UI 状态、画布交互、下载缓存、草稿/离线待同步操作、设备设置和资源预览。IndexedDB/客户端 SQLite 仅是可失效/可重建的本地缓存，离线变更需基于服务端资源版本比较后提交；不能离线决定正式授权与上游费用。
- **Local Bridge（以后）**：随用户设备部署并通过主动向服务端建立的受限连接/本机 IPC 对接设备工具；不要求平台服务端直接探测或暴露客户电脑公网端口。Bridge 的可用性/设备离线影响特定本地操作，不应阻塞普通云模型与 Web 服务。
- **路径与存储**：服务器下发稳定 asset_id/version/content_hash 与可过期、授权的传输凭据，不下发 Windows 绝对路径作为业务身份；本地缓存路径不回写成为服务器事实。素材字节与业务元数据分离。
- **演进策略**：继续当前 Windows 单活动 Gateway/SQLite/原文件存储；先验证 Linux 路径、信号、DPAPI 凭据适配、文件/DB 成套恢复、原任务续查；再经批准单企业试部署；测量后才讨论 PostgreSQL/共享存储/多 Worker/HA。不得把单机 SQLite 放网络共享盘来伪造多节点能力。
- **容量验证**：100/200/300 活跃用户混合负载，分别测画布保存、授权查询、资源传输、生成受理、查询恢复、WS 重连、客户端缓存及主机指标；报告 P95/P99、队列堆积、DB 写冲突、IO/媒体带宽、失败/恢复比例，区分请求量与实际付费模型并发。

### 5.2 最小数据关系（逻辑方案）

| 实体 | 关键字段/版本控制 | 典型持久方向 |
| --- | --- | --- |
| CanvasDocument / Workflow | canvas_id, version/etag, owner/context, nodes/edges, asset_refs | 既有画布/项目保存服务；新增字段优先兼容迁移 |
| ModelOfferingSnapshot | offering_id + capability_revision + resolved_adapter_version | 任务创建时固定，历史展示不随管理员改动漂移 |
| Run | run_id, actor_id, canvas_id, request_id, lifecycle_state, created_at, updated_at | 可映射已有任务标识；恢复时受原任务所有权约束 |
| NodeRun | node_run_id, run_id, node_ref, state, input_asset_refs, result_asset_refs | 按真实节点执行需要引入；避免虚构 UI 节点 |
| ProviderAttempt | attempt_id, node_run_id, provider_account_ref, credential_binding_ref, submission_verdict, provider_task_id, started_at | 绑定受理和扣费证据，敏感配置不落明文 |
| AssetRef / AssetVersion | asset_id, version_id, content_hash, type, state, owner/permissions, source_version_refs | 延续 N37 DRAFT 概念；不可覆盖正式版本 |
| TransferOperation | operation_id, target_ref, intent, expected_revision, checksum, phase, idempotency_key | 跨工具副本/上传/提交恢复；不直接授权文件系统路径 |
| ClientDevice / CapabilityGrant | device_id, user_id, revocable_grant, tool_scope, expiry, revoked_at | 未来插件本地委托边界，非默认永久授权 |

**实现前需明确**：上述逻辑对象中哪些已存在、哪些只需投影、哪些确需正式数据迁移。开发设备 Codex 不能把逻辑 ERD 自动转换成新数据库 schema；先证明原字段与迁移/备份边界不能复用。

### 5.3 三条关键数据链路

1. **管理员发布模型**：管理端授权 → 服务端校验供应商/协议与地址 → 绑定 SecretRef（不回显）→ 验证能力/参数 Schema → 显式发布修订 → 目录 API 按用户/部门/凭据政策过滤 → 画布动态渲染 → 发起任务时服务端再次校验。
2. **员工生成与恢复**：员工选择模型/源资产 → Gateway 授权 → Application 校验报价/准入/输入 → Journal 持久化提交意图与绑定 → Adapter 调上游 → 持久回执/Provider ID → 只读查询或合规回调 → 受控下载并归档资产 → 对画布关联结果（有版本/并发冲突校验）→ UI 接收通知并主动核对权威状态。**网络结果未知时进入核对，不能“重试生成”。**
3. **跨工具资产联通**：画布 AssetRef → Gateway 检查下载/外部导出权限 → PS/桌面通过限时传输获得副本 → 用户编辑 → 插件分块上传并确认哈希 → Gateway 检查最新版本与写权 → 创建新 WorkingVersion/TransferOperation → 通知画布刷新。编辑结果不可静默覆盖源/正式版本；PNG 导出不能视作 PSD/PSB 原生可编辑源文件。

## 6. 方向五：MCP、第三方智能体和现有 PS/Chrome 插件

### 6.1 双向 MCP，复用统一业务入口

**方向 A（外部 Agent 操作无限画布）**：把平台受限业务能力作为 MCP Server tools/resources 暴露给获授权的 Codex/智能体客户端（可由服务端受限接口或未来本地 Bridge 转接）。示例：list_authorized_canvases、get_asset_metadata、create_generation_run、get_run_status、import_asset_version。工具应为清晰、稳定、可审计业务 API 包装，不能直接操作数据库/文件目录。

**方向 B（无限画布调用用户设备工具）**：平台是 MCP Client，经未来桌面 Local Bridge 连接用户设备本地 MCP Server/智能体软件（本机优先 stdio/IPC，远程才用适当 HTTP 传输）。必须先确认设备在线、用户授权、工具能力、数据出站及动作审批；设备掉线执行进入可恢复/待确认，而非当作已成功。**MCP 是工具互操作协议，不替代 Provider Adapter/企业任务和收费治理；云模型推理不需要全部包成 MCP。**

- 设计以兼容协商为准，核对实际 MCP 客户端/Server 使用的协议版本；不要直接将某个新修订字段认作所有旧 Agent 设备已支持。
- 工具参数优先固定 JSON Schema、权限范围、超时、最大文件大小和提示/返回脱敏；拒绝任意 shell、读系统密钥、跨用户设备、盲目执行付费调用。
- OAuth/短期委托凭据、设备级撤销、每次操作身份传递与审计；服务端密钥**永不透传本地 MCP 进程**。高影响的远程修改/对外下载/收费生成需明确用户确认策略，不接受插件自报角色。
- 本地进程/浏览器来源限制、allowed origin/host、DNS rebinding/SSRF 防护、工具调用超时和最小权限；远程 MCP 不应直接信任客户端提供的 user_id。

### 6.2 延续已有插件，统一资产与任务契约

| 入口 | 已有源码现状（不是验收结论） | 增量接线方向 | 专属风险 |
| --- | --- | --- | --- |
| Photoshop UXP（tools/photoshop-asset-connector） | 资产浏览/置入、PNG 导出、WebSocket 更新，另有生成/查询/聊天的模块 | 企业登录/设备配对 → Gateway 权限 → AssetRef/TransferOperation/新工作版本 → 现有任务查询 | 目前企业身份接入未闭环；PNG 不是 PSD/PSB；禁止绕开 Gateway |
| Chrome 资源导入（tools/chrome-local-asset-importer） | 网页资源扫描/素材导入/下载，企业入口依赖浏览器同源登录 | 继续复用同源 Gateway；逐步将导入提交绑定统一 AssetRef/操作 ID | 页面内容不可信、跨域/第三方图片版权与大媒体下载、CORS、账号状态 |
| 员工桌面本地桥（未来） | 目标设计，非已交付 | 本机设备发现、最小权限 MCP Client/Server、离线队列可观测、可撤销连接 | 设备失联、秘钥驻留、OS 权限、恶意本地工具/静默付费 |
| 其他 Web 插件（未来/按代码核实） | 不能一概宣称都具备企业版支持 | 统一 API 版本、资源身份、任务 ID 与能力授权 | 浏览器插件不能托管企业 Secret，也不能绕过审计 |

对 MCP 与插件的功能开放建议按风险分级：**R0 只读发现/元数据 → R1 授权读取及下载副本 → R2 写入新工作版本 → R3 外部 AI 收费调用/批量操作或删除**。权限不能因为 R0 获批自动扩展到 R3；所有消费路径共享既有服务端 Policy 与收据。

## 7. 风险评估与可验证条件

| 风险 | 影响/等级 | 推荐止损、验证 |
| --- | --- | --- |
| 宣称后台添加“所有模型”均无需改代码 | 高：协议不匹配、生成异常、计费误判 | L1–L4 兼容分层，协议测试夹具；新协议必须新 Adapter 和验收 |
| 管理员自定义任意 API 地址/headers/body/脚本 | **高**：SSRF、云元数据探测、密钥泄漏与任意调用 | 受限协议模板、目的域名/IP/重定向校验、SecretRef、无脚本执行、不可被外部参数绕过 |
| 双任务账本或二次付费 | **严重**：UNKNOWN 被自动重发、状态错账 | 原 Journal/Receipt 单事实源；崩溃/丢包/上游 ID 保留；只读恢复，精确幂等审查 |
| 数据迁移破坏旧版升级/恢复 | 高：客户数据不一致 | 版本化兼容迁移、真实旧数据副本、故障注入/恢复；无未经批准新表 |
| 供应商声称取消/价格/用量但实际没有回执 | 高：误报取消、费用不可追踪 | 细分取消状态/计费证据，保留 UNKNOWN；不要前端估算当实际账单 |
| 客户端绕过 Gateway 或在本地缓存长期令牌 | **严重**：企业权限越权 | Server 权威、短期受限凭据/配对与撤销；逐入口验证身份/资源 |
| 外部 Agent/MCP 不经同意修改画布/付费 | **严重**：权限逃逸与财产损失 | 设备/操作/时限/资源范围限定、工具审核、用户确认、追踪审计 |
| 资产 DB/文件/缓存各自成为真相 | 高：丢资产/错版/权限泄漏 | AssetRef+version+hash，prepare/upload/commit/verify，服务端读后校验；缓存可重建 |
| 单机架构被当成多节点可用 | 高：同任务并行领取/数据损坏 | 先受控单机/Linux试验；上线多 Worker/PG/存储前验证锁、领取与成套恢复 |
| 大范围重构影响现有生成体验 | 高：兼容破坏 | 最小“接一个实际模型协议 + 一个任务回执”的垂直切片；旧 API 回归与特性开关 |

### 7.1 静态审核时的必要证据

- 逐项给出真实代码路径/关键调用链、原 Journal/Dispatcher/凭据/Policy/资产事实源；不把“设计中”写成“已实现”。
- 给出从现有图片、视频、LLM、ComfyUI、PS/Chrome 的真实入口到 Provider/Task/Asset 的映射，区分 Windows、Linux 候选与尚未存在的桌面桥。
- 确认已支持协议列表；列举“无需改代码接模型”的**真实边界**及 2–3 个兼容/不兼容样例（仅静态/Mock，不默认调用收费 API）。
- 确认受理未知/取消/超时/重启/重复提交/上游查询 ID/回调/素材已成功但归档失败等负向路径是否具备防重收费及恢复证据。
- 检查新旧任务 ID/模型 ID/凭据版本/资产引用与长期迁移、权限、费用证据的兼容方式；设计不许产生第二套权威事实源。
- 对跨设备 MCP、Chrome、UXP 的身份、授权、设备配对、撤销、来源信任及安全回包逐环审核。
- 明确本 RFC 哪些部分与当前 PROJECT_SCOPE_LOCK、CODE_BOUNDARIES 或路线图冲突，**必须标成待负责人决策**，不能自行更改事实源/优先顺序。

## 8. 如经审核与负责人批准，建议的渐进工作包（非当前开工命令）

| 次序/依赖 | 设计或验证包 | 最小完成证据 |
| --- | --- | --- |
| A 先评审 | 现有接口/存储事实盘点、L1–L4 兼容矩阵、边界/迁移风险；确定“何时无需改代码”的承诺措辞 | 代码路径 + 场景/差距表，负责人签认边界 |
| B 有界 Adapter | 在**既有**模型分派上形成一条真实协议的完整 submit/query/error/credential 垂直切片 | Mock/受控真实供应商验证，原 API/任务旧 ID 不变 |
| C 动态目录 | 支持一种**已内置协议**的受限管理员模型发布与能力表单 | 不改员工端代码新增同协议型号；权限/恶意参数/回滚测试 |
| D Run 语义 | 复用 Journal/Dispatcher 增加需要的 NodeRun/Attempt 关联和恢复投影 | 无第二事实源、未知不重发、重启与备份恢复定向测试 |
| E 资产/客户端 | 复用 N37 下位契约的必要资产版本/操作恢复；服务器适配按现有路线推进 | 服务器/客户端稳定资源身份、DB/文件完整性证据 |
| F 插件联通 | PS/Chrome 企业身份问题先核对；MCP 本地桥与工具授权作为**后续**专项决定 | 设备撤销、跨用户权限、失联/重连和真实 UXP/Chrome 宿主验收 |

执行顺序仍以当前路线图的**生产升级及真实任务恢复 → 资产一致性/容量与恢复 → 服务器适配 → 试部署/桌面 → 企业集成**为准；A 仅是可并行的**设计审核**，B–F 不构成授权开发。避免把 A–F 再登记成另一个并行项目计划或 16 周规范化工程。

## 9. 需负责人在实现前裁决的问题

1. “动态模型”首期支持哪些真实协议族/模态/同步异步模式？是否仅支持项目维护的 Provider Adapter + 有限能力配置？**建议：是；暂不建设任意协议编排器。**
2. 管理员模型发布权限是企业/部门哪一级？个人凭据与组织凭据优先级、禁用与历史任务查询规则如何按既有 Policy 定义？
3. 新能力是否依赖历史 Journal 增字段、只做投影，还是确需 DB migration？由现行升级/恢复证据决定，不能先定表。
4. 收费模型探针/回归预算及可用测试凭据由谁批准？没有真实供应商条件时清楚标 Mock-only。
5. 桌面 Local Bridge 的首批工具、用户确认模型、授权撤销策略和远端 Agent 访问范围是什么？当前仅设计，实施需再批准。
6. 升级旧客户端/UXP/Chrome 连接的兼容窗口和多版本 MCP 协商策略需要单独确认；不自动承诺无限向后兼容。

## 10. 本次 PR 的审查/交付口径

- **仅新增本 RFC 文档**。没有业务代码、SQL migration、UI、接口实现、测试、发行资产或安装包改动。
- 此 PR 为信息同步/技术审核载体；即使文档日后并入 main，也不等于批准 A–F 开发。**不得自行标 Ready、Merge、Release、生产部署、客户设备操作或付费调用。**
- 审核只要求当下代码对应的可定位矛盾/遗漏/风险和最小修改建议；若未发现可定位缺陷，报告 NO_ACTIONABLE_BUGS_FOUND，同时列明待负责人业务决策。
- 真正实施须再次核对最新 main、已有开发 PR 与准确版本，再按当前既定开发/测试/独立审查/授权交付流程推进。
