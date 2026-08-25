# USER-GOV-MVP-1 固定三角色治理实施记录

更新时间：2026-08-25

## 1. 状态与范围

`USER_GOV_MVP_1_repository_implementation_present=true`

`USER_GOV_MVP_1_repository_implementation_independently_accepted=false`

本阶段仅实现固定 `user`、`admin`、`super_admin` 三角色治理，以及 `super_admin` only 的系统升级授权。当前实现仍在 Draft PR 中等待独立复核；本文不声称已经合并、生产部署或获得生产授权。

本阶段不引入动态角色、可配置 RBAC、Capability 平台、组织层级、DATA-1、数据库 migration/restore、OPS-3B 或第二套 Runtime/update engine。

## 2. 固定治理矩阵

| Actor | 创建普通成员 | 创建管理员 | 治理普通成员 | user/admin 角色变更 | 治理 super_admin | 系统升级 |
| --- | --- | --- | --- | --- | --- | --- |
| `super_admin` | 允许 | 允许 | 允许 | 允许 | 禁止 | 允许 |
| `admin` | 允许 | 禁止 | 允许 | 禁止 | 禁止 | 禁止 |
| `user` | 禁止 | 禁止 | 禁止 | 禁止 | 禁止 | 禁止 |

普通管理页面不能创建、降级、禁用、删除或重置 `super_admin`。`role` 是权威字段；`is_admin` 只作为兼容派生值，不再决定系统升级权限。

## 3. 角色写入安全契约

创建 admin 或执行 user/admin 角色变更必须同时满足：

- actor 是实时数据库中的 active `super_admin`，且 principal `auth_version` 仍匹配；
- 当前账号密码验证通过；Greenfield 首个 `super_admin` 与后续高风险密码确认共享同一个 `1024` 字符最大长度契约；
- 提供非空且有界的变更原因；
- 目标当前角色与 `auth_version` 符合请求中的期望值；
- mutation 与 mandatory `security.role.change` audit 在同一数据库事务中提交；
- 目标 `auth_version` 原子递增，使现有目标会话失效；
- stale target、审计失败或 readback 不一致均 fail closed，不提交部分变更。

密码、Token、Cookie 和完整 traceback 不写入审计上下文或公共错误详情。

## 4. 系统升级权限

`system_update` 的有效授权固定为：全局开关开启且当前实时角色为 `super_admin`。admin 的历史 per-user `system_update=allow` 数据保留以避免破坏既有数据，但计算时忽略，管理 API 不再允许新增或删除该 override，普通 purge 也不会借机删除历史记录。

升级 API 自身再次检查实时 `super_admin` 角色，因此即使外围 feature helper 被错误替换或绕过，admin 仍不能执行 check、prepare、execute 或诊断操作。管理页面的升级入口只对 `super_admin` 显示。

## 5. 用户界面

管理后台准确显示普通成员、管理员、超级管理员，并提供对应筛选。super_admin 可在创建成员时选择普通成员或管理员，也可通过独立角色变更对话框执行 user/admin 变更；这两类敏感操作均要求当前密码和原因。admin 只能创建和治理普通成员，界面不提供管理员创建、角色变更或系统升级入口。

开发设备浏览器检查已覆盖三角色渲染、创建管理员表单和角色变更表单；该检查不是生产验收。

## 6. 测试证据边界

仓库测试覆盖：

- super_admin 创建 admin、user→admin、admin→user；
- admin 创建 admin、角色变更和升级操作拒绝；
- 当前密码错误、空原因、stale target 与 mandatory audit 失败；
- atomic rollback、角色/`auth_version` readback 和旧 JWT 失效；
- 两个相同目标状态的真实并发角色变更只允许一次提交，另一请求以 stale conflict 拒绝；
- 普通在线创建 API 对 `super_admin` 请求执行 L3 审计拒绝，不产生账号；
- super_admin 普通页面保护；
- 历史 system_update override 保留但不生效、不可新增/删除且不出现在普通 readback；
- UPDATE-MVP-1、SEC-1B1、SEC-1C0、SEC-1F0、Manifest v2、current-release、portable lifecycle、STAB-1 与 OPS 相关回归。

最终测试计数与 Head 身份将在 Draft PR 正文中按实际执行结果记录。`production_touched=false`，未访问生产或临时业务测试环境。

## 7. 未实现边界

- `dynamic_RBAC_implemented=false`
- `capability_platform_implemented=false`
- `super_admin_online_lifecycle_management=false`
- `DATA_1_started=false`
- `database_migration_supported=false`
- `database_restore_supported=false`
- `OPS_3B_started=false`
- `production_validation=false`
- `production_approved=false`
- `production_touched=false`

停止点：提交 Draft PR 后等待独立代码、权限绕过、审计原子性、会话失效和 UI 行为复核。
