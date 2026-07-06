# Enterprise E2E Acceptance Matrix

更新时间：2026-07-06

本文是企业版第一阶段隔离底座的端到端验收基线。后续功能 PR、上游同步 PR、权限策略 PR 都应按本文补充自动化或人工 A/B/admin 验收记录。

## 基线结论

当前企业版已基本完成第一阶段安全隔离底座：

- 3G-4A：上传资源隔离。
- 3G-4B：素材库完整隔离。
- 3G-5：WebSocket 广播隔离。
- 3G-6：异步任务历史 owner 隔离。
- 3G-7A：管理员权限开关最小版 + 审计。

当前项目仍不是完整企业协作平台。本文只验证 owner 隔离、管理员兜底、权限开关和审计，不验证 team / workspace / project members / canvas grants 等协作能力。

## 账号矩阵

| 角色 | 建议账号 | 验收定位 |
|---|---|---|
| 管理员 | `admin` | 可见全局、可代管、可配置权限开关、关键操作写审计。 |
| 普通用户 A | `user_a` | 创建和使用自己的项目、画布、对话、资源、素材、历史和任务。 |
| 普通用户 B | `user_b` | 验证不能看到、读取、管理或订阅 A 的数据。 |

## 通用规则

- 所有前端入口必须和后端 API 同时验证；隐藏入口不能替代后端鉴权。
- 普通用户对未知 owner / unowned 数据默认不可见、不可读、不可删、不可作为模型输入。
- 管理员可见全局，但归属迁移、删除、权限变更和关键代管操作必须写审计。
- Provider token、ModelScope Key、中转站、模型质量、2K/high、ComfyUI 自定义节点缺失不是企业隔离验收失败。
- Angle / Enhance ModelScope 上传解耦是 Issue #50 后续独立小修，不纳入本验收基线实现范围。

## E2E 验收矩阵

| 域 | 前端入口 | 后端 API / 数据 | admin 预期 | user_a 预期 | user_b 预期 | 审计 / 备注 |
|---|---|---|---|---|---|---|
| 登录与用户状态 | 登录页、左下角用户区 | `/enterprise/api/me`、JWT cookie | 管理员身份正确 | A 身份正确 | B 身份正确 | 禁用用户应无法继续访问受保护页面和 API。 |
| 项目 | 项目/画布列表 | `/api/projects`、`user_project_map` | 可见 A/B/unowned 项目 | A 创建项目、文件夹后仅 A 可见 | 不可见 A 项目 | 管理员分配项目 owner 写审计。 |
| 画布 | 画布列表、经典画布、Smart Canvas | `/api/canvases*`、`user_canvas_map` | 可见全局并可代管 | A 创建/打开/保存自己的画布 | 不可见 A 画布，直接 API 被拒绝 | 管理员把 A 画布转给 B 后 canvas owner 同步为 B。 |
| 画布迁移资源一致性 | 管理后台画布归属、画布详情 | canvas JSON、`user_resource_map` | 可把 A 画布转给 B | A 原始上传资源 owner 不变，A 仍可直链访问自己的原始上传文件 | B 可查看被转交画布内引用资源，但不能管理 A 的原始上传文件 | 不直接迁移 resource owner，依赖 canvas 引用回溯授权。 |
| 对话 | GPT 对话页 | `/api/conversations*`、`/api/chat*`、`user_conversation_map` | 可见和代管全局对话 | A 创建和继续自己的对话 | 不可见 A 对话，不能复用 A 附件 | 对话归属变更写审计。 |
| 上传资源 | 在线生图、GPT 附件、画布上传、ZImage / Angle / Enhance | `/api/ai/upload*`、`/api/upload`、`/api/view`、`/assets/input/*`、`user_resource_map` | 可读 A/B/unowned | A 上传图片后 owner 归 A，A 可预览/作为输入 | B 不能通过 `/api/view`、直链、历史、素材库或 canvas 输入绕过访问 | 3G-4A 回归；Angle / Enhance ModelScope 上传解耦另行处理。 |
| local-assets | 本地素材面板 | `/api/local-assets*`、`/assets/uploads/*` | 可见和管理全局 | A 只看到和管理自己的上传素材 | B 看不到、删不了、移不了 A 或 unowned 素材 | 管理员 delete/move 写审计。 |
| 素材库 | 素材库主页面、经典画布右侧素材库、Smart Canvas 素材库面板 | `/api/asset-library*`、`/assets/library/*`、`user_asset_object_map` | 可见和管理 A/B/unowned | A 可创建、重命名、移动、批量管理、使用自己的 library/category/item | B 看不到、管不了 A/管理员/unowned 的 library/category/item，不能把 A item 作为输入 | 3G-4B 回归；target library/category owner 必须校验。 |
| 历史记录 | 在线生图历史、本地功能历史、历史删除 | `/api/history`、`/api/history/delete`、`user_history_map` | 可见全局历史和 unowned | A 只看到和删除自己的历史 | B 看不到 A 历史，不能按 timestamp 删除 A 历史 | 历史删除不物理删除 output。 |
| 异步任务 | RunningHub、Comfy、video、image conversion、provider image task | `/api/*task*`、`/api/runninghub/*`、`user_task_map`、`user_canvas_task_map` | 可见全局或管理视角 | A 能查询自己的任务状态和结果 | B 不能看到 A 的 task id、状态、结果、resource URL | 3G-6 回归；真实 provider Key 缺失不算隔离失败。 |
| WebSocket | 主页面、历史刷新、素材库刷新、画布刷新 | `/ws/stats?client_id=...`、`new_image`、`asset_library_updated`、`canvas_updated` | 连接正常，可接收必要管理视角事件 | A 只收到自己的生成、素材库、画布刷新事件 | B 不收到 A 的 new_image、task id、prompt、resource URL、cloud_status | 3G-5 回归；stats/pong 不应被误伤。 |
| 权限开关 | 管理后台“权限开关”Tab、普通用户侧边栏 | `/enterprise/api/feature-flags*`、`enterprise_user_feature_overrides` | 可切换全局和用户 override，管理员永远 bypass | 被 allow 时入口和 API 同时可用；被 deny 时入口隐藏且 API 403 | B 不受 A override 污染 | `feature_flag_changed`、`user_feature_override_changed`、`permission_policy_updated` 写审计。 |
| API 设置 | 更多设置、`/static/api-settings.html` | `/api/providers`、`/api/config/token` 等 | 可读写设置 | 默认 deny；allow 后可见入口并进入页面 | 默认 deny，直访无权限 | 不误伤普通生成所需 `/api/config`、`/api/models` 脱敏读取。 |
| 工作流设置 | 更多设置、`/static/comfyui-settings.html` | workflow / Comfy / RunningHub 设置接口 | 可读写设置 | 默认 deny；allow 后可见入口并进入页面 | 默认 deny，直访无权限 | 不误伤普通 Comfy input/output、画布生成和任务提交。 |
| 生成能力开关 | 在线生图、ZImage、Angle、Enhance、video、RunningHub | `/api/online-image`、`/api/generate`、`/api/angle/generate`、`/api/ms/generate`、`/api/canvas-video`、`/api/runninghub/submit` | 管理员 bypass | allow 时核心生成链路正常；deny 时提交类 API 403 | B 的开关不受 A 设置影响 | 上传/预览/input owner 校验不能被 generation deny 误伤。 |
| 禁用用户 | 登录页、所有受保护页面 | `/enterprise/api/users/{id}/active`、JWT 校验 | 管理员可禁用/启用用户 | 被禁用后不能继续访问受保护页面和 API | 其他用户不受影响 | `user_disabled` / `user_enabled` 写审计。 |

## 上游同步回归要求

每次上游同步 PR 必须至少复核：

- `main.py` 新增 API 是否需要企业拦截。
- `static/` 新增入口是否需要企业隐藏、注入或无权限页。
- 上传、输出、历史、素材库、任务、WebSocket 路径是否进入 owner 矩阵。
- API 设置 / 工作流设置 / 更新入口是否仍受 3G-7A 权限开关保护。
- Angle / Enhance ModelScope 上传解耦如果尚未单独修复，不得在同步 PR 中顺手混入。

## 不属于本文实现范围

- team / workspace / project members / canvas grants。
- 用户之间共享画布或素材。
- 复杂 RBAC、部门权限、角色模板。
- 每用户 API Key、计费、SaaS 多租户。
- 数据库功能 schema 改造。
- `enterprise/interceptors.py` 大重构。
- Postgres、队列、运维系统。
- 上游同步实现。
- Angle / Enhance ModelScope 上传解耦实现。
