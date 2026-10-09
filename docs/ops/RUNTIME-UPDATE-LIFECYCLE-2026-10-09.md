# 主线升级生命周期诊断与恢复阻断实施（2026-10-09）

本文仅记录该增量的设计和验证；[当前状态](../CURRENT_PROJECT_STATUS.md) 与 [路线图](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md) 仍是唯一状态/顺序入口。没有生产操作或发行授权。

## 1. 来源与范围

- Base：`main@76cc43d2a5fea8c40adf49c52eb66751e01411e4`，基线收口 #146 已合并。
- 分支：`codex/runtime-update-lifecycle-mainline-20261009`，合并/CI 以本记录所在 PR 的准确 Head 为准。
- 选择性复用维护候选 #145 的 `d0861f907e0d33cd18f14e65eb44bbe19bdfac94` 中有效诊断/路径增量；没有合并整条分支、10.2 VERSION、旧交接文档或其未提交测试修改。
- 保留 main 的修复 fence/lease、no-create 恢复查询、数据库 v2、权限及任务实现。原配置 checkout 和其他工作树不改动。
- `VERSION=2026.08.5` 历史源码标记未改。正式 10.1 资产、生产设备及原始现场失败记录未修改；本增量不倒灌到旧包。

## 2. 生命周期证据

`UpdateJobStore` 在现有 status/events 中记录最多五个执行阶段的结果摘要：

| 阶段 | Release | 命令 | 何时执行 |
| --- | --- | --- | --- |
| target_start | 目标 | start | pointer 切换后 |
| target_health | 目标 | health | 目标启动成功后 |
| target_stop | 目标 | stop | 失败回退且 pointer 已切换 |
| source_start | 源 | start | 经验证恢复 source pointer/schema 后 |
| source_health | 源 | health | 源启动成功后 |

每个阶段先记录 started，再保存 Release、命令、退出码、结果码、时间和固定诊断字段；status 转换保留结果。目标失败的 `failure_code` 与最终恢复 `result_code` 分开，恢复失败不能覆盖最初原因。旧作业不会被补造缺失阶段。

直接 CLI 和 portable 入口共用纯标准库白名单：固定 stage/bootstrap 类别、有限整数 errno/winerror/host exit。不保存异常正文、stdout/stderr 原文、文件路径、环境或密钥。启动宿主创建、marker 准备、日志建立、入口缺失、早退和 readiness 超时分别可识别；日志创建失败也释放自己预约的锁，不清理他人的实例。

portable CLI 保留已经核准的 lexical APP/Runtime 根，不再通过 `resolve()` 把 Windows KnownFolder 身份替换为虚拟化后的路径；同时明确验证 reparse 祖先与目录隔离。不能据此放松完整进程身份、Manifest 或 Python 校验。

## 3. 新补的恢复保护

- 原更新执行器忽略目标 stop 的退出码，可能在停止尚未确认时恢复数据库/指针并启动 source。本增量先验证 stop；无法确认时停在 `RECOVERY_REQUIRED / SYSTEM_UPDATE_TARGET_STOP_UNCONFIRMED`，不恢复数据库/指针、不启动 source。
- source 启动异常/非零或 health 失败同样保留恢复阻断；启动未成功不执行/伪造 health。迁移提交前的 source 恢复异常也有持久终态，不逃出 worker 留成普通失败。
- 启动器退出 0 但没有有效 JSON 对象仍返回失败；阶段结果拒绝 bool/非整数退出码和空/非对象结果。进程退出成功不能代替受信任的结果文档。
- 有版本化迁移时继续要求 expected-current 数据库恢复及 pointer 身份校验；不自动删锁、解除阻断或重提业务任务。

## 4. 开发验证

验证分别归类，不能合并称为“完整生产升级通过”：

- Windows Python 3.11 最终定向组 **222 passed**（21.30 秒，两个既有 FastAPI on_event 弃用警告）：诊断、更新、恢复解除、portable 集成/身份/真实 BAT wrapper、preflight、静态树/APP_ROOT 写入审计、测试根保护。
- STAB-1 Windows 本地组已运行 52 个测试，包括新诊断初版与真实 CLI/宿主/角色停止、重启、所有权、崩溃隔离、日志及 ACK。后续新增允许字段/无效输出测试另作定向复核，不冒充重跑全套。
- 使用已有核验的 `ice-2026.10.1-bf1143a7bc54` 安装副本中的 CPython **3.14.6 x64** 执行当前源码 `test_stab_1_supervisor_logging.py --case cli-lifecycle`，实际结果通过：临时随机端口、fixture 子进程、后台 host、跨短会话控制与停止。它验证的是当前源码的 development CLI，**不是该正式包已包含本增量**，也不是固定 EXE→更新 handoff 全链。
- 目标停止失败分别覆盖同结构和改表路径：pointer 保留目标；改表库保持目标 schema，不回滚数据；source 不启动，后续作业被恢复门槛阻断。源恢复异常覆盖 pointer 切换后和迁移失败前两条路径。诊断 ZIP 保留阶段且不含注入的私密正文。
- 既有 APP_ROOT audit gate 继续通过；没有新增 Runtime 对 APP_ROOT 的写入能力。docs 检查仅验证登记/链接等文档契约。
- 诊断及最终 CLI/启动锁边界复核 **27 passed**；文档登记/链接检查通过，文档契约 **17 tests / OK**。GitHub CI 是独立证据，以 PR 准确 Head 为准；不把本地数字伪装成 CI。

## 5. 未覆盖与发布限制

本轮没有执行新构建完整安装副本的 portable 更新/自动回退端到端。现有 `update_mvp_1_windows_smoke.py` 要求默认当前用户根为空，开发机已有本产品历史 Runtime/cache；未为得到通过结果搬移、覆盖或删除这些材料。后续应完善仓库外隔离 fixture/安装副本验证，不把另购干净主机或账户作为开发前置门禁。

真实 CLI 与执行器故障注入是两组独立证据，不能拼接为完整固定入口→handoff→目标启动→自动恢复验收。未新增 schema、付费 Provider 调用、长稳/硬件故障测试、Release、生产启停或零停机声明。

早前生产失败的缺失 stage/errno 仍是 `not_recorded`；本增量只能改进未来记录。EXE 重建上下文后 10.1 成功不能证明旧失败的唯一根因，也不能证明已解决全部长期崩溃问题。
