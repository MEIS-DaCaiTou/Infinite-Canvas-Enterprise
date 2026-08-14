# RELEASE-MVP-1：首个真实可升级 GitHub Release 最终记录

- 状态：Gate A / Gate B 已完成，repository / Release / 远程升级证据已独立验收
- 最后验证代码基线：`main@dc00fdb9c127de927ca898bc65f96c68481dbf56`
- tree：`8c3fc38905888327f935f47f27137e25c929fbd0`
- 最终 Source / Target：公开 `2026.08.2 -> 2026.08.3`
- 生产操作：未授权、未执行

## 1. 最终结论

RELEASE-MVP-1 已完成从确定性三资产构建、公开 GitHub Release 发布，到真实 Source 使用 GitHub Provider / API / HTTPS 发现并升级至公开 Target 的完整最小闭环：

```text
RELEASE_MVP_1_completed=true
RELEASE_MVP_1_Gate_B_completed=true
RELEASE_MVP_1_remote_update_E2E=true
RELEASE_MVP_1_independently_accepted=true

source=2026.08.2
target=2026.08.3
job_state=SUCCEEDED
target_health=PASS
```

这证明当前仓库的同 Schema / 无 migration 单跳更新可以由真实公开 Release 驱动，并在隔离 Windows 环境完成 durable handoff、指针切换、目标启动与健康确认。公开 GitHub Release object 不等于项目 Formal Release、Production Baseline 或生产部署。

## 2. 阶段演进

### Gate A：repository preparation

Gate A 从 `main@0454bb3e62c55c566ac3f7589d2f667079352c49` 准备 `2026.08.1` 三资产 rehearsal，增加复用正式 Manifest v2 verifier 的窄 Release preflight，并验证版本 / tag、资产闭合、Manifest / inventory / archive / payload identity、同 Schema / 无 migration 数据库契约和 bounded metadata 扫描。PR #94 合并为 `8c97af7ad108ec29e90a3ac61b0b25e5d47b720d`。

Gate A repository preparation 与 rehearsal identity 已独立接受。其仓库外 rehearsal binary 未作为当时 ChatGPT 附件逐字节复哈希；Gate B 按要求从 merged main 重新构建并验证公开 bytes，没有将 Gate A rehearsal 冒充正式发布资产。

### Gate B：公开发布与真实远程升级

1. `2026.08.1` 首次建立真实 GitHub Release / Gate B 路径，暴露 async prepare 同步阻塞 Gateway event loop，以及 Supervisor 将 `startup_timeout` 错用于已经 healthy 角色的两个产品缺陷。
2. PR #95 对上述两个缺陷作窄修并通过独立代码与 Windows liveness 验收，合并为 `f73134b34195a86631916734b349e2b6f854cfc0`；该精确 commit 构建并发布为 `2026.08.2`。
3. PR #96 只修改权威 `VERSION`，合并为 `dc00fdb9c127de927ca898bc65f96c68481dbf56`；该精确 merged main 构建并发布为 `2026.08.3`。
4. R3-C R1 修正 restart counter 证据语义后，使用公开 `2026.08.2` 原始 bytes 作为 Source、公开 `2026.08.3` 作为 Target，完成真实 GitHub 在线升级 E2E。

`2026.08.1` 继续保留为历史测试 Release，不是最终在线升级验收基线；公开 `.2` / `.3` 未删除、未替换、未重发。

## 3. 公开 Release 身份

### Source：2026.08.2

```text
github_release_id=370312441
tag_target=f73134b34195a86631916734b349e2b6f854cfc0

manifest_sha256=824fba41142c9afe5838c936c332f762e54fedcb451f022cafb51f07b77425dc
inventory_sha256=5476af4ba40e4cfc522d21f6d7d72d0df0278ac6c638e6352d31642a0006ee39
archive_sha256=b2f0bc91f412d247c523e945a305a8c53dd052ccf7c8e74d4aec0126b3fb337c
```

### Target：2026.08.3

```text
github_release_id=370324665
tag_target=dc00fdb9c127de927ca898bc65f96c68481dbf56
release_id=ice-2026.08.3-dc00fdb9c127

manifest_sha256=6afdf17084ca20467f52c0ad3851b306cf2f3f88be1e9e3dc46c3ba89c84b8fa
inventory_sha256=e67b0f0c1a843aa6b11e177f1bca373be910a491d4551a451bc45903688e0d8a
archive_sha256=048a2215454668b28f1a532ca316a0e29e1788755c4a65127d71d80fe8ffbfed
```

Source 三资产重新从真实 GitHub Release 下载并通过正式 Manifest verify；Target 发布后三资产也经 GitHub 重新下载、哈希与 preflight 验证。Source 使用其 bundled CPython `3.14.6`、portable launcher、supervisor、gateway 和 upstream，不从 Git checkout 重建，也不是 synthetic Source。

## 4. R3-C R1 restart-counter 收口

初次 R3-C 只保存了最终累计 `upstream_restarts=1`，没有保存 75 秒窗口起点计数，因此不能证明窗口内发生了重启。R3-C R1 从公开 Source 的 Supervisor 生命周期开始重新完整采集：

```text
gateway_restart_count_before_first_healthy=0
upstream_restart_count_before_first_healthy=0

gateway_restart_count_start=0
gateway_restart_count_end=0
gateway_restart_delta=0

upstream_restart_count_start=0
upstream_restart_count_end=0
upstream_restart_delta=0

gateway_health_failures=0
upstream_health_failures=0
gateway_pid_changed=false
upstream_pid_changed=false
stable_75s=true

ROOT_CAUSE_CLASSIFICATION=HARNESS_GATE_DEFECT
previous_gate_used_cumulative_restart_count=true
new_product_defect_confirmed=false
```

旧 evidence 未保存此前累计增量对应的原始 restart event，因此不事后猜测其精确来源；受控重检中该计数未复现，完整 timeline 也没有 restart、crash、startup timeout 或 start failure。最终结论只纠正门禁语义，不把旧累计值描述为已确认产品 Runtime 故障。

## 5. 真实公开 `.2 -> .3` E2E

隔离 Windows fixture 使用 repository-external install / state / data / log / staging / release roots、非生产端口与非生产数据库。执行链与结果为：

```text
Source_public_bytes_exact=true
Source_bundled_CPython_3_14_6=true

GitHubReleasesProvider=true
real_GitHub_API=true
real_HTTPS_download=true

source_stable_75s=true
check=pass
prepare=READY
prepare_gateway_health_failures=0
prepare_upstream_health_failures=0

wrong_password_denied=true
password_reconfirm=pass
execute=pass
handoff=pass
reconnect=pass

job_state=SUCCEEDED
current_release_after=2026.08.3
target_health=PASS

old_owned_processes=0
wrong_listeners=0
worker_processes=0
active_update_lock_present=false
diagnostics_export_recorded_pass=true
```

`prepare` 期间 gateway / upstream health failure、restart delta 与 PID change 均为 `0`。错误密码以稳定错误拒绝；正确密码重新确认后生成 durable job，Source supervisor 真实停止并释放 lock，one-shot worker 完成 expected-current CAS、Target start / health 和最终清理。

## 6. Evidence 身份与边界

最终 R3-C R1 evidence：

```text
bundle=RELEASE-MVP-1-GATE-B-R3C-R1-EVIDENCE.zip
zip_sha256=30562e64fbad7fad02876fb01e04924f91d47e3e170ca071a4d51c354bf1daf8
SHA256SUMS_sha256=c1e474c43fd1d02c2887676322b409e6f9f09bdb071be134b3e31ef82e5813ad

checksum_entries=18
checksum_entries_present=18
checksum_entries_matching=18
```

独立复核重新解压并确认 ZIP hash、`SHA256SUMS.txt` 自身 hash 与内部 `18/18` 条目闭合。准确的 diagnostics 边界为：

```text
diagnostics_export_recorded_pass=true
delivered_sanitized_evidence_independently_verified=true
raw_diagnostics_export_independently_rehashed=false
```

raw diagnostics 含 repository-external 隔离 fixture 路径，因此没有进入交付 ZIP；不得声称独立复哈希了 raw export。交付 evidence 的 secret / 本机路径扫描通过，该边界不构成 RELEASE-MVP-1 technical acceptance blocker。

## 7. 数据库与生产边界

RELEASE-MVP-1 继续只支持：

```text
migration_compatibility=same-schema-no-migration
rollback_classification=code-release-pointer
database_migration_supported=false
database_restore_supported=false
```

任何 Schema、snapshot 或 migration IDs 漂移继续 fail closed。本阶段没有启动 DATA-1、OPS-3B、migration、restore、formal Activation 或生产操作。

```text
DATA_1_started=false
OPS_3B_started=false
project_formal_Release_created=false
Production_Baseline_approved=false
production_approved=false
production_deployed=false
production_validated=false
production_touched_by_RELEASE_MVP_1=false
temporary_business_environment_touched_by_RELEASE_MVP_1=false
```

## 8. 最终冻结状态

```text
RELEASE_MVP_1_completed=true
RELEASE_MVP_1_Gate_B_completed=true
RELEASE_MVP_1_remote_update_E2E=true
RELEASE_MVP_1_independently_accepted=true

GitHub_Release_object_created=true
source_version=2026.08.2
target_version=2026.08.3
job_state=SUCCEEDED
target_health=PASS

project_formal_Release_created=false
Production_Baseline_approved=false
production_touched=false
```
