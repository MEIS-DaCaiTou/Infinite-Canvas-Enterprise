# 无限画布企业版 · Agent 当前上下文入口

> 给后续 Codex / Agent 的第一阅读文件。上下文压缩、换线程、长期维护恢复时，先按本文阅读顺序恢复项目方向，再执行当前 Issue。

更新时间：2026-06-25

---

## 2026-07-06 阶段状态更新

3G 第一阶段 owner 隔离与安全治理底座已基本完成。已合并能力包括：

- 3G-4A 上传资源隔离，PR #34。
- 3G-4B 素材库完整隔离，PR #38。
- 3G-5 WebSocket 广播隔离，PR #42。
- 3G-6 异步任务历史 owner 隔离，PR #46。
- 3G-7A 管理员权限开关最小版 + 审计，PR #49。
- Issue #50 上游同步与 Angle / Enhance ModelScope 上传解耦只读定位已完成并关闭；结论是上游 2026.06.30 仍未修复该问题，当前不整体同步上游，Angle / Enhance 上传解耦后续单独小修。

当前项目还不是完整企业协作平台。第一阶段完成的是普通用户隔离、owner 归属、管理员兜底、关键 API 拦截、实时事件隔离、任务历史隔离、权限开关和审计记录。下一阶段应从 owner 隔离升级到协作权限设计，并在实现前明确 project members、canvas grants、共享/撤销、审计和迁移策略。

架构判断：上游 `main.py` / `static/` 保持内部上游服务，企业层通过 `enterprise/gateway.py`、`enterprise/interceptors.py`、`enterprise/db.py` 和 `enterprise-static/` 叠加多用户能力，这仍是当前阶段正确路线。长期风险是 `enterprise/interceptors.py` 已承载大量策略，后续新增策略应逐步模块化到 `enterprise/policies/`，避免继续扩大单文件拦截器。

端到端验收基线：新增 `docs/manual-acceptance-enterprise-e2e.md`，统一记录 admin / user_a / user_b 在项目、画布、对话、资源、素材库、历史、任务、WebSocket、权限开关上的前端入口和后端 API 双重验收路径。

---

## 1. 项目一句话定位

本项目的唯一方向是在上游开源项目 [hero8152/Infinite-Canvas](https://github.com/hero8152/Infinite-Canvas) 之上构建企业多用户版本。不得将本项目扩展为与企业多用户版 Infinite Canvas 无关的方向。

企业层本质是反向代理和权限隔离层：

- 对外服务：`enterprise/gateway.py` 监听 `0.0.0.0:8000`
- 内部上游：`main.py` 监听 `127.0.0.1:3001`
- 企业功能：登录、JWT Cookie、用户管理、画布归属、数据隔离、审计日志、健康检查、启动/停止闭环
- 上游功能：无限画布、资产、模型调用、更新按钮、静态前端资源

---

## 2. 阅读顺序

1. `PROJECT_HANDOFF_FOR_NEW_AGENT.md`：新 Codex 对话接手交接包，包含当前 main 状态、PR 时间线、数据模型、后续任务顺序和可复制接手提示词。
2. `PROJECT_CHARTER.md`：最高层项目定位文档，确认唯一方向是企业多用户版 Infinite Canvas。
3. `AGENT_CONTEXT.md`：当前真实状态、风险、路线，防止上下文压缩后跑偏。
4. `ARCHITECTURE.md`：当前企业网关覆盖上游的架构说明。
5. `CODE_BOUNDARIES.md`：代码修改边界，确认哪些文件可改、哪些默认不应改。
6. `CODEX_WORKFLOW.md`：Codex 每次任务的标准工作流和 PR 交付规则。
7. `SECURITY_BASELINE.md`：企业版安全配置、敏感文件和运行时配置治理基线。
8. `DEVELOPMENT_PLAN.md`：长期维护路线。
9. `ENTERPRISE_DOCS.md`：企业层完整开发规范。
10. `enterprise/tests/README.md`：测试脚本位置与用途。
11. `enterprise/tests/SMOKE_CHECKLIST.md`：每次上游更新后的必跑检查。
12. `enterprise/tests/BROWSER_REGRESSION_CHECKLIST.md`：浏览器级回归验收清单。
13. `enterprise/tests/browser-regression.md`：浏览器级回归自动化方案。
14. 必要时再读 `HANDOVER.md`：历史交接材料。该文件较长，部分终端可能显示乱码，不应作为唯一权威入口。

---

## 3. 当前实际状态

| 项 | 当前状态 |
|----|----------|
| 本地上游版本 | `2026.06.23` |
| 企业私有仓库 | `MEIS-DaCaiTou/Infinite-Canvas-Enterprise` |
| 企业仓库最新提交 | 以 `git log -1 --oneline` 为准；上游同步基线为 `hero8152/Infinite-Canvas@0da3ff9` |
| 上游源码仓库 | `hero8152/Infinite-Canvas` |
| 上游 bugfix PR | [hero8152/Infinite-Canvas#67](https://github.com/hero8152/Infinite-Canvas/pull/67)，状态 OPEN；2026-06-11 查询为 `CONFLICTING` |
| 当前运行端口 | `8000` 企业网关，`3001` 内部上游 |
| 当前健康检查 | `/enterprise/health` 返回 `gateway=ok`、`upstream=ok` |
| 测试脚本目录 | 统一放在 `enterprise/tests/`，不要散落到根目录或上游目录 |
| 安全基线 | 已新增 `enterprise.env.example`、`SECURITY_BASELINE.md`、`data/api_providers.example.json`；真实运行配置不应提交 |
| 用户管理审计 | 已增强启用/禁用、展示名更新、软删除兼容和关键用户管理审计日志 |

2026-06-11 维护中确认：12 个 `static/*.html` 改动均为资源版本参数从 `2026.06.02` 同步到 `2026.06.02.1`，用于让浏览器刷新缓存；这类改动属于上游静态资源版本归档，不是企业层功能开发方向。

2026-06-11 安全基线治理确认：`data/api_providers.json` 属于本地运行时模型配置，已加入 `.gitignore` 并通过 `git rm --cached data/api_providers.json` 停止 Git 跟踪；该操作不删除用户本地真实配置。生产部署前必须从 `enterprise.env.example` 复制生成本地 `enterprise.env`，并修改 `JWT_SECRET` 与 `ADMIN_PASSWORD`。

2026-06-11 用户管理审计增强确认：管理员 API 已支持 `PUT /enterprise/api/users/{id}/active` 启用/禁用用户、`PUT /enterprise/api/users/{id}/profile` 更新展示名；`DELETE /enterprise/api/users/{id}` 保持软删除兼容并返回禁用状态。创建用户、重置密码、修改角色、禁用/启用、修改展示名均写入审计日志，日志执行者为管理员 ID，detail 记录目标用户和动作摘要。管理后台做了最小适配，可编辑展示名并对账号执行启用/禁用。

2026-06-12 上游更新兼容性演练确认：Issue #9 在 `chore/upstream-update-compatibility` 分支将上游覆盖区域从 `2026.06.02.1` 更新到 `2026.06.11`。现有更新 API 因 GitHub anonymous REST tree rate limit 返回 HTTP 403，本轮改用受控手动同步：`git fetch upstream main` 后仅从 `hero8152/Infinite-Canvas@bc21b15` 替换 `main.py`、`VERSION`、`static/`。更新后 `enterprise/`、`enterprise-static/`、`enterprise.env.example`、`enterprise/tests/` 和企业文档未被上游覆盖。

2026-06-13 PR #10 复核补同步确认：上游 `hero8152/Infinite-Canvas` 已前进到 `9fb9a908c78f6d9e23fcfc03b7cf5d8b77ff3e0e`，真实 `VERSION` 为 `2026.06.12`。本轮在当前 `chore/upstream-update-compatibility` 分支继续同步，不新建分支/PR；同步范围从 `main.py`、`VERSION`、`static/` 扩展到 `workflows/`、`tools/`、`packages/`、`requirements.txt`、`get-pip.py`、`run.bat`、上游安装/登录脚本、README、macOS 脚本、运行说明和相关上游资源。`python/` 不提交，原因是企业仓库 `.gitignore` 明确将 `python/`、`python.zip` 作为本地运行时处理；当前本机仍使用本地 `python\python.exe` 运行验证。企业层 `enterprise/`、`enterprise-static/`、`enterprise.env.example` 未被上游覆盖。

2026-06-13 Issue #11 README 边界治理确认：根目录 `README.md` 必须是 Infinite Canvas Enterprise 企业版项目首页入口，不再由上游原版 README 占据。上游 README 如需保留，放在 `docs/upstream/README.upstream.md` 并标注仅供参考；上游同步策略记录在 `docs/upstream/SYNC_POLICY.md`。后续上游同步 PR 必须检查根目录 `README.md` 是否仍保持企业版定位。

2026-06-13 Issue #13 企业项目入口与更新权限治理：前端“项目主页”默认应指向企业仓库 `MEIS-DaCaiTou/Infinite-Canvas-Enterprise`，不再指向上游 `hero8152/Infinite-Canvas`。普通用户不应看到“一键更新”“更新到 vX”提示、更新弹窗、回滚/连通性测试入口或上游作者社交区；管理员看到的更新能力必须表述为企业版受控更新。当前实现优先放在 `enterprise/gateway.py` 的 HTML 注入脚本和 `enterprise/interceptors.py` 的响应/请求治理中，未直接修改 `static/index.html`。后续上游同步必须检查 `static/index.html` 的项目入口、版本更新 UI 和作者区 DOM 是否仍能被企业注入稳定治理。

2026-06-16 Issue #7 浏览器级回归验收体系：新增 `enterprise/tests/BROWSER_REGRESSION_CHECKLIST.md` 和 `enterprise/tests/browser-regression.md`，把启动健康、登录角色、管理后台、企业入口治理、画布、对话、素材输出资源、上游同步后验收和结果记录格式固化为长期维护清单。本任务只建立验收体系，不执行 Issue #8，不重新打开 Issue #15 / #16，不处理第三方图片模型高规格失败问题。

2026-06-16 Issue #8 多用户归属隔离加固：企业网关已将画布、对话和受保护本地资源的访问控制集中到 `enterprise/interceptors.py`。普通用户只能访问 `user_canvas_map` / `user_conversation_map` 中归属自己的画布和对话；未归属历史数据默认仅管理员可见，普通用户列表不可见且直接请求被拒绝。新建画布/对话会自动记录归属，管理员可在管理后台分配画布和对话归属。受保护资源路径覆盖 `/assets/input/`、`/assets/output/`、`/assets/uploads/`、`/assets/library/`、`/output/`、`/api/view`、`/api/download-output`、`/api/media-preview`；无法可靠判断归属的历史资源默认拒绝普通用户访问。

2026-06-23 Task 3U 受控上游同步：上游覆盖区域同步到 `hero8152/Infinite-Canvas@0da3ff9ae0477e6e18b7c241020c2ce8cb0d5c73`，`VERSION=2026.06.23`。根目录企业 README、企业层目录、企业测试和运行时忽略规则未被覆盖。上游新版 `static/js/smart-canvas.js` 未吸收 PR #21 的旧画布日志兼容逻辑，因此以最小迁移方式保留日志初始化、冲突合并和恢复/手工查询任务成功后的日志补写，并由 `enterprise/tests/test_smart_canvas_logs.js` 约束。上游新增的项目、图片转换和 Comfy 任务接口只记录为后续 Task 3G 的设计输入，本轮未扩展隔离规则。

2026-06-24 Task 3G-1 企业隔离设计基线：新增 `ENTERPRISE_ISOLATION_MATRIX.md` 与 `ENTERPRISE_PERMISSION_DESIGN.md`。已盘点项目/文件夹、画布、对话、资源、历史、素材、任务、WebSocket 和功能入口的存储与 API 面。当前画布、对话、受保护本地资源已有基础 owner 隔离；`/api/projects`、全局 `history.json`、素材库/批量管理、Comfy/video/图片转换任务、WebSocket 事件及 API/工作流权限开关尚未实现完整隔离。后续必须按 3G-2 至 3G-7 分阶段交付，普通用户对未知 owner 数据默认拒绝。

2026-06-24 Task 3G-2 项目、文件夹与画布列表隔离：新增 `user_project_map` 企业映射。普通用户 `/api/projects` 响应仅返回自己拥有的项目和按本人画布重算数量的虚拟默认项目；项目创建自动归属当前用户，项目更新/删除、画布创建、画布 meta/保存中的项目移动均验证 project owner，跨用户项目返回 404 风格无权限响应。管理员可查看全局项目、未归属项目及画布，并可在管理后台“项目归属”最小页面分配常规项目 owner；全局 `default` 项目不分配给单一用户。当前上游项目 API 为扁平节点，尚无独立 parent/folder 字段。

2026-06-25 PR #24 已合并到 `main`：最新合并提交为 `1f9ee81`。真实浏览器验收确认管理员将用户 A 的画布剪切/移动到用户 B 项目后，管理后台画布归属刷新为 B，A 重新登录不可见，B 重新登录可见且可生成 output，刷新/退出重登后 output 仍存在，管理员可见，其他普通用户不可见。新增 `PROJECT_HANDOFF_FOR_NEW_AGENT.md` 作为新 Codex 对话接手入口；后续推荐从 Task 3G-3 开始。

---

## 4. 不可偏离的开发边界

### 企业层功能优先放在企业层

企业化能力应优先在这些位置实现：

- `enterprise/`
- `enterprise-static/`
- `enterprise.env`
- `启动企业版.bat`
- `停止企业版.bat`
- `enterprise/tests/`
- 项目文档

### 上游文件默认不作为企业二开入口

以下属于上游更新覆盖面：

- `main.py`
- `static/`
- `workflows/`
- `API/`
- `python/`
- `VERSION`

原则：企业层不应为了企业功能修改上游文件。

例外：如果确认是上游项目自身 bug，可以先做最小本地热修用于生产验证，但必须同时：

1. 在文档中记录原因和影响范围。
2. 向上游提交 issue 或 PR。
3. 后续上游合并后移除本地热修差异。
4. 每次上游更新后按 `enterprise/tests/SMOKE_CHECKLIST.md` 重新验证。

---

## 5. 已完成的重要工作

- 企业版启动器改为受控双进程模型：内部上游 `127.0.0.1:3001`，企业网关 `0.0.0.0:8000`。
- 新增 `停止企业版.bat`，用于清理 `8000/3001` 监听。
- 新增诊断、冒烟、启动停止闭环脚本，统一在 `enterprise/tests/`。
- 修正 `/enterprise/health` 探测上游 `/api/app-info`，其语义是“上游可达性检查”，不是严格版本差异检查。
- 私有 GitHub 仓库已改为 `Infinite-Canvas-Enterprise` 并完成首次推送。
- 明确局域网地址选择策略：不固定主机 IP；`11.*` 地址如果受浏览器代理影响，本机可能访问失败，关闭代理或配置绕过后可正常访问。
- 发现 Smart Canvas LLM 节点“长时间运行”问题：本质是前端 `running` 临时状态被持久化或未及时保存清理，同时带 `*` 的通配模型名可被用户选中导致上游 503。
- 已向上游提交 PR：`hero8152/Infinite-Canvas#67`。
- 增强企业用户管理与审计闭环：启用/禁用、展示名更新、软删除兼容、关键用户管理操作审计日志，以及管理后台最小适配。
- 完成 Issue #9 / PR #10 上游版本更新兼容性演练并补同步：本地上游版本更新为 `2026.06.12`，诊断、冒烟、管理员用户管理、普通用户隔离、新建 Smart Canvas 归属和 Smart Canvas 打开验证均通过；`python/` 作为本地运行时不纳入 Git。
- 完成 Issue #11 README 边界治理：根目录 `README.md` 恢复为企业版入口，上游 README 移至 `docs/upstream/README.upstream.md`，并新增 `docs/upstream/SYNC_POLICY.md` 防止后续上游同步再次覆盖企业首页。
- 完成 Issue #8 多用户归属隔离加固：画布、对话、受保护资源默认按企业归属判断；未归属历史数据普通用户不可见、不可直接访问；管理员可查看并分配画布/对话归属。
- 完成 Task 3U 受控同步：上游覆盖区域升级到 `2026.06.23`，企业入口治理、普通用户更新权限、归属隔离和 PR #21 Smart Canvas 日志兼容逻辑均完成回归；`python/` 继续作为本地运行时，不纳入 Git。

---

## 6. 当前已知风险

1. 上游更新会覆盖 `main.py` 和 `static/`，因此任何上游热修都可能在更新后丢失。
2. `data/api_providers.json` 是运行时配置，已按安全基线停止跟踪并忽略；模型可用性需要以实际接口测试为准。
3. 内置 `python/` 运行时与 GitHub TLS 曾出现兼容问题；必要时用 PowerShell 下载上游文件绕过 Python SSL 问题。
4. `enterprise.env`、`API/.env`、`data/` 是运行态/敏感数据，不应提交到 Git；示例配置只能使用 `.example` 文件且不得包含真实密钥。
5. 多用户局域网使用依赖防火墙、代理绕过和主机当前网络路由，不能硬编码固定 LAN 地址。
6. 现有内置更新 API 依赖 GitHub anonymous REST tree 请求，可能因 rate limit 返回 HTTP 403；后续应考虑配置 GitHub token 或提供 git-fetch fallback。
7. 上游当前会跟踪 `python/` 运行时，但企业仓库目前将 `python/`、`python.zip` 视为本地运行时并忽略；后续如要改变该策略，必须单独评估仓库体积、平台兼容性和发布方式，不能在上游同步 PR 中顺手改变。
8. 根目录 `README.md` 是企业版项目入口，不应在上游同步中被上游 README 覆盖；如需保留上游 README，只能同步到 `docs/upstream/README.upstream.md`。
9. 受保护资源隔离目前以可从 URL、请求参数、响应数据、画布/对话引用或 `user_resource_map` 判断的本地资源为主；复杂嵌套素材集合和无法可靠归属的历史资源需要后续继续通过浏览器级回归和迁移流程补强。
10. Task 3G-1 设计已落地；3G-2 已完成当前上游扁平项目节点、项目计数和画布项目移动隔离。全局 `history.json`、素材库/批量管理、Comfy/video/图片转换任务、WebSocket 事件及 API/工作流权限开关仍必须按 3G-3 至 3G-7 单独 PR 交付，不能以 UI 隐藏替代 API 授权。

---

## 7. 后续维护原则

- 先稳运行，再稳维护，再扩功能。
- 每次上游更新后，先跑诊断和冒烟，再做功能开发。
- 遇到上游 bug：最小复现、最小补丁、提交上游 PR，本地只保留临时热修。
- 遇到企业需求：优先代理层、拦截层、企业前端实现。
- 不要把测试脚本、临时诊断脚本散落到项目根目录；统一放入 `enterprise/tests/`。
- 安全治理任务不得提交真实 API Key、Token、Cookie、数据库或运行时配置；本地开发体验可以保留，但生产/严格模式必须阻断明显危险默认值。
- 每次任务必须只处理当前 Issue，不扩大范围，不顺手重构无关代码。
- 后续任务必须通过独立分支和 PR 交付，不直接推 `main`。

---

## 8. 最近一次验证记录

验证时间：2026-06-13

已执行：

- 启动 `enterprise/launcher.py`，拉起 `127.0.0.1:3001` 与 `0.0.0.0:8000`。
- `enterprise/tests/test_start_stop.ps1 -StopExisting`（2026-06-12 已验证；本轮未重跑，避免中断当前服务）
- `enterprise/tests/diagnose.ps1`
- `enterprise/tests/smoke.ps1`
- Playwright 浏览器验证 `/enterprise/logs` 分页与 Smart Canvas 打开。

结果：

- 本机健康检查 `http://127.0.0.1:8000/enterprise/health`：HTTP 200。
- 内部上游 `http://127.0.0.1:3001/api/app-info`：HTTP 200，版本 `2026.06.12`。
- 监听端口：`0.0.0.0:8000`、`127.0.0.1:3001`。
- 本轮诊断选中的 LAN 地址：`11.0.1.98`；LAN 地址随部署主机网络环境变化，不应硬编码。
- Windows 代理开启：`127.0.0.1:7897`；代理可能影响对局域网地址的普通浏览器访问，必要时配置绕过。
- 冒烟检查全部通过：健康检查、登录页、管理员页鉴权、根路径鉴权/跳转。
- 启动/停止闭环在 2026-06-12 已通过：`test_start_stop.ps1 -StopExisting` 能启动、等待健康、释放 `8000/3001`；2026-06-13 本轮未重跑该破坏性检查。
- 管理员功能通过：登录、打开 `/enterprise/admin`、启用/禁用用户、编辑展示名、重置密码、审计日志出现 `user_disabled` / `user_enabled` / `user_profile_updated` / `user_password_reset`。
- `/enterprise/logs` 浏览器验证通过：默认 20 条，10/20/50/100 切换、上一页/下一页、用户筛选、操作类型筛选均正常。
- 普通用户功能通过：登录、只能看到授权画布、创建 Smart Canvas 后记录归属，更新/回滚相关 API 被管理员权限拦截。
- Smart Canvas 打开验证通过：测试画布标题加载，浏览器 console 0 error，未观察到明显永久 running 异常。

本轮手工验证创建了本地运行时测试画布、审计日志和 media preview cache；这些属于运行时数据，不得提交到 Git。

---

历史记录：

验证时间：2026-06-03

已执行：

- `enterprise/tests/diagnose.ps1`
- `enterprise/tests/smoke.ps1`

结果：

- 本机健康检查 `http://127.0.0.1:8000/enterprise/health`：HTTP 200。
- 内部上游 `http://127.0.0.1:3001/api/app-info`：HTTP 200，版本 `2026.06.02.1`。
- 监听端口：`0.0.0.0:8000`、`127.0.0.1:3001`。
- 当前推荐 LAN 地址：`11.0.1.98`。
- Windows 代理开启：`127.0.0.1:7897`；普通请求访问 `11.0.1.98:8000` 会被代理影响而超时。
- `curl --noproxy` 访问 `http://11.0.1.98:8000/enterprise/health`：HTTP 200。
- 冒烟检查全部通过：健康检查、登录页、管理员页鉴权、根路径鉴权/跳转。

本轮未执行 `test_start_stop.ps1 -StopExisting`，因为它会中断当前正在运行的服务。需要验证启动/停止闭环时，先告知当前页面会短暂不可用，再执行。
