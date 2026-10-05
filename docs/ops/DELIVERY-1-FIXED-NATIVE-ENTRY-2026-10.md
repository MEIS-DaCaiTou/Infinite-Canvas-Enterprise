# DELIVERY-1：固定原生入口逐项回归

记录日期：2026-10-05。本文是本轮实施证据，不是新路线图、客户安装教程或生产批准。状态只见 [CURRENT](../CURRENT_PROJECT_STATUS.md)，任务顺序只见 [路线图](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md)。

第 1–5 节保留固定入口首轮的准确基线与当时范围；安装接线见第 6 节，#139 合并及实际安装副本演练见第 7 节，#140 合并及同版本程序修复候选见第 8 节。不能把旧轮次的“未合并/未接线/未启动”继续当最新状态。

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

## 7. #139 审查合并、完整安装副本与实际 Runtime（2026-10-05）

### 审查与来源

- #139 Base `65d3f8a936e082e6e991be24f0800901c497f3fd`，准确 Head `2bad146d39a08f8bf744633baa3a1a993b85d692`，tree `b4f3bf024663a94ff87f2396c03543a50623ea8b`。既有四项检查全部成功：Documentation、Enterprise（1077 passed/24 skipped）、Runtime（36 passed）及 Windows 固定入口（38 passed＋3 项安装接线检查）。没有手动重跑其全套门禁。
- [审查记录](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/139#issuecomment-5989094779) 核对指针最后发布、同源构建、入口修复不改库/账号、共用锁、拥有者限定回退和恢复竞态；没有阻断发现。按准确 Head 合并为 `dc6a24fae88a74848d2c6d0eb6a088d892a1e2e3`，merge tree 与上述已测试 tree 一致。
- 本轮后续候选 `codex/delivery-maintenance-drills-20261005` 从该 main 出发，实施提交 `dc8285c378a80625d3802f2c066660cf7534b016`，tree `6ad2229564ba0c7e5ff3397fcb97261fec2c0c20`。保持源码 VERSION 不变；下面的 `2026.08.5` 是本轮 main 构建候选标签，**不是新发布的客户 08.5，也不是 09.9 的升级包**。
- 同提交 native/完整 Release/完整 Setup 均从干净源码构建；复用严格核验的原始 Runtime（CPython 3.14.6、1913 文件、63,186,281 字节），不重新下载依赖或混用修改过的客户程序。所有输出在 `Infinite-Canvas-Enterprise-Artifacts/development/delivery-entry/20261005` 与专用 `t/M5*` 子目录，不在 D 盘根目录生成散落文件夹。

### 实测发现及修正

1. 首次完整安装副本运行在 #139 main 上，四项安装/入口恢复检查通过，真实服务启动失败：`RUNTIME_SERVICE_HOST_EARLY_EXIT`，host 分类为 `host_entry_failed`。只读定位发现 Windows 包目录重定向使 `Path.resolve()` 将已核验 KnownFolder 的逻辑目录替换成物理目录，第二次 portable context 检查因目录身份不匹配而拒绝；不是缺少 Python，也不是数据库损坏。
2. `_paths()` 对 portable host 保留原可信目录拼写，但仍先执行原 containment 检查，随后 host/supervisor 完整核验 PathRoots、Manifest、Python 与进程身份。新增测试先在旧实现得到 1 failed/2 passed，修正后通过；开发模式继续使用原 resolved 路径，运行目录在 APP_ROOT 内的情况仍拒绝。没有放宽安全检查或改 Windows 策略。
3. 经用户授权浏览旧候选的修复向导：到准备页即取消，不填写密码、不执行安装、不改快捷方式/登记。实测准备页缺少实际目录和修复范围，环境页说明也更新过晚。本轮在 `CurPageChanged` 进入环境页时显示目录与“入口专用修复”，`UpdateReadyMemo` 最后确认页标明不是业务升级、不改数据库/管理员/当前版本。回调签名按 [Inno 官方事件说明](https://jrsoftware.org/ishelp/topic_scriptevents.htm) 校核；真实双编译通过。修正包的图形复查尚待单独确认，不把源码断言或编译成功当点击验收。

### 安装副本验证

`enterprise/tests/test_install_maintenance_windows.py` 使用完整物化程序、实际内置 Python 和当前用户 SID named pipe，不调用 GUI 的安装按钮、不修改注册表或快捷方式：

| 场景 | 结果与实际证据 |
| --- | --- |
| 新装、重复安装、两次入口修复 | #139 main 副本通过；SQLite 完整性 ok，首个超级管理员恰好 1 个、审计已建立；重复安装被阻止且所有文件快照不变，两次修复保留实例 ID/库/画布/素材/配置/指针 |
| 新装指针发布前失败 | 注入失败时入口和真实 SQLite 已准备；只撤销本次新建安装根，重试成功，不留下半个“已安装”实例 |
| 入口发布后出现待恢复作业 | 注入检查竞态后回退本次入口文件，保留原文件快照和备份证据，释放已证明可恢复的锁；后续修复成功且 ID 不变 |
| 未知锁 | 阻止维护，不删除锁、不重建目录或数据库，文件快照不变；这不是崩溃后自动恢复能力 |
| 实际根 EXE 与 Supervisor | 修正提交完整副本通过；真实 start/health/status/stop，Gateway/Upstream HTTP 200，匹配 Release 与进程身份；stop ACK 确认 Supervisor 退出、两子进程优雅停止、两随机端口释放，库/画布/素材/配置/指针/实例记录保留 |

准确命令与运行边界：

- 第一次：`test_install_maintenance_windows.py` 五场景执行为 **4 passed/1 failed**，资源来自干净 `main@dc6a24f`，证据根 `t/M5C`。没有抹去首次失败。
- 修正后仅复测受影响场景：`-k actual_native_entry`，资源来自 `dc8285c`，证据根 `t/M5D`，**1 passed/4 deselected**，152.23 秒；EXE 的 status/start/health/status/stop 全周期 84.656 秒，包含重复完整校验和停止后探针，并非“启动耗时 84 秒”。
- 安装 Python 定向回归：`test_install_ux_1.py test_install_entry.py test_install_mvp_1.py`，**76 passed/1 skipped**。
- Runtime 路径/绑定/监督定向回归：`test_env_1b1c_b2_portable.py test_env_1b1c_b2_lifecycle_identity.py test_env_1b1b_path_roots.py test_stab_1_supervisor_logging.py`，**140 passed/3 skipped**。跳过不计验收；没有手动跑 Enterprise 全套门禁。
- APP_ROOT 写入审计与其回归 **7 passed/23 deselected**；文档检查 **123 文档、214 本地链接、21 冻结文件** 通过，文档检查器 **17 单元测试** 通过。新记录只扩展既有 DELIVERY-1，不另建状态表或交接包。
- 当前用户 Runtime 目录仍共用：服务演练先检查无活动实例，只使用动态测试端口；不得为测试停止其它安装。临时 Runtime/cache 的可信 KnownFolder 使用与生产入口相同，未伪造环境覆盖。不据此宣称多实例同时运行已支持。

### 完整候选构建身份

Release `ice-2026.08.5-dc8285c378a8`，2115 个 inventory 文件；干净同源原生/安装器双构建一致，未签名、`production_approved=false`：

| 资产 | SHA-256 |
| --- | --- |
| 根入口 InfiniteCanvas.exe（22,528 字节） | `570ad6885cae124e39f534bc6a95073212eec0ad4d9c1d8085f5e0888d3987fd` |
| 完整 Release ZIP | `11ae862e6d85c9861dc585315ca3b600d4b5ebbf51017e0a93cc0f719f264c55` |
| ops-release-manifest-v2.json | `c3b40b2b03f94bdbf67bf1e6dd40bb6aff8ceda8ce274ccb8a66a75245aa0b03` |
| release-payload-inventory.json | `a1f54a41fdb2d5eba1443d5848be89daed071ab4b3503a79acd10fb09802894c` |
| 完整候选 Setup（33,099,933 字节） | `3a129dd252c1c95ccb12521367a17ab92cd739051447f03b7502edb1ee943db4` |

builder 的报告单独保存；交给安装器的资产目录仅含严格三资产，附加报告会被阻止，不能因此放宽闭包检查。本轮未发布候选应用/安装器，也未更换已公开 Release 资产。

### 仍未交付

完整程序/Python 环境损坏修复、标准保留数据卸载、维护进程被终止后的图形恢复、worker 截止/取消、自动多跳/自更新、历史来源统一业务升级，以及客户实际图形新装/修复和长期运行验收仍未完成。入口修复的已知异常回退和未知锁阻止不能替代这些能力；当前阶段仍为阶段 3，不启动大规模业务扩张。

本轮未连接客户设备、使用客户数据/密码、执行付费生成、改系统安全策略、开启诊断上传或清理其它项目。配置中的测试凭据仅属新建夹具，不写进公共测试输出或 PR。

## 8. #140 审查合并与程序/Python 修复候选（2026-10-05）

### 主线基线与审查

- #140 Base `dc6a24fae88a74848d2c6d0eb6a088d892a1e2e3`，Head `c8715ebe534d7453e0222725d50c258e7eb0cfbe`。准确 binary commit-range diff 共 56,267 字节，SHA-256 `844288b586e8b6510cb49408ce73dd0ed60f9946911990166a0695a94cee63cf`。
- 只读补丁影响审查检查 portable 路径/进程身份、安装器回调与现有测试，未发现阻断；建议经授权审查合并，不把尚未执行的修正向导点击写成验收。审查记录见 [#140 comment](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/140#issuecomment-5990288062)。
- 准确 Head 四项 CI 全通过：Enterprise **1081 passed/29 skipped**、Runtime **36 passed**、原生构建/入口 **38 passed**＋安装检查 **3 passed**、文档检查及其 **17 单元测试**。CI 链接见 CURRENT；本轮没有额外手动重跑 #140 全套门禁。
- 10-05 合并为 `ef4523d7c78a4422021c388289dea44bc341ae3d`，merge tree `c1da3d2ad629bd099bed556cfcff1e2d44f44ab1` 与已测试 Head tree 一致。
- 本轮新候选 `codex/delivery-program-repair-20261005` 从该 main 创建，实现提交 `16f77c67f862af93a88ef99dc8de06818ba38147`。后面的安装包用于安装副本验证，未发布、不代替客户 09.9；主线/候选/公开 Release 分开。

### 新实现范围

`enterprise.install_repair` 只修复已登记、停止状态、**同一准确 Release/Manifest** 的程序目录和内置 Python，使用外部已核验完整包，不能要求损坏的安装 Python 自行修复。

1. 复用 Manifest v2 校验/物化、安装身份验证、current pointer、共用维护锁和 Runtime 检查；不另写数据库升级引擎。只有已知程序路径允许损坏/缺失，额外未知文件/空目录拒绝，不猜测文件归属。
2. 在安装根自己的 `staging/program-repairs/<操作短 ID>/` 准备 candidate、不可覆盖 plan/result 和独占 kernel lease；过深目的路径在准备前阻止。原始损坏树与 rejected 新树保留为证据，不递归清理未知目录。
3. 共用 `system-update-active.lock` 与当前用户 Runtime fence。启动预约创建后再次检查 fence，避免修复与启动竞争。读当前 Runtime 状态/进程/端口，不停止、杀死或接管其它安装；未知锁/活动 Runtime 阻止操作。
4. 准备成功再移动停止的程序目录；不打开业务数据库、不创建账号、不写配置/画布/素材/实例记录/根入口/版本指针。任务中心尚未完整交付，要求明确确认没有活动任务，不宣称可排空所有旧内存任务。
5. 普通失败恢复修复前树；真实执行器退出后 kernel lease 由操作系统释放，第二执行器重新核验 plan、锁、文件身份和内容。没有成功记录时恢复原树；成功记录和新树一致时完成释放，不把成功操作转成回退。
6. identity/pointer/plan/备份/锁变动、存活执行器或未知状态保持阻断和证据。**回退到原损坏程序只是恢复修复前一致状态，并不等于已修好；核验后可重试修复。** 不通过删锁或重建数据库“恢复”。

`install_setup_bridge` 保留 v1/v2 的封闭协议，新增 v3 仅接 `repair-program` / `recover-program`，必须显式任务确认，拒绝管理员凭据和未知字段。当前 Inno 仍是 v2 入口专用修复；新后台 handler 不等于图形按钮已交付，也不接管旧入口专用锁或业务更新 RECOVERY_REQUIRED。

### 定向验证与完整构建

- 安装/入口/新程序修复初轮回归 **104 passed/1 skipped**；补严格端口语法后，新程序修复文件 **34 passed**。覆盖丢失整个程序目录、程序/Python 损坏、已知错误回退、五个中断点、未知文件/空目录/任务状态/待恢复作业阻止、身份/指针/计划/备份/锁变化保持证据、存活执行器不被抢占，以及两种启动预约的 fence 竞争。
- Runtime 受影响路径/进程/监督回归：`test_runtime_reliability.py test_env_1b1c_b2_portable.py test_env_1b1c_b2_lifecycle_identity.py test_stab_1_supervisor_logging.py`，**106 passed**，266.37 秒；现有 FastAPI 事件弃用警告未扩大为本轮无关改造。
- APP_ROOT 写入审计 **7 passed/23 deselected**。新写入明确属于 W47 停止状态同版本维护例外，Runtime fence 归 W26；不宣称 APP_ROOT 在所有维护阶段绝对不可写。冻结清单哈希 `c6674e2e2e465949c6294180d5ae8099f37e879a9320e3a38da9663c1cee8af1`，467 站点全部映射，无解析/未覆盖/漂移错误。
- 从干净实现提交构建 `ice-2026.08.5-16f77c67f862`，tree `4ebffc68166dcb43e00b8b0deef46617338f52bb`，2116 个 inventory 文件；复用已核验 Runtime，仅重新构建应用，原生入口双构建一致且未签名。这个 VERSION 是主线历史值，不是客户升级推荐版本。

完整安装副本用实际内置 CPython 3.14 和当前用户 SID named pipe 执行 v3 handler，**4 passed/5 deselected**，565.08 秒；证据根 `t/R6A1`。这里没有替换 OS Runtime 观察，也没有模拟进程退出：测试子进程用 `os._exit(86)` 直接退出，第二个独立进程接管已释放 kernel lease。

| 实际安装副本场景 | 验证结果 |
| --- | --- |
| 程序损坏且 Python EXE 缺失 | 外部维护 Python 修复成功，完整 inventory 复核通过；库完整性/账号/审计及库/配置/画布/素材/指针/身份/根入口快照保持 |
| 原树已移动后直接退出 | 第二进程恢复原损坏树，保留记录；重新修复成功，业务快照不变 |
| 新树已发布、成功尚未记录时退出 | 第二进程只回退自身计划的新树，恢复原树；重试成功，不变更业务数据 |
| 已记录成功、释放锁前退出 | 第二进程复核新树和成功记录，完成释放，不回退已成功操作；业务快照不变 |

总耗时包括准备资源、多次新装、校验、故障注入、恢复和重试，不能当作一次修复耗时或客户端进度百分比。GUI/取消/性能优化需单独测量，不降低闭包校验。

另外仅执行受影响的修复后实际生命周期场景：`-k actual_native_entry`，**1 passed/8 deselected**，205.29 秒，证据根 `t/R6L1`。先损坏并修复完整程序/Python，再通过根 EXE 实际 start/health/status/stop；Gateway/Upstream HTTP 200、readiness/进程/Release 身份匹配，stop ACK 确认退出和两随机端口释放，库完整性 ok，画布/素材/配置/指针/实例记录不变。单独 EXE 生命周期测量为 83.875 秒，不包含前面的新装和修复准备，不可当作纯启动时长。未重复执行前面的四个整包场景或其它旧门禁。

文档检查通过 **123 文档、214 本地链接、21 冻结文件**，检查器 **17 单元测试** 通过；这些不是额外业务验收。本轮新增原始文件只有程序修复模块及其定向测试，文档复用现有事实源/实施记录，未增加另一套交接/规划目录。

| 验证资产 | SHA-256 |
| --- | --- |
| 根入口 InfiniteCanvas.exe（22,528 字节） | `570ad6885cae124e39f534bc6a95073212eec0ad4d9c1d8085f5e0888d3987fd` |
| 完整 Release ZIP | `258cd0a0b4823538f6cb559121411d7be641dd549eb01cb1a540aae85886b9e4` |
| ops-release-manifest-v2.json | `f89f82c8dda75405bfdbce2f1e2a1efb8e0623c6149376968829973a825258ac` |
| release-payload-inventory.json | `84aaeceb67841bc9a820fe90d3ce4ffa8920567792c5f50c21c92ec15c6df577` |

构建根集中于 `D:\CodeProject\Infinite-Canvas-Enterprise-Artifacts\development\program-repair\20261005`；短测试根只在该产品 artifact 的 `t/R6*` 下新建。没有在 D 盘根目录新增散落目录，没有清理其它项目、旧用户安装或配置。原始开发 checkout 未修改。

### 尚未交付

本轮仍需新候选的 CI/审查及 Inno v3 图形接线、恢复状态解释/跨窗口进度、入口旧锁崩溃恢复、worker 截止/取消、标准保留数据卸载、磁盘/备份容量和清理策略、历史接管升级收敛。没有新客户应用 Release、图形安装执行、客户设备验证、断电/硬件故障恢复、更新器自更新、多跳、业务升级/迁移、机器级服务或多实例运行验收。不使用当前用户共享 Runtime 来推断多安装并行已支持。
