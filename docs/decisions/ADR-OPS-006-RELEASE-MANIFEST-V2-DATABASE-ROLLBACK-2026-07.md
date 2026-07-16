# ADR-OPS-006：Release Manifest v2 与数据库回滚

- 状态：Accepted
- 决策日期：2026-07-16
- 事实基线：`main@396cccc68d63bd16393a2cb72d24e4a48fcf47cb`
- 实施状态：仅决策；Manifest v2、OPS-3B、restore 和 rollback 尚未实现

## 背景

OPS-3A 已实现严格的 `ops-release-manifest-v1`、可信 GitHub Release provider、安全下载、staging 和非执行 prepare plan。v1 使用精确字段集合，不应为了 ENV-1 运行时证据而放宽现有解析语义。

版本目录可回切不等于数据库可以回滚。新代码如果已经执行不兼容 migration，直接切回旧代码可能造成二次故障或数据误读。

## Manifest 决策

1. `ops-release-manifest-v1` 的字段和现有安全语义保持不变。
2. ENV-1 后新增独立、严格的 `ops-release-manifest-v2`。
3. v2 采用新的 schema version、资产名、模型、解析器和测试；未知或缺失字段继续 fail closed。
4. v2 至少绑定：

- 应用归档文件名、大小和 SHA-256。
- runtime manifest 和 Python ABI。
- dependency lock 和 wheelhouse manifest。
- CycloneDX JSON SBOM。
- 第三方许可证清单。
- 上游 commit / tree / VERSION 和企业 commit / tree。
- 配置 schema、数据库 schema 和 migration IDs。
- migration compatibility 与 rollback classification。
- launcher / runtime 最低兼容版本。

本项目采用 CycloneDX JSON 作为首个正式 SBOM 格式，因为其组件、依赖关系、哈希和 vulnerability tooling 适合当前 Python Release 供应链；同时生成独立第三方许可证清单。SPDX 可以后续作为交换格式增加，但不构成 ENV-1 首个门禁。

## 数据库回滚分类

### A. 无 migration

新版本未修改持久数据 schema。健康失败时可以在确认进程、APP_ROOT 和状态证据后自动切回旧 Release。

### B. 向后兼容 migration

只有 migration 明确声明 backward-compatible，并通过旧版本读取、写入边界和回滚演练后，才允许自动切回旧 Release。

### C. 不兼容或不可逆 migration

禁止简单自动切回旧代码。必须恢复与计划绑定的正式备份，或进入人工恢复流程。OPS 报告必须明确数据库可能已改变和禁止重试条件。

未声明 compatibility、分类不一致或证据缺失时一律 fail closed。

## OPS-3B 前置门禁

- 不可变 APP_ROOT 和路径契约已落地。
- Manifest v2 与 runtime evidence 已验证。
- DATA-1 schema version、migration history 和兼容检查已完成。
- 正式 backup 与目标数据库绑定。
- restore rehearsal 和人工 recovery runbook 已完成。
- runtime supervisor lifecycle ACK 已验证，但不得据此推导数据库可回滚。

## 后果

- v1 的已审查安全边界不会被 ENV-1 扩展意外削弱。
- 自动 rollback 只适用于有证据证明安全的分类。
- OPS-3B 不能在 DATA-1 和 restore rehearsal 之前开始实施。
