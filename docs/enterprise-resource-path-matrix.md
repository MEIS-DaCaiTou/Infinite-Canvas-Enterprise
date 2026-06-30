# Enterprise Resource Path Matrix

更新时间：2026-06-30

本文记录企业版本地资源路径、owner 来源、访问和删除策略。后续上游同步如新增上传目录、返回 URL 或资源代理接口，必须更新本文并补测试。

| 路径 / 接口 | 资源类型 | 主要来源 | Owner 来源 | 普通用户策略 | 管理员策略 | 删除 / 管理策略 | 当前任务 |
|---|---|---|---|---|---|---|---|
| `/assets/input/*` | 上传输入、参考图、附件、workflow import 资源 | `/api/ai/upload`、`/api/ai/upload-base64`、`/api/ai/import-local-image`、`/api/canvas-workflows/import` | `user_resource_map` | owner 可读；canvas/conversation 引用可读/可运行；unowned 拒绝 | 可读全局 | 不在历史删除中清理；上传管理另行鉴权 | 3G-4A |
| `/assets/input/<comfy_name>` | ComfyUI input 稳定 key | `/api/upload`、`/api/comfyui/upload-base64` | `user_resource_map` | owner 可通过 `/api/view?type=input` 预览并作为 `/api/generate` 输入；他人拒绝 | 可读全局 | 不直接管理 ComfyUI 后端文件 | 3G-4A |
| `/assets/uploads/*` | 本地上传素材 | `/api/local-assets/upload`、`/api/local-assets/import-urls` | `user_resource_map` | 只在 `local-assets` 列表中显示真实 owner 的文件；canvas 引用可读/可运行 | 可见全局 | delete/move/rename/caption/classify 需要真实 owner；管理员写审计 | 3G-4A |
| `/api/local-assets` | 本地上传素材列表和 tree | `assets/uploads` 扫描 | item URL 对应 `user_resource_map` | 过滤 `items/files/tree`，重算 count | 全量返回 | 不作为安全边界，后端逐项校验写操作 | 3G-4A |
| `/api/view?filename=...&type=input` | 输入预览代理 | ComfyUI input 或本地 `assets/input` 回退 | 归一化为 `/assets/input/<filename>` | owner 或 canvas/conversation scope 可读 | 可读全局 | 只读 | 3G-4A |
| `/api/view?filename=...&type=output` | ComfyUI output 预览代理 | ComfyUI output、画布 Comfy task result | 归一化为 `/assets/output/<subfolder>/<filename>` | owner 或 canvas/conversation scope 可读 | 可读全局 | 只读；`filename/type=output` 不当作 input | 3G-4A |
| `/api/media-preview?url=...` | 缩略图代理 | 任意本地资源 URL | 原 URL 对应 owner | 先校验原 URL；cache 不单独授权 | 可读全局 | `data/media_previews` 只是派生缓存 | 3G-4A |
| `/api/image-jpeg?url=...` | JPEG 转换代理 | 任意本地资源 URL | 原 URL 对应 owner | 先校验原 URL | 可读全局 | 只读转换，不作为任务历史 | 3G-4A |
| `/assets/output/*` | 生成 output | 在线生图、Smart Canvas、Comfy、RunningHub | 生成响应、history、canvas task GET 结果补记 | owner 或 canvas/conversation/history scope 可读 | 可读全局 | 历史删除不物理删除 output | 3G-4A 回归补强 |
| `/output/*` | 旧 output 兼容路径 | 旧上游输出 | 归一化到 protected resource | 同 output 策略 | 可读全局 | 兼容保留 | 回归 |
| `/assets/library/*` | 素材库文件 | 素材库、workflow library、shared folder import | 新建 item URL 记录到 `user_resource_map` | 只显示和管理真实 owner 的 item；unowned 隐藏；canvas/conversation 回溯不授予管理权 | 可见全局 | item delete/move/rename/batch/classify/crop/register 等先校验真实 owner；管理员写审计 | 3G-4A 最小兜底 |
| `data/asset_library.json` | 素材库业务索引 | 素材库 UI、画布右侧素材库面板 | item URL 反查 `user_resource_map` | `/api/asset-library` 过滤嵌套 `libraries[].categories[].items[]` 和顶层 `categories[].items[]` | 可管理 | library/category 完整 owner、分组权限和批量业务治理仍归 3G-4B | 3G-4A 最小兜底 + 3G-4B 完整治理 |
| `history.json` | 生成历史 | 在线/本地功能历史 | `user_history_map` | 只看自己的历史 | 可见全局 | 只删历史记录，不删 output 文件 | PR #28 |
| `data/canvases/*.json` | 画布节点和日志 | 画布保存 | `user_canvas_map` | 只访问自己的画布；资源可从画布引用派生读取 | 可代管 | owner 迁移不改 resource owner | PR #24 + 3G-4A |
| `data/conversations/*/*.json` | 对话和附件引用 | GPT 对话 | `user_conversation_map` | 只访问自己的对话；资源可从对话引用派生读取 | 可代管 | 对话迁移后资源真实 owner 不自动转移 | 既有 + 3G-4A |

## 输入复用校验

以下运行接口不能粗暴 403。企业层策略是允许当前用户有权访问的资源，拒绝他人、unknown、unowned 资源：

- `/api/online-image`
- `/api/chat`
- `/api/chat/stream`
- `/api/generate`
- `/api/canvas-comfy-tasks`
- `/api/canvas-image-tasks`
- `/api/runninghub/upload-asset`
- `/api/runninghub/submit`
- `/api/runninghub/workflow-submit`
- `/api/image-jpeg`
- `/api/media-preview`

运行接口请求体中的 `/assets/*`、`/output/*`、`/api/view`、`/api/download-output` URL 由统一资源归一化处理。ComfyUI input 文件名按 `/assets/input/<name>` 校验。

ComfyUI output payload 中如果只有 `filename/subfolder/type=output`，企业层按 `/assets/output/<subfolder>/<filename>` 记录和鉴权，不会误归一化为 `/assets/input/<filename>`。

## 上游同步检查

每次同步上游后必须搜索：

- `UploadFile`
- `FormData`
- `multipart`
- `/api/*upload*`
- `/api/*assets*`
- `/api/*files*`
- `/api/*attachments*`
- `/api/view`
- `/api/*download*`
- `/api/*import*`

新增路径必须加入本矩阵、`enterprise/interceptors.py` 归一化逻辑、自动化测试和 A/B/admin 浏览器验收。

## 3G-4A asset-library 兜底说明

素材库完整治理仍属于 3G-4B，但 3G-4A 已增加最小安全兜底：

- 新保存到素材库的 `/assets/library/*` item 记录当前用户 owner。
- 素材库列表和画布右侧素材库面板共用 `/api/asset-library`，因此同一后端过滤同时覆盖两处入口。
- 普通用户不能看到或管理 owner 不是自己的 `/assets/library/*` item。
- 管理员可以查看和管理 A/B/unowned item，关键操作写 `usage_logs`。
- asset-library 写接口返回整份 `library` 快照时，企业层只记录新建 `item/items` 的 owner，不再扫描整份快照，避免把其他用户素材误补记给当前用户。
