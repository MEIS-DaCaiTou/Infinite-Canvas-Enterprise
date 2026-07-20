# ENV-1B2P：Windows Python Runtime 分层来源证据

- 状态：当前 Draft PR 实施；尚未进入 `main`
- 验证日期：2026-07-20
- 当前代码基线：`main@a53885b026a6c2440acb0fbde72d6571ff6f7723`
- 固定上游：`hero8152/Infinite-Canvas@f1dd6834a72f3e7ff8340be05a84347d931e9cb9`，`VERSION=2026.07.6`
- 决策依据：[ADR-ENV-002](../decisions/ADR-ENV-002-WINDOWS-PYTHON-RUNTIME-PROVENANCE-2026-07.md)
- 机器摘要：[ENV-1B2P-RUNTIME-PROVENANCE-SUMMARY.json](./evidence/ENV-1B2P-RUNTIME-PROVENANCE-SUMMARY.json)
- 生产影响：`production touched=false`、`production_approved=false`

## 1. 结论

ENV-1B2P 是对开发设备仓库外既有证据的只读核验，不是 Runtime 重建、安装、下载或正式入口接线。当前 Draft PR 的真实验证结果为：

```text
core_runtime_provenance_verified=true
dependency_layer_rebuilt_and_verified=false
archive_provenance_verified=false
production_approved=false
overall_classification=partially_verified
```

三个字段独立判断。核心层通过不提升依赖层或完整归档层；任何层通过也不构成 Production approval。ENV-1B1B、ENV-1B1C、完整 ENV-1B2、Manifest v2、ENV-1B3、正式 Release 和 Production Baseline 均未由本任务实施。

## 2. 仓库事实

- PR #81 已合并，merge commit 为 `a53885b026a6c2440acb0fbde72d6571ff6f7723`；ENV-1B1A 已进入 `main`。
- ENV-1B1A 已移除 startup/HTML response static 自修改并实现确定性 staging builder，但完整 APP_ROOT 仍不是只读。
- Windows launcher 和 `enterprise/runtime/process.py` 仍允许 PATH / `sys.executable` 兼容回退；这是未实施的 ENV-1B1C 边界。
- `requirements.txt` 是直接依赖声明，不是带完整哈希、重建和 `pip check` 证据的正式依赖锁。
- `python/`、Runtime archive、wheelhouse 和原始外部证据仍按既定边界保存在 Git 仓库外。

## 3. 外部证据事实与选择

按项目说明记录的证据根、长期项目目录的直接关联目录和有限文件名搜索，只发现一个可绑定的 ENV-1B2A 候选集合。未按修改时间选择；manifest 中的 Python 版本、ABI、固定 upstream commit、企业 commit、lock SHA-256、wheel manifest SHA-256、核心文件 SHA-256 和 source archive SHA-256 均指向同一集合。未发现第二个可竞争的 manifest、lock、wheelhouse 或 `python.zip`。

下表仅记录 basename、大小和 SHA-256/确定性树摘要，不记录本机绝对路径：

| Artifact | Basename / identity | Size | SHA-256 |
| --- | --- | ---: | --- |
| Runtime manifest | `runtime-manifest.json` | 3,692 bytes | `f77bd14613ebaedb733a55fea3c47e86d708d84fe0f5a73ac11616080435275a` |
| Dependency lock | `requirements-windows-cp310.lock` | 537 bytes | `bcc10796c392ac250114f8fe8dfedd6f191dce5afd9b58ede6911ce097c85c92` |
| Wheel manifest | `wheelhouse-sha256.json` | 13,640 bytes | `c72210136ca7db01f0879d1313f9f6f2455a08c1bd1bd478a61ea1e6c7c9c902` |
| Source archive | `python.zip` | 29,433,625 bytes | `d55f1deea7351f1e83168db5fd533b9740fcd0bc429a6c1fbc53bda135c33aa2` |
| Historical validation attachment | `ENV-1B2A-UPSTREAM-PYTHON-RUNTIME-VALIDATION.md` | 4,500 bytes | `a062cc38f6ba9ab15bb8e80fcfe7fc91fe868e99d30e20ecb074ca090864a4cb` |
| Candidate Runtime tree | `python-enterprise`，3,342 files | 70,241,459 bytes | `3f1182706edcd09099deddae9801587294b589e2d9ad33ce23e91c17a428caff` |
| Wheelhouse tree | `wheelhouse`，30 files | 11,891,911 bytes | `9d1730e966807c3a48ffc55b976eff3af1a03b28bcc31831c922f031b343ba0a` |
| Local Git-derived upstream core snapshot | `fixed-upstream-core.zip`，34 files | 8,630,513 bytes | `136f0a44febfccc418b51321196ad14a2c238689e40daf32561a7eaafbb1e333` |

最后一项由本地已有固定 commit 的 Git 对象临时导出，只作为 34 个核心文件的只读对照；未下载、未提交，也不是 Runtime 构建输入。外部原始 artifact、候选 Runtime 和临时 snapshot 均未复制到 Git 工作树。

## 4. 验证器实现

`enterprise.release.runtime_provenance` 与 `tools/verify_runtime_provenance.py` 采用标准库和显式路径：

- 支持 `enterprise-windows-runtime-manifest-v1`、`env-1b2a-wheelhouse-sha256-v1`、`name==version` dependency lock 和 ZIP 目录流式检查。
- source Runtime archive 与未来 assembled candidate archive 使用不同参数和证据角色，source `python.zip` 不能冒充完整候选归档。
- 路径绝对化；输入根、祖先和树内 symlink / junction / reparse fail closed；manifest、lock 和 ZIP 路径拒绝绝对路径、逃逸、ADS、Windows 设备名、大小写归一重复和 symlink 条目。
- 大文件分块 SHA-256；ZIP 直接读取目录和流，不解压到正式目录。
- 候选解释器只使用显式 `python.exe`、清理后的环境、`PYTHONDONTWRITEBYTECODE=1`、参数数组、`shell=False` 和超时；不导入项目业务代码。
- 报告只含 basename、哈希、大小、计数和稳定错误码；不含本机绝对路径、环境变量值、secret 或 traceback。
- 报告使用全新目标和同目录临时文件原子发布；失败不会留下 `result=pass`。

报告 schema 为 `env-1b2p-runtime-provenance-report-v1`，verifier version 为 `env-1b2p-runtime-provenance-verifier-v1`。

## 5. 三层真实结果

### 5.1 Core Runtime：verified

`core_runtime_provenance_verified=true` 的直接证据：

- 固定 upstream commit 的本地 Git 对象精确包含 34 个 `python/` 核心文件。
- source `python.zip` 中对应 34 个文件与固定 Git 核心逐项大小和 SHA-256 一致；缺失和差异均为 0。
- 候选 Runtime 的 33 个未变核心文件逐项匹配；`python310._pth` 的唯一变化由 manifest 同时绑定 original/candidate SHA-256，并固定为相对 `..` APP_ROOT 项和 `import site`，没有本机绝对路径。
- manifest 声明的 5 个关键核心文件与实际候选一致；3,342 个文件、70,241,459 bytes 的全树摘要与 manifest 一致。
- 显式候选解释器返回 CPython 3.10.11、64-bit AMD64、`cp310` 兼容身份；`python.exe` basename、prefix/base-prefix basename、`sys.abiflags` 和可用 SOABI 均以脱敏字段处理。
- 候选 Runtime 全树在解释器检查前后摘要一致。

这只证明核心层可绑定固定 upstream；不批准 Python 3.10.11 为长期支持版本，也不替代后续干净 Windows 生命周期验证。

### 5.2 Dependency Layer：insufficient

`dependency_layer_rebuilt_and_verified=false`。已通过的子检查包括：

- lock 中 30 个精确版本与 wheel manifest 的 30 个 package/version 双向闭合。
- wheelhouse 无缺失、额外 wheel 或 SHA-256 差异；全部 tag 与 `cp310-win_amd64` 或 pure-Python 兼容。
- 候选解释器读取的 30 个锁定分发版本全部匹配。
- manifest 对 lock 和 wheel manifest 的 SHA-256 绑定一致；验证前后 wheelhouse 树摘要一致。

仍不足以提升为 `true`：现有 machine manifest 没有可独立验证的 offline rebuild attestation，也没有 `pip check` 结果。历史 Markdown 声称曾使用 `--no-index --no-deps --force-reinstall`，但外部人工报告只能作为附件，不能单独替代机器证据、完整安装闭包和 `pip check`。本任务没有重建依赖或补造这些证据。

### 5.3 Complete Archive：insufficient

`archive_provenance_verified=false`。已验证 source `python.zip` 的唯一身份、完整 SHA-256、3,724 个 central-directory 条目（其中 3,287 个普通文件）的安全 ZIP 结构和 34 个核心文件绑定；但该文件是 source Runtime archive，不是依赖重建后的 assembled candidate archive。

历史 manifest 和报告明确记录 candidate Runtime ZIP 未生成，因此缺少：完整候选归档、逐文件 full manifest、candidate archive build process provenance，以及归档与已验证依赖层的绑定。孤立 source archive hash、可解压或可启动均不能提升本字段。

## 6. 当前证据限制

- 外部证据的 enterprise commit 为 `396cccc68d63bd16393a2cb72d24e4a48fcf47cb`，当前基线为 `a53885b026a6c2440acb0fbde72d6571ff6f7723`。证据内部没有 commit 冲突，但它没有重跑 PR #81 合并后的完整应用生命周期；因此保留 `evidence-built-against-earlier-enterprise-commit`。
- PR #81 已从当前 `main` 关闭历史 static startup mutation，不能反向改写 2026-07-15 候选验证的历史失败；本任务的文件证据验证也不能替代后续干净 Windows 生命周期回归。
- Python 3.10 官方支持时限风险仍在；本任务不提前给出新 Python 版本兼容结论。
- `production_approved=false` 固定不变。

## 7. 后续边界

- ENV-1B1B：路径根、版本目录和 `current-release.json` 尚未开始。
- ENV-1B1C：正式入口、内部进程和 Release-bound Python fail closed 尚未开始。
- 完整 ENV-1B2：可重复依赖重建、hash lock、`pip check`、SBOM、许可证、assembled archive 和新 Python 版本兼容仍待独立实施。
- Manifest v2、ENV-1B3、正式 Release Candidate、Fresh Install Bootstrap、OPS-3B 和 Production Baseline 均未形成。
- 本任务未访问生产设备、生产数据或网络，未安装 Python，未修改 `python/` 或 `requirements.txt`。
