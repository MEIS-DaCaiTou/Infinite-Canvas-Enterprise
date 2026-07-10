# 无限画布企业版 · 架构说明

本文档描述当前企业多用户版 Infinite Canvas 的运行架构和主要模块职责。

> 当前事实源：本文件保留快速运行架构说明。基于 `main@a095ce2eb9ef9afda356cb6f20b6c38851f52b1d` 的完整评估、风险与 P0 / P1 / P2 / P3 演进方向见 `docs/architecture/ARCH-2A-ARCHITECTURE-ASSESSMENT-AND-EVOLUTION-2026-07.md`。当前统一定位是“已投入生产的企业安全增强型单机模块化单体”；规划中的 Docker、PostgreSQL、Redis、对象存储、apply-upgrade、restore 和 rollback 尚未实现。

---

## 1. 总体架构

```text
局域网/服务器用户浏览器
        |
        | HTTP + enterprise_token Cookie
        v
Enterprise Gateway
enterprise/gateway.py
监听 0.0.0.0:8000
        |
        | 反向代理 + 用户上下文注入 + 拦截/过滤
        v
上游 Infinite Canvas
main.py
监听 127.0.0.1:3001
        |
        +-- data/canvases/*.json
        +-- data/conversations/
        +-- static/

企业层独立数据
data/enterprise.db
```

企业网关是对外入口。上游 Infinite Canvas 只在本机内部端口运行，不直接暴露给局域网用户。

---

## 2. 端口职责

| 端口 | 服务 | 访问范围 | 说明 |
|------|------|----------|------|
| `8000` | 企业网关 | 局域网/服务器对外 | 用户访问入口，负责登录、鉴权、代理 |
| `3001` | 上游主程序 | 仅本机 `127.0.0.1` | 内部上游服务，不直接对外开放 |

---

## 3. 企业网关

文件：`enterprise/gateway.py`

职责：

- 提供企业登录、退出、个人中心、管理后台页面入口
- 校验 `enterprise_token` Cookie
- 对普通上游请求进行反向代理
- 向上游注入企业用户上下文
- 调用 `enterprise/interceptors.py` 做访问控制与响应过滤
- 保护管理员专用接口和上游更新/回滚相关接口
- 提供 `/enterprise/health` 健康检查

---

## 4. 拦截与过滤

文件：`enterprise/interceptors.py`

职责：

- 请求前置处理：判断当前用户是否允许访问某些路径
- 响应后置处理：过滤上游返回的画布和对话列表
- 将普通用户限制在自己拥有的画布/对话范围内
- 允许管理员查看和管理全量数据

拦截层是企业数据隔离的核心。修改该文件时必须优先验证普通用户和管理员的可见范围。

---

## 5. 企业数据库

文件：`enterprise/db.py`

数据库：`data/enterprise.db`

主要表：

- `users`：企业用户账号、密码哈希、角色、状态
- `user_canvas_map`：画布归属关系
- `user_conversation_map`：对话归属关系
- `usage_logs`：审计日志

企业数据库不替换上游数据文件，只记录企业身份、归属和审计信息。

---

## 6. 管理 API

文件：`enterprise/admin_api.py`

职责：

- 用户列表、创建用户、禁用用户
- 重置用户密码
- 设置或撤销管理员角色
- 查询和修改画布归属
- 查询审计日志

管理员 API 必须执行管理员鉴权，不应暴露给普通用户。

---

## 7. 企业前端

目录：`enterprise-static/`

职责：

- `login.html`：企业登录页
- `admin.html`：企业管理后台
- `profile.html`：个人中心
- `logs.html`：审计日志页面

企业前端页面服务于企业登录、管理和审计，不应替代上游 `static/` 中的画布主体验。

---

## 8. 启动与测试

关键文件：

- `启动企业版.bat`
- `停止企业版.bat`
- `enterprise/launcher.py`
- `enterprise/tests/diagnose.ps1`
- `enterprise/tests/smoke.ps1`
- `enterprise/tests/test_start_stop.ps1`

启动器负责同时管理内部上游和企业网关。测试脚本统一放在 `enterprise/tests/`，不得散落到项目根目录或上游目录。

---

## 9. 上游同步策略

上游更新覆盖区域包括：

- `main.py`
- `static/`
- `workflows/`
- `API/`
- `python/`
- `VERSION`

企业层应尽量不侵入这些文件。上游更新后，应保留企业层目录和文档，重新运行诊断、冒烟和手工清单。

