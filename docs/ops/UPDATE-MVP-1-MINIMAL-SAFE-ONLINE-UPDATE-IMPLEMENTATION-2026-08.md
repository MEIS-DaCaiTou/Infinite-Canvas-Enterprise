# UPDATE-MVP-1：最小安全在线升级与诊断实施记录

状态：Repository implementation present; awaiting independent review
基线：`main@646616b36233282088baed787c30075f355923b3`
生产操作：未授权、未执行

## 1. 能力与边界

UPDATE-MVP-1 在既有 OPS-3A、Manifest v2、PathRoots、`current-release.json`、portable Runtime、STAB-1 supervisor 和 admin UI 上形成最小单跳更新闭环。它只接受固定 GitHub 仓库中同时具备 detached Manifest v2、external inventory 和唯一 Windows x64 archive 的稳定 Release，完成 bounded download、离线验证、同卷 `.partial` materialization、expected-current pointer 切换、目标 `start` / `health`，并在目标启动或健康失败时停止目标、切回源 Release、重新启动并验证源 Release。

本实现不是完整 OPS-3B、OPS-3C、通用 Activation Phase 或数据库升级引擎。它不执行 migration 或 restore，不接受 operator URL、路径、命令或 executable，不调用 shell，不原地修改 APP_ROOT，也不建立常驻 updater daemon。`Release_activation_implemented=false` 继续表示完整正式 activation 能力尚未完成；本阶段仅有受严格数据库契约限制的 `code_release_pointer_switch_mvp=true`。

## 2. 权限与确认

现有 feature flag / user override 存储模型保持不变。仅对 `system_update` 取消历史 `is_admin => allowed` 自动放行：环境总闸与数据库总开关必须同时开启；`super_admin` 默认允许；普通 `admin` 只有在当前数据库中存在显式 `allow` override 时允许；`user`、未知角色、`inherit` 和 `deny` 均拒绝。只有实时数据库角色为 `super_admin` 的 principal 可以修改该全局 flag 或 grant/revoke override，普通 admin 不能自授权、替他人授权或借批量 purge 清除该高风险授权。

prepare 不接收密码。execute 会重新读取 actor、核对 `auth_version` 和当前权限，并只在该请求内验证当前密码。密码不进入 plan、status、JSONL、audit、环境变量或 diagnostics。

## 3. Job、handoff 与恢复

Job 使用外部 `STAGING_ROOT/update-mvp` 的 bounded canonical JSON/JSONL，状态为 `PREPARING`、`READY`、`UPDATING`、`RESTARTING`、`VERIFYING`、`SUCCEEDED`、`ROLLING_BACK`、`ROLLED_BACK`、`FAILED`。`STATE_ROOT/system-update-active.lock` 使用 create-only reservation，阻止同 job 或不同 job 的并发确认。

Gateway 在返回 `202` 后只向通过 ownership/readiness 二次检查的现有 supervisor 提交固定 `update-handoff` 命令。Supervisor 只能用当前 Release 的固定 Python、`-I -B` 和固定 `enterprise/ops/update/handoff.py --job-id <32 hex>` 启动一次性无网络 worker；worker 不接受 shell、URL 或命令，等待源 supervisor 释放 lock 后执行并退出。页面把 job ID 保存在 session storage，Gateway 重启期间持续重试，最终状态只以 durable job 为准。

执行前重新验证 source/target materialized Release、Manifest identity、payload tree、数据库兼容性和 expected-current pointer。切换后 target `start` 或 `health` 失败才进入 code rollback；切换前失败准确记录为 `FAILED`，不会伪报 `ROLLED_BACK`。若源 Release 无法重新达到 health，最终同样是 `FAILED`。

## 4. 数据库契约

目标 Manifest v2 必须使用唯一允许的 MVP 分类：

```text
migration_compatibility=same-schema-no-migration
rollback_classification=code-release-pointer
ops3b_activation_eligible=true
```

source 与 target 的 `schema_id`、`schema_snapshot_sha256` 和完整 `migration_ids` 必须完全相同。任一变化均以 `SYSTEM_UPDATE_DATABASE_CONTRACT_UNSUPPORTED` fail closed；`database_migration_supported=false`、`database_restore_supported=false`。

## 5. UI、诊断与审计

Update Center 显示当前/最新版本、release notes、兼容性、prepare/execute/job 状态和结果。未授权 admin 不显示危险按钮且后端仍返回 403；user 无权进入。执行确认明确提示短时中断与自动代码回滚，并要求当前密码。

诊断接口只读取固定 runtime log 名、指定 job JSONL 和受限 state/status 摘要；每源最多读取 2 MiB、最多返回 500 行，继续使用现有 secret redaction。ZIP 只包含脱敏后的 `update-diagnostics.json`，不打包 `.env`、原始 header、数据库或任意路径文件。审计名称包含 permission grant/revoke、started、succeeded、failed 和 rolled_back，字段仅包含 actor/target/job/release identity 与稳定结果码。

## 6. 验证与限制

Focused evidence 覆盖权限矩阵、自授权与路由键绕过、密码二次确认、同 job/异 job 并发、Manifest v2/database contract、expected-current、source/target verification、成功切换、broken-target 自动回滚、固定 handoff、页面重连、日志脱敏和 diagnostics ZIP。Windows A→B 与 failed-B→A 使用隔离临时根和等价 API/core fixture，不访问生产或临时业务测试部署。

由于本任务扩展了 Manifest v2 的唯一允许 database-contract 分类，相关 Manifest、materialization、portable lifecycle 和 APP_ROOT audit repository regressions必须通过；本 Draft 不把历史 Candidate 08 物理 W01-W14 证据冒充为新 Head 的独立验证。最终测试结果见下方“验证结果”，且仍等待独立复核。

## 验证结果

- UPDATE-MVP-1 focused：`18 passed`。
- 权限、Manifest v2、current-release、portable lifecycle、Windows wrappers、STAB-1 等组合回归：`228 passed / 4 skipped / 0 failed`。
- 直接脚本：`test_ops_3a_online_update.py`、`test_ops_runner.py`、`test_sec_1b1_role_auth.py` 均通过。
- `python -m compileall enterprise tools`：通过。
- APP_ROOT audit：`scanned=136`、`excluded=294`、`detected=405`、`mapped=405`、`uncovered=0`、`stale=0`、`missing=0`，digest=`e86368690a7e37276ae189f306a24c3ad765d318c7be72d2411ffeb66386f8d6`。
- 最终 enterprise full suite：固定 CPython 3.11.9 x64，`757 passed / 10 skipped / 0 failed / 8 warnings`，exit `0`；仅在最终候选暂存后运行一次，结果回填后未重跑。
- `github_ci_verified=false`；新 Head 尚未获得独立物理 Windows W01-W14 验证；生产设备与临时业务测试部署均未访问。

```text
UPDATE_MVP_1_repository_implementation=true
UPDATE_MVP_1_repository_implementation_independently_accepted=false
system_update_super_admin_default=true
system_update_admin_explicit_grant_required=true
database_migration_supported=false
database_restore_supported=false
code_release_rollback_supported=true
DATA_1_STARTED=false
Release_activation_implemented=false
OPS_3B_implemented=false
formal_Release_created=false
Production_Baseline_approved=false
production_approved=false
production_validation=false
production_touched=false
```
