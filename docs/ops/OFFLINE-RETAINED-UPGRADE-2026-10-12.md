# C6：离线升级、跨版本保留数据重装与原生维护工具更新

记录日期：2026-10-12。开发基线 `main@bc33339fd11df4c0303f29257766f0f2e53560fe`，代码候选 `f48b0808d93629fbe5bb5ee3c9d74efe3c3f37d1`；本包的标准卸载确认和跨版本保留数据重装 GUI 已在开发机合成安装副本补验收，独立审查尚未完成。正式 Release 仍为 v2026.10.1，没有客户或生产操作。

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

2026-10-12 首次 GUI 查看被用户物理 Esc 中止，后台演练安全停止；历史目录未进入该轮移动，目录身份与上次已验证恢复一致。用户随后要求继续。中止、准备脚本失败、首次 GUI 安全阻断和最终有效验收分别保留，不将先前失败改写为通过。

## 验收待收口与后续边界

GUI 完整链路已通过，当前继续已安装位置、进程中断和目标启动失败的完整副本恢复演练；结果与历史目录最终恢复记录收齐后集中提交 Draft PR，供独立审查。

自动多跳、在线原生 EXE/Setup 更新、完整业务维护态、未知未来 Schema 迁移、长期恢复副本/资产保留政策及旧 v1/未知锁接管仍是路线图中的独立工程能力。本包的离线原生工具更新不等于这些范围已完成；专业服务器/云部署和 500+/200+ 约束继续适用。
