# ENV-1B2A：可复现 Windows Python Runtime 实施记录

更新时间：2026-07-28

## 1. 范围与结论

ENV-1B2A 固定现有 Python 3.10 合约，建立标准库实现的离线构建、双构建复现、SBOM、独立 dependency/archive 证据与现有 provenance verifier 闭环。真实大型产物只保存在仓库外 `ARTIFACT_ROOT`；Git 只保存构建代码、哈希锁、策略、测试和脱敏摘要。

PR #87 correction 的最终大文件与逐项机器证据在最终 correction Head 提交后生成，保存在仓库外 review bundle；本文件不嵌入会造成 commit 自引用的动态 artifact hash。最终交付要求保持：

```text
core_runtime_provenance_verified=true
dependency_layer_rebuilt_and_verified=true
archive_provenance_verified=true
production_approved=false
overall_classification=verified
```

`verified` 仅表示候选 Runtime 证据链通过当前 verifier，不表示 formal Release、Production Baseline 或生产批准。

## 2. 固定输入

| 输入 | 身份 |
| --- | --- |
| Python source | CPython 3.10.11 Windows x64 embeddable；`python-3.10.11-embed-amd64.zip`；8,629,277 bytes；SHA-256 `608619f8619075629c9c69f361352a0da6ed7e62f83a0e19c63e0ea32eb7629d`；固定 34 文件 inventory |
| Source policy | `runtime/windows/python-source.json`；SHA-256 `1d1f54f8f3aa4f06ed103722e48f2f9c01bb7de720feff65a45c587fb57220e5` |
| Dependency lock | `runtime/windows/requirements.lock`；30 个精确版本与 SHA-256；SHA-256 `c0cb8e68af568bf5c0d8ae2ef2d50437ae8ab7c662a5e7a39036eb0fd1de4a35` |
| Wheelhouse lock | `runtime/windows/wheelhouse.lock.json`；30 wheels；SHA-256 `2adf980c39c7820d32437ba13b9c4877ce24f4c5a46ce4f1a2df9ed53869a445` |
| Build policy | `runtime/windows/build-policy.json`；固定 builder v2、确定性 ZIP 与 bootstrap wheel 身份 |
| Bootstrap allowlist | `pip==26.1.1`、`setuptools==82.0.1`、`wheel==0.47.0`，各自 wheel 由 policy 固定 filename/size/SHA-256 |

构建和验证命令不发现隐式输入，不使用 PATH Python，不访问网络，不调用 shell，不生成新 dependency lock 或 wheelhouse。应用安装固定使用 `--no-index --only-binary=:all: --require-hashes`。

## 3. Build A / Build B

初审前构建绑定的旧 commit `dc31cda0e88e2c18eee5b255e4eb691c5dc0de03` 已被 correction evidence 取代。最终 Build A/B 必须绑定 correction Head、其完整 Git tree identity 和 clean worktree；两个全新输出根分别从固定 source、lock、wheelhouse 和 policy 开始。动态 Runtime/archive/SBOM digest 以仓库外最终 report 和 review bundle 为准。

| 比较项 | Build A | Build B | 相等 |
| --- | --- | --- | --- |
| Runtime file count | 1,915 | 1,915 | true |
| Runtime size | 55,661,713 bytes | 55,661,713 bytes | true |
| Runtime tree SHA-256 | `6dbeb669533b082a0fe5ca01239692288388df3d27ba4338f6bfe8f5aa6b9887` | 同左 | true |
| Archive SHA-256 | `f57d50c4184f4fe6d07dc86423b4d266455f976d2011894838aa3526ca6c09c0` | 同左 | true |
| Archive inventory | fixed canonical JSON | fixed canonical JSON | true |
| Installed distributions | 33 | 33 | true |
| SBOM | CycloneDX 1.6 | CycloneDX 1.6 | true |

Pip 生成且嵌入绝对 build-root 的 console-script launchers 不属于应用 Runtime 入口合约；build policy 固定删除这些 launchers，并同步移除对应 wheel `RECORD` 行。没有用 ignored field 掩盖差异，`ignored_nondeterministic_fields=[]`。

## 4. Dependency、SBOM 与 Archive

- Wheelhouse：30 个 application wheels，tree SHA-256 `ca2e2e549fa7fdca2ef706753c9212f62ae0f63a54c3b145db9f5ef94decf42d`，11,891,911 bytes；lock/wheelhouse 双向闭合。
- Installed closure：30 个 lock distributions + 固定 3 个 bootstrap distributions，共 33 个；closure SHA-256 `eedc05a1fa1a6ddc140f84609661107adfd88d895b1dfd5f4b706177f85f4bf7`。
- `pip check`：exit 0，broken requirements 0；这是真实新构建 Runtime 的功能证据。
- SBOM：CycloneDX 1.6 canonical JSON；从 fixed Runtime 的真实 `Requires-Dist` metadata 生成并按 CPython 3.10 / Windows x64 marker 环境求值；每个 dependency edge 必须闭合到 installed distribution，Build A/B canonical graph 必须相同。
- Archive：单一 `runtime/` root、1,915 个全局闭合 entries、确定性排序/时间/权限/压缩；23,434,284 bytes；SHA-256 `f57d50c4184f4fe6d07dc86423b4d266455f976d2011894838aa3526ca6c09c0`。
- Rebuild attestation、pip-check report、full inventory 和 archive build record 均由 Runtime manifest 用实际 SHA-256 绑定；现有 `enterprise/release/runtime_provenance.py` 是唯一 verifier。其 true-path 额外要求 lock 每项带 SHA-256、committed source policy 的 Git/blob identity、官方 ZIP filename/size/SHA-256/34-file inventory、clean Git HEAD/tree，以及这些 source identity 在 rebuild attestation 和 archive build record 中一致。legacy 无哈希 lock 仍可解析，但只能得到 insufficient，不能提升 dependency layer。

## 5. 真实 fixed-Python fixture

仓库外最小 Release fixture 使用与 clean correction Head 的 `git archive` 字节完全一致的源码快照、真实 Build A `python/python.exe`、Runtime manifest、current-release pointer、临时 PathRoots、随机 loopback 端口和 fixture child。成功路径实际调用四个正式 Batch wrapper。结果：

```text
real_bundled_python_fixture_tests=true
fixed_release_python_real_start_chain_verified=true
start_result=started
health_ready=true
portable_ownership_valid=true
stop_result=stopped
ports_released=true
runtime_tree_unchanged=true
```

wrapper bootstrap 还验证了中文/空格路径、不同 cwd、污染的 `PYTHONHOME`/`PYTHONPATH`、固定 `python.exe -I -B` 和稳定缺失 pointer 错误。success chain 为 Batch → fixed `python.exe -I -B` → `launcher.py` → preflight → controller/host/supervisor/child；外部 `sitecustomize` 测试缝只在 enterprise 模块实际由 launcher 导入后注入临时 local-root、随机端口和 fixture child，不向 production launcher grammar 暴露 operator trust-root override。没有启动业务 Provider、真实数据库或用户服务，也没有访问临时业务测试部署。

## 6. 证据摘要

仓库只提交 [稳定契约摘要](./evidence/ENV-1B2A-RUNTIME-SUMMARY.json)，不提交原始证据或大型产物。最终 correction Head 的小型 JSON evidence、fixture 命令记录、完整测试节点清单/汇总、报告和 `SHA256SUMS` 位于仓库外 `ENV-1B2A-PR87-REVIEW-BUNDLE.zip`；PR body 记录其 SHA-256。旧 `dc31cda` artifact hashes 仅是初审前历史证据，不再作为最终 PR #87 true-path 依据。

## 7. Audit 与测试证据

APP_ROOT audit 将构建器的所有 caller-owned 仓库外产物写入归入独立 W43。当前 correction tracked scan 为 `scanned=97`、`excluded=266`、`detected=322`、`mapped=322`，parse failure、uncovered、stale、missing anchor 和 invalid flow 均为 0；digest 为 `b69cfffca2f40a4f6b39af5b92673efbfede91d8ac3740017fc28914a9c69c71`。W43 不表示应用 APP_ROOT 获得新的运行时写入能力。

最终候选的本地验证结果：

| 命令组 | 结果 |
| --- | --- |
| `python -m compileall enterprise tools` | exit 0 |
| ENV-1B2A + ENV-1B2P focused | correction 后 94 passed |
| ENV-1B1C-B1 focused | 214 passed、2 skipped |
| ENV-1B1C-B2 focused | 41 passed |
| ENV-1B1A static/audit post-fix regression | 30 passed、2 warnings |
| enterprise full suite | correction Head 使用一次无遗漏隔离 aggregate；完整 collected node ID 集合、分片命令、去重/覆盖证明、最终汇总与 exit code 写入 review bundle |

`github_ci_verified=false`；本地隔离 aggregate 不是 GitHub CI，也不是 clean-Windows 或 production validation。最终通过/失败数字仅以 correction Head 的仓库外测试汇总为准。

## 8. 未完成边界

```text
new_Python_version_qualified=false
ENV_1B2_completed=false
clean_Windows_validation=false
Manifest_v2_implemented=false
Release_activation_implemented=false
OPS_3B_implemented=false
formal_Release_created=false
formal_release_deployed=false
Production_Baseline_approved=false
production_approved=false
production_validation=false
```

本任务未访问生产设备、临时业务测试部署、真实凭据、Provider 或真实用户数据。
