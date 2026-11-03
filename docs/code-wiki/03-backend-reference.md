# 后端类与函数参考

2026.11.1新增POST /enterprise/api/admin/comfy-queue/{task_id}/release：系统管理员验证后转原内部队列服务，Journal在原锁内幂等写queue_release，Queue排除其本地占用并wake。404不存在、409运行/排队/已明确结束不适用；不重提、不调用后端取消，不改原失败事实。已释放且有prompt_id仍可查原任务，真实后端排队仍占算力容量；复用db.log_action，不新增业务表或记录备份。

COMFY1103：providers.comfyui.ComfyNotSubmittedError只覆盖连接建立前的已知错误，main.run_canvas_comfy_task记503/COMFY_NOT_SUBMITTED、failed/not_submitted、recovery_required=false；原ComfyQueue据原终态释放预算。ReadTimeout、ProtocolError/重置、未分类ConnectionError继续未知受理，无新重试。generation_tasks.describe_task复用public_comfy_task输出can_cancel/cancellation_pending，归档阶段及已取消/明确失败不提供取消；原内部/公开逐笔取消接口与权限不变。生产旧记录仍原样，准确现场证据/本地测试/待交付边界见收敛记录。

2026-11-03 AUTH1103：QuerySnapshots.library_lookup/LibraryLookup集中原资产文件的ID/受保护URL到位置映射、容器导航和原顺序候选投影。db.asset_library_query_snapshot按当前用户潜在授权候选，在同一只读事务补候选与容器事实；400参数一批，原授权优先级保留。interceptors.handle_collection_query只对普通用户分页/轻目录调用，再交原filter_asset_library；管理员、旧完整GET与写入未改。缓存随文件修订，沿用源8MiB预算，超限不留缓存，权限每次重读。新旧页面/游标精确对照和42项定向通过；并发复测与限制见原收敛记录。

2026-11-02 WINDOW1102没有修改后端查询或权限实现。新增隔离真实Gateway/JWT读取测量：1k→10k资产的24项响应约5.1→5.2KB，8账号隔离及当前撤权通过；10k/16路闭环P95约5.7秒。源码仍每次读取全量asset对象/资源归属，再过滤资产树；本机分析还观察到数据库路径检查及源解析成本，不将单次分析写成现场唯一根因。后续先做授权查询范围/可重建投影的专项收敛，保留优先级和旧接口，不缓存当前授权或跳过路径检查。媒体、网络、写入及长期并发尚未覆盖。

2026-11-02 UPLOAD1102：`local_uploads.metadata_items(root, allowed_urls)`对普通用户按当前资源授权直接取文件元数据，管理员扫描保留DirEntry；不读图片内容/旁车，不做授权决策。`is_picker_query`只识别原分页请求；Gateway覆盖`x-enterprise-upload-source: canvas-inputs-v1`（其他请求剥离调用方提示），`upload_picker_index(include_uploads=False)`保留原画布输入参考而省去上传树。post链按当前归属在Gateway补上传元数据并分页，读取失败HTTP503；无标记旧上游按原完整包过滤。仍扫描画布参考、读取本人的资源授权集合，资产写入内部回包未优化。

2026-11-02 COLD1102：`iter_canvas_media_entries`集中原遍历、URL去重及类型判断；`character_asset_urls`只取图片URL，`extract_canvas_assets`仍构造原完整记录，200画布/1万引用逐项输出对照一致。首次引用缓存构建仍读画布JSON，并非持久索引。原资产写入可选`catalog=1|true`，Gateway在原归属登记、授权及事件处理后精简公开library及别名，保留操作结果item；无参数与内部回包仍完整。`runtime/child.py`仅增加明确停机时8秒HTTP排空上限，现有任务/生命周期清理路径保留，不能保证阻塞的lifespan在此期限退出。

2026-11-02 READ1102：`local_uploads.kind_ext/display_name`复用原上传规则，`metadata_items`只枚举路径/大小/时间；`main.upload_picker_index`补原画布输入图片，引用来自同一`ResourceReferenceIndex._snapshots/canvas_context`和原提取器。Gateway对上传目录项按资源归属、画布参考按画布归属过滤，再复用collection_query分页。旧完整树/旁车接口不变。

`canvas_asset_context`只匹配本批图片项目；常见ASCII路径避免反复URL解析，Unicode/绝对URL规范化，缓存依文件元数据失效，当前授权在响应时复核。只读POST在通用登记前返回，不产生任务/资源归属或广播。`item_id`/`match_url`在原授权/分类筛选后精确定位；原写入CAS/原子替换保留，COLD1102增加可选精简回包。职责和冷扫描限制见代码边界/原收敛记录。

2026-11-02资产消费者续批：`collection_query.library_catalog`只从已经由原policy过滤的目录生成计数和最多两张分类封面，保留空库/旧categories形状，不写原件；`interceptors.handle_collection_query`在原feature/resource门禁后处理GET的`catalog=1|true`，其他值400；COLD1102在原pre/post链追加写入参数检查与结果投影。旧GET/无参数写入兼容。目录计数、封面与后续分页均复用当前授权，不缓存权限；新测试覆盖两个有资产用户、管理员、旧格式及源字节不变。前端缩略图共用既有media-preview，不新增后台媒体管线。

2026-11-02读接线：`HistoryQueryIndex.rebuild/page`仍共用collection_query与原history身份；`HistoryQueryCache.page/consider/close`仅协调可重建副本。Gateway启动注册、关闭在原threadpool中等待；原history分页先当前授权，再尝试有效索引，缺失/陈旧/不可读时回原JSON。成功JSON页提供已解析快照，单后台线程合并构建，不排队/重复解析，失败退避30秒。超过原8MiB缓存预算才用持久投影，CACHE_ROOT/queries/history-v1.sqlite3；配置开关false重启可禁用。原源坏文件503、源变化cursor409保持，索引错误本身不使正常历史报错。未增加公开API/业务表/授权缓存；全量JSON写、增量维护及异常强杀临时文件处置仍未完成。原影子工具继续只读校对，详细证据见原收敛记录。

2026-11-01查询候选：`collection_query.QuerySnapshots`按文件身份/大小/纳秒时间失效；`history_ids`只复用原history_id的派生值，当前归属每次查DB。`handle_collection_query`位于原pre_process权限链之后，权限过滤先于page/total。`asset_library_ownership_snapshot`在同一只读事务批读原对象/资源归属；旧素材完整响应和分页共用原policy及回退优先级。缓存超8MiB源文件不保留解析树，仍可查询；全量写入与持久索引未替换。

2026-10-31现行本地核对：`main.load_asset_library/save_asset_library`使用document_lock、原子替换与updated_at比较，损坏目录返回503，保存竞争409；单项撤销可keep_file保留字节，批量/分类删除已先提交目录再清库内副本；写入失败保留字节，清理失败可能留孤立文件。管理员画布调整已使用相同文档协调，但SQLite/JSON强杀恢复不宣称原子事务。角色语音复用原journal/dispatcher；未知收费任务不重提。当前PR状态回CURRENT；#170 RunningHub续修尚未进入main，不能从旧候选描述推断已交付。

2026-10-31历史续批：`history_records`统一history.json追加/删除的document_lock和atomic_write_json；异常读取不回空后覆盖，取消5000条隐式截断。企业Gateway原删除已只移除元数据，本批补共同锁、损坏文件503及兼容入口一致性；原媒体授权保留。生成成功/历史失败的`history_warning`不把已付费结果改成失败重提，亦非自动补档。列表内部不可读ID只用于Gateway按权限计数，不传给浏览器。跨文件/SQLite恢复与授权后分页仍见路线图。

2026-10-28 校准：本章各日期的“候选/未发布”保留当时上下文；10.9相关模块的现行接线以源码及[当前状态](../CURRENT_PROJECT_STATUS.md)为准。项目工作台、共享和费用/预算路由不属于10.9当前注册入口。ComfyUI队列、个人用量与逐笔取消参见[接口章节](./04-frontend-api-and-websocket.md#109-comfyui-队列与原任务接口)。

2026-10-18 LLM 任务续包（基于 #174 的独立候选）：`canvas_llm_tasks.CanvasLLMTasks` 使用原 journal、任务归属和调度钩子，在请求断开后执行原 `main.canvas_llm`；`llm_submitting/llm_response` 只在同步 HTTP/CLI 提交边界记录阶段。请求/聊天历史/密钥不写入回执，收到正文通过 `record_llm_result` 先保存，再复用原文本文件归档。平台 GET 读取原任务，reconcile 仅能恢复已收到的本地正文；不会调用供应商或把 chat completion ID 当异步查询 ID。原 `/api/canvas-llm` 兼容保留，新 `canvas-llm-tasks` 入口沿用 Gateway 路由/素材/任务授权；目录增加 `canvas_llm` 类型，无新业务表。状态见 [CURRENT](../CURRENT_PROJECT_STATUS.md)。

2026-10-18 来源关联增量（开发候选）：`task_canvas_context.TaskCanvasSource/accepted_source/describe_source` 复用既有画布文件和 `interceptors.can_access_canvas`，在原 journal 中记录可选来源，不新增业务表。`create_task_receipt` 在执行前校验来源；图片/视频/ComfyUI 请求都可携带此字段，旧调用仍可省略。`GenerationTaskRepository.detail` 仅在当前仍可访问时返回来源标题和定位 URL；原节点删除时保留打开画布入口。`generation_task_routes` 的原详情 GET 可带 `target_canvas_id`，同时核实本人任务、目标画布及具体结果资源后才允许复用，不写入目标画布。Gateway 继续覆盖用户身份；真实状态与限制见 [CURRENT](../CURRENT_PROJECT_STATUS.md)。

> 源码参考快照（2026-10-13）：main@e89a288（已合并 #154/#155/#156）；产品功能源码基点 #156@4bdd9a1 保留；C5/C6/C7 已合并，构建与验收范围仍引用其准确记录。本文是代码/运行参考，当前 PR/CI、Release 和验收只见 [CURRENT](../CURRENT_PROJECT_STATUS.md)，实施顺序只认路线图。

[返回索引](./README.md)

本文只列出理解主链路所需的关键符号。完整路由以源码装饰器为准。

2026-10-28未发布角色库：`character_api.create_router()`在Gateway显式注册，仅从认证会话获取账号；`Characters`核对资料、原媒体访问、期望版本和归档；`CharacterRepository`在一个共享实例锁内比较并复用`local_json.atomic_write_json(create_parent=True)`保存DATA_ROOT个人文件。它不调用生成供应商，也不具备跨进程事务。接口及字段见[角色库契约](./04-frontend-api-and-websocket.md#本地角色库接口未发布)，适用范围、维护责任及未完成项见[架构7.6](../../ARCHITECTURE.md#76-2026-10-28-角色库本地实现与资源复用)。

## 1. 旧业务内核：`main.py`

`main.py` 是单个大型 FastAPI 模块，负责：

- 启动时创建目录、装载配置、执行兼容迁移和恢复任务回执。
- 提供静态页面和媒体预览、下载、上传。
- 保存项目、画布、对话、历史、素材库和 Provider 配置。
- 对接 RunningHub、ModelScope、火山引擎、即梦、OpenAI 兼容协议、Codex CLI、Gemini CLI、ComfyUI 等。
- 维护生成队列、任务查询、SSE/流式输出和上游 WebSocket 统计。

关键符号：

| 符号 | 说明 |
| --- | --- |
| `app` | Upstream FastAPI 实例 |
| `ConnectionManager` | 旧内核 WebSocket 客户端与统计广播管理 |
| `startup_event()` | 建立目录、读取配置、恢复/迁移运行数据 |
| `/api/upload`、`/api/media-preview`、`/api/view` | 文件进入与受控读取路径 |
| `/api/projects*`、`/api/canvases*` | 项目/画布持久化接口 |
| `/api/conversations*`、`/api/chat*` | 对话与流式模型调用 |
| `/api/local-assets*`、`/api/asset-library*` | 素材树、图库、移动删除和标注 |
| `/api/canvas-image-tasks*`、`/api/canvas-comfy-tasks*` | 画布异步生成任务 |
| `/api/runninghub*`、`/api/comfyui*` | 工作流平台与本地 ComfyUI 集成 |
| `/api/providers*`、`/api/config` | Provider 与模型配置 |

维护风险：该文件同时包含路由、存储、Provider 协议和业务状态，模块内耦合高。新增企业授权应优先放在 Gateway，不应在每个旧路由重复实现。

## 2. Gateway：`enterprise/gateway.py`

### `AuthStateMiddleware`

从 Cookie/请求中恢复 JWT，验证用户存在、启用状态和 `auth_version`，把当前主体写入 `request.state.user`。角色或密码变更导致 `auth_version` 更新后，旧令牌失效。

### 生命周期

| 函数 | 说明 |
| --- | --- |
| `startup()` | 初始化企业 DB/schema、HTTP 客户端和 Gateway 运行依赖 |
| `shutdown()` | 关闭转发客户端等资源 |
| `liveness_check()` | `/enterprise/live`，表示 Gateway 事件循环仍能响应 |
| `health_check()` | `/enterprise/health`，汇总 Gateway 与 Upstream 状态 |

### 页面与会话

| 函数 | 路径 | 说明 |
| --- | --- | --- |
| `login_page()` | `GET /enterprise/login` | 登录页 |
| `do_login()` | `POST /enterprise/login` | 校验账号并设置会话 Cookie |
| `logout()` | `POST /enterprise/logout` | 在同源写请求边界内清除会话，避免 GET 触发状态变更 |
| `admin_page()` | `GET /enterprise/admin` | 管理员/超级管理员后台 |
| `profile_page()` | `GET /enterprise/profile` | 当前用户资料页 |
| `logs_page()` | `GET /enterprise/logs` | 操作日志页 |

### 转发

| 函数 | 说明 |
| --- | --- |
| `reverse_proxy()` | 捕获普通 HTTP 路径，只转发 `route_policy` 已登记的方法/路径，再执行认证、功能检查和转发 |
| `_forward()` | 构造 Upstream 请求并处理响应/流式响应 |
| `ws_proxy()` | 建立双向 WebSocket，并调用企业事件过滤 |
| `_build_enterprise_shell_guard()` | 向旧页面注入企业导航与前端访问约束 |

### 路由与浏览器边界：`enterprise/route_policy.py`

- `is_allowed_upstream_route()`：按方法和路径精确匹配 `main.py` 的已审查路由；测试通过 AST 清单防止新增路由静默漂移。
- `is_allowed_public_static_path()`：只允许固定公共静态命名空间，不以 `.js`、`.css` 等后缀推断为公共资源。
- `is_allowed_protected_resource_path()`：资源目录只允许已认证的 `GET/HEAD` 读取，并继续进入归属拦截。
- `is_allowed_websocket_path()`：当前只允许 `/ws/stats`。

Gateway 还对 Cookie 状态变更请求执行精确同源校验；Bearer CLI 请求保持独立兼容边界。登录失败在有限时间窗内按用户名摘要和客户端地址限流，外部跳转、静态目录逃逸和未知路由均 fail closed。

## 3. 认证与角色

### `enterprise/auth.py`

- `create_token(user_id)`：按当前用户身份生成带角色和 `auth_version` 的 JWT。
- `verify_token(token)`：验证签名、过期时间与基本 claims。
- `authenticate(username, password)`：查找用户、验证密码和启用状态。

### `enterprise/roles.py`

- `ROLE_USER`、`ROLE_ADMIN`、`ROLE_SUPER_ADMIN`：固定三角色。
- `normalize_role()`：只接受固定集合，非法值 fail closed。
- `role_from_legacy_is_admin()`：从旧 `is_admin` 布尔值迁移，不凭空创建超级管理员。

## 4. 数据访问：`enterprise/db.py`

这是企业元数据的数据访问层，连接 SQLite 并提供事务级 API。

| 函数组 | 代表函数 | 说明 |
| --- | --- | --- |
| Schema | `ensure_db_schema_in_connection()`、`ensure_db_schema()` | 建表、索引和兼容升级 |
| 用户 | `create_user()`、`list_users()`、`set_user_active()`、`delete_user()` | 旧兼容用户操作；安全治理优先使用 governance 层 |
| 画布 | `record_canvas_owner()`、`set_canvas_owner()`、`set_canvas_project()` | 首次认领与管理员调整 |
| 项目 | `record_project_owner()`、`set_project_owner()` | 项目归属 |
| 对话 | `record_conversation_owner()`、`set_conversation_owner()` | 对话归属 |
| 资源 | `record_resource_owner()`、`record_asset_object_owner()` | 文件 URL 与素材对象归属 |
| 任务 | `record_canvas_image_task_owner()`、`record_task_owner()` | 异步任务归属与关联 |
| 历史 | `record_history_owner()`、`set_history_owner()` | 生成历史归属 |
| 功能开关 | `list_feature_flags()`、`set_feature_flag()`、`set_user_feature_override()` | 全局开关与用户覆盖 |
| 有效权限 | `get_effective_feature_value()`、`can_use_feature()` | 计算 inherit/allow/deny 后的结果 |

## 5. 请求/响应拦截：`enterprise/interceptors.py`

关键入口：

- `pre_process()` / `_pre_process_sync()`：在请求进入 Upstream 前执行权限、资源、任务和设置检查。
- `post_process()` / `_post_process_sync()`：过滤列表与响应，记录新建资源/任务归属。
- `can_access_canvas()`、`can_access_project()`、`can_access_conversation()`、`can_access_resource()`、`can_access_task()`：领域访问裁决。
- `sanitize_settings_response()`：递归移除密钥、Token 等敏感配置。
- `filter_canvas_list()`、`filter_project_list()`、`filter_conversation_list()`、`filter_local_assets()`、`filter_asset_library()`：用户范围过滤。
- `record_resources_from_data()`、`record_event_stream_ownership()`：从普通/流式结果中提取并登记归属。
- `handle_history_delete()`：按拥有者执行历史删除。

该模块是旧业务变为多用户企业版的核心适配层；新增 API 时必须同步判断其请求、响应和 WebSocket 是否带有受保护对象。

## 6. WebSocket：`enterprise/ws.py`

| 符号 | 说明 |
| --- | --- |
| `EnterpriseWsConnection` | 记录连接、用户、客户端与活动状态 |
| `register_connection()` / `forget_connection()` | 连接生命周期 |
| `should_forward_ws_event()` | 按任务/资源/历史归属决定事件可见性 |
| `should_forward_client_message()` | 客户端只允许固定 `ping` 消息，其它消息关闭连接 |
| `send_to_user()` | 向同一用户的活动连接发送 |
| `broadcast_asset_library_updated()` | 素材变化通知 |
| `broadcast_new_image()` | 新图像通知，但仍经过可见性语义 |

## 7. 管理与安全

### `enterprise/admin_api.py`

提供成员列表/创建/启停/密码/角色/删除、删除影响预览、画布/项目/对话/历史归属、功能开关、个人密码和操作日志等 API。

### `enterprise/security_user_governance.py`

安全写操作应走此层：

- 管理员只能治理普通用户；超级管理员治理管理员与系统更新。
- 当前密码、原因、目标版本/状态通过 compare-and-swap 校验。
- 用户变更和安全审计在同一事务内完成。
- 角色、密码、启用状态变化会推进 `auth_version`，使既有会话失效。
- 保护最后一个活动超级管理员，避免系统失去治理主体。

### `enterprise/security_audit.py`

创建 `security_audit_events`、不可变触发器和索引；`append_security_audit_event()` 对 actor、action、上下文大小和敏感字段执行 fail-closed 校验。

### `enterprise/security_bootstrap.py`

负责把旧用户 schema 迁移到角色/审计 READY 状态，包含只读计划、正式备份、执行、生命周期记录、失败恢复和重复执行校验。

## 8. 主线收敛分支增量：`enterprise/canvas_task_journal.py`

`CanvasTaskJournal` 的原子回执、单次领取、完成和中断恢复已在当前 main；`create_task_receipt()` 在受理前写回执及归属。#123 已合并实现在既有 v1 JSON 上增加可选供应商成员回执与恢复结果，仍使用同一根目录和写入者，不增加数据库 Schema。

## 9. 本轮核对的源码规模与候选模块

4bdd9a1 快照：main.py 16993 行、794 个函数/方法节点；经典画布 14829 行，智能画布 17037 行。行数仅作定位，不作为交付成果或不能维护的结论。

| 文件/符号 | 已核对职责与归属 |
| --- | --- |
| enterprise/providers/zhenzhen.py：IMAGE_FAMILIES、IMAGE_MODELS | #156 集中模型家族/别名及能力，不散落每模型请求实现 |
| is_zhenzhen / image_profile / public_image_profiles | 明确供应商选择、内置能力、已选模型的公开投影 |
| image_body / submit_image | 正确请求字段、现有 client 一次提交；不写客户数据/系统状态 |
| provider_image_profiles.py：image_profile_for / build_aspect_parameters | 内置优先、未知模型临时配置、明确画幅/档位校验 |
| user_model_api.py：current_user_id / get_model_preferences / put_model_preferences | 当前认证主体的 GET/PUT；请求不能替换目标账号 |
| user_model_preferences.py：load_preferences / save_preferences | DATA_ROOT/user-model-preferences，自己的临时文件原子替换；既有写入审计 W50 |

main.py 的 api_headers、generate_ai_image、wait_for_image_task 和结果归档仍参与调用，新增模块不是完整 Provider 体系。完整边界随实际供应商工作包逐步提取。

## 付费提交与查询规则（#123 已合并）

`enterprise/providers/submission.py` 承担明确 API 拒绝判定、未知结果错误、提交响应结构校验和 GET/HEAD 瞬态重试。入口复用它，不在响应丢失时再次付费生成；已有 ID 在错误和图像持久回执中保留。它不访问业务数据库或文件目录。此包已合并，见[工程记录](../ops/PAID-SUBMISSION-STOPLOSS-2026-10-13.md)，不等于完整任务中心。

`enterprise/canvas_image_recovery.py` 的 `ImageReceiptSink` 在通用上游接受后、第一次轮询前保存 ID/查询绑定；`CanvasImageRecovery` 只查询原任务并回写原回执，单飞协调只保留活动查询，不作为任务事实源。已有结果缓存、批量成员结果、供应商配置变更拒绝及部分结果提示在此边界。`main.py` 的 `POST /api/canvas-image-tasks/{task_id}/reconcile` 只接线；Gateway 复用任务归属，结果仍归原用户。旧回执及旧查询路由保留，不意味着全 Provider/视频/自动对账已完成。

## ComfyUI 续修（2026-10-14 历史候选记录）

enterprise/providers/comfyui.py 的 ComfyClient 分离 upload/submit/inspect/wait；base_url/endpoint 保留 HTTP(S) 和路径前缀。main.prepare_comfy_workflow 只对内置图应用历史编号预设，archive_comfy_history 沿用输出归档；execute_comfy_generation 连接现有本地队列统计与持久回执。CanvasTaskJournal.record_comfy/claim_comfy_query 保存与领取原任务查询，不重新提交。create_canvas_comfy_task 可接受 UUID request_id 并返回同 owner 原回执；默认旧请求仍可用。续修状态见 CURRENT，不将本候选写入正式 10.2 能力。

2026-10-15 候选：enterprise/providers/comfy_workflow.py 负责已确认动态插槽输入组、请求图副本、提示词用途和 SaveText 正文/附件选择。GenerateRequest.workflow_values 使用服务端配置；设置页运行使用本次配置快照，旧 params 路径保留。结果含 run_id/result_id、正文与本地文件；已受理后的恢复仍仅查询原 prompt_id，不重新生成。无新业务表或运行平台依赖，详见既有 ComfyUI 实施记录。

## 2026-10-15 主线收口与任务目录候选

前述 #161“未合并”均为审查前快照：现已合并 main6603550，尚未发布。独立复审修正的 `comfy_input_policy.authorize_workflow_media` 在实际调用前校验工作流图引用的素材，不只信任前端参数名。

任务中心（#162 已合并）：`generation_tasks.GenerationTaskRepository.page/detail` 用 `db.list_owned_canvas_tasks` 的 owner-first SQL 读取既有 journal；`generation_task_api` 提供两个本人读取路由，不接受客户端 owner、供应商地址或凭据。详情在本人归属核实后复用资源投影，不替换原 owner。`ImageReceiptSink.started/generated/interrupted` 补充提交阶段/报告用量/脱敏错误，`CanvasTaskJournal.record_reconciliation` 保存最近核对及次数；仍是单上游写入者。`providers/zhenzhen.image_headers/image_task_endpoint/query_image` 与 `image_task_protocol` 复用现有 HTTP/状态语义。详见 [工程记录](../ops/PAID-SUBMISSION-STOPLOSS-2026-10-13.md#2026-10-15-持久任务中心与供应商边界续包)。本包已独立复审并合并 main6d9d77d，未完成全供应商/费用结算；后台调度为下述独立候选。

任务目录读写协调补记：生产路径由 Gateway 的 generation_task_api 认证并覆盖身份，通过既有回环 HTTP 连接池读取 generation_task_routes 的内部路由；Repository 注入上游同一个 CANVAS_TASK_JOURNAL，共用既有互斥锁，Gateway 不直接打开回执文件。Windows 普通读取句柄阻止 os.replace 的对照已复现；改为同一对象协调后，并发读取/30 次回执写入通过。公开 Gateway 拒绝整个 /_enterprise_internal/ 命名空间，客户端伪造身份无效；业务进程不可用时返回 503，不自动生成。原生文件接口试验未保留，无新平台适配/数据库结构。

自动恢复候选：`CanvasTaskJournal.recovery_candidates/record_auto_recovery` 在同一互斥锁内重建索引/写入 v1 可选调度字段。`AcceptedTaskRecovery.start/notify/stop` 由 main 生命周期和实际失败完成钩子接入；内存不是事实源，未知提交不进入自动任务。owner/启用账号/已维护供应商由现有 DB 与配置校验；图像沿用 CanvasImageRecovery 的原供应商绑定，Comfy 沿用原 backend/prompt_id 并校验后端仍在配置中。`CanvasComfyRecovery` 用共享单飞和 claim，每次只调用 `ComfyClient.inspect_async` 的 GET，初次提交/同步 inspect 仍复用原解析 helper。归档失败保留原身份，归档线程取消时先等待该次写入结束，不启动第二次归档。维护标记仅暂停新领取，不能据此声称完整业务写屏障。

Zhenzhen `image_query_status` 按维护的异步查询状态区分处理中/明确失败/结果成功/人工核对；未知 JSON 和成功无结果不无限伪报运行。`reported_usage` 识别异步 data.data 的报告用量，仍无费用估算或平台结算。协议来源见 [供应商查询文档](https://gpt-best.apifox.cn/api-356258956)。候选尚待独立审查合并，详见任务工程记录。


### 视频持久任务候选（2026-10-16，依赖 #163）

`enterprise/canvas_video_tasks.py` 在现有 v1 journal/owner 映射上登记视频任务，提交前写归属、轮询前写受理 ID 与查询绑定；`enterprise/providers/video_tasks.py` 只做单次 GET 状态识别。main 保留现有视频参数构造并接线 `/api/canvas-video-tasks`、`/{task_id}`、`/{task_id}/reconcile`。原任务续查复用 #163 调度器和输出归档，不能重新提交生成；无 ID/协议不明保留待核对。覆盖与验证限制见 [原任务记录](../ops/PAID-SUBMISSION-STOPLOSS-2026-10-13.md#2026-10-16-视频持久任务与原任务续查候选)，不属于正式 10.2。

2026-10-17 续修候选：`AcceptedTaskRecovery.after_manual_query` 让 Zhenzhen 图像和 ComfyUI 显式查询复用后台结果记账/退避；解除此前 manual 后，下一次查询仍由原验证和维护暂停控制。`canvas_image_recovery.public_receipt` 对已受理且后台等待/查询的任务投影 running，保留内部失败/原身份并屏蔽绑定。既有端点、前端、v1 journal 和 owner 表复用，不增加生成提交。范围和模拟证据见 [同一工程记录](../ops/PAID-SUBMISSION-STOPLOSS-2026-10-13.md#2026-10-17-手动原任务查询后接续后台跟踪)；尚未合并或发布。

2026-10-18 候选增量（Base main73d2b67，尚未合并/发布）：`providers/video_generation.py` 的 `json_video_body`、`generate_json_video`、`video_error_detail` 承接既有统一JSON构造/提交/解析；main只注入媒体、HTTP头、受理与查询回调，再归档输出。`providers/zhenzhen.py` 集中视频v2优先/明确缺失时v1兼容及Bearer头；`video_tasks.read_video_task`/`video_task_result` 保持只查询能力，实时 `poll_video` 与重启恢复共用解析，NOT_START为排队。旧回执的video_v2与generic mode保持兼容。不提供全模型能力目录/模板系统，不宣称所有Provider已模块化；源文档、验证及回滚见 [工程记录](../ops/PAID-SUBMISSION-STOPLOSS-2026-10-13.md#2026-10-18-zhenzhen-统一视频适配收口)。

## 2026-10-19 未开始任务执行边界候选

`canvas_task_dispatch.CanvasTaskDispatch` 在原 v1 journal 上协调私有待执行输入和就绪标记；既有 runner 的 mark_running 是提交前不可重放边界。`canvas_task_dispatch_app.create_dispatch` 注入当前 owner/来源/素材权限、Zhenzhen 模型与鉴权绑定、Comfy 工作流与后端绑定及维护暂停。新模块不改变数据库 Schema 或 Provider 提交协议，main 只连接四类入口和启动/停止。既有 `AcceptedTaskRecovery` 仍只负责已受理原任务续查。

认证 Zhenzhen HTTP 图像/视频/LLM 和 ComfyUI 可恢复未开始任务；CLI/匿名/其他供应商、敏感字段和超64MiB输入保留既有路径。正常提交并发不变，仅重启批次并发2。inputs 位于 DATA_ROOT 的私有任务子目录，不进入公开任务数据；结束/拒绝后清理，不删除素材。单 Upstream、旧回执人工核对和已开始不重提限制保留，详见 [原任务记录](../ops/PAID-SUBMISSION-STOPLOSS-2026-10-13.md#2026-10-19-未开始任务持久执行与重启恢复候选)。这是独立候选，不包含在冻结 v2026.10.3 构建中。
