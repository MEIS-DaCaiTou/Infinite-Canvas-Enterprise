# U2-F1 文生图 / 细节增强刷新后历史记录丢失定位报告

## 1. 问题摘要

PR #61 合并到企业版 `main` 后，浏览器复测发现：

- 文生图页面生成完成后会立即显示结果，但刷新后下方历史卡片消失。
- 细节增强页面生成完成后会立即显示结果，但刷新后 `ARCHIVE` 区域为空或显示 `END OF ARCHIVE`。

本次定位结论：

- `static/zimage.html` 的 ModelScope 云端路径是上游目标 commit 原始逻辑缺陷：页面刷新读取 `/api/history?type=zimage`，但后端 `/generate` 保存 `history.json` 时写入 `type: "cloud"`，导致刷新后查不到。
- `static/enhance.html` 的 ModelScope 分支是企业版 PR #53 为上传解耦保留的增强路径：前端刷新读取 `/api/history?type=enhance`，但它调用的后端 `/api/ms/generate` 固定保存 `type: "klein"`，导致刷新后查不到。
- `static/klein.html` 的本地和 ModelScope 路径在当前数据中表现一致：刷新读取 `/api/history?type=klein`，后端 `/api/generate` 或 `/api/ms/generate` 都可保存 `type: "klein"`，管理员视角能看到历史记录。
- 当前证据不支持“企业层 owner 过滤误删了可见历史”这一判断。`history.json`、`user_history_map`、`user_resource_map` 中 `cloud` / `klein` 记录均存在 owner 映射；普通用户看不到他人记录，管理员能看到，符合既有隔离策略。

## 2. 复现环境

- 企业版仓库：`MEIS-DaCaiTou/Infinite-Canvas-Enterprise`
- 当前分支：`chore/u2-f1-history-refresh-loss-investigation`
- 当前 main / origin/main：`25a9c65ee5739dc9f268d165f0a1dcbcbfe54ebc`
- 上游固定目标：`hero8152/Infinite-Canvas@f1dd6834a72f3e7ff8340be05a84347d931e9cb9`
- 启动目录：`D:\CodeProject\26-5-27-无限画布`
- 上游服务：`http://127.0.0.1:3001`
- 企业网关：`http://127.0.0.1:8000`
- `/api/app-info`：`version=2026.07.6`
- 验证用户：
  - admin 登录成功：`admin / admin123`
  - 普通用户隔离请求使用现有 active 普通用户 `codex_3g7a_a` / `codex_3g7a_b` 的临时 JWT Cookie，仅用于本地只读请求，未写入数据库。

说明：本次未删除 `history.json`、`data/enterprise.db`、`assets/`、`output/`，也未清理运行时现场。复现主要基于当前 main 的真实运行时数据、HTTP 查询结果和代码链路。未再次执行真实 provider 生成以避免产生更多运行时图片；当前 `history.json` 已包含项目负责人验收阶段生成的 `cloud` 与 `klein` 记录，足以验证刷新查询链路。

## 3. 复现矩阵结果

| 角色 | 路径 | 立即显示 | 刷新后显示 | 证据 | 判断 |
|---|---|---:|---:|---|---|
| admin | 文生图本地 `/api/generate` | 代码会 `renderImageCard(data, true)` | 当前无 `zimage` 记录可验证 | `/api/generate` 会按 `req.type` 保存；当前 `history.json` 中 `zimage=0` | 逻辑上应持久化为 `zimage`，但当前现场没有本地成功样本 |
| admin | 文生图 ModelScope `/generate` | 是 | 否 | `history.json` 中 `cloud=4`，`zimage=0`；`/api/history?type=zimage` 为空 | type 不匹配 |
| admin | Klein 本地 `/api/generate` | 代码会 `renderImageCard(result, true)` | 应显示 | `/api/generate` 按 `type:"klein"` 保存 | 逻辑一致 |
| admin | Klein ModelScope `/api/ms/generate` | 是 | 是 | `/api/history?type=klein`：3001 返回 11 条，8000 admin 返回 11 条 | 正常 |
| admin | Enhance 本地 `/api/generate` | 代码会 `renderImageCard(finalData, true)` | 当前无 `enhance` 记录可验证 | `/api/generate` 会按 `type:"enhance"` 保存；当前 `history.json` 中 `enhance=0` | 逻辑上应持久化为 `enhance`，但当前现场没有本地成功样本 |
| admin | Enhance ModelScope `/api/ms/generate` | 是 | 否 | 前端刷新 `/api/history?type=enhance`，后端保存 `type:"klein"` | type 不匹配 |
| user_a | 他人 `cloud/klein` 记录 | 不适用 | 不显示 | 8000 普通用户请求 `zimage/cloud/klein/enhance` 均返回 0 | owner 隔离生效 |
| user_b | 他人 `cloud/klein` 记录 | 不适用 | 不显示 | 8000 普通用户请求 `zimage/cloud/klein/enhance` 均返回 0 | owner 隔离生效 |

## 4. 3001 与 8000 对比结果

| 请求 | 3001 上游直连 | 8000 admin | 8000 普通用户 |
|---|---:|---:|---:|
| `/api/history?type=zimage` | 0 | 0 | 0 |
| `/api/history?type=cloud` | 4 | 4 | 0 |
| `/api/history?type=klein` | 11 | 11 | 0 |
| `/api/history?type=enhance` | 0 | 0 | 0 |

判断：

- 3001 自身 `type=zimage` 为空，8000 也为空，说明文生图云端不是企业过滤导致，而是上游保存为 `cloud` 后刷新查 `zimage`。
- 3001 与 8000 admin 对 `klein` 数量一致，说明企业层未丢失 Klein / ModelScope 历史记录。
- 普通用户看不到 admin/Aidan02 产生的 `cloud` / `klein` 记录，符合 owner 隔离。

## 5. `history.json` 检查结果

当前 `history.json`：

| type | 数量 |
|---|---:|
| `online` | 146 |
| `angle` | 2 |
| `cloud` | 4 |
| `klein` | 11 |
| `zimage` | 0 |
| `enhance` | 0 |

代表样本：

- `cloud`：`/assets/output/cloud_1783492035.png`，`type:"cloud"`，来源为 `static/zimage.html` 的 ModelScope `/generate`。
- `klein`：`/assets/output/ms_black-forest-labs_FLUX.2-klein-9B_1783492101.png`，`type:"klein"`，来源为 `/api/ms/generate`。

## 6. `user_history_map` 检查结果

当前 `user_history_map`：

| type | owner 映射数量 |
|---|---:|
| `angle` | 2 |
| `cloud` | 4 |
| `klein` | 11 |
| `online` | 59 |
| `zimage` | 0 |
| `enhance` | 0 |

代表样本：

- `cloud` 记录 owner：`Aidan02`，source=`generate`，resource=`/assets/output/cloud_1783492035.png`。
- `klein` 记录 owner：`Aidan02`，source=`api/ms/generate`，resource=`/assets/output/ms_black-forest-labs_FLUX.2-klein-9B_1783492101.png`。

判断：企业层能为 `/generate` 与 `/api/ms/generate` 生成结果补 owner 映射；问题不是 owner 记录完全缺失。

## 7. `user_resource_map` 检查结果

当前与本问题相关的资源 owner 统计：

| resource 前缀 | 数量 |
|---|---:|
| `/assets/output/cloud*` | 6 |
| `/assets/output/ms_*` | 11 |
| `/assets/output/zimage*` | 0 |
| `/assets/output/enhance*` | 0 |
| `/assets/output/online*` | 133 |

判断：`cloud` / `ms_` 输出资源已进入资源 owner 映射；刷新丢失不是因为图片资源 404 或 owner 未记录导致。

## 8. 前端调用链

### zimage 本地

- 文件：`static/zimage.html`
- 生成接口：`POST /api/generate`
- payload：`type: "zimage"`
- 成功显示：`renderImageCard(data, true)`
- 刷新加载：`GET /api/history?type=zimage`
- 后端预期：`/api/generate` 按 `req.type` 保存 `type:"zimage"`

### zimage ModelScope

- 文件：`static/zimage.html`
- 生成接口：`POST /generate`
- 成功显示：`renderImageCard({ timestamp: Date.now(), prompt, images: [data.url], type: 'cloud' }, true)`
- 刷新加载：`GET /api/history?type=zimage`
- 后端实际：`/generate` 保存 `record.type = "cloud"`
- 根因：前端刷新过滤 `zimage`，后端持久化 `cloud`。

### klein 本地

- 文件：`static/klein.html`
- 生成接口：`POST /api/generate`
- payload：`type: "klein"`
- 成功显示：`renderImageCard(result, true)`
- 刷新加载：`GET /api/history?type=klein`
- 后端预期：`/api/generate` 按 `req.type` 保存 `type:"klein"`

### klein ModelScope

- 文件：`static/klein.html`
- 生成接口：`POST /api/ms/generate`
- 成功显示：前端构造 `resultData.type = "klein"` 后 `renderImageCard(resultData, true)`
- 刷新加载：`GET /api/history?type=klein`
- 后端实际：`/api/ms/generate` 保存 `record.type = "klein"`
- 当前表现：3001 和 8000 admin 都能看到 `klein` 记录。

### enhance 本地

- 文件：`static/enhance.html`
- 生成接口：`POST /api/generate`
- payload：`type: "enhance"`
- 成功显示：`renderImageCard(finalData, true)`
- 刷新加载：`GET /api/history?type=enhance`
- 后端预期：`/api/generate` 按 `req.type` 保存 `type:"enhance"`

### enhance ModelScope

- 文件：`static/enhance.html`
- 生成接口：`POST /api/ms/generate`
- 成功显示：前端构造 `finalData` 后 `renderImageCard(finalData, true)`
- 刷新加载：`GET /api/history?type=enhance`
- 后端实际：`/api/ms/generate` 固定保存 `record.type = "klein"`
- 根因：前端刷新过滤 `enhance`，后端持久化 `klein`。

## 9. 后端保存链

### `/api/generate`

- 文件：`main.py`
- `GenerateRequest.type` 默认 `zimage`。
- 结果对象包含 `"type": req.type`。
- 生成成功后调用 `save_to_history(result)`。
- 适用于本地 ComfyUI 生成、Klein 本地、Enhance 本地。

### `/generate`

- 文件：`main.py`
- 注释为 “ModelScope Z-Image 云端生图”。
- 成功后构造：
  - `{"timestamp": time.time(), "prompt": req.prompt, "images": [local_path], "type": "cloud"}`
- 调用 `save_to_history(record)`。
- 返回给前端：`{"url": local_path}`。
- 问题：没有保存为 `zimage`，也没有返回完整 history record；前端临时构造的卡片类型也是 `cloud`。

### `/api/ms/generate`

- 文件：`main.py`
- 注释为 “ModelScope 通用图片生成（支持图生图）”。
- 成功后固定构造：
  - `type: "klein"`
  - `model: req.model`
- 调用 `save_to_history(record)`。
- 返回给前端：`{"url": local_path, "task_id": task_id}`。
- 问题：该接口被 `static/enhance.html` 的 ModelScope 分支复用，但后端没有接收或保存调用方期望的 `type:"enhance"`。

### `/api/history`

- 文件：`main.py`
- 过滤逻辑：`item.get("type", "zimage") == type`
- 因此：
  - `type=zimage` 不会返回 `type=cloud`。
  - `type=enhance` 不会返回 `type=klein`。

## 10. 企业层过滤链

### post_process owner 记录

- 文件：`enterprise/interceptors.py`
- `_HISTORY_GENERATION_PATHS` 已覆盖：
  - `api/online-image`
  - `api/image-task-query`
  - `api/angle/generate`
  - `api/angle/poll_status`
  - `generate`
  - `api/ms/generate`
  - `api/generate`
- `_history_records_from_generation_payload()` 支持：
  - 响应直接含 `images` + `timestamp` 时直接记录。
  - 响应只有 `url` / `task_id` 时，回查 `history.json`，按资源 URL 或 task id 匹配刚保存的 record。
- 当前 `cloud` 和 `klein` owner 映射已存在，说明匹配链有效。

### filter_history_list

- `GET /api/history` 后置过滤只保留：
  - admin 可见所有记录；
  - 普通用户仅可见 owner 是自己的记录；
  - 普通用户默认看不到 unowned / 他人记录。
- 当前 admin 能通过 8000 看到 `cloud=4`、`klein=11`；普通 A/B 均看不到他人记录，符合预期。

## 11. 上游对比结论

固定上游目标 `f1dd6834a72f3e7ff8340be05a84347d931e9cb9`：

- `static/zimage.html`：与当前企业版相关逻辑一致，ModelScope 路径调用 `/generate`，刷新读取 `/api/history?type=zimage`，临时卡片 `type:'cloud'`。
- `static/klein.html`：与当前企业版相关逻辑一致，ModelScope 路径调用 `/api/ms/generate`，刷新读取 `/api/history?type=klein`。
- `main.py`：与当前企业版相关逻辑一致，`/generate` 保存 `type:"cloud"`，`/api/ms/generate` 保存 `type:"klein"`。
- `static/enhance.html`：当前企业版与上游不同。上游目标中未包含当前企业版的 ModelScope Enhance 上传解耦分支；企业版保留 PR #53 后，Enhance ModelScope 分支调用 `/api/ms/generate`，因此被 `/api/ms/generate` 固定 `type:"klein"` 影响。

结论：

- 文生图 ModelScope 刷新丢失：上游目标自身存在的 type 不匹配问题，U-2 同步后被带入企业版。
- Enhance ModelScope 刷新丢失：企业版增强路径与上游 `/api/ms/generate` 固定 `klein` 语义不兼容。
- Klein ModelScope 刷新：当前逻辑与上游一致，按现有数据可以刷新显示。

## 12. 根因判断

| 路径 | 根因 |
|---|---|
| 文生图本地 | 当前现场没有 `zimage` 成功样本；代码链路应持久化为 `type:zimage`。若未来仍丢失，应优先查 Comfy 本地生成是否成功写入 `history.json` 与 `user_history_map`。 |
| 文生图 ModelScope | `/generate` 保存 `type:"cloud"`，而 `zimage.html` 刷新只查 `/api/history?type=zimage`。立即显示来自前端临时 `renderImageCard()`，刷新后查询不到。 |
| Klein 本地 | 代码链路一致，`/api/generate` payload 和刷新均为 `klein`。当前未发现根因级缺陷。 |
| Klein ModelScope | 代码链路一致，`/api/ms/generate` 保存 `klein`，刷新查 `klein`。当前 3001/8000 admin 均能看到 11 条记录。 |
| Enhance 本地 | 当前现场没有 `enhance` 成功样本；代码链路应持久化为 `type:enhance`。若未来仍丢失，应查 Comfy 本地生成是否写入历史。 |
| Enhance ModelScope | `enhance.html` 刷新查 `type=enhance`，但复用 `/api/ms/generate` 后端固定保存 `type=klein`。立即显示来自前端临时 `renderImageCard()`，刷新后查询不到。 |

## 13. 最小修复建议

建议进入单独修复任务，不在本只读报告中直接改代码。

### 方案 A：让调用方传递并持久化业务 type（推荐）

1. 扩展 `MsGenerateRequest`：
   - 新增 `type: str = "klein"`，白名单限制为 `klein` / `enhance` 等明确调用方。
2. `static/enhance.html` ModelScope 分支调用 `/api/ms/generate` 时传 `type:"enhance"`。
3. `static/klein.html` 保持传或默认 `type:"klein"`。
4. `/api/ms/generate` 保存 `record.type = req.type`。
5. 返回响应可包含完整 history record 字段，减少前端临时构造和后端真实记录不一致。

### 方案 B：拆分专用接口

为 Enhance ModelScope 新增专用后端路径，例如 `/api/ms/enhance`，保存 `type:"enhance"`。优点是语义清晰，缺点是接口和权限治理面更大。

### 方案 C：前端读取多个 type（不推荐作为主修）

`zimage.html` 同时读取 `zimage` 与 `cloud`，`enhance.html` 同时读取 `enhance` 与 `klein`。这会模糊不同页面归档边界，可能把 Klein 页面历史混入 Enhance 页面，存在 UX 与隔离语义风险。

### zimage ModelScope 修复建议

1. 将 `/generate` 保存记录类型从 `cloud` 调整为 `zimage`；或
2. 增加 `CloudGenRequest.type` 使用并默认 `zimage`，保存 `record.type=req.type`；或
3. 新增 `/api/zimage/generate` 语义化接口。

优先建议使用 `CloudGenRequest.type`，因为该模型已有 `type: str = "zimage"` 字段，只是当前 `/generate` 未使用。

## 14. 建议新增测试

建议新增或扩展：

- `enterprise/tests/test_history_refresh_persistence.py`
  - `/generate` 成功响应后，`history.json` 记录应为 `type=zimage`，`/api/history?type=zimage` 可返回。
  - `/api/ms/generate` 在 `type=enhance` 请求下应保存 `type=enhance`。
  - `/api/ms/generate` 在 Klein 请求下仍保存 `type=klein`。
  - 企业 `post_process` 对 `{url: ...}` 响应能回查历史并记录 `user_history_map`。
  - 普通用户 A 刷新能看到自己的 zimage/enhance 历史。
  - 普通用户 B 看不到 A 的 zimage/enhance 历史。
  - 管理员能看到 A/B 历史。

建议补前端静态测试：

- `static/zimage.html` ModelScope 成功卡片 type 与刷新 type 一致。
- `static/enhance.html` ModelScope 请求传递业务 type，刷新 type 与后端保存 type 一致。
- `static/klein.html` 仍使用 `type=klein`。

建议回归测试：

- `test_history_isolation.py`
- `test_task_history_isolation.py`
- `test_angle_enhance_upload_decouple.py`
- `test_feature_flags.py`
- `test_settings_entry_ux_guard.py`
- `test_upstream_sync_exclusions.py`

## 15. 风险边界

后续修复必须保持：

- 不破坏 owner 隔离。
- 不让 user_b 看到 user_a 的历史。
- 不把 `cloud` 历史粗暴暴露给所有 `zimage` 页面用户。
- 不把 Klein 页面历史混入 Enhance 页面。
- 不提交运行时图片。
- 不提交 `history.json`。
- 不提交 `data/enterprise.db`。
- 不提交 `assets/`、`output/`。
- 不提交 `enterprise.env`、API Key、Token、Cookie 或本地日志。

## 16. 关键命令摘录

```powershell
git rev-parse HEAD
git rev-parse origin/main
git status --short --untracked-files=all

Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:3001/api/app-info'
Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:3001/api/history?type=zimage'
Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:3001/api/history?type=klein'
Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:3001/api/history?type=cloud'
Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:3001/api/history?type=enhance'

Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/enterprise/login' -Method POST
Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/history?type=zimage'
Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/history?type=klein'
Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/history?type=cloud'
Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/history?type=enhance'

git show f1dd6834a72f3e7ff8340be05a84347d931e9cb9:static/zimage.html
git show f1dd6834a72f3e7ff8340be05a84347d931e9cb9:static/klein.html
git show f1dd6834a72f3e7ff8340be05a84347d931e9cb9:main.py
```

