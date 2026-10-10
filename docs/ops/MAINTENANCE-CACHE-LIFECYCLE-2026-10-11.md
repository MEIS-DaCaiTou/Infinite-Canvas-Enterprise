# 工作包 C2：维护准备包的显式安全清理

日期：2026-10-11。实施顺序沿用 [正式路线图](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md) 阶段 3；不是新路线图，也不改变 [范围锁](../../PROJECT_SCOPE_LOCK.md) 或业务实施授权。

## 基线与完整成果

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

阶段性记录：源码/测试/图形接线已编写；完整 payload、bundled Python、实际当前用户管道、实际进程退出与清理中进程死亡演练正在准备。未将 GUI 源码、安装器编译或普通 CI 视为完成图形点击验收；后续在本记录补充准确提交、产物与结果。

| 层次 | 当前证据 | 限制 |
| --- | --- | --- |
| 定向关联回归 | 初轮 137 PASS / 1 SKIP，59.24 秒；实际解包闭包修复后，CPython 3.11 清理与 bridge 合计 62 项 PASS（33.44 秒），bundled CPython 3.14 清理 35 项 PASS（18.97 秒）；追加字节再核验用例单列 | 小型封闭 fixture；多数退出观测替换，不算完整 GUI 或完整生产负载；计数有重合，不相加 |
| 实际完整准备包与 CPython | 尚待执行本工作包的准确源码构建 | 环境变量缺失的 SKIP 不算 PASS |
| 完整图形操作 | NOT_RUN | 不把 v5 管道、源码断言或编译通过当作真实点击验收 |
| PR / 合并 / Release / 现场 | 本工作包尚未提交 PR；不批准自动合并、发行或客户操作 | #150 的合并不是 C2 的合并 |

可重复定向检查：`python -B -m pytest -q enterprise/tests/test_install_cache.py enterprise/tests/test_install_ux_1.py enterprise/tests/test_install_entry.py enterprise/tests/test_install_program_repair.py enterprise/tests/test_install_repair_status.py`。测试根应是本轮全新、明确属于测试的短路径；pytest 的旧 `--basetemp` 不可复用，因为框架会先清空它。

真实准备包演练：设置 `ICE_CACHE_RELEASE_ASSETS` 为准确干净源码构建的三资产目录，`ICE_NATIVE_ENTRY` 为同源编译入口，运行 `enterprise/tests/test_install_cache_windows.py`。四个 opt-in 场景不得仅以 CI 跳过替代：后台退出而 Setup 客户端仍活跃的保留、实际 v5 清理、隔离后进程死亡、删除首个成员后进程死亡；核对整个合成安装的文件 SHA 保持一致。

CI 自动执行小型 CPython 3.11/3.14 清理合同及既有静态/入口编译检查；完整准备包和真实 GUI 门禁另列。APP_ROOT 写审计 W47 新增只限本模块的明确写符号；扫描器不自动发现 Win32 handle 改名/删除调用，这些需针对本模块进行源码审查与真实 Windows 验证，不能声称静态审计覆盖全部写操作。
