# Infinite-Canvas-Enterprise 开发路线图（2026-2027）

更新时间：2026-07-10
ARCH-2A 代码核对基线（PR #69 合并后）：`a095ce2eb9ef9afda356cb6f20b6c38851f52b1d`

## 1. 路线原则

当前系统定位是“已投入生产的企业安全增强型单机模块化单体”。总体路线保持：

> 先稳固安全和数据一致性，再建立恢复、性能和可观测性，随后推进单机生产化，最后扩大到多实例、多服务器和团队协作。

当前继续采用“上游主应用 + enterprise gateway + enterprise data + OPS”的模块化单体，不立即微服务化。任何未来规划都不能写成当前已经支持的能力。

详细架构评估、代码事实和技术决策见 [ARCH-2A：整体架构评估与演进方向](../architecture/ARCH-2A-ARCHITECTURE-ASSESSMENT-AND-EVOLUTION-2026-07.md)。

## 2. 已完成基线

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| 3G owner 隔离主线 | 已完成第一阶段 | 项目、画布、对话、资源、历史、任务、素材和已知敏感 WebSocket 事件的 owner 隔离基础。 |
| 3G-7B | 已完成 | delete-impact、soft delete、feature override 清理和成员管理增强。 |
| U-1 / U-2 / U-2-F2 | 已完成 | 上游只读审计、受控同步到 `2026.07.6` 和 history type 一致性修复。 |
| DOC-1 | 已完成，PR #63 | 项目文档体系与 Agent 交接资料同步。 |
| OPS-0 / OPS-0A | 已完成，PR #64 | 生产环境只读盘点和事实文档化。 |
| OPS-1 | 已完成，PR #65 | 生产备份、离线发布、演练、回滚、migration 与数据治理方案设计。 |
| ARCH-1 | 已完成，PR #66 | 企业架构、开发路线、Docker / 1Panel 和 OPS 蓝图。 |
| OPS-2A | 已完成，PR #67 | inventory、check-data、backup、validate-release、prepare-upgrade 和 OPS job JSONL。 |
| OPS-2B | 已完成，PR #69 | Windows bundled Python + runner.py 直调的 dry-run 和 backup execute wrapper。 |
| ARCH-2A | 已完成，PR #70 | 当前架构评估、目标原则和 P0 / P1 / P2 / P3 演进方向同步。 |
| SEC-1A | 已完成 ADR 决策，PR #71 | 超级管理员、Capability、L0–L3、Step-up 和高风险治理基线；不代表任何超级管理员或安全能力已经实现。 |
| SEC-1B1 | 仓库实现与临时数据库验证完成，PR #72 | role / auth_version、新旧 schema 兼容、显式 migration 基础和 JWT 当前状态加载；生产 migration 未激活。 |

OPS-2A / OPS-2B 已进入 main，项目负责人已在生产侧人工完成 dry-run 和一次单独确认的正式备份。该事实不代表 restore、upgrade、apply-upgrade 或 rollback 已实现，也不代表生产已经升级。当前 `check-data` 仍有 warn，数据未被自动修复。

## 3. 当前阶段

ARCH-2A 架构评估与演进方向文档同步已完成，由 PR #70 承载。完成 ARCH-2A 只代表架构共识、目标原则和 P0 / P1 / P2 / P3 路线同步完成。

ARCH-2A 完成不代表以下事项已经实施：

- P0 security fix。
- policy / repository / service 重构。
- schema migration。
- Docker / 1Panel。
- PostgreSQL、Redis 或对象存储。
- apply-upgrade、restore 或 rollback executor。
- 自动 owner-map 修复。

SEC-1A 已完成 ADR 决策，由 PR #71 承载。SEC-1B1 已完成仓库实现和临时数据库验证，由 PR #72 承载；不代表生产 migration 已激活、super_admin 已创建或 Capability / Step-up / 安全审计已经实现。当前下一阶段是 SEC-1F0，之后才是 SEC-1B2 migration activation 与首次 bootstrap。每个安全事项必须使用独立 Issue、独立分支和独立 Draft PR。

## 4. 近期路线

### 4.1 ARCH-2A：已完成的架构评估与方向同步

- 统一当前系统定位。
- 分开当前实现、部分实现、已确认方向和长期目标。
- 固化目标模块边界和架构决策。
- 建立后续任务拆解与审查规则。
- 状态：文档同步已完成，由 PR #70 承载；不代表任何整改已实施。

### 4.2 ARCH-2B / SEC-1：P0 安全整改任务拆分

SEC-1A 只完成 ADR。后续按独立 Issue / Draft PR 实施：

| 任务 | 范围 | 状态 |
| --- | --- | --- |
| SEC-1A | user / admin / super_admin、Capability、L0–L3、Step-up、bootstrap 和高风险治理 ADR | ADR 决策完成；未实现代码 |
| SEC-1B1 | `role`、`auth_version`、migration、JWT 当前状态加载和旧 Token 撤销的实现与临时数据库验证；不激活生产 migration | 仓库实现完成，PR #72；生产未激活 |
| SEC-1F0 | 最小强制安全审计 schema、append-only 写入、bootstrap / role change / break-glass、敏感字段禁记、fail closed 和临时数据库测试 | 下一阶段，SEC-1B2 前置，未实现 |
| SEC-1B2 | migration activation 与本机首次 super_admin bootstrap；依次进入 `UNINITIALIZED`、`ACTIVE` | SEC-1F0 后置，未实现 |
| SEC-1C | Capability 后端门禁、最后超级管理员保护、防自我提权、admin 不得影响 super_admin | 未实现 |
| SEC-1D | Step-up Authentication、单次 Operation Token、replay protection、CSRF / Origin | 未实现 |
| SEC-1E | 管理后台角色治理、高风险警告、二次认证 UI 和浏览器回归 | 未实现 |
| SEC-1F | 完整安全审计查询、脱敏摘要导出、保留和归档策略 | 未实现 |
| SEC-1U | `system_update` bypass、更新总开关、升级 approve / execute、白名单 OPS 和禁止任意 shell | 未实现 |

其它 P0 安全事项继续独立拆分：HTTP 未分类 route 默认拒绝、WebSocket 未知 event 默认拒绝、Secure Cookie、登录限流、`next` URL 校验、企业静态路径 containment、生产错误脱敏和依赖锁定。SEC-1A 的详细决策见 [ADR SEC-1A](../decisions/ADR-SEC-1A-SUPER-ADMIN-CAPABILITY-GOVERNANCE-2026-07.md)。

### 4.3 DATA-1：数据一致性与 migration 基础设计

- repository 接口。
- schema version。
- migration history。
- SQLite `busy_timeout`、索引和约束复核。
- owner reconciliation 报告与人工修复计划。
- 临时数据库 dry-run、备份和回滚测试。

不自动修复生产 owner map，不直接修改生产数据库。

### 4.4 OPS 恢复演练

- 核对已执行 backup manifest。
- 在隔离副本中做 restore rehearsal。
- 验证 SQLite、JSON、assets / output、env 和启动链路。
- 记录人工 rollback 决策点与恢复时间。

已有 backup 不等于 restore 已完成。restore rehearsal 通过前，不接入网页 apply-upgrade。

### 4.5 OBS-1 / OPS-L1：日志与可观测性基础

- access / app / error / security / operation log。
- request_id / job_id。
- 本地结构化 JSONL 与轮转 / 保留策略。
- 磁盘、SQLite、任务、WebSocket 和 upstream 健康检查。
- 默认脱敏和敏感字段审计。

当前只有 usage audit、OPS job JSONL 和进程输出，不能写成完整日志体系已实现。

## 5. 中期路线

### 5.1 ARCH-3：策略模块化

- 建立显式 route registry 和 WebSocket event registry。
- 按数据域渐进拆分 policy。
- 引入 service / repository 边界。
- 每次只迁移一个数据域并保持 API 行为兼容。
- 不一次性重写 `interceptors.py`。

### 5.2 PERF-1：真流式代理和性能基线

- 真正流式上传 / 下载 / SSE。
- 大文件限制、timeout、背压和中断传播。
- 去除在线全目录扫描。
- 同步 SQLite / 文件 I/O 与 async handler 隔离。
- 建立可重复负载测试，不承诺未经测试的容量数字。

### 5.3 OPS-D1：Docker / 1Panel 单机生产化

- Linux entrypoint 和单容器双进程管理。
- Dockerfile、Compose、volume、healthcheck 和日志。
- 1Panel HTTPS、WebSocket proxy、上传大小和长任务 timeout。
- 计划任务备份与恢复演练。

当前不是 Docker-ready。只有该阶段实现并完成验收后，才能更新支持声明。

### 5.4 PostgreSQL 迁移准备

- 先完成 DATA-1 repository 和 migration 基础。
- 设计 PostgreSQL target schema ADR。
- 建立 SQLite 导出 / PostgreSQL 导入的临时环境演练。
- 定义校验、维护窗口和回滚。

这一阶段是准备，不是 PostgreSQL 正式迁移。

## 6. 长期路线

1. PostgreSQL 正式迁移。
2. Redis / durable queue / Pub/Sub。
3. MinIO / S3 / NAS storage adapter。
4. 多实例 session、realtime 和任务执行。
5. 多服务器健康检查与集中日志。
6. workspace / organization / member roles / ACL / grants。
7. 团队资源、项目协作、共享 / 撤销和合规审计。
8. 高可用、灾备和故障演练。

这些是 P3 长期目标，不是当前能力。

## 7. OPS 路线

建议顺序：

1. release builder。
2. release validator 增强。
3. backup restore rehearsal。
4. 人工维护窗口 upgrade rehearsal。
5. 人工 rollback 验证。
6. 最后才评估 Update Center 的 apply-upgrade。

`prepare-upgrade` 只生成 plan。OPS-3 / OPS-4 不得被描述为当前已实现；网页端未来也只能调用白名单、计划驱动、可审计的 OPS API，不能执行任意 shell。

## 8. 自动化测试路线

3G-8 浏览器级自动化回归保留，并应逐步纳入每个安全 / policy 阶段：

- 登录 / 登出与旧 Token 撤销。
- user A、user B、admin、super_admin（角色落地后）。
- 列表过滤和直接 ID。
- 资源 URL。
- 刷新、退出重登和角色变化。
- 历史、画布、对话、素材、任务。
- 设置与高风险功能。
- WebSocket 已知事件和未知事件。
- Update Center 仅在实际实现后纳入。

每个权限 PR 都必须提供对应 API 回归；前端隐藏不能替代后端鉴权。

## 9. 阶段门禁

| 进入阶段 | 前置门禁 |
| --- | --- |
| ARCH-3 | P0 默认拒绝策略和关键会话安全已建立，现有 A/B/admin 回归可运行。 |
| DATA-1 migration 实现 | schema / backup / rollback 设计通过，临时数据库测试可重复。 |
| OPS 正式升级演练 | executed backup、restore rehearsal、release validation 和 data-check 已人工复核。 |
| Docker / 1Panel | volume、日志、healthcheck、backup / restore 和 WebSocket 验收方案已明确。 |
| PostgreSQL 正式迁移 | repository、schema version、导入校验、维护窗口和回滚演练完成。 |
| 多实例 / 多服务器 | session、queue、realtime、shared storage 和集中可观测性完成。 |
| 团队协作 ACL | organization / member / grant / revoke / audit 模型和迁移策略独立评审。 |

## 10. 持续禁止事项

- 生产 `git pull`、`checkout main`、`reset --hard` 或开发目录覆盖。
- 未备份、未恢复演练、未回滚设计的生产升级。
- 自动修复生产 owner map 或自动删除生产文件。
- 在普通功能 PR 中顺手完成大规模架构重构。
- 把 Docker、PostgreSQL、Redis、MinIO、apply-upgrade、restore、rollback 写成已实现。
- 用连接池大小、WAL 或单进程 WebSocket 推导并发容量或多实例能力。

## 11. 任务交付规则

- 每个 P0 / P1 / P2 / P3 项目使用独立 Issue、独立分支和独立 Draft PR。
- 安全策略变更至少覆盖 user A、user B、admin。
- 权限变更覆盖列表、直接 ID、资源 URL、刷新 / 重登和 WebSocket。
- migration 必须有 dry-run、备份、回滚和临时数据库测试。
- 生产动作由项目负责人人工执行；Codex 不直接连接生产主机。
- 每个实现 PR 同步对应状态文档，保持当前事实与规划边界一致。
