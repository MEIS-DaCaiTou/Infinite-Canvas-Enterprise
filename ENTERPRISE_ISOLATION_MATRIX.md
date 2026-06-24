# Infinite Canvas Enterprise 隔离数据域与 API 矩阵

更新时间：2026-06-24
状态：Task 3G 设计基线。本文不实现任何隔离代码，也不改变上游行为。

## 1. 目的与决策

企业版的安全边界是“默认拒绝普通用户访问未知归属数据”。管理员可以代管、分配和审计，但不应把全局上游数据直接暴露给普通用户。

本矩阵是后续 3G 分阶段实现、上游同步复核和浏览器回归的唯一设计输入。矩阵中的“目标”并不表示当前已经实现；当前已覆盖的画布、对话和受保护本地资源以 `enterprise/interceptors.py` 与 `enterprise/tests/test_ownership_isolation.py` 为准。

### 术语

- `owner`：唯一企业用户 ID。普通用户只可读写自己拥有的数据。
- `scope`：资源可由所属画布、对话或项目的 owner 派生访问权限。
- `unowned`：历史数据尚无企业 owner。普通用户不可见、不可访问；管理员可见并可分配。
- `404 风格拒绝`：对无权访问的对象返回“资源不存在或无权限访问”，避免枚举其他用户数据。
- `管理员代管`：管理员可查看、迁移、分配或在 owner 画布内生成资源；管理员操作必须可审计。

## 2. 当前存储与归属盘点

| 数据域 | 当前上游存储/接口 | 当前共享状态 | 当前企业 owner 映射 | 目标归属模型 | 当前风险与 3G 处理 |
| --- | --- | --- | --- | --- | --- |
| 项目 | `data/projects.json`，`/api/projects` | 全局单文件 | `user_project_map` | `project_id -> owner_user_id`；预留 `parent_project_id`、`visibility`、`archived_at` | 3G-2 已覆盖当前扁平项目节点的列表、CRUD 与画布移动校验。 |
| 默认项目 | `DEFAULT_PROJECT_ID`、`projects.json` | 全局默认记录 | 不映射，作为每用户虚拟根 | 逻辑默认项目仅作为每位用户的虚拟根，不共享实体 | 3G-2 已按当前用户重算可见画布数量；不得分配给单一用户。 |
| 画布 | `data/canvases/*.json`，`/api/canvases*` | 文件全局 | `user_canvas_map` | 保留 `canvas_id -> owner`，并补 `canvas -> project` 的 project-owner 一致性校验 | 已部分覆盖。项目移动、列表计数及未归属旧画布仍需 3G-2 复核。 |
| 画布回收站 | 画布 JSON 的删除字段，`/api/canvases/trash` | 全局扫描 | `user_canvas_map` | 与画布 owner 相同；恢复、清空、移动均校验 owner | 已部分覆盖，纳入项目隔离回归。 |
| 对话 | `data/conversations/<user>/<id>.json`，`/api/conversations*` | 上游按 header 目录，历史文件仍可全局扫描 | `user_conversation_map` | 保留 `conversation_id -> owner`；记录真实文件 owner 用于代理 | 已部分覆盖；历史/生成记录引用需 3G-3 补齐。 |
| 输入、输出、上传资源 | `assets/input`、`assets/output`、`assets/uploads`、`output`，`/api/view` 等 | 目录全局 | `user_resource_map`，并可从画布/对话引用回填 | `resource_url -> owner`，或由 `canvas_id` / `conversation_id` scope 派生 | 已部分覆盖；素材库与历史缩略图的 owner 回填尚未完整。 |
| 素材库 | `assets/library`、`data/asset_library.json`、`/api/asset-library*` | 全局 JSON 与目录 | 无 | library/category/item 三级 owner；共享须明确 `visibility=shared` | 高。3G-4 前普通用户不应获得全局管理权。 |
| 本地上传素材与文件夹 | `assets/uploads`、`/api/local-assets*` | 全局文件树 | 无 | path/item owner；文件夹 owner、父级 owner、继承规则 | 高。路径与缩略图均须按 owner 过滤。 |
| 共享文件夹 | `data/shared_folders.json`、`/api/shared-folders*` | 全局 | 无 | 默认管理员管理；如启用共享，显式 ACL，不可隐式共享 | 高。先限制入口，后实现 ACL。 |
| 提示词库 | `data/prompt_libraries.json`、`/api/prompt-libraries*` | 全局 | 无 | library/category/item owner 与可见性 | 中高。视为用户内容，不得因名称为“库”而默认共享。 |
| 工作流与运行配置 | `workflows/`、`data/runninghub_workflows.json`、`/api/workflows*`、`/api/runninghub/workflows*` | 主要全局 | 无 | 企业管理员默认管理；未来若开放，采用工作流 owner/共享 ACL | 高风险设置。3G-6 先入口和 API 授权，非管理员默认不可写。 |
| API Provider 与密钥 | `data/api_providers.json`、`API/.env`、`/api/providers*`、`/api/config*` | 全局敏感配置 | 无 | 不按普通用户 owner 开放；仅管理员或受控服务账号 | 严重。普通用户不可见密钥、不可编辑。 |
| 在线生图与本地功能历史 | `history.json`、`/api/history`、`/api/history/delete`、在线/Angle/ZImage/Klein/Enhance 等结果 | 全局单文件 | 无 | `history_item_id -> owner`，历史图片复用 resource owner | 高。3G-3 设计 migration，禁止直接对普通用户返回全量。 |
| Smart Canvas 生成日志 | 画布 JSON `logs` 与 output URL | 随画布保存 | 画布/资源 owner | 画布 scope；管理员在用户画布生成的结果归画布 owner | 已覆盖日志兼容与去重；3G-3 只补交叉页面历史投影。 |
| Canvas image/Comfy/video 任务 | 上游内存任务，`/api/canvas-image-tasks*`、`/api/canvas-comfy-tasks*`、`/api/canvas-video` | 进程全局 | `user_canvas_task_map` 仅 image task | task -> requester、canvas_id、owner/scope、输出 resource | 中高。Comfy/video 尚未纳入完整 owner/task 矩阵。 |
| 图片转换 | `/api/image-jpeg` | 请求即处理，资源可能落盘 | 无显式 task 映射 | 输入/输出均必须通过 resource scope 校验并记录输出 owner | 中高。2026.06.23 新增面。 |
| WebSocket 事件 | `/ws/stats`，`new_image`、`canvas_updated`、队列/状态事件 | 上游广播给所有已连客户端 | 无订阅 owner | connection -> user；事件携带 canvas/resource/task 时按 owner fan-out | 严重。3G-5 前不能宣称 WebSocket 隔离完成。 |
| 审计日志 | `enterprise.db: usage_logs`、`/enterprise/api/logs` | 管理员可见 | actor user ID | 记录管理员代管、权限开关、归属迁移、批量删除 | 已有基础；3G 各写操作补审计。 |

## 3. 目标数据库扩展原则

后续新增表必须在 `enterprise/db.py` 中创建，不修改上游 JSON schema 作为唯一权限依据。建议采用最小可迁移映射表，而不是一次性重写上游存储：

| 建议实体 | 最小字段 | 说明 |
| --- | --- | --- |
| `user_project_map` | `project_id` PK、`user_id`、`parent_project_id`、`visibility`、`created_at`、`archived_at` | 将上游项目记录纳入企业 owner；默认 `visibility=private`。 |
| `user_asset_library_map` | `library_id` PK、`user_id`、`visibility` | 素材库根对象 owner。 |
| `user_asset_item_map` | `item_id` PK、`library_id`、`user_id`、`resource_url`、`created_at` | 文件、缩略图及逻辑 item 关联。 |
| `user_history_map` | 稳定 `history_id` PK、`user_id`、`type`、`resource_url`、`created_at` | 不可只用时间戳作为删除授权依据。 |
| `user_task_map` | `task_id` PK、`user_id`、`canvas_id`、`project_id`、`task_type`、`created_at` | 统一 image、Comfy、video、图片转换等任务。 |
| `enterprise_permission_settings` | `setting_key` PK、`value`、`updated_by`、`updated_at` | 系统级开关，不存于浏览器 LocalStorage。 |
| `enterprise_share_grants` | `subject_type`、`subject_id`、`grantee_user_id`、`permission`、`created_by` | 仅在明确启用共享后使用；默认不写入 grant。 |

迁移规则：旧数据默认 `unowned`；不得根据文件名、目录名或当前访问者猜测 owner。管理员可通过后台批量或逐项分配，系统可在已有 owner 的画布/对话范围内幂等回填资源。

## 4. API 权限矩阵

### 4.1 项目、文件夹、画布与对话

| API | 方法 | 数据域 | 管理员 | 普通用户 | 未登录 | 过滤/校验目标 | 代管/审计 | 上游风险 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/projects` | GET | 项目/项目计数 | 全部，可标识 owner/unowned | 仅 owner 项目和自己的虚拟默认项目 | 401 | `project_id` owner 过滤，计数仅统计可见画布 | 管理员查看不必逐项审计 | 3G-2 已覆盖 |
| `/api/projects` | POST | 项目 | 可创建并指定 owner 或自己 | 为自己创建 | 401 | 创建后写 `user_project_map` | 创建记录写审计 | 3G-2 已覆盖 |
| `/api/projects/{id}` | POST | 项目重命名/排序 | 可改任意 | 仅 owner | 401 | `project_id` owner；禁止影响其他人排序 | 管理员代改待细化审计 | 3G-2 已覆盖 |
| `/api/projects/{id}` | DELETE | 项目删除/画布迁移 | 可删除/迁移 | 仅 owner | 401 | 项目 owner；上游迁回虚拟默认项目 | 管理员操作审计待细化 | 3G-2 已覆盖 |
| `/api/canvases` | GET | 画布列表 | 全部 | `user_canvas_map` 过滤 | 401 | 响应过滤；项目计数同步过滤 | 管理员可见 unowned | 已实现基础，需项目联动 |
| `/api/canvases` | POST | 新建画布 | 可创建，默认归自己 | 创建后归当前用户，项目必须是自己的 | 401 | body.project 的 project owner；写 canvas owner | 创建诊断；管理员代建审计 | 中 |
| `/api/canvases/trash` | GET | 回收站 | 全部 | 仅自己的删除画布 | 401 | canvas owner 过滤 | 管理员可恢复/分配 | 中 |
| `/api/canvases/{id}` | GET/PUT/DELETE | 画布读写删除 | 全部 | 仅 canvas owner | 401 | `canvas_id` 404 风格拒绝；保存体内资源校验 | 管理员代管审计可选 | 已实现基础 |
| `/api/canvases/{id}/meta`、`/touch`、`/restore`、`/purge` | GET/POST/DELETE | 元数据、恢复、彻底删除 | 全部 | 仅 canvas owner | 401 | `canvas_id`；项目移动还需 project owner | restore/purge/转移审计 | 中 |
| `/api/canvas-assets`、`/api/canvas-assets/check` | GET/POST | 画布资源索引 | 全部 | 仅自己的 canvas/resource 条目 | 401 | canvas 列表及 URL scope 双过滤 | 管理员可见 unowned | 高 |
| `/api/conversations` | GET/POST | 对话列表/创建 | 全部 | 仅自己的对话；创建归当前用户 | 401 | `user_conversation_map`；保持 `x-user-id` 上游目录隔离 | 管理员查看/转移审计 | 已实现基础 |
| `/api/conversations/{id}` | GET/DELETE | 对话详情/删除 | 全部 | 仅 conversation owner | 401 | `conversation_id` 404 风格拒绝 | 管理员代管审计 | 已实现基础 |
| `/api/chat`、`/api/chat/agent`、`/api/chat/stream` | POST | 对话消息 | 全部 | 仅 body 中有权的 conversation；新对话写 owner | 401 | body `conversation_id`、上游 `x-user-id` | 管理员代管应标记 actor | 中 |

### 4.2 本地资源、任务、生成日志与历史

| API / 路径 | 方法 | 数据域 | 管理员 | 普通用户 | 未登录 | 过滤/校验目标 | 代管/审计 | 上游风险 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `/assets/input/*`、`/assets/output/*`、`/assets/uploads/*`、`/assets/library/*`、`/output/*` | GET | 本地资源 | 全部 | owner 或 canvas/conversation scope | 401 | 规范化 `resource_path`，未知拒绝 | 管理员可读 | 已实现基础，目录扩展需复核 |
| `/api/view`、`/api/download-output`、`/api/media-preview` | GET | 预览/下载 | 全部 | 同上 | 401 | filename/type/subfolder 或 url 归一化 | 无需每次审计 | 已实现基础 |
| `/api/upload`、`/api/ai/upload*`、`/api/comfyui/upload-base64` | POST | 输入资源 | 全部 | 允许自身上传并立即写 resource/task owner | 401 | multipart/JSON 输出 URL 写 owner | 管理员代上传记录 actor | 高 |
| `/api/local-assets` | GET | 本地上传素材列表 | 全部 | 仅自己的 path/item | 401 | 文件树和缩略图按 owner 过滤 | 管理员可代管 | 高 |
| `/api/local-assets/folders` | POST/PATCH | 本地素材文件夹 | 全部 | 开关允许时仅自身根下 | 401 | folder path owner、父级 owner | 重命名/移动审计 | 高 |
| `/api/local-assets/items`、`move`、`delete`、`caption`、`classify` | PATCH/POST | 本地素材项 | 全部 | 仅 item/path owner | 401 | item ID/path 及引用资源 owner | 批量动作审计 | 高 |
| `/api/canvas-image-tasks` | POST/GET | 图片任务 | 全部 | 仅自己发起/所属画布的 task | 401 | 统一 `user_task_map`；result output 归 canvas owner | 管理员在 A 画布生成归 A 画布 scope | 已有 image task 基础 |
| `/api/canvas-comfy-tasks` | POST/GET | Comfy task | 全部 | 仅自己/所属画布 | 401 | 同上；当前缺完整 map | 管理员代管审计 | 高，2026.06.23 新增 |
| `/api/canvas-video`、`/api/image-jpeg` | POST | 视频/转换任务和输出 | 全部 | 仅可读自己的输入/画布，输出归自己或画布 owner | 401 | input URL、task、output URL 三段校验 | 高风险动作审计 | 高 |
| Smart Canvas `logs`、画布保存 | GET/PUT | 生成日志/缩略图 | 全部 | 仅所属画布 | 401 | 作为 canvas JSON 的子域；输出 URL 走 resource scope | 管理员在用户画布生成归画布 owner | 已有兼容/去重，勿回归 |
| `/api/online-image`、`/api/image-task-query`、`/api/angle/*`、`/generate`、`/api/ms/generate`、`/api/generate` | POST | 在线生成与异步结果 | 全部 | 允许与否由功能开关；任务/输出/历史均归当前用户 | 401 | request/task/result/history owner 链 | 管理员调用审计 | 高，勿在 3G-1 修改模型逻辑 |
| `/api/history` | GET | 全局历史 | 全部或按后台策略 | 仅自己的 `history_id` | 401 | response 按 history owner 过滤；未知不返回 | 管理员可修复归属 | 严重 |
| `/api/history/delete` | POST | 历史删除及物理输出 | 全部 | 仅自身 `history_id`，不可按 timestamp 模糊删除他人 | 401 | 稳定 ID + owner + resource scope | 必须审计批量/物理删除 | 严重 |
| `/api/queue_status` | GET | 队列状态 | 全局汇总可选 | 仅自己的位置，或只返回无敏感总数 | 401 | `client_id` 必须绑定 user/session | 管理员可全局 | 高 |

### 4.3 素材、提示词、工作流和敏感设置

| API / 路径 | 方法 | 数据域 | 管理员 | 普通用户 | 未登录 | 过滤/校验目标 | 代管/审计 | 上游风险 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/asset-library` | GET | 全局素材库 | 全部 | 默认不返回全局库；仅 owner 或显式共享 | 401 | library/category/item/resource owner | 管理员可管理 | 严重 |
| `/api/asset-library/libraries*`、`categories*` | POST/PATCH/DELETE | 素材库结构 | 全部 | 由开关控制，默认禁止 | 401 | library owner、共享 ACL | 结构变更审计 | 高 |
| `/api/asset-library/items*`、`batch`、`move`、`delete`、`crop`、`classify` | POST/PATCH/DELETE | 素材项与批量管理 | 全部 | 仅 own/shared item，批量默认禁止 | 401 | item/resource owner；每项过滤 | 必须审计批量删除/移动 | 严重 |
| `/api/prompt-libraries*` | GET/POST/PATCH/DELETE | 提示词库 | 全部 | 仅 owner 或显式共享 | 401 | library/category/item owner | 共享、删除审计 | 高 |
| `/api/shared-folders*` | GET/POST/DELETE | 注册共享目录 | 管理员默认可用 | 普通用户默认不可见/不可写 | 401 | folder owner 或明确 ACL；禁止裸路径授权 | 注册/导入审计 | 严重 |
| `/api/workflows*`、`/api/runninghub/workflows*` | GET/POST/PUT/DELETE | 工作流配置 | 全部 | 默认不可编辑；是否可见由开关 | 401 | workflow owner/共享或管理员-only | 写操作审计 | 高 |
| `/api/runninghub/*`、`/api/jimeng/*`、`/api/comfyui/instances` | GET/POST/PUT | 平台集成与会话/实例 | 管理员默认可用 | 默认隐藏且禁止配置性操作 | 401 | 入口权限；不泄露平台 token/session/实例配置 | 登录/注销/配置审计 | 严重 |
| `/api/config`、`/api/config/token`、`/api/providers*`、`/api/models` | GET/PUT/POST | API 设置、模型与密钥 | 管理员受控访问 | 普通用户默认不可见、不可读、不可写、不可测试 | 401 | 服务器端管理员检查，响应脱敏 | 配置变更/测试审计 | 严重 |

### 4.4 WebSocket、入口和企业专用 API

| API / 页面 | 方法 | 数据域 | 管理员 | 普通用户 | 未登录 | 过滤/校验目标 | 代管/审计 | 上游风险 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `/ws/stats` | WebSocket | 在线、队列、`new_image`、canvas 更新、素材更新 | 可接收授权全局事件 | 仅自身/自身 scope 事件 | close 1008 | connection 绑定 enterprise user；按 event 的 canvas/task/resource owner fan-out | 管理员订阅敏感事件可审计 | 严重 |
| `/enterprise/admin`、`/enterprise/api/*`、`/enterprise/logs` | GET/REST | 企业治理与审计 | 允许 | 403/隐藏 | 登录跳转或 401 | 管理员角色 | 所有治理写操作审计 | 企业层 |
| `/api/check-update`、`/api/update-*` | GET/POST | 上游更新 | 受控更新 | 403、隐藏入口 | 401 | 服务器端管理员检查，不能只靠隐藏 | 更新/回滚审计 | 已实现基础 |
| 企业项目主页按钮 | 页面入口 | 项目主页 | 指向企业仓库 | 指向企业仓库或由开关隐藏 | 不适用 | 不应指向上游默认仓库 | 不适用 | 已实现注入，需同步复核 |

## 5. 当前实施覆盖与缺口

| 能力 | 当前状态 | 后续动作 |
| --- | --- | --- |
| 画布、对话单对象 404 风格授权 | 已覆盖基础路径 | 在 3G-2 扩展到项目归属、移动和新列表页面。 |
| 新建画布/对话 owner | 已覆盖 | 3G-2 校验 project owner，3G-3 关联 task/history。 |
| 本地资源 URL 归一化和 scope 回填 | 已覆盖基础资源路径 | 3G-3/4 覆盖素材、历史、缩略图和新上游输出路径。 |
| 项目/文件夹隔离 | 3G-2 已覆盖当前上游扁平项目节点；项目 API 尚无独立 parent/folder 字段 | 后续上游增加真实层级 API 时，复用 `user_project_map` 的 parent/visibility 预留字段并补矩阵。 |
| 历史、在线生成、批量历史 | 未覆盖 | 3G-3 定义稳定 ID 和 owner migration。 |
| 素材库/上传文件夹/共享目录 | 未覆盖 | 3G-4 使用 item/path/library owner 与 ACL。 |
| WebSocket 事件扇出 | 仅登录认证，未按事件 owner 过滤 | 3G-5 必须在网关做 connection/user 绑定与授权扇出。 |
| API/工作流/平台入口开关 | 更新入口已有管理员保护 | 3G-6 补服务器端权限开关与注入层隐藏。 |

## 6. 上游兼容实施位置

1. `enterprise/db.py`：只保存企业 owner、ACL、权限开关和审计，不复制或重写上游业务数据。
2. `enterprise/interceptors.py`：集中做路径解析、对象 owner 判断、列表过滤、响应归属记录和默认拒绝。新增路径必须在这里建立可测试函数，避免散落在网关。
3. `enterprise/gateway.py`：保持认证、用户 header 注入、WebSocket 代理与最小 HTML 注入。WebSocket 隔离应在此处或独立企业模块实现，不能在上游 `main.py` 广播层直接打补丁。
4. `enterprise/admin_api.py` 与 `enterprise-static/`：提供归属迁移、开关管理和审计查看。不要在管理台直接读取上游数据文件绕过权限模型。
5. `enterprise/tests/`：所有临时数据使用临时目录/SQLite；为每个新增上游路径建立 A/B/admin 测试。
6. `static/`：默认不修改。入口隐藏优先由网关 HTML 注入；只有上游 DOM 完全无法被注入稳定治理时，才做最小兼容补丁，并在上游同步 PR 中逐项复核。

## 7. 上游同步防回归门禁

每次上游同步后必须：

1. 从上游路由表重新搜索 `/api/projects`、`/api/*tasks`、`/api/history`、`/api/*assets`、`/api/providers`、`/api/workflows` 与 `@app.websocket`。
2. 将新增的读、写、下载、异步 task、列表和 WebSocket API 加入本矩阵，再决定是否可合并。
3. 比对 `enterprise/interceptors.py` 的前置授权、后置过滤与任务/资源记录覆盖是否仍命中这些路径。
4. 浏览器以 A、B、管理员三角色复验列表、直链、刷新/重登、缩略图、WebSocket 和入口权限。
5. 在 `enterprise/tests/UPDATE_TEST_LOG.md` 写明未覆盖路径；未覆盖高风险全局列表不得默认为普通用户可用。
