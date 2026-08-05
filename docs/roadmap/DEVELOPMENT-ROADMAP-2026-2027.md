# Infinite-Canvas-Enterprise 开发路线图（2026-2027）

更新时间：2026-08-05
最后一次代码事实核对基线：`main@105f3ca47f81207d2820fbd9acfa0a6d7b65770a`

当前 repository HEAD 以 GitHub `main` 为准；PR #80 至 PR #90 的已授权 ENV、Runtime、Manifest 和 clean-Windows validation 阶段均已合并。PR #90 merge commit 为 `105f3ca47f81207d2820fbd9acfa0a6d7b65770a`；Candidate 08 已完成独立 W01-W14 `14 PASS / 0 FAIL / 0 BLOCKED`，成为首个接受的不可变 clean-Windows RC。它不是 formal Release、activation、Production Baseline 或生产部署。

当前实施事实以 [CURRENT_PROJECT_STATUS](../CURRENT_PROJECT_STATUS.md) 为准；架构决策以 [ADR 索引](../README.md) 为准。本文负责阶段顺序，不重复定义实现状态。

## 1. 路线原则

当前仓库架构定位是“企业安全增强型单机模块化单体”。旧生产仍运行历史版本并已定义为待退役遗留系统；当前仓库基线继续开发，未来新生产采用 Greenfield 全新部署。该决策以 [ADR-OPS-007](../decisions/ADR-OPS-007-GREENFIELD-PRODUCTION-BASELINE-AND-LEGACY-NON-MIGRATION-2026-07.md) 为准。总体路线调整为：

> 先形成可维护、可恢复、可持续升级的 Production Baseline，再在干净环境全新部署；旧生产不作为迁移输入或原地升级目标。

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
| SEC-1F0 | 仓库实现与临时数据库验证完成，PR #73 | 最小强制安全审计 Schema、append-only writer、显式 migration 和 fail closed；生产 Schema 未激活，在线操作未接线。 |
| SEC-1C0 | 仓库实现与临时数据库验证完成，PR #74 | 首次 bootstrap 前的角色层级保护、READY 原子审计、在线角色关闭和最后 active super_admin helper；生产 migration 未激活。 |
| SEC-1B2 | 仓库实现与临时数据库验证完成，PR #75 | 本机受控 activation plan、正式备份与指纹门禁、不可变 bootstrap marker、生命周期检查和原子首次 bootstrap；生产 activation 未执行。 |
| OPS-3A | 已合并，PR #77 | 在线更新检查、下载、验证、staging 和 prepare plan；不包含 apply / rollback。 |
| STAB-1 / OPS-L1 | 已合并，PR #78 | Windows supervisor、角色独立恢复、lifecycle CLI、持久日志、runtime state 和 Job Object。 |
| Runtime service-host hotfix | 已合并，PR #79 | detached host / child 脚本路径隔离和启动失败证据；不代表生产已切换。 |
| ENV-1B0 / DOC-2 / DOC-2A | 已合并，PR #80 | 冻结架构决策、Greenfield 生产路线和文档事实；merge commit `be5573a`。 |
| ENV-1B1A | 已合并，PR #81 | APP_ROOT 写入审计、static 构建期哈希和漂移门禁；merge commit `a53885b`，不等于完整 APP_ROOT 只读。 |
| ENV-1B2P | 已合并，PR #82 | Runtime 分层来源证据验证；core true、dependency/archive false，production approval 固定 false。 |
| ENV-1B1B | 已合并，PR #83 | PathRoots、严格 pointer 和核心路径迁移；不实施 activation、B1C 或完整 immutable release。 |
| ENV-1B1C-B1 | 已合并并独立验收，PR #84 | Runtime mode、manifest startup view、Python identity、preflight、launch context、writable probe、release/ownership gate 和 path safety 的纯契约与测试基础；不接入正式 lifecycle。 |
| ENV-1B1C-B2 | 已合并，PR #86 | 固定 direct-script launcher、Release Python/preflight/launch-context 信任链、复用 STAB-1 lifecycle 的 host/supervisor/child identity、ownership、readiness 和 Windows wrappers。 |
| ENV-1B2A | 已合并，PR #87 | 固定 CPython 3.10.11 x64，完成官方 source、hash lock、闭合 wheelhouse、双 clean build、pip check、SBOM、deterministic archive 和真实 B2 fixture；作为历史证据和 rollback baseline 保留。 |
| ENV-1B2B | Repository implementation 已独立验收 | 唯一 active Runtime 迁移到 ordinary-GIL CPython 3.14.6 / cp314，`ENV_1B2_completed=true`；后续 ENV-1B3 已完成 clean-Windows 验证，formal Release 和 production approval 尚未完成。 |
| OPS Release Manifest v2 | Repository implementation 已独立验收 | Release candidate payload 可构建、离线验证，portable startup 已绑定 Manifest v2；activation、OPS-3B 与 formal Release 尚未完成。 |
| ENV-1B3 | 已完成并合并，PR #90 | Candidate 08 在独立 Windows Guest 完成 W01-W14 `14/0/0`，`clean_Windows_validation=true`、`ENV_1B3_completed=true`；不等于 formal Release、Production Baseline 或生产部署。 |

OPS-2A / OPS-2B 已进入 main，项目负责人曾在旧生产侧人工完成 dry-run 和一次单独确认的正式备份。这些是历史运维事实，不代表 restore、upgrade、apply-upgrade 或 rollback 已实现，也不再作为旧到新迁移输入。旧生产 `check-data` warning 和其中的 unowned、orphan map、missing file 不再阻塞新生产基线；旧数据仍未被自动修复或删除。

## 3. 当前阶段

当前已确认状态为 **ENV-1B1C-B1/B2、ENV-1B2A/B2B、OPS Release Manifest v2 与 ENV-1B3 已完成各自批准范围**。`ENV_1B2_completed=true`、`ENV_1B3_completed=true`、`clean_Windows_validation=true`；当前阶段移至 DATA-1 与 Fresh Install Bootstrap 准备。Release activation、OPS-3B、formal Release、Production Baseline 和生产批准仍未完成。正常上游功能同步继续受控；紧急安全漏洞修复可单独评估并引入。

Greenfield Production Baseline 路线按以下顺序执行，后项不能绕过前项门禁：

0. ENV-1B0：架构决策冻结和文档事实同步；已合并。
1. ENV-1B1A：完整 APP_ROOT 写入审计与 static 构建期哈希；已由 PR #81 合并完成，但不等于完整 APP_ROOT 只读。
2. ENV-1B2P：Python 核心、依赖层、archive provenance 分层证据；已合并，core `true`、dependency `false`、archive `false`、`production_approved=false`。
3. ENV-1B1B：路径根、版本目录和 `current-release.json`；已合并，不含 activation。
4. ENV-1B1C-B1：Runtime mode、manifest startup view、Python identity、preflight、launch context 和 writable probe 的纯契约/安全原语；已由 PR #84 合并并独立验收，不接入 lifecycle。
5. ENV-1B1C-B1 docs closeout：由独立 docs-only closeout commit 持久化 Final Acceptance evidence；不接入 Runtime lifecycle。
6. ENV-1B1C-B2：已由 PR #86 合并；固定 portable launcher、Release Python 信任链、现有 STAB-1 lifecycle 与 readiness 已进入 `main`。
7. ENV-1B2A：固定 Python 3.10 layout 的官方来源、依赖锁、离线双重建、`pip check`、SBOM、deterministic archive 和 B2 fixed-Python fixture；已由 PR #87 合并并保留为 rollback baseline。
8. ENV-1B2B：资格门禁选择 CPython 3.14.6；cp314 active policy、离线双构建、三层 provenance 与真实 formal-entry fixture 已完成并通过 repository implementation 独立验收，`ENV_1B2_completed=true`。
9. OPS Release Manifest v2：repository implementation 已独立验收，Release candidate payload 可构建并离线验证，portable startup 已绑定 v2；不含 activation 或 OPS-3B。
10. ENV-1B3：已由 PR #90 合并；Candidate 08 在独立 Windows Guest 完成无系统 Python、标准非管理员、中文/空格/长路径、低磁盘、重启、损坏 DLL/manifest、杀毒软件和只读 APP_ROOT 等 W01-W14 `14/0/0`。
11. 首个不可变 clean-Windows Release Candidate 已接受；Release Candidate 仍不等于 formal Release 或 Production Baseline。
12. DATA-1：Repository、schema version、migration history、新版本 migration compatibility、数据完整性和数据库回滚基础；不迁移或修复旧生产数据。
13. Fresh Install Bootstrap：面向空环境建立目标 Schema、mandatory audit、首个 `super_admin` 和不可变 lifecycle marker。
14. 在干净 Windows 环境完成全新安装与初始化验收。
15. 收口 ARCH-3、P0 安全、PERF-1 / OBS-1、浏览器回归和真实 Provider 成功链路。
16. 使用全新基线数据完成正式 backup 和 restore rehearsal。
17. OPS-3B repository implementation：实现计划驱动的 apply / switch / health / rollback / restore；不用于旧生产。
18. 在干净 Windows 环境使用 Fresh Install Bootstrap 建立的全新隔离数据，完成 Release Candidate 之间的升级、rollback / restore 演练；这是开发或隔离验证，不是生产执行。
19. 由项目负责人确认已经具备经过验证的持续升级和失败恢复能力，并批准 Production Baseline。
20. 在生产设备使用全新数据库、账号、配置和凭据执行 Greenfield 部署，并完成新生产业务验收。
21. 后续正式 Release 进入新生产版本迭代；OPS-3B 的首次真实生产执行只能发生在 Greenfield 新生产部署以后，并由项目负责人在生产设备本地执行。
22. 新生产验收通过后，由项目负责人另行决定旧生产停止、归档或删除。
23. OPS-3C / Update Center 可在 Production Baseline 后单独实施，不是首次生产部署前置条件。
24. Linux 单服务器适配。
25. PostgreSQL、对象存储、queue、Redis 和多实例按真实需求引入。

第 0 至 11 项已完成各自批准范围；当前依次进入：DATA-1、Fresh Install Bootstrap、clean-Windows 全新安装/初始化验收、P0/ARCH-3/PERF-1/OBS-1/browser/provider 收口、backup/restore rehearsal、OPS-3B repository implementation、apply/switch/health/rollback/restore rehearsal、Production Baseline 批准和 Greenfield 生产部署。Linux、PostgreSQL、Redis、对象存储、durable queue、多实例、Windows Service、formal Release 和 Production Baseline 当前仍不是已完成能力。

## 4. 历史拆解参考

本节保留 ENV-1B0 之前的 ARCH / SEC / DATA / OPS 拆解语境，不再决定当前执行顺序；当前顺序只以上一节为准。

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
| SEC-1B1 | `role`、`auth_version`、migration、JWT 当前状态加载和旧 Token 撤销的实现与临时数据库验证 | 仓库实现完成，PR #72；不在旧生产执行 migration |
| SEC-1F0 | 最小强制安全审计 schema、append-only 写入、bootstrap / role change / break-glass catalog、敏感字段禁记、fail closed 和临时数据库测试 | 仓库实现完成，PR #73；不在旧生产 activation，在线操作未接线 |
| SEC-1C0 | 首次 bootstrap 前的 super_admin 过渡保护：admin 不得影响 super_admin、禁止自行提权、正常在线事务不得将 active super_admin 降为零；不实现完整 Capability | 仓库实现完成，PR #74；不在旧生产 activation |
| SEC-1B2 | 面向现有 active admin 的受控 migration activation 与本机首次 super_admin bootstrap；实施 plan、备份门禁、生命周期和原子 runner | 仓库实现完成，PR #75；代码保留但不在旧生产执行，也不是 Fresh Install Bootstrap |
| SEC-1C | Capability 后端门禁、最后超级管理员保护、防自我提权、admin 不得影响 super_admin | 未实现 |
| SEC-1D | Step-up Authentication、单次 Operation Token、replay protection、CSRF / Origin | 未实现 |
| SEC-1E | 管理后台角色治理、高风险警告、二次认证 UI 和浏览器回归 | 未实现 |
| SEC-1F | 完整安全审计查询、脱敏摘要导出、保留和归档策略 | 未实现 |
| SEC-1U | `system_update` bypass、更新总开关、升级 approve / execute、白名单 OPS 和禁止任意 shell | 未实现 |

其它 P0 安全事项继续独立拆分：HTTP 未分类 route 默认拒绝、WebSocket 未知 event 默认拒绝、Secure Cookie、登录限流、`next` URL 校验、企业静态路径 containment、生产错误脱敏和依赖锁定。SEC-1A 的详细决策见 [ADR SEC-1A](../decisions/ADR-SEC-1A-SUPER-ADMIN-CAPABILITY-GOVERNANCE-2026-07.md)。

### 4.3 DATA-1：新生产数据一致性与 migration 基础设计

- repository 接口。
- schema version。
- migration history。
- SQLite `busy_timeout`、索引和约束复核。
- 新生产数据完整性报告与受控 reconciliation 机制。
- 临时数据库 dry-run、备份和回滚测试。

DATA-1 服务于全新数据库和未来新版本 migration，不导入旧生产数据，不创建旧 owner map 修复任务，也不直接修改任何生产数据库。

### 4.4 Production Baseline 恢复演练

- 使用 Fresh Install Bootstrap 创建的全新基线数据核对 executed backup manifest。
- 在隔离副本中做 restore rehearsal。
- 验证 SQLite、JSON、assets / output、env 和启动链路。
- 记录人工 rollback 决策点与恢复时间。

旧生产已有 backup 只保留历史证据，不作为新基线恢复输入。新基线 backup 不等于 restore 已完成；restore rehearsal 通过后，还必须完成 OPS-3B 仓库实现及隔离环境 apply / switch / health / rollback / restore 演练，才能批准 Production Baseline。网页 Update Center 由 OPS-3C 后续独立实施，不是首次生产部署前置条件。

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

1. Manifest v2 Release builder/verifier、fixed CP314 和首个 clean-Windows immutable Candidate 已完成批准范围；不包含 activation。
2. 完成 DATA-1 与 Fresh Install Bootstrap，并在 clean Windows 上完成全新安装/初始化验收。
3. 收口 P0/ARCH-3/PERF-1/OBS-1、browser/provider 门禁。
4. 使用新基线数据完成 backup / restore rehearsal。
5. 完成 OPS-3B 仓库实现。
6. 使用 Fresh Install Bootstrap 建立的全新隔离数据，在干净 Windows 环境完成 apply / switch / health / rollback / restore rehearsal。
7. 项目负责人批准 Production Baseline。
8. 在生产设备 Greenfield 部署 Production Baseline。
9. 后续正式 Release 进入新生产版本迭代，首次真实 OPS-3B 执行只能由项目负责人在生产设备本地执行。
10. OPS-3C / Update Center 在 Production Baseline 后单独评估和实施，不是首次生产部署前置条件。

`prepare-upgrade` 只生成 plan。OPS-3B 不用于旧生产原地升级；其仓库实现和隔离演练是 Production Baseline 前置门禁，但不构成生产执行。OPS-3 / OPS-4 不得被描述为当前已实现；网页端未来也只能调用白名单、计划驱动、可审计的 OPS API，不能执行任意 shell。

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
| Fresh Install Bootstrap | 目标 Schema、mandatory audit、首个 super_admin、本机交互和重复执行拒绝设计通过；不得复用 SEC-1B2 的现有 admin 前提。 |
| OPS-3B repository implementation | 不可变 Release、Manifest v2、DATA-1、Fresh Install Bootstrap、正式 backup、restore rehearsal、migration compatibility 和 Runtime lifecycle 验证已经完成；不使用旧生产数据。 |
| Production Baseline 批准 | 使用 Fresh Install Bootstrap 建立的全新隔离数据完成 release validation、data-check 以及 OPS-3B apply / switch / health / rollback / restore 演练；旧生产 warning 不作为输入。 |
| OPS-3B 首次真实生产执行 | Greenfield 新生产已经部署，且项目负责人在生产设备本地对后续正式 Release 另行执行；不得用于旧生产。 |
| OPS-3C / Update Center | Production Baseline 后单独设计、实现和验证；不是首次生产部署前置条件。 |
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
