# SEC-1F0：最小强制安全审计基础

- 状态：仓库实现与临时数据库验证完成，等待 Draft PR 复核
- 代码基线：`main@7758a3356947802fab854081ff8f28a9099fe2c0`
- 决策依据：[ADR SEC-1A](../decisions/ADR-SEC-1A-SUPER-ADMIN-CAPABILITY-GOVERNANCE-2026-07.md)
- 生产状态：未创建审计表，未执行 production migration，未创建 super_admin

## 1. 当前问题

现有 `usage_logs` 和 `log_action` 服务于普通操作日志与既有基础审计。`log_action` 遇到数据库异常会忽略失败，表中也没有 operation、risk、result、actor role snapshot 或强制不可变语义，因此不能作为 bootstrap、break-glass、migration activation、角色治理或生产升级的 mandatory audit。

SEC-1F0 新增独立 `security_audit_events` 通道。它不删除、不替换也不批量改接 `usage_logs`；现有日志页面和普通业务日志继续使用原表。

## 2. 最小 Schema

```sql
CREATE TABLE security_audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    operation_id TEXT NOT NULL,
    action TEXT NOT NULL,
    risk_level TEXT NOT NULL
        CHECK (risk_level IN ('L0', 'L1', 'L2', 'L3')),
    result TEXT NOT NULL
        CHECK (result IN ('attempted', 'success', 'denied', 'failed')),
    actor_type TEXT NOT NULL
        CHECK (actor_type IN ('user', 'system', 'local_operator')),
    actor_user_id TEXT,
    actor_role TEXT
        CHECK (actor_role IS NULL OR actor_role IN ('user', 'admin', 'super_admin')),
    actor_label TEXT,
    capability TEXT,
    target_type TEXT,
    target_id TEXT,
    reason TEXT,
    context_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL
);
```

`actor_user_id` 不建立到 `users` 的级联外键。账号停用或 soft delete 后，历史安全事件仍必须保留。

## 3. 索引与 append-only trigger

必要索引：

- `idx_security_audit_operation (operation_id, id)`
- `idx_security_audit_action_created (action, created_at)`
- `idx_security_audit_actor_created (actor_user_id, created_at)`

必要 trigger：

- `trg_security_audit_no_update`：任何 UPDATE 使用 `RAISE(ABORT, ...)` 拒绝。
- `trg_security_audit_no_delete`：任何 DELETE 使用 `RAISE(ABORT, ...)` 拒绝。

事件最终结果通过相同 `operation_id` 追加新事件，不修改 attempted 事件。本任务不提供 update、delete、clear、truncate 或保留周期清理接口。

SQLite trigger 能防止应用误改和普通 SQL 路径修改，但不能阻止拥有数据库文件及完整系统权限的人员直接篡改文件。离线防篡改、归档和远程副本不属于 SEC-1F0。

## 4. Schema 状态

CREATE TABLE、三个 CREATE INDEX 和两个 CREATE TRIGGER 由 `enterprise/security_audit.py` 中同一组 canonical DDL 定义生成，migration apply 与 inspect 共用该事实源。inspect 对 `sqlite_master.sql` 只忽略安全的空白、大小写和末尾 statement terminator，然后与 canonical 定义完整比较；不使用 SQL 片段包含关系。

状态只根据实际 `sqlite_master`、`PRAGMA table_info`、索引列和 canonical DDL 比较结果判断：

- `SECURITY_AUDIT_MISSING`：表和同名必要对象均不存在。
- `SECURITY_AUDIT_READY`：table、indexes 和 UPDATE / DELETE triggers 与 SEC-1F0 canonical 定义一致，且审计表不存在额外普通 trigger、额外用户 index 或 TEMP trigger。
- `SECURITY_AUDIT_PARTIAL`：表、同名对象、字段、约束、索引或 trigger 只完成一部分或结构不匹配。

同名但定义不同的 table、index 或 trigger 均为 PARTIAL。额外 `WHEN`、不同 body、错误表绑定、只保留相同错误文本但不执行 RAISE，以及用 comment 伪造约束文本均不能成为 READY。inspect 还会查询 `sqlite_temp_master`；任何绑定 `security_audit_events` 的 TEMP trigger、同名 TEMP TABLE / VIEW 遮蔽物，以及任何不在 canonical 闭集中的普通 trigger 或用户 index，都会成为 PARTIAL。名称比较大小写不敏感；SQLite 为 PRIMARY KEY / UNIQUE 自动创建且 `sql IS NULL` 的 autoindex 不视为额外用户 index。

PARTIAL 必须 fail closed；plan 只报告问题，apply 不修补、不覆盖、不删除，也不重建已有对象。warning 只报告对象名称分类，不输出 trigger SQL 全文。

## 5. inspect、plan 与 apply

`enterprise/migrations/sec_1f0_security_audit.py` 提供：

- `inspect_security_audit_schema`：显式 Connection 或已存在普通文件；路径使用 SQLite URI `mode=ro`。
- `plan_security_audit_migration`：完全只读，报告 table / indexes / triggers、`production_activation=false` 和 `super_admin_to_create=0`。
- `apply_security_audit_migration`：显式 Connection 或已存在普通文件；路径使用 `mode=rw`，不创建新数据库文件。

apply 未接入 startup、API、OPS runner、PowerShell 或生产 CLI。首次 MISSING apply 在一个 `BEGIN IMMEDIATE` 事务中创建 table、indexes、triggers，并写入 activation event；任一步失败均回滚。READY 再次 apply 不重复写 activation event，PARTIAL 直接拒绝。

## 6. migration activation event

首次 apply 写入：

- action：`security.audit.foundation.activate`
- risk：`L3`
- result：`success`
- actor type：`local_operator`

调用方必须提供 `actor_user_id`、`actor_label`、`operation_id` 和非空 `reason`。actor 必须是 `main.users` 中的 active admin 或 active super_admin；字段检查使用 `PRAGMA main.table_info(users)`，LEGACY 从主库 `is_admin` 推导，ROLE_AUTH_READY 从主库严格 `role` 读取。writer 在 INSERT 前从同一数据库连接的 `main.users` 重新读取角色并覆盖调用方快照，不信任声明的 `actor_role`，也不受同名 TEMP users 影响。

## 7. Actor 规则

- `user`：必须提供 `actor_user_id` 和精确基础角色。
- `system`：不得提供用户 ID 或角色；label 可为空或为固定系统标签。
- `local_operator`：必须提供脱敏 label；activation 还必须绑定当前 active admin / super_admin。

actor type 和 role 均精确匹配，不执行 strip、lower 或自动纠正。空白 ID、非法角色及不存在、disabled 或普通 user 的 activation actor 全部拒绝。

## 8. 固定 action Catalog

SEC-1F0 固定支持：

- `security.audit.foundation.initialize`
- `security.audit.foundation.activate`
- `security.role_auth.migration.activate`
- `security.super_admin.bootstrap`
- `security.super_admin.break_glass`
- `security.role.change`
- `security.user.password_reset`
- `security.user.active_change`
- `security.user.soft_delete`
- `security.session.revoke_all`
- `security.authorization.denied`

action 不接受任意输入，不执行字符串清洗。新增 action 必须通过后续代码变更进入 Catalog。

## 9. risk 与 result

风险固定为 `L0`、`L1`、`L2`、`L3`，结果固定为 `attempted`、`success`、`denied`、`failed`。Catalog 同时限制每个 action 可使用的 risk：foundation、migration、bootstrap 和 break-glass 为 L3；角色、密码、active、soft delete、session revoke 和 authorization denied 为 L2 或 L3。

所有事件必须提供 operation ID；L3 还必须提供非空 reason。同一操作的 attempted、success、denied 或 failed 事件复用 operation ID。result 只是记录结果，不替代授权门禁。

## 10. Writer API 与事务语义

`append_security_audit_event` 由服务端生成 `event_id` 和 UTC epoch milliseconds `created_at`，验证后执行参数化 INSERT，不接受调用方时间或事件 ID。Schema、字段、index、计数、INSERT 和 event-id 回读分别显式使用 `main.sqlite_master`、`PRAGMA main.table_info/index_info` 和 `main.security_audit_events`，不依赖 SQLite 默认对象解析顺序。即使同一 connection 存在同名 TEMP 对象，持久化写入和验证也只指向 main Schema。

INSERT 返回后，writer 必须确认 affected row 为 1，并在同一 connection、同一事务内从 `main.security_audit_events` 按 `event_id` 恰好回读一行，逐项核对全部持久化字段。没有抛出 SQLite 异常不等于审计成功；`RAISE(IGNORE)` 等静默 no-op 会因 rowcount 或回读不一致而 fail closed。

传入 `sqlite3.Connection` 时：

- 调用方必须已经显式建立 active transaction；`connection.in_transaction` 为 false 时拒绝。
- `isolation_level=None` 的 autocommit Connection 必须先显式执行 `BEGIN`。
- writer 不替调用方隐式 BEGIN。
- 不 commit、不 rollback、不 close。
- 只在调用方当前事务中 INSERT。
- 高风险业务修改和安全事件可由调用方统一 commit 或 rollback。

传入 `database_path` 时：

- 只打开已存在普通文件。
- writer 自己执行 `BEGIN IMMEDIATE`、commit 或 rollback。
- 缺失或 PARTIAL Schema、验证失败和 INSERT 失败全部抛异常。

两种输入必须二选一。writer 不回退到 `usage_logs`、普通文件或 best-effort 模式。

## 11. fail-closed 异常

- `SecurityAuditError`：基础类型。
- `SecurityAuditValidationError`：枚举、actor、字段或 context 验证失败。
- `SecurityAuditSchemaError`：Schema 缺失、PARTIAL 或不可检查。
- `SecurityAuditWriteError`：INSERT、constraint、trigger、affected-row 或写后回读确认失败。
- `SecurityAuditMigrationError`：显式 migration 计划或执行失败。

异常不包含 context 内容、secret value、SQL 全文或数据库绝对路径。后续 L3 调用方必须在审计失败时回滚或不执行；本 PR 不接入现有在线操作。

## 12. 敏感字段拒绝

context 对所有 dict key 递归检查，list 内 dict 同样检查。key 统一按大小写不敏感并移除连字符、下划线等分隔符后，使用受控 canonical aliases 精确匹配，因此 `api-key`、`api_key`、`APIKey` 等属于同类。

禁止 aliases 包括基础密码、Token、Cookie、API Key、secret、env 和 private key 字段，也明确覆盖 `db_password`、`database_password`、`admin_password`、`user_password`、`credential(s)`、`auth_token`、`bearer_token`、`session_token`、`user_access_token`、`raw_request_body`、`request_payload`、`full_user_prompt`、`raw_prompt`、`canvas_data`、`canvas_json_data`、`private_key_pem`、`environment_value` 和 `production_env`。一旦出现，整条事件拒绝；不删除字段后继续写入。

该策略是明确字段名 aliases 与受限 context 边界，不声称能够识别任意字段名或任意秘密值。为避免误伤非秘密统计，`token_count`、`input_token_count` 和 `output_token_count` 明确允许；禁止规则不采用“包含 token 即拒绝”的无限前后缀匹配。后续 action 接线仍应使用最小 context allowlist。

## 13. context 与字段限制

context 根节点必须是 dict，只允许 null、bool、int、有限 float、str、list 和字符串 key dict：

- 最大嵌套深度：4。
- 全部 dict key 总数：100。
- 单字符串或 key：2048 字符。
- 紧凑 UTF-8 `context_json`：16 KiB。
- 序列化固定使用 `ensure_ascii=false`、`sort_keys=true` 和紧凑 separators。

bytes、自定义对象、datetime、NaN、Infinity、非字符串 key 和所有超限输入均拒绝，不做静默截断。operation ID、reason、actor label、capability、target type / ID 也有明确长度限制。

## 14. 新数据库与旧数据库策略

本任务不修改 `init_db`。原因是当前 `init_db` 同时服务新库和旧库，startup 自动建表会模糊 production activation 边界。

- 真正新数据库：先由现有 `init_db` 建立业务 Schema 和默认 admin，再显式执行 SEC-1F0 apply，写 activation event。
- 已存在 LEGACY / ROLE_AUTH_READY 数据库：startup 不创建、不修补 security audit Schema。
- PARTIAL：任何 startup 或 apply 都不自动修复。

`security.audit.foundation.initialize` 已进入固定 Catalog，供未来经过独立设计的新库原子初始化流程使用；本任务不自动写 initialization event。

## 15. 测试覆盖

`enterprise/tests/test_sec_1f0_security_audit.py` 全部使用 `tempfile.TemporaryDirectory`，覆盖：

- existing-path、MISSING / PARTIAL / READY、canonical DDL、只读 plan 和字节 / Schema 不变。
- `WHEN 0`、伪 RAISE 文本、错误表绑定、不同 trigger body、额外普通/TEMP trigger、同名 TEMP TABLE / VIEW、额外用户 index、不同 index 和 comment 伪约束全部判定 PARTIAL。
- inspect 被测试替换为 READY 时，writer 仍只写入和回读 `main.security_audit_events`；caller commit / rollback 原子性保持不变。
- TEMP users 对普通用户、disabled admin 和 active admin 的伪造均不能改变 `main.users` actor 判定。
- active admin / synthetic super-admin fixture、disabled / user / missing actor 拒绝。
- apply 数据保留、同事务 activation、幂等和故障注入完整回滚。
- writer 自管事务、caller active-transaction 门禁、autocommit 显式 BEGIN、commit / rollback 和 connection ownership。
- INSERT 失败、`RAISE(IGNORE)` 静默 no-op、rowcount/写后回读确认的明确异常，以及无 `usage_logs` / 文件 fallback。
- UPDATE / DELETE trigger 与继续 INSERT。
- action / risk / result / actor 验证、当前数据库 actor role 覆盖伪造快照。
- 基础与复合敏感 aliases、嵌套绕过、允许的 token-count 统计、JSON 类型、深度、key、字符串和总大小限制。
- 中文 context、现有 `usage_logs`、默认 admin 和显式新库 activation。

测试不会打开或复制 `data/enterprise.db`，不读取生产 env、Token、Cookie、密码或备份。

## 16. 当前未实现

- 生产 Schema activation 和 migration CLI。
- super_admin bootstrap、break-glass executor 或 SEC-1C0 在线保护。
- Capability、Step-up Authentication、Operation Token。
- 现有用户、角色、密码、active、soft delete、feature flag、owner 或登录接口接线。
- 管理后台查询、导出、删除、归档、保留周期、远程日志或 SIEM。
- apply-upgrade、restore 或 rollback。

SEC-1F0 自身的审计表和 activation actor 查询已固定使用 main Schema。SEC-1B1 migration 中其余未限定 users 查询仍需在 SEC-1B2 production activation 前通过独立任务全面加固；本 PR 不宣称整个 SEC-1B1 migration 已完成 Schema qualification，也不实施 SEC-1B2。

## 17. 后续顺序

SEC-1F0 合并只代表底层 append-only writer、显式 migration 和临时数据库证明进入仓库，不代表生产审计表已创建。生产仍为 LEGACY，未执行 role/auth 或 audit production migration，也未创建 super_admin。

下一阶段是 SEC-1C0 transitional protection。SEC-1B2 仍负责受控 role/auth 与 security audit activation 以及首次 bootstrap，并且不得早于 SEC-1F0 和 SEC-1C0。
