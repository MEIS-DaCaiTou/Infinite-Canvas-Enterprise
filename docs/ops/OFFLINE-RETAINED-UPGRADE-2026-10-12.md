# C6：离线升级、跨版本保留数据重装与原生维护工具更新

> 2026-10-13 合并状态补充：#154 已合并为 `11c9a38c`，#155 已合并为 `3e0deeae`，负责人明确授权后按准确 Head 核查并合并；没有新增独立审查结论。本文原有源码、构建、GUI 与失败证据仍按原采集范围解释，Release 仍为 v2026.10.1；后续状态见 [CURRENT](../CURRENT_PROJECT_STATUS.md)。

记录日期：2026-10-12。开发基线 `main@bc33339fd11df4c0303f29257766f0f2e53560fe`，完整副本/GUI 演练代码 `9dcbf4ed9f64a0d1cdf4bc5c15c70585e3faa031`；后续 CI 指针发布边界收口见下文，不混写为已经重新构建的候选。本包的标准卸载确认和限定跨版本保留数据重装 GUI 已在开发机合成安装副本补验收，独立审查尚未完成。正式 Release 仍为 v2026.10.1，没有客户或生产操作。

## 实现与恢复边界

新版 Setup v7 从已安装位置，或 C3 可证明的保留数据卸载位置升级到较新版本。来源完整程序、当前指针、原安装 UUID、数据/配置目录身份、数据库 schema/ledger 和 native entry 必须匹配；仅接受已知 v1/v2 的相同 Schema，不初始化客户数据库、不重置账号，不接受无身份历史布局、未知锁、跨 Schema 或降级。

`enterprise.install_upgrade` 委托现有 `UpdateMvpService.prepare_from_artifacts` / `execute_update_job`，不复制业务或迁移实现。恢复保留来源时不释放启动 fence；以同一已证明文件对象转交准确 Job。不可变计划和 Job receipt 绑定原文件身份、来源/目标 Manifest 与共享引擎计划；状态文件不是文件删除或作业接管授权。

固定 EXE、安装记录、保留的 maintenance Setup 和 support.ini 分别记录发布检查点。来源对象经 Windows handle 校验后同卷移入本事务恢复目录，未知/同内容不同身份对象拒绝替换；旧恢复副本不自动删除。新的原生 `--tool-info` 输出 contract 2，常规服务启停仍使用原 Python Runtime。

维护 Setup 来自经过 SID/PID/创建时间核验的管道客户。Inno 内部 `.tmp` 客户通过其仍存活的直接 `.exe` 包装父进程取得完整 Setup；请求不接受任意可执行文件路径。原文件身份和哈希在读取/准备后重新核验。

目标启动失败时，共享引擎先确认目标停止，恢复来源指针；安装层先恢复原生工具对象，再启动来源服务。显式中断恢复依赖准确计划、Job receipt、文件身份和 kernel lease；不靠锁龄、PID 消失或 phase 推断成功，不恢复旧数据库覆盖业务写入。引擎已经 SUCCEEDED 时只继续登记，不能回退已成功的新版本。

成功激活先进入 AWAITING_REGISTRATION。目标版本的 HTTP/WS 业务请求分别返回 503/1013，健康探测保留；这只覆盖离线维护目标的登记窗口，不等于已有任务排空或完整业务维护态。只有验证当前用户的实例定位、准确路径、目标版本/发布者、实际卸载器及其哈希后才 COMPLETE 并释放标记。Windows Registry/文件 handle/Setup 逻辑留在平台适配层；服务端请求暂停中间件可跨平台使用。本包不声明 Linux/云端部署已完成。

## 当前测试证据

- C6a/unit-h.xml：29 passed，真实 SQLite/文件校验与 Windows 文件身份操作，Runtime 进程调用用小型替身；包含原生字段发布中断、Job 绑定前后中断、来源保留恢复、目标失败恢复、外来同内容文件/fence 拒绝、旁路文件阻断及成功后不回退。
- C6a/registration-a.xml：14 passed（登记适配器 7、HTTP/WS 暂停 7）；登记拒绝旧版本、错误路径/命令/类型/定位和卸载器字节变更。登记单测替代 WinReg 查询，不是 GUI 验收。
- C6a/regression-a.xml：182 passed / 1 skipped；C6a/audit-a.xml：30 passed。复用 C2/C3/C4 未变更的既有充分证据，没有重跑其全套验收。
- 来源复用 C3d 冻结合成包：`ice-2026.08.5-9d6fd9de4726`，Manifest `618a87a4cb3822b0801840469c298ee455d3ef21155b1f6413e280a950edc490`。
- 实际通过跨版本 GUI 的测试候选 C6c：`b82f41828ca8ebb3d9b6119394099fb981c1962b`，tree `ab88f4345c21d6d814fe3fad4941de749076a015`，源代码为上述 `f48b0808`；只在独立 artifact clone 修改测试 VERSION 为 2026.08.6，没有修改主线发行版本。Manifest `4998b4dd8e76885d40ccfb022aaed8c3dae80c582d9f123244afca694fe82df3`；native SHA `61e25c4f8f11dfa678371162dd9eae7d9f14c5770f8ca8b9e1f3e8b85d41b6a8` / 22528 bytes；Setup SHA `e28c3ccc9cb193190c9038129e26265e10f8fb63e8250a1e55676dd3a9324a5b` / 33180714 bytes。两者分别双构建一致，未签名、未发布、未获生产批准。
- C6b/bridge-fix.xml：35 passed。首次 C6b GUI 升级被 `INSTALL_TARGET_NOT_GREENFIELD` 安全阻断；已有目录校验未包含 v7 四项操作，已补齐并回归。修复前原来源、业务文件和安装身份未被替换，失败证据保留；原 C6b 候选不能作为成功升级证据。

## 实际 GUI 与完整安装副本

源安装 UUID `56edb359ecd94105bfe65fa9de457b6c`；测试根为产品 artifact 下的 `C6b/gui-install`，只包含本轮创建的账号、画布、素材和配置。原有当前用户两处 KnownFolder 目录先按完整树哈希、mtime 和目录身份保全；没有使用客户安装或生产数据。

1. 通过来源 C3d Setup 完成实例卸载登记，启动该实例的实际 Windows 标准卸载器。标准卸载确认和“无活动任务／保留业务数据”确认均实际点击 Yes；`C6b/gui-evidence/uninstall-click.log` 两处记录 `User chose Yes`，实际成功窗口已确认。后端核验 UNINSTALLED、原程序/固定入口在准确恢复位置；受保护文件 SHA、数据/配置目录和 UUID 保持。此证据补齐此前按钮点击限制，不能替换或改写 C3 记录中的历史静默验收。
2. C6c Setup 明确选择原目录和“跨版本保留数据重装”，确认服务已停且无任务；没有经过创建账号页。实际执行来源恢复、共享单跳更新、原生工具发布和目标 Runtime 启动。Windows 出现 Python 防火墙权限窗口，由负责人手动点击允许；代理未操作系统权限。此开发机权限状态不是公网或生产网络验收。
3. 点击安装器“完成”前，共享 Job SUCCEEDED、安装事务 AWAITING_REGISTRATION；真实健康 HTTP 200，业务 HTTP 503。完成按钮实际点击后，登记收口运行完毕，事务 COMPLETE、安装暂停标记释放；实际 HKCU 定位和卸载记录、目标 DisplayVersion、发布者、卸载器哈希均通过适配器核验。
4. 新固定入口 `--tool-info` 返回 contract 2 和实际目标 Release，保留 maintenance Setup 的 SHA 与实际 C6c Setup 一致。原账号可登录，管理员页面 HTTP 200；匿名业务请求返回正常认证 401。SQLite 完整性、schema/ledger、原用户及画布映射保持，画布/素材/配置 SHA 与升级前一致。实际固定入口停止后两个端口均关闭，离线数据库契约再次通过。

对应原始证据为 `C6b/gui-evidence` 的截图、`uninstall-verified.json`、`upgrade-pending-verified.json`、`upgrade-complete-verified.json` 和 `upgrade-stopped-verified.json`。没有以 Python 函数调用或静默卸载代替上述真实 GUI 点击；这些证据只覆盖本机准确来源与相同 Schema 目标，不代表全部维护 GUI 分支或任意历史跨版本安装已完成。

后续已安装位置的完整副本演练 `C6c/real-a` 发现 WAL 模式来源的剩余缺口：共享引擎的普通 `mode=ro` 读取会产生空 WAL/SHM，安装层因既有旁路文件检查而进入 RECOVERY_REQUIRED；来源/目标进程均停止，数据及失败记录保留。修正为共享引擎接受显式数据库检查器；C6 检查器先核验准确数据库文件身份、安装事务及服务静止，再复用已有 immutable 只读元数据核验。未知 WAL/SHM/journal 仍阻断，没有删除、恢复或忽略旁路文件；普通在线更新保留原默认读法。`C6c/wal-regression-a.xml` 的 130 项升级/共享引擎/生命周期回归通过，其中新增四项实际 WAL-mode SQLite 成功和回退组合。写点审计仍为 477 处，仅原只读检查函数改名，SQL 调用指纹未变；完整安装副本须按修正后的冻结候选再次验证，不能用此前 GUI 成功掩盖此失败。

修正后的 C6d 完整副本已实际通过已安装来源升级、原生工具发布、真实 HTTP 暂停和成功后不回退；`C6d/real-a/in-place` 的 AWAITING_REGISTRATION 结果与最终停止记录保留。但中断案例在到达故障注入前，准备目录因重复拼接目标 Release 和完整 Job ID 而触发 WinError 206；准确错误由同一冻结 CP314 工具在该合成副本复现，见 `C6d/real-a/interrupted/prepare-diagnostic.json`。来源已停止、KnownFolder 目录恢复核验通过，失败不计为中断恢复成功。准备目录改为同卷隐藏 `.{完整 Job ID}.partial`；目标身份仍由准确 Manifest 和 Job 绑定，目录删除仍需准确文件对象身份，不按名字接管旧目录。演练入口同时在断言前保存返回码及原始 stdout/stderr，避免故障原因因预期进程退出断言而丢失。

2026-10-12 首次 GUI 查看被用户物理 Esc 中止，后台演练安全停止；历史目录未进入该轮移动，目录身份与上次已验证恢复一致。用户随后要求继续。中止、准备脚本失败、首次 GUI 安全阻断和最终有效验收分别保留，不将先前失败改写为通过。

## 最终完整副本与后续边界

最终候选 C6e：`ice-2026.08.7-25600ecda60f`，commit `25600ecda60f6fee38abcc4c6ffa45f486019958`，tree `d905ed6a1c4367d400f93fd65de12ceeab8276d0`，源代码为上述 `9dcbf4ed`；只在独立构建 clone 修改测试 VERSION 为 2026.08.7。Manifest `24236522dbe3645a6dc16b10514d65555abee897b996dd12e5678c564edb2829`；固定入口仍为上述 contract 2 字节、构建记录绑定准确新 commit/tree，Setup SHA `3101bb705ae8a939da10c649677732979b57a7553cf923d4fa702a0cf1a9ad7b` / 33180768 bytes。两项双构建一致，未签名、未发布、未获生产批准。

`C6e/real-a/summary.json` 三项完整副本场景全部通过：

- interrupted：来源真实 EXE 启动/健康/停止后，在原生入口发布处实际 `os._exit(93)`；第二个冻结 CP314 进程显式恢复为 ROLLED_BACK，原固定入口文件对象和业务文件/安装 UUID 保持，两个端口关闭。
- rollback：目标真实启动后只停止该测试目标，让实际健康探测失败；共享引擎确认目标停止后自动恢复来源程序指针、原生工具并成功启动/核验来源，最终 ROLLED_BACK，原文件对象/业务文件/UUID 保持，端口清理确认。
- retained：来源真实启动/健康/停止、C3 保留数据卸载后，恢复准确原程序和入口，再升级到最终目标；AWAITING_REGISTRATION、新入口 contract 2、目标健康 200/业务暂停 503、维护 Setup 哈希匹配、成功目标恢复检查不回退均通过；业务文件/UUID 保持，端口清理确认。

已安装来源的相同 WAL 修正与真实成功证据复用 `C6d/real-a/in-place`；准备目录短名称通过上述 C6e 案例覆盖，不重复未受影响的 C2/C3/C4 全套门禁。运行上下文实际处于 Windows Job，C6e 报告 flags 12288；没有用被替换的 Runtime 结果或在线 handoff 前置资格冒充这些真实生命周期。普通在线 handoff 的 C5 仍见 #154，不依赖其尚未合并代码。

最终 C6e 安装器已对实际运行过的 C6c 来源完成 GUI 已安装升级。实际选择、无任务确认、安装和完成按钮点击均留有截图；准确 Job `489e157be56b4ee78511ac9cbbd86b4e` SUCCEEDED，安装事务 `d22f4cd35a474db9abfd4783ae95fa3f` COMPLETE。点击完成前健康 200/业务 503，登记收口后原账号登录和管理员页面 200，匿名业务恢复正常认证 401；HKCU 两项登记、目标版本/发布者及实际卸载器哈希核验通过。安装 UUID、原用户/画布映射、画布/素材/配置 SHA 和数据库 schema/ledger 保持。原始结果为 `C6b/gui-evidence/upgrade-e-pending-verified.json`、`upgrade-e-complete-verified.json`，停止后的端口关闭和离线数据库契约为 `upgrade-e-stopped-verified.json`。因此最终候选也有实际已安装 GUI/WAL 来源证据，没有以较早候选替代最终完成状态。

测试实例随后使用其实际标准卸载器静默清理本轮创建的 Windows 定位/卸载登记和快捷方式，返回 0；仅该测试 UUID 登记被移除，业务数据和恢复副本继续保留，两个端口关闭。此步只是测试清理，`final-test-registration-cleanup.json/log` 明确不替代先前的真实 GUI 验收。后台保全驱动在清理后恢复原有 KnownFolder 目录并复核完整树/mtime/目录身份；最终恢复与集中证据封存结果在下文记录。

本包以 Draft PR 供独立审查，未合并、未发行。以上两次分别确认的单跳演练不等于一次授权自动多跳。

最终原有两处 KnownFolder 目录均按完整树字节/mtime 和原目录身份恢复核验，`ICE-UpdateDrill-Saved-c6-gui-20261012-a/RESTORED.json` 与 `C6b/GUI-SESSION-RESTORED.json` 已落盘，保全驱动退出 0。各嵌套完整副本演练的恢复证明也保留，没有覆盖历史目录。其他工作区及既有未提交修改保留，本地 main 安全同步至上述 GitHub 基点。

集中证据封存于产品 artifact 的 `t/C6e/C6-review-evidence-9dcbf4ed9f64.zip`：118 项原始证据、528141 bytes，SHA256 `5ba4dc182f3740600838e07e2cda4789c727e47e44eb4f7d5201fda1f2e3781f`；`review-evidence-index.json` 为逐文件 SHA/大小索引。包含有效 JUnit、精确构建记录、GUI 截图/验证、真实生命周期阶段、三项早期失败和目录恢复证明；不含客户数据库、配置密钥、业务材料或历史目录详细清单。后续文档提交不改变已冻结运行代码；CI/独立审查/合并结果以本包 PR 的准确 Head 记录为准，不把本机验收当作已合并或生产批准。

Draft [#155](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/155) 的初始 Head `6dfba1ff716cb61f8e33db380b0befb5ac04773a`，Runtime/原生构建/文档 CI 成功，企业套件为 1627 passed / 50 skipped / 1 failed。失败是原指针写入边界门禁：C6 显式恢复直接调用底层 writer。收口将原样的来源指针 CAS 发布移入共享 MVP `restore_source_pointer`，C6 继续先核验目标停止、数据库/来源、指针和对象身份，再调用共享边界；恢复算法、CAS 参数及业务数据行为保持。门禁继续禁止其他 Runtime writer，并改为精确 AST 调用点 `{execute_update_job: 3, restore_source_pointer: 1}`，没有放宽为任意安装器直接写指针。

`C6e/ci-pointer-a.xml` 的 151 项安装升级/共享引擎/真实指针写入契约定向回归通过，477 处写点审计摘要未变。此提交只收口发布边界及其门禁/文档；复用前述真实进程、GUI 和原目录恢复证据，没有重复全套本机演练，也不宣称该收口提交经过新的完整候选构建。封存 ZIP 不覆盖；CI 修复附加证据与最终准确 Head CI 在 PR 单独记录。

自动多跳、在线原生 EXE/Setup 更新、完整业务维护态、未知未来 Schema 迁移、长期恢复副本/资产保留政策及旧 v1/未知锁接管仍是路线图中的独立工程能力。本包的离线原生工具更新不等于这些范围已完成；专业服务器/云部署和 500+/200+ 约束继续适用。

身份无法证明、目标停止无法确认或 fence 写入中遭遇未覆盖的电源/文件系统故障时仍安全阻断；检查点进程退出演练不能扩写为任意电源故障自动恢复。完整维护 GUI 矩阵、客户历史版本和生产服务验收分别保留边界。


## 2026-10-19 页面升级来源的登记预检与维护提示候选

基线 main `e0dfa843d4bec3ff9c05a6f2ee25337a3687fc3e`，独立分支 `codex/install-upgrade-preflight-20261019`，运行代码 `a8ec5268fc3eda4bc0a7ab247f62c89815ba217a`。正式 v2026.10.3 已发布；本节是后续维护候选，不替换该正式资产、不承诺任意历史来源可升级，也没有客户操作。

负责人反馈正式 10.2 经页面升级、installation.json 缺失而旧 native-entry.json 存在，离线升级返回 IDENTITY_REQUIRED。旧来源升级不会凭空创建安装身份。原入口修复已有兼容路径，但必须核验完整来源/旧 EXE 归属并停机；未知 EXE 不认领。客户提供日志在北京时间 13:55:26 仍有业务/网关 HTTP 200，且当天没有停止完成，解释了首次 RUNTIME_BUSY；该副本日志不证明客户后来机器的实时状态。原生诊断 ZIP 只含上次操作摘要，不能独立证明停机。负责人随后确认停机后固定 EXE 窗口仍打开，出现通用 REPAIR_FAILED；本地真实 Windows 句柄拒绝替换可复现该码及 PermissionError/WinError 5，但客户错误仍须关闭窗口后的结果确认，不把本地条件复现当现场唯一原因。

增量只做：Setup v2 新增无凭据 inspect-entry，共用原归属检查且不写登记；刷新按入口/程序/生命周期/离线升级操作选择检查，不再固定跑同版程序检查；离线升级在进入确认页前预检；缺登记、Runtime 占用与写入被拒绝给出明确下一步。PermissionError 在原事务回退及清理成功后返回 INSTALL_ENTRY_WRITE_DENIED；恢复不明确继续 RECOVERY_REQUIRED。没有自动停机、删除锁、绕过身份、重建账号/Schema、安装策略或升级引擎变更。

验证证据保存在受管 artifact 的 install-103-identity-fix-20261019 和 t/I19B：

- 相关五模块首次 179 passed / 1 failed；失败是新增回退测试错误要求指针时间字节不变。修正为核验原 Release/Manifest/根及回退目标身份后，两个新来源场景定向 2 passed；后续桥接/GUI 静态契约/新来源定向 3 passed。没有将首次失败改写为首次全绿，也未因文案重复全量回归。
- Windows 真实文件句柄阻止替换测试 1 passed：写入失败保留原入口/登记/业务，关闭句柄后同一入口修复成功。Runtime 在该单元夹具中替代，不是实际运行 EXE 窗口点击证据。
- 写点审计继续通过，原登记摘要未变化。固定 CPython 3.14.6、编译器和依赖不升级；准确代码 a8ec526 的 ZIP/Manifest、固定 EXE、Setup 和维护资产构建成功，EXE/Setup 各自双构建一致。
- 冻结目标 CP314 工具对正式 ice-2026.10.2-7da593b52f3d 新建的合成副本验证，使用中文安装路径：缺登记→REGISTRATION_REQUIRED/IDENTITY_REQUIRED；本轮自建模拟 Runtime 锁仍阻断为 RUNTIME_BUSY；清除该自建测试标记后原入口事务 SUCCEEDED、REGISTERED、离线资格 ELIGIBLE，原业务/配置/指针字节保持。没有修改真实 Runtime 目录或客户文件。
- 既有单跳引擎的成功及目标失败恢复仅由新来源定向测试覆盖；本候选未执行真实 GUI 离线升级/Windows 登记矩阵，也未完成客户停机关闭窗口后的实测。上述冻结包只证明登记修复和离线资格，不等于完整客户升级验收。

独立技术 Review 对当前运行 Diff 及新增写入错误映射的定向复审均为 NO_ACTIONABLE_BUGS_FOUND；该结论不是 GitHub Approval 或无缺陷保证。准确 PR Head CI 单独见原 PR。候选可关闭/弃用；合并后如需回退源码，使用正常 revert PR。补丁版本、正式发布和客户升级另行批准，不覆盖 v2026.10.3。


## 2026-10-20 空 WAL/SHM 受控预处理候选

负责人提供完整测试安装快照后，确认入口登记已补齐，当前仍为正式 `ice-2026.10.2-7da593b52f3d`；WAL=0、SHM=32768、无 journal。停机完成日志与隔离快照的 quick_check/Schema READY-v2 证明限定状态，不替代执行时进程/端口/Runtime 锁检查，也不承诺所有业务内容正确。客户原 ZIP、数据库、配置及素材不入 Git/PR；原库未处理。

负责人已明确批准新增写连接的候选开发，终点仍是独立 Review/Draft PR，不合并、不发布、不操作测试主机原库。候选 `codex/install-database-preparation-20261020` 以 #178 Head `26299e11d35e2dc813d44cb425ed15b33f8dec1b` 为 Base，保留该 PR 与历史工作区；不是替换已发布 10.3 资产。

- `install_database_preparation` 只接受 WAL 模式、空 WAL 与 32768 字节 SHM 同时存在的受证文件对象；非空 WAL、journal、不完整/陌生旁路文件及非 READY 元数据拒绝。资格检查只读，返回 `database_preparation_required`，不删除日志或调用 checkpoint。
- 写阶段复用原 `install_upgrade` 的不可变计划、runner lease、active receipt 和 system-update fence；绑定原来源、安装登记、主库对象/字节及 Schema/ledger。停机及身份再核验后才记录 PREPARING_DATABASE、调用既有版本化 SQLite checkpoint helper，不新增恢复引擎或数据库表。
- helper 的可选 guard 只在本路径启用，迁移/备份默认行为不变。先禁止失败关闭时隐式 checkpoint，再取得 SQLite exclusive mutex，锁内复验 WAL 仍为空、主库字节与旁路对象仍匹配，之后才允许 TRUNCATE。仅成功且主库字节不变时恢复正常 SQLite close 清理。SHM 是 SQLite 自管锁/索引，其内容可变化但文件身份与长度必须匹配；不得手工 unlink。
- 进程中断保留原事务 fence/计划；现有 inspect-upgrade 只报告 RECOVERY_REQUIRED，只有用户显式 recover-upgrade 才在准确计划/租约下重验并清理受证空日志、回到原版本。未知非空日志及字节变化继续阻断，不自动重试、重建数据或回旧快照。无该字段的旧 v1 计划仍可读取。
- 固定 CP314 Runtime 的 SQLite setconfig/NO_CKPT_ON_CLOSE 是必要能力；旧 Python 工具缺失时在发布维护记录前拒绝。保留数据卸载/同版重装等其他生命周期操作的原旁路文件拒绝语义不放宽。

定向验证：冻结 CPython 3.14.6/SQLite 3.50.4 下新模块 15 passed / 1 skipped（旧工具专属分支）；含真实第二连接写入互斥、检查后提交非空 WAL 保持原主库/WAL，以及持 SQLite 锁时子进程实际 os._exit(93) 后显式恢复。Python3.11 的同模块 2 passed / 14 capability skips；默认迁移 backup/restore 9 passed。原生命周期/桥接/Setup 静态契约 84 passed。原离线升级 35 个无残留场景的有效证据沿用本轮初次短路径运行；没有为文案或 Review 重跑无关全套。

首次长 artifact 测试目录触及 Windows 路径限制，产生 21 项路径失败，另 1 项是新增占用用例在 Windows 锁字节读取处未映射的错误；缩短目录并修正后，后续新增测试又发现 hook 错误复用已关闭 writer，修正该测试。独立 Review 随后用真实提交复现 1 项 P1：最后检查与 checkpoint 间新出现非空 WAL，事后检查过晚。已按上述互斥/失败 close 保护修复，具体并发回归通过，定向复审 NO_ACTIONABLE_BUGS_FOUND；不是 GitHub Approval 或无缺陷保证。未把早期失败改写为首次全绿。

证据位于产品专用 artifact 的 install-database-preparation-20261020；客户数据只在仓库外隔离副本。新增 CI 只在现有 Runtime3.14 作业加入该小模块，本地约13秒，不加作业、依赖或新门禁。准确 Head CI 与候选构建结果在 PR 记录；GUI、Windows 登记及现场 10.2→目标完整升级仍 NOT_VERIFIED。合并/补丁发布/现场执行需分别批准。

## 2026-10-20 组合候选的完整冻结副本验收

独立组合分支汇集 #177、#178→#181、#179→#180；Base main `e0dfa843d4bec3ff9c05a6f2ee25337a3687fc3e`。完整构建与原生演练源码准确为 `b0fcb067aaf6deff3ff372a7a10ba911d6947780`，内部目标 `ice-2026.10.3-b0fcb067aaf6`；后续只补文档和演练Setup路径提前检查，最终PR Head/CI另记。此10.3候选未替换公开10.3资产，不是新正式Release。

固定CPython3.14.6/依赖和原编译工具链构建ZIP/Manifest、固定EXE、Setup及维护资产成功。复用原C6完整副本演练，新增显式 `--empty-wal-residue --scenarios in-place interrupted rollback`：正式 `ice-2026.10.2-7da593b52f3d` 源资产新建合成账号/画布/素材，实际固定EXE启动、健康和停机后生成限定空WAL/SHM，冻结目标Python执行原升级事务。无客户ZIP/原库执行、无付费调用。

| 场景 | 实际结果 | 证据边界 |
| --- | --- | --- |
| 正常升级 | AWAITING_REGISTRATION；新目标真实健康200、业务入口503；显式recover不把成功目标降回旧版 | 受控准备阶段主库字节保持，业务文件/安装身份保持；不含Windows登记 |
| SQLite锁内中断 | 进程在database_locked实际退出93；显式recover处理受证空日志后ROLLED_BACK | 原native对象恢复、主库字节和业务文件保持；不是任意电源故障覆盖 |
| 目标健康失败 | 目标start成功后在真实health前受控停止；health返回PORTABLE_STARTUP_NOT_READY，原引擎停止目标并重启正式10.2，source_health成功，ROLLED_BACK | Runtime phases/events记录完整，不以任意提前回滚冒充注入到达；原native对象和安装身份保持 |

三个场景的测试端口关闭，既有本机两处KnownFolder原树字节/mtime及目录身份完整恢复。开发宿主第一次保全移开原树后出现历史空占位目录而安全拒绝，未创建安装fixture；空占位单独保留后原树恢复。第二次传入不存在的Setup文件名，事务发布前返回INSTALL_CACHE_UNPROVEN；只读资格仍ELIGIBLE，修正为实际构建文件并在演练前增加文件存在检查。失败和恢复记录保留，不算首次全绿。普通桌面上下文最终三场景退出0；没有修改应用Job/Runtime保护。

同一源码业务组合定向127项通过；新增三进程排队MiniMax-H3验证一次选定POST、GET原ID、终态重开无供应商请求。测试自身最初误读结果响应层级，定向修正后1项通过，原五项四类任务恢复场景通过。写点审计7项通过，513处完整登记、无失效映射，增删正好为已审候选并集；文档检查及17项契约通过。其余仍有效的单包CP314、Browser及真实Provider证据只按原范围复用，不重复全量本机测试。

组合运行交界及新增演练/测试独立Review为NO_ACTIONABLE_BUGS_FOUND。仓库外演练驱动一处普通文件可能被空目录快照误接纳的P2，已增加目录类型/对象身份复验，定向拒绝及复审通过；不是应用源码缺陷，也不是GitHub Approval。证据仍放产品既有artifact的candidate-integration-20261020与t/C20，不新增治理文档；35个其他工作区原状态保持。

当前新条件的Setup GUI、Windows登记、在线更新及现场完整升级仍NOT_VERIFIED，不以本节覆盖；常规CI跳过固定EXE opt-in也不算通过。候选准确Head CI/合并状态见新PR，main及正式10.3不变。新增演练是手动opt-in，未增加常规PR作业/依赖/门禁。下一完整包在获准合并后固定补丁版本/源码，补Setup登记、更新中心来源副本和现场复测边界；发行及客户操作分别批准。未知恢复继续原fence与显式recover，不删除日志或强行重装。


## 2026-10-20 安装向导简化候选

#182 已按负责人批准合入 main `5582c9f3094e052bee889835cae1aca065210992`，准确 main 的 Enterprise/Runtime39351798091、Docs39351798247、Native39351798243 最终 SUCCESS。正式 v2026.10.3 的资产与客户设备保持原状。负责人随后批准精简向导，独立候选 `codex/installer-simple-flow-20261020` 保留原后端事务，只变更 Inno 页面、选择接线及相关契约检查。

首次安装为位置→管理员→最终确认；已有安装为位置→三个常用入口→最终确认。去掉单独的位置模式、环境说明、停机确认和附加任务页面；停机确认及桌面/启动选项集中在最终页。高级维护只有主动选择才出现，原十三个操作和显式恢复仍可访问；列表不再与刷新按钮重叠。多个安装时位置留空要求明确选择；每次请求发送用户核对的准确目录。未知非空目录不会按新装重建。

建议复用现有只读 inspect-entry：同 Release 建议程序修复，已登记旧版建议升级，缺少登记建议先修复启动；身份/状态未能核验则引导高级检查。建议不创建安装ID，不提交修复/升级；进入常用升级仍复用原 inspect-upgrade，真正执行时再次核验身份、锁、进程、数据库和恢复条件。页面返回后停机确认重置，PrepareToInstall 也强制检查。未新增 Schema、依赖、CI 作业、自动终止进程或自动恢复。

准确功能/构建源码 `2859a2aefbac5d30829eb7f7aa73c82ee1eb2583`，内部 VERSION=2026.10.4，目标 `ice-2026.10.4-2859a2aefbac`。固定CP314、原编译器/Inno与维护资产构建器生成同源ZIP、Manifest、固定EXE、Setup和维护资产；双构建一致。先前8ab5b90内部候选不包含简化界面，不用于正式交付。后续仅文档提交与构建身份分开；目前未创建tag、Release或公开更新目录。

定向单元94 passed/14 Windows opt-in skipped；第一次运行旧页面断言有3项失败，按新页面入口与最终保护点更新后通过。首次预览编译发现 TNewCheckBox 没有 WordWrap 属性，删除该不可用属性并缩短文案后编译成功。预览只用于编译检查，不冒充准确源码交付资产。独立 Review 对本次接线未发现可证实程序缺陷，NO_ACTIONABLE_BUGS_FOUND，不是GitHub Approval或无缺陷保证。

开发机真实窗口已核验位置→管理员及返回、缺登记只读建议且原指针/缺失登记未变化、正常旧版默认升级、主动进入/返回高级维护，以及最终页不确认停机即阻止执行。普通路径不显示十三项高级操作。截图与原始证据在产品artifact `t/S20`，没有客户素材或凭据。

首轮整体验收在确认页交互期间，仓库外隔离会话等待上限到期并按原保护清理准备目录、恢复本机原树，随后点击安装正确被 INSTALL_BOOTSTRAP_INVALID 阻断；原10.2指针未变、未创建升级事务。该失败保留，不记为升级通过。后续同一冻结包的独立会话执行结果在原PR分别记录，未重建或改写原恢复规则；不把作业SUCCEEDED冒充最终GUI/登记验收。测试只使用正式10.2/10.3资产创建的开发机合成安装、账号、画布和素材；不运行客户ZIP原库、不进行付费生成。

下一完整包先收口简化候选的准确Head CI、升级/登记及在线恢复证据、路由与可复测资产，再按负责人批准合并/正式发布。现场完整升级、全部GUI维护组合、真实JSON编辑与代码签名仍分别按事实记录，不以常规CI全绿替代。未增加默认遥测或第二治理台账。
