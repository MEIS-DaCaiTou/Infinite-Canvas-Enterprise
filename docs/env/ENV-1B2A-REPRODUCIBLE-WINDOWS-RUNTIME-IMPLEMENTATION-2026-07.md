# ENV-1B2A：可复现 Windows Python Runtime 实施记录

更新时间：2026-07-28

## 1. 范围与结论

ENV-1B2A 固定现有 Python 3.10 合约，建立标准库实现的离线构建、双构建复现、SBOM、独立 dependency/archive 证据与现有 provenance verifier 闭环。真实大型产物只保存在仓库外 `ARTIFACT_ROOT`；Git 只保存构建代码、哈希锁、策略、测试和脱敏摘要。

本次正式结果：

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
| Build policy | `runtime/windows/build-policy.json`；SHA-256 `f778e831ccc83537c88d64cec9acdc24b1d36c6f72aedaaadc1421790d90c27a` |
| Bootstrap allowlist | `pip==26.1.1`、`setuptools==82.0.1`、`wheel==0.47.0`，各自 wheel 由 policy 固定 filename/size/SHA-256 |

构建和验证命令不发现隐式输入，不使用 PATH Python，不访问网络，不调用 shell，不生成新 dependency lock 或 wheelhouse。应用安装固定使用 `--no-index --only-binary=:all: --require-hashes`。

## 3. Build A / Build B

正式构建绑定企业代码 commit `dc31cda0e88e2c18eee5b255e4eb691c5dc0de03`。两个全新输出根分别从固定 source、lock、wheelhouse 和 policy 开始。

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
- SBOM：CycloneDX 1.6 canonical JSON；SHA-256 `8d2ddc18eabb8556210a0c7a95099d722c6abf01d64cb2b77a0986832fe6bc07`。
- Archive：单一 `runtime/` root、1,915 个全局闭合 entries、确定性排序/时间/权限/压缩；23,434,284 bytes；SHA-256 `f57d50c4184f4fe6d07dc86423b4d266455f976d2011894838aa3526ca6c09c0`。
- Rebuild attestation、pip-check report、full inventory 和 archive build record 均由 Runtime manifest 用实际 SHA-256 绑定；现有 `enterprise/release/runtime_provenance.py` 是唯一 verifier。

## 5. 真实 fixed-Python fixture

仓库外最小 Release fixture 使用正式源码快照、真实 Build A `python/python.exe`、Runtime manifest、current-release pointer、临时 PathRoots、随机 loopback 端口和 fixture child。结果：

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

wrapper bootstrap 还验证了中文/空格路径、不同 cwd、污染的 `PYTHONHOME`/`PYTHONPATH`、固定 `python.exe -I -B` 和稳定缺失 pointer 错误。fixture 使用仓库外 test-only local-root injection，复用现有 launcher/controller/host/supervisor/state/lock/fixture-child 实现；没有启动业务 Provider、真实数据库或用户服务，也没有访问临时业务测试部署。

## 6. 证据摘要

| Artifact basename | SHA-256 |
| --- | --- |
| `runtime-manifest.json` | `69bf1673fcc6185b262cb3e464e5ce3c63c694aae5b0b9ca6422d3dcecbeb05a` |
| `dependency-rebuild-attestation.json` | `27e809eb500e609d68f920c27d9efa256b1a6acfd3c4fa10af549797ffb4ecd4` |
| `pip-check-report.json` | `349f01b69cb83ea0ed80f9aeff6c3d2c57ca5525bac1b65bd2e9f483d7cc074b` |
| `runtime-sbom.cdx.json` | `8d2ddc18eabb8556210a0c7a95099d722c6abf01d64cb2b77a0986832fe6bc07` |
| `runtime-archive-inventory.json` | `67043be7e0b70f0f30b20e3587ecce977372d07125964b7a3ae5950389ddb121` |
| `runtime-archive-build-record.json` | `e8af1817beb68679b6703df68b77bb34197e49851070abb18d46846c6fc0707c` |
| `runtime-archive-provenance-report.json` | `06d5e438801dfe33d2b099e03e35d33ace6cb5dc51953c7ab86b2aa9d0f95466` |
| `reproducibility-summary.json` | `106ec283c3ebbe766e73d16382a41c8459cc2ce571a532e72486b6746a3a6154` |
| `b2-real-bundled-python-fixture-report.json` | `ed689c1330682fb67ff361e2b7667bf196528874738b2af127d65a335363f226` |

仓库只提交 [脱敏机器摘要](./evidence/ENV-1B2A-RUNTIME-SUMMARY.json)，不提交上述原始证据或大型产物。

## 7. Audit 与测试证据

APP_ROOT audit 将构建器的所有 caller-owned 仓库外产物写入归入独立 W43。当前 tracked scan 为 `scanned=97`、`excluded=264`、`detected=321`、`mapped=321`，parse failure、uncovered、stale、missing anchor 和 invalid flow 均为 0；digest 为 `e81201364d49abeb3b2b40bb92c839dc33dc37ad502bca9be3887a45b4c548d6`。W43 不表示应用 APP_ROOT 获得新的运行时写入能力。

最终候选的本地验证结果：

| 命令组 | 结果 |
| --- | --- |
| `python -m compileall enterprise tools` | exit 0 |
| ENV-1B2A + ENV-1B2P focused | 90 passed |
| ENV-1B1C-B1 focused | 214 passed、2 skipped |
| ENV-1B1C-B2 focused | 41 passed |
| ENV-1B1A static/audit post-fix regression | 30 passed、2 warnings |
| 单次 `python -m pytest enterprise/tests -q` | collected 545；在 W43 登记前暴露 1 个 audit failure；随后 Windows lifecycle/Job Object 用例回收当前 Codex command host，未产生最终 pytest 汇总或 exit marker |

单次 full-suite 暴露的 audit failure 已由上述 W43 focused regression 关闭，但依任务书“不重复 final full suite”边界没有把修正后的 focused 结果改写为完整 suite pass。因此 `full_suite_passed=false`、`github_ci_verified=false`；这是测试证据限制，不改变 Build A/B、实际 `pip check`、provenance verifier 或真实 fixed-Python fixture 的结果。

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
