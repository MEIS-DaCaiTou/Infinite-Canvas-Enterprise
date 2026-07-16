# Infinite Canvas Enterprise 当前项目状态

更新时间：2026-07-16

## 1. 当前主线与运行事实

- 企业版仓库：`MEIS-DaCaiTou/Infinite-Canvas-Enterprise`
- `current_main`：以仓库 GitHub `main` HEAD 为准。
- `last_verified_code_baseline`：`396cccc68d63bd16393a2cb72d24e4a48fcf47cb`。
- DOC-2 / PR #80：仅同步文档，不改变运行时代码事实。
- OPS-3A：PR #77 已合并，merge commit `1430e2d7389c66d82d8f93d3c306451a22a51d3c`。
- STAB-1 / OPS-L1：PR #78 已合并，merge commit `a00a2fd2807b41a9fee3c267ee1116986b52fd7e`。
- Runtime service-host 启动修复：PR #79 已合并，merge commit `396cccc68d63bd16393a2cb72d24e4a48fcf47cb`。
- ARCH-2A 代码核对基线（PR #69 合并后）：`a095ce2eb9ef9afda356cb6f20b6c38851f52b1d`
- SEC-1A 代码核对基线：`dcb6629569246f58a2eda358d1073693376d6fa9`
- SEC-1B1 代码实现基线：`4432dd7af3898b0d9511d6add79f3e7de891d00f`
- SEC-1F0 代码实现基线：`7758a3356947802fab854081ff8f28a9099fe2c0`
- 当前上游版本：`2026.07.6`
- 固定上游目标 commit：`hero8152/Infinite-Canvas@f1dd6834a72f3e7ff8340be05a84347d931e9cb9`
- 当前仓库运行架构：本地 runtime supervisor -> 独立 upstream `main.py:3001` + gateway `enterprise/gateway.py:8000` -> 上游 `data / assets / output / static / workflows`
- U-1 / U-2 临时 worktree 已清理；后续任务从原主项目目录最新 `main` 新建分支。

## 2. 架构判断

当前系统的统一定位是“已投入生产的企业安全增强型单机模块化单体”。当前企业版适配“单机无限画布小规模企业多用户化”的阶段目标。第一阶段重点不是组织协作，而是：

- 普通用户隔离。
- owner 归属。
- 管理员兜底。
- 关键 API 拦截。
- 实时事件隔离。
- 任务历史隔离。
- 权限开关。
- 审计记录。

当前“上游主应用 + enterprise gateway + interceptors + enterprise DB 映射”仍是阶段性正确路线。长期风险是 `enterprise/interceptors.py` 继续中心化膨胀；后续新增策略应逐步模块化到 `enterprise/policies/`，再由 gateway / interceptors 编排。

当前生产事实仍按既有 Windows + bundled Python + SQLite + JSON + 本地文件系统边界描述。PR #78/#79 合并不代表生产已切换到新 supervisor。当前项目还不是完整企业协作平台，也不是分布式、高可用、多服务器、零停机升级或 Docker-ready 平台。

ARCH-2A 已完成当前架构评估与演进方向文档同步，由 PR #70 承载。完成 ARCH-2A 只代表架构共识和路线同步完成；P0 安全整改、模块化、migration、restore、Docker、PostgreSQL 等均未实施。详细评估见 [ARCH-2A：整体架构评估与演进方向](./architecture/ARCH-2A-ARCHITECTURE-ASSESSMENT-AND-EVOLUTION-2026-07.md)。

SEC-1A 已完成 ADR 决策，由 PR #71 承载；后续 SEC-1B1、SEC-1F0、SEC-1C0 和 SEC-1B2 已建立 role / auth_version、强制审计底层、过渡保护和受控首次 bootstrap。仓库支持 `super_admin` 角色与本机 activation 流程，但生产没有执行 activation、没有创建真实 super_admin；Capability、Step-up Authentication、Operation Token 和完整安全审计查询仍未实现。详细决策见 [ADR SEC-1A](./decisions/ADR-SEC-1A-SUPER-ADMIN-CAPABILITY-GOVERNANCE-2026-07.md)。

SEC-1B1 已完成仓库实现和临时数据库验证，由 PR #72 承载。该实现增加 role / auth_version schema 基础、显式 legacy migration inspect / plan / apply 和 JWT 当前数据库状态加载；不代表生产 migration 已激活，不代表 super_admin 已创建，也不代表 SEC-1C0 过渡保护、Capability 或 Step-up 已实现。生产数据库仍按 LEGACY 状态治理，SEC-1B2 维护窗口 activation 前不得调用 migration apply。

SEC-1F0 已完成仓库实现和临时数据库验证，由 PR #73 承载。该实现增加独立 `security_audit_events` Schema、显式 inspect / plan / apply、append-only trigger、mandatory writer、敏感字段拒绝和 fail-closed 异常；不代表生产审计 Schema 已激活，不代表现有管理操作已接入强制审计，也不代表 super_admin 已创建。生产仍为 LEGACY，详细边界见 [SEC-1F0 实施文档](./security/SEC-1F0-MANDATORY-SECURITY-AUDIT-IMPLEMENTATION-2026-07.md)。

SEC-1C0 已完成仓库实现和临时数据库验证，由 PR #74 承载。该实现增加首次 bootstrap 前的 actor / target 过渡矩阵、READY 敏感治理与 mandatory audit 原子提交、在线角色关闭、旧 mutator 防绕过、TEMP users 防护和最后 active super_admin helper；不代表 production migration 已激活，不代表 super_admin 已创建，也不代表 Capability、Step-up 或 Operation Token 已实现。生产仍为 LEGACY，详细边界见 [SEC-1C0 实施文档](./security/SEC-1C0-SUPER-ADMIN-TRANSITIONAL-PROTECTION-2026-07.md)。

SEC-1B2 已完成仓库实现和临时数据库验证，由 PR #75 承载。该实现增加本机受控 activation plan、正式备份 manifest 与数据库指纹门禁、`BEGIN EXCLUSIVE` 原子迁移、不可变 bootstrap marker、生命周期检查和首次本机 bootstrap runner；不代表生产 activation 已执行，不代表生产审计或 role/auth Schema 已激活，也不代表生产已创建 super_admin。生产仍为 LEGACY，详细边界见 [SEC-1B2 实施文档](./security/SEC-1B2-CONTROLLED-ACTIVATION-BOOTSTRAP-2026-07.md) 与 [SEC-1B2 受控 activation runbook](./runbooks/SEC-1B2-PRODUCTION-ACTIVATION-RUNBOOK-2026-07.md)。

## 3. 已完成任务一览

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| 3G-4A | 已完成，PR #34 | 上传资源隔离与上传资源 owner 治理。 |
| 3G-4B | 已完成，PR #38 | 素材库完整隔离与素材业务 owner 治理。 |
| 3G-5 | 已完成，PR #42 | WebSocket 广播隔离与实时事件 owner 治理。 |
| 3G-6 | 已完成，PR #46 | 异步任务历史 owner 隔离；外部 provider 成功链路仍需有 Key 后补验。 |
| 3G-7A | 已完成，PR #49 | 管理员权限开关最小版 + 审计。 |
| Angle / Enhance 上传解耦 | 已完成，PR #53 | ModelScope / cloud 模式不再依赖本地 Comfy `/api/upload` 成功。 |
| 3G-7B-1 | 已完成，PR #55 | 用户删除影响 dry-run 预览。 |
| 3G-7B-2 | 已完成，PR #56 | soft delete 语义收口、管理员安全保护、feature override 清理。 |
| 3G-7B-3 | 已完成，PR #58 | 成员管理搜索、筛选、排序、分页，默认隐藏已停用用户。 |
| U-1 | 已完成，PR #60 | 上游同步只读审计。 |
| U-2 | 已完成，PR #61 | 受控同步到上游 `2026.07.6` 并补企业兼容。 |
| U-2-F1 / U-2-F2 | 已完成，PR #62 | 文生图 / Enhance 刷新后历史丢失定位与云端 history type 一致性修复。 |
| DOC-1 | 已完成，PR #63 | 项目文档体系全量同步与 Agent 交接资料更新。 |
| OPS-0 / OPS-0A | 已完成，PR #64 | 生产环境只读盘点和生产治理优先级文档化。 |
| OPS-1 | 已完成，PR #65 | 生产备份、离线发布包、升级演练、回滚、数据库迁移与数据治理方案设计。 |
| ARCH-1 | 已完成，PR #66 | 企业架构蓝图、开发路线图、Docker / 1Panel 蓝图和 OPS 路线图。 |
| OPS-2A | 已完成，PR #67 | 生产运维工具套件第一版：inventory、check-data、backup、validate-release、prepare-upgrade；merge commit `7f8586ca90f74a8a172ff9ab2af390099c4cdbc5`。 |
| OPS-2B | 已完成，PR #69 | Windows 生产侧 dry-run / backup execute wrapper；merge commit `a095ce2eb9ef9afda356cb6f20b6c38851f52b1d`。 |
| OPS-3A | 已完成，PR #77，merge `1430e2d` | 可信发布源、严格 manifest v1、受限下载、Windows 安全 staging、证据绑定的非执行 online-update plan；合并不代表生产检查、下载、升级或服务操作已经执行。 |
| STAB-1 / OPS-L1 | 已完成，PR #78，merge `a00a2fd` | 本地 `3001` upstream / `8000` gateway 独立 supervisor、持久化脱敏日志、原子 runtime state、完整进程 identity、generation-bound lifecycle ACK、优雅 child shutdown、Windows Job Object 和 PyJWT 依赖声明。开发设备隔离验证不代表生产服务已切换或 Windows Service 已安装。 |
| Runtime startup hotfix | 已完成，PR #79，merge `396cccc` | 修复 child/host 直接执行时的标准库遮蔽、detached service-host import path 和启动早期脱敏诊断；不声称解决 CPython `0xC0000005` 根因。 |
| ARCH-2A | 已完成，PR #70 | 当前架构评估、目标原则、架构决策表和 P0 / P1 / P2 / P3 演进方向同步；不代表任何整改已实施。 |
| SEC-1A | 已完成 ADR 决策，PR #71 | 定义 user / admin / super_admin、Capability、L0–L3、Step-up、bootstrap 和高风险治理；不代表任何超级管理员或安全能力已经实现。 |
| SEC-1B1 | 仓库实现与临时数据库验证完成，PR #72 | role / auth_version、新旧 schema 兼容、显式 migration 基础和 JWT 当前状态加载；生产 migration 未激活。 |
| SEC-1F0 | 仓库实现与临时数据库验证完成，PR #73 | 最小强制安全审计 Schema、append-only writer、显式 migration、敏感字段拒绝和 fail closed；生产 Schema 未激活，在线操作未接线。 |
| SEC-1C0 | 仓库实现与临时数据库验证完成，PR #74 | 首次 bootstrap 前的 super_admin 过渡保护、READY 原子审计、在线角色关闭、最后 active super_admin 和 TEMP users 防绕过；生产 migration 未激活。 |
| SEC-1B2 | 仓库实现与临时数据库验证完成，PR #75 | 受控 activation plan、本机交互 runner、不可变 bootstrap marker、生命周期检查和原子首次 bootstrap；生产 activation 未执行。 |

## 4. 当前能力矩阵摘要

| 能力域 | 当前状态 |
| --- | --- |
| 登录 / JWT Cookie | SEC-1B1 已在仓库实现数据库当前状态 principal 和 auth_version 校验；生产 LEGACY schema 尚未激活版本撤销。 |
| 管理后台 | 已有成员管理、项目归属、画布归属、对话归属、操作日志、权限开关。 |
| 成员治理 | 已有启用 / 禁用、soft delete、delete-impact dry-run、feature override 清理、成员搜索 / 筛选 / 分页。 |
| 项目 / 画布 / 对话隔离 | 已按 owner 过滤；管理员可治理归属。 |
| 上传资源隔离 | 已按 `user_resource_map` 记录和鉴权。 |
| 素材库隔离 | library / category / item 业务 owner 已治理。 |
| 历史记录隔离 | `user_history_map` owner 过滤已落地；zimage / enhance / klein 云端 type 已一致。 |
| 异步任务隔离 | `user_task_map` / `user_canvas_task_map` owner 拦截基线已落地。 |
| WebSocket 隔离 | stats / pong 保留，敏感事件按 owner / task owner 过滤或合成。 |
| API / 工作流权限 | 已分类的高风险设置与功能已有 feature flag + user override + 审计；管理员 bypass 与未分类路由默认策略列入 P0 整改。 |
| 上游同步 | U-2 已受控同步到 `2026.07.6`，未直接 merge upstream。 |
| OPS / Runtime | OPS-2A / OPS-2B / OPS-3A、STAB-1 / OPS-L1 和 PR #79 hotfix 已进入 main。已有 `start/stop/restart/status/health`、独立角色恢复、持久日志、runtime state、完整 identity、ACK 和 Job Object。上述能力不代表生产已升级或切换，也不代表 apply-upgrade / restore / rollback、Windows Service、Docker / 1Panel 或 PostgreSQL 已实现。 |
| 超级管理员 / Capability | SEC-1B1 只建立固定 role 基础，不创建 super_admin，也不实现 Capability；生产仍使用现有 `is_admin` 数据。 |
| 强制安全审计 | SEC-1F0 已提供仓库底层和临时数据库证明；生产未建表，现有在线管理操作仍使用原 `usage_logs`，完整查询 / 导出 / 保留 / 归档未实现。 |

## 5. 当前人工确认

合并后最小浏览器确认已通过：

- `/api/app-info` 显示 `2026.07.6`。
- 登录页可打开。
- zimage / enhance / klein 页面可打开。
- user_a 云端生成后刷新历史仍在。
- user_b 仍看不到 user_a 历史。

U-2 项目负责人浏览器验收已通过，重点覆盖登录、普通用户管理后台拒绝、API 设置页新版推荐平台与 CLI 设置展示、权限边界、版本显示、Smart Canvas / Classic Canvas 基础路径、RunningHub / Angle / Enhance 相关入口和企业隔离核心路径。

OPS-2A / OPS-2B 生产侧人工确认：

- 项目负责人已在生产机本地执行 inventory、check-data 和 backup dry-run。
- 项目负责人已单独确认并人工执行正式 `backup --execute`，返回成功结果。
- 正式备份成功只证明该次备份命令成功，不代表 restore 已实现、恢复演练已完成或生产已经升级。
- 当前 `check-data` 仍为 warn，包含需要后续人工治理的 unowned、orphan map、missing file 等差异；当前没有自动修复，也不得据此直接删除或改写生产数据。

## 6. 后续任务队列

ARCH-2A、SEC-1A、SEC-1B1、SEC-1F0、SEC-1C0 和 SEC-1B2 仓库实现已完成。SEC-1B1、SEC-1F0、SEC-1C0 与 SEC-1B2 均不代表 production migration 已激活，也没有创建 super_admin；当前生产仍为 LEGACY。是否执行 SEC-1B2 activation 只能由项目负责人在受控维护窗口内按 runbook 人工决定，不能由仓库代码、startup 或网页入口自动触发。

每个 P0 安全事项必须使用独立 Issue、独立分支和独立 Draft PR，不将全部 P0 项目打包到一个大 PR。

当前正式路线以 `docs/roadmap/DEVELOPMENT-ROADMAP-2026-2027.md` 和 ENV / OPS ADR 为准：

1. ENV-1B0：ADR 与文档事实同步，本 PR 只处理文档。
2. ENV-1B1A：完整 APP_ROOT 写入审计与 static 构建期内容哈希。
3. ENV-1B2P：核心、依赖层和 archive provenance 分层证据。
4. ENV-1B1B / B1C：路径根、版本目录、current-release.json 和正式入口 fail closed。
5. ENV-1B2 / Manifest v2 / ENV-1B3：可重复 Runtime、SBOM、自检和干净 Windows 验证。
6. 发布首个不可变 Windows Release 后，实施 DATA-1、ARCH-3、PERF-1 / OBS-1。
7. restore rehearsal、数据库兼容分类和 Manifest v2 完成后，才进入 OPS-3B。
8. Linux 单服务器后置；PostgreSQL、对象存储、queue、Redis 和多实例按真实需求引入。

3G-8 浏览器级自动化回归、3G-6 外部 provider 成功链路补验和长期协作 ACL 仍保留，但不得挤占 P0 安全与数据一致性优先级。

## 7. 当前不进入主线的事项

- team / workspace / project_members / canvas_grants / asset_library_grants 实现。
- 用户共享、复杂 ACL、复杂 RBAC、部门权限。
- 每用户独立 API Key。
- SaaS 多租户。
- 计费。
- 插件市场 / 工作流市场。
- 大规模 UI 改版。
- 生产 `git pull`、直接覆盖升级、apply-upgrade、rollback、自动修复 owner map、删除生产数据。
- 模型质量、第三方中转站、Provider 2K/high 等非企业隔离主线问题。
- 物理文件 GC 或删除 `assets/` / `output/` / `history.json` / 数据库。

## 8. 禁止提交范围

不得提交：

- `assets/`
- `output/`
- `history.json`
- `data/`
- `data/enterprise.db` 或任何数据库文件
- `enterprise.env`
- `API/.env`
- `python/`
- Token / Cookie / API Key / 本地日志 / 缓存 / 运行时图片 / 上传文件

上游覆盖区 `main.py`、`static/`、`workflows/`、`API/`、`python/`、`VERSION` 默认不修改。只有在受控上游同步或明确 bugfix 任务中，才允许最小化修改并在 PR 中说明原因、风险、回滚方案和测试结果。

## 9. 后续 Agent 启动 Checklist

```powershell
git checkout main
git pull --ff-only origin main
git rev-parse HEAD
git status --short --untracked-files=all
```

从 GitHub 最新 `main` 开始新任务；`396cccc68d63bd16393a2cb72d24e4a48fcf47cb` 是 DOC-2 审计输入和最后一次代码事实核对基线，`a095ce2e` 只作为 ARCH-2A 历史核对基线。main 前进后先读取 `docs/README.md`、本文件、当前 ADR 和最近 PR。

每个新任务必须：

- 新建独立分支。
- 只处理当前 Issue。
- 创建 Draft PR。
- 明确测试结果。
- 有前端 / 权限行为时等待项目负责人浏览器验收。
- 不提交运行时数据或敏感配置。
