# Infinite-Canvas-Enterprise 企业架构蓝图（2026-07）

更新时间：2026-07-16
代码核对基线：`main@396cccc68d63bd16393a2cb72d24e4a48fcf47cb`

中期架构形态由 [ADR-ENV-001](../decisions/ADR-ENV-001-MODULAR-MONOLITH-MIDTERM-ARCHITECTURE-2026-07.md) 决定；本文件只提供当前运行架构摘要。

## 1. 项目定位

Infinite-Canvas-Enterprise 不是单纯的上游部署。本项目是基于上游 `hero8152/Infinite-Canvas` 的企业多用户二次开发版本。

当前统一定位是：

> 已投入生产的企业安全增强型单机模块化单体。

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

ARCH-2A 的详细代码事实、风险判断、技术决策表和阶段路线见 [ARCH-2A：整体架构评估与演进方向](./ARCH-2A-ARCHITECTURE-ASSESSMENT-AND-EVOLUTION-2026-07.md)。本蓝图只保留架构总览和目标方向，不替代详细评估。

## 2. 当前运行架构

当前真实运行链路：

```text
浏览器 / 局域网用户 / 公网入口
  -> enterprise gateway :8000
  -> 上游 main app :3001
  -> SQLite / JSON / data / assets / output / static / workflows
  -> 外部模型 / ComfyUI / RunningHub 等服务
```

实际职责：

- `enterprise.gateway:app` 是企业入口。
- `main:app` 是上游主应用。
- `8000` 对外暴露。
- `3001` 仅本机访问。
- 企业层通过 gateway / interceptors / db / admin_api 实现登录、鉴权、权限、owner 映射和响应过滤。
- 企业 WebSocket 层对已知敏感事件执行 owner / task / resource 可见性治理。
- 仓库已实现 `enterprise/runtime/` Windows supervisor，通过 service-host 独立监督 upstream 和 gateway；该事实不代表生产已经切换到新 supervisor。
- 默认尽量不直接修改上游覆盖区。

这个架构适合当前“单机无限画布小规模企业多用户化”的阶段目标。它用较小侵入保留上游功能，同时在企业入口处补上登录、隔离和审计。

## 3. 企业层模块说明

| 模块 | 当前职责 |
| --- | --- |
| `enterprise/config.py` | 读取 `enterprise.env`，管理企业端口、上游地址、JWT、DB_PATH、企业仓库地址、更新治理开关和启动安全警告。 |
| `enterprise/auth.py` | 密码认证后的 JWT 创建与校验；当前会话撤销和角色实时同步仍需 P0 补强。 |
| `enterprise/gateway.py` | 企业网关、登录 / 登出、Cookie 鉴权、管理员页面、HTML 注入、设置入口治理、WebSocket 代理和上游 HTTP 代理。 |
| `enterprise/interceptors.py` | 请求前置检查、响应后置过滤、资源访问控制、owner 记录、history / task / asset-library / local-assets / settings / update 等企业隔离策略。 |
| `enterprise/db.py` | SQLite 企业数据库；用户、owner map、feature flags、user overrides、usage_logs、审计和 soft delete 相关数据访问。 |
| `enterprise/ws.py` | 企业 WebSocket connection registry、已知敏感事件过滤和按用户合成事件；当前仍是单进程内存状态。 |
| `enterprise/admin_api.py` | 管理员 API；用户管理、delete-impact、soft delete、feature override 清理、项目 / 画布 / 对话 / 历史归属管理、审计日志查询。 |
| `enterprise/runtime/` | Windows service-host、子进程监督、角色独立恢复、退避 / crash-loop、健康检查、持久日志、runtime state、Job Object 和固定 lifecycle CLI。 |
| `enterprise/launcher.py` | 保留兼容入口；正式生命周期事实由 `enterprise/runtime/` 负责。 |
| `enterprise/ops/` | OPS-2A/2B 与 OPS-3A：inventory、data check、backup、release check/fetch/stage/prepare、报告和 job JSONL；不执行 apply / rollback。 |
| `tools/ops/windows/` | OPS-2B Windows bundled Python 直调 runner 的 dry-run / backup execute 封装。 |
| `enterprise-static/` | 企业登录页、管理员页面、操作日志页面和个人中心等企业静态资源。 |

长期风险：`enterprise/interceptors.py` 继续中心化膨胀。后续新增策略应逐步模块化到 `enterprise/policies/`，再由 gateway / interceptors 编排。

当前模块化单体方向仍合理。这里的“模块化”是演进目标，不表示 policy / service / repository / adapter 分层已经完成，也不表示当前适合立即拆分微服务。

## 4. 当前事实与目标规划边界

### 当前已实现

- 企业 gateway 与 JWT Cookie 登录。
- admin / normal user 角色边界和 owner mapping。
- 项目、画布、对话、资源、历史、任务、素材对象隔离基础。
- 已知敏感 WebSocket 事件治理。
- 管理 API、企业管理前端和基础 audit。
- OPS-2A / OPS-2B、OPS-3A 在线更新核心。
- Windows supervisor、upstream / gateway 独立恢复、固定 lifecycle CLI、持久日志、runtime state 和 Job Object。
- PyJWT 依赖声明与 detached service-host 启动修复。

### 当前部分实现

- 受控更新入口：可 check / fetch / stage / prepare，没有 apply-upgrade / rollback 执行器。
- 日志：runtime 持久日志、crash event、usage audit 和 OPS job JSONL 已有；统一 access / security / metrics 和集中检索仍未完成。
- 数据治理：有 check-data 报告，没有自动修复，也不允许自动修复生产 owner map。
- 依赖与部署：有 Windows bundled Python 运行方式，没有完整依赖锁、Dockerfile 或 Compose。

### 已确认但尚未实施

- P0 会话与默认拒绝安全整改。
- policy / service / repository / adapter 渐进模块化。
- schema version、migration runner、restore rehearsal 和人工 rollback 闭环。
- 真正流式代理和正式负载测试基线。
- Docker / 1Panel 单机生产化。
- ENV-1 路径根、不可变 Release、可信 Windows Runtime 和正式入口契约。
- OPS Release Manifest v2 与 OPS-3B apply / switch / rollback / restore。

### 长期目标

- PostgreSQL、Redis、durable queue、对象存储、多实例和多服务器。
- team / workspace / collaboration ACL、高可用和灾备。

## 5. 上游层边界

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

## 6. 当前数据模型

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

## 7. 权限与数据隔离模型

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

## 8. 受控更新与 OPS 架构

当前已有企业版受控更新入口和 OPS-3A check / fetch / stage / prepare 能力，并通过 `system_update` feature flag 管理系统更新入口。普通用户默认不应触达高风险更新路径。

当前代码中管理员会 bypass feature flag，且 `ENTERPRISE_UPDATE_ENABLED` 默认开启；该语义已列入 ARCH-2B / SEC-1 P0 复核范围，不能把现状描述为高危更新审批闭环已经完成。

OPS-3B 和后续 Update Center 尚未实现。后续入口必须：

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

## 9. 日志与可观测性蓝图

### 当前已有

- `usage_logs` 企业审计表。
- 部分管理员操作写入 audit。
- 登录、用户管理、权限开关、归属管理、素材库关键代管操作等已有审计覆盖。
- Windows runtime 的 launcher / supervisor / child stdout / stderr / health / crash-event 持久日志与轮转、脱敏。
- `runtime-state.json` 与稳定 lifecycle 状态。

### 当前不足

- 无完整 access log。
- 无统一 app log。
- 尚无跨业务域统一结构化 error log。
- 无 security log。
- OPS-2A 已有 job JSONL，但尚未形成与 access / app / error / security log 统一关联的完整体系。
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

## 10. 部署架构蓝图

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

## 11. P0 / P1 / P2 / P3 演进顺序

| 优先级 | 阶段 | 目标 |
| --- | --- | --- |
| P0 | ARCH-2B / SEC-1 | 会话撤销、JWT 角色同步、HTTP / WebSocket 未分类默认拒绝、更新开关语义、Secure Cookie、CSRF、登录限流、next URL、静态路径 containment、错误脱敏和依赖锁。 |
| P1 | ARCH-3 / DATA-1 / PERF-1 / OBS-1 | policy 渐进拆分、repository 与 migration 基础、真流式代理、性能基线和本地可观测性。 |
| P1 / P2 | OPS-3 / OPS-4 | release、restore rehearsal、人工维护窗口升级和人工 rollback 验证；Update Center apply-upgrade 最后考虑。 |
| P2 | OPS-D1 | Docker / 1Panel 单机生产化。 |
| P3 | DATA-2 / SCALE-1 / TEAM-1 | PostgreSQL、Redis、对象存储、多实例、多服务器、团队协作 ACL、高可用与灾备。 |

总体顺序保持：先稳固安全和数据一致性，再建立恢复、性能和可观测性，随后推进单机容器化，最后扩大到多服务器与团队协作。

## 12. 当前已实现 / 部分具备 / 未实现 / 长期目标

| 分类 | 能力 |
| --- | --- |
| 当前已实现 | 企业网关、登录、JWT Cookie、管理员后台、用户管理、启用 / 禁用、soft delete、delete-impact、feature flags、user overrides、审计基础、项目 / 画布 / 对话 / 资源 / 历史 / 素材 / 任务 owner 隔离、WebSocket 隔离、U-2 上游受控同步、U-2-F2 history type 修复。 |
| 当前部分具备 | 受控更新入口、操作日志、启动安全警告、生产只读盘点、生产升级治理设计、OPS-2A runner、OPS-2B Windows wrapper、inventory、backup manifest / copy、check-data、validate-release、prepare-upgrade、OPS job 本地 JSONL、资源引用回溯、外部 provider task owner 拦截。 |
| 当前未实现 | P0 security fixes、apply-upgrade、restore executor、rollback、完整本地 access/app/error/security log、远程日志推送、Dockerfile、docker-compose、1Panel 正式部署、schema migration runner、自动修复型数据治理工具、PostgreSQL、Redis、对象存储生产支持。 |
| 长期目标 | Update Center、计划驱动升级、自动备份、可回滚发布、集中日志、PostgreSQL、对象存储、多服务器部署、协作 ACL、浏览器级自动化回归基线。 |

本文只记录架构蓝图，不代表上述长期目标已经实现。
