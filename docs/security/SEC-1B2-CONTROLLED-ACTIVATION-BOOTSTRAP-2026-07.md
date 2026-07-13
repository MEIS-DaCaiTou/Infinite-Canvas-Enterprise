# SEC-1B2: 受控迁移激活与首次本机 Bootstrap

## 定位

SEC-1B2 为 SEC-1B1、SEC-1F0 和 SEC-1C0 提供一个仅限本机人工执行的受控 activation 路径。它建立代码、临时 SQLite rehearsal、只读 plan 和 local runner；不执行生产 migration，不创建生产 `super_admin`，也不接入网页、API、startup 或远程入口。

生产当前仍是 LEGACY：没有执行 role/auth migration，没有建立 `security_audit_events`，没有真实 `super_admin`，没有 bootstrap。合并本 PR 不改变这些事实。

## 安全模型

SEC-1B1 migration 只读取和写入 `main.users`，并拒绝同名 TEMP table/view、TEMP users trigger、main users trigger、PARTIAL schema、非法 `is_admin` / `is_active`、非法 role / `auth_version` 以及 READY 下 role/is_admin 不一致的数据。migration 的 raw verification 不使用 `normalize_user_record` 作为完整性证明。

SEC-1B1 和 SEC-1F0 都提供 caller-transaction primitive。它们要求现有 connection 已有 transaction，且不会自行 BEGIN、commit、rollback 或 close。SEC-1B2 在同一个 `BEGIN EXCLUSIVE` transaction 内编排 audit、role/auth、marker 和 bootstrap；任何失败都会回滚本次 transaction，绝不回退到 `usage_logs`。

## 生命周期

`security_governance_bootstrap` 是 singleton、append-only marker：`singleton_id=1`，记录完成时间、bootstrap actor/target、operation ID 和脱敏 operator label。canonical schema 强制非空、无首尾空白的 marker 文本、非负整数时间、`created_at=bootstrap_completed_at` 与 `bootstrap_completed_by=bootstrap_target_user_id`；包含 target index 及禁止 UPDATE / DELETE 的 trigger。DDL、额外对象、TEMP shadow 或 TEMP trigger 不一致均为 PARTIAL，代码不会自动修补。

| 状态 | 判定 | 行为 |
| --- | --- | --- |
| `UNINITIALIZED` | 无 marker，且没有任何 `super_admin` | 可以生成首次本机 bootstrap plan；普通业务不因该状态停止。 |
| `ACTIVE` | marker 原始字段合法，marker target 是 active `super_admin`，至少一个 active `super_admin`，且恰好一条 bootstrap L3 audit 精确匹配 marker；其 context 必须是无额外/缺失字段的 JSON object，字段值和类型均精确匹配 | 首次 runner 拒绝重复执行。 |
| `RECOVERY_REQUIRED` | marker 缺失但已有任何 `super_admin`，marker target 不存在/不再是 active `super_admin`，或 bootstrap audit 不一致 | 首次 runner 拒绝；未来独立 break-glass 处理。 |
| `LIFECYCLE_SCHEMA_PARTIAL` | marker schema 或 TEMP/canonical 完整性不符合要求 | 与 `RECOVERY_REQUIRED` 区分；人工分析，不自动 repair。 |

没有 active `super_admin` 不会使代码自动挑选或提升 admin。SEC-1B2 不实现 break-glass。

## Plan 与备份门禁

`plan_sec_1b2_activation` 只读数据库和已存在的 backup manifest；它不会创建 schema、marker、audit、用户或输出文件。runner 负责把 plan 写到调用者明确指定且尚不存在的文件。

plan 使用确定性 JSON（`ensure_ascii=False`、`sort_keys=True`、紧凑 separators），其 `plan_hash` 为删除 `plan_hash` 字段后的规范 JSON 的 SHA-256。plan 最长有效期 24 小时，且绑定：

- 当前目标数据库与 source database 的 size、SHA-256 与 journal mode；
- manifest SHA-256、backup ID、SQLite backup SHA-256 与 size；
- role/auth、audit、lifecycle 的 activation 前状态；
- 明确 target ID、精确 username、actor label、reason；
- server-generated plan ID 与 operation ID。

正式 OPS backup manifest 额外记录受控的 `source_database_relative_path=data/enterprise.db`、`source_database_size_bytes`、`source_database_sha256` 和 `source_database_journal_mode`。SEC-1B2 要求 `kind=backup-manifest`、`dry_run=false`、`status=pass`/`success`、`sqlite_backup_status=success`，并同时验证 source fingerprint、backup path、backup size 与 backup SHA-256。plan 与 execute 都重新核对当前目标数据库是否等于 manifest source；旧 manifest 缺少 source fingerprint、来自其它数据库的 backup、dry-run、failed、critical warning、缺字段或 checksum 失配均拒绝。SEC-1B2 不修改备份、不会删除 WAL/SHM、不会 checkpoint。

应用连接默认使用 WAL，因此本机 runner 提供显式 `prepare-journal`。它要求服务已停止确认和绑定数据库文件名的确认短语，先预检独占锁与既有 sidecar；存在 `-wal` / `-shm` 时直接拒绝，不删除 sidecar、不 checkpoint。SQLite 要求 WAL -> DELETE 在无 transaction 状态切换；因此同一连接会在切换前后精确比较 `data_version`、`schema_version`、`user_version`、`total_changes`、users 原始摘要和完整 main-schema 摘要。任何其它连接在窗口内提交的业务或 schema 改动都会 fail closed，且 SEC-1B2 不修复或回滚该外部改动。已经是 DELETE 时保持同一独占 transaction 内幂等验证。prepare 后必须重新创建正式 backup，再生成 plan；plan / execute 只接受 DELETE 且无 sidecar。

## Target 与密码

首次 target 必须是一个明确指定的、现有的 active admin：main.users 中 ID 存在、username 精确确认、raw `is_admin=1`、raw `is_active=1`、role 是 legacy/READY admin。actor 与 target 固定为同一账号。

不会新建账号、不会自动选择账号、不会将所有 admin 提升，也不会从 `is_admin` 推导 `super_admin`。password 只由 local runner 用 `getpass` 交互读取；它不出现在 CLI 参数、环境变量、plan、report、audit 或日志中。

## 原子执行顺序

execute 在所有人工确认完成后使用短 `busy_timeout` 和 `BEGIN EXCLUSIVE`。锁内会重新验证数据库 fingerprint、backup manifest、schema、lifecycle、target 和当前密码，不信任 plan 的旧快照。

1. audit MISSING 时建立 SEC-1F0 canonical schema，并写 `security.audit.foundation.activate`。
2. role/auth LEGACY 时执行 SEC-1B1 raw migration，并写 `security.role_auth.migration.activate`。
3. 建立 immutable lifecycle schema。
4. 再次确认 `UNINITIALIZED` 和 zero `super_admin`。
5. 将指定 admin 原子更新为 `super_admin`，同步 `is_admin=1`，并递增 auth_version。
6. INSERT singleton marker，检查 affected row 和 raw readback。
7. 写 `security.super_admin.bootstrap`，三项 L3 event 复用同一 operation ID。
8. 回读 audit、marker、target 与 lifecycle，要求 `ACTIVE` 且刚好一个 active `super_admin`，随后 commit。

每次 SQL mutation 都检查 affected row 与 main-schema readback。任何 DDL、audit、raw verification、target update、marker insert 或 final lifecycle failure 都会 rollback 本 transaction。测试中的 super_admin 仅存在于临时数据库。

## Token 与 Resume

LEGACY activation 把所有用户的 `auth_version` 初始化为 1，使所有既有 token 失效；bootstrap target 随后递增到 2。若 role/auth 已是 READY、只执行 bootstrap resume，则只有 target 的旧 token 失效，其他当前版本 token 保持有效。plan 与 report 明确给出 `session_invalidation_scope`、`all_existing_tokens_invalidated` 与 `target_tokens_invalidated`；代码不自动签发 token，也不修改 `JWT_SECRET`。

允许的 resume 前提是 audit READY + LEGACY，或 audit READY + ROLE_AUTH_READY + UNINITIALIZED；已经 READY 的层不会重复写对应 activation event。`ACTIVE`、`RECOVERY_REQUIRED`、任何 PARTIAL schema、stale plan、changed database/manifest/target 和锁冲突均拒绝。

## 本机 Runner 与 Report

`tools/sec_1b2_local_runner.py` 只能直接运行文件，并只提供 `status`、`prepare-journal`、`plan`、`execute`：

- `status` 只读 inspect；
- `prepare-journal` 需要显式服务停止确认、交互式数据库标签确认和新的 preparation report 路径；
- `plan` 需要显式 database、formal manifest、target ID/username、actor label、reason 与新输出路径；
- `execute` 需要 plan、expected plan hash、相同 manifest/target/label/reason、四个维护确认、交互密码和绑定 `SEC-1B2 <operation_id> <username> <session_invalidation_scope>` 的确认短语；确认参数为 `--confirm-session-impact-reviewed`，必须以 plan 的动态 `session_impact` 为准，而不是假设所有旧 token 均失效。

没有 password、remote、web、api、daemon、force、skip、repair、checkpoint 或 break-glass 参数。report 必须先以排他方式预留到调用者指定的新路径，初始状态为 `pending_manual_verification_required`；在调用数据库 execute 前，会以 flush / fsync 持久化 `execution_in_progress`。final report 使用安全写入和 flush / fsync。成功 report 记录 plan / operation、必要的数据库与 manifest cryptographic fingerprint、前后状态、target 角色/version、event ID、token impact 和 warning 摘要，但不记录密码或 password hash。失败 report 使用固定错误 code 与真实 transaction state：只有确认 rollback 后才写 `database_transaction_rolled_back=true`；任何 commit 后异常都会明确 `database_changes_committed=true`、`post_commit_verification_required=true` 和 `do_not_rerun_until_status_verified=true`。若 final report 不能替换 execution-in-progress 文件，保留的文件仍要求先 `status`、禁止重试，绝不伪称未提交。report 不记录 Token、Cookie、SQL、数据库内容、绝对路径或 traceback。

## 未实现项

- 生产 activation、生产 rehearsal、生产 `super_admin`；
- break-glass 与 `RECOVERY_REQUIRED` 恢复；
- Capability、Step-up Authentication、Operation Token、UI 或在线角色治理；
- audit 查询、导出、保留、归档、远程日志；
- apply-upgrade、restore、rollback、Docker、PostgreSQL、Redis。

生产 execute 只能由项目负责人于生产主机本地、受控维护窗口内人工运行。ChatGPT 与 Codex 不访问生产；首次 execute 前必须重新创建并复核正式备份，停止服务，并在执行后验证 ACTIVE、审计、所有用户重新登录和 SEC-1C0 保护。
