# 依赖与外部集成

> 源码参考快照（2026-10-13）：main@e89a288（已合并 #154/#155/#156）；产品功能源码基点 #156@4bdd9a1 保留；C5/C6/C7 已合并，构建与验收范围仍引用其准确记录。本文是代码/运行参考，当前 PR/CI、Release 和验收只见 [CURRENT](../CURRENT_PROJECT_STATUS.md)，实施顺序只认路线图。

[返回索引](./README.md)

## 1. Python 依赖

根 `requirements.txt` 是开发/旧运行依赖入口，包含 FastAPI、Uvicorn、Requests、Pydantic、PyJWT、python-multipart、HTTPX 和 Pillow。

正式 Windows Runtime 使用 `runtime/windows/requirements.lock` 的精确版本与 SHA-256。当前锁中的核心版本：

| 依赖 | 版本 | 用途 |
| --- | --- | --- |
| FastAPI | `0.136.1` | HTTP API |
| Starlette | `1.0.0` | ASGI/Middleware/WebSocket 基础 |
| Uvicorn | `0.47.0` | ASGI server |
| Pydantic | `2.13.4` | 数据模型/校验 |
| HTTPX | `0.28.1` | 异步 HTTP 与 Gateway 转发 |
| Requests | `2.34.2` | 同步 Provider/下载兼容调用 |
| PyJWT | `2.13.0` | 企业会话 Token |
| Pillow | `12.2.0` | 图片读取、格式和尺寸处理 |
| python-multipart | `0.0.28` | 上传与表单 |
| websockets | `16.0` | WebSocket 客户端/服务支持 |
| watchfiles | `1.1.1` | Uvicorn 相关运行依赖 |

锁文件还包含完整传递依赖。正式发布不得只执行无哈希的 `pip install -r requirements.txt` 来替代已验证 Runtime。

## 2. Python 版本

- 开发解释器依当前工作区环境；企业 CI 为 Python 3.11，Runtime 专项为 3.14，不假定所有源码树自带同一 Python。
- 正式 Runtime 策略：CPython 3.14.x、Windows x64、固定来源与闭合 wheelhouse。

两者目的不同。测试通过开发 Python 不等于正式固定 Runtime 已验证；反过来，Runtime provenance 测试也不证明业务功能全部通过。

## 3. 前端依赖

前端没有 npm 依赖图。仓库内静态 vendor/共享依赖包括：

- Tailwind CSS 浏览器脚本。
- Lucide 图标脚本。
- 自有主题、国际化、鼠标/触摸、预览和历史批量工具。

安全与性能含义：无需 npm 构建，但大型单文件脚本缺少模块边界；更新 vendor 文件需要同步离线发布 inventory 和浏览器回归。

## 4. 外部 AI/工作流集成

| 系统/协议 | 入口 | 典型用途 |
| --- | --- | --- |
| OpenAI-compatible | Provider 配置 | 对话、图片或兼容 API |
| Gemini API | Provider 配置 | 对话/多模态 |
| ModelScope | 专用 Provider | 图片生成与模型列表 |
| RunningHub | `/api/runninghub*` | 云端工作流、上传、提交、查询 |
| 火山引擎 | Provider 专用字段 | 图像/视频等模型调用 |
| 即梦 CLI | `/api/jimeng*` | 本机 CLI 登录与任务 |
| Codex CLI | `/api/codex*` | 使用本机 CLI 会话 |
| Gemini CLI | `/api/gemini-cli*` | 使用本机 CLI 会话 |
| ComfyUI | `/api/comfyui*` | 本地/内网实例、工作流执行 |

Provider 凭据存于服务端配置，不应通过设置读取接口回传明文。外部请求可能受系统代理、`HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` 或应用专用代理影响；排障时应分别验证直接连接与代理连接。

## 5. GitHub 集成

在线更新固定使用：

- 仓库：`MEIS-DaCaiTou/Infinite-Canvas-Enterprise`
- GitHub Releases API/资产下载
- 可选 `GITHUB_TOKEN` 用于私有仓库访问
- Manifest v2、inventory 与单个 Windows x64 archive 的闭合集合

安全客户端会重新验证重定向目标；跨 Host 不透传 Authorization。GitHub 网页能打开或 API 返回 200 只证明网络链路，仍需验证 Release 资产集合和 Manifest。

## 6. 操作系统依赖

正式产品路径依赖 Windows 能力：

- PowerShell 5.1 兼容批处理/诊断。
- Windows Job Object 管理子进程。
- PID 创建时间与可执行路径身份。
- 本地固定磁盘、Known Folder、reparse point 检测。
- Inno Setup 7 x64 安装器构建。
- 文件原子替换和目录同步语义。

代码含部分跨平台测试 seams，正式 portable lifecycle 仍是 Windows 设计。Linux、云部署和容量实施待负责人需求；新的业务规则不新增 Registry、固定盘符或桌面启动前置。

## 7. 配置项

`enterprise.env` 的公开配置契约：

| 键 | 默认/示例 | 说明 |
| --- | --- | --- |
| `GATEWAY_PORT` | `8000` | 企业入口 |
| `UPSTREAM_PORT` | `3001` | loopback 旧内核 |
| `JWT_SECRET` | 必须替换 | JWT 签名秘密，生产至少 32 字符 |
| `JWT_EXPIRE_HOURS` | `168` | 会话有效期 |
| `ADMIN_USERNAME` | `admin` | 旧兼容初始管理员配置 |
| `ADMIN_PASSWORD` | 必须替换 | 旧兼容初始密码 |
| `DB_PATH` | `data/enterprise.db` | 相对 DATA_ROOT 解析 |
| `ENTERPRISE_REPO_URL` | 本项目 GitHub URL | 更新仓库绑定 |
| `ENTERPRISE_UPDATE_ENABLED` | `true` | 更新紧急总开关 |
| `ENTERPRISE_HIDE_UPSTREAM_AUTHOR` | `true` | 页面品牌覆盖 |
| `ENTERPRISE_ENV` | 可选 `production` | 启用生产严格校验 |
| `ENTERPRISE_STRICT_SECURITY` | 可选 `1` | 显式严格安全模式 |

真实 `enterprise.env`、Provider Key 和 GitHub Token 不得提交 Git。

## 8. 依赖变更规则

1. 先更新源码使用与开发 requirements。
2. 对正式 Runtime 更新哈希锁、wheelhouse 闭包、SBOM 与来源证据。
3. 运行离线安装、`pip check`、双构建一致性和 Runtime 生命周期验证。
4. 将新文件纳入 Manifest/inventory；禁止隐式下载未声明依赖。
5. Provider SDK/协议升级还要回归超时、代理、重试、未知结果和凭据脱敏。

## 9. 候选供应商及本地工具

Zhenzhen 图像能力/请求构造位于 #156 的 enterprise/providers/zhenzhen.py，使用现有 HTTPX client，不新增 SDK、数据库或 Windows 依赖。12 个已确认 JSON 图像模型/别名的契约及未覆盖协议见[实现记录](../ops/PRODUCT-INTEGRATION-FIXES-2026-10-13.md)。Chat 继续复用既有 OpenAI-compatible 路径；不据此宣称全部视频/原生接口可用。

Photoshop UXP 源码 manifest 0.3.0，最低 PS 24，具备浏览/置入/PNG 导出/生成查询等接线，但企业认证与真实宿主未验收。素材 Chrome 扩展源码 1.0.1 包含网页/媒体采集、截图、下载/ZIP 与平台导入；#156 修复同源平台连接，真实扩展宿主矩阵未验收，不推断已安装状态。两者是项目能力，与开发用 Codex Browser 不混同。


2026-10-19 独立视频候选（Base main e0dfa84）：`enterprise/providers/zhenzhen_video.py` 承接精确型号能力、媒体字段及提交/查询选路，`model_catalog.py` 仅修正已知分类。main 保留媒体转换、现有鉴权、回执和归档接线；CanvasModelPicker 向两类画布提供同一视频能力。实际调用、旧回执兼容与未覆盖边界见 [产品记录](../ops/PRODUCT-INTEGRATION-FIXES-2026-10-13.md#2026-10-19-贞贞视频协议路由候选)，不是全部上游模型或正式发行能力声明。


同日图片候选（Base #179@bd341fb）：zhenzhen.py补精确JSON编辑/单图拆层；`image_outputs.py`保留有界图层元数据，generation_tasks沿用资源校验后投影，经典画布优先既有image_items。图层仍是普通透明图片及元数据，没有新编辑器；上游500和未验收范围见[图片候选](../ops/PRODUCT-INTEGRATION-FIXES-2026-10-13.md#2026-10-19-图片编辑与图层输出候选)。
