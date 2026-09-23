# UPDATE-DATA-1：更新中心数据库迁移与恢复集成

更新时间：2026-09-22  
范围：Issue [#114](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/issues/114)；实现由 [PR #121](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/121) 交付。  
前置：DATA-MVP-1 foundation（PR #107）及独立复核（PR #120）。

## 1. 结论

UPDATE-DATA-1 将 DATA-MVP-1 已复核的 migration、backup、restore 原语接入 Update Center 的 prepare / execute / verify / rollback 作业。实现保留既有同 Schema 更新路径，并新增显式的版本化前向迁移路径。

本记录只说明仓库实现与隔离测试，不表示已经升级客户数据库、生成正式 Release、完成生产发布或批准 Production Baseline。项目负责人不要求独立 Windows 主机验收门禁；GitHub Actions、隔离故障注入和后续管理后台回归仍须分别记录。

## 2. 执行闭环

```text
prepare
  -> 校验 Manifest v2 / inventory / archive
  -> 读取 source + target 数据库证据
  -> 绑定当前数据库 schema 身份、迁移注册表和目标 schema
  -> 持久化不可变 database_update plan

execute
  -> 重读 Release、pointer、数据库和迁移计划
  -> MIGRATING：一致性备份 + 事务迁移 + 目标 schema 校验
  -> 持久化 database-result.json
  -> RESTARTING：expected-current 切换 Release pointer
  -> VERIFYING：启动目标 Release 并检查健康
  -> SUCCEEDED：确认目标数据库版本

failure
  -> 目标启动/健康失败：停止目标 -> 恢复数据库 -> 恢复 pointer -> 启动并检查 source
  -> 可证明恢复：ROLLED_BACK
  -> 数据库、pointer 或 source 健康无法证明：RECOVERY_REQUIRED
```

## 3. 数据契约

Manifest v2 现在接受两类可执行数据库契约：

| 模式 | `migration_compatibility` | `rollback_classification` | 行为 |
| --- | --- | --- | --- |
| 同 Schema | `same-schema-no-migration` | `code-release-pointer` | 不写数据库；允许在 schema 不变时追加预置未来 migration registry |
| 版本化迁移 | `versioned-forward-migration` | `database-backup-restore` | 备份、按 registry 顺序迁移、校验；失败时恢复数据库与代码指针 |

迁移 Release 的 source 与 target 证据必须同时绑定：

- 当前数据库的 `schema_version` 与 `schema_objects_sha256`；
- 完整 migration registry 的 SHA-256 与有序 migration ID；
- 唯一 operation/job ID；
- 目标 schema 版本及 schema SHA-256；
- 迁移结果、备份 manifest SHA-256 与备份数据库 SHA-256。

同 Schema Release 只能在 schema 版本和对象哈希均不变时追加 registry，不能删除、重排或改写当前已知前缀。该桥接用于先发布迁移代码与注册表，再由后续 Release 声明数据库结构变化，避免让旧 Runtime 动态执行未经当前代码注册的迁移实现。

## 4. 持久状态与重复执行

- 新增 `MIGRATING` 与 `RECOVERY_REQUIRED` 作业状态。
- `database-result.json` 使用 create-only 写入并设置 64 KiB 上限；不记录绝对路径、凭据或数据库内容。
- 执行前重新计算数据库计划并与 prepare 阶段计划精确比较，拒绝 Release 证据、数据库 schema 或计划漂移。
- 全局更新 reservation 继续保证单个活动更新；同一终态 Job 不能再次执行。
- Worker 在 `MIGRATING`、`RESTARTING` 或 `VERIFYING` 中断时，保守落为 `RECOVERY_REQUIRED`，不能误记为普通 `FAILED`。

## 5. 故障语义

| 故障点 | 结果 |
| --- | --- |
| prepare 身份/契约不匹配 | 不进入执行，不修改数据库或 pointer |
| migration 校验失败且 DATA-MVP-1 已证明内部回退 | source 数据库保持原版本，source Runtime 恢复，Job `FAILED` |
| migration 后目标启动/健康失败 | 恢复数据库和 pointer，source 健康后 Job `ROLLED_BACK` |
| 数据库恢复、pointer 恢复或 source 健康无法证明 | Job `RECOVERY_REQUIRED`，禁止自动重试 |
| Worker 在迁移/切换/验证阶段异常退出 | Job `RECOVERY_REQUIRED`，等待诊断和明确恢复 |

`RECOVERY_REQUIRED` 是保护状态，不表示数据库已经损坏；它表示系统不能以现有证据证明代码、pointer 和数据库已经回到同一版本语义。

## 6. 验证记录

提交前隔离验证：

- `enterprise/tests/test_update_mvp_1.py`：`35 passed`。
- UPDATE + Manifest v2 + DATA 组合：`110 passed, 4 skipped`。
- `py_compile`：通过。
- `git diff --check`：通过。

覆盖成功迁移、迁移失败、目标启动失败、目标健康失败、数据库恢复失败、计划漂移、重复执行、同 Schema 路径和 Worker 中断状态。所有数据库、Release、备份和状态根均为临时 fixture；不读取或修改客户数据。

完整企业套件和 CP314 Runtime 专项以 PR #121 的最终 GitHub Actions 为准，不在检查完成前预写为通过。

## 7. 后续边界

本任务完成迁移执行引擎接线，但不等于在线升级产品体验已经完成。下一阶段仍需：

1. #115：隔离 apply / switch / health / rollback / restore 演练；
2. 面向用户的维护通知、任务排空、跨重启进度和恢复 UX；
3. 首个真实 schema-changing Release 的 migration step、fixture 与兼容范围审查；
4. 离线升级兜底和正式 Release 签名/不可变资产治理。

