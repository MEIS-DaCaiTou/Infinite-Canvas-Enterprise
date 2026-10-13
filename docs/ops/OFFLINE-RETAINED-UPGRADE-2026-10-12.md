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
