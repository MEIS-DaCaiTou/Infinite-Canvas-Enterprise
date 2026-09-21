# Infinite Canvas Enterprise 当前架构

更新时间：2026-09-21

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
| Release/update | Manifest v2、资产校验、prepare、pointer switch、rollback foundation | `enterprise/release/`，`enterprise/update_api.py` |
| Enterprise UI | 登录、管理后台、个人中心、更新中心 | `enterprise-static/` |

Code Wiki 提供更细的文件、类和函数导航：[docs/code-wiki/README.md](docs/code-wiki/README.md)。

## 3. 安全与权限边界

- 对外仅暴露 Gateway；`:3001` 必须绑定 loopback。
- UI 隐藏不是权限控制，API、WebSocket、后台任务和资源访问必须服务端授权。
- 普通用户对未知 owner、未知路由和未知事件应默认拒绝。
- 超级管理员能力是显式授权，不由普通管理员身份隐式继承。
- Cookie、Origin/Host、登录跳转、静态文件路径和代理目标均需独立校验。
- 数据库约束/RLS（后续 PostgreSQL）是纵深防御；业务授权仍负责返回稳定的产品错误和审计信息。

当前安全缺口跟踪在 Issue #111；不得因为已有登录和角色表就宣称权限闭环完成。

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

DATA-MVP-1 已进入 `main`，但尚未完整接入更新中心。新增部门、账本和统一任务表之前，必须先完成数据升级能力。

## 5. Runtime 与健康

Runtime Supervisor 分别管理 Gateway 和 Canvas application，并持久化运行状态、日志、进程 identity 和 generation。存活、就绪与业务健康的语义必须分开：

- liveness：进程/事件循环是否能响应，不访问外部 Provider。
- readiness：实例是否可接收业务流量。
- dependency health：数据库、Canvas application、Provider 等依赖状态。

短暂依赖失败应进入 degraded，不得直接导致 Gateway 破坏性重启。真实进程退出才进入带退避的恢复。PR #108 中的收敛能力尚未合并时，仍属于分支事实。

## 6. Release 与在线更新

当前已具备不可变 Release、Manifest v2、资产哈希、prepare 和代码指针/健康回滚基础。当前缺口是数据迁移和用户体验没有形成完整闭环。

目标单机更新事务：

```text
authorize
  -> check compatibility
  -> notify users / stop accepting long tasks
  -> drain or checkpoint tasks
  -> download and verify immutable assets
  -> backup database + business metadata + config
  -> apply schema migration and verify
  -> switch Release pointer
  -> start and health-check
  -> commit success
     or restore data + pointer and report recovery state
```

浏览器关闭和服务重启不能丢失升级 Job。多节点滚动升级属于 PostgreSQL/HA 阶段，不复用单机指针切换作为完整方案。

## 7. 目标演进

架构沿既定顺序增量演进：

1. 收紧 Gateway/事件/资源安全边界。
2. 把数据库 migration/backup/restore 接入 Update Center。
3. 建立用户通知、维护态、跨重启进度和恢复 UX。
4. 在可升级 schema 上增加组织、部门、Provider 凭据、费用账本和持久任务。
5. 建立 CAS 资源层、Web/服务端分层缓存和可选择 D/E 盘的桌面壳。
6. 将团队/高可用形态迁到 PostgreSQL、多 Worker、共享对象存储和多节点发布。
7. 接入 OIDC/SAML、目录和复用统一授权语义的 MCP/Agent 接口。

模块化原则是按业务域逐步提取 Policy、Application Service、Repository、Provider Adapter 和 Storage Adapter；不做一次性重写，也不继续把新业务规则堆入 `gateway.py` 或 `interceptors.py`。

## 8. 历史来源边界

项目保留 `hero8152/Infinite-Canvas@2026.07.6` 的来源归属和历史审计。上游已停止维护，后续不再要求同步；`main.py`、`static/`、`workflows/` 等都可以在明确任务、测试和发布迁移计划下演进。`docs/upstream/` 仅作历史证据，不是当前开发限制。

## 9. 尚未实现

以下内容仍是目标而非当前事实：完整数据库在线迁移、维护通知和跨重启进度、统一持久任务/对账、部门费用治理、CAS/桌面缓存、PostgreSQL、多节点 HA、SSO、SCIM、MCP/Agent 委托授权。
