# Infinite Canvas Enterprise 当前项目状态

更新时间：2026-09-28

## 1. 状态摘要

| 层级 | 当前事实 |
| --- | --- |
| GitHub 主线 | `origin/main@b80439fc81b2e1cd41a00421abefda2a0323525d`（本次核验快照）；PR #129 已合并，具备正式版/开发版更新通道选择的主线代码；主线已有 DATA-MVP-1、Runtime、SEC-P0 和更新中心迁移/恢复基础 |
| 正式客户过渡 Release | [`2026.09.6`](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/releases/tag/2026.09.6)，`ice-2026.09.6-8f65c5cd328f`，从准确 `09.5` 源版本同数据库结构升级；独立发布分支，不等于主线全部能力已部署 |
| 设备验证 | 测试设备的 `09.5→09.6` 更新作业成功，重开已有画布、图片显示和登录使用正常；此前客户设备 `09.4→09.5` 更新成功。两者不能互相替代，也不是所有客户数据库迁移批准 |
| 当前开发任务 | 以正式 09.6 安装副本验证下一跳迁移和回退；已发现正式 09.6 内置迁移清单为空，**不能直接在线执行未来新增的迁移步骤**。需要先交付不改数据库结构、预置已审查迁移步骤的代码过渡版，再执行改表升级；见 [09.6 第二跳核验](./ops/UPDATE-096-SECOND-HOP-2026-09.md) |
| 本地分支边界 | `codex/096-data-upgrade-20260928` 正在收敛旧库备份/登记/迁移/恢复代码和定向演练；尚未合并、发布或部署到客户设备 |

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

### PR #119 合并后主线具备

- 上游 HTTP 方法/路径显式登记，未知路由默认 404，静态资源不再按文件后缀放行。
- Cookie 写请求同源校验，WebSocket 限定同源、固定路径、固定客户端消息及已知服务端事件。
- 登录限流、安全的 `next` 跳转、HTTPS `Secure` Cookie、POST 登出和企业静态目录 containment。

以上属于 #111 的已合并实现；测试和审查通过不等于正式 Release 或生产部署批准。

### PR #120、#121 合并后主线具备

- DATA-MVP-1 的迁移、备份、恢复基础已完成独立复核，结果见 [#109 记录](./data/DATA-MVP-1-INDEPENDENT-REVIEW-2026-09.md)。
- Update Center 可针对受 Manifest v2、当前数据库身份和不可变计划约束的版本化前向迁移，执行备份、迁移、目标健康验证与失败恢复；既有同 Schema 升级路径保留。
- 数据库、Release 指针或源版本健康无法证明一致时，持久化 `RECOVERY_REQUIRED`，不自动重试。迁移事务已提交但结果返回前异常时，不会在目标 Schema 上启动旧版本。

这些是仓库与 CI 层面的能力；尚无首个真实 schema-changing 正式 Release，也未对客户数据执行此路径。

### 已发布但不属于通用主线结论

客户 `2026.09.4` 热修是在 `2026.08.5-ee4281022d01` 上的定点修复。随后准确 `09.5` 客户线发布了同 Schema 的 `09.6` 过渡版；测试设备已完成在线升级、画布/图片/登录基本回归。这些现场事实不自动覆盖其它源版本、真实改表升级、全新安装或多节点环境。

## 3. 关键缺口

1. **安全后续**：SEC-P0 已进入主线；可信反向代理/TLS 配置、分布式限流与策略模块化仍属于后续加固，不阻断在线升级体验开发。
2. **数据升级验收**：#109、#114 已合并；#115 以临时数据的成功/失败/恢复定向测试收口，不设置干净设备门禁。正式 09.6 的 `DEFAULT_MIGRATIONS` 为空，下一版本的新迁移步骤不能由现装 09.6 更新器执行；需要安全的代码过渡版及正式迁移目标包。测试 fixture 不能当作客户升级批准。
3. **在线升级体验**：#115 的升级与恢复定向验证已合并；面向全体用户的维护通知、任务排空、跨重启进度和完整失败恢复 UX 仍待实现。`RECOVERY_REQUIRED` 后必须有经核验的人工恢复与解除阻断流程，不能靠删除状态文件再次升级。
4. **部门与任务**：组织/部门/项目模型、部门级 Provider 凭据、费用账本、统一持久任务和对账尚未形成。
5. **资源与桌面**：尚无完整 CAS 资源层、分层缓存和正式桌面壳；浏览器不能替代 D/E 盘选择、后台下载与断点续传。
6. **规模化**：当前仍是 SQLite + 单机文件 + 单写入者，不是 PostgreSQL、多 Worker、共享对象存储或高可用。
7. **企业集成**：SSO 身份关联、SCIM/目录、MCP/Agent 委托授权均未完整实现。

## 4. 当前任务与依赖

| Issue | 任务 | 所属阶段 | 前置/说明 |
| --- | --- | --- | --- |
| [#111](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/issues/111) | SEC-P0 请求与事件默认拒绝、浏览器安全边界 | 1 安全修复 | PR #119 已合并 |
| [#109](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/issues/109) | DATA-MVP-1 独立复核 | 2 数据升级 | PR #120 已合并，Issue 已关闭 |
| [#114](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/issues/114) | 将 migration/restore 接入更新中心 | 2 数据升级 | PR #121 已合并，Issue 已关闭；不等于生产发布 |
| [#115](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/issues/115) | OPS-3B apply/switch/health/rollback 定向验证 | 3 在线升级 | PR #124 已合并，Issue 已关闭；不设干净设备、独立 Windows 用户或真实跨进程演练门禁 |
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

安全修复和数据升级基础实现已进入主线，正式 09.6 的同库结构在线升级已在测试设备通过基本回归；当前先闭合 09.6 与主线迁移能力的实际交付路径，再继续第三阶段维护通知、任务控制与进度恢复。阶段转换不表示客户改表迁移已获批准。

## 6. 不变量

- PostgreSQL 是后续团队/高可用形态的事实源；SQLite 继续服务单机形态，但不作为多 Worker 共享数据库。
- 图片/视频字节不写入业务数据库事务；数据库保存元数据、归属、哈希和状态。
- 更新必须先备份、迁移、校验，再切换；失败恢复必须覆盖代码、数据库和版本指针。
- 管理员触发升级不等于绕过权限；只有明确授权的超级管理员可以启动系统更新。
- Provider 已受理但本地未知结果必须保留 `UNKNOWN/RECONCILING`，不能伪装成失败或成功。
- 桌面壳是本项目的正式组成部分，负责可选磁盘、容量策略、后台下载、断点续传和本地工具集成；Web 仍保留浏览器缓存和服务端资源优化。
- 项目负责人已明确取消独立 Windows 主机、干净用户环境及真实跨进程演练门禁；定向自动化测试、现有 GitHub Actions 和必要人工回归仍是合并证据，证据范围不得夸大。

## 7. 下一步

1. 完成 [09.6 第二跳核验](./ops/UPDATE-096-SECOND-HOP-2026-09.md) 中的源/目标兼容矩阵：从准确正式 09.6 三资产复核源数据库结构、迁移清单、主线 Schema 差异和发布构建器约束。
2. 先制作兼容 09.6 的**同库结构代码过渡版**，预置经过审查的首个真实迁移步骤；用 09.6 安装副本证明可准备、切换、启动和失败回退。再制作独立的数据库迁移目标包，验证备份、迁移、目标健康与恢复。两跳均需完整 Manifest v2 三资产与各自准确源版本声明，版本号在构建时确定。
3. 在前两步验收并发布前，不建议现装 09.6 客户点击任何改表更新；大规模部门/任务业务表开发继续排在可靠升级路径之后。继续维护通知、任务控制与跨重启进度；不额外设置干净 Windows 主机门禁或无理由重跑 PR 全套门禁。
