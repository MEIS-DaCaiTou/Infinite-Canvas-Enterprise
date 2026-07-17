# 无限画布企业版 · Codex 项目交接文档

> **已被替代的历史交接。** 本文中的 launcher、启动命令和运行状态仅反映早期实现。当前入口是 [`docs/README.md`](docs/README.md)，运行事实见 [`ARCHITECTURE.md`](ARCHITECTURE.md) 和 [`docs/CURRENT_PROJECT_STATUS.md`](docs/CURRENT_PROJECT_STATUS.md)。

> **写给接手的 AI Agent（Codex）**
> 阅读顺序：先读本文档，再读 `ENTERPRISE_DOCS.md`。本文档是**现状速览**，`ENTERPRISE_DOCS.md` 是**完整开发规范**。

---

## 一、项目是什么

这是一个在开源项目 [Infinite-Canvas](https://github.com/hero8152/Infinite-Canvas)（无限画布 AI 创作工具）之上构建的**企业多用户层**。

原项目是单用户工具，企业层为其加上了：

- 多账号登录（JWT Cookie 认证）
- 数据隔离（每个用户只看到自己的画布/对话）
- 管理后台（成员管理 + 画布归属分配）
- 审计日志、个人中心、健康检查接口

**架构本质**：企业层是上游的**反向代理**，监听 `:8000`，转发到上游 `:3001`，在转发过程中注入认证和数据过滤。企业层二开应保持在代理层实现，**不应修改上游文件**。

---

## 二、目录结构速览

```
项目根/
├── enterprise/               ← 企业层后端（可修改）
│   ├── gateway.py            ← FastAPI 主入口，路由注册，代理核心
│   ├── interceptors.py       ← 请求前置检查 + 响应后置过滤（数据隔离核心）
│   ├── admin_api.py          ← 所有管理员 REST API（/enterprise/api/...）
│   ├── db.py                 ← SQLite 数据库访问层
│   ├── auth.py               ← JWT 生成/验证，用户登录认证
│   ├── config.py             ← 从 enterprise.env 读取所有配置
│   ├── launcher.py           ← Windows 企业版受控启动器
│   ├── pick_lan_ip.ps1       ← 动态选择当前主机局域网访问地址
│   └── tests/                ← 诊断、冒烟、启动停止闭环测试脚本（统一存放）
│
├── enterprise-static/        ← 企业层前端（可修改）
│   ├── login.html            ← 登录页（纯 CSS，无 Tailwind 依赖）
│   ├── admin.html            ← 管理后台（Tailwind 本地版本）
│   ├── profile.html          ← 个人中心（修改密码）
│   └── logs.html             ← 操作审计日志（管理员专用）
│
├── enterprise.env            ← 配置文件（不在 git 中，.gitignore 已屏蔽）
├── ENTERPRISE_DOCS.md        ← 完整开发规范文档（必读）
├── 启动企业版.bat            ← Windows 一键启动入口（调用 enterprise/launcher.py）
├── 停止企业版.bat            ← Windows 停止 8000/3001 服务
│
├── [以下是上游文件，绝对不能修改]
│   ├── main.py               ← 上游主程序
│   ├── static/               ← 上游前端资源
│   ├── workflows/            ← 工作流配置
│   ├── python/               ← 内置 Python 3.10 运行时
│   └── VERSION               ← 当前版本（2026.06.01）
│
└── data/
    ├── enterprise.db         ← 企业层 SQLite 数据库（用户账号、画布归属）
    ├── canvases/             ← 上游画布数据（.json 文件）
    └── conversations/        ← 上游对话数据
```

---

## 三、启动服务

### 正常启动（推荐）

双击 `启动企业版.bat`，入口会调用 `enterprise/launcher.py`，自动：
1. 启动上游（`127.0.0.1:3001`）
2. 轮询等待上游端口就绪（最多 60 秒）
3. 启动企业网关（`0.0.0.0:8000`）
4. 在同一个受控启动器里管理两个子进程

在 Windows 上，启动器会尽量使用 Job Object 管理子进程；按 `Ctrl+C` 或关闭启动窗口时，会清理本次启动器拉起的 `3001/8000` 服务。若历史旧脚本留下孤儿进程，可先运行 `停止企业版.bat` 清掉，再重新双击 `启动企业版.bat`。

> 局域网地址选择原则：按当前主机网络路由动态选择，不强行纠正为某个固定网段。若本机浏览器开启代理，访问 `11.*` 等地址可能被代理拦截；局域网其他用户关闭代理或正确配置代理绕过后仍可正常访问。

### 手动启动（调试时）

```powershell
# 先启动上游（内部端口，仅本机）
cd "d:\CodeProject\26-5-27-无限画布"
Start-Process -FilePath "python\python.exe" -ArgumentList "-m","uvicorn","main:app","--host","127.0.0.1","--port","3001","--log-level","warning" -WindowStyle Minimized

# 等待上游就绪
$i=0; do { Start-Sleep 1; $i++ } while(!(Test-NetConnection 127.0.0.1 -Port 3001 -InformationLevel Quiet -WarningAction SilentlyContinue) -and $i -lt 30)

# 再启动企业网关（前台，Ctrl+C 退出）
.\python\python.exe -m uvicorn enterprise.gateway:app --host 0.0.0.0 --port 8000 --log-level info
```

### 检查服务状态

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8000/enterprise/health" -UseBasicParsing | Select-Object StatusCode, Content
# 期望：StatusCode=200, Content={"status":"ok","upstream":"ok",...}
```

> **当前实现说明**：`/enterprise/health` 在 `enterprise/gateway.py` 中请求上游 `/api/app-info`，用于确认企业网关能访问内部上游服务。它仍然是“上游服务可达性探测”，不是严格的版本差异检查。

### 重启网关（代码变更后必须执行）

```powershell
.\停止企业版.bat
.\启动企业版.bat
```

> **注意**：`enterprise-static/*.html` 是每次请求从磁盘读取的，前端改动**无需重启**。只有修改 `enterprise/` 下的 Python 文件才需要重启网关。

### 诊断与冒烟测试

所有测试脚本统一放在 `enterprise/tests/`，严禁散落到项目根目录或上游目录。常用命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\diagnose.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\smoke.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\test_start_stop.ps1 -StopExisting
```

`test_start_stop.ps1 -StopExisting` 会停止当前 `8000/3001` 监听并验证新启动器闭环，执行期间当前网页会暂时不可用。

---

## 四、关键约束（必须遵守）

### ① 绝对禁止修改上游文件

下列文件/目录**一行都不能动**：

| 禁止修改 | 原因 |
|----------|------|
| `main.py` | 上游随时会发布新版本覆盖它 |
| `static/` | 同上 |
| `workflows/`, `API/`, `python/` | 同上 |
| `启动服务.bat`, `VERSION` | 同上 |

**违反此约束的后果**：上游更新时产生 merge 冲突，手动修改的内容丢失，企业层功能损坏。

### ② 上游更新方法

更新按钮调用的是上游接口 `/api/update-from-github`。企业网关会限制更新/回滚相关接口只有管理员可访问；普通用户页面会隐藏“一键更新”按钮，即使直接请求接口也会返回 403。管理员触发更新时，企业网关会把请求里的 `auto_restart` 强制改为 `false`，避免上游更新后启动普通版 `:3000` 服务、破坏企业版 `:3001 + :8000` 的双服务结构。点击更新成功后，应手动重启 `启动企业版.bat`。

如果当前机器的打包 Python 与 GitHub TLS 握手不兼容，更新按钮可能仍会失败。此时用 PowerShell 手动下载上游更新：

```powershell
# 下载上游最新代码（绕过 Python SSL 问题）
$base = "https://raw.githubusercontent.com/hero8152/Infinite-Canvas/main"
$files = (Invoke-WebRequest "$base/VERSION" -UseBasicParsing).Content.Trim()
# 或直接拉取 GitHub API 获取文件列表，再逐个下载
# 企业层文件（enterprise/, enterprise-static/, enterprise.env, data/）不会被覆盖
```

详细脚本参见本次会话历史（用 PowerShell 从 GitHub 下载 63 个文件的完整流程）。

### ③ 数据隔离逻辑不能破坏

`interceptors.py` 中的 `pre_process()` 和 `post_process()` 是数据安全的核心。修改时必须确保：
- 普通用户仍然只能看到 `user_canvas_map` 中属于自己的画布
- `POST /api/canvases` 的响应依然会触发归属记录
- 管理员依然可以看到全量数据

---

## 五、数据库结构

文件位置：`data/enterprise.db`（SQLite）

| 表 | 用途 |
|----|------|
| `users` | 账号：id/username/password_hash/display_name/is_admin/is_active |
| `user_canvas_map` | 画布归属：canvas_id → user_id（PK 是 canvas_id） |
| `user_conversation_map` | 对话归属：conversation_id → user_id |
| `usage_logs` | 操作审计：user_id/action/detail/ts（毫秒时间戳） |

密码格式：`{16字节hex盐}:{pbkdf2_hmac_sha256_迭代20万次_hex}`

---

## 六、现有 API 总览

### 公开接口（无需登录）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/enterprise/login` | 登录页 / 登录验证 |
| GET | `/enterprise/logout` | 注销 |
| GET | `/enterprise/health` | 健康检查（返回 gateway + upstream 状态） |

### 普通用户接口（需登录）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/enterprise/profile` | 个人中心页面 |
| GET | `/enterprise/api/me` | 当前用户信息 JSON |
| PUT | `/enterprise/api/me/password` | 修改自己的密码（需验旧密码） |

### 管理员接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/enterprise/admin` | 管理后台页面 |
| GET | `/enterprise/logs` | 审计日志页面 |
| GET | `/enterprise/api/users` | 用户列表 |
| POST | `/enterprise/api/users` | 创建用户 |
| PUT | `/enterprise/api/users/{id}/password` | 强制重置用户密码 |
| PUT | `/enterprise/api/users/{id}/role` | 设置/撤销管理员权限 |
| DELETE | `/enterprise/api/users/{id}` | 软删除用户（is_active=0） |
| GET | `/enterprise/api/canvas-owners` | 所有画布归属信息 |
| PUT | `/enterprise/api/canvases/{id}/owner` | 手动分配画布归属 |
| GET | `/enterprise/api/logs` | 审计日志（分页+过滤） |

---

## 七、配置项（enterprise.env）

```ini
GATEWAY_PORT=8000         # 企业网关对外端口
UPSTREAM_PORT=3001        # 上游内部端口
JWT_SECRET=<改为随机字符串>   # ← 生产环境必须修改！
JWT_EXPIRE_HOURS=168      # Token 有效期（小时）
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin123   # ← 生产环境必须修改！
DB_PATH=./data/enterprise.db
```

---

## 八、已知问题与注意事项

### 1. Python 内置运行时的 SSL 限制

`python/` 目录内的 Python 3.10 是打包版本，其 OpenSSL 与 `raw.githubusercontent.com` 的 TLS 握手失败。上游的"检查更新"功能因此无法使用（会报 `SSLEOFError`）。解决方法：用系统 PowerShell `Invoke-WebRequest` 手动下载更新文件。

### 2. 前端 Tailwind 控制台警告

`admin.html` 引用 `/static/vendor/js/tailwindcss-cdn.js`（本地文件），但该 JS 内部有硬编码警告 `"cdn.tailwindcss.com should not be used in production"`，这是 Tailwind 脚本自身的行为，不是真实的 CDN 加载，可忽略。

### 3. 旧画布的归属问题

企业版部署之前已存在的画布（`data/canvases/` 中的文件）在 `user_canvas_map` 表中没有归属记录，所有普通用户都看不到它们。管理员可在管理后台 → "画布归属" Tab 手动分配。

### 4. WebSocket 在网关重启期间断开

重启企业网关时，浏览器中正在进行的 WebSocket 连接（在线人数统计）会断开，刷新页面后自动重连。画布编辑数据不会丢失（通过 REST API 保存）。

### 5. 软删除不是真删除

`DELETE /enterprise/api/users/{id}` 只将 `is_active` 设为 0，用户数据和归属记录仍然保留。目前没有硬删除接口，如需彻底删除需要直接操作 SQLite。

---

## 九、开发新功能的快速路径

| 需求类型 | 修改文件 |
|----------|----------|
| 拦截/过滤新 API 路径 | `enterprise/interceptors.py` |
| 新的管理员功能接口 | `enterprise/admin_api.py` 新增 `@router` 路由 |
| 新的前端页面 | `enterprise-static/` 新增 HTML + `gateway.py` 新增 `@app.get` |
| 新的数据库表 | `enterprise/db.py` 的 `init_db()` 的 `executescript` |
| 修改配置项 | `enterprise/config.py` + `enterprise.env` |

---

## 十、当前用户数据（接手时的状态）

| 账号 | 角色 | 备注 |
|------|------|------|
| admin | 管理员 | 默认账号，密码见 enterprise.env |
| 测试 | 普通用户 | 测试账号 |
| Aidan02 | 管理员 | 测试账号 |
| 测试用户2 | 普通用户 | 测试账号 |

现有画布（7 个）均已分配归属，无未归属画布。

上游版本：`2026.06.01`

---

## 十一、完整开发规范

本文档只覆盖接手所需的关键信息。完整的开发规范、CSS 变量体系、UI 规范、Git 工作流、安全检查清单、Agent 防偏移规则等，详见：

**→ `ENTERPRISE_DOCS.md`**（尤其是第 12 节"Agent 接手开发规范"）
