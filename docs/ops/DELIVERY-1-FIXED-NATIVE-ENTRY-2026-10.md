# DELIVERY-1：固定原生入口逐项回归

记录日期：2026-10-05。本文是本轮实施证据，不是新路线图、客户安装教程或生产批准。状态只见 [CURRENT](../CURRENT_PROJECT_STATUS.md)，任务顺序只见 [路线图](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md)。

第 1–5 节保留固定入口首轮的准确基线与当时范围；随后合并及安装接线进展见第 6 节，不能把首轮的“未合并/未接线”继续当最新状态。

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

## 6. 主线合并与安装接线增量（2026-10-05）

### 准确基线

- #137 已合并为 `a7ff9ba689f310b419c7c4d375898068e4e80bd7`。
- #138 从文档分支重定到 main 前，确认合成 tree 为 `ce399c18d270f76ef7bd02b16362cf3c829344ae`，与已经通过 CI 的准确 tree 相同，再合并为 `65d3f8a936e082e6e991be24f0800901c497f3fd`。其固定入口 CI 为 38 passed，Enterprise 为 1051 passed/21 skipped，Runtime 为 36 passed；未额外手动重跑旧门禁。
- 新候选 `codex/delivery-install-entry-20261005` 从该 main 出发，不合入客户维护线整个目录树，不修改公开 Release 或 VERSION。

### 实现范围

1. 原 Inno 安装器嵌入同准确 commit/tree 的独立 `InfiniteCanvas.exe` 和构建记录；构建器逐项绑定原生文件/policy/哈希，不从未知 EXE 拼包。编译输出仍只允许全新外部构建根。
2. 新装复用 `install_greenfield()`，在最终 current pointer 前发布根目录入口与 `state/installation.json`；指针发布前失败只撤销本次拥有的入口/新装文件。
3. 实例使用独立 UUID，不用路径/版本号充当身份；已有记录保留 ID/通道。快捷方式指向根 EXE，不再找 `releases/<版本>/BAT`。HKCU 只作有限定位提示，Python 再核验完整安装，不扫描 D 盘或其它项目。
4. 明确 `repair-entry` 操作，已有安装不接受首个管理员凭据，不重建账号/数据库、不改配置或版本指针。完整程序/运行环境修复与应用更新不是这一操作的别名，业务更新暂仍通过原更新中心。
5. 入口发布使用共用更新锁、原文件内容/文件身份比较、写入前入口备份与拥有者限定恢复；恢复不明保留锁和证据。检查未完成升级作业时不为此创建 staging 目录，取得锁后再次检查，防止检查与加锁之间出现待恢复作业；保留既有恢复审计规则。
6. 编译/安装副本发现本机关闭长路径策略时过深解包失败；新装增加写入前目的路径检查和中文原因，修复也校验该边界。不更改系统策略，不用短路径通过结果宣称任意长路径兼容。

### 验证与剩余边界

- 六个受影响 Python 测试文件共 159 passed、1 skipped（本机 symlink 权限不足）、2 个既有 FastAPI 弃用警告，覆盖原新装、当前用户真实 named pipe、入口写入/恢复、更新锁与恢复审计；没有手动重跑 PR 全套门禁。文档检查 123 文档/213 链接/21 冻结文件通过，17 个检查器单元测试通过；完整命令在该候选 PR 记录。
- 固定 Inno 7.1.0 的官方安装器及编译器闭包哈希核准后，用官方 portable 模式解包到本项目开发目录，无标准工具安装/卸载登记；[官方 portable 源码](https://github.com/jrsoftware/issrc/blob/is-7_1_0/isportable.iss) 定义该模式。本轮 Pascal/快捷方式改动实际双编译通过且字节相同，产物只含编译样本，不可向客户分发。
- 使用完整已公开 09.5 与 09.9 归档，按严格 Manifest/inventory 物化独立副本。两次入口修复和实际 EXE `--identity` 通过，数据库/画布/素材/配置/原指针文件逐项保持；数据库是明确不打开的保留样本，不是客户数据库迁移验证。
- 三个 Windows 用例通过：实际安装器双编译 1 项，完整公开程序副本入口修复/身份核验 2 项（首次因未设置编译器环境变量跳过的用例已单独补跑通过）。本地 EXE 身份核验约 11.8 秒（09.5）/11.6 秒（09.9），非服务启动时间；这是开发设备实测，不代表客户设备性能。不降低闭包校验来掩盖耗时。
- Windows 定向 CI 补齐安装接线路径触发、固定 portable Inno、SHA-256 锁定公开资产和编译后检查；资源缺失不能把跳过当通过。
- 尚未完成：真实新包 GUI 新装/修复点击、真实 Supervisor 启停、worker 截止/取消、标准卸载、完整程序/环境修复、入口维护崩溃后图形恢复、多跳/自更新、所有历史来源兼容。未知损坏或未完成锁会阻止而不是冒险接管。
- 仅代码候选与验证资源交付；没有新应用 Release、客户更新、系统设置修改、付费 Provider 调用或遥测上传。开发产物统一在 `Infinite-Canvas-Enterprise-Artifacts` 专用子目录；没有清理其它项目或客户数据。
