# Infinite Canvas Enterprise 文档索引与事实源

更新时间：2026-07-20
最后一次代码事实核对基线：`main@240f6a2b93268a415cddc3c9af9951f334c8e4e1`

当前 repository HEAD：以 GitHub `main` 分支为准；PR #80 已完成 ENV-1B0 / DOC-2 / DOC-2A，PR #81 已合并并完成 ENV-1B1A，PR #82 已合并并完成 ENV-1B2P（core `true`、dependency/archive `false`、`production_approved=false`）。ENV-1B1B 的 PathRoots / current-release 实现在当前 Draft PR 分支，尚未进入 `main`。

本索引用于避免当前事实、目标架构、历史实施记录和未来规划相互覆盖。新任务应先读取当前事实源，再按任务域读取 ADR 和专项文档。

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
| ENV-1B1B 路径根与版本指针 | [ENV-1B1B PathRoots 与 Current Release 实施记录](./env/ENV-1B1B-PATH-ROOTS-AND-CURRENT-RELEASE-IMPLEMENTATION-2026-07.md) | 当前 Draft PR：核心路径迁移和严格 pointer 原语，不等于 activation 或完整只读 APP_ROOT |
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

ADR 的 `Accepted` 只表示决策冻结，不表示对应能力已经实现或生产已经采用。ADR-OPS-007 已冻结 Greenfield 全新生产路线，但新生产尚未部署，Fresh Install Bootstrap 尚未实现，旧生产也未因该决策停止或删除。

## 专项参考

- Architecture：[architecture/](./architecture/)
- ENV：ADR-ENV-001 至 ADR-ENV-005 已由 PR #80 冻结；ENV-1B1A 已由 PR #81 合并，ENV-1B2P 已由 PR #82 合并；ENV-1B1B 是当前 Draft PR 实施阶段，ENV-1B1C / 完整 ENV-1B2 均未开始。
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

历史文档中的 SHA、PR 状态和当时的未实现边界只描述其记录时点。当前状态始终以 `docs/CURRENT_PROJECT_STATUS.md` 为准。

## 维护规则

1. 当前事实只在唯一事实源中完整描述，其它文档链接引用。
2. 历史文档不重写原始结论；被替代时在顶部增加 `Superseded by`。
3. 规划文档必须明确标注未实现，不得用完成时态描述未来能力。
4. 每个实现 PR 同步 CURRENT_PROJECT_STATUS、对应路线和测试 README。
5. 每个 ADR 记录状态、事实基线、实施状态、后果和重新评估条件。
6. 文档不得包含 secret、本机绝对路径、生产数据或临时 runtime 证据路径。
7. 当前 main 前进后，旧 SHA 可以作为历史基线保留，但不能继续标为当前 main。
