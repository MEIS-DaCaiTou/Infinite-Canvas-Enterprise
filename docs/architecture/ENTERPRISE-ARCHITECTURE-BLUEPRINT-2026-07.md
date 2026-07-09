# Infinite-Canvas-Enterprise 企业架构蓝图（2026-07）

## 1. 项目定位

Infinite-Canvas-Enterprise 不是单纯的上游部署。本项目是基于上游 `hero8152/Infinite-Canvas` 的企业多用户二次开发版本。

当前目标是在尽量保留上游 Infinite Canvas 能力的基础上，增加：

- 企业登录。
- 权限隔离。
- 资源归属。
- 项目 / 画布 / 对话隔离。
- 审计日志。
- 管理后台。
- 受控更新。
- 生产运维治理。
- 后续多服务器部署能力。

当前项目已经形成“企业安全隔离底座”，但还不是完整 team / workspace / ACL 协作平台。后续协作能力必须在 owner 隔离、生产备份、升级治理和自动化验收基线稳定之后再设计和实现。

## 2. 当前运行架构

当前真实运行链路：

```text
浏览器 / 局域网用户 / 公网入口
  -> enterprise gateway :8000
  -> 上游 main app :3001
  -> data / assets / output / static / workflows
```

实际职责：

- `enterprise.gateway:app` 是企业入口。
- `main:app` 是上游主应用。
- `8000` 对外暴露。
- `3001` 仅本机访问。
- 企业层通过 gateway / interceptors / db / admin_api 实现登录、鉴权、权限、owner 映射和响应过滤。
- 默认尽量不直接修改上游覆盖区。

这个架构适合当前“单机无限画布小规模企业多用户化”的阶段目标。它用较小侵入保留上游功能，同时在企业入口处补上登录、隔离和审计。

## 3. 企业层模块说明

| 模块 | 当前职责 |
| --- | --- |
| `enterprise/config.py` | 读取 `enterprise.env`，管理企业端口、上游地址、JWT、DB_PATH、企业仓库地址、更新治理开关和启动安全警告。 |
| `enterprise/gateway.py` | 企业网关、登录 / 登出、Cookie 鉴权、管理员页面、HTML 注入、设置入口治理、WebSocket 代理和上游 HTTP 代理。 |
| `enterprise/interceptors.py` | 请求前置检查、响应后置过滤、资源访问控制、owner 记录、history / task / asset-library / local-assets / settings / update 等企业隔离策略。 |
| `enterprise/db.py` | SQLite 企业数据库；用户、owner map、feature flags、user overrides、usage_logs、审计和 soft delete 相关数据访问。 |
| `enterprise/admin_api.py` | 管理员 API；用户管理、delete-impact、soft delete、feature override 清理、项目 / 画布 / 对话 / 历史归属管理、审计日志查询。 |
| `enterprise/launcher.py` | 当前 Windows bat 启动入口；负责拉起 `main.py:3001` 和 `enterprise.gateway:8000` 双进程，并打印局域网访问地址。 |
| `enterprise-static/` | 企业登录页、管理员页面、操作日志页面和个人中心等企业静态资源。 |

长期风险：`enterprise/interceptors.py` 继续中心化膨胀。后续新增策略应逐步模块化到 `enterprise/policies/`，再由 gateway / interceptors 编排。

## 4. 上游层边界

以下区域视为上游覆盖区：

- `main.py`
- `static/`
- `workflows/`
- `API/`
- `python/`
- `VERSION`

默认不修改上游覆盖区。只有以下场景允许最小化修改：

- 受控上游同步。
- 明确 bugfix。
- 与企业隔离、权限治理、生产升级直接相关的必要兼容。

修改上游覆盖区时必须在 PR 中说明：

- 修改原因。
- 风险。
- 回滚方案。
- 自动化测试。
- 项目负责人手动验收范围。

禁止整目录覆盖 `static/`，禁止把本地运行时 `python/`、`assets/`、`output/`、`data/` 或密钥配置带入 Git。

## 5. 当前数据模型

当前生产主要使用 SQLite：

- 数据库：`data/enterprise.db`
- 主要上游数据：`history.json`、`data/canvases/`、`data/conversations/`、`assets/`、`output/`

企业数据库当前核心表包括：

| 表 | 用途 |
| --- | --- |
| `users` | 企业用户、管理员标记、启用状态、登录时间。 |
| `usage_logs` | 企业审计日志。 |
| `user_project_map` | 项目 owner 映射。 |
| `user_canvas_map` | 画布 owner 映射。 |
| `user_conversation_map` | 对话 owner 映射。 |
| `user_history_map` | 历史记录 owner 映射。 |
| `user_resource_map` | 本地资源 URL owner 映射。 |
| `user_canvas_task_map` | 画布任务 owner 映射。 |
| `user_task_map` | 外部 provider / workflow / RunningHub 等异步 task owner 映射。 |
| `user_asset_object_map` | 素材库 library / category / item 业务对象 owner 映射。 |
| `enterprise_feature_flags` | 全局功能开关。 |
| `enterprise_user_feature_overrides` | 单用户功能覆盖。 |

当前仍是 JSON / 文件系统 / SQLite 混合存储。owner map 是企业隔离核心，不能绕过。生产已经有真实用户和真实业务数据，不能直接覆盖或清理。

## 6. 权限与数据隔离模型

当前权限模型：

- 登录由企业网关统一处理。
- 会话通过 JWT Cookie 校验。
- 管理员与普通用户分离。
- 管理员 bypass 大部分业务隔离，用于治理和代管。
- 普通用户默认只能访问自己 owner 的项目、画布、对话、资源、历史、任务和素材对象。
- 普通用户对未知 owner / unowned 敏感数据默认拒绝。
- 管理员可治理 owner 映射。
- 功能入口由 feature flags 和 user overrides 控制。

当前已纳入 owner 模型的对象：

- 项目。
- 画布。
- 对话。
- 上传资源。
- 输出资源。
- 历史记录。
- 异步任务。
- 画布任务。
- 素材库业务对象。

仍需持续补强：

- 外部 provider 成功链路补验。
- 浏览器级自动化回归。
- 协作 ACL 设计。
- 数据治理巡检和修复流程。

## 7. 受控更新与 OPS 架构

当前已有企业版受控更新入口，并通过 `system_update` feature flag 管理系统更新入口。普通用户默认不应触达高风险更新路径。

后续应把更新入口演进为 Update Center：

- 只展示计划驱动的 OPS job。
- 只调用白名单 OPS API。
- 不得执行任意 shell。
- 不得直接把网页输入拼接成系统命令。
- 高危动作必须基于 plan、backup、日志和回滚点。

长期 OPS 核心对象：

- ops runner。
- upgrade plan。
- backup manifest。
- rollback plan。
- data-check report。
- ops job log。

Update Center 应成为管理员触发和查看 OPS job 的入口，而不是直接操作生产系统的脚本控制台。

## 8. 日志与可观测性蓝图

### 当前已有

- `usage_logs` 企业审计表。
- 部分管理员操作写入 audit。
- 登录、用户管理、权限开关、归属管理、素材库关键代管操作等已有审计覆盖。
- 启动器 / 网关主要通过 print / uvicorn warning 输出运行信息。

### 当前不足

- 无完整 access log。
- 无统一 app log。
- 无结构化 error log。
- 无 security log。
- 无 OPS job log 完整体系。
- 无远程日志推送。
- 无后台日志检索页面。
- 无集中日志平台适配。

### 目标规划

后续应分层建立：

- OPS job log。
- access log。
- app log。
- error log。
- security log。
- audit log。
- 本地 JSONL。
- 后续 HTTP push / syslog / Loki / ELK / OpenSearch / ClickHouse 适配。

日志体系必须默认脱敏，不记录密钥值、登录凭据、会话凭据、管理员密码或用户隐私。

## 9. 部署架构蓝图

### 当前部署

- Windows 单机。
- bat 启动。
- bundled python。
- SQLite。
- 本地 `data/`、`assets/`、`output/`。
- 局域网访问。
- frpc / frps + 1Panel 反代规划。
- 公网 WebSocket 支持状态仍需确认。

### 目标部署

- Windows 单机继续支持。
- Linux 裸机可支持。
- Docker 单容器可支持。
- Docker Compose 可支持。
- 1Panel 可支持。
- 长期 PostgreSQL。
- 长期 NAS / MinIO / S3 / 对象存储。
- 长期集中日志。
- 长期多服务器部署。

当前项目具备 Docker 化基础，但还不是 Docker-ready，不能宣称已经支持一键 Docker 部署。

## 10. 当前已实现 / 部分具备 / 未实现 / 长期目标

| 分类 | 能力 |
| --- | --- |
| 当前已实现 | 企业网关、登录、JWT Cookie、管理员后台、用户管理、启用 / 禁用、soft delete、delete-impact、feature flags、user overrides、审计基础、项目 / 画布 / 对话 / 资源 / 历史 / 素材 / 任务 owner 隔离、WebSocket 隔离、U-2 上游受控同步、U-2-F2 history type 修复。 |
| 当前部分具备 | 受控更新入口、操作日志、启动安全警告、生产只读盘点、生产升级治理设计、资源引用回溯、外部 provider task owner 拦截。 |
| 当前未实现 | OPS runner、备份脚本、离线 release 包生成、apply-upgrade、rollback、完整 OPS job log、本地结构化 access/app/error/security log、远程日志推送、Dockerfile、docker-compose、1Panel 正式部署手册、schema migration 工具、数据治理巡检工具、PostgreSQL 生产支持、对象存储生产支持。 |
| 长期目标 | Update Center、计划驱动升级、自动备份、可回滚发布、集中日志、PostgreSQL、对象存储、多服务器部署、协作 ACL、浏览器级自动化回归基线。 |

本文只记录架构蓝图，不代表上述长期目标已经实现。
