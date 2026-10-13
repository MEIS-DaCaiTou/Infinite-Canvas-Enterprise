# C8：固定 Windows 启动方式与在线更新交接收口

2026-10-13。基于 `main@e89a288fe1ce8e5066ebebe1971e69bf5d4c7945`，继续[唯一路线图 3.3](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md#33-日常更新与长期跨版本)。本工作包是开发候选，不是正式发行；Latest 仍为 v2026.10.1。

## 使用契约：启动与更新分开

正式 Windows 启动方式是从开始菜单或安装目录打开固定 `InfiniteCanvas.exe`，点击“启动并打开”。这只校验并启动当前已安装版本，打开业务页面；不查询最新版本、不下载更新、不切换版本。没有更新需求时直接使用该按钮。关闭入口窗口不停止服务。

更新是管理员在现有更新中心单独选择目标、准备并确认执行的维护操作，普通用户不用每次启动执行更新。准备更新尚未执行时继续使用原版本；下载/准备失败不授权停服。已执行的维护不能靠关闭窗口取消，已有恢复依赖也不能通过删锁绕过。该区别是数据一致性的要求，不是强制用户升级。

无需更新也能启动，但当前安装文件损坏、端口被其他程序占用或已进入未完成恢复时，仍须处理对应故障；不能将这些故障包装成必须更新。此契约沿用既有 `LauncherProgram.Execute → launcher.py → execute_portable_command(start)`，没有新增启动更新分支、后台更新服务或定时器。

在线交接被宿主拒绝时先查看状态；原业务健康可继续使用。需要更新时按已有路径停止服务，再运行目标版本维护安装器。清理退出未确认时使用既有恢复核验，不能反复点更新或清理缓存。旧已发行源若缺少本次启动修正，可能先需一次既有停服离线维护；不可变 10.1 不因源码修正自动改变。

## 有范围的实现

Windows 创建参数此前在宿主无显式 breakaway 权限时仍请求 `CREATE_BREAKAWAY_FROM_JOB`，本机 Explorer 启动也可能继承外层 Job，因此不能将该失败简单归为 Codex 工具环境。

`handoff_lifecycle.host_creation_flags(context)` 根据已核实的 Job 信息一次选择：无 Job 或已知 Job 不允许显式 breakaway 时使用已有 detached/group 参数；已知允许 breakaway 或无法证明上下文时保留原 breakaway 参数。Launcher、Worker 和能力探针共用选择。没有在 WinError 5 后重试，没有关闭 Job，也没有去掉源 lease、READY、原对象句柄、源 Runtime Job 排除、拥有者清理和停机前资格证明。

普通创建仍受外层 Job 约束；不宣称可逃逸任意宿主、注销后常驻或任何工具环境可运行。Windows 继承及 breakaway 规则参考 [Microsoft Nested Jobs](https://learn.microsoft.com/en-us/windows/win32/procthread/nested-jobs)。现有平台适配层不新增业务代码的 Windows 前置。

界面只改现有入口说明和更新中心两类失败提示；无新页面、按钮、设置或额外操作。入口明确显示“点击‘启动并打开’即可使用当前已安装版本，不会自动更新。更新由管理员在管理后台更新中心单独确认”。

## 准确证据与限制

开发机证据根：`D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/t/windows-start-20261013/`。两个短路径安装副本为 `t/W8/s` 和 `t/W8/r`，只有合成账号、SQLite、画布和媒体。核心修正基点 `69048021bcd4a7e588f850e096bbe523ab83be48`；合成来源 `80a039db27fd6cc43c6dca2d0137d1a006ded8d1`（显示 2026.08.11）及目标 `5bf1f7ee5bd5`（显示 2026.08.12）不是对应历史发行包。后续 `955e319c27d4d60fac6dc3ea110206bf855a318b` 仅进一步明确入口文案，已重新完成干净原生双构建。

| 证据 | 结果与实际范围 |
| --- | --- |
| `qualification.json` | 真 Windows 无业务探针 qualified；宿主创建/清理、源 lease、Worker 排除源 Runtime Job、进程回收均确认 |
| 受影响自动检查 | handoff lifecycle/commit 82 项通过；runtime diagnostics/verified updater 初轮 111 通过、10 项仅旧创建参数断言失败，调整夹具后对应 10 项通过；静态 write audit 1 项、admin guidance Node 检查通过。没有重跑无关全量安装/卸载矩阵 |
| `evidence/gui-start-health.json`、`after-gui-close-health.json`、`native-start-complete.jpg` | Explorer 双击实际固定 EXE，点击“启动并打开”，GUI 显示完成；关闭该窗口后服务仍 ready，当前版本仍 2026.08.11。这也是不执行更新即可启动的实际证据 |
| `evidence/online-result.json` | 真实本机 HTTP 管理员授权 execute → SUCCEEDED，目标 2026.08.12；安装身份、业务记录及配置/画布/媒体保留。源角色停止、目标启动及 Worker 独立性交接有真实日志 |
| `rollback/result.json` | 拥有的故障监听者阻止目标端口启动，ROLLED_BACK / PORTABLE_RUNTIME_OWNERSHIP_UNTRUSTED；源 pointer 与 ready 恢复、业务/文件/安装身份保留，恢复 fence 清除 |
| `evidence/online-target-page.png`、`rollback-source-page.png` | 内置 Browser 实际登录及业务页面，分别显示目标 2026.08.12 和恢复源 2026.08.11；942×704。更新中心页面可访问，但本轮执行确认由真实 HTTP 完成，不称为完整更新 GUI 点击验收 |
| `native-optional-update/native-entry-build-record.json` | 最后入口文案的原生固定 EXE 干净双构建通过；实际窗口 AX 读到“不自动更新”的完整说明。工具窗口激活失败，未取得有效的新文案窗口截图，不以旧截图冒充；没有重跑服务/升级流程，自己启动的两个说明窗口已关闭 |
| `FINAL-RESTORE.json` | 演练 Runtime 已停止，端口/PID 不存在；原先借用的 Runtime 目录归还，47 个原文件所在目录恢复。原缓存/temp 未移动或清理；演练 Runtime/残余目录保留而非递归删除。工具会话结束后未重获原字节对照基线，不将第一次还原的 RESTORED.json 当成本次逐字节复核 |

浏览器记录含既有 Tailwind CDN 提示和一条没有来源 URL 的 MutationObserver 非 Node 错误；没有把全项目 console 宣称为零错误，也没有扩展本包去改无关创作界面。

本轮是单跳真实运行及目标失败恢复；没有替换在线原生 EXE/Setup 资产，没有重跑 C7 全部多跳、全部历史 Schema、整机重启或所有 GUI 组合。C5/C6/C7 原生工具、多跳及限定卸载/重装证据继续复用，不能将已有成功抹除，也不能外推本次来源覆盖全部已部署设备。未执行付费生成、客户设备操作、新 Release 或生产部署。

## 后续边界

本包经独立审查后纳入源码；正式发布和具体已部署来源采用路径仍需对应批准。安装维护只处理影响实际迭代的缺口；其余任意宿主/历史来源/GUI 组合按需求补充。业务主任务继续依据唯一路线图推进可靠任务与部门业务，不因扩大维护矩阵长期阻断；专业服务器/云和 500+/200+ 保留长期设计约束，当前不实施整体重构。
