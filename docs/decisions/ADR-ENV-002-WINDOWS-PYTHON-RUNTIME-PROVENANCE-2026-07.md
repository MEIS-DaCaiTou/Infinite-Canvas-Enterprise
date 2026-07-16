# ADR-ENV-002：Windows Python 运行时与来源证据

- 状态：Accepted
- 决策日期：2026-07-16
- 事实基线：`main@396cccc68d63bd16393a2cb72d24e4a48fcf47cb`
- 实施状态：候选验证已完成，正式 Release 运行时尚未批准

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

因此当前结论是：核心解释器可绑定到固定上游提交；依赖层需要从锁文件和可信 wheelhouse 重建；完整 archive provenance 仍未验证。当前运行时不得标记 `production_approved=true`。

## 正式证据要求

- Python 精确版本、实现、架构和 ABI。
- `python.exe`、核心 DLL、标准库和 `._pth` 哈希。
- 依赖锁、wheel 文件哈希、安装闭包和 `pip check` 结果。
- 构建工具版本、构建时间、上游和企业 commit。
- runtime manifest、SBOM、第三方许可证清单和完整归档哈希。
- 清空 `PYTHONPATH`、无系统 Python 条件下的导入与生命周期验证。

## 后果

- 不能直接把历史 ZIP 或当前 `python/` 复制为正式环境。
- 当前 PATH / `sys.executable` 回退继续被记录为待 ENV-1B1C 关闭的兼容行为，不是已接受的 portable-release 终态。
- 正式 Release 构建需要可重复、离线、同 ABI 的依赖输入。
- Python 版本升级必须通过上游、企业 Gateway、runtime、OPS 和功能回归，不因短期兼容而无限期停留在 3.10.11。
