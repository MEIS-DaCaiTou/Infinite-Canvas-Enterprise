# Infinite Canvas Enterprise 当前项目状态

更新时间：2026-09-21

## 1. 状态摘要

| 层级 | 当前事实 |
| --- | --- |
| GitHub 主线 | `origin/main@8ba6befdf2e6737823634b53327dc6e98f7bbdae`，已合并 DATA-MVP-1 foundation（PR #107）与 Runtime 主线收敛（PR #108） |
| 当前实施分支 | `codex/sec-p0-browser-boundaries`，处理 [#111](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/issues/111)；未合并前不属于 `main` |
| 最近主线审查 | [PR #108](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/108) 已于 2026-09-21 合并，merge commit 为 `8ba6befdf2e6737823634b53327dc6e98f7bbdae`；合并前两项 Windows GitHub Actions 均 SUCCESS |
| 客户定点 Release | `2026.09.4@a0d1ccf`，仅适用于从 `2026.08.5-ee4281022d01` 原位升级的 Runtime 热修 |
| 生产结论 | 已确认一台客户设备升级后恢复正常；不是通用 Production Baseline，不代表 PR #108 已部署 |

固定 SHA 是本次核验快照。开始新任务时仍须 `git fetch origin --prune` 并重新确认 `origin/main`、PR 和 Release 状态。

## 2. 当前已经具备的能力

### 主线已具备

- Enterprise Gateway + loopback Canvas application 的双进程拓扑。
- 登录、固定角色治理、所有权隔离、审计和管理后台基础能力。
- Windows Runtime Supervisor、进程身份、受控启停、日志和状态文件。
- 不可变 Release、`current-release.json` 指针、Manifest v2 校验和最小更新作业。
- SQLite schema version、确定性 migration、一致性备份与 restore foundation。
- GitHub Actions 的 Windows 企业测试与 CP314 Runtime 可靠性检查。

### PR #108 合并后主线具备

- 独立存活探针与 readiness 边界。
- 短暂健康失败降级而非破坏性重启。
- 重启退避、启动宽限、单次探针和阻塞工作线程隔离。
- 两类画布任务的持久回执基础。

这些能力已进入代码主线，但尚未因此自动成为正式 Release、客户部署或通用 Production Baseline。

### 仅在当前安全分支实施、尚未进入主线

- 上游 HTTP 方法/路径显式登记，未知路由默认 404，静态资源不再按文件后缀放行。
- Cookie 写请求同源校验，WebSocket 限定同源、固定路径、固定客户端消息及已知服务端事件。
- 登录限流、安全的 `next` 跳转、HTTPS `Secure` Cookie、POST 登出和企业静态目录 containment。

以上属于 #111 的在审实现；只有经测试、PR 审查并合并后才能写成 `main` 已实现。

### 已发布但不属于通用主线结论

客户 `2026.09.4` 热修是在 `2026.08.5-ee4281022d01` 上的定点修复。现场监测支持“短暂失败降级、不破坏性重启”的策略，客户设备已恢复在线更新能力；该结果不自动覆盖其它源版本、全新安装或多节点环境。

## 3. 关键缺口

1. **安全**：未知 HTTP 路由/WebSocket 事件默认拒绝、静态路径穿越和浏览器请求边界仍须收口。
2. **数据升级**：DATA-MVP-1 仍需独立复核，并接入更新中心的 prepare/apply/restore 流程。
3. **在线升级体验**：缺少面向全体用户的维护通知、排空、跨重启进度、数据库迁移状态和失败恢复 UX。
4. **部门与任务**：组织/部门/项目模型、部门级 Provider 凭据、费用账本、统一持久任务和对账尚未形成。
5. **资源与桌面**：尚无完整 CAS 资源层、分层缓存和正式桌面壳；浏览器不能替代 D/E 盘选择、后台下载与断点续传。
6. **规模化**：当前仍是 SQLite + 单机文件 + 单写入者，不是 PostgreSQL、多 Worker、共享对象存储或高可用。
7. **企业集成**：SSO 身份关联、SCIM/目录、MCP/Agent 委托授权均未完整实现。

## 4. 当前任务与依赖

| Issue | 任务 | 所属阶段 | 前置/说明 |
| --- | --- | --- | --- |
| [#111](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/issues/111) | SEC-P0 请求与事件默认拒绝、浏览器安全边界 | 1 安全修复 | 发布阻断项 |
| [#109](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/issues/109) | DATA-MVP-1 独立复核 | 2 数据升级 | 先确认 foundation |
| [#114](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/issues/114) | 将 migration/restore 接入更新中心 | 2 数据升级 | 依赖 #109 |
| [#115](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/issues/115) | OPS-3B apply/switch/health/rollback 演练 | 3 在线升级 | 依赖 #114；不设独立 Windows 主机门禁 |
| [#110](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/issues/110) | 持久任务恢复、未知结果对账与幂等 | 4 部门与任务 | 部门账本与 Provider 接入的基础 |
| [#113](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/issues/113) | 浏览器回归与真实 Provider 成功链路 | 4 部门与任务 | 与真实供应商闭环共同验证 |
| [#112](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/issues/112) | 可观测性与负载基线 | 横向能力 | 从阶段 1 起逐步补齐 |
| [#116](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/issues/116) | Gateway/interceptors 策略边界拆分 | 横向能力 | 随功能按域渐进拆分，不做大爆炸重写 |
| [#117](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/issues/117) | 签名安装器 Gate B | 发布配套 | 条件任务，不阻断普通功能开发 |

部门治理、资源缓存/桌面壳、PostgreSQL/HA、SSO/MCP 需要在对应阶段再拆分为可执行 Issue；不得越过数据升级和在线升级阶段直接写业务表。

## 5. 固定开发顺序

```text
安全修复
  -> 数据升级能力
  -> 在线升级体验
  -> 部门与任务
  -> 资源缓存与桌面壳
  -> PostgreSQL 及高可用
  -> 企业集成
```

当前处于“第一阶段安全修复”阶段。PR #108 已完成 Runtime 主线收敛，但不等于安全阶段、数据阶段或在线升级体验阶段全部结束。

## 6. 不变量

- PostgreSQL 是后续团队/高可用形态的事实源；SQLite 继续服务单机形态，但不作为多 Worker 共享数据库。
- 图片/视频字节不写入业务数据库事务；数据库保存元数据、归属、哈希和状态。
- 更新必须先备份、迁移、校验，再切换；失败恢复必须覆盖代码、数据库和版本指针。
- 管理员触发升级不等于绕过权限；只有明确授权的超级管理员可以启动系统更新。
- Provider 已受理但本地未知结果必须保留 `UNKNOWN/RECONCILING`，不能伪装成失败或成功。
- 桌面壳是本项目的正式组成部分，负责可选磁盘、容量策略、后台下载、断点续传和本地工具集成；Web 仍保留浏览器缓存和服务端资源优化。
- 项目负责人已明确取消独立 Windows 主机验收门禁；GitHub Actions、可复现实验和必要人工回归仍是合并证据。

## 7. 下一步

1. 完成 #111 的聚焦/全量测试、独立安全审查和 PR 审查；不得直接发布未合并分支。
2. #111 合并后独立复核 #109 DATA-MVP-1 foundation。
3. 在 #109 结论基础上完成 #114，将 migration/restore 接入更新中心。
4. 只有 #109、#114 完成后，才进入管理后台在线升级体验；部门与任务业务表继续保持阻断。
