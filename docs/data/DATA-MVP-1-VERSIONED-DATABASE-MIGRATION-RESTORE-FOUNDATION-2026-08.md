# DATA-MVP-1：版本化数据库迁移与恢复基础

更新时间：2026-08-25

## 1. 当前结论

DATA-MVP-1 在仓库中建立了面向未来 SQLite Schema 演进的最小基础：显式 Schema 版本、确定性 migration registry、调用方事务内顺序迁移、一致性备份、迁移后校验，以及目标版本启动或健康失败后的数据库恢复接口。

本记录随实现 Draft PR 提交，仍等待独立复核：

- `DATA_MVP_1_repository_implementation_present=true`
- `DATA_MVP_1_repository_implementation_independently_accepted=false`
- `versioned_SQLite_migration_foundation=true`
- `database_backup_restore_foundation=true`
- `Update_Center_database_migration_integrated=false`
- `Update_Center_database_restore_integrated=false`
- `OPS_3B_started=false`
- `production_touched=false`

## 2. 固定执行模型

未来调用方必须显式提供目标版本、完整 registry、目标 Schema SHA-256、operation ID 和 expected-current 数据库身份。基础原语不在普通 Gateway 启动时自动迁移，也不被当前 Update Center 隐式调用。

```text
inspect exact metadata and ledger
→ plan a contiguous ordered migration path
→ create and verify a SQLite-consistent backup
→ BEGIN EXCLUSIVE
→ apply each registered step
→ validate each step
→ update ledger and schema fingerprint
→ integrity / foreign-key / target-schema validation
→ COMMIT
→ target Release start and health (future integrator)
   ├─ healthy: retain migrated database
   └─ start/health failed: verify backup and expected-current identity
      → stage exact backup bytes
      → atomic replace
      → directory sync or explicit uncertain-state error
```

迁移步骤必须是严格的 `N → N+1`，registry 必须从 baseline 连续排列。已应用 ledger 的 migration ID 和 checksum 必须继续匹配 registry；缺口、重复、降级、checksum 漂移、部分元数据或目标 Schema 不一致均 fail closed。

## 3. 数据与恢复边界

- Greenfield Fresh Install 直接创建当前 Schema 后，在同一调用方事务中写入 baseline metadata；不会回放 SEC-1B1、SEC-1F0 或 SEC-1B2 历史 migration，也不会生成历史 activation event。
- 现有数据库只能通过显式 bootstrap API 加入版本 ledger，并且加入前的完整 Schema fingerprint 必须与调用方给出的 SHA-256 精确相同。
- 备份使用 SQLite backup API，不复制活动 WAL；源数据库在备份前后必须保持相同文件 SHA-256 和大小。备份 manifest 绑定源/备份 SHA-256、Schema version、Schema fingerprint、ledger fingerprint、integrity check 和 foreign-key 结果。
- 所有 migration 在同一个 `BEGIN EXCLUSIVE` 事务中执行。任一步异常或验证失败都会 rollback Schema、业务数据、ledger 和 state。
- restore 只接受经过 manifest 验证的备份，并要求当前数据库仍等于该 migration result 记录的 post-migration SHA-256。并发变化时拒绝覆盖。
- `os.replace()` 前失败保留当前数据库；replace 后目录同步失败返回 `database_may_have_changed=true` 和 `reread_required=true`。

## 4. 公开接口

实现位于 `enterprise/migrations/versioned.py`：

| 接口 | 职责 |
| --- | --- |
| `initialize_schema_metadata_in_transaction()` | 在调用方现有事务中直接创建 baseline metadata/ledger |
| `bootstrap_existing_schema_metadata()` | 用精确 Schema SHA-256 显式登记既有数据库 |
| `validate_registry()` / `plan_migrations()` | 验证 registry 并形成连续、确定的迁移计划 |
| `create_database_backup()` / `verify_database_backup()` | 创建、绑定并离线复核一致性备份 |
| `apply_versioned_migrations()` | 备份后在单个独占事务中执行和校验迁移 |
| `restore_database_backup()` | expected-current 门禁下原子恢复数据库 |
| `finalize_release_database_validation()` | 为未来 Release start/health 集成提供 keep-or-restore 决策接口 |

Release Manifest v2 的 database snapshot 新增严格成组的 `schema_version`、`schema_objects_sha256`、`migration_registry_sha256` 和 `versioned_migration_ids`。历史没有这组字段的 v2 fixture 仍可验证；只出现部分新字段或内部 SHA 不一致会被拒绝。

## 5. 隔离验证

测试只使用仓库外临时 SQLite 数据库和脱敏 fixture，覆盖：

- baseline metadata 创建、部分状态拒绝和既有 Schema 精确 bootstrap；
- registry 顺序、缺口、checksum 与确定性 identity；
- 旧 Schema 到新 Schema 的事务迁移及既有用户/业务数据保留；
- 多步 migration 中断后的 Schema、数据、ledger 全回滚；
- source backup manifest、SQLite integrity、foreign keys 和 SHA-256 绑定；
- target start failure / health failure 后恢复旧 Schema 和原数据；
- backup tamper、并发数据库变化、replace 失败和 post-replace sync uncertain state；
- Greenfield installer、Manifest v2、历史 SEC migration 的兼容回归。

当前 Draft 候选的开发侧结果：DATA-MVP-1 focused `13 passed`；DATA/INSTALL/Manifest/UPDATE/RELEASE/current-release/USER-GOV relevant regression `211 passed / 4 skipped`；历史 SEC-1B1、SEC-1F0、SEC-1B2 direct scripts 均通过；OPS runner 与 OPS-3A direct scripts 通过；完整 `enterprise/tests` 为 `877 passed / 10 skipped / 0 failed`（固定 CPython 3.11.9，未切换解释器）。仓库外 evidence bundle 只记录这些真实结果，不包含数据库、凭据、Token、Cookie、生产路径或用户数据。

## 6. 明确未实现

本阶段不直接修改页面升级流程，不执行生产 migration/restore，不支持旧生产数据导入，不实现 PostgreSQL、Redis、队列、HA、通用 migration 平台、自动 reconciliation、完整 OPS-3B、动态 RBAC、安装器或签名。当前 Update Center 继续保持同 Schema / no-migration fail-closed 契约，直到后续任务单独完成集成和隔离升级/恢复验收。
