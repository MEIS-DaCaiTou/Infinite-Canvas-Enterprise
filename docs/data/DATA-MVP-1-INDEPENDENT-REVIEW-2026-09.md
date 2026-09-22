# DATA-MVP-1 独立复核记录

日期：2026-09-22

范围：Issue #109；基线为已合并 PR #107 的 DATA-MVP-1 foundation，并在合并 PR #119 后的 `origin/main@8cdb3c7b7399dbb144dbd828fc2ad876c79ae64a` 上复核。

## 1. 结论

`ACCEPT_WITH_FIX`：版本化 SQLite migration/backup/restore foundation 的执行模型合理；在补齐恢复时的预期 manifest SHA-256 绑定后，可以作为 #114 Update Center 集成的基础。

- `DATA_MVP_1_repository_implementation_independently_accepted=true`
- `Update_Center_database_migration_integrated=false`
- `Update_Center_database_restore_integrated=false`
- `customer_database_touched=false`
- `production_release_approved=false`

本结论只接受基础原语，不批准生产迁移，不放宽当前 Update Center 的同 Schema/no-migration 门禁。

## 2. 已复核不变量

1. metadata 与 ledger 必须完整、连续且与 Schema/ledger SHA-256 一致；部分状态 fail closed。
2. registry 只能由连续的 `N -> N+1` 步骤组成；已应用 migration ID/checksum 必须与 registry 一致。
3. 所有步骤、业务数据修改、ledger 和 state 在同一个 `BEGIN EXCLUSIVE` 事务中提交；任一步失败整体回滚。
4. 迁移前备份使用 SQLite backup API，并绑定数据库、Schema、ledger、integrity 与 foreign-key 结果。
5. 目标启动/健康失败后的恢复必须同时满足 expected-current 数据库 SHA-256 与迁移时记录的 expected-manifest SHA-256；不能接受另一份自洽的 manifest/backup 对。
6. 并发迁移只允许一个计划提交；持有旧计划的调用方在独占事务内复核源身份后拒绝。
7. 已迁移状态的重复执行返回 `DATA_MIGRATION_NOT_REQUIRED`；恢复后复用相同 operation ID 返回 `DATA_BACKUP_ALREADY_EXISTS`，不覆盖历史备份。
8. `os.replace()` 前失败不改变当前数据库；替换后目录同步失败明确返回 `database_may_have_changed=true`、`reread_required=true`。

## 3. 复核中发现并修正的问题

原实现会校验 manifest 内声明的 backup SHA-256 与实际备份一致，但恢复接口没有要求调用方传入迁移时记录的 manifest SHA-256。这样在 manifest 与备份被成对替换为另一份自洽备份时，单纯的内部一致性校验无法证明它仍是本次迁移创建的备份。

修正：`restore_database_backup()` 新增强制参数 `expected_backup_manifest_sha256`；在解析 manifest 和替换数据库前，先将 manifest 文件与迁移结果中保存的 SHA-256 精确比对。`finalize_release_database_validation()` 固定传入 `migration_result.backup.manifest_sha256`。新增成对替换测试证明错误备份被拒绝且迁移后数据库保持不变。

## 4. 隔离验证

全部用例使用 pytest 临时目录和临时 SQLite 数据库，不连接客户数据库、不启动客户 Runtime、不访问外部 Provider。

定点命令：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
py -3.11 -m pytest -q enterprise/tests/test_data_mvp_1.py
```

定点结果：`16 passed`。

覆盖项：成功迁移、步骤失败整体回滚、禁止 migration callback 自行提交、备份损坏拒绝、manifest/backup 成对替换拒绝、目标启动/健康失败恢复、expected-current 并发变化拒绝、并发迁移一胜一拒绝、重复执行拒绝、replace 前失败和 replace 后不确定状态。

完整企业套件：`950 passed, 10 skipped, 8 warnings in 449.72s`。警告为既有 FastAPI `on_event` 弃用提示和测试夹具 JWT 短密钥提示；本轮没有测试失败。GitHub Actions 结果仍以对应实现 PR 为准；测试通过不等于 Release 或生产批准。

## 5. #114 集成约束

- Update Job 必须持久化 migration plan、registry SHA-256、目标 Schema SHA-256、backup manifest SHA-256、post-migration database SHA-256 和 operation ID。
- migration/restore 只能在 Runtime 已受控停止、数据库 sidecar 不存在且更新作业持有互斥锁时执行。
- 目标启动或健康失败时，先停止失败目标，再按 expected-current + expected-manifest 恢复数据库，随后恢复源 Release 指针与生命周期。
- 恢复失败或 replace 后状态不确定时必须进入 `recovery_required`，禁止自动重试覆盖。
- 现有同 Schema/no-migration 路径必须保持兼容；只有 Release Manifest 明确声明并通过计划验证时才进入迁移分支。
