# Infinite Canvas Enterprise 权限设计与 Task 3G 实施路线

更新时间：2026-06-24
状态：Task 3G 设计基线。本文定义后续 PR 的边界，不在本 PR 修改业务行为。

## 2026-07-06 阶段结论

3G-7A 已完成管理员权限开关最小版与审计记录。当前权限治理目标是限制普通用户管理系统设置和高风险功能，而不是限制普通用户正常使用生成能力。

已完成能力包括：

- 普通用户默认不能访问 API 设置、工作流设置和系统更新。
- 管理员可配置全局 feature flag。
- 管理员可配置单个用户的 `inherit` / `allow` / `deny` 覆盖。
- 管理员永远 bypass。
- 权限开关变更写入审计日志，并可在操作日志中筛选。

当前权限模型仍是“管理员 / 普通用户 + 最小 feature flag”，不是复杂 RBAC、团队空间、部门权限、计费或每用户 API Key。下一阶段如进入协作权限设计，应先定义项目成员、画布授权、素材共享、撤销和审计，再扩展实现。

后续新增权限策略不应继续无边界堆入 `enterprise/interceptors.py`。建议逐步引入 `enterprise/policies/`，由 gateway / interceptors 负责调用。

## 1. 权限模型

### 1.1 默认策略

- 未登录：仅可访问登录页、企业静态资源和健康检查；其他 API 返回 401 或跳转登录。
- 普通用户：只可读写 private owner 为自己的数据；未归属历史数据一律不可见。
- 管理员：可读全部、代管和分配归属；不因管理员身份绕过审计和资源归属写入。
- 共享：默认关闭。未来只通过显式 share grant 授权，不以“同项目”“同文件夹”“同目录”推断共享。

### 1.2 归属优先级

1. 显式对象 owner。
2. 对象的 canvas/conversation/project scope owner。
3. 显式共享 grant。
4. 管理员代管。
5. 其他情况拒绝；不得回退为全局可见。

管理员在用户 A 的画布内创建 output、日志或任务结果时，目标资源 scope 属于画布 owner A；审计中的 actor 是管理员。这保持 A 重登后可见，同时 B 无权访问。

## 2. 页面与入口权限矩阵

| 页面/入口 | 管理员可见/可操作 | 普通用户默认 | 未登录 | 后端强制要求 | 后台开关 |
| --- | --- | --- | --- | --- | --- |
| 在线生图 | 可见，可用 | 可见但只看自己的任务/历史；可由开关关闭 | 登录页 | task/history/resource owner | `user_online_image_enabled` |
| GPT 对话 | 可见，可用 | 可见，仅自己的对话 | 登录页 | conversation owner | `user_chat_enabled` |
| 无限画布/项目页 | 可见，全局管理视图 | 可见，仅自己的项目、文件夹和画布 | 登录页 | project/canvas owner | `user_projects_enabled`、`user_project_create_enabled` |
| Smart Canvas | 可见，可用 | 可见，仅自己的画布、日志、资源 | 登录页 | canvas/task/resource owner | `user_smart_canvas_enabled` |
| 素材库 | 可见，管理共享库 | 默认只自己的库；全局库/批量管理隐藏 | 登录页 | library/item/resource owner | `user_asset_library_enabled`、`user_asset_manage_enabled` |
| 本地素材/上传文件夹 | 可见 | 默认仅自己的目录/素材 | 登录页 | path/item owner | `user_local_assets_enabled` |
| API 设置 | 可见，受安全审计 | 默认隐藏且 API 返回 403 | 登录页 | admin-only | `user_api_settings_visible`、`user_api_settings_editable`，默认 false |
| 工作流设置 | 可见，受安全审计 | 默认隐藏且写 API 返回 403 | 登录页 | admin-only 或 owner/ACL | `user_workflow_settings_visible`、`user_workflow_settings_editable`，默认 false |
| Comfy/视频/图片转换/平台登录 | 可见，按部署策略 | 默认隐藏或只允许安全的生成入口 | 登录页 | feature permission + input/resource owner | `user_comfy_enabled`、`user_video_enabled`、`user_image_convert_enabled` |
| 企业项目主页 | 可见，指向企业仓库 | 默认可见且指向企业仓库；可配置隐藏 | 登录页 | 无敏感 API | `user_enterprise_home_visible` |
| 上游更新/回滚 | 可见，文案为企业受控更新 | 隐藏，直接 API 403 | 401 | admin-only | `enterprise_update_enabled` |
| 管理后台、审计日志 | 可见 | 隐藏，直接 403 | 登录页/401 | admin-only | 不向普通用户开放 |
| 快捷键、普通 UI 帮助 | 可见 | 可见 | 不适用 | 无 | 无 |
| 项目页新增按钮/文件夹操作 | 可见 | 按项目创建/管理开关和 owner 显示 | 登录页 | project owner | `user_project_create_enabled`、`user_project_manage_enabled` |

页面隐藏不是授权。每个入口对应的 API 必须在 `enterprise/interceptors.py` 或企业专用路由执行同一权限判定。

## 3. 管理后台权限开关设计

### 3.1 配置存储和安全默认值

配置保存到企业 SQLite 的 `enterprise_permission_settings`，由管理员 API 写入、读取并记录审计日志。不要存于前端 LocalStorage、上游 `global_config.json` 或 API provider 配置中。

| 开关 | 默认 | 影响范围 | 说明 |
| --- | --- | --- | --- |
| `user_api_settings_visible` | false | API 设置页面入口 | 即使 true，也不自动允许读写密钥。 |
| `user_api_settings_editable` | false | `/api/providers*`、`/api/config*` | 仅在明确产品决策后开放；响应仍必须脱敏。 |
| `user_workflow_settings_visible` | false | 工作流设置入口 | 普通用户可见不等于可编辑。 |
| `user_workflow_settings_editable` | false | workflow CRUD/run | 开放前需 workflow owner/ACL。 |
| `user_enterprise_home_visible` | true | 企业项目主页 | 仅企业仓库链接，不展示上游作者入口。 |
| `user_project_create_enabled` | true | 项目/文件夹创建 | 创建对象永远归当前用户。 |
| `user_project_manage_enabled` | true | 重命名、删除、移动、归档 | 只作用于 owner 项目，不能跨用户移动画布。 |
| `user_asset_library_enabled` | true | 私人素材库 | 全局共享库仍默认不可见。 |
| `user_asset_manage_enabled` | true | 私人素材 CRUD | 批量删除另行控制。 |
| `user_bulk_history_delete_enabled` | false | 历史批量删除 | 高破坏性，默认关闭。 |
| `user_comfy_enabled` | false | Comfy 入口/任务 | 需要任务与资源隔离完成后才开放。 |
| `user_video_enabled` | false | 视频生成 | 需要任务与资源隔离完成后才开放。 |
| `user_image_convert_enabled` | false | 图片转换 | 需要输入/输出归属链后才开放。 |
| `user_sharing_enabled` | false | 项目/画布/素材共享 | 关闭时没有任何跨用户可见性。 |
| `admin_transfer_ownership_enabled` | true | 管理员代管/转移 | 写审计，保留来源/目标 owner。 |

### 3.2 管理后台最小能力

后续 3G-6 才实现下列 UI，不在本设计 PR 改动页面：

1. “功能权限”页：系统级开关、说明、默认值、最后修改者和时间。
2. “项目归属”页：未归属项目、默认项目迁移、项目 owner 与画布 owner 不一致告警。
3. “数据迁移”页：未归属画布/对话/历史/素材的批量分配和 dry-run 统计。
4. “共享与代管”页：显式 grant、管理员在他人画布生成的资源归属与审计记录。
5. “风险状态”页：未映射总数、被拒绝资源请求、WebSocket 未覆盖事件和最近权限变更。

## 4. 分阶段实施计划

### 3G-1：只读矩阵与风险清单

- 交付本文与 `ENTERPRISE_ISOLATION_MATRIX.md`。
- 审核所有上游新增路由和数据域，不改业务代码。
- 把未知归属、高风险全局列表和 WebSocket 风险明确记录。
- 完成条件：设计经人工审核，后续子任务不再依赖口头约定。

### 3G-2：项目、文件夹与画布列表隔离

- 已新增 `project_id -> owner` 映射和每用户默认项目语义。
- 已拦截 `/api/projects` CRUD、项目下画布计数、画布创建/移动/元数据更新和回收站列表。
- 普通用户只能看自己的项目、数量和画布；unowned 项目仅管理员可见。
- 上游当前 `/api/projects` 为扁平项目节点，不提供独立 parent/folder 字段；本阶段将其作为项目/文件夹层的当前实现，保留映射表的 parent/visibility 字段供未来上游层级 API 使用。
- 未改 `main.py`；通过请求/响应过滤与企业数据库实现。

### 3G-3：历史记录与生成日志隔离

- 为在线生图、ZImage、Klein、Angle、Enhance、图片转换、video/Comfy 任务建立统一 task/history owner 链。
- 过滤 `/api/history`、保护删除、输出缩略图和生成日志投影。
- 保持 PR #21/#22 的 Smart Canvas 日志初始化、持久化、恢复补写与去重逻辑不回归。

### 3G-4：素材库与批量管理隔离

- 为 asset library、prompt library、local uploads、shared folders 建 owner/ACL 模型。
- 先关闭普通用户的全局/批量破坏性操作，再逐项开放私有能力。
- 所有批量删除、移动、导入、共享写审计日志。

### 3G-5：WebSocket 广播隔离

- 网关 WebSocket 连接绑定企业 user/session。
- 对 `new_image`、task completion、queue、canvas/asset 更新按 owner/scope fan-out。
- 未知事件先不向普通用户转发；管理员可见范围需显式定义。
- 加入连接伪造、跨用户事件和重连后的回归测试。

### 3G-6：后台权限开关与页面入口治理

- 实现上述权限开关、管理员 API、审计日志和企业注入层的入口显示。
- 后端先拒绝，前端再隐藏；不把安全策略放在 CSS/JS 单点。
- API 设置、工作流、平台登录、更新、企业治理入口均按开关与角色控制。

### 3G-7：浏览器级回归与长期维护文档

- 将 A/B/admin 核心场景逐步脚本化，维护 `UPDATE_TEST_LOG.md`。
- 每次上游同步强制复跑矩阵中“上游风险=高/严重”的项目。
- 增加未覆盖路由的发现检查，防止新增全局 API 静默上线。

## 5. 验收清单

每个实现子 PR 至少使用 A、B 两个普通用户和一个管理员账号，且测试数据必须可清理、不得提交。

### 项目、文件夹、画布

- [ ] A 创建项目，B 的项目列表、项目数量、默认项目视图均不可见。
- [ ] A 创建文件夹/项目层级，B 不可见；B 对项目 ID 的直接请求返回 404 风格响应。
- [ ] A 创建画布，A 列表可见，B 列表不可见；B 直接请求画布返回 404 风格响应。
- [ ] A 将画布移动到自己的项目可用；不能把画布移动到 B 的项目。
- [ ] 未归属项目、画布和回收站记录仅管理员可见，管理员分配后目标用户可见。

### 对话、资源、日志与历史

- [ ] A 创建对话，B 不可见且直接访问被拒绝；管理员可代管。
- [ ] A 生成图片，A 可见、管理员可见、B 不可见；A 的 input/output/缩略图均可加载。
- [ ] 管理员在 A 画布生成资源时，A 后续可见，B 不可见，审计记录 actor=管理员、scope owner=A。
- [ ] B 看不到 A 的 Smart Canvas 日志、在线生图历史、本地功能历史、历史缩略图或 output。
- [ ] 刷新、退出重登、打开旧画布后 owner、output 与生成日志仍生效；同一完成事件只保留一条成功日志。

### 入口、设置与 WebSocket

- [ ] 普通用户默认无法访问更新入口，`/api/update-*` 返回 403。
- [ ] API 设置和工作流设置按后台开关显示/隐藏，直接 API 调用也按同一策略拒绝或允许。
- [ ] 普通用户不可读取 API Key、Token、平台登录会话或其他敏感配置。
- [ ] WebSocket 不向 B 广播 A 的 `new_image`、task completion、canvas/resource 更新；管理员行为按明确策略验证。
- [ ] 企业项目主页始终指向企业仓库；普通用户不出现上游作者或上游更新入口。

## 6. 本设计 PR 的非目标

- 不处理模型调用、provider token、图片规格、第三方 API 或 2K/high 失败。
- 不实施 3G-2 至 3G-7 的业务代码。
- 不改 `main.py`、`static/`、`workflows/`、`API/`、`python/` 或 `VERSION`。
- 不修改、读取后提交或输出任何真实数据库、图片、缓存、密钥、Token、Cookie、`enterprise.env`、`API/.env`。
