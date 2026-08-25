# Infinite Canvas Enterprise 文档索引与事实源

更新时间：2026-08-25
最后一次独立验证代码基线：`860a71004a181d5c48e217964176b7736dcf7025`（tree `6bfefc8a5d2861524498828436385d2568840555`）

`current_main` 是动态 GitHub 事实，必须在评审或新任务开始时查询 GitHub / `origin/main`，静态文档中的固定 SHA 不得被解释为永久当前值。USER-GOV-MVP-1 accepted Head `860a71004a181d5c48e217964176b7736dcf7025` 已通过独立复核，并由 PR #105 merge commit `4d68898fe6c7c5247013aeeee86b3024349e666d` 以相同 tree 合并。固定三角色治理不等于动态 RBAC、组织权限、Production Baseline、生产部署或 production approval。

本索引用于避免当前事实、目标架构、历史实施记录和未来规划相互覆盖。新任务应先读取当前事实源，再按任务域读取 ADR 和专项文档。

## 权威阅读顺序

1. [文档索引与事实源](./README.md)
2. [当前项目状态](./CURRENT_PROJECT_STATUS.md)
3. [当前架构](../ARCHITECTURE.md)
4. [开发路线图](./roadmap/DEVELOPMENT-ROADMAP-2026-2027.md)
5. 与任务域对应的 ADR、当前 implementation record 和 acceptance evidence
6. `AGENT_CONTEXT.md`、`HANDOVER.md`、`PROJECT_HANDOFF_FOR_NEW_AGENT.md` 等历史交接材料（仅作历史参考）

## 唯一事实源

| 主题 | 权威文档 | 维护规则 |
| --- | --- | --- |
| 当前实现和未实现边界 | [CURRENT_PROJECT_STATUS.md](./CURRENT_PROJECT_STATUS.md) | 每个实现 PR 合并后同步 |
| 当前运行架构摘要 | [../ARCHITECTURE.md](../ARCHITECTURE.md) | 只写当前拓扑和职责 |
| 中长期路线 | [roadmap/DEVELOPMENT-ROADMAP-2026-2027.md](./roadmap/DEVELOPMENT-ROADMAP-2026-2027.md) | 明确已完成、已决策未实施和规划 |
| OPS 路线 | [ops/OPS-ROADMAP-2026-07.md](./ops/OPS-ROADMAP-2026-07.md) | 不把 prepare 写成 apply |
| 生产部署路线 | [ADR-OPS-007](./decisions/ADR-OPS-007-GREENFIELD-PRODUCTION-BASELINE-AND-LEGACY-NON-MIGRATION-2026-07.md) | Greenfield 新生产与旧生产非迁移的权威决策 |
| ENV-1B1A 实施与写入审计 | [ENV-1B1A APP_ROOT 写入审计与 Static 构建](./env/ENV-1B1A-APP-ROOT-WRITE-AUDIT-AND-STATIC-BUILD-2026-07.md) | 区分 PR #81 已关闭的 static blocker 与后续未迁移写入 |
| ENV-1B2P Runtime 来源证据 | [ENV-1B2P Windows Runtime 分层来源证据](./env/ENV-1B2P-WINDOWS-RUNTIME-PROVENANCE-EVIDENCE-2026-07.md) | 独立记录 core / dependency / archive 结论并固定 production approval 为 false |
| ENV-1B2A 可复现 Runtime | [ENV-1B2A 可复现 Windows Runtime 实施记录](./env/ENV-1B2A-REPRODUCIBLE-WINDOWS-RUNTIME-IMPLEMENTATION-2026-07.md) | 官方 source、哈希锁、闭合 wheelhouse、双 clean build、SBOM、archive 与真实 B2 fixture；仍固定 production approval 为 false |
| ENV-1B2B Python 3.14 Runtime | [ENV-1B2B Python 3.14 Runtime 实施记录](./env/ENV-1B2B-PYTHON-314-RUNTIME-IMPLEMENTATION-2026-07.md) | 唯一 active policy 迁移到 CPython 3.14.6 / cp314；repository implementation 与 Runtime candidate 已独立验收 |
| OPS Release Manifest v2 | [OPS Release Manifest v2 实施记录](./ops/OPS-RELEASE-MANIFEST-V2-IMPLEMENTATION-2026-07.md) | detached canonical manifest、闭合 payload/archive inventory 与 portable identity；repository implementation 已独立验收，不含 activation/OPS-3B |
| ENV-1B3 Windows validation | [ENV-1B3 clean Windows validation and Release Candidate](./env/ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE-2026-07.md) | PR #90 已合并；Candidate 08 已通过独立 W01-W14 `14/0/0`，但不是 formal Release、activation 或 Production Baseline |
| ENV-1B3 最终验收收口 | [ENV-1B3 Final Acceptance / Closeout](./env/evidence/ENV-1B3-FINAL-ACCEPTANCE-CLOSEOUT-2026-08-05.md) | 固定 PR #90/main/Candidate/evidence 身份、开发与物理 Windows 证据边界及下一阶段交接 |
| UPDATE-MVP-1 | [最小安全在线升级与诊断实施记录](./ops/UPDATE-MVP-1-MINIMAL-SAFE-ONLINE-UPDATE-IMPLEMENTATION-2026-08.md) | 同 Schema/无 migration 的 Manifest v2 单跳更新、代码 Release 回滚与 bounded diagnostics；repository implementation 及隔离 Windows WU1/WU2 已独立接受，不是 OPS-3B、formal activation 或生产授权 |
| USER-GOV-MVP-1 | [固定三角色治理实施记录](./security/USER-GOV-MVP-1-FIXED-THREE-ROLE-GOVERNANCE-IMPLEMENTATION-2026-08.md) | 固定 user/admin/super_admin、super_admin-only 管理员治理与系统升级、原子审计和会话失效；repository implementation 已由 PR #105 合并并通过独立复核，不是动态 RBAC |
| INSTALL-UX-1 | [Signed One-Click Windows Installer 实施记录](./ops/INSTALL-UX-1-SIGNED-ONE-CLICK-WINDOWS-INSTALLER-IMPLEMENTATION-2026-08.md) | Gate A repository implementation 已由 PR #102 合并并独立验收；Gate B、新版本、正式签名、clean-Windows signed Setup 和公开安装器仍须单独批准 |
| ENV-1B1B 路径根与版本指针 | [ENV-1B1B PathRoots 与 Current Release 实施记录](./env/ENV-1B1B-PATH-ROOTS-AND-CURRENT-RELEASE-IMPLEMENTATION-2026-07.md) | 已合并：核心路径迁移和严格 pointer 原语，不等于 activation 或完整只读 APP_ROOT |
| ENV-1B1C Runtime 入口与自检 | [ENV-1B1C Runtime 入口与自检实施记录](./env/ENV-1B1C-RUNTIME-ENTRYPOINT-SELF-CHECK-IMPLEMENTATION-2026-07.md) | B1 已独立验收；B2 repository implementation 与 D1–D10 实现已通过独立代码审查 |
| ENV-1B1C-B2 portable lifecycle | [ENV-1B1C-B2 Portable Runtime Lifecycle 实施记录](./env/ENV-1B1C-B2-PORTABLE-RUNTIME-LIFECYCLE-IMPLEMENTATION-2026-07.md) | 固定 launcher、Release identity、STAB-1 integration 与 readiness 的实现和验证边界 |
| ENV-1B1C-B1 最终验收与收口 | [ENV-1B1C-B1 Final Acceptance / Closeout](./env/evidence/ENV-1B1C-B1-FINAL-ACCEPTANCE-CLOSEOUT-2026-07-27.md) | PR #84 合并后的独立验收决定、审查包摘要、测试矩阵和未实现边界 |
| ENV-1B1C-B1 实施报告 | [ENV-1B1C-B1 实施报告](./env/evidence/ENV-1B1C-B1-IMPLEMENTATION-REPORT.md) | B1 Draft 实施时点的完整 Codex 回报、测试和边界证据；历史措辞不表示当前状态 |
| ENV-1B1C-B1 R3 补正报告 | [ENV-1B1C-B1-R3 补正报告](./env/evidence/ENV-1B1C-B1-R3-CORRECTION-REPORT.md) | 独立复核九项纯契约 blocker 的修正、回归与边界证据 |
| ENV-1B1C-B1 R4 补正报告 | [ENV-1B1C-B1-R4 补正报告](./env/evidence/ENV-1B1C-B1-R4-CORRECTION-REPORT.md) | R3 第二轮独立复核后的纯契约修正；该历史时点仍等待新的独立复核，不进入 B2 |
| ENV-1B1C-B1 R5 补正报告 | [ENV-1B1C-B1-R5 补正报告](./env/evidence/ENV-1B1C-B1-R5-CORRECTION-REPORT.md) | R4 后纯契约信任链修正的历史时点证据 |
| ENV-1B1C-B1 R6 补正报告 | [ENV-1B1C-B1-R6 补正报告](./env/evidence/ENV-1B1C-B1-R6-CORRECTION-REPORT.md) | stable error、bounded ownership read 等修正的历史时点证据 |
| ENV-1B1C-B1 R7 补正报告 | [ENV-1B1C-B1-R7 补正报告](./env/evidence/ENV-1B1C-B1-R7-CORRECTION-REPORT.md) | bounded reader、post-replace uncertain-state 和 duplicate path 收口的历史时点证据 |
| 临时测试部署反馈 | [临时测试部署反馈](./ops/TEMPORARY-TEST-DEPLOYMENT-FEEDBACK-2026-07.md) | 仅记录不含敏感信息的兼容性反馈；不是生产操作 |
| 代码和数据边界 | [../CODE_BOUNDARIES.md](../CODE_BOUNDARIES.md) | 上游覆盖区和禁止提交范围 |
| 上游同步 | [upstream/SYNC_POLICY.md](./upstream/SYNC_POLICY.md) | 固定 commit、差异和回归 |
| 测试清单 | [../enterprise/tests/README.md](../enterprise/tests/README.md) | 与当前测试文件同步 |
| 文档审计 | [ops/DOC-2-DOCUMENT-INVENTORY-AND-FACT-AUDIT-2026-07.md](./ops/DOC-2-DOCUMENT-INVENTORY-AND-FACT-AUDIT-2026-07.md) | 记录分类、替代关系和处理结果 |

## 架构、ENV 与 OPS ADR

- [ADR-ENV-001：中期总体架构形态](./decisions/ADR-ENV-001-MODULAR-MONOLITH-MIDTERM-ARCHITECTURE-2026-07.md)
- [ADR-ENV-002：Windows Python 运行时与来源证据](./decisions/ADR-ENV-002-WINDOWS-PYTHON-RUNTIME-PROVENANCE-2026-07.md)
- [ADR-ENV-003：不可变 Release 与 static 缓存策略](./decisions/ADR-ENV-003-IMMUTABLE-RELEASE-STATIC-CACHE-2026-07.md)
- [ADR-ENV-004：路径根与版本目录](./decisions/ADR-ENV-004-PATH-ROOTS-AND-RELEASE-DIRECTORY-2026-07.md)
- [ADR-ENV-005：正式入口、自检和执行模式](./decisions/ADR-ENV-005-RUNTIME-ENTRYPOINT-SELF-CHECK-MODES-2026-07.md)
- [ADR-OPS-006：Release Manifest v2 与数据库回滚](./decisions/ADR-OPS-006-RELEASE-MANIFEST-V2-DATABASE-ROLLBACK-2026-07.md)
- [ADR-OPS-007：全新生产基线部署与旧生产非迁移](./decisions/ADR-OPS-007-GREENFIELD-PRODUCTION-BASELINE-AND-LEGACY-NON-MIGRATION-2026-07.md)（当前生产路线权威决策）
- [ADR SEC-1A：超级管理员与高风险治理](./decisions/ADR-SEC-1A-SUPER-ADMIN-CAPABILITY-GOVERNANCE-2026-07.md)

ADR 的 `Accepted` 只表示决策冻结，不表示对应能力已经实现或生产已经采用。ADR-OPS-007 已冻结 Greenfield 全新生产路线；Fresh Install Bootstrap repository implementation 已由 INSTALL-MVP-1 完成，但新生产尚未部署，旧生产也未因该决策停止或删除。

## 专项参考

- Architecture：[architecture/](./architecture/)
- ENV：ADR-ENV-001 至 ADR-ENV-005 已由 PR #80 冻结；ENV-1B1A 至 ENV-1B3 的已授权 repository/validation 阶段已分别合并。CPython 3.14.6 / cp314、OPS Release Manifest v2 与独立 clean-Windows Candidate 08 均已有对应证据，`ENV_1B2_completed=true`、`ENV_1B3_completed=true`。UPDATE-MVP-1、INSTALL-MVP-1、INSTALL-UX-1 Gate A 与 USER-GOV-MVP-1 repository implementation 均已完成相应批准范围。DATA-1 暂停，INSTALL-UX-1 Gate B、完整 activation、OPS-3B、Production Baseline 和 production approval 均未完成。
- OPS：[ops/](./ops/)
- Security：[security/](./security/)、[runbooks/](./runbooks/)
- Upstream：[upstream/](./upstream/)
- Deployment：[deployment/](./deployment/)
- Tests：[enterprise/tests/README.md](../enterprise/tests/README.md)

## Historical / Superseded

以下文档保留历史价值，但不再作为当前事实入口：

- `AGENT_CONTEXT.md`
- `HANDOVER.md`
- `PROJECT_HANDOFF_FOR_NEW_AGENT.md`
- `DEVELOPMENT_PLAN.md`
- `docs/decisions/ADR-0001-enterprise-gateway-over-upstream.md`
- `docs/decisions/ADR-current-architecture-and-next-stage.md`
- `docs/ops/*-TASK-2026-07.md`
- 生产盘点、上游同步、缺陷调查和测试日志等带日期的实施记录

历史文档（包括 B1 Implementation Report、R3–R7 Correction Reports 与 Candidate 01–07 过程记录）中的 SHA、Draft/等待验收措辞和当时的未实现边界只描述其记录时点。当前状态始终以 `docs/CURRENT_PROJECT_STATUS.md`、B1 Final Acceptance / Closeout 和 ENV-1B3 Final Acceptance / Closeout evidence 为准。

## 维护规则

1. 当前事实只在唯一事实源中完整描述，其它文档链接引用。
2. 历史文档不重写原始结论；被替代时在顶部增加 `Superseded by`。
3. 规划文档必须明确标注未实现，不得用完成时态描述未来能力。
4. 每个实现 PR 同步 CURRENT_PROJECT_STATUS、对应路线和测试 README。
5. 每个 ADR 记录状态、事实基线、实施状态、后果和重新评估条件。
6. 文档不得包含 secret、本机绝对路径、生产数据或临时 runtime 证据路径。
7. `current_main` 必须实时查询；静态文档不得把固定 SHA 表述为永久当前 main。
8. `docs/CURRENT_PROJECT_STATUS.md` 分别记录最后验证代码基线与最近一次 docs-only 收口；二者不得合并为一个字段。
9. docs-only merge 可以推进 main，但不会自动改变最后验证代码基线；旧 SHA 可以作为明确标注的历史或验证基线保留。
