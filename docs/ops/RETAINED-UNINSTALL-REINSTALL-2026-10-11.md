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

小型 owned fixture 已覆盖实际 Windows 文件 handle/对象移动与离线 SQLite：卸载/重装及原对象恢复、准备/隔离/恢复各阶段中断、旧 token/相同字节对象替换、未知文件/空目录/硬链接、配置/数据库对象变化、Schema/sidecar、并行 lease 与启动竞争。Unit Runtime 观测替换，MZ 入口是测试字节，不能称为完整 Setup 或原生入口验收。完整 payload、bundled Python、实际进程死亡和 GUI 证据将在构建后追加准确源码与产物身份；当前不宣称已通过这些门禁。

APP_ROOT AST 审计只自动覆盖可发现的计划/lease/link 与明确 readonly SQLite 调用；Win32 handle 改名及 fence 解除需要人工检查和实际 Windows 验证，不宣称扫描器自动覆盖所有文件操作。

## 授权和部署边界

本包仅在开发机新建合成安装/数据执行，不连接客户或生产设备，不调用付费 Provider，不修改公开 Release。专业服务器/容量补充同步进入现有权威文档；Windows 对象移动留在平台适配层，不宣称 Linux、容器、云部署或新业务已经实现。

实现、定向测试、完整副本、GUI、准确 Head CI、独立审查、main 合并、正式 Release 和客户验收分别记录。C2/C3 的合并按治理审批执行；本轮不自动合并或发行。
