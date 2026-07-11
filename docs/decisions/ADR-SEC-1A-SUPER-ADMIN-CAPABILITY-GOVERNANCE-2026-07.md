# ADR SEC-1A：超级管理员、Capability 与高风险操作治理

- 状态：Accepted for staged implementation
- 日期：2026-07-10
- 代码核对基线：`main@dcb6629569246f58a2eda358d1073693376d6fa9`
- 决策范围：角色、授权、二次认证、高风险操作和安全审计的目标基线
- 实施状态：仅完成 ADR；尚未实施 schema、JWT、Capability、Operation Token、超级管理员账号或 UI

## 1. 文档定位

本文是 Infinite-Canvas-Enterprise 超级管理员角色、Capability 权限模型和高风险操作治理的正式决策基线。角色和治理方向已经由项目负责人确认，因此状态为 `Accepted for staged implementation`；合并本文后可以拆分实施任务，但不能据此宣称相关能力已经上线。

本文不替代具体数据库 migration、JWT / session 设计、管理 API、管理前端、OPS executor、恢复演练或生产升级计划。每个实施阶段仍须使用独立 Issue、独立分支、独立 Draft PR、针对性测试和项目负责人确认。

本文延续 [ARCH-2A 架构评估](../architecture/ARCH-2A-ARCHITECTURE-ASSESSMENT-AND-EVOLUTION-2026-07.md) 的原则：当前系统是企业安全增强型单机模块化单体，安全和数据一致性优先于扩容与平台化；规划能力不得写成当前能力。

## 2. 当前实现事实

以下事实来自对 `main@dcb6629569246f58a2eda358d1073693376d6fa9` 的代码核对。本 ADR 不修复这些问题。

| 主题 | 当前代码事实 | 影响 |
| --- | --- | --- |
| 用户角色 | `users` 表只有 `is_admin`，没有 `role`、`super_admin`、`auth_version`、`session_version`、`role_updated_at` 或 `role_updated_by` | 当前只有普通用户 / 管理员二级模型 |
| JWT | `create_token` 将 `is_admin` 写入 JWT | 角色状态被复制到长生命周期凭证 |
| Token 校验 | `verify_token` 只确认用户仍存在且处于 active，再返回原 JWT payload；不重新读取当前角色 | 角色变化后旧 Token 中的管理员状态不会立即同步 |
| 密码与会话 | 密码修改、密码重置和角色修改没有统一会话版本 | 未过期旧 Token 缺少确定的撤销机制 |
| 禁用与重新启用 | 禁用后 active 用户查询失败，旧 Token 暂时失效；重新启用后没有版本机制阻止未过期旧 Token 再次有效 | 禁用不能替代正式会话撤销 |
| 管理员 API | `_require_admin` 读取 request state 中 JWT payload 的 `is_admin` | 后端授权仍依赖旧 Token 中的角色快照 |
| 管理员互相治理 | 当前管理员可以修改其他管理员的角色、重置其密码、禁用或 soft delete 其他管理员 | 没有更高层级角色隔离 |
| 最后管理员保护 | 禁用和 soft delete 会保护最后一个 active admin；角色修改路径未使用同一保护 | 当前保护不完整，也不等同于最后超级管理员保护 |
| 自身操作 | 当前阻止管理员修改自身角色、禁用自身或删除自身 | 已有局部保护，但没有 Capability 或 Step-up 模型 |
| 更新入口 | `ENTERPRISE_UPDATE_ENABLED` 默认 `true`；feature flag 的 `system_update` 默认 false，但管理员在有效 feature 计算中直接 bypass | 管理员身份当前可能绕过 feature flag，语义与受控升级原则不一致 |
| 审计 | `usage_logs` 只有 `user_id`、`action`、`detail`、`ts` 等少量字段；`log_action` 写入异常会被忽略 | 不足以承载不可关闭、可关联、失败关闭的高风险安全审计 |
| 管理前端 | 成员管理和个人资料只展示 `is_admin` 对应的普通用户 / 管理员 | 当前没有超级管理员、Capability、Step-up 或 Operation Token UI |
| OPS | 已有 inventory、check-data、backup、validate-release、prepare-upgrade；prepare-upgrade 只生成 plan | apply-upgrade、restore 和 rollback executor 尚未实现 |

当前代码与旧文档中“管理员永远 bypass”的描述一致，但该描述只能作为现状记录，不能作为目标权限原则。目标模型中，管理员和超级管理员都必须受 Capability、生产开关、操作前置条件和审计约束。

## 3. 问题与决策摘要

### 3.1 为什么二级模型不足

当前管理员同时承担日常用户治理、owner 代管、feature flag、审计查看和系统更新相关能力。随着正式备份、恢复、回滚、数据库 migration、批量数据治理和遥测配置进入路线图，继续将所有治理操作放入一个 `is_admin` 布尔值会产生以下问题：

- 日常管理员获得超出工作需要的生产高危能力。
- 角色判断散落在 API、拦截器、WebSocket 和前端，难以审计。
- 无法区分“可以查看 / 准备”“可以批准”“可以执行”。
- 无法在不修改角色的前提下表达单次、短期、绑定目标的高危授权。
- 管理员身份可能被误解为可以绕过 release、backup、restore rehearsal 和 audit 等硬性条件。

### 3.2 最终决策

采用以下组合模型：

1. 固定基础角色：`user`、`admin`、`super_admin`。
2. 角色提供默认 Capability 集合，后端以 Capability 作为接口授权主依据。
3. L2 / L3 操作叠加 Step-up Authentication；L3 以及指定 L2 操作使用短期、单次、动作与目标绑定的 Operation Token。
4. 高风险流程使用独立的 prepare / approve / execute 状态，不以一个角色判断代替流程门禁。
5. mandatory security controls 高于所有人工角色。

统一层级为：

```text
user < admin < super_admin < mandatory security controls
```

`super_admin` 是系统内最高人工角色，但不是操作系统 root，也不是无限制应用账号。它不能执行任意 shell、关闭高风险审计、跳过备份或绕过升级前置条件。

### 3.3 role、Capability 与审批状态的区别

| 概念 | 回答的问题 | 生命周期 | 示例 |
| --- | --- | --- | --- |
| role | 用户在系统治理中的基础职责是什么 | 持久，变更需审计并撤销旧会话 | `admin` |
| Capability | 该用户当前是否允许请求某类后端动作 | 由当前角色和系统策略计算 | `ops.upgrade.prepare` |
| workflow state | 某个具体高风险操作是否完成必要步骤 | 绑定 operation / release / plan | `approved` |
| Operation Token | 本次具体动作是否刚完成二次认证且仍可单次执行 | 5–10 分钟、单次、绑定目标 | 对指定 `upgrade_plan_id` 执行升级 |

角色优先级不等于所有接口只比较 role 字符串，也不等于拥有 Capability 就能跳过流程状态或硬性安全门禁。

## 4. 备选方案

| 方案 | 描述 | 优点 | 问题 | 决策 |
| --- | --- | --- | --- | --- |
| 方案 1 | 继续使用 `is_admin` 二级模型 | 改动最小 | 无法隔离日常管理与高危执行，继续扩大 bypass | 不采用 |
| 方案 2 | 增加 `is_super_admin` 布尔字段 | 可快速出现第三级 | 会产生 `is_admin=false/is_super_admin=true` 等非法组合，组合判断继续散落，难以映射细粒度能力 | 不采用 |
| 方案 3 | `role` + Capability + Step-up Authentication | 角色语义单一、授权集中、可绑定高危流程和审计 | 需要分阶段 migration、后端门禁、会话和 UI 改造 | 采用 |

本阶段不立即引入可配置 `roles`、`permissions`、`role_permissions` 全套 RBAC 表，不允许管理员自由创建角色或组合权限。当前采用固定基础角色加代码定义 Capability，先建立可测试的安全边界；待 team / workspace 阶段再评估组织级 RBAC / ACL。

## 5. 基础角色模型

### 5.1 `user`

- 使用自身业务功能。
- 访问自身 owner 数据和显式授权数据。
- 不进入系统治理和 OPS 执行路径。
- 不能从请求体、feature override 或前端参数获得治理 Capability。

### 5.2 `admin`

- 执行日常用户和资源治理。
- 管理普通用户、分配 owner、查看审计。
- 执行低风险或只读 OPS：inventory、check-data、validate-release、prepare-upgrade、backup dry-run。
- 不执行正式生产升级、回滚、恢复、数据库 migration 或批量生产数据修复。
- 不创建、删除、降级、停用、重置密码或撤销会话的超级管理员。
- 不给自己或他人授予 / 撤销 `admin` 或 `super_admin`。

### 5.3 `super_admin`

- 包含管理员的日常治理能力。
- 承担角色治理、安全策略治理、高风险 OPS 批准和执行。
- 可以管理 admin；管理另一个 super_admin 时属于 L3。
- 仍受 Step-up、Operation Token、生产总开关、计划、manifest、维护模式、审计和其它 mandatory security controls 约束。
- 不能跳过 release validation、正式 backup、restore rehearsal、upgrade plan、data-check、rollback point 或审计。
- 不能执行任意 shell，也不能将白名单 OPS API 转换为通用命令执行器。

## 6. 目标用户数据模型

目标 `users` 模型至少包含：

- `role`：固定值 `user`、`admin`、`super_admin`。
- `auth_version`：会话安全版本。
- `role_updated_at`：最近角色变更时间。
- `role_updated_by`：最近角色变更执行者。

实现还需要能够判断超级管理员治理生命周期是否已完成首次 bootstrap，例如记录 `bootstrap_completed_at` 或等价元数据；本 ADR 只规定必须可区分生命周期状态，不决定最终表名、字段名或存储位置。

`is_admin` 可以在迁移期作为兼容字段保留，但它不是长期事实源。新权限判断不得继续散落地直接依赖 `is_admin`；兼容字段的写入、读取优先级和废弃时机由 SEC-1B migration 决定。

建议迁移映射：

- `is_admin=0` -> `role=user`
- `is_admin=1` -> `role=admin`

不得自动将任何现有管理员升级为 `super_admin`。本 ADR 不修改数据库结构。

## 7. Capability 模型

角色负责提供默认 Capability；服务端根据数据库中的当前角色、账号状态、`auth_version` 和系统策略计算有效 Capability。Capability 不允许由前端、请求体、user override 或 JWT 内的旧角色快照决定。

以下 44 个名称是实现建议基线，SEC-1B / SEC-1C 可以在不弱化语义的前提下调整命名。

### 7.1 用户与角色（12）

| Capability | 语义 |
| --- | --- |
| `users.read` | 读取授权范围内的用户信息 |
| `users.create` | 创建普通用户 |
| `users.update` | 更新普通用户资料 |
| `users.disable` | 启用或停用授权范围内的用户 |
| `users.delete` | 执行受保护的 soft delete |
| `users.password.reset` | 重置授权范围内用户密码 |
| `roles.admin.assign` | 授予管理员角色 |
| `roles.admin.revoke` | 撤销管理员角色 |
| `roles.super_admin.assign` | 授予超级管理员角色 |
| `roles.super_admin.revoke` | 撤销超级管理员角色 |
| `sessions.revoke` | 撤销目标用户指定会话 |
| `sessions.revoke_all` | 撤销目标用户全部会话 |

### 7.2 资源与数据治理（10）

| Capability | 语义 |
| --- | --- |
| `ownership.read` | 读取 owner 映射与差异 |
| `ownership.manage` | 单项 owner 分配或调整 |
| `ownership.bulk_plan` | 生成批量 owner 治理计划 |
| `ownership.bulk_execute` | 执行已批准的批量 owner 治理 |
| `data.check` | 执行只读数据完整性检查 |
| `data.reconciliation.plan` | 生成数据 reconciliation 计划 |
| `data.reconciliation.execute` | 执行已批准的数据 reconciliation |
| `data.migration.plan` | 生成数据库 migration 计划 |
| `data.migration.execute` | 执行已批准的数据库 migration |
| `data.sensitive_export` | 导出完整数据集或包含敏感字段的数据 |

### 7.3 安全治理（6）

| Capability | 语义 |
| --- | --- |
| `security.audit.read` | 查看安全审计 |
| `security.audit.export` | 导出限定时间、字段和范围的脱敏安全审计摘要 |
| `security.settings.read` | 读取安全配置摘要 |
| `security.settings.manage` | 修改允许在线管理的安全策略 |
| `security.telemetry.configure` | 配置远程遥测上传策略 |
| `security.emergency_recovery` | 进入受限的本机应急恢复流程 |

### 7.4 OPS（16）

| Capability | 语义 |
| --- | --- |
| `ops.inventory` | 运行只读 inventory |
| `ops.check_data` | 运行只读 check-data |
| `ops.release.validate` | 校验 release |
| `ops.release.approve` | 批准已校验 release 进入指定高危流程 |
| `ops.upgrade.read` | 查看升级状态、计划和报告 |
| `ops.upgrade.prepare` | 生成 upgrade plan，不执行升级 |
| `ops.backup.dry_run` | 生成 backup dry-run manifest |
| `ops.backup.execute` | 执行正式备份 |
| `ops.maintenance.enter` | 进入维护模式 |
| `ops.maintenance.exit` | 退出维护模式 |
| `ops.upgrade.approve` | 批准指定 upgrade plan |
| `ops.upgrade.execute` | 执行已批准的 upgrade plan |
| `ops.rollback.approve` | 批准指定 rollback plan |
| `ops.rollback.execute` | 执行已批准的 rollback plan |
| `ops.restore.approve` | 批准指定 restore plan |
| `ops.restore.execute` | 执行已批准的 restore plan |

前端只根据服务端返回的能力决定展示，不得自行计算 Capability。隐藏按钮只改善体验，伪造请求仍必须被后端拒绝。

## 8. 角色与 Capability 矩阵

符号说明：`允许` 表示角色可获得基础 Capability；`条件允许` 表示还必须通过 Step-up、Operation Token、目标范围或流程门禁；`拒绝` 表示该角色不能获得该能力。

| 操作 | 主要 Capability | 风险 | user | admin | super_admin | 额外条件 |
| --- | --- | --- | --- | --- | --- | --- |
| 使用自身业务功能 | 业务域 Capability | L0 | 允许 | 允许 | 允许 | owner / grant 校验 |
| 查看用户 | `users.read` | L1 | 拒绝 | 允许 | 允许 | admin 不得读取不必要的超级管理员敏感字段 |
| 创建普通用户 | `users.create` | L1 | 拒绝 | 允许 | 允许 | 不能通过创建接口指定更高角色 |
| 修改普通用户非安全资料 | `users.update` | L1 | 拒绝 | 允许 | 允许 | 仅 display name 等非安全资料，写入日常管理审计 |
| 启用普通用户 | `users.disable` | L1 | 拒绝 | 允许 | 允许 | 重新启用后旧 Token 仍必须因 `auth_version` 不匹配而失效 |
| 停用普通用户 | `users.disable` | L2 | 拒绝 | 条件允许 | 条件允许 | Step-up、reason、递增 `auth_version` |
| soft delete 普通用户 | `users.delete` | L2 | 拒绝 | 条件允许 | 条件允许 | Step-up、影响预览、明确确认、reason |
| 重置普通用户密码 | `users.password.reset` | L2 | 拒绝 | 条件允许 | 条件允许 | Step-up + Operation Token；admin 不能影响 super_admin |
| 撤销指定会话 | `sessions.revoke` | L2 | 拒绝 | 条件允许 | 条件允许 | Step-up、目标会话绑定 |
| 撤销全部会话 | `sessions.revoke_all` | L2 | 拒绝 | 条件允许 | 条件允许 | Step-up + Operation Token、递增 `auth_version` |
| 授予或撤销 admin | `roles.admin.assign`、`roles.admin.revoke` | L2 | 拒绝 | 拒绝 | 条件允许 | Step-up + Operation Token、reason、审计、会话撤销 |
| 授予或撤销 super_admin | `roles.super_admin.assign`、`roles.super_admin.revoke` | L3 | 拒绝 | 拒绝 | 条件允许 | Operation Token、最后超级管理员保护、不可关闭审计 |
| 读取 owner | `ownership.read` | L1 | 仅自身 | 允许 | 允许 | 目标范围限制 |
| 单项 owner 管理 | `ownership.manage` | L1 | 拒绝 | 允许 | 允许 | actor / before / after 审计 |
| 批量 owner 修复计划 | `ownership.bulk_plan` | L2 | 拒绝 | 条件允许 | 条件允许 | dry-run、范围、reason、审计 |
| 批量 owner 修复执行 | `ownership.bulk_execute` | L3 | 拒绝 | 拒绝 | 条件允许 | 已批准 plan、Operation Token、备份、审计 |
| reconciliation plan | `data.reconciliation.plan` | L2 | 拒绝 | 条件允许 | 条件允许 | 只生成 plan，不修改数据 |
| reconciliation execute | `data.reconciliation.execute` | L3 | 拒绝 | 拒绝 | 条件允许 | 已批准 plan、Operation Token、备份、审计 |
| 审计查看 | `security.audit.read` | L1 | 拒绝 | 允许 | 允许 | 服务端脱敏 |
| 审计摘要导出 | `security.audit.export` | L2 | 拒绝 | 条件允许 | 条件允许 | admin 可在 Step-up 后导出脱敏、限定时间、限定字段和限定范围的摘要；导出本身继续审计 |
| 安全设置读取 | `security.settings.read` | L1 | 拒绝 | 允许 | 允许 | 只返回脱敏摘要 |
| inventory | `ops.inventory` | L1 | 拒绝 | 允许 | 允许 | 只读 |
| check-data | `ops.check_data`、`data.check` | L1 | 拒绝 | 允许 | 允许 | 只读，不自动修复 |
| validate-release | `ops.release.validate` | L1 | 拒绝 | 允许 | 允许 | 只读校验 |
| release approve | `ops.release.approve` | L3 | 拒绝 | 拒绝 | 条件允许 | 校验成功、manifest / checksum、Operation Token |
| 查看升级状态和计划 | `ops.upgrade.read` | L1 | 拒绝 | 允许 | 允许 | 只读、脱敏 |
| prepare-upgrade | `ops.upgrade.prepare` | L2 | 拒绝 | 条件允许 | 条件允许 | 只生成 plan；Step-up、输入报告齐全 |
| backup dry-run | `ops.backup.dry_run` | L1 | 拒绝 | 允许 | 允许 | 不得隐式升级为 execute |
| backup execute | `ops.backup.execute` | L3 | 拒绝 | 拒绝 | 条件允许 | Step-up、Operation Token、明确确认、结果审计 |
| 维护模式进入 / 退出 | `ops.maintenance.enter`、`ops.maintenance.exit` | L3 | 拒绝 | 拒绝 | 条件允许 | 已批准 operation、任务处置、Operation Token |
| apply-upgrade | `ops.upgrade.approve`、`ops.upgrade.execute` | L3 | 拒绝 | 拒绝 | 条件允许 | 全部硬性升级门禁；当前未实现 |
| rollback | `ops.rollback.approve`、`ops.rollback.execute` | L3 | 拒绝 | 拒绝 | 条件允许 | rollback plan / point、Operation Token；当前未实现 |
| restore | `ops.restore.approve`、`ops.restore.execute` | L3 | 拒绝 | 拒绝 | 条件允许 | restore plan、隔离演练、Operation Token；当前未实现 |
| migration plan | `data.migration.plan` | L2 | 拒绝 | 条件允许 | 条件允许 | dry-run、临时数据库、备份和 rollback 设计 |
| migration execute | `data.migration.execute` | L3 | 拒绝 | 拒绝 | 条件允许 | 已批准 plan、维护模式、Operation Token |
| 安全配置管理 | `security.settings.manage` | L2 | 拒绝 | 拒绝 | 条件允许 | Step-up + Operation Token；硬性安全门禁不可关闭 |
| 遥测配置 | `security.telemetry.configure` | L3 | 拒绝 | 拒绝 | 条件允许 | 明确目的地、数据范围、Operation Token |
| 本机应急恢复 | `security.emergency_recovery` | L3 | 拒绝 | 拒绝 | 仅本机 break-glass | 系统无 active super_admin、离线流程、不可关闭审计 |
| 敏感数据导出 | `data.sensitive_export` | L3 | 拒绝 | 拒绝 | 条件允许 | 完整或含敏感字段的数据；Operation Token、reason、不可关闭审计 |

`admin` 可以 prepare，但不能 approve 或 execute 生产高危流程。单超级管理员环境中，同一账号可以依次 prepare、approve、execute，但三个步骤必须保持独立状态、使用对应 Capability，并分别写入审计；禁止单击即升级。

## 9. 高风险操作分级

| 等级 | 典型操作 | 最低角色 | 重新认证 | Operation Token | reason | plan / manifest | 强制审计 | API 自动调用 | 批量执行 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| L0 普通业务 | 画布、生成图片、查看自身数据 | user | 否 | 否 | 否 | 否 | 按业务审计策略 | 可在已认证业务 API 中调用 | 仅业务定义范围 |
| L1 日常管理 | 创建普通用户、修改非安全资料、启用普通用户、单项 owner、查看审计、只读 OPS | admin | 通常否 | 否 | 破坏性动作需要 | 只读报告或单项目标 | 是 | 允许白名单 API，不允许通用命令 | 仅受限、可回退的小批量 |
| L2 敏感管理 | 停用 / soft delete 普通用户、密码重置、授予 admin、撤销全部会话、审计摘要导出、批量治理计划、安全策略 | admin 或 super_admin，按矩阵 | 必须 | 指定动作需要 | 是 | dry-run / plan 或目标摘要 | 是 | 仅显式交互的白名单 API | 只允许先 plan / preview |
| L3 生产高危 | super_admin 变更、backup execute、维护模式、升级、回滚、恢复、migration、批量修复、敏感导出、遥测上传 | super_admin | 是 | 必须 | 必须 | 必须有对应 plan / manifest / preconditions | 不可关闭，写入失败则 fail closed | 禁止无人值守或任意 API 自动触发 | 仅执行已批准、范围固定的 plan |

风险级别与角色不是同一维度。某个 L2 动作可以要求 super_admin；某个 super_admin 执行 L1 也不能省略其正常审计。

## 10. 强制安全规则

### 10.1 最后一个 active super_admin

系统不得：

- 删除、soft delete 或停用最后一个 active super_admin。
- 将最后一个 active super_admin 降级。
- 通过批量操作影响最后一个 active super_admin。
- 允许最后一个 active super_admin 自行降级。
- 通过 user override、兼容字段或 migration 绕过该保护。

保护必须在数据库事务内基于当前状态重新判断，不能只依赖前端按钮状态或请求前缓存。进入 `ACTIVE` 状态后，所有正常在线角色管理事务不得将 active super_admin 数量降为零；`UNINITIALIZED` 和 `RECOVERY_REQUIRED` 是受限状态，L3 全部关闭，只允许本机 bootstrap 或 break-glass。具体状态存储、约束与并发处理由 SEC-1B1 / SEC-1B2 / SEC-1C 设计。

### 10.2 禁止自我提权

任何角色不得：

- 通过请求体给自己增加 role 或 Capability。
- 通过 feature / user override 获得 `super_admin` 能力。
- 通过前端参数指定自身角色。
- 通过普通管理员 API 授予自己 admin 或 super_admin。
- 将 Operation Token 用于其未绑定的 capability、action 或 target。

### 10.3 角色管理边界

admin 不能修改、删除、停用、重置密码或撤销会话的 super_admin，也不能授予或撤销 admin / super_admin。super_admin 可以管理 admin；super_admin 管理另一个 super_admin 时一律按 L3 处理。

### 10.4 高危升级门禁

即使 actor 是 super_admin，以下任一条件不满足也必须拒绝 upgrade execute：

- release 未通过校验。
- release manifest 不存在。
- checksum 不匹配。
- 正式 backup 不存在。
- backup manifest 的 `dry_run=true`。
- SQLite backup 未成功。
- restore rehearsal 未完成或结果不可接受。
- upgrade plan 不存在、过期或与 release / backup 不匹配。
- check-data 存在 critical。
- 未进入维护模式。
- 活跃任务未按 plan 排空、完成或明确处置。
- rollback point 不存在或未验证。
- Operation Token 无效、过期、已使用或绑定目标不匹配。
- 强制安全审计不可写入。

这些门禁是逻辑 AND，不得用 super_admin、feature flag、网页确认或 `ENTERPRISE_UPDATE_ENABLED` 单独替代。

### 10.5 审计不可绕过

admin 和 super_admin 都不能关闭高风险安全审计。L3 操作的强制审计无法持久化时，操作必须 fail closed；不得先执行再尝试补记。

## 11. 会话撤销与 `auth_version`

JWT 不应长期信任 Token 内的 role、`is_admin` 或未来 `is_super_admin`。目标 JWT 至少保存：

- `user_id`
- `session_id` 或 token id
- `auth_version`
- `iat`
- `exp`

每次授权必须从数据库重新读取：

- `role`
- `is_active`
- `auth_version`

以下操作必须递增 `auth_version`：

- 用户修改密码。
- 管理员重置密码。
- 角色修改。
- 用户停用。
- soft delete。
- 强制退出全部设备。
- 安全事件处置。
- 超级管理员降级或撤销。

Token 中的 `auth_version` 与数据库不一致时，旧 Token 立即失效。重新启用用户不得恢复旧 Token 有效性。角色与 Capability 只能使用数据库当前状态计算；JWT 可以携带显示信息，但不能成为角色授权事实源。

本节只定义决策，SEC-1B 负责 schema、migration、JWT 加载和测试。

## 12. Step-up Authentication 与 Operation Token

所有 L2 / L3 操作都必须重新认证。所有 L3 操作必须使用 Operation Token；以下 L2 操作也必须使用 Operation Token：密码重置、授予 / 撤销 admin、撤销目标用户全部会话和安全设置修改。`security.audit.export` 要求 Step-up、限定时间 / 字段 / 范围和导出审计，但本基线不强制 Operation Token。只生成 plan / preview 的其它 L2 操作至少要求 Step-up，SEC-1D 可根据威胁模型进一步扩大 Operation Token 范围，但不得缩小上述基线。

L2 / L3 二次认证流程：

1. 用户先完成普通登录。
2. 请求 Step-up 时重新输入当前密码。
3. 服务端重新读取 `user_id`、`role`、`is_active`、`auth_version`。
4. 服务端验证该角色当前具有目标 Capability。
5. 验证 CSRF / Origin 和请求上下文。
6. 签发 5–10 分钟有效、单次使用、绑定动作与目标的 Operation Token。
7. 执行端再次读取当前角色、active 状态和 `auth_version`，并原子消费 Token。
8. 使用成功、角色变化、`auth_version` 变化或到期后立即失效。

Operation Token 至少绑定：

- `actor_user_id`
- `actor_role`
- `capability`
- `action`
- `target_type`
- `target_id`
- `release_id`
- `upgrade_plan_id`
- `backup_id`
- `operation_id`
- `auth_version`
- `issued_at`
- `expires_at`
- `nonce`

不适用字段可以为空，但 action、capability、actor、operation、auth version、时间和 nonce 不得缺失。Token 不能作为普通登录 Token 使用，不能存入浏览器持久存储，不能跨 action / target / release / plan / backup 复用，不能在日志中记录明文。

本 ADR 不实现 Step-up 或 Operation Token。

## 13. 超级管理员治理生命周期、初始化与 break-glass

### 13.1 生命周期状态

| 状态 | 判定 | 允许行为 | 禁止行为 |
| --- | --- | --- | --- |
| `UNINITIALIZED` | 从旧 `is_admin` 模型迁移后，尚未完成首次 super_admin bootstrap | 普通业务继续；只允许生产主机本机首次 bootstrap | 所有 L3；远程 bootstrap；普通角色管理创建 super_admin |
| `ACTIVE` | 首次 bootstrap 已完成，且至少存在一个 active super_admin | 正常业务、受授权治理和满足门禁的高危流程 | 任何正常在线事务将 active super_admin 数量降为零 |
| `RECOVERY_REQUIRED` | 系统曾完成 bootstrap，但当前没有 active super_admin | 普通业务继续；只允许生产主机本机 break-glass 恢复 | 所有 L3；重新走首次 bootstrap；远程恢复 |

状态转换规则：

- SEC-1B1 只准备并使用临时数据库验证 migration 与 JWT 当前状态加载，不开放在线角色写入，也不激活生产 migration。
- `UNINITIALIZED -> ACTIVE`：SEC-1B2 在 SEC-1F0 可用后激活 migration，再执行本机首次 bootstrap；两个动作都必须写入强制审计。
- `ACTIVE` 的正常在线事务必须维持至少一个 active super_admin。
- 如果损坏、异常 migration 或离线事故导致已初始化系统变为零 active super_admin，系统进入 `RECOVERY_REQUIRED`，不得退回 `UNINITIALIZED`。
- `RECOVERY_REQUIRED -> ACTIVE`：仅通过本机 break-glass 恢复并成功写入强制审计。

实现可以记录 `bootstrap_completed`、`bootstrap_completed_at` 或等价元数据，以区分从未初始化与初始化后异常；本 ADR 不决定最终表结构。

### 13.2 首次 bootstrap

禁止：

- 将所有现有管理员自动升级为超级管理员。
- 每次启动根据 env 持续自动提权。
- 系统任意选择一个管理员升级。
- 通过普通网页注册或管理员 API 创建第一个超级管理员。

允许的 staged design：

1. SEC-1B1 建立 `role`、`auth_version`、migration 和 JWT 当前状态加载，并使用临时数据库验证 `is_admin` 到 `user` / `admin` 的映射；不激活生产 migration，不开放在线角色写入，也不执行 bootstrap。
2. SEC-1F0 建立可 fail closed 的最小 `security_audit_events` 写入基础。
3. SEC-1B2 激活 migration，将现有 `is_admin` 映射为 `user` / `admin`，写入 migration activation 审计，系统进入 `UNINITIALIZED`。
4. 项目负责人明确指定一个现有管理员用户名。
5. 通过生产主机本机维护命令或一次性 bootstrap 配置执行。
6. 仅在 `UNINITIALIZED` 且系统不存在任何 super_admin 时允许。
7. 操作要求本机交互、明确确认，并在角色变更前成功写入强制审计。
8. 一次性配置成功后必须标记已消费或由项目负责人人工移除，生命周期进入 `ACTIVE`。

bootstrap 命令不得成为远程通用提权 API，也不得接受任意 SQL 或 shell。首次 bootstrap 不得早于 SEC-1F0。

### 13.3 `RECOVERY_REQUIRED` 与 break-glass

如果已完成 bootstrap 的系统因损坏、异常 migration 或离线事故而没有 active super_admin，必须进入 `RECOVERY_REQUIRED`：

- 普通业务和 owner 隔离继续运行。
- 所有 L3 操作自动禁用。
- 系统输出不含敏感信息的高优先级安全告警。
- 只允许在生产主机本机使用离线 break-glass 流程恢复一个明确账号。
- break-glass 必须验证 bootstrap 曾完成且当前确实无 active super_admin，记录原因、actor / operator、时间、目标账号和结果。
- break-glass 事件必须通过 SEC-1F0 append-only 接口写入；强制审计写入失败时恢复 fail closed。
- 恢复后必须递增目标 `auth_version`，撤销旧会话并复核审计。

`security.emergency_recovery` 不是远程万能权限，而是对本机受限恢复实现的命名边界。

### 13.4 数量策略

- 系统允许多个 super_admin。
- 进入 `ACTIVE` 后，正常在线角色管理事务必须保护至少一个 active super_admin。
- 小规模部署可以只有一个。
- 生产最佳实践建议至少两个相互独立的超级管理员账号，但初期不作为硬性门禁。
- 双人审批可作为后续增强，不属于 SEC-1A 或首轮实现。

## 14. 安全审计模型

现有 `usage_logs` 不足以表达角色快照、Capability、风险等级、operation、request、release、backup、plan、before / after 和结构化结果，也不能保证写入失败时阻止 L3 或 bootstrap。首次 bootstrap 之前必须先由 SEC-1F0 建立最小强制审计基础；后续 SEC-1F 再完成查询、导出、保留和归档能力。

### 14.1 SEC-1F0：Minimal Mandatory Security Audit Foundation

SEC-1F0 至少包括：

- `security_audit_events` 最小 schema。
- 单向 append-only 写入接口，不提供普通删除或更新接口。
- migration activation、bootstrap、role change 和 break-glass 事件。
- 禁止记录密码、JWT、Cookie、Operation Token、API Key 和 env value。
- L3 / bootstrap 强制审计写入失败时 fail closed。
- 使用临时数据库覆盖 schema、append-only、脱敏字段和 fail-closed 行为的测试。

SEC-1F0 暂不包括：

- 管理后台页面。
- 复杂查询。
- 导出。
- 归档。
- 保留周期。
- 远程日志平台。

SEC-1F0 是 SEC-1B2 首次 bootstrap 的前置门禁，不代表完整安全审计系统已经实现。

SEC-1F0 的仓库实现见 [SEC-1F0：最小强制安全审计基础](../security/SEC-1F0-MANDATORY-SECURITY-AUDIT-IMPLEMENTATION-2026-07.md)。该阶段只提供显式 migration、append-only writer、敏感字段拒绝和 fail-closed 底层异常；完整查询、导出、保留和归档仍属于 SEC-1F。

SEC-1C0 的仓库实现见 [SEC-1C0：首次 bootstrap 前的超级管理员过渡保护](../security/SEC-1C0-SUPER-ADMIN-TRANSITIONAL-PROTECTION-2026-07.md)。该阶段建立 admin / target 过渡保护、原子 mandatory audit 和最后 active super_admin helper，但在线角色及 super_admin 安全治理仍关闭；完整 Capability 属于 SEC-1C，Step-up / Operation Token 属于 SEC-1D，首次本机 bootstrap 属于 SEC-1B2。

### 14.2 完整安全审计目标

目标字段至少包括：

- `event_id`
- `actor_user_id`
- `actor_role`
- `capability`
- `action`
- `risk_level`
- `target_type`
- `target_id`
- `operation_id`
- `request_id`
- `release_id`
- `backup_id`
- `upgrade_plan_id`
- `reason`
- `result`
- `error_code`
- `source_ip`
- `user_agent`
- `before_summary`
- `after_summary`
- `created_at`

禁止记录：密码、JWT、Cookie、Operation Token、API Key、env value、完整请求体、用户提示词全文、图片或素材内容。摘要必须结构化、最小化并脱敏。

必须审计：

- 角色变化和 admin / super_admin 授予、撤销、降级。
- 强制会话撤销和 Step-up / Operation Token 的成功、拒绝、过期与重放。
- 高危安全配置变化。
- 正式备份、维护模式、升级、回滚、恢复和 migration。
- 批量数据治理、遥测策略变化和敏感导出。
- mandatory security control 的拒绝结果。
- break-glass 恢复。

admin 不可删除安全审计；super_admin 也不可通过普通管理 API 删除。保留周期、归档、离线防篡改和合法删除流程由独立任务设计。审计导出行为本身必须继续审计。

## 15. 升级工作流职责分离

升级至少使用四类 Capability：

- `ops.upgrade.read`
- `ops.upgrade.prepare`
- `ops.upgrade.approve`
- `ops.upgrade.execute`

admin 可以 read / prepare，super_admin 可以 read / prepare / approve / execute。角色 Capability 只是第一层；实际 execute 还必须通过 release validation、executed backup、restore rehearsal、check-data、upgrade plan、maintenance mode、active task drain、rollback point、Operation Token 和 audit。

当前 `prepare-upgrade` 只生成非执行型 plan。现有 backup success 不等于 restore rehearsal 或生产升级完成。在 restore / rollback 演练和强制门禁未落地前，不得将 apply-upgrade 接入网页 Update Center。

即使当前只有一个项目负责人，prepare、approve、execute 也必须是三个独立状态和三条独立审计事件。未来可以增加双人审批，但不能在当前文档中写成已实现。

## 16. 管理后台未来行为

本 ADR 不修改页面。后续管理后台应：

- 明确显示 `user` / `admin` / `super_admin`，中文为“普通用户 / 管理员 / 超级管理员”。
- 对角色变化和高风险操作显示醒目警告、目标对象和影响摘要。
- 普通管理员不显示 super_admin 管理按钮。
- 普通管理员伪造请求时仍由后端拒绝。
- 最后一个超级管理员的降级、停用和删除由后端拒绝，不能只禁用按钮。
- L2 / L3 操作要求重新认证，显示 Operation ID 以及目标 release / backup / plan。
- 不提供任意 shell 输入框。
- 不在浏览器持久保存密码或 Operation Token。
- 页面关闭、登出、角色或 `auth_version` 变化后不复用高危授权。

## 17. 错误与拒绝语义

| HTTP | error code | 语义 |
| --- | --- | --- |
| 401 | 会话失效或未登录 | 需要重新登录，不泄露账号状态细节 |
| 403 | `ROLE_REQUIRED` | 当前基础角色不足 |
| 403 | `CAPABILITY_REQUIRED` | 当前有效 Capability 不足 |
| 403 | `STEP_UP_REQUIRED` | 需要二次认证 |
| 403 | `LAST_SUPER_ADMIN_PROTECTED` | 最后 active super_admin 保护 |
| 403 | `SELF_ESCALATION_DENIED` | 禁止自我提权 |
| 403 | `HIGH_RISK_PRECONDITION_FAILED` | 高危前置条件失败；响应只给安全摘要和 operation id |
| 409 | `ROLE_STATE_CONFLICT` | 角色状态或并发变更冲突 |
| 409 | `OPERATION_ALREADY_USED` | Operation Token 已使用或重放 |
| 410 | `OPERATION_TOKEN_EXPIRED` | Operation Token 已过期 |

错误响应不得包含密码、Token、Cookie、API Key、env value、内部文件绝对路径或完整异常栈。

## 18. 实施阶段拆分

| 任务 | 范围 | 明确不混入 |
| --- | --- | --- |
| SEC-1B1 | `role`、`auth_version`、migration、JWT 当前状态加载和旧 Token 撤销的实现与临时数据库验证 | 生产 migration activation、在线角色写入、首次 super_admin bootstrap、Capability UI、OPS executor |
| SEC-1F0 | 最小 `security_audit_events` schema、append-only 写入、bootstrap / role change / break-glass、脱敏禁记、L3 / bootstrap fail closed、临时数据库测试 | 管理页面、复杂查询、导出、归档、保留周期、远程日志 |
| SEC-1C0 | 首次 bootstrap 前的 super_admin 过渡保护：admin 不得修改其角色、重置密码、启停、soft delete 或撤销会话；最后 active super_admin 保护与禁止自行提权 | 完整 Capability 矩阵、Step-up UI、升级执行 |
| SEC-1B2 | migration activation、本机首次 super_admin bootstrap 和一次性配置消费；依次进入 `UNINITIALIZED`、`ACTIVE` | 早于 SEC-1F0 / SEC-1C0 执行、远程提权、自动升级现有管理员 |
| SEC-1C | `require_role`、`require_capability`、最后超级管理员保护、防自我提权、admin 不得影响 super_admin | Step-up UI、升级执行 |
| SEC-1D | 重新认证、单次短期 Operation Token、action / target 绑定、replay protection、CSRF / Origin | 管理后台大改版 |
| SEC-1E | 角色展示、角色调整、高风险警告、二次认证 UI、浏览器回归 | 数据库和 OPS 大重构 |
| SEC-1F | 完整安全审计查询、脱敏摘要导出、保留和归档策略 | 远程日志平台或遥测实现 |
| SEC-1U | `system_update` bypass、`ENTERPRISE_UPDATE_ENABLED` 默认策略、super_admin approve / execute、白名单 OPS、禁止任意 shell | 通用 shell、未演练 apply-upgrade |
| OPS-2C | Release Builder | upgrade executor |
| OPS-4A | Restore / Rollback Rehearsal | 网页一键升级 |
| OPS-4B | Controlled Maintenance Upgrade Executor | 未通过门禁的生产执行 |

推荐实施顺序为：SEC-1B1 -> SEC-1F0 -> SEC-1C0 -> SEC-1B2 -> SEC-1C -> SEC-1D -> SEC-1E -> SEC-1F -> SEC-1U。SEC-1B 可以保留为总任务，但首次 bootstrap 不得早于 SEC-1F0 和 SEC-1C0。这些任务不得合并成一个大 PR，SEC-1A 本身不实施任何一项代码。

实施顺序安全澄清：SEC-1C0 只实现首个 super_admin 出现前必须具备的过渡保护，不提前实现完整 Capability。它必须确保 admin 无法修改 super_admin 角色、重置其密码、启停、soft delete 或撤销其会话，禁止自行提权，并保证正常在线事务不能把 active super_admin 数量降为零。PR #72 不实现 SEC-1C0，也不创建 super_admin；SEC-1B2 不得早于 SEC-1C0。

## 19. 后续测试与验收矩阵

后续实现至少使用：`user_a`、`user_b`、`admin_a`、`super_admin_a`，可选 `super_admin_b`。测试必须使用临时数据库和测试数据，不读取或修改生产。

### 19.1 角色与会话

- 普通用户不能进入管理接口。
- 管理员不能授予或撤销管理员。
- 管理员不能创建、修改、停用、删除、重置密码或撤销会话的超级管理员。
- 超级管理员可以授予 / 撤销管理员。
- 超级管理员授予或管理另一个超级管理员需要 L3 门禁。
- 禁止通过请求体、override 或直接 API 自我提权。
- `UNINITIALIZED` 只允许本机首次 bootstrap，普通业务继续且 L3 全部拒绝。
- `ACTIVE` 下的并发角色事务不能将 active super_admin 数量降为零。
- `RECOVERY_REQUIRED` 只允许本机 break-glass，普通业务继续且 L3 全部拒绝。
- 最后一个 active super_admin 不能被降级、停用、soft delete 或删除。
- 角色变化、密码变化、禁用和 soft delete 后旧 Token 立即失效。
- 重新启用后旧 Token 不得恢复有效。
- 并发降级 / 停用请求不能绕过最后超级管理员保护。

### 19.2 高风险操作

- admin 可以 prepare，不能 approve / execute。
- super_admin 无 Step-up / Operation Token 时不能 execute。
- Operation Token 过期、重放、已使用或 `auth_version` 不匹配时拒绝。
- Token 绑定错误 release / plan / backup / target 时拒绝。
- release 校验失败、manifest 缺失或 checksum 不匹配时拒绝。
- backup manifest `dry_run=true` 或 SQLite backup 失败时拒绝。
- check-data 存在 critical 时拒绝。
- restore rehearsal、maintenance mode、task drain 或 rollback point 缺失时拒绝。
- SEC-1F0 必须先于首次 bootstrap 可用，并使用临时数据库验证 append-only 与敏感字段禁记。
- L3、首次 bootstrap 或 break-glass 的强制审计写入失败时，动作 fail closed 且不产生部分执行。
- 前端隐藏、直接 API、刷新 / 重登和 WebSocket 路径都不能绕过后端授权。

每个权限实现 PR 还必须覆盖列表过滤、直接 ID、资源 URL、刷新 / 重登和相关 WebSocket 事件；前端行为不能替代后端用例。

## 20. 非目标

本 ADR 不设计或实现：

- 完整组织架构、workspace、department 或自定义角色编辑器。
- 任意权限组合 UI、SaaS 多租户或组织级 ACL。
- OAuth、SSO、LDAP、TOTP 或硬件密钥实现。
- 双人审批实现。
- apply-upgrade、rollback executor 或 restore executor。
- PostgreSQL、Redis、Docker 或对象存储。
- 超级管理员账号创建、数据库 migration、JWT 改动或页面改动。
- 自动修复生产 owner map、直接修改生产数据库或执行生产命令。

这些内容可以在独立阶段扩展，但不能作为 SEC-1A 已完成能力。

## 21. 后果与约束

收益：

- 日常治理与生产高危执行有明确隔离。
- 角色、能力、流程状态和单次授权各自职责清晰。
- 为会话撤销、升级门禁和专用安全审计提供统一术语。
- 支持单超级管理员小规模部署，同时保留多超级管理员和未来双人审批扩展。

代价：

- 需要 schema、会话、授权、审计和 UI 多阶段改造。
- 迁移期必须谨慎处理 `is_admin` 兼容和旧 Token。
- 高危操作步骤增加，但这是生产安全门禁的必要成本。

持续约束：任何后续实现不得将 super_admin 写成无限制 root，不得用角色比较替代 Capability 与 mandatory security controls，不得在没有备份、恢复演练、rollback point 和审计时开放生产升级。
