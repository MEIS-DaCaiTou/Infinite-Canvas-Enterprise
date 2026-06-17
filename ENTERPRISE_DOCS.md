# 无限画布企业版 · 开发规范文档

> **面向 Agent / 开发者**：接手此项目二次开发前，必须完整阅读本文档。  
> 本文档是企业化改造的长期规范；当前真实状态和路线以 `AGENT_CONTEXT.md`、`DEVELOPMENT_PLAN.md` 为第一入口。

**推荐阅读顺序**：

1. `AGENT_CONTEXT.md`：当前真实状态、风险和维护边界。
2. `ENTERPRISE_DOCS.md`：企业层完整开发规范。
3. `enterprise/tests/SMOKE_CHECKLIST.md`：上游更新后的验证清单。
4. `DEVELOPMENT_PLAN.md`：后续开发规划。

---

## 一、项目架构概述

### 1.1 双层结构

```
上游层（Upstream）                    企业层（Enterprise）
─────────────────────────────         ─────────────────────────────
main.py + static/ + workflows/   ←→   enterprise/ + enterprise-static/
由 https://github.com/hero8152/       由本团队维护，不受上游更新影响
Infinite-Canvas 持续维护
```

**核心原则：企业功能不应修改上游文件。** 企业能力优先通过"代理拦截层"实现。

如果确认是上游项目自身 bug，可以做最小本地热修用于验证，但必须同步提交上游 issue/PR，并在 `AGENT_CONTEXT.md` 中记录。上游合并后，应移除本地热修偏差，恢复跟随上游。

### 1.2 运行架构

```
局域网用户浏览器（访问 :8000）
        ↓ HTTP / Cookie 鉴权
Enterprise Gateway（enterprise/gateway.py :8000，对外）
        ↓ 内网透明代理
上游 Infinite-Canvas（main.py :3001，仅本机可访问）
        ↓
data/canvases/*.json  data/conversations/  (上游数据)
data/enterprise.db                         (企业层数据)
```

### 1.3 端口规划

| 端口 | 服务 | 可访问范围 |
|------|------|-----------|
| 3001 | 上游主程序（内部） | 仅 127.0.0.1 |
| 8000 | 企业网关（对外） | 局域网所有机器 |

---

## 二、目录结构与职责

```
项目根/
├── enterprise/                  ← 企业层后端（你的代码）
│   ├── __init__.py
│   ├── config.py                ← 配置读取（从 enterprise.env）
│   ├── db.py                    ← SQLite 数据库（用户、归属映射）
│   ├── auth.py                  ← JWT 认证
│   ├── interceptors.py          ← 请求前置拦截 & 响应后置过滤
│   ├── admin_api.py             ← 管理员 REST API
│   ├── gateway.py               ← FastAPI 主网关（核心入口）
│   ├── launcher.py              ← Windows 企业版受控启动器
│   ├── pick_lan_ip.ps1          ← 动态选择当前主机局域网访问地址
│   ├── tests/                   ← 诊断、冒烟、启动停止闭环测试脚本
│   └── requirements.txt         ← 企业层额外依赖
│
├── enterprise-static/           ← 企业层前端（你的代码）
│   ├── login.html               ← 登录页
│   ├── admin.html               ← 管理后台（成员管理 + 画布归属 + 对话归属）
│   ├── profile.html             ← 用户个人中心（修改自己的密码）
│   └── logs.html                ← 操作审计日志查看页（管理员专用）
│
├── enterprise.env               ← 企业配置（不上传 git）
├── 启动企业版.bat               ← Windows 一键启动入口（调用 enterprise/launcher.py）
├── 停止企业版.bat               ← Windows 停止 8000/3001 服务
├── .gitignore                   ← 已屏蔽 enterprise.env 和数据库
│
├── [上游文件，严禁修改]
│   ├── main.py
│   ├── static/
│   ├── workflows/
│   ├── API/
│   └── python/
```

---

## 三、数据库结构（enterprise.db）

企业层使用独立的 SQLite 数据库，与上游数据完全分离。

### 3.1 users 表（用户账号）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT PK | UUID hex |
| username | TEXT UNIQUE | 登录用户名 |
| password_hash | TEXT | `{salt}:{pbkdf2_sha256_hex}` |
| display_name | TEXT | 界面展示名 |
| is_admin | INTEGER | 1=管理员 0=普通用户 |
| is_active | INTEGER | 1=正常 0=已禁用（软删除） |
| created_at | INTEGER | 毫秒时间戳 |
| last_login | INTEGER | 毫秒时间戳 |

### 3.2 user_canvas_map 表（画布归属）

| 字段 | 类型 | 说明 |
|------|------|------|
| canvas_id | TEXT PK | 上游生成的画布 UUID |
| user_id | TEXT | 画布创建者的用户 ID |
| created_at | INTEGER | 毫秒时间戳 |

**工作原理**：上游创建画布时生成 UUID，企业层拦截 `POST /api/canvases` 的响应，将 `canvas_id → user_id` 记录到此表。查询列表时过滤只返回本用户的画布。

### 3.3 user_conversation_map 表（对话归属）

同上，对 `POST /api/conversations` 做同样处理。

### 3.4 user_resource_map 表（本地资源归属）

| 字段 | 类型 | 说明 |
|------|------|------|
| user_id | TEXT | 资源归属用户 ID |
| resource_url | TEXT PK | 标准化后的本地资源 URL，如 `/assets/output/xxx.png` |
| source | TEXT | 记录来源，如上游接口路径或派生来源 |
| created_at | INTEGER | 毫秒时间戳 |

**工作原理**：企业层对上传、生成、保存、SSE 响应以及画布/对话引用中的本地资源做最小归属记录。普通用户访问受保护资源时，优先检查此表；如没有记录，再尝试从自己拥有的画布或对话中派生归属。

### 3.5 usage_logs 表（操作日志）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| user_id | TEXT | 操作用户 |
| action | TEXT | 操作类型（如 "login", "create_canvas"） |
| detail | TEXT | 附加信息 |
| ts | INTEGER | 毫秒时间戳 |

---

## 四、数据隔离机制

### 4.1 原理

上游所有画布存在 `data/canvases/*.json`，文件名就是画布 ID。企业层**不移动、不重命名**这些文件，而是通过 `user_canvas_map` 表记录"哪个画布属于哪个用户"。

当前隔离规则：

- 管理员可以查看和访问全部画布、对话和受保护资源。
- 普通用户只能查看和访问 `user_canvas_map` / `user_conversation_map` 中归属自己的画布和对话。
- 未映射归属的历史画布、历史对话默认仅管理员可见；普通用户列表不可见，直接请求也会返回 404 风格的无权限响应，避免泄露资源是否存在。
- 新建画布会在 `POST /api/canvases` 成功后自动记录 `canvas_id → 当前用户`；记录失败会在后端输出可诊断日志。
- 新建对话会在 `POST /api/conversations`、`POST /api/chat`、`POST /api/chat/agent` 或流式响应中自动记录 `conversation_id → 当前用户`；记录失败会在后端输出可诊断日志。
- 访问单个画布、回收站画布、恢复、删除、彻底删除等通过 `canvas_id` 操作的请求，都会先经过 `interceptors.pre_process()` 权限判断。
- 访问单个对话、删除对话、对话消息读取以及带 `conversation_id` 的聊天请求，都会先经过 `interceptors.pre_process()` 权限判断。

### 4.2 请求拦截流程

```
gateway.py 验证 Cookie → 获取 user_id
    ↓
interceptors.pre_process()  （访问控制）
    ↓
转发给上游（同时注入 x-user-id 头，实现上游原生会话隔离）
    ↓
上游返回全部画布列表（响应体格式：`{"canvases": [...] }`）
    ↓
interceptors.post_process() （过滤：只保留 user_canvas_map 中属于此用户的画布）
    ↓
返回过滤后的列表给用户
```

### 4.3 上游原生 x-user-id 支持（企业层复用机制）

上游 `main.py` 所有会话相关端点原生支持 `x-user-id` HTTP 头，无需任何修改：

```python
# 上游原生代码（main.py 约 5281 行起，勿修改）
async def conversations(request: Request, x_user_id: str = Header(default="")):
    user_id = safe_user_id(x_user_id, request)
```

企业层通过在 `gateway.py` 中注入此头来实现会话隔离：

```python
# enterprise/gateway.py（我们的代码）
headers["x-user-id"] = user["user_id"]   # 注入企业用户 ID
```

**这是"使用上游现有功能"，不是修改上游代码。** 上游对 `x-user-id` 为空时回退到请求的客户端 IP，为非空时以此作为用户标识隔离会话数据。

### 4.4 管理员特权

`is_admin=True` 的用户在 `post_process` 中跳过过滤，可看到所有用户的数据。

### 4.5 本地资源访问隔离

企业网关会对以下本地资源路径进行登录和归属判断：

- `/assets/input/`
- `/assets/output/`
- `/assets/uploads/`
- `/assets/library/`
- `/output/`
- `/api/view`
- `/api/download-output`
- `/api/media-preview`

判断顺序：

1. 管理员直接允许。
2. 公共前端资源（如 `/assets/images/`）直接允许。
3. 已记录到 `user_resource_map` 的资源，只允许对应用户访问。
4. 没有直接资源归属时，尝试扫描用户可访问的画布和对话引用；能从自有画布或自有对话派生出的资源允许访问，并补写资源归属。
5. 无法可靠判断归属的受保护资源，普通用户默认拒绝。

当前限制与后续加固点：

- 通用素材库和本地资源集合接口的过滤以顶层 `items/assets/files/results/data` 列表为主，嵌套树形结构和复杂统计仍需后续浏览器级回归继续覆盖。
- 对无法从 URL、请求参数、响应数据或画布/对话引用中可靠关联归属的历史资源，本轮选择不扩大访问面，由管理员统一访问和后续分配/清理。

---

## 五、认证机制

- **方式**：HTTP-only Cookie（名称：`enterprise_token`）
- **算法**：JWT HS256
- **有效期**：默认 168 小时（7 天），见 `enterprise.env`
- **密钥**：`JWT_SECRET`（必须在 `enterprise.env` 中修改为随机字符串）
- **密码存储**：`{16字节hex盐}:{pbkdf2_hmac_sha256，迭代20万次}` 

登录流程：
1. 用户访问任意页面 → Gateway 检查 `enterprise_token` Cookie
2. 无效 → 302 跳转到 `/enterprise/login`
3. 登录成功 → 设置 Cookie → 跳转原目标页

---

## 六、企业层 API 接口

所有企业专用接口挂载在 `/enterprise/` 路径下，与上游接口路径不冲突。

### 6.1 公开接口（无需登录）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/enterprise/login` | 登录页面 |
| POST | `/enterprise/login` | 登录验证，成功设置 Cookie |
| GET | `/enterprise/logout` | 清除 Cookie，跳转登录页 |
| GET | `/enterprise/health` | 服务健康检查（返回 gateway/upstream 状态） |

`/enterprise/health` 探测企业网关到内部上游 `/api/app-info` 的可达性，用于确认 `:3001` 上游服务在线；它不是版本差异检查。

**健康检查响应示例：**

```json
// 正常：HTTP 200
{ "status": "ok", "gateway": "ok", "upstream": "ok", "upstream_latency_ms": 12 }

// 上游不可达：HTTP 503
{ "status": "degraded", "gateway": "ok", "upstream": "unreachable", "upstream_latency_ms": null }
```

### 6.2 普通用户接口（需登录，不限管理员）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/enterprise/profile` | 个人中心页面（展示用户名 + 修改密码表单） |
| GET | `/enterprise/api/me` | 获取当前登录用户信息（JSON） |
| PUT | `/enterprise/api/me/password` | 修改自己的密码（需验证旧密码，新密码 ≥6 位） |

### 6.3 管理员专用接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/enterprise/admin` | 管理后台页面（成员管理 + 画布归属 + 对话归属 Tab） |
| GET | `/enterprise/logs` | 操作审计日志查看页面 |
| GET | `/enterprise/api/users` | 获取所有用户列表 |
| POST | `/enterprise/api/users` | 创建用户 |
| PUT | `/enterprise/api/users/{id}/password` | 重置用户密码（管理员强制重置） |
| PUT | `/enterprise/api/users/{id}/role` | 设置/撤销管理员权限 |
| PUT | `/enterprise/api/users/{id}/active` | 启用/禁用用户（管理员不能禁用自己） |
| PUT | `/enterprise/api/users/{id}/profile` | 更新用户展示名；展示名为空时回退为用户名 |
| DELETE | `/enterprise/api/users/{id}` | 删除用户（兼容软删除，内部禁用 `is_active=0`） |
| GET | `/enterprise/api/canvas-owners` | 获取所有画布的归属信息 |
| PUT | `/enterprise/api/canvases/{id}/owner` | 手动分配/变更画布归属用户 |
| GET | `/enterprise/api/conversation-owners` | 获取所有对话文件的归属信息，包含未归属历史对话 |
| PUT | `/enterprise/api/conversations/{id}/owner` | 手动分配/变更对话归属用户 |
| GET | `/enterprise/api/logs` | 查询操作审计日志（支持分页、用户/操作类型过滤） |

用户管理 API 行为约束：

- 目标用户不存在时返回 HTTP 404。
- 管理员不能禁用或删除自己。
- `PUT /enterprise/api/users/{id}/active` 成功返回 `success`、`user_id`、`is_active`、`status`。
- `PUT /enterprise/api/users/{id}/profile` 成功返回 `success`、`user_id`、`display_name`。

已进入审计日志的用户管理操作：

- 创建用户：`user_created`
- 重置用户密码：`user_password_reset`
- 修改用户角色：`user_role_updated`
- 禁用用户 / 软删除用户：`user_disabled`
- 启用用户：`user_enabled`
- 修改用户展示名：`user_profile_updated`

### 6.4 企业项目入口与更新治理

企业版首页中的“项目主页”必须指向企业仓库：

- `https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise`

上游项目来源说明保留在 `README.md`、`docs/upstream/README.upstream.md` 和 `docs/upstream/SYNC_POLICY.md` 中，但普通用户前端不应突出展示上游作者社交入口。

更新相关能力属于管理员受控运维能力：

- 普通用户不显示“一键更新”按钮。
- 普通用户不显示“更新到 vX”的上游更新提示。
- 普通用户不显示更新弹窗、连通性测试或回滚入口。
- 普通用户绕过前端请求 `/api/update-*` 或 `/api/check-update` 时，企业网关必须返回 HTTP 403。
- 管理员可看到企业版版本信息和企业版受控更新入口。
- 管理员触发 `/api/update-from-github` 时，企业网关会关闭上游 `auto_restart`，避免破坏企业版 `3001/8000` 双进程模型。

当前实现位于：

- `enterprise/gateway.py`：向上游首页 HTML 注入企业入口和更新 UI 治理脚本。
- `enterprise/interceptors.py`：拦截普通用户更新接口，并对 `/api/app-info` 做企业化响应。
- `enterprise/config.py` / `enterprise.env.example`：提供 `ENTERPRISE_REPO_URL`、`ENTERPRISE_UPDATE_ENABLED`、`ENTERPRISE_HIDE_UPSTREAM_AUTHOR` 配置。

审计日志中 `user_id` 记录执行操作的管理员 ID，`detail` 记录目标用户 ID、目标用户名和动作摘要。画布归属变更写入 `canvas_assigned`，对话归属变更写入 `conversation_assigned`。

管理后台最小适配：

- 成员列表继续展示启用/禁用状态。
- 启用用户显示“禁用”操作，禁用用户显示“启用”操作。
- 新增“编辑名称”操作，可更新展示名；留空时后端回退为用户名。
- 画布归属 Tab 可查看未分配画布并分配给指定用户。
- 对话归属 Tab 可查看未分配历史对话并分配给指定用户。

---

## 七、UI 设计规范（与上游完全一致）

### 7.1 CSS 变量体系

所有企业层页面必须使用与上游相同的 CSS 变量，**不得使用硬编码颜色值**：

```css
/* 亮色主题（默认）*/
:root {
  --bg: #f7f8fa;         /* 页面背景 */
  --panel: #fff;          /* 卡片/面板背景 */
  --soft: #f1f4f8;        /* 次级背景（悬停、输入框） */
  --line: #e8ecf2;        /* 边框（默认） */
  --line-strong: #dbe1ea; /* 边框（强调） */
  --text: #0f172a;        /* 主文字 */
  --muted: #64748b;       /* 次要文字 */
  --faint: #94a3b8;       /* 占位符/辅助文字 */
  --accent: #0f172a;      /* 强调色 */
}

/* 暗色主题 */
html.studio-theme-dark body, body.studio-theme-dark {
  --bg: #0e1014;
  --panel: #1c1e26;
  --soft: #272a33;
  --line: #323540;
  --line-strong: #3f424d;
  --text: #e8e8ea;
  --muted: #a4adbf;
  --faint: #7a8497;
  --accent: #f5f6f8;
}
```

### 7.2 主题检测（每个页面 `<head>` 顶部必须包含）

```html
<script>
  (function(){
    try {
      var t = localStorage.getItem('studio_theme') || localStorage.getItem('canvas_theme') || 'light';
      if (t === 'dark') {
        document.documentElement.classList.add('studio-theme-dark');
        document.documentElement.classList.add('theme-dark');
      }
    } catch(e) {}
  })();
</script>
```

### 7.3 字体

- 主字体：**Inter**（与上游 api-settings 页面一致）
- 声明：`font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;`

### 7.4 输入框规范（field-frame 模式）

```html
<div class="field">
  <span class="label">字段名称</span>
  <div class="field-frame">
    <input type="text" placeholder="提示文字" />
  </div>
</div>
```

对应 CSS（照抄上游规范）：
- `field-frame`：外层容器，`border-radius: 11px`，`padding: 4px`，提供边框
- `field-frame input`：内部透明输入框，高度 34px，无边框
- 获焦时：`border-color: var(--text)`

### 7.5 按钮规范

```css
.action-btn {
  height: 36px; padding: 0 14px; border-radius: 10px;
  font-size: 12.5px; font-weight: 800;
  border: 1px solid var(--line); background: var(--panel); color: var(--text);
}
/* Primary 变体（黑底白字） */
.action-btn.primary { background: var(--text); color: var(--bg); border-color: var(--text); }
/* Danger 变体 */
.action-btn.danger { color: #ef4444; border-color: rgba(239,68,68,.25); }
```

### 7.6 依赖引用（需要时从上游 static 引入，不要重复打包）

```html
<script src="/static/vendor/js/tailwindcss-cdn.js"></script>
<script src="/static/vendor/js/lucide.js"></script>
<link rel="stylesheet" href="/static/css/theme.css">
```

---

## 八、Git 工作流规范

### 8.1 分支结构

```
main（上游同步分支）  ←  git fetch upstream + rebase
enterprise（企业功能分支）  ←  你的所有改动在此
```

### 8.2 同步上游更新（标准流程）

```bash
# 1. 拉取上游最新代码
git fetch upstream

# 2. 在企业分支执行 rebase（而非 merge）
git checkout enterprise
git rebase upstream/main

# 3. 因为 enterprise/ 目录是新增的，上游不会触碰，预期零冲突
# 4. 测试后部署
```

### 8.3 冲突预防规则

**绝对禁止**修改以下文件（上游随时可能更新它们）：

- `main.py`
- `static/` 下的所有文件
- `workflows/` 下的所有文件
- `API/` 下的所有文件
- `python/` 下的所有文件
- `启动服务.bat`
- `VERSION`

**只能新增以下文件/目录**：

- `enterprise/` 下的所有文件
- `enterprise-static/` 下的所有文件
- `enterprise.env`（已加入 .gitignore）
- `启动企业版.bat`
- `停止企业版.bat`
- `ENTERPRISE_DOCS.md`（本文档）
- `.gitignore`

---

## 九、添加新功能的开发模式

### 场景 A：拦截新的 API 路径

修改 `enterprise/interceptors.py`：
- `pre_process()` 中添加访问控制逻辑
- `post_process()` 中添加响应过滤逻辑

### 场景 B：添加新的管理员功能

修改 `enterprise/admin_api.py`：
- 新增 `@router.get/post/put/delete("/api/xxx")` 接口
- 所有接口必须调用 `_require_admin(request)` 鉴权

### 场景 C：添加新的前端页面

在 `enterprise-static/` 下新增 HTML 文件，并在 `enterprise/gateway.py` 中添加对应路由：

```python
@app.get("/enterprise/new-page", include_in_schema=False)
async def new_page(request: Request):
    user = _get_user(request)
    if not user:
        return RedirectResponse("/enterprise/login?next=/enterprise/new-page")
    html_file = ENTERPRISE_STATIC_DIR / "new-page.html"
    return HTMLResponse(html_file.read_text(encoding="utf-8"))
```

### 场景 D：添加新的数据库表

修改 `enterprise/db.py` 的 `init_db()` 函数，在 `executescript` 中添加 `CREATE TABLE IF NOT EXISTS`。

### 场景 E：在资产库/文件系统层面隔离

当前资产库（`data/asset_library.json`）是所有用户共享的（合理）。  
如果未来需要按用户隔离资产，在 `db.py` 新增 `user_asset_map` 表，并在 `interceptors.py` 中添加对 `/api/asset-library` 的拦截。

---

## 十、部署与配置

### 10.1 首次部署步骤

```bash
# 1. Fork 上游仓库到私有仓库
git clone <你的私有仓库>
git remote add upstream https://github.com/hero8152/Infinite-Canvas
git checkout -b enterprise

# 2. 将 enterprise/ 等文件提交到 enterprise 分支
git add enterprise/ enterprise-static/ enterprise.env.example 启动企业版.bat 停止企业版.bat .gitignore ENTERPRISE_DOCS.md
git commit -m "feat: add enterprise layer"

# 3. 修改 enterprise.env（必须修改 JWT_SECRET 和 ADMIN_PASSWORD）
# 4. 双击 启动企业版.bat
#    ↳ 入口会调用 enterprise/launcher.py：
#       a) 启动上游服务（127.0.0.1:3001）
#       b) 轮询等待上游就绪（每秒检测，最多等 60 秒）
#       c) 启动企业网关（0.0.0.0:8000）
#       d) 在同一个启动器中管理两个子进程并自动打开浏览器
#    ↳ 按 Ctrl+C 或关闭启动窗口时，自动停止本次启动器拉起的服务
# 5. 访问 http://localhost:8000/enterprise/admin 创建员工账号
```

### 10.1.1 诊断与冒烟测试

所有测试脚本必须统一放在 `enterprise/tests/`，不要散落在项目根目录、上游目录或临时目录中。

```powershell
# 查看版本、IP、代理、端口、健康检查
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\diagnose.ps1

# 对正在运行的企业网关做非破坏性 HTTP 冒烟测试
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\smoke.ps1

# 破坏性生命周期测试：会先停止当前 8000/3001，再验证启动器关闭后端口释放
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\test_start_stop.ps1 -StopExisting
```

`diagnose.ps1` 会同时显示本机代理配置。若当前主机访问 `11.*` 地址失败，但 `curl --noproxy "*"` 或局域网其他机器访问正常，通常是本机代理绕过规则导致，不代表企业网关故障。

### 10.2 enterprise.env 关键配置

```ini
GATEWAY_PORT=8000          # 企业网关端口
UPSTREAM_PORT=3001         # 上游内部端口（修改后同步更新启动脚本）
JWT_SECRET=<随机32位以上字符串>  # 必须修改！
ADMIN_USERNAME=admin        # 管理员用户名
ADMIN_PASSWORD=<强密码>     # 必须修改！
DB_PATH=./data/enterprise.db
```

### 10.3 安全检查清单

- [ ] `JWT_SECRET` 已修改为随机字符串
- [ ] `ADMIN_PASSWORD` 已修改为强密码
- [ ] `enterprise.env` 已加入 `.gitignore`，不会上传到代码仓库
- [ ] 上游主程序绑定在 `127.0.0.1:3001`（不对局域网暴露）
- [ ] 局域网防火墙允许 8000 端口，屏蔽 3001 端口

---

## 十一、常见问题

**Q：上游更新后某个功能消失了，是企业层拦截了吗？**  
A：在 `interceptors.py` 的 `pre_process` 中检查是否意外拦截了该路径，或在 `post_process` 中过滤了响应。

**Q：企业版里能点击上游的"一键更新"吗？**  
A：可以，但只能由管理员触发。普通用户页面会隐藏"一键更新"按钮，直接请求更新/回滚接口也会返回 403。企业网关会放行管理员的上游更新接口，但会把 `/api/update-from-github` 请求里的 `auto_restart` 强制改为 `false`，避免上游更新后启动普通版 `:3000` 服务。更新完成后请手动重启 `启动企业版.bat`，让内部上游 `:3001` 和企业网关 `:8000` 一起回到正确结构。

**Q：新用户登录后看不到任何画布，是正常的吗？**  
A：是的。每个用户只能看到自己创建的画布。旧数据（企业版部署前已有的画布）没有归属记录，不会出现在任何用户的列表中。若需要迁移旧数据，登录管理后台 → 点击"画布归属"Tab → 找到"未分配"的画布 → 在下拉框中选择用户 → 点击"分配"即可。

**Q：新用户登录后看不到旧对话，是正常的吗？**
A：是的。每个用户只能看到归属自己的对话。旧数据没有 `user_conversation_map` 记录时，普通用户默认不可见、不可直接访问；管理员可在管理后台 → "对话归属"Tab 中查看并分配给目标用户。

**Q：为什么某些图片或输出文件直接 URL 打不开？**
A：企业网关会对 `/assets/input/`、`/assets/output/`、`/assets/uploads/`、`/assets/library/`、`/output/`、`/api/view`、`/api/download-output`、`/api/media-preview` 做归属判断。普通用户只能访问自己画布、对话或资源记录关联到的本地资源；无法判断归属的历史资源默认拒绝，避免绕过画布/对话隔离。

**Q：怎么给用户设置/撤销管理员权限？**  
A：登录管理后台 → 找到对应用户行 → 点击"设为管理员"或"撤销管理员"按钮，立即生效（下次该用户请求时生效，无需重新登录）。注意管理员无法修改自己的权限。

**Q：管理员能在管理后台看到所有画布吗？**  
A：管理员访问 `/api/canvases` 时不做过滤，可以看到所有画布。通过 `/enterprise/api/canvas-owners` 可以查询每个画布的所有者信息。

**Q：WebSocket 不工作怎么办？**  
A：企业版的 WebSocket 代理需要安装 `websockets` 库（启动脚本已自动安装）。如果 WebSocket 仍不工作，主要功能（画布编辑、图像生成）不受影响，仅实时在线人数统计功能会失效。

**Q：怎么修改管理员密码？**  
A：登录管理后台 → 找到管理员用户行 → 点击"重置密码"。或者临时修改 `enterprise.env` 中的 `ADMIN_PASSWORD` 并删除 `enterprise.db`（会丢失所有用户数据，慎用）。

---

## 十二、Agent 接手开发规范

> **面向所有接手此项目的 AI Agent**：在开始任何开发工作之前，必须完整执行以下检查流程，防止出现"开发偏移"——即无意中修改了上游文件，破坏后续上游更新的合并能力。

### 12.1 接手时必读检查清单

**第一步：确认架构理解**

- [ ] 我理解本项目有两层：上游层（`main.py` + `static/`）和企业层（`enterprise/` + `enterprise-static/`）
- [ ] 我理解上游层**永远不能修改**，企业功能全部通过代理拦截实现
- [ ] 我理解上游运行在 `127.0.0.1:3001`，企业网关运行在 `0.0.0.0:8000`

**第二步：当前服务状态确认**

```powershell
# 检查两个端口是否都在监听
try { $null = New-Object System.Net.Sockets.TcpClient('127.0.0.1', 3001); "上游服务:  OK (127.0.0.1:3001)" } catch { "上游服务:  NOT RUNNING" }
try { $null = New-Object System.Net.Sockets.TcpClient('127.0.0.1', 8000); "企业网关:  OK (0.0.0.0:8000)" } catch { "企业网关:  NOT RUNNING" }
```

**第三步：验证数据隔离仍然正常**

```python
# 使用 python/python.exe 执行
import sys, json, http.client
sys.path.insert(0, '.')
from enterprise.auth import create_token
# 替换 user_id 为实际值（从 data/enterprise.db 查询）
# admin 应看到全部画布，普通用户只看到自己的
```

### 12.2 开发时的防偏移规则

**修改文件前，先问自己：**

| 问题 | 如果"是" → 操作 | 如果"否" → |
|------|----------------|-----------|
| 这个文件在 `enterprise/` 或 `enterprise-static/` 目录下吗？ | 可以修改 | 继续往下问 |
| 这个文件是 `enterprise.env`、`启动企业版.bat`、`停止企业版.bat`、`ENTERPRISE_DOCS.md` 之一吗？ | 可以修改 | **禁止修改，寻找替代方案** |
| 其他所有文件 | — | **禁止修改** |

**需求实现路径决策树：**

```
新需求
  ↓
需要修改上游返回的数据？
  → 是 → 修改 enterprise/interceptors.py 的 post_process()
需要阻止某个上游 API 被访问？
  → 是 → 修改 enterprise/interceptors.py 的 pre_process()
需要新的管理员功能？
  → 是 → 修改 enterprise/admin_api.py，新增 @router 路由
需要新的前端页面？
  → 是 → 在 enterprise-static/ 新增 HTML + 在 gateway.py 新增路由
需要新的数据表？
  → 是 → 修改 enterprise/db.py 的 init_db() executescript
上游的某个功能需要复用？
  → 是 → 通过 HTTP 头注入（如 x-user-id）使用上游现有能力，不修改 main.py
```

### 12.3 提交前验证清单

- [ ] 运行服务，确认 `GET /api/canvases` 返回 HTTP 200（不是 502）
- [ ] 用管理员账号验证：可见所有画布
- [ ] 用普通用户验证：只能看到自己创建的画布
- [ ] 检查 `main.py` 未被修改（文件时间戳或内容校验）
- [ ] 检查 `static/` 目录无新增或修改的文件
- [ ] 确认 `enterprise.env` 未加入 git 暂存区

### 12.4 上游更新同步（执行前确认）

当上游发布新版本时，正确的同步流程是：

```bash
# 1. 备份当前 enterprise/ 目录
# 2. 用上游新版本替换 main.py、static/、workflows/ 等
# 3. 保留 enterprise/、enterprise-static/、enterprise.env、启动企业版.bat、停止企业版.bat 不变
# 4. 验证数据隔离仍然正常（见 12.1 第三步）
# 5. 如果上游新增了 API，评估是否需要在 interceptors.py 中添加新的隔离规则
```


