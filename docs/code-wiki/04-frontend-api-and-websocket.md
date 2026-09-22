# 前端、API 与 WebSocket

[返回索引](./README.md)

## 1. 前端技术形态

前端是原生 HTML/CSS/JavaScript，不存在 `package.json`、React 构建或 npm 启动步骤。Tailwind 与 Lucide 以仓库内静态脚本形式加载；主题、国际化、触摸/鼠标适配为共享脚本。

这意味着：

- 修改后由 FastAPI 直接提供文件，无 bundler 编译阶段。
- 缓存版本通过 HTML 中资源 URL 的查询串维护。
- 大页面脚本持有大量可变全局状态，回归必须覆盖真实浏览器交互。
- 企业 Gateway 会对旧页面注入用户导航与权限守卫。

## 2. 工作台与普通画布

### `static/js/canvas-list.js`

负责项目/画布列表、创建、重命名、移动、排序、置顶、回收站和页面跳转。所有列表必须接受 Gateway 返回的当前用户可见集合，不能假设 Upstream 文件目录天然隔离。

### `static/js/canvas.js`

关键函数：

| 函数 | 职责 |
| --- | --- |
| `screenToWorld()`、`applyViewport()` | 屏幕坐标与世界坐标换算、平移缩放 |
| `fitAllNodesViewport()`、`toggleZoomPreview()` | 视图适配与缩放预览 |
| `scheduleSave()`、`saveCanvas()` | 防抖保存画布 |
| `serializableCanvasNode()` | 去除临时运行态，生成可持久化节点 |
| `loadCanvasList()`、`openCanvas()` | 加载并进入画布 |
| `syncRemoteCanvasNow()`、`checkRemoteCanvasVersion()` | 保存/远端版本同步与冲突感知 |
| `refreshMissingCanvasAssets()` | 修复或刷新缺失素材引用 |
| `createCanvas()`、`createSmartCanvas()` | 创建普通/智能画布 |
| `returnToCanvasManager()` | 返回工作台 |

文件还包含图片/视频节点、选择与拖动、连线、最小地图、Provider 参数、生成轮询、历史和编辑器逻辑。

## 3. 智能画布

### `static/js/smart-canvas.js`

智能画布维护节点、连线、分组、循环执行、撤销、任务状态、生成日志和工作流导入导出。

关键函数族：

- `snapshotForUndo()`、`pushUndo()`、`performUndo()`：撤销快照。
- `canvasForStorage()`、`serializableSmartNode()`：持久化模型。
- `exportSelectedSmartWorkflow()`、`importSmartWorkflowFile()`：工作流交换。
- `createImageNodeAt()`、`arrangeSmartGroupMembers()`：节点与分组布局。
- `normalizeSmartGenerationLogs()`、`mergeSmartGenerationLogs()`：生成日志兼容与合并。
- `smartLoop*`、`smartCascade*`：循环/级联执行状态。

智能画布与普通画布是不同的大脚本实现，修复一个页面的保存/资源行为时不能假定另一个页面自动获得同样修复。

## 4. 素材与设置

| 文件 | 主要职责 |
| --- | --- |
| `asset-manager.js` | 本地素材树、上传、批量选择、移动删除、标签/描述、预览 |
| `api-settings.js` | Provider CRUD、协议识别、密钥输入、模型获取、连接测试、CLI 状态 |
| `comfyui-settings.js` | ComfyUI 实例与工作流配置 |
| `image-preview.js` | 图片预览通用逻辑 |
| `history-bulk-manager.js` | 历史记录批量操作 |
| `theme.js`、`i18n.js` | 主题和文本本地化 |
| `touch-mouse.js` | 触摸与鼠标交互归一化 |

设置响应经 Gateway 脱敏，页面中显示“已有密钥”或预览值不等于前端持有明文密钥。

## 5. 企业页面

| 页面 | 访问范围 | 功能 |
| --- | --- | --- |
| `/enterprise/login` | 未登录 | 用户名/密码登录 |
| `/enterprise/profile` | 已登录 | 当前用户资料与密码 |
| `/enterprise/logs` | 受权限控制 | 操作日志 |
| `/enterprise/admin` | admin/super_admin | 成员、归属、权限开关、更新中心 |

更新中心的“可见”与“可执行”不同：管理员可进入后台，但更新操作要求当前超级管理员、全局 `system_update` 开关有效、紧急更新开关开启，并再次确认当前密码。

## 6. API 领域分组

`main.py` 的路由数量多，建议按领域定位：

| 领域 | 典型前缀/接口 |
| --- | --- |
| 页面与版本 | `/`、`/canvas*`、`/api/app-info` |
| 文件/媒体 | `/api/upload`、`/api/view`、`/api/media-preview`、`/api/download-output` |
| 项目/画布 | `/api/projects*`、`/api/canvases*`、保存/删除/恢复/彻底删除 |
| 对话 | `/api/conversations*`、`/api/chat*`、流式对话 |
| 本地素材 | `/api/local-assets*`、`/api/canvas-assets*` |
| 素材库 | `/api/asset-library*`、共享文件夹 |
| Provider | `/api/config`、`/api/providers*`、`/api/models` |
| 画布任务 | `/api/canvas-image-tasks*`、`/api/canvas-comfy-tasks*` |
| RunningHub | `/api/runninghub*` |
| ComfyUI | `/api/comfyui*` |
| 生成工具 | ModelScope、Angle、Z-Image、视频与图像工具接口 |
| CLI | `/api/codex*`、`/api/gemini-cli*`、`/api/jimeng*` |
| 更新中心 | `/api/update-mvp/*`（定义在企业 Router） |

## 7. 更新中心 API

| 方法与路径 | 行为 |
| --- | --- |
| `GET /api/update-mvp/access` | 返回角色、是否可操作、全局开关和权限来源 |
| `GET /api/update-mvp/check` | 读取 current pointer/当前 Manifest，并查询最新合规 GitHub Release |
| `POST /api/update-mvp/prepare` | 下载三件套、校验并创建 READY 作业 |
| `POST /api/update-mvp/jobs/{id}/execute` | 再验密码与当前状态，创建执行保留并触发 Runtime handoff |
| `GET /api/update-mvp/jobs/{id}` | 查询作业状态 |
| `GET /api/update-mvp/diagnostics` | 返回或导出脱敏诊断 ZIP |

## 8. WebSocket 事件规则

Gateway 不应透明广播所有 Upstream 事件。事件过滤至少考虑：

- `client_id` 是否唯一属于当前用户。
- 任务 ID 是否由当前用户拥有。
- 历史记录和生成资源 URL 是否归当前用户。
- 素材库更新是否在用户可见范围。
- 管理员是否具有该事件的扩展可见性。

SEC-P0 额外固定传输边界：只接受同源 `/ws/stats`，浏览器到 Upstream 只转发精确字符串 `ping`；服务端事件类型必须进入显式已知集合，未知类型、缺失类型和非 JSON 消息对普通用户与管理员都默认拒绝。管理员身份不会把未知协议变成可见协议。

新增异步业务时，应同时实现 HTTP 受理归属、查询权限、结果资源归属和 WebSocket 事件过滤四个环节。
