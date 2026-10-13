# 工作包 C2：维护准备包的显式安全清理

日期：2026-10-11。实施顺序沿用 [正式路线图](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md) 阶段 3；不是新路线图，也不改变 [范围锁](../../PROJECT_SCOPE_LOCK.md) 或业务实施授权。

## 基线与完整成果

准确 Head `e1aca8a2acc6f99029e0be2404f1e9e10ec70d78` 经独立技术审查后，#151 于 2026-10-11 合并为 `bdace2a35e10e07c268d0ca7eaf6050f2411d5ad`；随后 #152 合入的新 main 为 `1d8dd4902aa3297a274f2e13b2e333e75d34a1c3`，四项常规 main CI 最终 SUCCESS、opt-in SKIPPED。该收口不授权正式 Release 或生产清理；以下原源码/准备包/限定 GUI 证据继续有效，没有重跑本包全套门禁。

同版入口恢复 #150 已在准确 Head `e24d402a99e6257269eee6175fd0566d6b72b704` 的四项常规 CI、限定真实 Windows 证据和风险审查通过后合并。2026-10-11 北京时间 00:28:13 的合并点为 `main@63394178b4c3d05c491c39d42c75518f000ed3cf`。真实固定 EXE 门禁的 opt-in CI 未运行；#150 的本机 9 场景证据继续见 [入口恢复记录](./ENTRY-REPAIR-RECOVERY-2026-10-10.md)，不重复计入 C2。

C2 单独完成“准备包归属记录 → 占用/恢复依赖核验 → 显式预览与选择 → 隔离清理 → 中断后再次确认继续”工程闭环。保留数据卸载/重装具有不同风险，另属后续工作包。没有新增数据库表、业务政策、自动保留期限、正式发行或生产操作。

## 契约与安全边界

- 只处理当前用户 KnownFolder `Infinite-Canvas-Enterprise/maintenance-payloads/<32hex>/install-ux-bundle` 的 Setup 准备副本。核心三资产、原生入口及完整展开程序必须核验，并且整树不得混入未登记文件、额外空目录、硬链接或 reparse。已有未知/未登记历史包不自动接管或删除。
- 实际 Setup 的 archive 展开目录不含物化工具额外附上的 `release-manifest.json`；闭包核验使用已验证的外置三资产逐成员复核 hash/size，不在原目录补造 metadata。若 raw 内有这份可选 Manifest，必须与外置 Manifest 字节相同，不能接受任意内容。
- `.ledger/<32hex>` 在清理树之外保存封闭字节/文件及目录身份、Release/Manifest、lease 身份和终态。记录不授权删除安装根的 Release、数据库、配置、媒体、备份、Runtime 或历史事务证据。
- 只有维护/检查成功、没有未知恢复依赖、已验证当前用户的 Setup 客户端与后台 worker 均真实退出且 kernel lease 可取得时，才显示 `CLEANABLE`。PID 查询失败不等于不存在；PID 复用按创建身份及可执行路径区分。当前窗口自身准备包继续保留。
- v5 当前用户管道只接受 `inspect-cache` / `clean-cache`；凭据必须为空。清理一次仅绑定一个明确 cache ID、预览 SHA 和布尔确认。预览后任何归属、字节、对象身份、占用或依赖变化都重新阻断；没有自动重试。
- GUI 入口不经过安装发布、快捷方式/注册或自动启动步骤。无默认选择，最终删除确认默认“否”；未知/忙碌项保留。清理会释放所选包的程序副本空间，但创建/使用当前安装器准备包需要空间，不能宣称一次清空所有历史缓存。
- 先持久 `DELETING`，再同卷隔离到 `.quarantine/<32hex>`；不跨卷复制、不覆盖现有隔离目录。文件和目录由 Windows 实际 handle 绑定对象身份后删除/改名；文件另复核字节及单硬链接，拒绝替换文件、写入者和重解析。
- 登记与执行统一使用 Windows `FileIdInfo` 的卷标识及 128 位文件 ID，不依赖 CPython 3.11/3.14 各自的 `st_dev` 编码；时间变化仅在 path/path、fd/fd 同类观测之间比较，不能把 3.14 的创建/变更时间语义差异当作文件替换。依据：[Microsoft FILE_ID_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_info)。
- 不使用 `rmtree` 或目录通配递归删除。未知成员使操作保留剩余材料并停止。隔离后真实进程退出，下一次必须取得新预览并再次明确确认，才允许继续删除原登记、尚存且未变更的成员。不可恢复已删除的程序副本；可从原不可变包重新准备。业务数据与备份不在删除目标内。
- 只有既定的解析/本轮工作量上限：最多 64 个待处理候选、24,000 个树条目、单文件 2 GiB、树 4 GiB。超过上限保持材料、报告阻断；这些不是批准的长期容量、期限或自动清理政策。小型 ledger 证据保留，累计过多仍需另行容量治理。
- 缓存收尾失败不能把已经提交的程序/入口修复误报为失败；返回 `INSTALL_CACHE_RETAINED` 警告，未获充分证据的缓存保留。

## 验证与交付状态

截至本记录日期，实现及本机门禁已经完成，工作包以独立 Draft PR 交付；CI、独立审查及是否合并须另按准确 Head 的 GitHub 记录判断。完整准备包与图形验收使用干净源码 `350f20d87ec70d1d91db41268e1fc30bb986d583`、tree `fd6aa17a613c83ecb7a737b49cd80dfcd575f8a3`；后续本提交仅更新交付文档，不将文档 Head 冒充已构建源码。所有数据、凭据和媒体均为开发机新建的合成 fixture，没有客户数据或付费请求。

| 层次 | 当前证据 | 限制 |
| --- | --- | --- |
| 定向关联回归 | 初轮 137 PASS / 1 SKIP，59.24 秒；实际解包闭包修复后，CPython 3.11 清理与 bridge 合计 62 项 PASS（33.44 秒），bundled CPython 3.14 清理 35 项 PASS（18.97 秒）；追加的两项核验后字节变化场景 2 PASS（1.71 秒） | 小型封闭 fixture；多数退出观测替换，不算完整 GUI 或完整生产负载；计数有重合，不相加；最终 37 项清理合同由 CI 统一执行 |
| 实际完整准备包与 CPython | 同源完整 payload、bundled CPython 3.14、认证管道及真实客户端/worker；4 场景 PASS，1721.90 秒；每次清理后整个合成安装的文件 SHA 不变 | 无进程/verifier/file API 替换；本机特定 Windows 环境、合成单安装，不是生产负载或性能承诺；环境变量缺失的 SKIP 不算 PASS |
| C2 真实图形操作 | 双次一致性编译的实际 Setup；中文自定义合成安装根、预览无默认选择、未知/忙碌项保留、默认“否”的明确删除确认、删除成功及显式刷新通过；负责人在最终点击前明确批准唯一合成副本 | 仅 C2 页面及删除闭环，不是完整新装/修复/卸载/重装 GUI 验收；当前安装器准备包保留，未另行删除 |
| PR / 合并 / Release / 现场 | 独立 PR 交付；CI、审查、Draft 转换和合并分别以准确 Head 的 GitHub 记录为准；本历史记录不自行授权合并 | #150 的合并不是 C2 的合并；本轮没有 Release 或生产/客户操作 |

实验资产：测试 Release ID 为 `ice-2026.08.5-350f20d87ec7`，仅沿用历史 VERSION 构建未发布的开发候选，不改变正式 10.1。

- archive SHA-256：`1de7b2ac9ae7ce08b2599eff756d78bedf39fcd43d56bfe6d22ad0f76b572432`。
- 外置 Manifest SHA-256：`2df2bc9d5b250aa609a484b8cb3a24df49b8502d8769ca39b4120a46e6133a76`。
- Inventory SHA-256：`bb344f7492f539e45240677221846f876592e8065f22e99f2776b2e53388611d`。
- 原生入口 SHA-256：`570ad6885cae124e39f534bc6a95073212eec0ad4d9c1d8085f5e0888d3987fd`；同源双次编译一致，22528 字节。
- Setup SHA-256：`c26ad31aae802043f637416e7b64ad6054e7964749426d586d3cdc3bbe303a07`；固定 Inno 7.1.0 闭包核验及双次编译一致，33153032 字节，未签名、未时间戳。

本机完整输入位于 `D:\CodeProject\review-artifacts\t\WPC2\assets2`、`native2`、`setup2`；四场景使用全新 `WPC2-full-4`，不可作为以后 pytest basetemp 重用。图形实际删除的是明确登记且已关闭的旧合成准备副本 `13cdb24d18ed4e56b0766f28f66a3e3f`（105888171 字节），不是安装目录。其对应合成安装 `WPC2-full-3/i-6a511057` 的 2129 个文件，按相对路径及各文件 SHA-256 聚合的前后指纹同为 `156f7157b26c8400e86cc0068adfd87fb5a87c9b23757b98bbce77aadcf90c34`；记录保留，程序副本可从原资产重新准备。三个未知包及当前 Setup 副本均保留，窗口已正常退出。

本轮主要阻断是运行时/打包真实契约差异，现已消除：CPython 文件时间/卷身份语义、测试错误带入编译 pass 目录、实际 Setup 不含 raw Manifest，以及测试误把既有 import 警告当作管道失败。只接受精确白名单中的既有合成环境 JWT 提示及两个 CPython 3.14 SyntaxWarning；没有屏蔽其他 stderr 或修改发行源码来绕过核验。早前未登记/中止准备包保留，不反复运行相同失败条件。完整 Windows 演练耗时较长，主要是逐对象/字节核验和多次完整准备；未由此设置生产 RTO。

仍未完成：独立审查、C2 合并/发行/现场验收，标准保留数据卸载/重装及其恢复验证，完整安装维护 GUI、多语言验收、长期 ledger/容量治理。维护后退出仍使用 Inno 的标准安装退出文案，属于后续完整 GUI 收口项，不能据此把本次只清理流程写成进行了安装。正式路线图和业务授权不变。

可重复定向检查：`python -B -m pytest -q enterprise/tests/test_install_cache.py enterprise/tests/test_install_ux_1.py enterprise/tests/test_install_entry.py enterprise/tests/test_install_program_repair.py enterprise/tests/test_install_repair_status.py`。测试根应是本轮全新、明确属于测试的短路径；pytest 的旧 `--basetemp` 不可复用，因为框架会先清空它。

真实准备包演练：设置 `ICE_CACHE_RELEASE_ASSETS` 为准确干净源码构建的三资产目录，`ICE_NATIVE_ENTRY` 为同源编译入口，运行 `enterprise/tests/test_install_cache_windows.py`。四个 opt-in 场景不得仅以 CI 跳过替代：后台退出而 Setup 客户端仍活跃的保留、实际 v5 清理、隔离后进程死亡、删除首个成员后进程死亡；核对整个合成安装的文件 SHA 保持一致。

CI 自动执行小型 CPython 3.11/3.14 清理合同及既有静态/入口编译检查；完整准备包和真实 GUI 门禁另列。APP_ROOT 写审计 W47 新增只限本模块的明确写符号；扫描器不自动发现 Win32 handle 改名/删除调用，这些需针对本模块进行源码审查与真实 Windows 验证，不能声称静态审计覆盖全部写操作。
