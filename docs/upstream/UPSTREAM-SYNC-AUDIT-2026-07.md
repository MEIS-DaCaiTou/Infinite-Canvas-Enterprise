# U-1 上游同步只读审计报告

## 1. 审计结论摘要

本次不建议立即整体同步上游，也不建议直接 merge / rebase / cherry-pick `upstream/main`。

核心原因：

- 当前企业版 `origin/main` 与上游 `upstream/main` 没有可用 Git merge-base，不能按普通 fork 分支直接合并。
- 上游最新版本从 `2026.06.23` 演进到 `2026.07.6`，主要改动集中在 `main.py`、`static/`、新增 `CLI/`、新增内置 `python/`，并包含 `API/.env` 这类不应直接进入企业版的敏感路径。
- 企业版已经在 `enterprise/gateway.py`、`enterprise/interceptors.py`、`enterprise/db.py`、`enterprise/ws.py`、`enterprise-static/` 和 `enterprise/tests/` 建立登录、owner 隔离、权限开关、审计、WebSocket 过滤、任务历史隔离、用户治理等能力。上游覆盖区变更如果直接落入，会绕过或打断这些治理点。
- 上游 `static/angle.html` / `static/enhance.html` 仍不等价于企业版 PR #53 的 ModelScope / cloud 上传解耦修复；直接覆盖会回归该修复。

推荐策略：

1. U-2 只做小步、可回滚的上游覆盖区同步，不引入企业层兼容变更。
2. U-3 单独做企业层兼容适配，包括 gateway 注入、interceptors 路径策略、feature flags、task/resource owner 记录、WebSocket 事件过滤和测试补强。
3. U-4 做全量自动化回归与项目负责人 A/B/admin 浏览器验收。

最大风险点：

- `main.py` 新增 Codex / Gemini CLI provider 与 RunningHub 输出处理，会影响 provider 设置、任务 owner、输出资源 owner、history 和 feature gate。
- `static/js/smart-canvas.js`、`static/js/canvas.js`、`static/js/api-settings.js` 大幅变化，会影响企业注入脚本、设置入口治理、素材库 owner、local-assets、WebSocket 事件和任务轮询。
- 上游新增 `API/.env`、内置 `python/`、CLI 输出图片示例等内容，不应机械提交到企业版，存在敏感配置、二进制膨胀和运行时数据混入风险。

## 2. 审计基线

| 项目 | 值 |
| --- | --- |
| 企业版仓库 | `MEIS-DaCaiTou/Infinite-Canvas-Enterprise` |
| 企业版 commit | `872729b804cf7aa6fafa71ee98a5fbe836e0f55e` |
| 企业版 VERSION | `2026.06.23` |
| 上游仓库 | `hero8152/Infinite-Canvas` |
| 上游 remote | `https://github.com/hero8152/Infinite-Canvas.git` |
| 上游默认分支 | `main` |
| 上游最新 commit | `f1dd6834a72f3e7ff8340be05a84347d931e9cb9` |
| 上游最新 commit 时间 | `Mon Jul 6 18:13:58 2026 +0800` |
| 上游最新 commit message | `修复bug` |
| 上游 VERSION | `2026.07.6` |
| 本次审计使用的上游 ref | `upstream/main` |
| 审计时间 | `2026-07-07`，Asia/Shanghai |
| 审计方式 | `git fetch upstream --prune` 后只读 diff / grep / 文件检查；未 merge、未 cherry-pick、未修改业务代码 |

重要口径说明：

- `git merge-base origin/main upstream/main` 未返回共同祖先。因此 `git diff origin/main..upstream/main` 是“企业版当前树 vs 上游当前树”的树差异，不是可直接同步计划。
- 为了识别上游自身从企业版当前 `VERSION=2026.06.23` 到最新 `2026.07.6` 的演进，本报告同时参考上游 `0da3ff9ae0477e6e18b7c241020c2ce8cb0d5c73` 到 `f1dd6834a72f3e7ff8340be05a84347d931e9cb9` 的差异。`0da3ff9` 的上游 `VERSION` 同为 `2026.06.23`，可作为“上游版本演进参考”，但它不是 Git merge-base。

## 3. 当前企业版关键架构

当前企业版采用“上游主应用 + enterprise gateway + interceptors + enterprise DB 映射”的阶段性架构：

```text
浏览器 / 局域网用户
-> enterprise/gateway.py:8000
-> 登录认证 / JWT Cookie / 权限校验 / owner 记录 / 响应过滤 / HTML 注入
-> 上游 main.py:3001
-> data / assets / output / static / workflows
```

企业层主要承载：

- `enterprise/gateway.py`：登录态校验、JWT Cookie、反向代理、WebSocket 代理、设置页门禁、HTML 注入、企业后台入口。
- `enterprise/interceptors.py`：请求前置拦截、feature flag 守卫、owner 访问控制、上传/资源/任务/history/asset-library 响应后处理。
- `enterprise/db.py`：用户、owner map、feature flags、usage_logs、dry-run impact、soft delete/override 清理等企业 DB 能力。
- `enterprise/ws.py`：WebSocket connection registry、事件 owner 过滤、合成安全事件。
- `enterprise/admin_api.py`：成员管理、归属管理、权限开关、审计日志、用户删除 dry-run / soft delete / override purge。
- `enterprise-static/`：企业登录页、管理后台、操作日志、个人中心。
- `enterprise/tests/`：owner 隔离、上传资源隔离、素材库隔离、任务历史隔离、WebSocket 隔离、权限开关、成员治理等回归测试。

上游覆盖区主要包括：

- `main.py`
- `static/`
- `API/`
- `python/`
- `workflows/`
- `VERSION`
- 根目录启动脚本、README、配置、运行说明等

当前已完成能力包括：

- 登录认证 / JWT Cookie
- 管理员后台
- 普通用户 owner 隔离
- 项目 / 画布 / 对话归属
- 上传资源隔离
- 素材库业务 owner 隔离
- 异步任务历史隔离
- WebSocket 广播隔离
- feature flags 与权限开关审计
- soft delete / purge overrides / delete-impact dry-run
- 成员管理搜索 / 筛选 / 分页
- Angle / Enhance ModelScope 上传解耦

## 4. 上游差异总览

### 4.1 当前企业版树 vs 上游最新树

命令：

```powershell
git diff --stat origin/main..upstream/main
git diff --name-status origin/main..upstream/main
```

摘要：

```text
159 files changed, 23031 insertions(+), 36447 deletions(-)
```

目录级文件数量摘要：

| 目录 | 文件数 | 说明 |
| --- | ---: | --- |
| `python/` | 34 | 上游新增内置 Python 二进制运行时 |
| `static/` | 33 | 上游静态页面、JS、CSS 大量变化 |
| `enterprise/` | 32 | 上游没有企业目录，树差异表现为删除；不是同步建议 |
| 根目录 | 24 | README、VERSION、文档、启动脚本等差异 |
| `CLI/` | 19+ | 上游新增 CLI 安装脚本和示例输出 |
| `docs/` | 9 | 企业 docs 在上游不存在，树差异表现为删除；不是同步建议 |
| `enterprise-static/` | 4 | 上游没有企业静态后台，树差异表现为删除；不是同步建议 |
| `data/` | 2 | `data/asset_library.json` 新增，`data/api_providers.example.json` 差异 |
| `API/` | 1 | 上游新增 `API/.env` 空文件 |

由于没有 Git merge-base，上述 raw diff 只能说明“当前树不同”，不能作为机械同步清单。

### 4.2 上游自身从 2026.06.23 到 2026.07.6 的演进参考

命令：

```powershell
git diff --stat 0da3ff9..upstream/main
git diff --name-status 0da3ff9..upstream/main
```

摘要：

```text
59 files changed, 22414 insertions(+), 16457 deletions(-)
```

主要目录：

| 目录 | 文件数 | 说明 |
| --- | ---: | --- |
| `static/` | 33 | 页面与 JS/CSS 主体变化 |
| `CLI/` | 19+ | 新增 Gemini / Jimeng / OpenAI CLI 安装脚本 |
| 根目录 | 4 | README、VERSION、运行说明等 |
| `API/` | 1 | 新增 `API/.env` |
| `data/` | 1 | 新增 `data/asset_library.json` |

关键文件变更：

| 文件 / 目录 | 变化 |
| --- | --- |
| `main.py` | `2097` 行级 diff；新增 Codex / Gemini CLI provider、RunningHub 输出处理、provider 检测和若干路由 |
| `static/js/smart-canvas.js` | `32343` 行级 diff；大面积重排/功能变化，是最高风险静态文件 |
| `static/js/canvas.js` | `954` 行级 diff；画布节点、RunningHub、图片编辑、日志相关变化 |
| `static/js/api-settings.js` | `668` 行级 diff；provider 设置、Codex/Gemini CLI、RunningHub/Jimeng 逻辑变化 |
| `static/enhance.html` | `251` 行级 diff；上游仍不等价于企业 PR #53 的 ms 上传解耦 |
| `static/angle.html` | `18` 行级 diff；上游 cloud 可使用 file，但上传失败 UI 仍可停留为失败 |
| `static/css/*.css` | 多处 UI / 响应式变化 |
| `static/js/touch-mouse.js` | 新增 |
| `static/images/lingjing*.png` | 上游删除 |
| `data/asset_library.json` | 上游新增默认 asset library 数据 |
| `API/.env` | 上游新增空文件，不建议进入企业版 |
| `python/` | 在当前企业版树 vs 上游最新树中表现为新增大量二进制；不建议机械同步 |

## 5. 上游覆盖区变更分析

### 5.1 `main.py`

上游变化：

- `VERSION` 从 `2026.06.23` 更新到 `2026.07.6`。
- `main.py` 大幅变化，路由列表整体仍保留既有 API，但新增或扩展：
  - `GET /api/codex/status`
  - `POST /api/codex/help`
  - `GET /api/gemini-cli/status`
  - `POST /api/gemini-cli/help`
  - `SUPPORTED_PROVIDER_PROTOCOLS` 增加 `codex`、`gemini-cli`
  - Codex / Gemini CLI provider、chat、image generation 支持
  - RunningHub 输出 URL rewrite、workflow hidden overrides、模型 endpoint alias、`image_items` 返回结构
  - `online_image` 对 RunningHub query / output 的处理增强
  - `chat` / `chat_stream` 对 Codex / Gemini CLI provider 的处理

企业影响：

- `enterprise/interceptors.py` 当前按固定路径与 feature key 管理 provider、image tools、RunningHub、task owner、history、resource owner。新增 `codex` / `gemini-cli` 协议需要明确是否属于 `image_tools_generation`、`api_settings_access`、`workflow_settings_access` 或新的 feature key。
- 新增 CLI provider 可能读取本地 `~/.codex/auth.json` 或 CLI 环境，不能让普通用户通过 provider 设置或生成接口间接触碰本地凭据。
- RunningHub 返回结构变化会影响：
  - `user_task_map`
  - `record_resources_from_data`
  - `/api/runninghub/query`
  - WebSocket `cloud_status` / `task_updated`
  - history owner 记录
- `save_to_history`、`/api/history`、`/api/history/delete` 仍是企业历史隔离关键点，不能由上游直接覆盖后跳过 3G-6 逻辑。

同步判断：

- 不可机械同步。
- 必须人工适配并补测试。

### 5.2 `static/`

上游变化：

- `static/js/smart-canvas.js` 大幅变化，涉及上传、素材库、local-assets、history group、RunningHub、Comfy、canvas task、WebSocket、download-output、media-preview 等路径。
- `static/js/canvas.js` 大幅变化，涉及画布编辑、RunningHub 节点、图片编辑、日志、节点拖拽和输出。
- `static/js/api-settings.js` 增加 Codex / Gemini CLI provider，调整内置 provider 逻辑、RunningHub workflow 配置、provider 验证、模型获取。
- `static/angle.html` / `static/enhance.html` 仍调用 `/api/upload`，其中上游 `enhance.html` 在 `if (!uploadedPath)` 上仍阻断；直接覆盖会回归企业 PR #53。
- `static/online.html` 仍使用 `/api/ai/upload`，可作为 cloud 输入解耦参考。
- `static/js/touch-mouse.js` 新增；CSS 与小屏适配变化较多。

企业影响：

- 企业 gateway 的 HTML 注入和设置入口 guard 依赖上游 DOM、iframe、侧栏、`api-settings.html` / `comfyui-settings.html` 路径。`static/index.html`、设置页和侧栏变化必须回归 PR #30 / #32 / #49。
- Smart Canvas 与经典画布变更会影响 3G-4A / 3G-4B / 3G-5 / 3G-6 的关键路径：
  - `/api/ai/upload`
  - `/api/ai/import-local-image`
  - `/api/upload`
  - `/api/local-assets/*`
  - `/api/asset-library/*`
  - `/api/canvas-image-tasks`
  - `/api/canvas-comfy-tasks`
  - `/api/runninghub/*`
  - `/api/media-preview`
  - `/api/image-jpeg`
  - `/api/download-output`
  - `/ws/stats`
- `history-bulk-manager.js` query version 升级本身是低风险，但历史删除入口必须继续受 `history_batch_delete` 和 owner 隔离约束。

同步判断：

- `static/` 不可整目录覆盖。
- `static/js/touch-mouse.js` 可以作为候选机械同步，但需要确认引用位置与移动端行为。
- `static/angle.html` / `static/enhance.html` 必须手工三方合并，保留企业 PR #53 修复。
- `static/js/smart-canvas.js`、`static/js/canvas.js`、`static/js/api-settings.js` 必须人工适配，且应拆小 PR。

### 5.3 `API/`

上游变化：

- 新增 `API/.env` 空文件。

企业影响：

- `.env` 路径属于敏感配置高风险区。即使当前上游文件为空，也不应进入企业版提交习惯。

同步判断：

- 暂不接入。

### 5.4 `python/`

上游变化：

- 当前企业版树 vs 上游最新树显示上游包含大量 `python/` 二进制运行时文件。

企业影响：

- 会显著增加仓库体积。
- 可能与企业部署、Windows 本地 Python、venv、依赖安装方式冲突。
- 不属于企业 owner 隔离、权限治理或上游功能必要最小同步。

同步判断：

- 暂不接入，除非单独做运行时打包策略评审。

### 5.5 `workflows/`

本次 `0da3ff9..upstream/main` 未发现 `workflows/` 变更。

同步判断：

- 无需处理。

### 5.6 `VERSION`

上游变化：

- `2026.06.23` -> `2026.07.6`。

企业影响：

- 企业版不能只改 VERSION 宣称上游已同步；必须与实际覆盖区同步和回归结果一致。
- 如 U-2/U-3 分步同步，VERSION 更新应在对应阶段说明同步范围，或最后 U-4 后统一更新。

同步判断：

- 不建议单独机械同步 VERSION。

### 5.7 依赖 / 配置 / README

上游变化：

- README 小幅变化。
- 新增 CLI 安装脚本、运行说明。
- 未发现 `requirements.txt` / `pyproject.toml` / `package.json` 等依赖声明变化。

企业影响：

- README 可以人工提取上游说明，但企业版 README / docs 已承担交付边界，不应直接覆盖。
- CLI 脚本可能有用，但涉及本地工具安装、鉴权文件和示例输出，不应与企业功能同步混在同一 PR。

同步判断：

- 文档可人工摘取。
- CLI 暂不接入，或单独做 U-CLI 评审。

## 6. 企业层影响分析

### 6.1 `enterprise/gateway.py`

风险来源：

- 上游 `static/index.html`、设置页、侧栏、iframe、脚本版本变化可能破坏企业 HTML 注入、设置入口恢复/隐藏、无权限提示。
- 上游新增 `/api/codex/*`、`/api/gemini-cli/*`、provider 设置路径后，gateway 必须继续让普通用户走 feature gate，而管理员可 bypass。
- WebSocket `/ws/stats?client_id=...` 路径仍存在，但上游前端事件类型和 payload 可能变化。

建议：

- U-3 必须检查 `_build_enterprise_shell_guard()`、settings access denied、`reverse_proxy()`、`ws_proxy()`。
- 若上游 `index.html` DOM 变化，应优先企业层注入适配，不直接改上游 HTML。

### 6.2 `enterprise/interceptors.py`

风险来源：

- `interceptors.py` 中硬编码了大量上游路径、feature keys、上传 owner 记录、素材库过滤、task owner、history owner、asset-library owner、local-assets owner、输入复用鉴权。
- 上游新增 Codex / Gemini CLI provider 与 RunningHub output `image_items` 结构，需要补充 owner 记录与输入复用校验。
- 上游 `static/js/smart-canvas.js` 继续调用 `/api/upload`、`/api/ai/upload`、`/api/local-assets/*`、`/api/asset-library/*`、`/api/runninghub/*`、`/api/canvas-image-tasks` 等路径，任何字段变化都可能绕过当前提取逻辑。

建议：

- U-3A 专门评估新路径是否需要 feature flag、审计、owner 记录。
- U-3B 专门补 `record_resources_from_data()`、`_extract_runtime_input_resource_urls()`、task owner、history owner 兼容。
- 避免继续无限膨胀 `interceptors.py`，新策略逐步移到 `enterprise/policies/`。

### 6.3 `enterprise/db.py`

风险来源：

- 上游不直接改 enterprise DB，但上游新增业务对象和任务类型后，可能需要新增 map 或扩展已有 `user_task_map`、`user_resource_map`、`user_asset_object_map` 的 source / task_type。
- Codex / Gemini CLI 生成输出如果写入 `/output/*` 或 `/assets/*`，需要 owner 记录。

建议：

- 优先复用 `user_task_map` 与 `user_resource_map`。
- 只有明确出现新业务对象 owner 时再新增窄表。

### 6.4 `enterprise/admin_api.py`

风险来源：

- 上游新增 provider 协议会影响管理后台权限开关语义。
- 当前 admin API 与上游无直接同名冲突，但 PR #49 feature flags 需要覆盖新高风险接口。

建议：

- 新 CLI provider 状态/帮助接口默认归入 `api_settings_access` 或 `system_update`/新 feature key 前需要产品确认。
- 操作日志 action 下拉若新增审计事件，需要保持同步。

### 6.5 `enterprise-static/`

风险来源：

- 上游不包含企业后台，但 U-2/U-3 后可能需要在后台显示新 provider、feature key 或同步策略状态。
- 当前成员管理分页、soft delete、dry-run、override purge 不应被上游同步 PR 触碰。

建议：

- 上游同步 PR 不修改 `enterprise-static/admin.html`，除非 U-3 明确需要管理新 feature key。

### 6.6 `enterprise/tests/`

风险来源：

- 上游覆盖区同步会触发几乎所有企业回归测试。
- `test_angle_enhance_upload_decouple.py` 对 `static/angle.html` / `static/enhance.html` 尤其关键。
- `test_websocket_isolation.py` 对新事件类型和 payload 去重关键。

建议：

- U-2 可先做静态文件同步 + inline parse。
- U-3 必须运行完整 enterprise tests。

## 7. 已有企业能力风险矩阵

| 能力名称 | 风险等级 | 影响来源 | 风险描述 | 建议处理 | 测试建议 |
| --- | --- | --- | --- | --- | --- |
| 登录认证 / JWT Cookie | 中 | `static/index.html`、gateway 注入 | 上游 DOM 变化可能影响用户区、登录入口、管理后台入口 | U-3 检查 shell guard | 登录/登出、管理员/普通用户 |
| 管理员后台入口 | 中 | gateway 注入、`enterprise-static/admin.html` | 上游侧栏/更多设置 DOM 变化可能影响入口显示 | 保留企业层注入 | 浏览器验收后台入口 |
| 用户启用/禁用 | 低 | enterprise-only | 上游不直接影响，但登录校验需回归 | 不在 U-2 修改 | `test_user_delete_cleanup.py` |
| soft delete | 低 | enterprise-only | 上游不直接影响 | 不在同步 PR 修改 | soft delete 浏览器冒烟 |
| purge overrides | 低 | enterprise-only | 上游不直接影响 | 不在同步 PR 修改 | override purge 测试 |
| delete-impact dry-run | 低 | enterprise-only | 上游不直接影响 | 不在同步 PR 修改 | dry-run 测试 |
| feature flags | 高 | 新 provider / 新 API | Codex/Gemini CLI、RunningHub 新路径可能未进 feature gate | U-3 补路径矩阵 | `test_feature_flags.py` 扩展 |
| 成员管理搜索/筛选/分页 | 低 | enterprise-only | 上游不直接影响 | 不在同步 PR 修改 | `test_admin_member_list_filters.py` |
| 项目归属隔离 | 中 | `main.py` `/api/projects`、canvas JSON | 上游项目/画布结构变化可能影响过滤 | U-3 校验响应结构 | `test_ownership_isolation.py` |
| 画布归属隔离 | 高 | `static/js/canvas.js`、`smart-canvas.js`、`main.py` canvas routes | 保存/打开/移动路径变化可能绕过 owner | U-3 人工适配 | A/B 画布隔离 |
| 对话归属隔离 | 中 | `main.py` chat routes | Codex/Gemini CLI chat 分支可能绕过 conversation owner 记录 | U-3 补 post_process | 对话 A/B 隔离 |
| 上传资源隔离 | 高 | `static/js/smart-canvas.js`、`/api/upload`、`/api/ai/upload` | 新上传字段或 URL 字段可能未记录 owner | U-3 补 extractor | `test_upload_isolation.py` |
| 素材库隔离 | 高 | `data/asset_library.json`、`static/js/smart-canvas.js`、`asset-manager.html` | 上游新增默认 asset library 数据和 UI，可能引入 unowned / shared item | U-3 复核 asset object owner | `test_asset_library_isolation.py` |
| 异步任务历史隔离 | 高 | RunningHub / image task / Codex / Gemini CLI | 新 task id、`image_items`、output 字段可能未进 `user_task_map` | U-3 扩 task type | `test_task_history_isolation.py` |
| WebSocket 广播隔离 | 高 | `static/js/*` WS payload | 新事件或 payload 字段可能绕过 owner filter 或产生重复卡片 | U-3 更新 ws 策略 | `test_websocket_isolation.py` |
| usage_logs 审计 | 中 | 新高风险 API | 新 provider/CLI/status/help 操作是否审计不明确 | U-3 定义审计事件 | logs 筛选 |
| Angle 上传解耦 | 高 | `static/angle.html` | 上游不包含企业 `refreshAngleSubmitState` 修复 | 不可覆盖，手工合并 | `test_angle_enhance_upload_decouple.py` |
| Enhance 上传解耦 | 高 | `static/enhance.html` | 上游仍 `if (!uploadedPath)` 阻断 ms 分支 | 不可覆盖，手工合并 | `test_angle_enhance_upload_decouple.py` |
| 图片生成 / 编辑入口 | 高 | `online.html`、`zimage.html`、`canvas.js`、`smart-canvas.js` | 新 provider / RunningHub / CLI 可能改变任务/输出结构 | U-3 路径矩阵 | 真实 A/B/admin |
| API 设置入口治理 | 高 | `api-settings.js`、gateway settings guard | 新 provider 设置 UI 与新 API 路径需要守卫 | U-3 feature gate | `test_settings_permission_guard.py` |
| 设置入口 UX guard | 中 | `index.html` DOM | 入口隐藏/恢复可能失效 | U-3 浏览器验收 | `test_settings_entry_ux_guard.py` |
| 运行时 assets/output 访问 | 高 | `api/view`、`media-preview`、`download-output`、RunningHub rewrite | 新 output URL 或 remote URL 可能绕过 `can_access_resource` | U-3 归一化策略 | `/assets/*` A/B |

## 8. 同步策略分类

### 8.1 可机械同步候选

保守结论：本轮没有建议“无条件机械同步”的核心业务文件。以下仅是候选，仍建议单独 PR + 快速回归。

| 文件 / 目录 | 上游变化摘要 | 为什么相对低风险 | 建议进入 PR |
| --- | --- | --- | --- |
| `static/js/touch-mouse.js` | 新增触摸/鼠标适配脚本 | 如果未被引用，则不会改变现有行为；若引用需检查页面 | U-2B，随引用页面一起验证 |
| `static/css/canvas-list.css` | 新增 CSS | 主要视觉层，但可能依赖 HTML 类名 | U-2B，浏览器验收 |
| `README.md` 部分内容 | 小幅更新 | 可人工摘录，不影响运行 | docs-only 或 U-2 docs |
| `static/update-notes.json` | 更新说明 | 不应影响 owner，但可能影响更新 UI | U-2B，需结合 system_update gate |

不建议把 `VERSION` 单独作为机械同步文件。

### 8.2 需要人工适配

| 文件 / 目录 | 上游变化摘要 | 影响企业版原因 | 需要适配的企业层位置 | 建议测试 |
| --- | --- | --- | --- | --- |
| `main.py` | 新 provider、RunningHub、Codex/Gemini CLI、output 处理 | 新 API / 新 task / 新 output 字段需要 owner 与 feature gate | `enterprise/interceptors.py`、`enterprise/db.py`、`enterprise/tests/` | py_compile、feature/task/resource tests |
| `static/js/api-settings.js` | 新 provider UI、Codex/Gemini CLI、RunningHub 设置 | 普通用户设置入口默认 deny，管理员 bypass；新高风险路径需审计 | `gateway.py`、`interceptors.py`、`admin_api.py` | settings permission / entry UX |
| `static/js/smart-canvas.js` | 大幅变更，涉及上传、素材、任务、WS、history | 3G-4A/4B/5/6 核心路径密集耦合 | `interceptors.py`、`ws.py`、tests | upload/asset/task/ws/browser |
| `static/js/canvas.js` | 画布、RunningHub、图片编辑、日志变化 | 画布 owner、资源回溯、task owner、history group 风险 | `interceptors.py`、`db.py` | ownership/task/history |
| `static/angle.html` | 上游仍无企业稳态 refresh 函数 | 直接覆盖会回归 PR #53 | 手工三方合并 | angle/enhance decouple |
| `static/enhance.html` | 上游 ms 分支仍依赖 `uploadedPath` | 直接覆盖会回归 ModelScope 解耦 | 手工三方合并 | angle/enhance decouple |
| `data/asset_library.json` | 上游新增默认素材库 | 旧 unowned / 默认 library 与 3G-4B 业务 owner 冲突 | `interceptors.py`、`db.py` | asset library A/B/admin |
| `static/runninghub/api_providers.json` | RunningHub provider metadata 变化 | provider 设置、workflow、wallet key、模型列表均属高风险配置 | `interceptors.py` feature gate | settings + RunningHub |

### 8.3 暂不建议接入

| 文件 / 功能 | 上游变化摘要 | 暂不接入原因 | 后续接入前置条件 |
| --- | --- | --- | --- |
| `API/.env` | 新增空 env 文件 | 敏感配置路径，不应提交企业版 | 改为 `.env.example` 且无敏感值 |
| `python/` | 上游包含内置 Python 二进制 | 仓库体积、部署策略、供应链风险 | 单独运行时打包 ADR |
| `CLI/windows/openai/output/imagegen/*.png` | 示例输出图片 | 运行时/示例图片，不应进入企业版主 PR | 单独 demo assets 策略 |
| 整目录覆盖 `static/` | 上游静态大改 | 会回归企业注入、owner、feature gate、PR #53 | 拆页面/JS 小 PR |
| 直接覆盖企业 docs / enterprise 目录 | raw diff 中表现为上游删除 | 上游无企业层，不能删除企业能力 | 不适用 |
| Codex / Gemini CLI provider 直接开放给普通用户 | 新 provider 协议 | 涉及本地 CLI、auth 文件、凭据与执行安全 | feature key、审计、管理员策略先行 |

## 9. 后续 PR 拆分建议

### U-2：上游覆盖区同步规划 PR（Draft）

目标：

- 只同步低风险、可回滚的上游覆盖区文件。
- 不改企业层逻辑。

允许修改范围：

- 经确认的低风险 `static/css` / `static/js/touch-mouse.js` / update notes / docs。

禁止事项：

- 不同步 `main.py`。
- 不同步 `static/js/smart-canvas.js`、`static/js/canvas.js`、`static/js/api-settings.js`。
- 不同步 `API/.env`、`python/`、运行时图片。

测试：

- inline script parse。
- `test_settings_entry_ux_guard.py`。
- 浏览器基本打开。

### U-2A：后端上游文件人工同步 PR（Draft）

目标：

- 人工合并 `main.py` 中明确需要的上游修复。

允许修改范围：

- `main.py`。
- 必要时少量 docs。

禁止事项：

- 不改企业层兼容逻辑；若必须改，转入 U-3。

测试：

- `python -m py_compile main.py enterprise\*.py`
- 上游 API smoke。

### U-2B：静态页面 / JS 同步 PR（Draft）

目标：

- 按页面拆分同步 `static/`，每次只同步一个功能簇。

建议拆分：

- U-2B-1：API 设置页面
- U-2B-2：经典画布
- U-2B-3：Smart Canvas
- U-2B-4：Angle / Enhance / ZImage / Online

测试：

- inline script parse。
- 对应 enterprise tests。
- 项目负责人浏览器验收。

### U-3：企业层兼容修复 PR（Draft）

目标：

- 根据 U-2 引入的上游变化补企业 owner、feature、audit、WS、task、history 兼容。

建议拆分：

- U-3A：`enterprise/gateway.py` 兼容与 HTML 注入修复。
- U-3B：`enterprise/interceptors.py` 路径/owner/task/resource 兼容。
- U-3C：`enterprise/ws.py` 新事件/去重/owner 兼容。
- U-3D：`enterprise/tests/` 覆盖新增 provider / RunningHub / CLI 路径。

测试：

- 全量 enterprise 自动化测试。
- A/B/admin 浏览器验收。

### U-4：全量回归与手动验收 PR / 验收任务

目标：

- 不引入新功能，只修 U-2/U-3 后发现的回归。
- 完整跑自动化 + 项目负责人手动验收。

要求：

- Draft 到验收通过后再 Ready。
- 明确未提交运行时数据、assets、env、token。

## 10. 自动化测试矩阵

上游同步实现完成后，至少运行：

```powershell
python -m py_compile enterprise\db.py enterprise\admin_api.py enterprise\gateway.py enterprise\interceptors.py enterprise\config.py
python .\enterprise\tests\test_user_delete_cleanup.py
python .\enterprise\tests\test_admin_member_list_filters.py
python .\enterprise\tests\test_upload_isolation.py
python .\enterprise\tests\test_asset_library_isolation.py
python .\enterprise\tests\test_task_history_isolation.py
python .\enterprise\tests\test_feature_flags.py
python .\enterprise\tests\test_settings_entry_ux_guard.py
python .\enterprise\tests\test_websocket_isolation.py
python .\enterprise\tests\test_ownership_isolation.py
python .\enterprise\tests\test_settings_permission_guard.py
python .\enterprise\tests\test_history_isolation.py
python .\enterprise\tests\test_angle_enhance_upload_decouple.py
node --check static/js/smart-canvas.js
node .\enterprise\tests\test_smart_canvas_logs.js
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\diagnose.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\smoke.ps1
```

如上游同步涉及 `enterprise-static/admin.html` 或 inline HTML script，继续运行对应静态 parse 测试：

```powershell
python .\enterprise\tests\test_admin_member_list_filters.py
python .\enterprise\tests\test_settings_entry_ux_guard.py
```

如上游同步涉及 `main.py`、`static/js/canvas.js`、`static/js/smart-canvas.js`，建议补充：

- JS inline script parse。
- `node --check` 对独立 JS。
- Browser console error 检查。
- `/enterprise/health`。

## 11. 项目负责人手动验收清单

真实浏览器验收建议覆盖：

- 登录 / 登出。
- 管理员登录。
- 普通用户 A / B 登录。
- 管理员后台可访问。
- 成员管理搜索 / 筛选 / 分页。
- 用户禁用 / 启用。
- soft delete。
- purge overrides。
- delete-impact dry-run。
- 权限开关全局与用户 override。
- 项目归属管理。
- 画布归属管理。
- 对话归属管理。
- 操作日志筛选与详情。
- 普通用户只能看到自己的项目、画布、对话、历史、素材、任务。
- 管理员可见治理视图。
- 上传图片。
- `/assets/input/*`、`/assets/uploads/*`、`/assets/library/*` 访问隔离。
- local-assets 上传、移动、重命名、删除。
- 素材库主页面与经典画布 / Smart Canvas 右侧面板。
- 异步任务历史列表隔离。
- WebSocket stats、new_image、asset_library_updated、cloud_status 隔离。
- 经典画布打开 / 保存。
- Smart Canvas 打开 / 保存。
- GPT 对话打开 / 保存 / 流式输出。
- 在线生图。
- ZImage。
- Angle Control。
- Enhance / Z IMAGE。
- RunningHub 任务提交与查询。
- Comfy input/output。
- API 设置入口治理。
- 工作流设置入口治理。
- 普通用户直访设置页无权限提示。
- 管理员设置页正常。
- 移动端或窄屏基本可用性，如适用。

## 12. 未确认事项与阻塞问题

- 当前企业版与上游没有 Git merge-base，后续同步不能使用普通 `git merge upstream/main` 工作流。
- 上游新增 `Codex` / `Gemini CLI` provider 的安全边界尚未产品确认，尤其涉及本地 CLI、auth 文件、模型输出和普通用户是否允许使用。
- 上游 `data/asset_library.json` 默认数据如何映射到 `user_asset_object_map` 需要设计，不可直接把 unowned library 暴露给普通用户。
- 上游 `python/` 内置运行时是否进入企业版，需要单独架构决策。
- 上游 `API/.env` 不应进入企业版；如上游未来在该路径放真实 key，必须继续拒绝同步。
- 上游 `static/js/smart-canvas.js` 体量大、变更广，需单独小步同步与截图验收。

## 13. 附录

### 13.1 关键命令

```powershell
git rev-parse HEAD
git rev-parse origin/main
git status --short
git branch --show-current
git remote -v
git fetch upstream --prune
git ls-remote --symref upstream HEAD
git remote show upstream
git rev-parse upstream/main
git log -1 --oneline upstream/main
git log -1 --format=fuller upstream/main
git merge-base origin/main upstream/main
git diff --stat origin/main..upstream/main
git diff --name-status origin/main..upstream/main
git show 0da3ff9:VERSION
git diff --stat 0da3ff9..upstream/main
git diff --name-status 0da3ff9..upstream/main
git diff --stat 0da3ff9..upstream/main -- main.py static API python workflows VERSION requirements.txt pyproject.toml package.json README.md data/asset_library.json data/api_providers.example.json
rg -n '@app\.(get|post|put|delete|patch|websocket)|@app\.api_route' main.py
git show upstream/main:main.py | rg -n '@app\.(get|post|put|delete|patch|websocket)|@app\.api_route'
```

### 13.2 关键 diff 摘要

当前企业版树 vs 上游最新树：

```text
159 files changed, 23031 insertions(+), 36447 deletions(-)
```

上游 `0da3ff9` 到 `upstream/main`：

```text
59 files changed, 22414 insertions(+), 16457 deletions(-)
```

关键文件：

```text
main.py                         2097 行级 diff
static/js/smart-canvas.js       32343 行级 diff
static/js/canvas.js             954 行级 diff
static/js/api-settings.js       668 行级 diff
static/enhance.html             251 行级 diff
static/angle.html               18 行级 diff
```

### 13.3 需要复核的文件清单

高优先级：

- `main.py`
- `static/js/smart-canvas.js`
- `static/js/canvas.js`
- `static/js/api-settings.js`
- `static/angle.html`
- `static/enhance.html`
- `static/online.html`
- `static/zimage.html`
- `static/comfyui-settings.html`
- `static/js/comfyui-settings.js`
- `static/runninghub/api_providers.json`
- `data/asset_library.json`

企业层适配复核：

- `enterprise/gateway.py`
- `enterprise/interceptors.py`
- `enterprise/db.py`
- `enterprise/ws.py`
- `enterprise/admin_api.py`
- `enterprise-static/admin.html`
- `enterprise-static/logs.html`
- `enterprise/tests/`

明确暂不建议同步：

- `API/.env`
- `python/`
- `CLI/windows/openai/output/imagegen/sand-art-poster-16x9.png`
- 任何运行时 `assets/`、`output/`、数据库、缓存、token、cookie、env 文件
