# 依赖与外部集成

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

- 工作区当前 `python/python.exe`：Python 3.10.11，用于本地开发与测试。
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

代码含部分跨平台测试 seams，但正式 portable lifecycle 是 Windows 设计。

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
