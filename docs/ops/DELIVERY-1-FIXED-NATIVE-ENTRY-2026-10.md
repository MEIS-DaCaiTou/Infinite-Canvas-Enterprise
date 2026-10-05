# DELIVERY-1：固定原生入口逐项回归

记录日期：2026-10-05。本文是本轮实施证据，不是新路线图、客户安装教程或生产批准。状态只见 [CURRENT](../CURRENT_PROJECT_STATUS.md)，任务顺序只见 [路线图](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md)。

## 1. 准确基线与文档审查

- 主线：`7905ecf39efabeb3101d7b63c709d8dcd230c9a0`，本轮未修改。
- 依赖：[PR #137](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/137)，Base 为上述 main，Head `f229dc65a5e2982c70ddd813327cdea6270caf20`。
- 10-05 核验该 Head 的 Documentation、Enterprise、Runtime 三项检查均通过，未额外重跑门禁。对准确二进制 Git diff 的只读风险审查未发现阻断问题，建议合并；未执行合并。diff SHA-256：`46366e90b78764c3ba343e6d547bf68ee8460ecef1d85b144a5825e205d5bac3`。
- 新候选：`codex/delivery-fixed-entry-20261005`，从 #137 准确 Head 建立，必须区分依赖 PR、候选和已合并 main；不是从客户维护分支整体覆盖主线。
- 入口来源：维护线 PR #136 Head `f86754867c2ecf10ca1b32b66dc926371fe9f0b2` 中已存在的 `NativeCore.cs`、`LauncherProgram.cs`、`app.manifest`，保留其薄入口职责。旧维护线缺少部分主线安全代码、任务回执和测试，因此只按模块回归，不合入其整个目录树。

## 2. 实现与不实现

`installer/windows/native/` 包含 C# 薄入口：

1. 从安装根的 `state/current-release.json` 读取准确生效 Release，不绑定 09.9 或某个版本号。
2. 核验 pointer、Manifest、inventory 与文件闭包；拒绝缺失、修改、多余文件、路径逃逸或 reparse。
3. 使用该 Release 自带的 Python，以 `-I -B` 直接调用既有 Python Runtime launcher；C# 不复制 Supervisor、更新或数据迁移引擎。
4. 图形外壳提供启停、重启、状态与脱敏摘要；CLI 错误不弹阻塞对话框，结果文件不覆盖已有用户文件。

`tools/build_native_entry.py` 与独立 policy：

- 无历史目录、目标 Release 或数据库版本依赖，不复制固定到 09.9 的整套升级器构建。
- 使用外置固定 Roslyn 4.12.0 官方 package；验证 package SHA-256 及解包后完整 net472 编译器闭包。
- 构建输出只能位于全新的外部 artifact 子目录，拒绝现存/重叠/重解析路径；不接触客户数据、配置、指针、快捷方式或注册表。
- 默认只构建干净准确 Git 提交；实验脏构建必须显式标记，不用于发布。
- 两次确定性编译按字节比较，记录提交/tree、源码/policy/工具链/EXE 哈希；产物未做 Windows 发布者签名，不关闭系统安全保护。
- 为 C#、应用 manifest 和构建 policy 显式固定 Git 的 LF 检出契约；首次 CI 暴露 Windows CRLF/LF 差异会改变 EXE，已补格式契约与回归，不仅比较同一目录内的两次编译。

本轮**不包含**历史数据库接管、普通更新替换逻辑、多跳、自更新、安装身份登记、安装器接线、新装/修复/卸载、旧快捷方式替换或完整桌面客户端。现有客户公开资产和 VERSION 不变。构建出来的独立 EXE 不是可供客户新装的安装包。

## 3. 验证证据与边界

本地 Windows 定向结果：

| 验证 | 结果 | 证据边界 |
| --- | --- | --- |
| 构建 policy/工具链闭包/输出归属/脏源码阻断与 LF 检出契约 | 20 passed，1 skipped | 被跳过项是本机不能创建测试 symlink；不是被测路径防护被关闭 |
| 实际编译 EXE 契约 | 17 passed | 真实 EXE + 最小 pointer/payload + 测试 C# worker，未启动 Python 或真实服务 |
| 旧 Windows wrapper 兼容及 APP_ROOT 写入审计 | 20 passed | 与新构建合计 40 passed、1 skipped；未手动重跑全套 Runtime |
| 文档契约及登记检查 | 17 单元测试通过；123 文档、213 链接、21 冻结文件检查通过 | 不证明外部链接和客户功能，未改写冻结验收 |
| 双构建 | 两次 EXE 字节完全一致，22,528 字节 | 本地首次为显式脏实验构建；可发布身份需再从干净提交构建并留记录 |

编译后测试覆盖：固定根默认定位；`source→target→source` 指针切换/回退；同一 EXE 不变；中文/空格路径；五种 Runtime 命令的固定参数、工作目录和 Python 环境清理；Manifest/Python 修改、陌生文件、缺文件、指针逃逸/重复字段；多命令/未知参数与结果文件不覆盖。安装副本的 `data`、`config`、素材和原始指针/程序快照保留。

这些最小夹具不是完整公开 Release，不证明数据库迁移、真实 Supervisor 启停、GUI 点击、浏览器打开或客户长期运行。复用的 Runtime 自有其原测试，本轮不据此扩大现场批准。

新增 `native-entry-checks.yml` 在受影响 PR 的 Windows CI 下载并核验固定编译器，干净提交双构建后执行上述两个文件，仅保留 7 天验证产物；不是 Release 自动发布。PR 的 CI 结果以检查页面为准，不把新任务与 #137 旧检查混用。

新构建写入按现有 W44 外部构建流登记；保留 W48 画布任务回执、W49 数据登记/迁移审计，不用维护线映射覆盖主线。文档仍由登记表管理，不改冻结验收资源。

## 4. 开发者验证入口

仅用于开发环境，不要求客户执行命令行：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
py -3.11 -B -m pytest -q enterprise/tests/test_native_entry_build.py
```

编译需要 Windows、系统 .NET Framework、已核验的 compiler package 和完整外置编译器目录；使用 `tools/build_native_entry.py --help` 的显式参数，输出指定全新产品 artifact 子目录，禁止选择客户安装或已有输出。

运行编译后契约时设置 `ICE_NATIVE_ENTRY`、`ICE_NATIVE_COMPILER_PACKAGE`、`ICE_NATIVE_COMPILER_ROOT`，再运行 `test_native_entry_windows.py`；缺少二进制时明确 skip，不能当作实际 EXE 已验证。C# `enterprise/tests/fixtures/native/ContractWorker.cs` 仅供测试，不能作为 Python 运行时分发。

## 5. 仍需验收的风险

- #137 尚未合并；候选的依赖关系和后续 main 基线必须明确。
- 全文件哈希验证的真实安装耗时尚未测量；不降低校验来掩盖性能问题。
- C# worker 等待未增加独立超时/取消；真实 Runtime 故障阻塞和关闭行为需在安装副本专门验证，不能仅以测试 worker 很快退出认定完成。
- 完整 Release 的真实启停、升级中/回退中的进程所有权，以及图形体验需补证。
- 历史 18/28 对象资格、main 的迁移登记与维护线目标 schema 不能无审查混用；后续仍需逐项兼容矩阵。
- 稳定安装身份、固定入口安全发布/修复、快捷方式、保留数据卸载及各入口共用升级引擎尚未实现。这里只落实统一交付 ADR 的一项基础，不改变后续阶段的进入条件。
