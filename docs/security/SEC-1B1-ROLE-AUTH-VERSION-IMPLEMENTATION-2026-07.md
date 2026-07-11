# SEC-1B1：角色、auth_version、迁移基础与 JWT 当前状态加载

- 状态：仓库实现与临时数据库验证完成，等待 Draft PR 复核
- 代码基线：`main@4432dd7af3898b0d9511d6add79f3e7de891d00f`
- 决策依据：[ADR SEC-1A](../decisions/ADR-SEC-1A-SUPER-ADMIN-CAPABILITY-GOVERNANCE-2026-07.md)
- 生产状态：未执行 migration，未创建 super_admin，未启用新生产角色能力

## 1. 当前问题

SEC-1B1 之前，`users` 只有 `is_admin` 二级角色；JWT 保存调用方提供的 `username` 和 `is_admin`，`verify_token` 验证签名和 active 用户后直接返回 Token payload。密码、角色和 active 状态变化没有统一会话版本，因此旧 Token 不能被确定撤销，角色授权也可能继续使用 Token 中的旧快照。

SEC-1B1 建立兼容基础，不实施 Capability、超级管理员治理或生产 activation。

## 2. 新旧 Schema

### LEGACY

旧 `users` 没有 `role`、`auth_version`、`role_updated_at` 和 `role_updated_by`。运行时代码通过 `PRAGMA table_info(users)` 识别该状态，不根据版本号、文件名或配置猜测。

### ROLE_AUTH_READY

新建数据库直接创建：

```sql
role TEXT NOT NULL DEFAULT 'user'
auth_version INTEGER NOT NULL DEFAULT 1
role_updated_at INTEGER NULL
role_updated_by TEXT NULL
```

`role` 只允许 `user`、`admin`、`super_admin`，`auth_version` 必须是非负整数。`is_admin` 作为迁移期兼容字段继续保留。

全新默认管理员为 `role=admin`、`is_admin=1`、`auth_version=1`。现有 `create_user(..., is_admin=True)` 只能创建 `admin`，不能创建 `super_admin`。

## 3. role 与 is_admin 兼容优先级

统一角色常量与转换位于 `enterprise/roles.py`。

| Schema | 角色事实源 | 兼容结果 |
| --- | --- | --- |
| LEGACY | `is_admin` | `0/null -> user`，`1 -> admin`，`auth_version=0` sentinel |
| ROLE_AUTH_READY | `role` | `user -> is_admin=false`，`admin/super_admin -> is_admin=true` |

迁移后即使 `is_admin` 与 `role` 不一致，读取结果也由 `role` 决定。role 必须精确匹配 `user`、`admin` 或 `super_admin`；不执行 `strip`、大小写转换或其他字符串清洗。非法 role、非法 legacy `is_admin` 或非法 `auth_version` 会 fail closed，不会被自动纠正或回退为管理员。

## 4. auth_version 递增规则

ROLE_AUTH_READY 数据库中：

- 密码每次成功修改都递增。
- user/admin 角色实际变化时递增。
- active 状态实际变化时递增，包括禁用和重新启用。
- display name 和 last_login 不递增。
- owner 与 feature override 不递增。

密码、角色 / `is_admin` 同步、active 变化和 `auth_version` 递增在同一个 `BEGIN IMMEDIATE` 事务中完成。重复设置相同角色或 active 状态不会递增。

LEGACY 数据库没有 `auth_version`，这些写入继续使用旧字段，以保持 migration activation 前的运行兼容。

因此，在生产仍为 LEGACY 期间，角色和 active 判断会按每次请求读取的当前数据库值生效，但密码修改以及禁用后重新启用仍没有版本级旧 Token 撤销保证。只有 SEC-1B2 激活 migration 后，`auth_version` 撤销语义才正式生效。

## 5. JWT 新 payload

`create_token(user_id)` 会先读取当前 active 用户，不再接受调用方提供的 `is_admin` 或 role。新 Token 包含 `user_id`、`auth_version`、`jti`、`iat` 和 `exp`。

JWT 不保存 role、`is_admin`、密码、密码哈希、Cookie、Capability、API Key 或 env value。

## 6. verify_token 当前状态加载

`verify_token` 强制所有 Token 包含非空字符串 `user_id`、合法时间类型 `iat` 和存在且未过期的 `exp`，并验证签名；缺少任一全局必要 Claim 的 Token 均拒绝。验证通过后，按 `user_id` 从数据库重新读取当前 active 状态、role、`auth_version` 和 username。

返回 principal 由数据库记录构造：

```json
{
  "user_id": "current-db-id",
  "username": "current-db-username",
  "role": "user-or-admin",
  "auth_version": 1,
  "is_admin": false,
  "jti": "token-id"
}
```

Token 中伪造的 role 或 `is_admin` 被忽略。HTTP middleware、页面鉴权和 WebSocket 代理继续复用同一个 `verify_token`。

## 7. 旧 Token 兼容策略

LEGACY 数据库：

- 允许缺少 `auth_version` 的旧 Token。
- 允许缺少 `jti` 的旧 Token。
- 仍强制要求 `user_id`、`iat` 和 `exp`，不兼容缺少 `exp` 的永久 Token。
- 忽略旧 Token 中的 role / `is_admin`。
- 每次请求从当前数据库 `is_admin` 推导 user/admin。
- 新签发 Token 使用 legacy sentinel `auth_version=0`。

ROLE_AUTH_READY 数据库：

- Token 必须包含合法 `auth_version` 和非空字符串 `jti`。
- 缺少版本或与数据库不匹配时拒绝。
- migration activation 后，迁移前签发的旧 Token 会统一失效并要求重新登录。

SEC-1B2 必须在维护窗口和用户通知中明确该会话失效行为。

## 8. migration inspect / plan / apply

`enterprise/migrations/sec_1b1_role_auth.py` 提供三个显式函数：

- `inspect_role_auth_schema`：路径输入必须指向已存在的普通文件，并通过 SQLite URI `mode=ro` 读取实际 columns、索引和聚合计数，识别 LEGACY / PARTIAL / ROLE_AUTH_READY、非法 role 和非法 auth_version。
- `plan_role_auth_migration`：复用真正的只读连接，输出待添加 columns / indexes、legacy 映射数量、warnings、`super_admin_to_create=0` 和 `production_activation=false`。
- `apply_role_auth_migration`：路径输入必须指向已存在的普通文件，并通过 SQLite URI `mode=rw` 打开；它只作为明确调用的代码基础和临时数据库测试入口，在单个事务中添加字段、映射 `is_admin`、初始化 `auth_version=1` 并创建 `idx_users_role_active`。

三个入口都不会为缺失路径隐式创建 SQLite 文件，面向调用方的异常不包含数据库绝对路径；显式 `sqlite3.Connection` 输入保持兼容。apply 幂等；失败会回滚。它不修改密码哈希、用户 ID、active 状态、owner 表或 `usage_logs`，不创建 super_admin。

本模块没有 CLI、网页 API、OPS runner、PowerShell 或 startup 注册。

## 9. 为什么 startup 不自动迁移

`init_db` 对全新空数据库直接创建 ROLE_AUTH_READY schema；对已存在 LEGACY users 表只执行兼容读取和旧字段插入，不执行 `ALTER TABLE users`，也不调用 migration apply。

生产 migration 需要 SEC-1F0 强制审计、正式备份、维护窗口、计划复核和项目负责人确认。startup 自动 ALTER 会绕过这些门禁，因此明确禁止。

## 10. 为什么不创建 super_admin

- 旧 `is_admin=1` 只映射为 `admin`。
- 默认管理员和现有管理员创建接口只产生 `admin`。
- migration plan 固定 `super_admin_to_create=0`。
- migration apply 验证自身不会增加 super_admin 数量。

首次 super_admin bootstrap 属于 SEC-1B2，且不得早于 SEC-1F0 和 SEC-1C0。

## 11. 测试覆盖

`enterprise/tests/test_sec_1b1_role_auth.py` 全部使用 `tempfile.TemporaryDirectory`，覆盖：

- LEGACY inspect / plan 只读与映射计数。
- 缺失路径拒绝且不生成空数据库、Windows 路径 URI 兼容和显式 Connection 兼容。
- 显式 migration、字段与索引、数据保留、幂等和失败回滚。
- 全新数据库、默认管理员与 create_user 兼容。
- JWT payload、伪造角色忽略、签名 / 过期 / 用户状态拒绝。
- 密码、角色、禁用、重新启用后的旧 Token 撤销。
- display name / last_login 不撤销。
- LEGACY Token 兼容和 migration 后统一失效。
- 管理员 API、feature flag、delete-impact、登录响应和 WebSocket verify 兼容。

现有 db / admin 相关隔离测试也必须回归。测试不会打开或复制 `data/enterprise.db`。

## 12. 未实现项

- SEC-1F0 `security_audit_events`。
- SEC-1C0 首次 bootstrap 前的 super_admin 过渡保护。
- SEC-1B2 生产 migration activation 或 super_admin bootstrap。
- SEC-1C Capability、最后超级管理员保护或新角色 API。
- SEC-1D Step-up Authentication / Operation Token。
- SEC-1E 超级管理员 UI。
- SEC-1F 完整审计查询、导出、保留和归档。
- SEC-1U 升级入口门禁。
- apply-upgrade、restore 或 rollback。

## 13. SEC-1F0 前置关系

SEC-1B1 合并后只存在仓库代码和临时数据库证明。下一阶段 SEC-1F0 必须先建立最小 append-only 强制安全审计及 fail-closed 测试。

SEC-1F0 完成后还必须先实施 SEC-1C0：阻止 admin 修改 super_admin 角色、重置其密码、启停、soft delete 或撤销其会话；阻止自行提权；并保证正常在线事务不能把 active super_admin 数量降为零。SEC-1C0 只提供首次 bootstrap 所需的过渡保护，不实现完整 Capability 矩阵。

首次 bootstrap、migration activation、role change 和 break-glass 不得早于 SEC-1F0；SEC-1B2 首次 bootstrap 还不得早于 SEC-1C0。PR #72 不实现 SEC-1C0，也不创建任何 super_admin。

## 14. SEC-1B2 激活条件

SEC-1B2 才负责维护窗口 migration activation。至少需要：

- SEC-1F0 已实现并验证。
- SEC-1C0 过渡保护已实现并验证。
- 正式备份与可复核 manifest。
- 临时副本 migration rehearsal。
- 明确旧 Token 统一失效和重新登录安排。
- 项目负责人在生产主机本地人工执行。

代码合并不等于生产 migration 已执行；新生产角色能力尚未启用；生产仍未创建 super_admin。
