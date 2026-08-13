# RELEASE-MVP-1：首个真实可升级 GitHub Release 准备记录

- 状态：Gate A repository preparation completed; awaiting independent review
- 任务基线：`main@0454bb3e62c55c566ac3f7589d2f667079352c49`
- 证据代码 Head：`cc642885a00b48a6b990089770734cecb64c0acb`（tree `c0c32f46b91fbb80a22b2805dbcdc97c3725cdbf`）
- 目标版本 / tag：`2026.08.1`
- 生产操作：未授权、未执行

## 1. Gate A 范围

本阶段只把已进入 `main` 的 Manifest v2、portable Runtime 与 UPDATE-MVP-1 组合成可供人工审查的三资产 Release rehearsal。权威 `VERSION` 已从 `2026.07.6` 更新到 `2026.08.1`；新增的窄 preflight 使用显式绝对路径并复用正式 Manifest v2 verifier，不建立第二套 verifier、更新器、Runtime controller 或发布平台。

Preflight 同时验证 canonical 版本顺序和 tag、精确三资产集合、Manifest/inventory/archive/payload identity、同 Schema/无 migration 数据库契约，以及发布资产外层必要 metadata 的 bounded secret/本机路径扫描。成功输出单行 JSON 和 exit `0`；阻断输出稳定 code、单行 JSON 和 exit `2`，不向普通 release operator 输出 traceback。

Windows `git archive` 会按宿主 checkout 策略把新 `VERSION` blob 的 LF 转为 CRLF，导致正式 verifier 返回 `RELEASE_ENTERPRISE_VERSION_MISMATCH`。Gate A 对现有 builder 做了最小确定性修正：与既有 requirements lock 处理相同，payload 中的 `VERSION` 明确使用精确 Git blob bytes。Verifier 未被放宽，accepted CP314 Runtime 未重建或修改。

## 2. Release rehearsal identity

```text
source_version=2026.07.6
target_version=2026.08.1
release_id=ice-2026.08.1-cc642885a00b

manifest_sha256=5355b37b16cbf97097961e7d6778f877f0c86c81b3223b26ab83815bf2a4d803
inventory_sha256=631d7c0559c4d8eb85fd55d780aae0d72ce4e84ccd998f384174744c9c951d89
archive_sha256=44f1efc9742120401164721d4f6708d06bd11e06e7862b1d82637295f128f4a8
payload_tree_sha256=eb8851eb8adfe9fdd708bad09681b66f49f252d23513c415e35f62519ec7043e

expected_asset_count=3
missing_asset_count=0
unexpected_asset_count=0
manifest_v2_verify=pass
preflight=pass
runtime_reused=true
runtime_rebuilt=false
```

三项拟发布资产仅为 detached `ops-release-manifest-v2.json`、`release-payload-inventory.json` 和由 Manifest 派生名称的 Windows x64 archive。Gate A evidence 保存在仓库外，不属于拟发布资产，也未提交到 Git。

## 3. 数据库兼容边界

Source A 与 Target B 的 `schema_id`、`schema_snapshot_sha256` 和完整 `migration_ids` 相同；目标继续严格声明：

```text
migration_compatibility=same-schema-no-migration
rollback_classification=code-release-pointer
ops3b_activation_eligible=true
database_migration_supported=false
database_restore_supported=false
```

任何 Schema、snapshot 或 migration IDs 漂移都会由 preflight 以 `RELEASE_MVP_DATABASE_CONTRACT_UNSUPPORTED` fail closed。本阶段没有启动 DATA-1、migration、restore、OPS-3B 或 Activation framework。

## 4. 测试与审计

- RELEASE-MVP-1 focused：`19 passed`。
- Manifest v2 与新 preflight 复核：`76 passed / 4 skipped`。
- Manifest v2、OPS-3A、UPDATE-MVP-1、current-release、portable lifecycle 组合回归：`155 passed / 4 skipped`。
- APP_ROOT audit 与 Gate A focused 最终核验：`20 passed`。
- 首次 full-suite 尝试：`779 passed / 10 skipped / 1 failed`；唯一失败是新增受审计 Release 模块后预期 site-manifest digest 陈旧，扫描本身仍为 `406/406 mapped`、`0 uncovered`、`0 parse failure`。同步既有安全门禁 digest 后，最终 full suite 为 `780 passed / 10 skipped / 0 failed / 8 warnings`，解释器为专用 CPython `3.11.9 x64`。
- `python -m compileall enterprise tools`：通过。
- APP_ROOT write audit、Git diff check、相对链接与 changed-file 范围、secret/本机路径扫描：通过。

这些是 Gate A repository/rehearsal 自证，等待独立复核；不冒充 GitHub CI、公开 Release 或远程升级 E2E。

## 5. 冻结状态

```text
Gate_A_repository_preparation=true
Gate_A_independently_accepted=false
Gate_B_GitHub_Release_published=false
Gate_B_remote_update_E2E=false

GitHub_Release_object_created=false
project_formal_Release_created=false
DATA_1_started=false
OPS_3B_started=false
Production_Baseline_approved=false
production_touched=false
```

Gate B 只有在本 Draft PR 经独立复核、由项目负责人 Merge，并再次明确授权 `CONTINUE_RELEASE_MVP_1_GATE_B=true` 后才可开始。
