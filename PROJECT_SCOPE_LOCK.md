# Infinite Canvas Enterprise · 项目定位与后续开发范围锁定

更新时间：2026-07-08
适用对象：ChatGPT 主对话、Codex、后续 Agent、人工审核者。  
状态：项目方向与后续开发范围已由项目负责人审核确认，后续任务不得偏离本文。

---

## 1. 项目整体定位

`Infinite-Canvas-Enterprise` 的唯一主线是在上游开源项目 `hero8152/Infinite-Canvas` 基础上构建企业多用户二次开发版本。

本项目不是：

- 普通上游本地部署说明。
- SaaS 多租户平台。
- 插件市场或工作流市场。
- 模型中转站、Provider 质量优化或第三方 API 故障排查项目。
- 大规模 UI 改版项目。

本项目当前目标是：

1. 尽量保留上游 Infinite Canvas 原有能力。
2. 通过企业网关和企业数据库叠加企业多用户能力。
3. 实现普通用户之间的数据隔离。
4. 实现管理员代管、归属迁移、审计日志和权限治理。
5. 建立可回归、可同步上游、可长期交给 Agent 维护的企业版系统。

当前系统链路：

```text
浏览器 / 局域网用户
        ↓
enterprise/gateway.py 企业网关，端口 8000
        ↓
登录认证 / JWT Cookie / 权限校验 / owner 记录 / 响应过滤 / HTML 注入
        ↓
main.py 上游服务，端口 3001
        ↓
data / assets / output / static / workflows
```

企业能力优先放在：

- `enterprise/`
- `enterprise-static/`
- `enterprise/tests/`
- 企业文档

默认不要修改上游覆盖区：

- `main.py`
- `static/`
- `workflows/`
- `API/`
- `python/`
- `VERSION`

如果必须修改上游覆盖区，必须在任务说明和 PR 描述中写清：原因、风险、回滚方案、后续上游同步影响。

---

## 2. 当前真实基线

依据 PR #60、#61、#62 合并后的主线状态，当前稳定开发基线为：

| 项 | 当前状态 |
|----|----------|
| 当前分支 | `main` |
| main / origin/main | `73a645f2bdded5df5c7109903c8b57eab9e3c459` |
| 当前上游基线版本 | `2026.07.6` |
| 固定上游目标 commit | `hero8152/Infinite-Canvas@f1dd6834a72f3e7ff8340be05a84347d931e9cb9` |
| PR #18-#62 | 已确认合并到 `main` |
| 最近关键合并 | PR #60 U-1 上游同步只读审计；PR #61 U-2 受控同步；PR #62 U-2-F1 / U-2-F2 history type 修复 |
| 最小浏览器确认 | `/api/app-info` 显示 `2026.07.6`；登录页、zimage/enhance/klein 页面可打开；user_a 刷新后历史仍在；user_b 不可见 user_a 历史 |
| Git 工作区 | 允许存在本地运行时 `assets/uploads/*` 未跟踪文件，不得 stage / commit |
| 运行时数据 | 本地存在 `enterprise.env`、`API/.env`、`data/enterprise.db`、`history.json`、`assets/`、`output/` 等，均不得提交 |

已完成的重要能力：

1. 画布、对话、受保护本地资源基础 owner 隔离。
2. 生成 output 资源 owner 补记。
3. output URL 规范化与旧画布资源回填。
4. Smart Canvas 旧日志持久化兼容。
5. 上游已由 PR #61 受控同步到 `2026.07.6`，保留企业补丁与企业治理能力。
6. 企业隔离设计与 API 矩阵文档。
7. 项目/文件夹/画布列表隔离。
8. 管理员跨用户项目移动画布后 canvas owner 自动同步。
9. 新 Agent 项目交接文档。
10. 历史记录隔离：在线生图历史、本地功能历史、全局 `history.json` owner 治理、列表过滤和删除鉴权。
11. API / 工作流高风险设置后端权限治理：普通用户不得管理 Provider、Key、Base URL、全局工作流等系统配置。
12. 普通用户隐藏 API 设置 / 工作流设置入口，并对直接访问设置页显示无权限提示。
13. 上传文件隔离与上传资源 owner 治理：上传 owner 记录、上传资源直链鉴权、local-assets 基础隔离、输入复用鉴权、画布迁移资源一致性。
14. asset-library 最小安全兜底：普通用户不能看到或管理其他用户 / unowned 的 `/assets/library/*` item。
15. 素材库完整隔离与素材业务 owner 治理：library / category / item 业务对象 owner、素材库主页面过滤、经典画布和 Smart Canvas 素材库面板过滤、素材库管理操作和 target library/category owner 校验、register-avatar / avatar-status owner 校验、shared folders 最小安全收紧、管理员审计、`/assets/library/*` item business owner 回溯读取。
16. WebSocket 广播隔离与实时事件 owner 治理：WebSocket 连接绑定 enterprise user，按 owner 过滤 `canvas_updated`、`asset_library_updated`、`new_image`、`cloud_status` 等实时事件，并清理 dead WebSocket connection。
17. 异步任务历史持久化列表隔离 owner 基线：RunningHub、provider image task query、Angle、ModelScope、video、image conversion、Smart Canvas / Comfy 本地 task 等异步任务 id 进入企业层 `user_task_map`，普通用户不能查询、复用、删除或轮询他人 task id；任务输出资源继续接入 `user_resource_map`。
18. 管理员权限开关最小版 + 审计：feature flag 全局开关、单用户 `inherit` / `allow` / `deny` 覆盖、管理员 bypass、权限变更审计、API/工作流设置入口与高风险提交类 API 后端守卫已由 PR #49 完成。
19. 用户删除影响 dry-run 预览：PR #55 已完成 `GET /enterprise/api/users/{id}/delete-impact`、成员管理影响预览入口和 `user_delete_dry_run` 审计。
20. soft delete 语义收口与 feature override 清理：PR #56 已完成删除自己/最后 active 管理员保护、后端 `confirm_username` 二次确认、用户权限覆盖清理和审计补强。
21. 成员管理可用性增强：PR #58 已完成成员搜索、状态/角色筛选、排序、默认隐藏已停用用户、统计和 25/50/100/全部分页。
22. 上游同步审计与受控同步：PR #60 完成 U-1 只读审计，PR #61 受控同步到上游 `2026.07.6`，跳过 `API/.env`、`python/`、`CLI/`、`assets/`、`output/`、`data/asset_library.json` 和敏感运行时文件。
23. U-2-F1 / U-2-F2：PR #62 已并入文生图 / Enhance 刷新后历史丢失定位报告，并修复 zimage / enhance / klein 云端 history type 一致性；企业 owner 过滤保持不变。

PR #24 后真实浏览器验收已确认：管理员将用户 A 的画布移动到用户 B 项目后，画布 owner 同步为 B；A 不可见，B 可见并可生成 output；刷新、退出重登后 output 仍可见；管理员可见；其他普通用户不可见。

项目/画布/资源归属链路、历史记录、上传文件、素材库、WebSocket 广播隔离和异步任务 owner 拦截已分别由前序 PR 完成。

Task 3G-6 风险边界：真实 RunningHub / ModelScope / provider 成功链路曾因缺少可用 Key 未完整补验，后续仍需在 3G-6 外部 provider 成功链路补验任务中以真实 Key / Provider 环境确认；这不影响当前 owner 拦截基线和 U-2-F2 已验证的 zimage / enhance / klein history type 修复。

Task 3G-7A 已由 PR #49 收口；Task 3G-7B 已由 PR #55 / #56 / #58 完成用户治理最小闭环。Issue #50 已完成只读定位；Angle / Enhance 上传解耦已由 PR #53 完成，U-2-F2 进一步修复云端生成刷新后 history type 一致性。

当前阶段结论：企业安全隔离底座第一阶段已基本完成，但项目还不是完整企业协作平台。下一阶段应从 owner 隔离升级到协作权限设计；在进入 team / workspace / project_members / canvas_grants 等实现前，先完成 DOC-1 文档体系同步、3G-8 浏览器级自动化回归和外部 provider 成功链路补验。

架构结论：当前“上游主应用 + enterprise gateway + interceptors + enterprise DB 映射”是阶段性正确路线；但 `enterprise/interceptors.py` 继续膨胀是长期风险，后续新增策略应逐步模块化到 `enterprise/policies/`。

---

## 3. 已批准进入开发主线的内容

项目负责人已审核确认，后续只允许围绕以下方向继续开发。

| 功能 | 审核结果 | 说明 |
|------|----------|------|
| 历史记录隔离 | 批准 | 处理在线生图历史、本地功能历史、全局 `history.json`、历史删除/批量删除鉴权。 |
| 素材库隔离 | 批准 | 处理 `assets/library`、素材分组、素材批量管理、素材列表过滤和直链鉴权。 |
| 上传文件隔离 | 批准 | 处理 `assets/uploads`、上传归属、上传列表、上传资源直链访问。 |
| WebSocket 广播隔离 | 已完成 | PR #42 已完成 `new_image`、任务完成、队列状态、画布更新、素材库更新等事件隔离。 |
| Comfy/video/图片转换任务历史隔离 | 已完成 | PR #46 已完成 Task 3G-6 owner 拦截基线；真实 RunningHub / ModelScope / provider 成功链路因缺 Key 后续补验。 |
| API 设置普通用户后端禁用 | 批准 | 普通用户默认不得读取、编辑、测试 API Provider、Key、Base URL 等敏感配置。 |
| 工作流设置普通用户后端禁用 | 批准 | 普通用户默认不得编辑全局工作流、Comfy、RunningHub 等高风险配置。 |
| 审计日志补强 | 批准 | 管理员迁移 owner、删除、批量操作、权限开关变更必须记录审计。 |
| 管理员权限开关 | 已完成 | PR #49 已完成 Task 3G-7A：管理员权限开关最小版、用户功能开关 / 访问控制开关、审计日志补强和管理员关键动作记录。 |
| 浏览器级自动化回归 | 批准 | 将 A/B/admin 验收路径逐步脚本化。 |
| 生产部署安全治理 | 批准但排后 | 包括默认密钥、默认管理员密码、运行时配置、备份恢复、生产启动检查等。 |

---

## 4. 暂缓内容

以下内容有价值，但当前不进入开发主线；如需启动，必须重新立项、重新审核。

| 功能 | 审核结果 | 暂缓原因 |
|------|----------|----------|
| 用户之间共享画布/素材 | 暂缓 | 需要 ACL、权限等级、撤销共享、共享审计，会显著复杂化当前 owner 模型。 |
| 每用户独立 API Key | 暂缓 | 会带来密钥存储、脱敏、额度、费用、泄露风险和调用隔离问题。 |
| SaaS 多租户 | 暂缓 | 需要 tenant/org/workspace 模型，当前先按单企业多用户推进。 |
| 复杂角色体系 | 暂缓 | 当前只保留管理员/普通用户两级，不做部门、角色模板、审批流。 |

---

## 5. 明确不批准内容

以下内容不得进入当前项目主线，Codex / Agent 不得顺手实现。

| 功能 | 审核结果 | 原因 |
|------|----------|------|
| 大规模 UI 改版 | 不批准 | 当前重点是安全隔离、权限治理和可维护性，不是视觉重构。 |
| 插件市场/工作流市场 | 不批准 | 会把项目扩张为平台生态，偏离企业多用户隔离目标。 |
| 模型质量/中转站适配优化 | 不放进当前主线 | Provider token、第三方中转、2K/high、模型质量问题不属于企业隔离主线。 |

如遇模型调用失败、Provider token 过期、第三方中转不稳定、2K/high 失败，应记录为 provider/runtime 问题，不得误判为企业隔离任务，也不得混入 3G 系列 PR。

---

## 6. 后续开发任务队列

### Task 3G-3：历史记录隔离

状态：已完成，PR #28。

范围：

- 在线生图历史。
- ZImage / Klein / Angle / Enhance 等本地功能历史。
- 全局 `history.json`。
- 历史列表过滤。
- 历史详情鉴权。
- 单条删除鉴权。
- 批量删除鉴权。
- 旧 unowned 历史普通用户不可见，管理员可见。
- 新历史自动归属当前用户。

不处理：素材库、上传文件、WebSocket、Comfy/video/图片转换任务历史、API 设置、工作流设置。

推荐 owner 模型：新增 `user_history_map`。不能只依赖 `timestamp` 作为权限依据。

### Task 3G-3B：高风险设置后端禁用

状态：已完成，PR #30。

范围：

- 普通用户默认不能读取、编辑、测试 API Provider / Key / Base URL。
- 普通用户默认不能编辑全局工作流设置。
- 管理员正常可用。
- 前端隐藏只是辅助，后端必须强制鉴权。

### Task 3G-3C：普通用户隐藏 API / 工作流设置入口与无权限提示

状态：已完成，PR #32。

范围：

- 普通用户左侧不显示 API 设置入口。
- 普通用户左侧不显示工作流设置入口。
- 普通用户直接访问设置页时显示“需要管理员权限”提示。
- 管理员仍可正常进入 API 设置和工作流设置。
- 不削弱 Task 3G-3B 的后端权限拦截。

### Task 3G-4A：上传文件隔离

状态：已完成，PR #34。

范围：

- `assets/uploads`。
- `/api/upload`。
- `/api/ai/upload*`。
- `/api/local-assets/upload`。
- 上传文件 owner。
- 上传文件直链访问。
- 上传文件列表过滤。
- local-assets 基础隔离。
- 作为模型输入复用时的资源 owner 校验。
- 管理员跨用户移动画布后的资源引用一致性。
- ComfyUI input/output 资源 owner 归一化与回归补强。
- asset-library 最小安全兜底。

PR #34 已完成上传文件 owner 记录、上传资源直链鉴权、local-assets 基础隔离、输入复用鉴权、画布迁移资源一致性，以及 asset-library 最小安全兜底。

PR #34 中的 asset-library 处理只是最小安全兜底：普通用户不能看到或管理其他用户 / unowned 的 `/assets/library/*` item。

不处理素材库 library/category/item 完整业务 owner、分组权限、共享、批量迁移、完整素材治理。这些仍属于 Task 3G-4B。

### Task 3G-4B：素材库完整隔离

状态：已完成，PR #38。

范围：

- `assets/library`。
- `data/asset_library.json`。
- `/api/asset-library*`。
- library / category / item 业务对象 owner。
- 素材库主页面过滤。
- 经典画布右侧素材库面板过滤。
- Smart Canvas 素材库面板过滤。
- 素材库管理操作 owner 校验。
- target library/category owner 校验。
- register-avatar / avatar-status owner 校验。
- shared folders 最小安全收紧。
- 管理员关键管理操作审计。
- `/assets/library/*` item business owner 回溯读取。

PR #38 已完成素材库业务 owner 治理。普通用户只能看到、使用和管理自己的素材库 library/category/item；不能通过 item id、category id、library id、目标分组或批量操作绕过权限。管理员可见 A/B/unowned 素材库对象，并对关键代管操作写审计。

不处理用户之间共享素材、复杂 ACL、SaaS 多租户、素材市场或 provider / 模型质量问题。

### Task 3G-5：WebSocket 广播隔离

状态：已完成，PR #42。

PR #42 已完成 WebSocket 广播隔离与实时事件 owner 治理，包括：

- WebSocket 连接绑定 enterprise user。
- query string / client_id 透传。
- client_id 不作为安全 owner。
- 企业层 WebSocket registry。
- `canvas_updated` 按 owner 过滤。
- `asset_library_updated` 普通用户拒收上游 ownerless 全局事件，并由 HTTP 成功后合成安全刷新。
- raw `new_image` 不再透传，并由企业层合成安全 `new_image`。
- `cloud_status` 保留路由但不信任 client_id。
- ownerless 敏感事件普通用户默认拒收。
- `stats` / `pong` 保持可用。
- 新版首页无 `online-val` 时企业壳层仍建立 `/ws/stats` keepalive。
- dead WebSocket connection 清理，避免关闭连接持续刷 send failed。

不重构上游任务系统。

不处理 Comfy / video / 图片转换 / RunningHub 任务历史隔离；这些已由 Task 3G-6 / PR #46 建立 owner 拦截基线，真实外部 provider 成功链路后续有 Key 后补验。

### Task 3G-6：异步任务历史隔离

状态：已完成，Issue #45 已按 completed 关闭，PR #46 已合并。

合并提交：`a7e7fbad3a1e6f9988439242accc3964bf6c6e49`。

范围：

- Comfy 任务。
- Video 任务。
- 图片转换任务。
- RunningHub 异步任务。
- canvas-comfy-tasks。
- canvas-video。
- image-jpeg。
- 任务 owner、任务查询鉴权、任务输出资源 owner。
- RunningHub / provider image / Angle / ModelScope / video / image conversion 等异步 task id 进入企业层 owner 治理。
- 普通用户查询未知 / unowned / 他人 task id 默认 404 风格拒绝。
- 管理员可放行治理，但已归属 task 的输出资源不因管理员查询而改归管理员。

3G-6 已完成任务历史持久化列表隔离的最小 owner 拦截基线，尤其是 Comfy、video、图片转换、RunningHub 等任务列表、任务详情、任务状态查询、历史记录持久化数据，不能让用户 A 看到、管理、复用或删除用户 B 的任务。

3G-6 不重新处理 3G-5 的 WebSocket 实时广播路由；如发现实时事件副作用，只记录为 3G-5 后续小修，不混入任务历史列表治理。

风险边界：真实 RunningHub / ModelScope / provider 成功链路仍需后续在可用 Key 环境补验；当前 PR #46 owner 拦截基线与 PR #62 history type 一致性修复均已合并。

### Task 3G-7A：管理员权限开关最小版 + 审计补强

状态：已完成，PR #49。

范围：

- 普通用户是否可见 API 设置。
- 普通用户是否可见工作流设置。
- 普通用户是否可用素材库管理。
- 普通用户是否可批量删除历史。
- 普通用户是否可用 Comfy / video / 图片转换等高风险能力。
- 用户功能开关 / 访问控制开关的最小实现。
- 管理员修改开关写审计日志。
- 管理员关键动作记录与审计日志补强。

只聚焦管理员权限开关最小版、用户功能开关 / 访问控制开关、审计日志补强和管理员关键动作记录。

不扩大到复杂 SaaS ACL、团队空间、计费、每用户 API Key、复杂角色体系或部门权限。

### Task 3G-7B-1：用户删除影响 dry-run 预览

状态：已完成，PR #55。

范围：

- `GET /enterprise/api/users/{id}/delete-impact`。
- 管理后台成员列表“影响预览”只读入口。
- `user_delete_dry_run` 审计。
- 不执行删除、不清理 owner mappings、不删除运行时文件。

### Task 3G-7B-2：soft delete 语义收口 + feature override 清理

状态：已完成，PR #56。

范围：

- `DELETE /enterprise/api/users/{id}` 明确为 soft delete / 禁用账号，不硬删 users 行。
- 后端强制 `confirm_username` 二次确认。
- 禁止删除自己。
- 禁止删除或禁用最后一个 active 管理员。
- `POST /enterprise/api/users/{id}/purge-overrides` 清理目标用户 feature overrides，并写审计。
- 不实现 owner transfer、cleanup-preview、cleanup 或运行时文件删除。

### Task 3G-7B-3：成员管理搜索 / 筛选 / 分页

状态：已完成，PR #58。

范围：

- 成员管理默认隐藏已停用用户。
- 状态筛选、角色筛选、用户名 / 展示名搜索、排序、统计。
- 25 / 50 / 100 / 全部分页。
- 项目归属、画布归属、对话归属表格分页。
- 不修改后端用户治理语义，不新增删除、转交或清理入口。

### U-1：上游同步只读审计

状态：已完成，PR #60。

范围：

- 只读分析企业版与上游差异。
- 形成 `docs/upstream/UPSTREAM-SYNC-AUDIT-2026-07.md`。
- 明确不能普通 merge upstream，后续必须受控同步。

### U-2：上游 2026.07.6 受控同步与企业兼容

状态：已完成，PR #61。

范围：

- 固定目标 `hero8152/Infinite-Canvas@f1dd6834a72f3e7ff8340be05a84347d931e9cb9`。
- 受控同步上游 `2026.07.6` 的 `main.py`、必要 `static/` 更新和 API 设置页相关文件。
- 保留企业 gateway / interceptors / owner / feature flag / WebSocket / 管理后台治理能力。
- 跳过 `API/.env`、`python/`、`CLI/`、`assets/`、`output/`、`data/asset_library.json` 和所有敏感运行时文件。

### U-2-F1 / U-2-F2：文生图与 Enhance 刷新后历史记录丢失定位和修复

状态：已完成，PR #62。

范围：

- `docs/bugs/U2-HISTORY-REFRESH-LOSS-INVESTIGATION.md` 记录只读定位结论。
- `/generate` 使用安全白名单后的 `req.type`，文生图云端保存 `type=zimage`。
- `/api/ms/generate` 支持安全白名单 type，默认 `klein`，Enhance 云端保存 `type=enhance`。
- `static/zimage.html`、`static/enhance.html`、`static/klein.html` 的云端请求 type 与刷新读取 type 保持一致。
- 不放宽 owner 过滤；user_a 刷新后历史仍在，user_b 不可见。

### DOC-1：文档体系全量同步与 Agent 交接资料更新

状态：当前正在执行。

范围：

- 同步当前稳定基线 `73a645f2bdded5df5c7109903c8b57eab9e3c459`。
- 同步上游版本 `2026.07.6`。
- 同步 PR #60 / #61 / #62 已完成事实。
- 更新 Agent 交接、范围锁、能力矩阵、权限设计、上游同步和 bug 报告文档。
- 只修改 Markdown，不修改业务代码。

### 下一阶段任务顺序

状态：DOC-1 完成后按以下顺序推进。

范围：

1. 3G-8：浏览器级自动化回归。
2. 3G-6 外部 provider 成功链路补验。
3. 3G-9：生产部署安全治理。
4. 协作权限设计 ADR + 端到端验收矩阵。
5. `enterprise/interceptors.py` 模块化只读审计。

当前不处理 team/workspace/project_members/canvas_grants 实现，不做数据库 schema 功能改造，不重构 `interceptors.py`，不再使用已清理的 U-1 / U-2 worktree，不做未经批准的新上游同步。

### Task 3G-8：浏览器级自动化回归

状态：批准。

范围：

- A/B/admin 登录。
- 项目隔离。
- 画布隔离。
- 历史隔离。
- 素材隔离。
- output 直链隔离。
- WebSocket 隔离。
- API 设置 / 工作流设置权限。
- 刷新、退出重登、直接 URL 访问。

### Task 3G-9：生产部署安全治理

状态：批准但排后。

范围：

- 默认 `JWT_SECRET` 风险。
- 默认管理员密码风险。
- `enterprise.env` 检查。
- `API/.env`、API Key、Cookie、Token 防提交。
- 数据库备份建议。
- `data/`、`assets/`、`enterprise.db` 备份恢复文档。
- 生产启动检查脚本。

---

## 7. 每次任务必须遵守的边界

每个 Codex / Agent 任务必须遵守：

1. 先同步 main，确认工作区干净。
2. 新建独立分支，不直接推 main。
3. 只处理当前任务，不把多个 Task 合并进一个 PR。
4. 不提交真实数据库、运行时图片、缓存、API Key、Token、Cookie、`enterprise.env`、`API/.env`。
5. 默认不修改 `main.py`、`static/`、`workflows/`、`API/`、`python/`、`VERSION`。
6. 不用前端隐藏代替后端鉴权。
7. 普通用户对未知 owner / unowned 数据默认拒绝。
8. 管理员可见全局数据，但删除、迁移、代管、权限变更必须审计。
9. Provider、模型、中转站、token、2K/high 失败不得混入企业隔离任务。
10. 有前端或权限行为时，必须做 A/B/admin 浏览器验收。
11. PR 必须保持 Draft，等待人工审核。
12. 安全治理不得破坏普通用户核心生成体验；限制系统设置管理，不限制正常生成能力。
13. 企业隔离优先在 `enterprise/`、`enterprise-static/`、`enterprise/tests/`、`docs/` 中实现。

---

## 8. 后续汇报模板

每个任务完成或阶段汇报必须包含：

- 任务编号。
- 任务目标。
- 当前状态。
- 修改范围。
- 不处理范围。
- 涉及文件。
- 涉及 API。
- 涉及数据表 / JSON / 目录。
- owner 模型。
- 普通用户行为。
- 管理员行为。
- 旧数据策略。
- 自动化测试。
- 浏览器验收。
- 风险。
- 回滚方案。
- 是否修改上游覆盖区。
- 是否提交运行时数据或敏感配置。
- 下一步建议。

---

## 9. 最终方向锁定

当前只批准：

- 企业隔离。
- 安全权限。
- 审计日志。
- 回归测试。
- 生产安全治理。

当前不批准：

- 用户共享。
- 每用户独立 API Key。
- SaaS 多租户。
- 复杂角色体系。
- 大规模 UI 改版。
- 插件市场 / 工作流市场。
- 模型质量 / 中转站适配优化。

后续 ChatGPT、Codex 或任何 Agent 如提出超出本文范围的开发计划，必须先回到人工审核，不得直接实施。
