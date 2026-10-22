# Infinite Canvas Enterprise 当前架构

更新时间：2026-10-14

本文描述 main 已合并的运行架构、明确标注的开发候选与已确定的演进边界。实现状态以 [docs/CURRENT_PROJECT_STATUS.md](docs/CURRENT_PROJECT_STATUS.md) 为准，未来顺序以 [开发路线图](docs/roadmap/DEVELOPMENT-ROADMAP-2026-2027.md) 为准。

## 1. 当前形态

当前是面向 Windows 单机/LAN 部署的模块化单体：

```text
Browser / LAN users
        |
        | HTTP + WebSocket
        v
Enterprise Gateway (0.0.0.0:8000)
  auth / permission / audit / admin / proxy
        |
        | user context, loopback only
        v
Canvas Application (127.0.0.1:3001)
  canvas / workflow / provider integration / static UI
        |
        +-- SQLite enterprise database
        +-- canvas/conversation/task JSON and metadata
        +-- asset/output files

Runtime Supervisor
  immutable Release + current pointer
  independent process ownership and health
  bounded restart/backoff and durable logs
```

这不是 PostgreSQL、多 Worker、共享对象存储或多节点高可用架构。`gateway` 与 `canvas application` 是同一产品内的两个进程；“Upstream”一词在代码里仍可能作为历史进程角色名出现，不表示产品继续依赖外部上游迭代。

专业企业服务器、私有化服务器和云服务器生产部署是已确认的长期产品目标。当前 Windows 单机/LAN 是已实现形态；Linux 运行兼容、标准服务管理、容器或其他服务器交付尚未完成验证，不能从 Python 源码的存在推导已可生产部署。

## 2. 主要模块

| 模块 | 当前职责 | 主要入口 |
| --- | --- | --- |
| Gateway | 登录、Cookie/JWT、请求和事件授权、HTML/响应治理、代理、管理入口 | `enterprise/gateway.py` |
| Interceptors/Policies | 路由分类、所有权过滤、功能开关、审计触发 | `enterprise/interceptors.py`，后续迁移到领域 Policy |
| Enterprise data | 用户、角色、归属、审计、版本化 migration/backup/restore | `enterprise/db.py`，`enterprise/migrations/` |
| Canvas application | 画布、工作流、模型调用、静态前端和原有业务 API | `main.py`，`static/` |
| Task journal | 两类画布任务持久回执基础 | `enterprise/canvas_task_journal.py` |
| 部门/费用候选（未激活） | 单部门/项目策略、DPAPI版本化来源、冻结调用归属、分单位费用和提醒；后续绑定接线候选复用任务回执，不新建队列 | `enterprise/department_governance.py`，`enterprise/department_costs.py`，`enterprise/task_credentials.py` |
| 旧创作入口来源兼容候选（未合并） | 在线生图复用持久图片执行器；聊天/流式/Agent 文本复用同一来源绑定、LLM 回执与归档；管理员明确接纳原共享密钥 | `enterprise/legacy_call_sources.py`；不新增队列、Schema 或供应商协议 |
| 供应商图像适配（#156 已合并） | 内置 Zhenzhen 已确认模型协议与能力；新模型临时兼容配置；与存储/Windows 生命周期分离 | `enterprise/providers/zhenzhen.py`，`enterprise/provider_image_profiles.py` |
| 个人模型显示（#156 已合并） | 当前登录账号的模型选择列表及持久设置；不授予供应商管理权限 | `enterprise/user_model_api.py`，`enterprise/user_model_preferences.py`，`static/js/model-picker.js` |
| 原任务续查（#123 候选） | 接受 ID 的持久绑定、原任务查询与原回执结果，复用既有 journal/归属 | `enterprise/canvas_image_recovery.py`，`static/js/canvas-task-query.js` |
| Runtime | launcher、supervisor、health、ownership、state/log | `enterprise/runtime/` |
| Release/update | Manifest v2、资产校验、prepare、pointer switch、rollback foundation | `enterprise/release/`，`enterprise/ops/update/`，`enterprise/update_api.py` |
| 部门项目界面候选（未激活） | 权限过滤的来源/项目控件、成员和密钥管理、三级费用视图；复用原任务元数据，不建任务队列 | `enterprise/business_workspace.py`，`enterprise-static/business.html`，`static/js/business-workspace.js`，`static/js/call-source-picker.js` |
| 经典画布媒体复用（#189已合并，未正式发布） | 按画布/节点/结果槽保留播放器；生成准备状态不写入持久画布 | `static/js/canvas-media-retention.js`，`static/js/canvas.js` |
| Enterprise UI | 登录、管理后台、个人中心、更新中心 | `enterprise-static/` |

Code Wiki 提供更细的文件、类和函数导航：[docs/code-wiki/README.md](docs/code-wiki/README.md)。

以下供应商/个人模型模块存在于 #156 的源码基点 4bdd9a1，已随 e89a288 合并 main，尚未正式发布，准确状态回到 CURRENT。模型调用继续复用现有入口、结果归档和任务回执。长期接入供应商的参数差异由项目维护内置适配，普通用户只选择模型、画幅、参考图等创作参数，无需配置请求模板。Zhenzhen 图像模型的已确认协议分组与别名集中在 `enterprise/providers/zhenzhen.py`，按明确供应商身份及实际请求契约选路；文生图和参考图生成使用文档指定的 JSON Generations，不探测多个付费提交入口。前端读取同一内置能力的公开投影，限制不支持的参数；已支持模型优先于历史临时模板。

临时模板默认折叠，仅供管理员在新上线模型尚未内置适配时配置兼容参数，不作为日常接入流程。该实现覆盖已确认的 Nano Banana、Gemini 3.1 图像、GPT Image 2 和 Seedream v5 Pro 图像契约；不等于供应商所有模型、视频协议、层分解输出或原生 Google 协议已经验收。新增同协议别名主要维护集中目录；新的提交/查询协议才增加适配代码。节点保留明确的画幅/分辨率选择，个人显示列表只影响选择体验。

个人模型偏好存于 `DATA_ROOT/user-model-preferences/<user_id>.json`，身份来自认证会话，以同目录临时文件原子替换；只清理本次写入自己的临时文件。该写入边界登记为既有 APP_ROOT 写入审计的 W50，不写安装源码目录，也不改动企业业务数据库 Schema。

`main.py` 中已有供应商调用、画布和工作流仍存在集中实现的技术债。本次将 Zhenzhen 新增图像请求构造与能力目录放在独立模块，主入口只连接现有 HTTP、资源转换和结果处理。其余供应商的模块化、统一持久任务/Attempt 和完整费用对账按唯一路线图阶段 4 落实；本次不构成自动最低价选路或不明状态跨供应商再次付费提交。

### 画布首页目录候选（2026-10-22）

`enterprise/canvas_workspace.py` 在原文件/所有权与部门项目策略上投影目录元数据，`department_api` 只接 HTTP；现有父级字段用于树，`migrations/canvas_workspace.py` 追加未激活 v4 的两张关联/归档表。没有第二任务队列或画布副本。`canvas-workspace-boot.js` 按已受控升级的能力选择新目录 UI，旧 schema/独立 main 保留原脚本；网格/列表用现有主题、图标和原编辑器，个人范围仍可进入旧自由布局。公开项目只返回明确关联的目录元数据；原资源和完整画布继续由既有所有权策略约束，完整只读预览另行接线。

### 项目任务与完整画布共享候选（2026-10-22）

`enterprise/project_results.py` 在既有任务所有权、journal与冻结业务归属上投影任务/归档成果；`shared_canvases.py` 依据明确项目关联与现行项目策略读取完整创作结构，过滤凭据，按请求重查资源授权。复用以独立资源所有权落在现有存储及原画布创建/保存流程，不执行供应商请求、不继承待运行任务。既有费用接口和角色权限保持，目录共享本身不授予全局资源访问。

前端 `project-results.js` 接原首页任务/成果及共享设置；共享画布直接导航原编辑器，`shared-canvas.js` 仅提供只读控件与保存副本，原编辑器停止自动保存和任务续查，保留原渲染/连线/媒体查看。`department-members.js` 增强现有管理后台成员页；`department_governance.member_workspace` 返回角色可管理范围，Gateway只允许现任部门负责人进入此受限页面，原公司管理API不放权。本包依赖未激活v3/v4，无新增Schema或第二业务页面。

两类显式素材副本的写入沿用 W15 的 `UPLOAD_ROOT/assets/output` 流程，并登记到既有写入清单；异常清理只删除该次创建的文件，不清理原项目素材。

## 3. 安全与权限边界

费用分页及站内预算提醒候选复用 `DepartmentCosts.entries/budgets/summary`：`alerts` 只投影现任可管理部门的当期超额预算，不参与任务受理，也不生成费用。`business-workspace.js` 使用原cursor分批显示明细；`budget-alerts.js` 在现有首页/后台/费用页显示非模态提醒，按账号在浏览器保存本期已知晓状态。无新Schema、队列或后台通知服务，费用仍由原角色授权，页面不可见时暂停定期读取。

- 对外仅暴露 Gateway；`:3001` 必须绑定 loopback。
- UI 隐藏不是权限控制，API、WebSocket、后台任务和资源访问必须服务端授权。
- 普通用户对未知 owner、未知路由和未知事件应默认拒绝。
- 超级管理员能力是显式授权，不由普通管理员身份隐式继承。
- Cookie、Origin/Host、登录跳转、静态文件路径和代理目标均需独立校验。
- 数据库约束/RLS（后续 PostgreSQL）是纵深防御；业务授权仍负责返回稳定的产品错误和审计信息。

SEC-P0 已通过 PR #119 合并，#111 已关闭；后续加固与管理员操作 403 仍需按精确治理状态回归。不能放宽授权来消除错误提示，也不能以已有角色表宣称所有权限场景均已验收。

## 4. 数据与存储

### 当前事实源

- 企业结构化数据：SQLite。
- 画布、对话和部分任务：文件/JSON 与 SQLite 映射并存。
- 图片、视频和输出：文件系统保存字节，数据库/JSON 保存路径和归属。
- 配置、Runtime 状态、日志和 Release 分属 `CONFIG_ROOT`、`STATE_ROOT`、`LOG_ROOT`、`INSTALL_ROOT/releases`。

### 固定不变量

- 数据从创建时就具有 owner/org/project 语义；不能依赖后补归属。
- 大型资源字节不进入普通业务数据库事务。
- schema 变化必须带版本、迁移、验证和恢复计划。
- 画布引用资源 ID/版本，不长期写死绝对磁盘路径。
- 任务和费用是可审计事实，不以进程内内存作为唯一状态。

### 近期缺口

DATA-MVP-1 与 UPDATE-DATA-1 已通过 PR #120/#121 复核和接入主线，PR #130 补齐旧库先备份再登记保护。新增表仍须验证准确来源、迁移步骤、数据保留与失败恢复；基础引擎通过不等于全部客户结构兼容。

文件/JSON、数据库和审计有不同状态，持久格式同样要版本化。两类任务回执不等于统一任务平台、费用账本和对账。

## 5. Runtime 与健康

Runtime Supervisor 分别管理 Gateway 和 Canvas application，并持久化运行状态、日志、进程 identity 和 generation。存活、就绪与业务健康的语义必须分开：

- liveness：进程/事件循环是否能响应，不访问外部 Provider。
- readiness：实例是否可接收业务流量。
- dependency health：数据库、Canvas application、Provider 等依赖状态。

短暂依赖失败应进入 degraded，不得直接导致 Gateway 破坏性重启。真实进程退出才进入带退避的恢复。主要修复已通过 PR #108 合并；真实 Windows 服务、安装副本回调和客户使用是不同证据层级。

## 6. Release 与在线更新

主线已有不可变 Release、Manifest v2、准备、数据迁移/恢复、一次确认和准确路由检查。正式 10.1 来自维护线，是 09.9 同数据库结构的后台维护包，不是 main 全量发布；两台设备成功反馈与剩余限制见 [CURRENT](docs/CURRENT_PROJECT_STATUS.md)。

本轮统一开发基线接回 `ice_096_security_schema_v2` 登记、v2 snapshot 和构建模式。默认未来构建生成与正式 09.9/10.1 同源的 30 对象/schema v2 证据；Greenfield 按已验证包内 evidence 选择受支持的 v1/v2 初始化并验证元数据/账本/结构，固定入口、密码和 pointer-last 保护保留。普通启动不隐式迁移旧库，28 对象历史变体不默认开放；历史资产须从冻结 refs 重建，不能用当前源码的旧 VERSION 标记伪造旧包。

主要缺口是阶段 3 在线交接收口、准确来源及 GUI 覆盖，以及完整任务/业务写入隔离。目标 Python 执行器、原生工具和连续路径已随 #154/#155 进入主线，在线交接缺口与验收范围仍分别记录。遵循 [统一交付 ADR](docs/decisions/ADR-DELIVERY-001-UNIFIED-INSTALL-UPDATE-LIFECYCLE-2026-10.md)。下面是目标完整流程，不声称每一步都已落地。

C5 开发分支新增 [经验证的目标更新执行器接管](docs/ops/VERIFIED-UPDATER-HANDOFF-2026-10-11.md)：纯读取契约独立声明控制器协议、worker 协议和引擎能力版本；完整包及持久计划核验后，目标代码/目标 Python 运行既有单跳事务，数据和状态仍归同一安装。无契约的不可变旧包沿用来源引擎，有但不可验证的契约拒绝交接；不弱化进程 lease、Job 独立性或恢复阻断。它不是原生 EXE 替换或自动多跳，也不扩展未知 Schema 的迁移授权。Windows 执行路径留在现有平台交付/Runtime 边界，不增加核心业务的桌面或注册表依赖。

目标单机更新事务：

```text
authorize
  -> check compatibility
  -> download and verify immutable assets
  -> notify users / stop accepting long tasks
  -> drain or checkpoint tasks
  -> backup database + business metadata + config
  -> apply schema migration and verify
  -> switch Release pointer
  -> start and health-check
  -> commit success
     or restore data + pointer and report recovery state
```

单跳已有持久作业和恢复查看基础；C7 协调器通过最新目标包内的协调器执行整条已授权路径，各跳仍复用单跳事务，不创建另一套数据库迁移引擎。网页、固定 EXE、安装器和恢复界面必须共用引擎：Python 承担业务/迁移，C# 仅做系统交互，安装器编排。

C6 [离线保留数据升级记录](docs/ops/OFFLINE-RETAINED-UPGRADE-2026-10-12.md) 复用上述引擎，在明确停止来源服务、相同 Schema 和可证明安装身份下恢复来源并升级程序、固定 EXE 与保留维护 Setup；分别保存对象身份和检查点。成功目标等待 Windows 登记时暂停其 HTTP/WS 业务，登记核验后完成。成功后的登记故障不触发数据库或来源版本回退；该粗粒度暂停不是持久任务排空、完整业务维护态或自动多跳。Windows 专属登记/文件操作不进入企业业务模型，候选/GUI/合并/正式发行分别记录。

#151/#152 已将归属缓存清理、实例标准卸载、同 Release 保留数据重装和持久恢复合入 main；C6 实现已补证标准卸载确认和限定跨版本 GUI，完整维护矩阵及长期闭环仍未完成。C4 [发布目录工程记录](docs/ops/UPDATE-CATALOG-PAGINATION-2026-10-11.md) 已经 #153 合入 main，将 v1/v2 元数据读取共用到分页目录：临时内存缓存按仓库/凭据身份隔离，每次 HTTP 条件核验全部页面，读取失败不作为升级事实源。路线缓存仅用于不可变声明的页面预览，准备和执行仍重新核验；不新增业务数据库、Windows 核心依赖或缓存 TTL 政策。

失败恢复应在开放业务写入前完成；已经接受新数据后不能还原旧快照。PostgreSQL 及多节点有独立排空、备份/恢复和发布协议，不照搬 SQLite 文件替换。

## 7. 目标演进

任务顺序只在 [唯一路线图](docs/roadmap/DEVELOPMENT-ROADMAP-2026-2027.md) 维护。

| 已确定角色 | 数据目标 | 实现边界 |
| --- | --- | --- |
| 长期保留单机版 | SQLite 业务数据与本地素材 | 不是多节点共享库 |
| 团队服务端 | PostgreSQL＋受管理存储 | 当前客户仍为 SQLite，产品迁移单独验证 |
| 员工桌面客户端 | 服务端业务事实；本地 SQLite 缓存/设置 | 尚未交付，不自动给每个员工装服务器 |

本地与企业服务器/云端部署复用业务领域模型、API、服务端权限契约和稳定资源身份；员工端消费同一业务契约，不复制业务系统。Windows Registry、Job Object、KnownFolder 和桌面交互留在平台适配层；业务核心不新增固定盘符或必须由桌面启动的依赖。

当前仍按单台 Windows 主机交付；Linux、云部署和规模容量实施待负责人需求，不作为本轮新增任务。后续服务器运行能力随正式工作包建立：先评估 Linux 真实依赖与阻碍，再落实配置外置、无交互启动/停止、健康检查、日志、权限/网络边界及可重复部署。公开入口须核验 TLS、可信反代、网络隔离、访问限制、身份/密钥与审计。跨企业采用共享 SaaS、每客户独立部署还是混合形态尚未确定；部门 Owner 隔离不能替代企业租户边界。

单企业未来 1—2 年的设计目标为 500 名以上员工、200 名以上同时活跃创作；不是现有容量或 200 个同时付费请求的承诺。后续使用 100/200/300 活跃用户的混合负载，观察 API/WebSocket、画布保存、AI 受理与查询、数据库写等待、素材读写和队列积压，再按瓶颈选择 PostgreSQL、独立 Worker、受管理文件/对象存储、传输缓存或多实例协调。高可用按业务可靠性目标演进；RPO/RTO、预算、云供应商及拓扑仍待负责人确认。不预设微服务、Docker、Kubernetes 或 Redis 为前置目标。

持久任务/Provider Attempt/回执/费用/审计、事务与版本冲突、Repository 和 Storage Adapter、格式迁移及失败恢复随 B13/B14/B15/B16/B17、N29/N34/N37 的对应实施授权一并落实。容量和服务器要求不改变当前阶段 3 顺序，也不豁免客户数据与更新恢复门禁。Vue 3＋TypeScript 是局部试做方向，不表示已迁移；桌面框架仍须比较验证。

模块化原则是按业务域逐步提取 Policy、Application Service、Repository、Provider Adapter 和 Storage Adapter；不做一次性重写，也不继续把新业务规则堆入 `gateway.py` 或 `interceptors.py`。

## 8. 历史来源边界

项目保留 `hero8152/Infinite-Canvas@2026.07.6` 的来源归属和历史审计。本项目已决定冻结来源基线，后续不再要求同步；`main.py`、`static/`、`workflows/` 等都可以在明确任务、测试和发布迁移计划下演进。`docs/upstream/` 仅作历史证据，不是当前开发限制。

## 9. 尚未实现

阶段 3 尚未完成所有来源/GUI/在线续接的交付闭环；完整通知/任务与写入隔离、统一任务/费用、CAS/员工桌面客户端、PostgreSQL/HA、SSO/目录/Agent 与可选远程诊断仍未交付。新装/同版修复/保留数据卸载/重装及目录分页已进入 main；目标执行器、原生工具和多跳协调器已合并，在线续接仍有宿主阻断。已实现迁移/恢复基础不再笼统写成未实现；具体范围见项目状态。

ComfyUI 输入修复候选将三处字段识别、旧配置读取修正、缺少素材检查和参数映射集中在 `static/js/comfy-workflow-fields.js`；设置页和两类画布复用，不建立新的任务/插件框架。修复不改工作流节点、数据库 Schema 或服务端权限，细节与受控验证边界见 [实施记录](docs/ops/COMFY-WORKFLOW-INPUT-REPAIR-2026-10-14.md)。

ComfyUI 10.2 反馈续修候选从 ef4c1e4 开发：协议边界在 enterprise/providers/comfyui.py，前端双视图共用 static/js/comfy-workflow-session.js；既有 journal 增加受理后端/prompt_id 与查询阶段，旧任务记录按有无真实受理身份区分恢复。本包只指定后端、复用原生队列及现有归档，不新增分布式队列/业务表。main 保留入口编排、内置图预处理和既有结果归档；此段为审查前设计快照；#161 已合并 main6603550，尚未正式发行。详见 [续修记录](docs/ops/COMFY-WORKFLOW-INPUT-REPAIR-2026-10-14.md)。

2026-10-15 ComfyUI 已批准增量继续放在 #161：图输入组和结果选择进入 enterprise/providers/comfy_workflow.py，文本使用进入共用 comfy-outputs.js/CSS，入口复用既有请求、归档、回执和画布持久化。动态扩展只采用已确认的 core 插槽契约；未知图依赖不进行通用推断。输出同时携带类型、正文、文件引用和运行/结果身份，选定下游文本保存快照。无新表/队列/平台依赖，#161 已合并 main6603550，尚未发布。

2026-10-15 任务中心已随 #162 合并 main6d9d77d，采用 `enterprise/generation_tasks.py` 作为归属映射和既有 journal 的读取 Repository，`generation_task_api.py` 仅接认证和 HTTP。Gateway 不写上游任务事实；已核实本人任务的结果复用既有资源归属投影，保留已有 owner。前端 `generation-task-center.js/CSS` 只接入原画布日志页签，两类入口各提供已有媒体预览/Prompt 创建回调。新回执信息为 v1 可选字段，重启仍由原单写入者恢复；供应商报告金额不等于结算，没有金额或币种不猜测。Zhenzhen 图像请求与查询/鉴权构造在对应模块，通用 JSON 状态在 `image_task_protocol.py`；结果解析/归档仍有 main 编排，尚不是全 Provider 模块化。当前仅单 Windows 主机，不新增 Windows 核心业务依赖；服务器/容量目标继续作为后续边界约束。

任务目录读写协调补记：生产路径由 Gateway 的 generation_task_api 认证并覆盖身份，通过既有回环 HTTP 连接池读取 generation_task_routes 的内部路由；Repository 注入上游同一个 CANVAS_TASK_JOURNAL，共用既有互斥锁，Gateway 不直接打开回执文件。Windows 普通读取句柄阻止 os.replace 的对照已复现；改为同一对象协调后，并发读取/30 次回执写入通过。公开 Gateway 拒绝整个 /_enterprise_internal/ 命名空间，客户端伪造身份无效；业务进程不可用时返回 503，不自动生成。原生文件接口试验未保留，无新平台适配/数据库结构。

自动恢复候选沿用上述单上游事实源：`accepted_task_recovery.AcceptedTaskRecovery` 只维护可重建的调度索引并调用原 ID 查询；持久回执增加可选 auto_recovery 状态，不新增业务表/供应商提交尝试。`canvas_comfy_recovery.CanvasComfyRecovery` 与图像恢复模块分别共享手动/后台单飞，Comfy 异步单次 inspect 复用原状态解析，归档继续复用 main 的既有实现。启动索引只扫描一次，运行中的失败由入口完成钩子通知，避免周期扫描全部历史。配置/owner 验证、维护暂停、退避与停止属于本闭环；不是完整业务维护写屏障、独立 Worker 或多实例调度。初次生成仍保留原执行路径，本候选不重写所有协议/运行时。
