# ADR-ENV-002：Windows Python 运行时与来源证据

- 状态：Accepted
- 决策日期：2026-07-16
- 决策事实基线：`main@396cccc68d63bd16393a2cb72d24e4a48fcf47cb`
- 当前实施核对基线：`main@c5d0a62822bb8b55b25215aa74a9f02653e03fc9`
- 实施状态：ENV-1B2P、ENV-1B2A 已合并；ENV-1B2B 的 CPython 3.14.6 / cp314 active Runtime repository implementation 已通过独立代码与证据审查，正式 Release 运行时仍未批准

## 背景

上游交付设计优先使用项目内 Python，但当前企业版还没有实现 portable-release 的解释器 fail-closed 契约。历史 `python.zip` 可以构建 CPython 3.10.11 x64、ABI `cp310` 的企业候选运行时，并已在隔离开发环境完成生命周期验证，但候选验证不等于来源、依赖和归档均已形成可重复的正式供应链。

Python 3.10 的官方支持计划于 2026 年 10 月结束，因此 3.10.11 只能作为上游兼容过渡基线，不能被定义为长期企业运行时。

## 当前实现事实

- 当前开发主目录的 `python/` 为空，不包含 `python.exe`。
- 当前 Windows lifecycle `.bat` 先查找 `python\python.exe`，缺失时静默回退 PATH 中的 `python`。
- `enterprise/runtime/process.py` 当前在项目解释器缺失时回退 `sys.executable`。
- 因此当前正式入口尚不能证明所有角色使用 Release 绑定解释器，也不是 fail closed。
- ENV-1B1C 尚未实施；在此之前不能把目标契约描述成当前行为。
- `development` 模式继续允许显式选择系统 Python，但其结果不能替代 portable-release 验证。

## 决策

1. 正式 Windows Python 运行时必须与不可变 Release 绑定。
2. `portable-release` 正式入口只能使用 Release 内 Python，解释器或证据缺失时 fail closed。
3. PATH 中的 `python`、`py` 和 `sys.executable` 回退只允许显式 `development` 模式使用。
4. CPython 3.10.11 x64 / `cp310` 仅作为上游兼容过渡基线。
5. ENV-1B2 必须并行验证仍受官方支持的新 Python 版本，并形成升级时限和兼容结论。
6. 运行时来源不得用一个模糊布尔值表示，必须采用三层证据模型：

```text
core_runtime_provenance_verified
dependency_layer_rebuilt_and_verified
archive_provenance_verified
```

## 当前证据

- 固定上游：`hero8152/Infinite-Canvas@f1dd6834a72f3e7ff8340be05a84347d931e9cb9`，`VERSION=2026.07.6`。
- 上游提交跟踪的 `python/` 核心文件为 34 个。
- 34 个文件与本地 `python.zip` 对应文件逐文件一致。
- 不同文件为 0，缺失文件为 0。
- ZIP 还包含 3253 个依赖层文件，不能由上游 Git 核心树证明来源。
- 本地 `python.zip` SHA-256 为 `d55f1deea7351f1e83168db5fd533b9740fcd0bc429a6c1fbc53bda135c33aa2`。
- 候选运行时完成过 `start -> restart -> stop -> start -> stop` 隔离生命周期验证。

ENV-1B2P 当前 Draft PR 使用标准库验证器对唯一外部候选重新执行只读核验，机器摘要见 [ENV-1B2P 实施与证据文档](../env/ENV-1B2P-WINDOWS-RUNTIME-PROVENANCE-EVIDENCE-2026-07.md)。结果保持严格分层：

```text
core_runtime_provenance_verified=true
dependency_layer_rebuilt_and_verified=false
archive_provenance_verified=false
production_approved=false
```

core 为 `true` 的依据是固定 commit 的 34 个 Git 核心、source archive 对应 34 文件、候选实际核心和受控 `python310._pth` 变换均逐项绑定，候选解释器身份与检查前后树摘要一致。dependency 为 `false`：lock / 30-wheel SHA-256 闭合通过，实际 33 个 distribution 等于 30 个 lock 项加固定 bootstrap allowlist（`pip`、`setuptools`、`wheel`），但现有证据缺少独立 rebuild attestation 和独立 pip-check report。archive 为 `false`，因为历史 source `python.zip` 不是 assembled candidate archive，且没有独立 archive build record。外部人工报告或 Runtime manifest 内的 `offline`、`pip_check_passed`、`build_process_record_sha256` 等自声明不能单独提升任何层。

ENV-1B2P 的 future true-path 必须将 rebuild attestation、pip-check report 和 archive build record 作为显式独立输入；Runtime manifest 只提供 filename / SHA-256 绑定，验证器必须重算 artifact 哈希并核对候选树、安装闭包、lock、wheelhouse、ABI、commit、命令退出结果和 archive 内容。assembled archive 的普通文件路径集合必须精确等于 `root_prefix` 下 full inventory 的展开集合，build record entry count 也必须等于该集合大小；root-prefix 外夹带文件、兄弟目录、第二个 Runtime 根和未声明 metadata 均为 `failed_integrity`，本阶段没有 metadata allowlist。artifact 缺失为 `insufficient`；已提供但哈希或内容冲突为 `failed_integrity`。

该复核证据的 enterprise commit 为历史 `396cccc`，当前代码基线为 `a53885b`；证据内部没有 commit 冲突，但没有重跑 PR #81 合并后的完整应用生命周期。ENV-1B2P 合并前，上述实现和机器结论只属于当前 Draft PR；无论是否合并，均不得标记 `production_approved=true`。

## 正式证据要求

- Python 精确版本、实现、架构和 ABI。
- `python.exe`、核心 DLL、标准库和 `._pth` 哈希。
- 依赖锁、wheel 文件哈希、安装闭包和 `pip check` 结果。
- 构建工具版本、构建时间、上游和企业 commit。
- runtime manifest、SBOM、第三方许可证清单和完整归档哈希。
- 清空 `PYTHONPATH`、无系统 Python 条件下的导入与生命周期验证。

## ENV-1B2A implementation-status addendum（2026-07-28）

ENV-1B2A 不改写上述历史候选事实，而是使用官方 CPython 3.10.11 Windows x64 embeddable ZIP（SHA-256 `608619f8619075629c9c69f361352a0da6ed7e62f83a0e19c63e0ea32eb7629d`）、30 项精确哈希 dependency lock、闭合 wheelhouse 和固定 3 项 bootstrap allowlist 从全新目录执行两次离线构建。两次 Runtime tree SHA-256 均为 `6dbeb669533b082a0fe5ca01239692288388df3d27ba4338f6bfe8f5aa6b9887`，两次 assembled archive SHA-256 均为 `f57d50c4184f4fe6d07dc86423b4d266455f976d2011894838aa3526ca6c09c0`。

独立 rebuild attestation、真实 `pip check`、installed closure、CycloneDX 1.6 SBOM、full inventory 和 archive build record 均以实际 SHA-256 相互绑定。现有 verifier 的本次仓库外结果为：

```text
core_runtime_provenance_verified=true
dependency_layer_rebuilt_and_verified=true
archive_provenance_verified=true
production_approved=false
```

真实 Build A 还通过 B2 fixed launcher/host/supervisor/fixture-child 启停验证，Runtime tree 前后不变。详情见 [ENV-1B2A 实施记录](../env/ENV-1B2A-REPRODUCIBLE-WINDOWS-RUNTIME-IMPLEMENTATION-2026-07.md)。该证据不完成 ENV-1B2B 新 Python qualification、clean-Windows validation、Manifest v2、activation、formal Release 或 production approval。

## ENV-1B2B implementation-status addendum（2026-07-28）

Python 版本资格门禁已选择仍受支持、提供 Windows x64 embeddable package 的 ordinary-GIL CPython 3.14.6。ENV-1B2B 已将 Git-tracked 唯一 active source policy、完整官方 36-file inventory、30 项应用依赖 lock、3 项 bootstrap wheel、builder/verifier 和 startup identity/preflight 契约迁移到 `cp314`，且 repository implementation 与 Python 3.14 Runtime candidate 已通过独立代码与证据审查；CPython 3.10.11 的 ENV-1B2A 证据继续作为历史证据与 rollback baseline 保留，不建立双 active profile 或 operator version selector。

仓库外两次独立 clean build、33 项精确 installed closure、真实 `pip check`、Requires-Dist graph、CycloneDX 1.6 SBOM、deterministic archive、三层 provenance 和真实 fixed-Python formal-entry fixture 已绑定同一 clean Git HEAD/tree并通过独立审查。`ENV_1B2B_repository_implementation_independently_accepted=true`、`Python_3_14_Runtime_candidate_independently_accepted=true`、`new_Python_version_repository_implemented=true`、`ENV_1B2_completed=true`。完整 repository regression 由 CPython 3.11.9 执行并通过；目标 CP314 已验证 formal-entry fixture，但未执行完整 enterprise suite。`clean_Windows_validation=false`、`github_ci_verified=false`、`Manifest_v2_implemented=false`、`Release_activation_implemented=false`、`OPS_3B_implemented=false`、`formal_Release_created=false`、`Production_Baseline_approved=false`、`production_approved=false`、`production_validation=false`。

## 后果

- 不能直接把历史 ZIP 或当前 `python/` 复制为正式环境。
- 当前 PATH / `sys.executable` 回退继续被记录为待 ENV-1B1C 关闭的兼容行为，不是已接受的 portable-release 终态。
- 正式 Release 构建需要可重复、离线、同 ABI 的依赖输入。
- Python 版本升级必须通过上游、企业 Gateway、runtime、OPS 和功能回归，不因短期兼容而无限期停留在 3.10.11。
