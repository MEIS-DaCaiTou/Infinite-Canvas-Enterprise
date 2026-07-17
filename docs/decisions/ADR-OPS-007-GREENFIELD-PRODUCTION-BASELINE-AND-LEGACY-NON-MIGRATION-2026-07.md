# ADR-OPS-007：全新生产基线部署与旧生产非迁移

- 状态：Accepted
- 决策日期：2026-07-17
- 决策人：Infinite-Canvas-Enterprise 项目负责人
- 事实基线：`main@396cccc68d63bd16393a2cb72d24e4a48fcf47cb`
- 文档收口分支：`docs/env-1b0-architecture-decisions`
- 当前关联 PR：Draft PR #80
- 实施状态：仅完成生产路线决策；未停止或删除旧生产，未部署新生产，未实施 Fresh Install Bootstrap
- 约束效力：自本 ADR 接受之日起，作为后续项目规划、任务拆解、Codex 实施、PR 审查和生产准入判断的强制前提

## 1. 背景

Infinite-Canvas-Enterprise 当前已经形成企业网关、用户和管理员治理、owner 数据隔离、WebSocket 隔离、权限开关、安全审计基础、Windows Runtime Supervisor、生产盘点与备份工具、在线更新准备和受控安全迁移基础。

现有生产设备仍运行历史旧版本。当前仓库基线、ENV-1 路线、Runtime、Release、数据治理和 OPS 能力仍在持续开发，尚未形成可以长期稳定部署、维护、恢复及迭代升级的正式生产基线版。

项目负责人现决定，不再将旧生产系统作为新版上线的数据来源或原地升级目标。

## 2. 术语定义

### 2.1 旧生产版本

指本 ADR 接受前，已经部署在生产设备上的历史 Infinite-Canvas-Enterprise 版本及其数据库、JSON、资源文件、运行配置和业务数据。

旧生产版本从本 ADR 接受后定义为：

`legacy production / retirement candidate`

该状态不表示旧服务已经停止、旧目录已经删除或旧数据已经销毁。

### 2.2 全新生产部署

指在干净或受控清理后的生产环境中，使用正式不可变 Release、可信 Runtime、全新配置、全新数据库和全新账号完成安装，不从旧生产版本导入业务数据或运行状态。

### 2.3 生产基线版

指经过项目负责人明确验收，具备稳定开发、维护、部署、备份、恢复和持续迭代升级能力，并被批准首次部署到新生产环境的 Infinite-Canvas-Enterprise 正式版本。

形成代码提交、合并 PR 或开发设备验证，不自动等于形成生产基线版。

## 3. 正式决策

### 3.1 采用 Greenfield 全新部署

Infinite-Canvas-Enterprise 后续生产路线采用全新部署，不采用旧生产原地升级。

目标流程为：

```text
继续开发和验证企业基线
→ 建立可信不可变 Release
→ 建立全新安装和首次安全初始化能力
→ 完成备份、恢复和版本升级演练
→ 项目负责人批准生产基线版
→ 在生产设备全新部署
→ 创建全新账号、数据库和配置
→ 完成生产业务验收
→ 再单独决定旧生产退役和数据处置
```

### 3.2 明确禁止旧生产数据迁移

新版生产环境不得自动或批量迁移下列旧生产内容：

- 旧用户、管理员及密码数据；
- 旧 SQLite 数据库；
- 旧项目、画布和对话；
- 旧生成历史；
- 旧素材库和素材业务对象；
- 旧上传文件、输入文件、输出文件和缓存；
- 旧任务及任务 owner 映射；
- 旧项目、画布、对话、资源、历史和素材 owner map；
- 旧 Feature Flag 和用户 override；
- 旧日志、Runtime State 和 OPS Job 状态；
- 旧 `enterprise.env`；
- 旧 Provider 配置；
- 旧 API Key、Token、Cookie、JWT Secret、密码或其它凭据；
- 旧 Python Runtime、依赖目录或本机缓存。

需要继续使用的 Provider 和外部服务凭据，必须由项目负责人在新生产环境重新配置，不得由迁移脚本复制。

### 3.3 旧生产数据问题不再阻塞新基线

旧生产中的下列问题不再作为新版生产基线形成的 blocker：

- unowned 数据；
- orphan owner map；
- missing file；
- 旧 Schema；
- 旧账号和角色结构；
- 旧目录结构；
- 旧配置格式；
- 旧运行时依赖；
- 旧生产 `check-data` warning。

旧生产盘点和正式备份结果继续作为历史运维证据保存，但不再承担新版迁移输入或升级门禁作用。

### 3.4 不在旧生产执行 SEC-1B2

不得为了新生产基线在旧生产数据库上执行：

- SEC-1B1 role/auth migration；
- SEC-1F0 security audit activation；
- SEC-1B2 migration activation；
- 旧管理员到 `super_admin` 的 bootstrap；
- 任何面向旧数据的 owner reconciliation 或自动修复。

现有 SEC-1B1、SEC-1F0、SEC-1C0 和 SEC-1B2 仓库实现仍保留为：

- 已完成的安全基础；
- migration 和事务治理参考；
- 临时数据库测试能力；
- 未来兼容场景的可复用组件；
- 后续 Fresh Install Bootstrap 的设计输入。

本决策不声称删除或废弃这些代码。

### 3.5 新增 Fresh Install Bootstrap 前置能力

正式生产基线版必须具有面向空环境的首次初始化能力。

该能力至少应支持：

```text
确认目标环境为允许初始化的空环境
→ 建立完整目标 Schema
→ 建立 schema version 和 migration history
→ 建立 mandatory security audit
→ 本机交互创建首个 super_admin
→ 建立不可变 bootstrap lifecycle marker
→ 原子提交
→ 输出脱敏初始化报告
→ 成功后拒绝重复初始化
```

Fresh Install Bootstrap：

- 尚未实现；
- 不得通过网页或远程 API 执行；
- 不得通过命令行参数、日志或报告记录明文密码；
- 不得依赖旧生产已有 admin；
- 不得被文档描述为当前已有能力；
- 必须在后续独立任务和独立 Draft PR 中设计、实现和验证。

### 3.6 保留未来版本 migration 能力

取消旧生产数据迁移，不等于取消数据治理和 migration。

新版正式投入生产后，仍必须支持：

- schema version；
- migration history；
- 新版本之间的数据库迁移；
- migration compatibility 分类；
- migration 前正式备份；
- rollback 或 restore 决策；
- 临时数据库 rehearsal；
- 生产维护窗口；
- 数据完整性验证；
- 失败后的受控恢复。

DATA-1、Manifest v2、数据库回滚分类和 restore rehearsal 继续保留为生产基线及后续迭代的重要门禁。

### 3.7 重新定义 OPS-3B

OPS-3B 不再用于将旧生产版本升级为新架构。

OPS-3B 的正式定位调整为：

> 在全新生产基线版已经部署并形成第一代新生产数据之后，为后续正式 Release 提供计划驱动的 apply、版本切换、健康验证、rollback 和 restore 能力。

任何 OPS-3B 实现仍必须后置于：

- 不可变 APP_ROOT；
- 路径根和版本目录；
- Release-bound Runtime；
- Manifest v2；
- DATA-1；
- 正式备份；
- restore rehearsal；
- 数据库 migration compatibility；
- Runtime Supervisor lifecycle 验证。

## 4. 生产基线版最低准入条件

### 4.1 Release 与 Runtime

- APP_ROOT 运行时不可变；
- 正式 Release 使用固定版本目录；
- `current-release.json` 或等效权威 Release 指针已经实现；
- 正式入口只使用 Release 绑定的可信 Python；
- PATH Python 和未批准的 `sys.executable` 回退被关闭；
- Runtime Manifest、依赖锁、wheelhouse、SBOM 和来源证据完整；
- Manifest v2 验证通过；
- static 内容哈希和 Release 证据一致；
- 干净 Windows 环境安装和启动验证通过。

### 4.2 安全初始化

- Fresh Install Bootstrap 已实现和验证；
- 全新数据库直接进入目标 Role/Auth Schema；
- 首个 `super_admin` 可由本机安全创建；
- mandatory security audit 从首次初始化开始存在；
- bootstrap marker 和审计证据一致；
- 默认 JWT Secret、默认密码和弱配置在生产模式下 fail closed；
- 未分类高风险 HTTP Route 和敏感 WebSocket Event 的默认策略已经收口；
- 登录限流、Cookie、跳转 URL、错误脱敏等生产安全门禁完成。

### 4.3 数据与恢复

- schema version 和 migration history 已实现；
- 全新数据库初始化可重复验证；
- 正式 backup execute 通过；
- restore rehearsal 通过；
- 数据库、JSON、资源、配置和启动链路均纳入恢复验证；
- migration compatibility 和 rollback 分类可验证；
- 不使用旧生产数据作为验收输入。

### 4.4 维护与迭代升级

- Runtime start、stop、restart、status 和 health 通过；
- 日志、状态、备份、缓存和配置位于 Release 目录之外；
- 至少完成一次新基线 Release 之间的受控升级演练；
- 升级失败后的 rollback 或 restore 路径通过；
- 不需要直接在生产目录执行 `git pull`、`checkout` 或覆盖复制；
- 项目负责人确认该版本已具备后续持续维护和迭代条件。

### 4.5 业务验收

至少覆盖：

- `super_admin`、admin、user A、user B；
- 登录、退出、禁用、重新登录和 Token 撤销；
- 项目、画布、对话；
- 上传资源、生成输出、历史、素材和任务；
- 直接 ID、资源 URL 和 WebSocket 越权；
- Feature Gate 和设置权限；
- 至少一条真实 Provider 成功生成链路；
- 刷新、退出重登和服务重启后的数据持久性；
- 备份、恢复和升级后的业务完整性。

## 5. 旧生产退役边界

本 ADR 不授权立即执行以下操作：

- 停止旧生产服务；
- 删除旧生产目录；
- 删除旧数据库或资源；
- 删除旧备份；
- 修改旧生产配置；
- 关闭旧生产网络入口；
- 在生产设备执行任何命令。

旧生产的最终处置必须在新生产基线部署和业务验收通过后，由项目负责人另行明确决定。

旧生产可选择：

- 离线保留；
- 制作只读归档；
- 保留一段观察期；
- 在确认不存在业务、合规和取证需求后永久删除。

无论采用何种方式，都不得将旧生产归档重新解释为新版迁移来源。

## 6. 对规划和任务拆解的约束

从本 ADR 接受之日起：

1. 后续任务不得把旧生产迁移作为默认目标。
2. 不得创建旧数据导入、旧 owner map 自动修复或旧数据库升级任务，除非项目负责人通过新决策明确授权。
3. Fresh Install Bootstrap 必须作为独立设计和实现任务。
4. 生产基线必须明确区分 Release Candidate、开发验证和正式 Production Baseline。
5. 每个相关任务必须标明：

   - 是否修改代码；
   - 是否改变 Schema；
   - 是否接触生产；
   - 是否创建或迁移数据；
   - 是否具备 rollback 或 restore；
   - 当前能力是否已经实现。
6. 任何涉及生产的命令只能由项目负责人在生产设备本地执行。
7. Codex、ChatGPT 和其它 Agent 不得连接、控制或操作生产设备。

## 7. 对 PR 审查的约束

涉及 Release、Runtime、Data、Security、OPS 或 Deployment 的 PR，必须检查：

- 是否错误加入旧生产迁移范围；
- 是否复制旧配置或凭据；
- 是否把开发验证描述为生产采用；
- 是否把合并描述为已部署；
- 是否把 Fresh Install Bootstrap 描述为已实现；
- 是否把 SEC-1B2 描述为新生产空环境初始化能力；
- 是否保留未来新版本 migration、backup、restore 和 rollback 治理；
- 是否未经授权增加生产停止、删除或数据销毁步骤；
- 是否保持 Draft，并等待项目负责人决定 Ready 和合并。

出现上述事实错误时，PR 不得进入 Ready。

## 8. 后果

### 正面后果

- 去除旧数据结构和旧运行环境对新架构的约束；
- 避免将旧 owner、orphan、missing 和配置问题带入新生产；
- 新数据库可以从第一天采用目标 Schema 和安全审计；
- Release、Runtime、路径和数据边界可以按正式架构设计；
- 生产验收标准更清晰；
- 后续升级治理只需服务于新基线后的版本演进。

### 成本和风险

- 旧生产业务数据不会自动出现在新系统；
- 旧账号需要重新创建；
- Provider 和生产配置需要重新设置；
- Fresh Install Bootstrap 成为新增开发任务；
- 新版正式投入使用前，旧生产仍需要独立维持或冻结；
- 项目负责人需要单独决定旧数据保留和销毁策略。

## 9. 重新评估条件

只有出现以下情况之一，才重新评估本 ADR：

- 项目负责人明确撤销“不迁移旧生产数据”的决定；
- 出现法律、合规或业务连续性要求，必须保留特定旧数据；
- 经独立审查确认某类数据必须以受控方式导入；
- 新版正式部署策略发生根本变化。

任何重新评估必须使用新的 ADR，不得通过普通功能 PR 或 Codex 自行扩大范围。

## 10. 当前事实声明

截至本 ADR 接受时：

```text
旧生产版本：仍存在，定义为待退役遗留系统
旧生产服务：未因本 ADR 自动停止
旧生产数据：未删除
旧生产迁移计划：取消
新生产环境：尚未部署
Fresh Install Bootstrap：尚未实现
正式不可变生产基线版：尚未形成
ENV-1B1A：未开始
OPS-3B：未开始
本次决策是否触碰生产：否
```
