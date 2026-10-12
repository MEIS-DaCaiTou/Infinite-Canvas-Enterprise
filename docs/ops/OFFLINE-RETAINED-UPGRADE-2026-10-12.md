# C6：离线升级、跨版本保留数据重装与原生维护工具更新

记录日期：2026-10-12。开发基线 `main@bc33339fd11df4c0303f29257766f0f2e53560fe`，代码候选 `4cc984b4657cda899722b07aa62ee3adccb8caa3`；本包尚待真实安装副本/GUI 验收和独立审查。正式 Release 仍为 v2026.10.1，没有客户或生产操作。

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
- 最终测试候选 C6b：`1abd6d451e8e730e55599b9fe9881420d28bb657`，只在独立 artifact clone 修改测试 VERSION 为 2026.08.6；没有修改主线发行版本。Manifest `879ee2fd7f8bad86492b256ee10124252cb90e18ccc4577d099ff0e71192b3a4`；native SHA `61e25c4f8f11dfa678371162dd9eae7d9f14c5770f8ca8b9e1f3e8b85d41b6a8` / 22528 bytes；Setup SHA `9989a806aaca2092a7b7fffa37bebc1dafd5392cf0438456eae7820ab0697f9e` / 33180564 bytes。两者分别双构建一致，未签名、未发布、未获生产批准。

2026-10-12 首次 GUI 查看被用户物理 Esc 中止，后台演练安全停止；历史目录未进入该轮移动，目录身份与上次已验证恢复一致。用户随后要求继续。中止、准备脚本失败和最终验收分别保留；尚未完成的确认按钮和真实跨版本范围不能改写为完成。

## 验收待收口与后续边界

当前正执行真实完整安装副本及原生 GUI 流程。最终结果、进程/端口清理、业务文件/安装身份保持和独立审查链接在本记录更新后集中提交。

自动多跳、在线原生 EXE/Setup 更新、完整业务维护态、未知未来 Schema 迁移、长期恢复副本/资产保留政策及旧 v1/未知锁接管仍是路线图中的独立工程能力。本包的离线原生工具更新不等于这些范围已完成；专业服务器/云部署和 500+/200+ 约束继续适用。
