# 后端类与函数参考

> 源码参考快照（2026-10-13）：main@e89a288（已合并 #154/#155/#156）；产品功能源码基点 #156@4bdd9a1 保留；C5/C6/C7 已合并，构建与验收范围仍引用其准确记录。本文是代码/运行参考，当前 PR/CI、Release 和验收只见 [CURRENT](../CURRENT_PROJECT_STATUS.md)，实施顺序只认路线图。

[返回索引](./README.md)

本文只列出理解主链路所需的关键符号。完整路由以源码装饰器为准。

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

`enterprise/providers/submission.py` 承担明确 API 拒绝判定、未知结果错误、提交响应结构校验和 GET/HEAD 瞬态重试。入口复用它，不在响应丢失时再次付费生成；已有 ID 在错误和图像持久回执中保留。它不访问业务数据库或文件目录。此包尚未合并，见[工程记录](../ops/PAID-SUBMISSION-STOPLOSS-2026-10-13.md)，不等于完整任务中心。

`enterprise/canvas_image_recovery.py` 的 `ImageReceiptSink` 在通用上游接受后、第一次轮询前保存 ID/查询绑定；`CanvasImageRecovery` 只查询原任务并回写原回执，单飞协调只保留活动查询，不作为任务事实源。已有结果缓存、批量成员结果、供应商配置变更拒绝及部分结果提示在此边界。`main.py` 的 `POST /api/canvas-image-tasks/{task_id}/reconcile` 只接线；Gateway 复用任务归属，结果仍归原用户。旧回执及旧查询路由保留，不意味着全 Provider/视频/自动对账已完成。
