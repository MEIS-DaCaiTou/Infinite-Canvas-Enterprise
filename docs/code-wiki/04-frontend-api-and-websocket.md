# 前端、API 与 WebSocket

2026-10-28 接口核对基线：10.9 产品源码 `0dce14f`。本章下方日期段是历史采集记录，其中“候选/未发布”只代表当时；现行状态见 [CURRENT](../CURRENT_PROJECT_STATUS.md)。10-24退出的项目工作台、共享、费用和预算路由不能按历史段落作为10.9接口调用。

2026-10-26队列增量已随10.9发布：管理员 GET/PUT `/enterprise/api/admin/comfy-queue` 配置算力分组/并发、个人额度和逐工作流等待；GET `/enterprise/api/me/comfy-queue` 返回本人用量，内部调度由原 Upstream 执行。经典画布区分 `platform_queued` 与后端排队；其他供应商保持原调度。

<a id="本地角色库接口未发布"></a>

### 角色库接口（10.10/10.11；人体交付续修另列）

资料接口已随10.10交付，10.11沿用，不属于正式10.9。本地人体交付修复不修改接口；新前端不再用local_preview_available选择渲染器，统一加载随包原Liblib人体及其依赖。此修复尚未发布。`character-studio.js`共用以下同源会话接口，角色接口只管理创作角色资料及已有图片引用；独立创建页使用原API图片任务生成参考图；“角色”不指系统权限角色。开发者维护HTTP/服务契约，前端维护者同步资料表单与两类画布适配器。

| 方法和路径 | 请求/响应与行为 |
| --- | --- |
| `GET /enterprise/api/me/characters` | 返回`{schema_version:1,owner_id:当前账号ID,characters:[...]}`，只读本人，按updated_at降序；每次核对素材访问，响应补充`unavailable_images`。 |
| `GET /enterprise/api/me/characters/catalog` | 返回`{schema_version:1,characters:[...],local_preview_available:布尔}`，只读目录；公开PR缺省目录为空且预览标记false。开发机另有未提交的10个参考角色和可选WebGL对照，仅齐备本地依赖时标记true，不发布私人素材或将原站内容纳入PR。 |
| `POST /enterprise/api/me/characters` | 完整资料：name（必填1–80字符）、description（≤2000）、gender、age_group、region、images（1–12个本地图片URL）、可选cover_url（本地图片URL）、archived（布尔，默认false）；返回新记录，自动生成id/revision1；可选`create_request_id`为32位小写十六进制，同账号首次将其作为id，相同资料重试返回原记录，资料不同409；PUT禁止此字段。 |
| `PUT /enterprise/api/me/characters/{id}` | 完整替换资料，并要求正整数`expected_revision`；比较成功后revision加1。传archived=false可恢复，不接受客户端owner。 |
| `DELETE /enterprise/api/me/characters/{id}` | JSON仅`{expected_revision:正整数}`；执行归档，返回`{archived:true}`，不删除原图或既有画布节点。 |

记录字段为`id/name/description/gender/age_group/region/images/cover_url/archived/revision/created_at/updated_at`，时间为Unix毫秒。gender取`unspecified/female/male/neutral/other`；age_group取`unspecified/child/teen/young/adult/middle/senior`；region取`unspecified/east_asia/south_asia/europe/africa/americas/middle_east/other`。cover_url可与参考图分离，独立核对授权；旧记录缺省时以首图为封面。允许PNG/JPG/JPEG/WebP/GIF，仍由原资源规范化和访问权限校验决定可用性。上传复用`POST /api/ai/upload`，不新增上传接口或任务事实源。创建页POST `/api/canvas-image-tasks`使用已有provider_id/model/prompt/reference_images，n固定1；提示词增加正面全身、简洁背景的角色构图指令，角色资料保存原始用户描述；GET `/enterprise/api/me/generation-tasks/{id}`读取本人状态、输出和实际call_source，再由用户确认保存。待受理回执先存按owner_id隔离的sessionStorage；GET续查不POST生成，明确拒绝（400/401/403/404/413/422/429）可修正后重新提交，网络/5xx/408不自动重发。无编号时只能核对日志后关联本人原任务。生成界面未套用原站14积分，使用原平台计费；原图片接口不支持幂等重发，未知状态不能以重试生成代替查证。

JSON请求上限32KiB，每账号最多500条（含归档）。成功200且no-store；字段/JSON错误400、未登录401、素材越权403、本人记录不存在404、版本冲突/数量上限409、请求超限413、文件损坏/未知格式/存储不可用503。409不自动提高版本重试覆盖；页面草稿仅在同一页面关闭重开时保留，刷新或离开页面不保证保留。官方目录只允许`/static/characters/`公开内置图片。`characterRef:{id,revision}`只是画布节点来源快照，不赋予共享权限或实时更新节点。目录记录可额外返回asset_labels，用于已有参考图名称；它不表示已具备对应资产生成任务。UI筛选按同一维度多选取并集、不同维度取交集，恢复原版筛选枚举，旧adult/other/south_asia/americas存量资料仍可编辑。数据生命周期与专业编辑未完成项见[架构7.6](../../ARCHITECTURE.md#76-2026-10-28-角色库本地实现与资源复用)。

### 10.9 ComfyUI 队列与原任务接口

| 方法和路径 | 契约与权限 |
| --- | --- |
| `GET /enterprise/api/admin/comfy-queue` | 管理员读取 `policy` 和 `status`；后端名称与任务状态受管理员权限保护。 |
| `PUT /enterprise/api/admin/comfy-queue` | 管理员提交完整 policy；字段包括 `user_running`、`user_outstanding`、`default_workflow_waiting`、`backends`、`workflows`。数值为1–128整数，运行上限不大于未结束上限；列表变化或有未结束任务时变更算力分组会返回409。 |
| `GET /enterprise/api/me/comfy-queue` | 已登录用户读取本人的 `running`、`waiting`、`outstanding` 和 `limits`；不返回其他人的列表或资源健康。 |
| `GET /enterprise/api/me/comfy-tasks?canvas_id=...` | 按认证用户与画布读取 Comfy 原任务摘要，返回 `items`。 |
| `POST /enterprise/api/me/comfy-tasks/{task_id}/cancel` | 按认证身份取消本人的指定任务；平台等待可直接取消，已提交后端需等待原任务状态确认。越权/不存在为404，无受理身份为409，不支持逐笔取消为501，结果暂不可确认可为503。 |

队列默认每人运行1、未结束3、每工作流等待6；后端默认容量1，管理员可配置。`backends` 每项为 `url`、`resource`、`capacity`，`workflows` 每项为 `name`、`waiting_limit`；同资源组容量必须一致。配置存于 `STATE_ROOT/comfy-queue`，任务回执仍由原 journal 和所有权映射管理。服务端从会话确定身份；内部 `/_enterprise_internal/` 路由只用于可信进程间调用，不是客户端接口。详情以 `enterprise/comfy_queue.py`、`comfy_queue_api.py` 和 `canvas_comfy_control.py` 为准。

2026-10-25 ComfyUI长任务：public_comfy_task复用原回执phase弥合本地超时→续查调度接管窗口，已受理且仍可跟踪的任务不对外返回终态失败或旧500字段；人工暂停及明确执行失败保留原处理。CanvasComfyRecovery只查询原backend/prompt_id，未新增POST或恢复状态表。经典画布runComfyNode的忙状态覆盖整个await，finally才解除，避免2秒后重复点击；生成结果及来源仍走原链路。

2026-10-25经典画布Comfy素材输入：renderComfyImages委托原renderImageInputList呈现缩略图、序号及同一拖拽处理；refreshComfyInputViews按runtimeFields识别图片组、保持连接刷新时的媒体预览。排序仍保存gen.inputs、运行仍由orderedSources→canvasValues构造请求；reorderInput只刷新当前节点，不新增数据模型或重新生成。对应实际交互与请求顺序检查纳入test_comfy_io.py调用的test_comfy_input_order.js。

2026-10-25自定义ComfyUI指令映射：`comfy-workflow-fields.js`在上传前检查连线提示词的输入映射，明确role=prompt的多个字段接收同一创作指令；未分类旧次要文本保持配置。服务端`enterprise/providers/comfy_workflow.py`依据可信配置写入创作字段，缺少映射时报错，保留系统/负面提示词及分支开关。main.py只向原领域函数传递prompt，不增加提交或重试分支。开发副本普通/增强指令通过原设置页配置，未改原工作流图；出图效果待人工实测。

2026-10-25设置反馈边界：企业注入账号栏由`enterprise-shell-ui.js/css`负责文字及配色，后台词表`i18n/admin.js`复用既有i18n-core及studio-lang-change/storage事件，动态数量/标题不附着初始占位翻译。project_homepage复用原feature flags和审计入口，仅允许全局设置；网关注入canOpenProject控制项目主页按钮，关闭时管理员也不绕过，不改变系统更新接口。ComfyUI定义刷新仍使用原工作流GET入口并通过workflow_backend校验所选后端，选项编辑仅作用于字段配置及对应预览select；`comfy-preview-links.js`只维护测试画布实际端口的SVG曲线和尺寸监听，不涉及生成、保存或供应商适配。

2026-10-25渠道密钥平台选择：`department-credentials.js`复用原GET /api/config平台目录，仅保留id/name/enabled/managed_source_supported用于呈现；新建仍向原业务来源接口提交provider_id，不新增路由或自建供应商配置。public_provider能力标记复用当前任务受理的is_zhenzhen判定，非管理员脱敏继续过滤地址和密钥，不过滤能力布尔值；该标记不授予调用权限。当前非贞贞平台不宣称渠道密钥调用已接通。

2026-10-25共享下拉呈现：17个HTML入口显式载入`studio-select.js/css`，事件委托接管现有单选select的弹层，原select仍是表单值与业务事件的来源；不为每个动态节点绑定监听或增加全树观察器。纯定位函数处理视口边缘、有限高度及展开方向，原生popover顶层避免祖先缩放/overflow影响。`StudioDropdowns.openPanel/closePanel`供智能画布既有参数面板及聊天模型/尺寸面板复用，保留原业务按钮与回调，不复制模型、任务或供应商规则。此增量现已随10.9交付。

2026-10-24成员后台：`admin-members.css`只负责后台样式；`admin-navigation.js`组织原管理分组，`admin-members.js`负责列表/详情选择与筛选呈现，通过回调复用admin.html原账号操作和department-members组织服务，不直接增加业务API。`admin-embedded-pages.js`只承载个人中心dialog与日志内容区，复用原profile/logs页面和认证接口；`admin-embedded-mode.js`及`admin-embedded.css`仅在embedded=admin时启用内嵌外观。组织/凭据服务、任务身份及安装模块不依赖这些呈现组件。此增量现已随10.9交付，设备反馈仍分列。

2026-10-24范围收缩：无限画布原目录直接加载canvas-list.js；workspace/project-results/shared-canvas/call-source-picker/budget-alerts的界面与脚本退出。department_api保留部门、成员、来源授权/轮换及精简管理context；department-credentials.js使用原后台组件，不加载原business工作台。原两类画布回到既有读取、所有权和保存接口，媒体复用与任务身份模块保留。以下旧工作台接口/脚本记述仅为历史实现，不代表10.9仍可访问。

2026-10-24导航候选：canvas-list在index的frame-canvas中运行，成员管理链接进入顶层/enterprise/admin；后台“返回画布”也指定_top回根首页。两处使用浏览器原生链接target，不让根首页进入子frame；Gateway原守卫仅在子frame隐藏重复账号栏，继续执行权限治理，不改变经典/智能画布编辑或目录在原frame中的导航。两级JS缓存版本同步更新，连续往返及项目/两类画布的验证边界见[CURRENT](../CURRENT_PROJECT_STATUS.md)。

2026-10-18 LLM 任务续包（开发候选）：`canvas-llm-tasks.js` 共用提交前保存 ticket、单次 POST、刷新后 GET 原任务和导航守卫。经典 LLM 节点/聊天与智能画布 Prompt 的原操作不变；节点 `llmTask` 保留平台 ID/状态，保存重开后回填输出正文或聊天记录。任务中心增加「LLM 文本」筛选，复用原正文弹窗和 Prompt 复用入口；有待执行回执的运行按钮改为「查询原任务」，未知时「新建运行」提示可能重复费用，只有用户主动新建运行才再提交。正常轮询状态不变时不重复安排画布保存。保留旧文本直到新结果到达，不将结果写入已经切换的画布。当前状态/模拟与真实调用限制见 [CURRENT](../CURRENT_PROJECT_STATUS.md)。

2026-10-18 来源关联增量（开发候选）：`task-canvas-context.js` 共用来源构造与 `focus_node` 识别；两类画布在新持久生成请求附带来源，在打开来源画布时选中并居中原节点。现有 `generation-task-center.js` 详情增加「定位原画布」与按项「放入当前画布」；采用原日志面板、主题变量与胶囊按钮，不增加页面。复用前重新读取有权限的详情，异步完成后检查仍在同一目标画布；文本使用原 Prompt 节点，其他媒体使用原素材节点，保存 `sourceTaskId/sourceResultId` 并沿用原保存重开逻辑。不再调用生成接口。无来源旧任务和不可访问来源明确提示；缺失原节点仅打开画布。真实状态见 [CURRENT](../CURRENT_PROJECT_STATUS.md)。

> 源码参考快照（2026-10-13）：main@e89a288（已合并 #154/#155/#156）；产品功能源码基点 #156@4bdd9a1 保留；C5/C6/C7 已合并，构建与验收范围仍引用其准确记录。本文是代码/运行参考，当前 PR/CI、Release 和验收只见 [CURRENT](../CURRENT_PROJECT_STATUS.md)，实施顺序只认路线图。

[返回索引](./README.md)

2026-10-22 费用候选：原业务页按 `/api/business/costs?before=...` 加载更早事件，范围切换用原epoch丢弃过期响应。`GET /api/business/budget-alerts` 复用原预算/费用投影，仅返回授权负责人/公司管理员的当前期间超额提醒；`budget-alerts.js` 在原首页、后台、费用页载入和每分钟可见时读取。链接携带费用tab和授权范围，已知晓为账号浏览器设置；不调用生成、任务恢复、消息发送或业务写入API。

2026-10-22 未合并项目内容候选：`project-results.js` 在原首页请求 `/enterprise/api/business/workspace/tasks` 及任务详情、`outputs/{index}` 和显式 `/reuse`；完整画布通过 `/workspace/canvases/{id}`、`resources/{index}/{filename}` 读取，由 `shared_canvases` 每次检查项目权限。共享项直接打开原 `canvas.html` / `smart-canvas.html` 的只读模式，`shared-canvas.js` 复用原节点/连线/媒体，不增加画布预览器；副本走原创建/保存API。`department-members.js` 在既有 admin 成员页使用 `/member-workspace` 和原部门分配API，费用仍走原角色授权。此增量补齐下文目录快照中尚未接入的创作内容，不激活Schema3/4。

2026-10-22 未合并目录候选：`canvas-list.html` 经 `canvas-workspace-boot.js` 按已激活 schema 能力加载原脚本或 `canvas-workspace.js`。后者请求 `/enterprise/api/business/workspace/context`、`/workspace`，并通过 `/workspace/folders/{id}`、`/workspace/archive` 更新树关联/归档；原项目创建、画布创建及 `/api/canvases/{id}/meta` 保持原协议。目录服务位于 `enterprise/canvas_workspace.py`，不由前端授予资源访问；完整成果只读预览尚未接入。

## 1. 前端技术形态

前端是原生 HTML/CSS/JavaScript，不存在 `package.json`、React 构建或 npm 启动步骤。Tailwind 与 Lucide 以仓库内静态脚本形式加载；主题、国际化、触摸/鼠标适配为共享脚本。

这意味着：

- 修改后由 FastAPI 直接提供文件，无 bundler 编译阶段。
- 缓存版本通过 HTML 中资源 URL 的查询串维护。
- 大页面脚本持有大量可变全局状态，回归必须覆盖真实浏览器交互。
- 企业 Gateway 会对旧页面注入用户导航与权限守卫。

2026-10-16 候选增量（`codex/model-workflow-selection-20261016`，Base main@39f4b02，未合并/发布）：`model-picker.js` 的个人模型弹窗复用 `comfy-outputs.css` 组件和主题，新增 `model-picker.css` 只补列表/搜索/勾选；账号存储与已有节点模型不变。`GET /api/workflows` 默认仅返回启用项，设置页通过 `include_disabled=true` 查看全部；原配置的可选 `enabled` 管理画布可用列表。未配置 shipped 默认隐藏，历史配置和自定义继续兼容；两类画布保留停用/移除身份、不自动替换且不循环重载。固定本地入口及配置边界见[产品记录](../ops/PRODUCT-INTEGRATION-FIXES-2026-10-13.md#2026-10-16-个人模型与工作流可用列表续修候选)。

2026-10-18 候选增量（Base main73d2b67，未合并/发布）：`canvas-task-query.js` 的 `runVideo` 一次提交后调用 `onAccepted` 保存平台任务 ID，`waitVideo` 只读轮询，`queryVideo` 只查询原任务。`canvas.js` 在输出节点保留视频 pending，`smart-canvas.js` 沿用 pendingTasks；重新打开后据此续接视频、保留旧结果并防止重复回调追加。新视频异步分支校验画布/节点/任务身份，离开后不将旧结果和日志写入其他画布。复用现有失败区域及查询按钮，无新页面或 CSS；回执/模拟与 Browser 验证边界见 [工程记录](../ops/PAID-SUBMISSION-STOPLOSS-2026-10-13.md#2026-10-18-两类画布视频任务保存重开与结果续接)。

## 2. 工作台与普通画布

### `static/js/canvas-list.js`

负责项目/画布列表、创建、重命名、移动、排序、置顶、回收站和页面跳转。所有列表必须接受 Gateway 返回的当前用户可见集合，不能假设 Upstream 文件目录天然隔离。

### `static/js/canvas.js`

2026-10-29本地修订：保存成功后只有页面仍含旧gate列表才异步刷新目录；独立编辑页返回由canvas-list自行加载，避免发出即将被导航取消的多余请求。原保存PUT、版本冲突和save-before-return流程保持。

关键函数：

| 函数 | 职责 |
| --- | --- |
| `screenToWorld()`、`applyViewport()` | 屏幕坐标与世界坐标换算、平移缩放 |
| `fitAllNodesViewport()`、`toggleZoomPreview()` | 视图适配与缩放预览 |
| `scheduleSave()`、`saveCanvas()` | 防抖保存画布 |
| `serializableCanvasNode()` | 去除临时运行态，生成可持久化节点 |
| `loadCanvasList()`、`openCanvas()` | 加载并进入画布 |
| `syncRemoteCanvasNow()`、`checkRemoteCanvasVersion()` | 保存/远端版本同步与冲突感知 |
| `refreshMissingCanvasAssets()` | 修复或刷新缺失素材引用 |
| `createCanvas()`、`createSmartCanvas()` | 创建普通/智能画布 |
| `returnToCanvasManager()` | 返回工作台 |

文件还包含图片/视频节点、选择与拖动、连线、最小地图、Provider 参数、生成轮询、历史和编辑器逻辑。

#123 已合并的 `static/js/canvas-task-query.js` 为经典/智能画布共用原任务查询请求。已绑定回执按本地 ID 调用 `/api/canvas-image-tasks/{task_id}/reconcile`，客户端不指定供应商地址/Key/上游 ID；旧记录保持原查询路径。已有“查询结果”按钮找回后更新原节点并保存；部分结果提示写入现有生成日志，无新增页面或必填设置。准确 GUI 与限制见[工程记录](../ops/PAID-SUBMISSION-STOPLOSS-2026-10-13.md)。

## 3. 智能画布

### `static/js/smart-canvas.js`

智能画布维护节点、连线、分组、循环执行、撤销、任务状态、生成日志和工作流导入导出。

关键函数族：

- `snapshotForUndo()`、`pushUndo()`、`performUndo()`：撤销快照。
- `canvasForStorage()`、`serializableSmartNode()`：持久化模型。
- `exportSelectedSmartWorkflow()`、`importSmartWorkflowFile()`：工作流交换。
- `createImageNodeAt()`、`arrangeSmartGroupMembers()`：节点与分组布局。
- `normalizeSmartGenerationLogs()`、`mergeSmartGenerationLogs()`：生成日志兼容与合并。
- `smartLoop*`、`smartCascade*`：循环/级联执行状态。

智能画布与普通画布是不同的大脚本实现，修复一个页面的保存/资源行为时不能假定另一个页面自动获得同样修复。

## 4. 素材与设置

| 文件 | 主要职责 |
| --- | --- |
| `asset-manager.js` | 本地素材树、上传、批量选择、移动删除、标签/描述、预览 |
| `api-settings.js` | Provider CRUD、协议识别、密钥输入、模型获取、连接测试、CLI 状态 |
| `comfyui-settings.js` | ComfyUI 实例与工作流配置 |
| `comfy-workflow-fields.js`（#158 已合并） | 设置页/两类画布共用的字段推断、旧配置修正、输入检查与参数映射 |
| `image-preview.js` | 图片预览通用逻辑 |
| `history-bulk-manager.js` | 历史记录批量操作 |
| `theme.js`、`i18n.js` | 主题和文本本地化 |
| `touch-mouse.js` | 触摸与鼠标交互归一化 |

设置响应经 Gateway 脱敏，页面中显示“已有密钥”或预览值不等于前端持有明文密钥。

## 5. 企业页面

| 页面 | 访问范围 | 功能 |
| --- | --- | --- |
| `/enterprise/login` | 未登录 | 用户名/密码登录 |
| `/enterprise/profile` | 已登录 | 当前用户资料与密码 |
| `/enterprise/logs` | 受权限控制 | 操作日志 |
| `/enterprise/admin` | admin/super_admin | 成员、归属、权限开关、更新中心 |

更新中心的“可见”与“可执行”不同：管理员可进入后台，但更新操作要求当前超级管理员、全局 `system_update` 开关有效、紧急更新开关开启，并再次确认当前密码。

## 6. API 领域分组

`main.py` 的路由数量多，建议按领域定位：

| 领域 | 典型前缀/接口 |
| --- | --- |
| 页面与版本 | `/`、`/canvas*`、`/api/app-info` |
| 文件/媒体 | `/api/upload`、`/api/view`、`/api/media-preview`、`/api/download-output` |
| 项目/画布 | `/api/projects*`、`/api/canvases*`、保存/删除/恢复/彻底删除 |
| 对话 | `/api/conversations*`、`/api/chat*`、流式对话 |
| 本地素材 | `/api/local-assets*`、`/api/canvas-assets*` |
| 素材库 | `/api/asset-library*`、共享文件夹 |
| Provider | `/api/config`、`/api/providers*`、`/api/models` |
| 画布任务 | `/api/canvas-image-tasks*`、`/api/canvas-comfy-tasks*` |
| RunningHub | `/api/runninghub*` |
| ComfyUI | `/api/comfyui*` |
| 生成工具 | ModelScope、Angle、Z-Image、视频与图像工具接口 |
| CLI | `/api/codex*`、`/api/gemini-cli*`、`/api/jimeng*` |
| 更新中心 | `/api/update-mvp/*`（定义在企业 Router） |

## 7. 更新中心 API

| 方法与路径 | 行为 |
| --- | --- |
| `GET /api/update-mvp/access` | 返回角色、是否可操作、全局开关和权限来源 |
| `GET /api/update-mvp/check` | 读取 current pointer/当前 Manifest，并查询最新合规 GitHub Release |
| `POST /api/update-mvp/prepare` | 下载三件套、校验并创建 READY 作业 |
| `POST /api/update-mvp/jobs/{id}/execute` | 再验密码与当前状态，创建执行保留并触发 Runtime handoff |
| `GET /api/update-mvp/jobs/{id}` | 查询作业状态 |
| `GET /api/update-mvp/diagnostics` | 返回或导出脱敏诊断 ZIP |

## 8. 候选个人模型与内置能力

#156 在经典/智能画布共用 model-picker.js。节点“我的模型”就地搜索、勾选及保存当前平台/类别，不另开普通用户设置页面；已有模型身份保留。GET/PUT `/enterprise/api/me/model-preferences` 由 Gateway 直接处理，账号来自认证上下文，不属于透传路由。

内置能力经 `/api/config` 用户投影读取；Zhenzhen 已确认模型自动限制不支持的质量/画幅/分辨率，API 设置只保留折叠的“临时兼容新模型”。素材扩展在已登录平台页同源导入，不访问普通用户无权读取的管理员配置。后台操作原因/确认与后端一致，不放宽创建管理员权限。

模型选择与明确请求参数已共用；两类画布的尺寸计算和部分交互仍重复，相关改动继续减少耦合。运行验收与未列矩阵见产品实现记录。

## 9. WebSocket 事件规则

Gateway 不应透明广播所有 Upstream 事件。事件过滤至少考虑：

- `client_id` 是否唯一属于当前用户。
- 任务 ID 是否由当前用户拥有。
- 历史记录和生成资源 URL 是否归当前用户。
- 素材库更新是否在用户可见范围。
- 管理员是否具有该事件的扩展可见性。

SEC-P0 额外固定传输边界：只接受同源 `/ws/stats`，浏览器到 Upstream 只转发精确字符串 `ping`；服务端事件类型必须进入显式已知集合，未知类型、缺失类型和非 JSON 消息对普通用户与管理员都默认拒绝。管理员身份不会把未知协议变成可见协议。

新增异步业务时，应同时实现 HTTP 受理归属、查询权限、结果资源归属和 WebSocket 事件过滤四个环节。

## 9. ComfyUI 输入修复候选

基于 main@e89a288fe 的 [修复记录](../ops/COMFY-WORKFLOW-INPUT-REPAIR-2026-10-14.md)：`normalizeWorkflow()` 在读取时纠正旧 `filename_prefix` 媒体类型，保留稳定字段 ID；`inferType()` 识别新字段；`kind()`、`requireMedia()`、`canvasValues()` 与 `paramsFromValues()` 服务设置页、普通/智能画布和级联。缺少素材按名称及节点定位，前缀是文本。HTML 先加载共用脚本再加载对应页面脚本。后端继续原上传/任务/归档入口，素材同步明确排除前缀；没有新 API 或 Schema。

## ComfyUI 双视图与指定后端候选

static/js/comfy-workflow-session.js 提供共享输入、上传互斥、运行快照和结果身份；设置页两处视图按字段 ID 读取它，输入修改后旧结果标记。/api/workflows/{name}/run 的 async_task=true 返回既有 canvas-comfy-tasks 回执，省略时保持同步结果契约。/api/upload 的 workflow/backend 可选参数将上传绑定到已配置后端，返回真实 comfy_name（含 subfolder）；两类画布自定义路径携带相同后端提交。GET workflow 的 include_definitions=true 为设置页读取目标 object_info，普通画布只使用保存的字段配置。多图/视频/音频/文件按实际 items 呈现，视频不会被当第一张图片丢弃。候选未发布；细节和未验收范围见 ComfyUI 修复记录。

候选任务 GET 的 resume=true 只领取已有受理 ID 的查询；普通轮询不自动无限重开超时跟踪，服务重启中断允许恢复一次。未知提交没有上游 ID 时不重新生成。

2026-10-15 #161 增量：runtimeFields 合并配置图片输入组，范围校验/上传顺序由 comfy-workflow-fields.js 共用。comfy-outputs.js/CSS 提供文本摘要、统一正文弹窗、复制/下载及 Prompt 节点复用，沿用日志面板的主题变量和按钮层级。经典 generatedOutputs/Output 和智能媒体列表保留类型、文本及结果身份，selectedResult 存储明确选择的快照；普通连线把文本送入提示词，不列作图片。已有画布 JSON 存储，无新页面/用户模板。GUI 是 loopback 协议夹具证据，真实 GPU 和内置 Browser 下载事件限制见实施记录。

## 2026-10-15 本人生成任务（#162 已合并）

#161 已合并 main6603550，未进入正式 Release。其共用文本视图/Prompt 复用作为本包依赖，沿用原主题变量和操作层级。

`static/js/generation-task-center.js`/CSS 在经典 `logModal/logList` 和智能 `smartLogModal/smartLogList` 中增加任务页签，入口脚本只提供已有预览与创建 Prompt 回调。读取 `GET /enterprise/api/me/generation-tasks`（cursor/status/kind/limit）及 `GET /enterprise/api/me/generation-tasks/{id}`；默认仍显示原生成日志，关闭后停止列表刷新。只有明确点击续查才调用原 `/api/canvas-image-tasks/{id}/reconcile` 或 Comfy GET `resume=true`，不调用生成端点。切换筛选期间旧响应不能覆盖新列表，未完成请求结束后补读当前筛选。本人目录不等于管理员全员任务/费用视图；#162 已独立复审并合并 main6d9d77d，尚未发行。

任务目录读写协调补记：生产路径由 Gateway 的 generation_task_api 认证并覆盖身份，通过既有回环 HTTP 连接池读取 generation_task_routes 的内部路由；Repository 注入上游同一个 CANVAS_TASK_JOURNAL，共用既有互斥锁，Gateway 不直接打开回执文件。Windows 普通读取句柄阻止 os.replace 的对照已复现；改为同一对象协调后，并发读取/30 次回执写入通过。公开 Gateway 拒绝整个 /_enterprise_internal/ 命名空间，客户端伪造身份无效；业务进程不可用时返回 503，不自动生成。原生文件接口试验未保留，无新平台适配/数据库结构。

任务中心审查修正：音频保留原文件链接，图片/视频才调用既有预览；详情资源投影仅使用已筛选结果 URL，不递归正文/错误/名称。未实际提交的本地失败显示明确失败，重启/真实受理未知仍待核对。

自动恢复候选继续使用相同任务页签和详情：列表/详情的 auto_recovery 含状态、次数、最近/下次查询及脱敏原因；后台 waiting/querying 时列表继续刷新，终态覆盖中断留下的旧调度显示。只有本次自动续查确认的 queued/running 才显示相应状态，旧的重启前核对记录不能伪报仍在运行。页面关闭不影响服务端调度，前端刷新只读取目录，不发起生成或自动查询操作；手动按钮继续查询原 ID。沿用现有 CSS/主题，无新页面、控件体系或用户配置步骤。


### 视频任务候选接线（2026-10-16，依赖 #163）

两类画布沿用视频生成交互，共用 `canvas-task-query.js` 的 `runVideo`：一次创建平台视频任务，之后 GET 本地记录，失败/未知提示到现有日志核对。任务中心增加 `API 视频` 筛选，复用已有详情、结果预览与“继续查询原任务”；续查 URL 仅含本地 task ID。刷新后从本人目录找回服务器记录，不自动补造当前画布节点或重新生成。HTML 同步缓存版本；布局、组件和设置页面保持原设计。Browser 证据验证实际画布、固定夹具账号和受控查询，不代表真实付费视频或播放验收。

### 部门项目界面候选（2026-10-20）

本段为历史候选：10.9 中下述 `business.html`、`business-workspace.js` 和 `call-source-picker.js` 已退出源码树，不能作为当前可用文件或入口。

相对 #186 Head `c3d2921` 的未合并候选新增 `enterprise-static/business.html`、`static/js/business-workspace.js` 与 `static/js/call-source-picker.js`。Gateway 的 `/enterprise/business` 是登录后入口；`enterprise/department_api.py` 的 context/directory/project-members/source-grants/tasks 读取继续复用领域权限。来源控件只提交来源 ID 与项目 ID，不取密钥原文；原任务续查不读取当前节点选择。部门任务页面仅元数据，不能从公开项目推导任务/费用或资源访问权限。schema 3 未激活，旧页面兼容与内容授权仍未完成；准确状态以 [CURRENT](../CURRENT_PROJECT_STATUS.md) 为准。


### 旧入口来源兼容候选（2026-10-21）

`enterprise/legacy_call_sources.py` 在 #187 候选上复用来源策略、LLM journal/归档与费用投影。在线生图和聊天图片使用原持久图片执行器；文本只执行一次，流式回执保留原凭据版本，收到正文后先保存再归档，未知不自动重提。Agent 的路由文本与图片分别绑定来源。管理员通过现有来源页明确接纳旧共享密钥；新增 `/api/call-sources/adopt` 受既有管理员设置策略及领域权限约束，原文只在服务端读取。在线/聊天复用 `call-source-picker.js`，只携带来源/项目 ID；不新增模型配置或队列，不激活 Schema3。准确交付状态见 CURRENT 与原 PR。

### 2026-10-21 经典画布性能候选

`codex/issue-canvas-performance-10-4`（Base main `0d0078f`，未合并）新增 `static/js/canvas-media-retention.js`。`CanvasMediaRetention.transplant` 在同画布、同节点内按结果身份/媒体 URL 及重复槽区分播放器；现代浏览器使用原子移动，旧路径保留已有逐元素播放状态恢复，不再使用全局 URL 状态覆盖多个卡片。`CanvasRunPreparation` 按画布与节点 ID 临时标记尺寸与来源保存阶段，并沿用远端同步延后机制，不持久写入任务或画布、不限制受理后的既有并发。经典 `runGenerator` 保存一次来源后传给该批子任务，`createCanvasImageTask` 提交前仍核对当前画布/节点；冲突和失败继续由既有保存/任务契约处理。范围与准确状态见 [CURRENT](../CURRENT_PROJECT_STATUS.md) 和 [Issue #188](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/issues/188)。

### 本地预览补充：ComfyUI逐笔取消（2026-10-25）

`enterprise/canvas_comfy_control.py`提供本人画布任务列表与取消编排，Gateway仅转发可信登录身份；原后端和prompt_id由既有journal读取。`providers/comfyui.py`负责单job取消协议及execution_interrupted解释，不使用全局中断回退。`static/js/canvas-comfy-tasks.js`只负责OUTPUT卡片状态、悬停详情与右键逐笔操作，复用StudioDropdowns定位；画布主脚本连接已有占位卡和结果呈现，原任务ID与运行快照随结果保留；完成/取消继续走原journal、CanvasComfyRecovery与AcceptedTaskRecovery，无另建任务系统或Schema变更。此增量现已随10.9合并和发布；真实GPU验证与GUI覆盖范围见 CURRENT。
