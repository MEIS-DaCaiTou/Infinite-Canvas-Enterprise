# SEC-1B2 生产 Activation Runbook

## 适用边界

本 runbook 是项目负责人于生产 Windows 主机本地执行的人工清单。它不是自动部署脚本，不提供远程运行，不授权 Codex/ChatGPT 访问生产，也不代表已完成 activation、bootstrap、restore、rollback 或升级。

不要把生产 `enterprise.env`、`API/.env`、`enterprise.db`、`history.json`、assets、output、backup、report、Token、Cookie、密码或 API Key 复制到开发环境。

## A. 执行前

1. 核对已合并的 main commit、服务版本和本次维护窗口。
2. 若本次 role/auth 仍为 LEGACY，通知所有用户：既有登录 token 将失效，执行后必须重新登录。若 status 已显示 ROLE_AUTH_READY，只能按 plan 的 `session_impact` 执行 target-only 影响确认。
3. 停止 enterprise gateway 和 upstream 服务；确认没有剩余应用进程或活动 SQLite 写入。
4. 仅用 bundled Python 直接运行 runner 文件并执行 status：

```powershell
& <AppRoot>\python\python.exe <ToolsRoot>\tools\sec_1b2_local_runner.py status --database <EnterpriseDb>
```

5. status 必须显示 LEGACY/UNINITIALIZED 或允许的 READY/UNINITIALIZED resume，且没有 PARTIAL 或 RECOVERY_REQUIRED。
6. 运行受控 journal 准备。它会要求输入绑定数据库文件名的确认短语；若发现 `-wal` / `-shm`，停止并人工复核，绝不删除 sidecar 或执行手工 SQLite SQL：

```powershell
& <AppRoot>\python\python.exe <ToolsRoot>\tools\sec_1b2_local_runner.py prepare-journal `
  --database <EnterpriseDb> `
  --report-output <NewJournalPreparationReportJson> `
  --confirm-service-stopped
```

7. 仅在 preparation report 显示 `journal_mode_after=delete`、success 且没有待核验状态时，重新创建一次正式 `backup --execute`。不要使用 prepare 前、旧 dry-run 或其它数据库的 manifest。
8. 人工复核新 manifest：`dry_run=false`、`status=pass`/`success`、`sqlite_backup_status=success`、`source_database_relative_path=data/enterprise.db`、source 与 backup 的 size/SHA-256、`source_database_journal_mode=delete` 可验证，且没有 critical warning。
9. 执行 inventory 与 check-data；若出现 critical，停止本次工作并复核。
10. 明确选择一个现有 active admin，双人核对其 user ID 与精确 username；不能选择普通用户、disabled admin 或自动选择账号。

## B. 生成并复核 Plan

```powershell
& <AppRoot>\python\python.exe <ToolsRoot>\tools\sec_1b2_local_runner.py plan `
  --database <EnterpriseDb> `
  --backup-manifest <ExecutedBackupManifest> `
  --target-user-id <ExistingAdminUserId> `
  --target-username <ExistingAdminUsername> `
  --actor-label <LocalOperatorLabel> `
  --reason <MaintenanceReason> `
  --plan-output <NewPlanJson>
```

人工复核 plan：

- plan hash、有效期、数据库与 source fingerprint、manifest SHA-256；
- target ID、username、`target_role_before=admin`；
- `role_auth_state_before`、`audit_state_before`、`lifecycle_state_before=UNINITIALIZED`；
- actions 只包含必要的 foundation activation、role/auth migration、bootstrap；
- plan 不含密码、hash、Token、Cookie、env 或完整用户对象。

plan 后不得启动服务、修改数据库、修改 target、替换 manifest 或修改 plan。任何变化都要求重新 plan。

## C. 本机 Execute

在服务保持停止的前提下，使用 plan 输出的精确 hash。不要将密码放在命令、环境变量、脚本或剪贴板持久记录中。

```powershell
& <AppRoot>\python\python.exe <ToolsRoot>\tools\sec_1b2_local_runner.py execute `
  --database <EnterpriseDb> `
  --plan <ReviewedPlanJson> `
  --expected-plan-hash <ReviewedPlanHash> `
  --backup-manifest <ExecutedBackupManifest> `
  --target-user-id <ExistingAdminUserId> `
  --target-username <ExistingAdminUsername> `
  --actor-label <LocalOperatorLabel> `
  --reason <MaintenanceReason> `
  --report-output <NewReportJson> `
  --confirm-service-stopped `
  --confirm-backup-reviewed `
  --confirm-session-impact-reviewed `
  --confirm-first-bootstrap
```

先按 reviewed plan 的 `session_impact` 确认影响范围：LEGACY 为 `all_existing_sessions`，READY bootstrap-only resume 为 `bootstrap_target_only`。runner 会交互读取该 selected admin 的当前密码，并要求输入绑定 operation ID、username 和该 session scope 的精确确认短语。没有 password、force、skip、repair、remote 或 break-glass 参数；不要尝试绕过。

## D. 执行后

1. status 必须显示 `ACTIVE`、ROLE_AUTH_READY、SECURITY_AUDIT_READY，且 exactly one active `super_admin`。
2. 核对 immutable marker 的 target 和 operation ID。
3. 核对同一 operation ID 下的 L3 audit：foundation（原先 MISSING 时）、role/auth migration（原先 LEGACY 时）、bootstrap。
4. 核对 target 已是 `super_admin`、auth_version 已额外递增；其他 user/admin 的角色与 owner 数据未改变。
5. 保存 report 和备份位置，不删除备份。
6. 启动应用；按 report 的 `session_impact` 验证旧 token 失效。LEGACY migration 必须验证所有用户重新登录；bootstrap-only resume 只验证 target 的旧 token 失效。
7. 验证 SEC-1C0 保护：admin 不能影响 `super_admin`，在线 role change 仍关闭。

## E. 失败处理

1. 不自动重试，不手工 ALTER，不手工 UPDATE role，不删 marker、不删 audit trigger。
2. 保持服务停止，保存 report 和 backup。
3. 根据 report 核对 `database_transaction_rolled_back`、`no_database_changes_committed`、`database_changes_committed`、`post_commit_verification_required` 与 `do_not_rerun_until_status_verified`。commit 后 verification/report failure 时不得重试，先运行 `status` 并按 report 和 stderr 确认已提交事实。
4. 不删除 backup，也不使用首次 bootstrap runner 处理 `RECOVERY_REQUIRED`。
5. 返回项目负责人和主对话复核；未来 break-glass 必须是单独任务和独立审批，不属于 SEC-1B2。
