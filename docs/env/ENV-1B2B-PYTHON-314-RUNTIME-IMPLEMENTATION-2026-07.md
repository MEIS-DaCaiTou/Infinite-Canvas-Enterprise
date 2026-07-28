# ENV-1B2B：Python 3.14 Windows Runtime 实施记录

更新时间：2026-07-28

## 状态

- 基线：`main@c5d0a62822bb8b55b25215aa74a9f02653e03fc9`（PR #87 merge）。
- 当前阶段：`ENV_1B2B_repository_implementation_independently_accepted=true`、`Python_3_14_Runtime_candidate_independently_accepted=true`、`new_Python_version_repository_implemented=true`、`ENV_1B2_completed=true`。
- 测试分类：`full_repository_regression_passed=true`、`full_repository_regression_interpreter=CPython 3.11.9`、`target_CP314_formal_entry_fixture_verified=true`、`target_CP314_full_enterprise_suite_run=false`、`github_ci_verified=false`。
- 未完成：`ENV_1B3_started=false`、`clean_Windows_validation=false`、`Manifest_v2_implemented=false`、`Release_activation_implemented=false`、`OPS_3B_implemented=false`、`formal_Release_created=false`、`Production_Baseline_approved=false`、`production_approved=false`、`production_validation=false`。

## Active Runtime 契约

唯一 active Windows Runtime 固定为 ordinary-GIL CPython 3.14.6、Windows x64、ABI `cp314`。`runtime/windows/python-source.json` 绑定 Python 官方 embeddable ZIP 的 filename、size、SHA-256 和完整 36-file inventory；`python314._pth` 只允许从官方原始内容变换为规范 CRLF 字节 `python314.zip`、`.`、`..`、`import site`。free-threaded、ARM64、其他 3.14 patch、CP310 active policy 和 operator version override 均不属于本实现。

应用 dependency lock 保持 ENV-1B2A 已资格验证的 30 个 distribution 名称与版本，只重新绑定 CPython 3.14 / win_amd64 wheel filename、tag、size 和 SHA-256。`pip`、`setuptools`、`wheel` 作为固定 3 项 bootstrap policy，最终 installed closure 必须精确为 33 项；安装只允许 `--no-index`、`--require-hashes`、`--only-binary=:all:` 和闭合 wheelhouse。

## 构建与验证

`enterprise/release/windows_runtime_build.py` 继续作为唯一可复现 builder，`enterprise/release/runtime_provenance.py` 继续作为唯一三层 provenance verifier。两者必须交叉验证 active policy、clean Git HEAD/tree、source archive、requirements lock、wheelhouse、Runtime tree、dependency graph、SBOM、attestation 和 archive build record。验证阶段离线执行，不读取系统 site-packages，不修改仓库 `python/`。

最终动态证据保存在仓库外 `review-artifacts/ENV-1B2B`，包括 Build A/B、三层 provenance、真实 formal Windows Batch chain、测试日志和小型 review bundle。独立审查已确认 repository implementation 与候选 Runtime 证据，没有把 PR 合并、clean Windows、formal Release 或 production validation 写成已完成事实。该仓库文档不嵌入大型 Runtime、wheel 或 archive。

## 历史与边界

ENV-1B2A 的 CPython 3.10.11 source、lock、Build A/B 和三层证据不被改写，并作为明确 rollback baseline 保留；它不是并行 active profile。ENV-1B2B 不修改 `main.py` 或 `enterprise/gateway.py`，不实施 Manifest v2、Release activation、OPS-3B、ENV-1B3 或生产操作。真实 fixture 只使用仓库外全新隔离目录和测试 child seam，不访问临时业务测试部署、Provider、真实配置、真实数据库或用户数据。
