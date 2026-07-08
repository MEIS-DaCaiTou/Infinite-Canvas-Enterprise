# U-2 上游受控同步实施记录

## 基线

- 企业版基线：`966a2aa021ae86fb732cd228e7928010febc1253`
- 上游仓库：`hero8152/Infinite-Canvas`
- 固定上游目标：`f1dd6834a72f3e7ff8340be05a84347d931e9cb9`
- 上游目标版本：`2026.07.6`
- 同步方式：基于 U-1 审计结果做补丁式受控合并，未 merge / rebase / cherry-pick `upstream/main`。

## 本轮接入范围

- `main.py`
  - 接入 2026.07.6 上游后端更新，包括 Codex / Gemini CLI provider、RunningHub 输出处理、`image_items` 兼容、workflow hidden override 相关变化。
- `static/`
  - 接入允许范围内的 HTML / JS / CSS 更新。
  - 新增上游 `static/js/touch-mouse.js`。
  - `static/angle.html` 人工合并并保留企业 PR #53 的 cloud / ModelScope 上传解耦。
  - `static/js/smart-canvas.js` 人工合并并保留企业 Smart Canvas 日志去重、pending task 恢复日志与 `image_items` 兼容。
- 企业层兼容
  - `enterprise/interceptors.py` 将 `/api/codex/status`、`/api/codex/help`、`/api/gemini-cli/status`、`/api/gemini-cli/help` 纳入 `api_settings_access` 权限治理。
  - `enterprise-static/logs.html` 增加 CLI provider 状态 / 帮助审计事件筛选项。
- 测试
  - 更新设置权限守卫测试，覆盖 Codex / Gemini CLI status/help。
  - 更新 Smart Canvas 日志测试，适配上游 `image_items` 与恢复日志上下文。
  - 新增 `test_upstream_sync_exclusions.py`，防止高风险上游 / 运行时目录进入提交。

## 明确跳过范围

- 未接入 `API/.env`。
- 未接入 `python/`。
- 未接入 `CLI/` 及其 `output/` 示例图片。
- 未接入 `assets/`、`output/`、数据库、缓存、运行时图片。
- 未接入 `data/asset_library.json`，避免绕过 3G-4B 素材库 owner 治理。
- 未接入真实 env、API Key、Token、Cookie、本地日志。
- `static/enhance.html` 未接入会移除企业 ModelScope Enhance 分支的上游变更，继续保留 PR #53 的上传解耦实现。

## 企业安全边界

- 新增 CLI provider 的设置面板状态和帮助接口默认只允许管理员或显式 `api_settings_access=allow` 的普通用户访问。
- 普通用户生成链路仍依赖既有 feature gates：
  - 图片工具生成：`image_tools_generation`
  - RunningHub 生成：`runninghub_generation`
  - 系统更新：`system_update`
- owner 记录继续复用既有映射：
  - `user_resource_map`
  - `user_task_map`
  - `user_canvas_task_map`
  - `user_asset_object_map`
- WebSocket 过滤策略未放宽，`new_image`、`asset_library_updated`、`cloud_status` 等仍按企业 owner / task owner 策略处理。

## 测试记录

已通过：

```powershell
python -m py_compile enterprise\db.py enterprise\admin_api.py enterprise\gateway.py enterprise\interceptors.py enterprise\config.py main.py
node --check static/js/smart-canvas.js
node --check static/js/canvas.js
node --check static/js/api-settings.js
node --check static/js/comfyui-settings.js
node --check static/js/touch-mouse.js
node --check static/js/theme.js
node .\enterprise\tests\test_smart_canvas_logs.js
python .\enterprise\tests\test_angle_enhance_upload_decouple.py
python .\enterprise\tests\test_settings_permission_guard.py
python .\enterprise\tests\test_upstream_sync_exclusions.py
python .\enterprise\tests\test_user_delete_cleanup.py
python .\enterprise\tests\test_admin_member_list_filters.py
python .\enterprise\tests\test_feature_flags.py
python .\enterprise\tests\test_settings_entry_ux_guard.py
python .\enterprise\tests\test_upload_isolation.py
python .\enterprise\tests\test_asset_library_isolation.py
python .\enterprise\tests\test_task_history_isolation.py
python .\enterprise\tests\test_websocket_isolation.py
python .\enterprise\tests\test_ownership_isolation.py
python .\enterprise\tests\test_history_isolation.py
```

补充执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\diagnose.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\smoke.ps1
```

说明：`diagnose.ps1` / `smoke.ps1` 返回通过，但当时 8000 / 3001 端口由原主工作区旧服务占用，因此仅作为现有服务健康记录，不作为 U-2 clean worktree 浏览器验收结论。

## 建议项目负责人手动验收

1. 登录 / 登出。
2. 管理员登录、普通用户 A / B 登录。
3. 管理员后台访问正常，普通用户不能访问管理后台。
4. 成员管理搜索 / 筛选 / 分页。
5. 用户禁用 / 启用、soft delete、purge overrides、delete-impact dry-run。
6. 权限开关全局与用户 override。
7. 项目 / 画布 / 对话归属管理。
8. 操作日志筛选与详情，包含 CLI provider 新审计事件。
9. 普通用户只能看到自己的项目、画布、对话、历史、素材、任务。
10. 上传图片与 `/assets/input/*`、`/assets/uploads/*`、`/assets/library/*` 隔离。
11. local-assets 上传、移动、重命名、删除。
12. 素材库主页面、经典画布右侧素材面板、Smart Canvas 右侧素材面板。
13. 异步任务历史列表隔离。
14. WebSocket stats / new_image / asset_library_updated / cloud_status 隔离。
15. 经典画布、Smart Canvas 打开 / 保存。
16. GPT 对话打开 / 保存 / 流式输出。
17. 在线生图、ZImage、Angle Control、Enhance / Z IMAGE。
18. RunningHub 任务提交与查询。
19. Comfy input / output。
20. API 设置入口治理、工作流设置入口治理、普通用户直访设置页无权限提示。
21. 如启用 Codex / Gemini CLI provider，验证普通用户权限边界和管理员入口。

## 剩余风险

1. 上游 `main.py` 与 `static/js/smart-canvas.js` 改动较大，仍需要项目负责人真实浏览器验收覆盖生成、画布保存、任务恢复和 RunningHub 输出。
2. Codex / Gemini CLI provider 依赖本机 CLI 登录态，本 PR 只治理设置入口与帮助 / 状态接口，不验证真实 CLI 环境。
3. `static/enhance.html` 为保留企业 ModelScope 上传解耦而跳过上游该文件变更，后续如需接入上游 Enhance 改动必须单独人工合并。
