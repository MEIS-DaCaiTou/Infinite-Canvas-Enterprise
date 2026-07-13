# SEC-1C0：首次 bootstrap 前的超级管理员过渡保护

- 状态：仓库实现与临时数据库验证完成，等待 Draft PR 复核
- 任务性质：SEC-1B2 首次本机 bootstrap 前的过渡保护
- 生产状态：仍为 LEGACY；未激活 role/auth 或 audit migration；未创建 super_admin

## 1. 任务定位

SEC-1C0 在 SEC-1B1 的 `role` / `auth_version` 基础和 SEC-1F0 的 mandatory audit 基础上，收紧在线用户治理。它不是完整 Capability 系统，不开放在线角色治理，也不实现 Step-up Authentication、Operation Token、bootstrap、break-glass 或 production migration activation。

本阶段保证：首次 super_admin 出现后，现有普通管理员接口不能修改其角色、密码、active 状态、profile、会话或 soft-delete 状态；在首次 bootstrap 之前，零 active super_admin 不会阻断普通业务和允许的普通用户治理。

## 2. 前置关系

- SEC-1B1 已提供固定 `user`、`admin`、`super_admin` 角色、`auth_version`、显式 migration 和数据库当前状态 JWT 校验。
- SEC-1F0 已提供显式 `security_audit_events` migration、append-only writer、main Schema 限定和 fail-closed 异常。
- SEC-1C0 不调用两项 production migration，也不创建 super_admin。
- SEC-1B2 不得早于 SEC-1F0 和 SEC-1C0。

## 3. Schema 状态行为

### 3.1 LEGACY

LEGACY 数据库继续使用原有 `is_admin` 兼容路径：

- 不自动增加 `role` 或 `auth_version`。
- 不自动创建 `security_audit_events`。
- 原管理员创建、密码、角色、active、profile 和 soft-delete 兼容行为保持。
- 不将任何 `is_admin=1` 用户解释为 super_admin。
- 不创建或提升 super_admin。

因此，本 PR 合并不会使当前生产管理员操作因缺少新 audit Schema 而整体中断。

### 3.2 ROLE_AUTH_READY + SECURITY_AUDIT_READY

在线敏感治理进入 `enterprise/security_user_governance.py`。服务在 `BEGIN IMMEDIATE` 后先从 `main.users` 读取并认证 actor，再以不抛 404 的 lookup 读取 target 用于策略和审计分类，最后才决定 target 是否可对当前 actor 公开。业务变更与 auth-version 更新使用同一 connection 追加 mandatory audit，audit 成功后才 commit。

READY 在线请求还必须携带已由认证中间件验证的 principal `auth_version`。治理事务在取得写锁后将其与 `main.users.auth_version` 精确比较；缺失、布尔值、非法值或不匹配均以脱敏的 `401 STALE_AUTHENTICATION` 拒绝。API 和治理服务均执行这一检查，后者不能依赖 HTTP 层已经完成认证。这样即使 Token 在中间件验证后被密码修改或会话撤销，旧请求也不能完成一次额外治理写入。

actor-first 的外部语义固定如下：stale actor 无论 target 是否存在均返回 401；active `role=user` actor 无论 target 是否存在均返回 403 并在 audit READY 时追加 denied event；只有当前 active 且 auth_version 匹配的 admin / super_admin 才可能得到 target 404。不存在 target 在审计 context 中使用 `target_role=null`，不会改变前两类 actor 的状态码，也不会成为枚举用户 ID 的信号。

### 3.3 ROLE_AUTH_READY + audit MISSING / PARTIAL

密码重置、active change、soft delete、在线角色请求、会话撤销策略和所有涉及 super_admin 的拒绝均 fail closed：

- 不修改用户数据。
- 不递增 `auth_version`。
- 不自动创建、修补或激活 audit Schema。
- 不回退到 `usage_logs` 或文件日志。
- API 返回稳定、脱敏的 `503 MANDATORY_AUDIT_UNAVAILABLE`。

普通用户创建和允许的非安全 profile 修改属于当前 L1 兼容范围；成功后继续使用现有 ordinary usage log。涉及角色字段或受保护目标时仍要求 mandatory denied audit。

## 4. Actor / Target 过渡矩阵

| actor | target=user | target=admin | target=super_admin |
|---|---|---|---|
| user | 拒绝进入治理服务 | 拒绝 | 拒绝 |
| admin | 允许普通创建、profile、密码重置、active、soft delete | 全部敏感治理拒绝 | profile、密码、active、soft delete、role、session 全部拒绝 |
| super_admin | 允许 profile、密码重置、active、soft delete | 允许现有普通治理操作 | 仅允许修改自己的非安全 profile；其它在线安全治理全部拒绝 |

所有角色的在线 role change 均关闭。super_admin 不能使用旧 `is_admin` 布尔接口授予或撤销 admin / super_admin，也不能自行降级、停用或 soft delete。

## 5. 创建用户提权保护

ROLE_AUTH_READY 下，普通创建接口只创建：

```text
role=user
is_admin=0
auth_version=1
```

以下请求明确拒绝，不做静默降级：

- `is_admin=true` 或其它非 false 值。
- 任何 `role` 字段，包括 `role=user`、`role=admin`、`role=super_admin`。

拒绝写入 `security.authorization.denied`。候选 target ID 由服务端生成；password 和 password hash 不进入 context、reason、异常或 ordinary log。首次 super_admin 仍只能由 SEC-1B2 本机 bootstrap 创建。

## 6. 在线角色与 super_admin 安全状态

ROLE_AUTH_READY 下，现有 `/api/users/{user_id}/role` 对 admin 和 super_admin 全部关闭：

- 不修改 `role`。
- 不修改兼容 `is_admin`。
- 不递增 `auth_version`。
- 普通目标拒绝为 L2；super_admin 目标拒绝为 L3。

同样关闭所有在线 super_admin 密码重置、active change、soft delete、session revoke 和另一个 super_admin profile 修改。SEC-1D 完成前不会开放这些路径。

## 7. 最后 active super_admin 保护

`count_active_super_admins(connection)` 和 `ensure_active_super_admin_remains(connection, target, operation)` 提供 connection-aware 基础：

- 只接受 active transaction。
- 只在 ROLE_AUTH_READY 使用。
- 只查询 `main.users`。
- active super_admin 精确定义为 `role='super_admin' AND is_active=1`。
- 不使用 `is_admin`、缓存计数、请求前快照或 TEMP users。
- 调用方必须先获得 `BEGIN IMMEDIATE` 写锁，再在同一事务重新计数。

SEC-1C0 在线策略直接关闭 super_admin 安全状态修改；该 helper 供 SEC-1B2、SEC-1C 和 SEC-1D 复用。双连接测试证明：第一个事务持有写锁时第二个写事务不能进入；第一个提交后，第二个事务重新看到剩余数量并拒绝降为零。

本阶段不根据数量持久化或推断 `UNINITIALIZED`、`ACTIVE`、`RECOVERY_REQUIRED`。零 active super_admin 时不自动创建、不自动提升 admin，普通业务及允许的普通用户治理继续运行。

## 8. 数据库事务与 mandatory audit

密码、active 和 soft delete 成功路径统一执行：

```text
open connection
-> BEGIN IMMEDIATE
-> inspect main users schema and audit schema
-> reload actor from main.users
-> reload target from main.users
-> evaluate transitional policy
-> update main.users and auth_version
-> append security_audit_events on the same connection
-> commit
```

每个 `main.users` INSERT 或 UPDATE 均保存 cursor 并要求 `rowcount == 1`。随后服务在同一 connection、同一事务内按 user ID 回读：创建确认 `id`、username、display name、password hash、`role=user`、`is_admin=0`、`auth_version=1` 和 active 状态；密码、active、soft delete 与 profile 操作同时确认预期变更和所有不应变化的安全字段。业务写入后、success audit 前还会重新确认 actor 的 role、active 与 auth_version 未被 trigger 或其它同事务副作用改变。

无异常 SQL 不等于治理成功。affected-row、回读缺失或字段不一致会以脱敏的 `409 USER_GOVERNANCE_INTEGRITY_FAILED` fail closed，整个事务 rollback；不会写 success mandatory audit，也不会回退到 `usage_logs` 或文件日志。任何验证、SQL 或 mandatory audit 失败同样 rollback，不存在“先提交用户变更，再补写审计”的路径。

## 9. Audit 规则

成功事件：

| 操作 | action | risk | result |
|---|---|---|---|
| 密码重置 / 自助密码修改 | `security.user.password_reset` | L2 | success |
| 启用 / 停用 | `security.user.active_change` | L2 | success |
| soft delete | `security.user.soft_delete` | L2 | success |

拒绝统一使用 `security.authorization.denied`：普通角色越权为 L2，涉及 super_admin 目标或 `role=super_admin` 请求为 L3。active `role=user` actor 也会进入治理事务并追加 denied event，不能仅依赖 API 的旧管理员初筛。L3 使用固定服务端 reason `transitional_super_admin_protection`。当可安全读取当前 actor、audit Schema READY 且 principal auth_version 已过期时，同样记录 denied event，但 context 仅使用固定 `stale_actor_auth_version` 策略码，不记录 Token 或 JWT。

context 只包含 `policy_code`、`requested_operation`、数据库当前 `actor_role` / `target_role`、可选 active 目标状态和 Schema 状态。禁止记录 password、password hash、JWT、Cookie、完整请求体或完整用户对象。

## 10. Reason 与 auth_version

- 密码重置、启用、停用和 soft delete 要求非空、非纯空白、最长 2048 字符的 reason。
- reason 不做 strip 后自动纠正，原值写入 mandatory audit。
- 密码成功变更每次 `auth_version + 1`。
- active 状态实际变化时 `auth_version + 1`；重复设置保持不变。
- soft delete 实际从 active 变为 inactive 时 `auth_version + 1`。
- profile 更新不递增。
- denied、验证失败或 audit 失败不递增。
- 重新启用不会恢复旧 Token；SEC-1B1 JWT 回归继续验证版本失效。

## 11. main Schema 与 TEMP users

治理模块的安全关键 SQL 显式使用：

- `main.sqlite_master`
- `PRAGMA main.table_info(users)`
- `main.users`
- SEC-1F0 writer 的 `main.security_audit_events`

actor、target、active、role、auth-version 和 active-super-admin count 均不依赖 SQLite 默认名称解析。测试在同一 connection 创建伪造 TEMP users，将 admin 改成 super_admin、将 super_admin 改成 user，最终授权和 audit actor role 仍以 `main.users` 为准。

## 12. 旧 mutator 防绕过

`enterprise/db.py` 的旧公共 mutator 在 ROLE_AUTH_READY 下执行以下边界：

- `update_user_password`、`update_user_role`、`set_user_active`、`delete_user`、`update_user_profile` 明确拒绝，要求进入治理服务。
- `create_user(..., is_admin=True)` 明确拒绝。
- `create_user(..., is_admin=False)` 保留为普通测试、初始化和内部兼容 primitive，只能生成 `role=user`。
- LEGACY 下原行为保持。

管理员在线路由不再直接调用 READY 旧敏感 mutator。自助密码修改也使用同一治理事务，避免为兼容路径留下无 actor / audit 的写入口。

## 13. API 与错误语义

LEGACY 的 `_require_admin` 保持原粗粒度入口初筛。READY 路由只检查 request principal 中已验证的 actor ID 与非负整数 `auth_version`，最终角色授权、actor role、active、auth_version 和 target 状态全部由服务在事务内从 `main.users` 重读。伪造 request-state role / `is_admin` 不能覆盖数据库事实。

| HTTP | code | 语义 |
|---|---|---|
| 400 | `INVALID_GOVERNANCE_REQUEST` | reason、确认或请求格式无效 |
| 403 | `TRANSITIONAL_POLICY_DENIED` | actor / target 角色策略拒绝 |
| 404 | `USER_NOT_FOUND` | target 不存在 |
| 409 | `USER_GOVERNANCE_CONFLICT` | 最后 super_admin 或状态冲突 |
| 409 | `USER_GOVERNANCE_INTEGRITY_FAILED` | affected-row 或事务内写后回读不一致 |
| 401 | `STALE_AUTHENTICATION` | principal auth_version 缺失、非法或已过期 |
| 503 | `MANDATORY_AUDIT_UNAVAILABLE` | READY audit 缺失、PARTIAL 或写入失败 |
| 500 | `USER_GOVERNANCE_INTERNAL_ERROR` | 脱敏内部错误 |

响应不返回 SQL、password hash、数据库路径或底层异常全文。伪造 request-state role / `is_admin` 不能覆盖数据库事实。

`POST /api/users` 对已知治理异常仍使用稳定错误映射，SQLite integrity conflict 使用安全 409；其它未知内部异常统一返回固定 `500 USER_CREATE_FAILED`，不将异常字符串、SQL、路径、异常类型或 traceback 写入客户端响应。

## 14. 测试覆盖

`enterprise/tests/test_sec_1c0_super_admin_protection.py` 使用 `TemporaryDirectory` 覆盖：

- LEGACY 不迁移、不建 audit、不产生 super_admin。
- READY audit MISSING / PARTIAL 敏感操作 fail closed，Schema 和用户状态不变。
- 零 active super_admin 时普通 user 密码治理继续成功。
- admin 对 user 允许，对 admin / super_admin 拒绝。
- super_admin 对 user / admin 允许，对 super_admin 安全状态拒绝；仅自己的 profile 允许。
- create role / `is_admin` 字段拒绝，在线 role change 全部关闭。
- password、active、soft delete、profile、session policy、自我操作和 denied L2 / L3。
- last-super-admin 单实例及双连接写锁重计数。
- audit 故障注入使用户数据和 auth-version 回滚。
- `main.users` 的 `RAISE(IGNORE)` 和写后篡改 trigger 不能伪造用户治理成功；rowcount、用户回读和 actor 安全状态回读失败时不写 success audit。
- stale principal auth_version 覆盖 password、active、soft delete、profile、普通创建、在线 role 拒绝、session policy、自助密码和 API `401` 边界。
- stale actor 对不存在 target 仍为 401，active ordinary user actor 对不存在 target 仍为 403；fresh admin 对同一 target 保持 404，避免 target 存在性成为撤销会话或普通用户的可观察差异。
- 治理服务的 `None`、bool、字符串、浮点数和负整数 auth_version 全部统一为 `STALE_AUTHENTICATION`；POST 用户创建的 Legacy/READY 重名冲突保持安全 409，未知异常保持固定脱敏 500。
- active 普通 user actor 的越权路径均写 denied audit；目标普通 user 为 L2，super_admin 目标或 `role=super_admin` 请求为 L3。
- 旧 mutator 直接调用不能影响 super_admin。
- TEMP users 不能影响 actor、target、count、policy 或 audit role。
- API 状态、脱敏、伪造 request principal 和自助密码回归。

SEC-1B1、SEC-1F0、用户删除及现有 feature / owner / history / asset / task / upload / WebSocket / settings / member-list 回归继续运行。

## 15. 未实现项

- production role/auth 或 audit migration activation。
- 首次 super_admin bootstrap 或任何真实 super_admin 账号。
- bootstrap 生命周期持久化、break-glass 或本机恢复。
- 完整 Capability / `require_capability`。
- Step-up Authentication、Operation Token 或管理前端角色 UI。
- super_admin 在线角色、密码、active、soft-delete 或 session 治理。
- apply-upgrade、restore、rollback 或任意 shell。

## 16. 后续关系

SEC-1C0 合并只代表仓库过渡保护和临时数据库证明完成，不代表生产 migration 已激活或 super_admin 已创建。当前生产仍为 LEGACY。

下一阶段是 SEC-1B2：在受控维护窗口激活 role/auth 与 audit migration，并执行首次本机 bootstrap。SEC-1B2 必须先独立加固 SEC-1B1 migration 中剩余未限定 `main.users` 的查询。本任务不实施该 activation。

SEC-1C 后续实现完整 Capability 门禁；SEC-1D 后续实现 Step-up Authentication 和 Operation Token。在线角色治理至少继续关闭到 SEC-1D 的高风险授权条件可用。
