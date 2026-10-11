# 工作包 C3：保留数据卸载、同版本重装与中断恢复

日期：2026-10-11。沿用 [唯一路线图](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md) 阶段 3，承接 C2/#151；该 PR 尚待治理助手独立审查，不因本工作包开发而合并。正式 main 核验点为 `63394178b4c3d05c491c39d42c75518f000ed3cf`，正式 Release 仍为 v2026.10.1。本记录是工程证据，不是新交接包、路线图或发行批准。

## 实现契约

- 每个安装身份使用独立的当前用户 Windows 卸载登记和快捷方式；普通检查、缓存清理和未知安装不产生卸载登记。同源匹配的新装、入口维护和重装才提供该登记。
- Windows 标准卸载调用本安装校验过的独立维护 Setup；从外部准备副本执行共用 Python 事务，不依赖删除中的安装 Python。不接受账号或密码，不初始化既有数据库。
- 核验准确 Release/Manifest、完整已安装程序、固定入口、安装记录、指针、数据/配置对象、离线 SQLite metadata/quick_check、活动 Runtime 与更新/恢复依赖。SQLite WAL/SHM/journal 存在时阻断，不借 immutable 忽略未归并的事实。
- 程序与固定入口通过 Windows handle/FileIdInfo 移入本安装同卷的 `state/install-lifecycle/<operation>/` 恢复副本，不跨卷、不覆盖未知对象、不永久递归删除。数据库、账号、画布、素材、配置、备份及旧更新/恢复记录不移动或重建；已卸载状态仍保留准确版本指针及安装身份。
- 持久计划、外置 runner lease 与两链接 maintenance fence 共同授权执行。卸载后保持启动阻断；同一 Release 重装在重新验证原对象/字节、数据库结构、配置及 Runtime 后恢复原程序对象，最后解除属于该事务的 fence。不会用新版本包覆盖保留数据或夹带迁移。
- 窗口/进程退出不抹去事务。不按年龄或 PID 猜测锁过期；未知/旧锁保持阻断。再次明确选择完成卸载或同版本恢复安装，才能继续已证明的事务。恢复过程再次中断可按同一契约核验。
- 默认保留程序恢复副本和维护 Setup，因此卸载不承诺释放全部程序磁盘空间；没有自动 GC、保留天数或数据清除功能。旧安装、损坏/缺失恢复副本、未知身份/Schema 与跨版本重新安装保持拒绝。

Inno 的动态 AppId 在安装开始前绑定已验证实例；条件 Uninstallable 只为成功可证明的实例启用。依据：[AppId](https://jrsoftware.org/ishelp/topic_setup_appid.htm)、[Uninstallable](https://jrsoftware.org/ishelp/topic_setup_uninstallable.htm)、[卸载脚本](https://jrsoftware.org/ishelp/topic_scriptuninstall.htm) 和 [Abort 的可中止阶段](https://jrsoftware.org/ishelp/topic_isxfunc_abort.htm)。这里的文档契约不能代替实际 Setup 编译/操作证据。

## 本轮验证状态

小型 owned fixture 覆盖实际 Windows 文件 handle/对象移动与离线 SQLite：卸载/重装及原对象恢复、准备/隔离/恢复各阶段中断、相同字节对象替换、未知文件/空目录/硬链接、配置/数据库对象变化、Schema/sidecar、并行 lease 与启动竞争。Unit Runtime 观测替换，MZ 入口是测试字节，不能称为完整 Setup 或原生入口验收。

| 证据层级 | 准确来源与结果 | 限制 |
| --- | --- | --- |
| 关联源码回归 | `317479772365b9dd2973eccc12a032275b428d43`；211 passed / 1 skipped，102.27 秒；后续 Inno 修正对应编译/桥接检查 28 passed，4.05 秒 | 不等于生产、GUI 或完整 payload 验收 |
| 完整 Python/原生入口副本 | 上述源码，tree `f7bb10a1d62df9a131d77323ae6c6c85c679d282`；3 passed，496.81 秒；正常卸载/重装、卸载 runner 死亡后恢复、重装 runner 死亡后恢复 | checkpoint 仅终止本测试 runner；Runtime、文件、数据库和 verifier 未替换；不是操作系统断电演练 |
| 最终候选构建 | `9d6fd9de4726765cd0c0aebfcab0c140c2ccd9bd`，tree `2d46df31a32c81ba6854d73771fbc1bb5f82a66c`；完整 payload 2123 文件，固定 EXE 和 Setup 均两次一致构建 | 与完整副本演练源码相比只改 Inno 脚本；没有重建 Python Runtime；无签名/时间戳、未发行 |
| 标准 Windows 卸载 | 最终候选的新建实例 `d3e26965b9df4f6ab24d5e91ac013527`；真实登记卸载器静默明确确认后退出 0，`UNINSTALLED`，本实例卸载登记/locator/快捷方式移除；6 个保留文件 SHA 与完整原程序对象一致 | 只有本机合成安装；保留程序恢复副本，未测试客户主机 |
| 图形保留数据重装 | 同一实例、同一最终候选完整 Setup；明确选原根和重装、停机确认、管理员创建页跳过、执行摘要、安装成功；`INSTALLED`、原程序对象恢复、6 个保留文件 SHA 相同、fence 解除、Windows 登记恢复、真实固定 EXE identity 退出 0 | 没有付费任务、自动服务启动或生产/外部设备验收；卸载执行使用真实静默入口，按钮限制见下文 |
| 文档与写入审计 | 文档登记检查通过；17 项文档契约测试通过；APP_ROOT AST uncovered/stale/anchor 均为空 | AST 不自动验证全部 Win32 文件操作 |

准确最终候选 `ice-2026.08.5-9d6fd9de4726` 是未发行合成测试标识，沿用历史 VERSION，不能当作正式 10.1。Manifest SHA-256 为 `618a87a4cb3822b0801840469c298ee455d3ef21155b1f6413e280a950edc490`，ZIP 为 `3fcc24168d8e552accbe627d6aab383e3318bd28a1df28deff05dbbf59391236`，Setup 为 `91a3966324c8e2f472e6c462a2986e453f34488ecc2bf033bbe832a7abce1062`（33,165,601 bytes），固定 EXE 为 `570ad6885cae124e39f534bc6a95073212eec0ad4d9c1d8085f5e0888d3987fd`（22,528 bytes）。本机证据位于开发 artifacts 的 `t/C3a/full-tests.xml`、`t/C3d/build/`、`t/C3d/native/`、`t/C3d/setup/`、`t/C3d/windows-uninstall.log` 和 `t/C3d/handover-evidence.json`；不上传数据库或配置原文。

GUI 在最终候选验证了明确根路径、已有身份识别、管理员创建页跳过、同源入口维护、实际 Windows 登记，以及标准卸载的两次确认提示。Computer Use 在卸载确认按钮处返回 `foreground window did not report a process id`，动作结果未知；重新观察后窗口已关闭且登记/程序尚在，因此标准卸载执行证据改为同一真实卸载器的静默入口，不把该按钮点击写成成功。同版本图形重装已按上述证据完成；没有把静默卸载伪称为全 GUI 按钮验收。

真实 GUI 排障曾安全暴露并修正两项 Inno 接线：复制 Setup 自身必须在正式安装阶段执行，不能在 PrepareToInstall；标准卸载需保存已核验的 app 根，不能沿用 `CreateAppDir=no`。最终脚本执行前证明实例/支持源，在 `ssInstall` 发布支持文件，并由 Inno 登记该根。依据：[CopyFile](https://jrsoftware.org/ishelp/topic_isxfunc_copyfile.htm)、[CreateAppDir](https://jrsoftware.org/ishelp/topic_setup_createappdir.htm)。失败候选保留全部安装及诊断文件；只清理其经身份核验的测试登记/快捷方式，未用破坏性 reset/clean 或删除数据掩盖失败。

APP_ROOT AST 审计只自动覆盖可发现的计划/lease/link 与明确 readonly SQLite 调用；Win32 handle 改名及 fence 解除需要人工检查和实际 Windows 验证，不宣称扫描器自动覆盖所有文件操作。

## 授权和部署边界

本包仅在开发机新建合成安装/数据执行，不连接客户或生产设备，不调用付费 Provider，不修改公开 Release。专业服务器/容量补充同步进入现有权威文档；Windows 对象移动留在平台适配层，不宣称 Linux、容器、云部署或新业务已经实现。

实现、定向测试、完整副本、GUI、准确 Head CI、独立审查、main 合并、正式 Release 和客户验收分别记录。C2/C3 的合并按治理审批执行；本轮不自动合并或发行。
