# Infinite Canvas Enterprise 当前架构

更新时间：2026-10-03

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

主线已有不可变 Release、Manifest v2、准备、数据迁移/恢复、一次确认和准确路由检查。客户维护线另行交付 09.9 与通用工具验收包，并非 main 全量发布。

主要缺口是统一安装维护、更新器接管/自身更新、跨重启自动多跳及任务/业务写入隔离。遵循 [统一交付 ADR](docs/decisions/ADR-DELIVERY-001-UNIFIED-INSTALL-UPDATE-LIFECYCLE-2026-10.md)。下面是目标完整流程，不声称每一步都已落地。

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

失败恢复应在开放业务写入前完成；已经接受新数据后不能还原旧快照。PostgreSQL 及多节点有独立排空、备份/恢复和发布协议，不照搬 SQLite 文件替换。

## 7. 目标演进

任务顺序只在 [唯一路线图](docs/roadmap/DEVELOPMENT-ROADMAP-2026-2027.md) 维护。

| 已确定角色 | 数据目标 | 实现边界 |
| --- | --- | --- |
| 长期保留单机版 | SQLite 业务数据与本地素材 | 不是多节点共享库 |
| 团队服务端 | PostgreSQL＋受管理存储 | 当前客户仍为 SQLite，产品迁移单独验证 |
| 员工桌面客户端 | 服务端业务事实；本地 SQLite 缓存/设置 | 尚未交付，不自动给每个员工装服务器 |

复用领域服务和存储接口，不复制三套业务。容量按写入等待、队列和延迟实测，不按用户数量猜测。Vue 3＋TypeScript 是局部试做方向，不表示已迁移；桌面框架仍须比较验证。

模块化原则是按业务域逐步提取 Policy、Application Service、Repository、Provider Adapter 和 Storage Adapter；不做一次性重写，也不继续把新业务规则堆入 `gateway.py` 或 `interceptors.py`。

## 8. 历史来源边界

项目保留 `hero8152/Infinite-Canvas@2026.07.6` 的来源归属和历史审计。本项目已决定冻结来源基线，后续不再要求同步；`main.py`、`static/`、`workflows/` 等都可以在明确任务、测试和发布迁移计划下演进。`docs/upstream/` 仅作历史证据，不是当前开发限制。

## 9. 尚未实现

统一新装/更新/修复/保留数据卸载、长期更新器接管、自动多跳、完整通知/任务与写入隔离、统一任务/费用、CAS/员工桌面客户端、PostgreSQL/HA、SSO/目录/Agent 与可选远程诊断仍未完整交付。已实现迁移/恢复基础不再笼统写成未实现；具体范围见项目状态。
