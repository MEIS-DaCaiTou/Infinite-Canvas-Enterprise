# Infinite Canvas Enterprise 当前架构

更新时间：2026-10-11

本文只描述当前运行架构与已确定的演进边界。实现状态以 [docs/CURRENT_PROJECT_STATUS.md](docs/CURRENT_PROJECT_STATUS.md) 为准，未来顺序以 [开发路线图](docs/roadmap/DEVELOPMENT-ROADMAP-2026-2027.md) 为准。

## 1. 当前形态

当前是面向 Windows 单机/LAN 部署的模块化单体：

```text
Browser / LAN users
        |
        | HTTP + WebSocket
        v
Enterprise Gateway (0.0.0.0:8000)
  auth / permission / audit / admin / proxy
        |
        | user context, loopback only
        v
Canvas Application (127.0.0.1:3001)
  canvas / workflow / provider integration / static UI
        |
        +-- SQLite enterprise database
        +-- canvas/conversation/task JSON and metadata
        +-- asset/output files

Runtime Supervisor
  immutable Release + current pointer
  independent process ownership and health
  bounded restart/backoff and durable logs
```

这不是 PostgreSQL、多 Worker、共享对象存储或多节点高可用架构。`gateway` 与 `canvas application` 是同一产品内的两个进程；“Upstream”一词在代码里仍可能作为历史进程角色名出现，不表示产品继续依赖外部上游迭代。

专业企业服务器、私有化服务器和云服务器生产部署是已确认的长期产品目标。当前 Windows 单机/LAN 是已实现形态；Linux 运行兼容、标准服务管理、容器或其他服务器交付尚未完成验证，不能从 Python 源码的存在推导已可生产部署。

## 2. 主要模块

| 模块 | 当前职责 | 主要入口 |
| --- | --- | --- |
| Gateway | 登录、Cookie/JWT、请求和事件授权、HTML/响应治理、代理、管理入口 | `enterprise/gateway.py` |
| Interceptors/Policies | 路由分类、所有权过滤、功能开关、审计触发 | `enterprise/interceptors.py`，后续迁移到领域 Policy |
| Enterprise data | 用户、角色、归属、审计、版本化 migration/backup/restore | `enterprise/db.py`，`enterprise/migrations/` |
| Canvas application | 画布、工作流、模型调用、静态前端和原有业务 API | `main.py`，`static/` |
| Task journal | 两类画布任务持久回执基础 | `enterprise/canvas_task_journal.py` |
| Runtime | launcher、supervisor、health、ownership、state/log | `enterprise/runtime/` |
| Release/update | Manifest v2、资产校验、prepare、pointer switch、rollback foundation | `enterprise/release/`，`enterprise/ops/update/`，`enterprise/update_api.py` |
| Enterprise UI | 登录、管理后台、个人中心、更新中心 | `enterprise-static/` |

Code Wiki 提供更细的文件、类和函数导航：[docs/code-wiki/README.md](docs/code-wiki/README.md)。

## 3. 安全与权限边界

- 对外仅暴露 Gateway；`:3001` 必须绑定 loopback。
- UI 隐藏不是权限控制，API、WebSocket、后台任务和资源访问必须服务端授权。
- 普通用户对未知 owner、未知路由和未知事件应默认拒绝。
- 超级管理员能力是显式授权，不由普通管理员身份隐式继承。
- Cookie、Origin/Host、登录跳转、静态文件路径和代理目标均需独立校验。
- 数据库约束/RLS（后续 PostgreSQL）是纵深防御；业务授权仍负责返回稳定的产品错误和审计信息。

SEC-P0 已通过 PR #119 合并，#111 已关闭；后续加固与管理员操作 403 仍需按精确治理状态回归。不能放宽授权来消除错误提示，也不能以已有角色表宣称所有权限场景均已验收。

## 4. 数据与存储

### 当前事实源

- 企业结构化数据：SQLite。
- 画布、对话和部分任务：文件/JSON 与 SQLite 映射并存。
- 图片、视频和输出：文件系统保存字节，数据库/JSON 保存路径和归属。
- 配置、Runtime 状态、日志和 Release 分属 `CONFIG_ROOT`、`STATE_ROOT`、`LOG_ROOT`、`INSTALL_ROOT/releases`。

### 固定不变量

- 数据从创建时就具有 owner/org/project 语义；不能依赖后补归属。
- 大型资源字节不进入普通业务数据库事务。
- schema 变化必须带版本、迁移、验证和恢复计划。
- 画布引用资源 ID/版本，不长期写死绝对磁盘路径。
- 任务和费用是可审计事实，不以进程内内存作为唯一状态。

### 近期缺口

DATA-MVP-1 与 UPDATE-DATA-1 已通过 PR #120/#121 复核和接入主线，PR #130 补齐旧库先备份再登记保护。新增表仍须验证准确来源、迁移步骤、数据保留与失败恢复；基础引擎通过不等于全部客户结构兼容。

文件/JSON、数据库和审计有不同状态，持久格式同样要版本化。两类任务回执不等于统一任务平台、费用账本和对账。

## 5. Runtime 与健康

Runtime Supervisor 分别管理 Gateway 和 Canvas application，并持久化运行状态、日志、进程 identity 和 generation。存活、就绪与业务健康的语义必须分开：

- liveness：进程/事件循环是否能响应，不访问外部 Provider。
- readiness：实例是否可接收业务流量。
- dependency health：数据库、Canvas application、Provider 等依赖状态。

短暂依赖失败应进入 degraded，不得直接导致 Gateway 破坏性重启。真实进程退出才进入带退避的恢复。主要修复已通过 PR #108 合并；真实 Windows 服务、安装副本回调和客户使用是不同证据层级。

## 6. Release 与在线更新

主线已有不可变 Release、Manifest v2、准备、数据迁移/恢复、一次确认和准确路由检查。正式 10.1 来自维护线，是 09.9 同数据库结构的后台维护包，不是 main 全量发布；两台设备成功反馈与剩余限制见 [CURRENT](docs/CURRENT_PROJECT_STATUS.md)。

本轮统一开发基线接回 `ice_096_security_schema_v2` 登记、v2 snapshot 和构建模式。默认未来构建生成与正式 09.9/10.1 同源的 30 对象/schema v2 证据；Greenfield 按已验证包内 evidence 选择受支持的 v1/v2 初始化并验证元数据/账本/结构，固定入口、密码和 pointer-last 保护保留。普通启动不隐式迁移旧库，28 对象历史变体不默认开放；历史资产须从冻结 refs 重建，不能用当前源码的旧 VERSION 标记伪造旧包。

主要缺口是统一安装维护、更新器接管/自身更新、跨重启自动多跳及任务/业务写入隔离。遵循 [统一交付 ADR](docs/decisions/ADR-DELIVERY-001-UNIFIED-INSTALL-UPDATE-LIFECYCLE-2026-10.md)。下面是目标完整流程，不声称每一步都已落地。

C5 开发分支新增 [经验证的目标更新执行器接管](docs/ops/VERIFIED-UPDATER-HANDOFF-2026-10-11.md)：纯读取契约独立声明控制器协议、worker 协议和引擎能力版本；完整包及持久计划核验后，目标代码/目标 Python 运行既有单跳事务，数据和状态仍归同一安装。无契约的不可变旧包沿用来源引擎，有但不可验证的契约拒绝交接；不弱化进程 lease、Job 独立性或恢复阻断。它不是原生 EXE 替换或自动多跳，也不扩展未知 Schema 的迁移授权。Windows 执行路径留在现有平台交付/Runtime 边界，不增加核心业务的桌面或注册表依赖。

目标单机更新事务：

```text
authorize
  -> check compatibility
  -> download and verify immutable assets
  -> notify users / stop accepting long tasks
  -> drain or checkpoint tasks
  -> backup database + business metadata + config
  -> apply schema migration and verify
  -> switch Release pointer
  -> start and health-check
  -> commit success
     or restore data + pointer and report recovery state
```

单跳已有持久作业和恢复查看基础，多跳协调器仍待实施。网页、固定 EXE、安装器和恢复界面必须共用引擎：Python 承担业务/迁移，C# 仅做系统交互，安装器编排。

#151/#152 已将归属缓存清理、实例标准卸载、同 Release 保留数据重装和持久恢复合入 main；完整 GUI、跨版本重装及长期维护闭环仍未完成。C4 [发布目录工程记录](docs/ops/UPDATE-CATALOG-PAGINATION-2026-10-11.md) 在独立分支将 v1/v2 元数据读取共用到分页目录：临时内存缓存按仓库/凭据身份隔离，每次 HTTP 条件核验全部页面，读取失败不作为升级事实源。路线缓存仅用于不可变声明的页面预览，准备和执行仍重新核验；不新增业务数据库、Windows 核心依赖或缓存 TTL 政策。

失败恢复应在开放业务写入前完成；已经接受新数据后不能还原旧快照。PostgreSQL 及多节点有独立排空、备份/恢复和发布协议，不照搬 SQLite 文件替换。

## 7. 目标演进

任务顺序只在 [唯一路线图](docs/roadmap/DEVELOPMENT-ROADMAP-2026-2027.md) 维护。

| 已确定角色 | 数据目标 | 实现边界 |
| --- | --- | --- |
| 长期保留单机版 | SQLite 业务数据与本地素材 | 不是多节点共享库 |
| 团队服务端 | PostgreSQL＋受管理存储 | 当前客户仍为 SQLite，产品迁移单独验证 |
| 员工桌面客户端 | 服务端业务事实；本地 SQLite 缓存/设置 | 尚未交付，不自动给每个员工装服务器 |

本地与企业服务器/云端部署复用业务领域模型、API、服务端权限契约和稳定资源身份；员工端消费同一业务契约，不复制业务系统。Windows Registry、Job Object、KnownFolder 和桌面交互留在平台适配层；业务核心不新增固定盘符或必须由桌面启动的依赖。

服务器运行能力随正式工作包建立：先评估 Linux 真实依赖与阻碍，再落实配置外置、无交互启动/停止、健康检查、日志、权限/网络边界及可重复部署。公开入口须核验 TLS、可信反代、网络隔离、访问限制、身份/密钥与审计。跨企业采用共享 SaaS、每客户独立部署还是混合形态尚未确定；部门 Owner 隔离不能替代企业租户边界。

单企业未来 1—2 年的设计目标为 500 名以上员工、200 名以上同时活跃创作；不是现有容量或 200 个同时付费请求的承诺。后续使用 100/200/300 活跃用户的混合负载，观察 API/WebSocket、画布保存、AI 受理与查询、数据库写等待、素材读写和队列积压，再按瓶颈选择 PostgreSQL、独立 Worker、受管理文件/对象存储、传输缓存或多实例协调。高可用按业务可靠性目标演进；RPO/RTO、预算、云供应商及拓扑仍待负责人确认。不预设微服务、Docker、Kubernetes 或 Redis 为前置目标。

持久任务/Provider Attempt/回执/费用/审计、事务与版本冲突、Repository 和 Storage Adapter、格式迁移及失败恢复随 B13/B14/B15/B16/B17、N29/N34/N37 的对应实施授权一并落实。容量和服务器要求不改变当前阶段 3 顺序，也不豁免客户数据与更新恢复门禁。Vue 3＋TypeScript 是局部试做方向，不表示已迁移；桌面框架仍须比较验证。

模块化原则是按业务域逐步提取 Policy、Application Service、Repository、Provider Adapter 和 Storage Adapter；不做一次性重写，也不继续把新业务规则堆入 `gateway.py` 或 `interceptors.py`。

## 8. 历史来源边界

项目保留 `hero8152/Infinite-Canvas@2026.07.6` 的来源归属和历史审计。本项目已决定冻结来源基线，后续不再要求同步；`main.py`、`static/`、`workflows/` 等都可以在明确任务、测试和发布迁移计划下演进。`docs/upstream/` 仅作历史证据，不是当前开发限制。

## 9. 尚未实现

统一新装/更新/修复/保留数据卸载、长期更新器接管、自动多跳、完整通知/任务与写入隔离、统一任务/费用、CAS/员工桌面客户端、PostgreSQL/HA、SSO/目录/Agent 与可选远程诊断仍未完整交付。已实现迁移/恢复基础不再笼统写成未实现；具体范围见项目状态。
