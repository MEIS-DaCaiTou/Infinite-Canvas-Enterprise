# Infinite Canvas Enterprise 当前项目状态

更新时间：2026-07-10

## 1. ARCH-2A 核对基线与运行事实

- 企业版仓库：`MEIS-DaCaiTou/Infinite-Canvas-Enterprise`
- ARCH-2A 代码核对基线（PR #69 合并后）：`a095ce2eb9ef9afda356cb6f20b6c38851f52b1d`
- SEC-1A 代码核对基线：`dcb6629569246f58a2eda358d1073693376d6fa9`
- 当前上游版本：`2026.07.6`
- 固定上游目标 commit：`hero8152/Infinite-Canvas@f1dd6834a72f3e7ff8340be05a84347d931e9cb9`
- 当前运行架构：浏览器 / 局域网用户 -> `enterprise/gateway.py:8000` -> `main.py:3001` -> 上游 `data / assets / output / static / workflows`
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

当前生产仍是 Windows + bat + bundled Python + SQLite + JSON + 本地文件系统。当前项目还不是完整企业协作平台，也不是分布式、高可用、多服务器、零停机升级或 Docker-ready 平台。

ARCH-2A 已完成当前架构评估与演进方向文档同步，由 PR #70 承载。完成 ARCH-2A 只代表架构共识和路线同步完成；P0 安全整改、模块化、migration、restore、Docker、PostgreSQL 等均未实施。详细评估见 [ARCH-2A：整体架构评估与演进方向](./architecture/ARCH-2A-ARCHITECTURE-ASSESSMENT-AND-EVOLUTION-2026-07.md)。

SEC-1A 已完成 ADR 决策，由 PR #71 承载；不代表任何超级管理员或安全能力已经实现。ADR 定义超级管理员、Capability 和高风险操作治理方向；当前代码和生产仍是 `is_admin` 普通用户 / 管理员二级模型，没有 `super_admin`、`role`、`auth_version`、Step-up Authentication、Operation Token 或专用安全审计表。详细决策见 [ADR SEC-1A](./decisions/ADR-SEC-1A-SUPER-ADMIN-CAPABILITY-GOVERNANCE-2026-07.md)。

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
| ARCH-2A | 已完成，PR #70 | 当前架构评估、目标原则、架构决策表和 P0 / P1 / P2 / P3 演进方向同步；不代表任何整改已实施。 |
| SEC-1A | 已完成 ADR 决策，PR #71 | 定义 user / admin / super_admin、Capability、L0–L3、Step-up、bootstrap 和高风险治理；不代表任何超级管理员或安全能力已经实现。 |

## 4. 当前能力矩阵摘要

| 能力域 | 当前状态 |
| --- | --- |
| 登录 / JWT Cookie | 已落地，企业网关统一校验。 |
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
| OPS 工具 | OPS-2A / OPS-2B 已进入 main，提供 inventory / check-data / backup / validate-release / prepare-upgrade 和 Windows wrapper；不代表生产已升级，也不代表 apply-upgrade / restore / rollback、Docker / 1Panel 或 PostgreSQL 已实现。 |
| 超级管理员 / Capability | 仅 SEC-1A ADR 已决策；当前未实现，生产仍使用 `is_admin` 二级模型。 |

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

ARCH-2A 文档同步已完成。项目负责人已确认继续采用“上游主应用 + enterprise gateway + enterprise data + OPS”的模块化单体路线，不立即微服务化。SEC-1A 已完成角色与高风险治理 ADR，当前下一项是 SEC-1B1 角色 schema 与会话版本基础；首次 super_admin bootstrap 必须后置到 SEC-1F0 最小强制安全审计之后。

每个 P0 安全事项必须使用独立 Issue、独立分支和独立 Draft PR，不将全部 P0 项目打包到一个大 PR。

下一步顺序：

1. SEC-1B1：独立实现并用临时数据库验证 `role`、`auth_version`、migration、JWT 当前状态加载和旧 Token 撤销；不激活生产 migration，不开放在线角色写入，不执行首次 bootstrap。
2. SEC-1F0：最小 `security_audit_events`、append-only 写入、bootstrap / role change / break-glass、敏感字段禁记、L3 / bootstrap fail closed 和临时数据库测试。
3. SEC-1B2：仅在 SEC-1F0 可用后激活 migration 并实施本机首次 super_admin bootstrap，依次进入 `UNINITIALIZED`、`ACTIVE`。
4. 按独立 Issue / Draft PR 继续 SEC-1C Capability 门禁、SEC-1D Step-up、SEC-1E UI、SEC-1F 完整审计和 SEC-1U 升级安全收口。
5. 设计 DATA-1 数据一致性、schema version、migration history 和人工 owner reconciliation 基础。
6. 推进 backup restore rehearsal；在 restore / rollback 未完成演练前，不接入网页 apply-upgrade。
7. 推进 OBS-1 / OPS-L1 日志与可观测性基础。
8. 逐域推进 ARCH-3 policy 模块化和 PERF-1 真流式代理 / 性能基线。
9. OPS-D1 Docker / 1Panel 单机生产化后置到安全、数据和恢复基础稳定之后。
10. PostgreSQL、Redis、MinIO / S3、多实例和多服务器属于长期 P3 目标。

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

从最新 main 开始新任务；`a095ce2eb9ef9afda356cb6f20b6c38851f52b1d` 仅作为 ARCH-2A 代码核对基线。若 main 已前进，先读取最新 `PROJECT_SCOPE_LOCK.md`、本文件、ARCH-2A 评估和最近 PR，再开始新任务。

每个新任务必须：

- 新建独立分支。
- 只处理当前 Issue。
- 创建 Draft PR。
- 明确测试结果。
- 有前端 / 权限行为时等待项目负责人浏览器验收。
- 不提交运行时数据或敏感配置。
