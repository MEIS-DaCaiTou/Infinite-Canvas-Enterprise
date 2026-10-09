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

## 6. 评审合并后：完整固定 EXE 演练准备

#147 已于 2026-10-09 合并。准确 Head `222b2dfd8adc2c1237ff8d38cddd3093640139ba` 经评审、三个 CI 检查通过并按 Head 校验合并；merge 为 `a5a6aa10b7882c46f129ec6df854239ee111da18`。没有发布新 Release、覆盖 10.1 或连接生产。

后续分支 `codex/fixed-exe-update-validation-20261009` 增加独立 opt-in 脚本 `enterprise/tests/fixed_exe_update_windows_smoke.py`。它使用真实固定 EXE、自己的全新数据库/账号/配置/画布/素材、实际登录及密码授权 HTTP execute、真实 detached handoff worker，预期核验三种终态：`SUCCEEDED`、瞬时端口冲突后的 `ROLLED_BACK`、端口冲突持续时的 `RECOVERY_REQUIRED`。同时验证源进程退出、worker 退出、指针、阶段记录、业务身份及配置/素材保留、完整程序 payload。不是直接伪造启动器返回值或作业终态。

两个包从干净、可追溯 Git 提交独立构建，产物仅在仓库外开发 artifact 目录：

| 测试身份 | 准确源码 | ZIP SHA-256 | detached Manifest SHA-256 |
| --- | --- | --- | --- |
| 源 `ice-2026.08.4-df69184a3f01` | `df69184a3f0181669828f94199fd533f3832aa26`，仅把测试源 VERSION 从合并后的 main 改成 2026.08.4 | `d245ff10012cc91aaa1d12f12c0c031a48e8662db49801b5c1edf72b9a019d6f` | `91c124c1f64c7f0c91fe301e664506f948b80dee97b0db51e4e2743d32c1d12f` |
| 目标 `ice-2026.08.5-a5a6aa10b788` | `a5a6aa10b7882c46f129ec6df854239ee111da18` | `a4a6399b7e1ac96760d1d17a8f0cc7bc14762819ca2c6bbcc64642a8ecb7a267` | `8f9bffebce014e3a288579b2eceb33ad7820aec1a76734baccd5afd087b6dbe8` |

两份 native build 也分别绑定对应提交，固定 EXE 双构建一致，SHA-256 为 `570ad6885cae124e39f534bc6a95073212eec0ad4d9c1d8085f5e0888d3987fd`。同结构 v2 数据库；已有 CPython 3.14.6 x64 Runtime 按构建器核验后复用。测试版本号仅为引擎的 newer-only 路由提供准确夹具身份，不代表历史客户 08.4/08.5 资产，也不发布这些测试包或源 fixture 分支。

安全定向组 `test_fixed_exe_update_smoke_safety.py`、既有烟测清理保护与生命周期诊断 **48 passed / 4.02 秒**。它只证明未授权不移动、停止身份门槛、未知锁不清理、目录边界、保存副本完整性、恢复不覆盖及继承配置隔离；不是三条真实 EXE 场景已通过。

截至 #148 初版 Head `43dd5e9a163cbe3d9580baab90e5fee4a82397ed`，开发机历史默认根只读核验为 stopped、无活动实例，尚未移动，完整执行等待明确许可。该 Head 三个 CI 检查随后通过。默认拒绝占用根，不删除历史材料，也不把新账户/干净设备作为门槛；异常清理或恢复目的地被占用时保留两份材料。获授权后的执行结果见下节，不能继续把本段未执行状态当作最新结果。

## 7. 获授权后的真实链路结果：未通过

负责人明确确认允许临时封存开发机两处默认 Runtime/cache 并原样恢复。测试不连接生产，不使用客户数据、配置或密钥，也不调用付费 Provider。

准备过程中修正了测试工具边界：历史缓存长文件使用 Windows extended-length 命名空间读取，仍逐项检查 reparse；保留 builder 原始输出和 attestation，另建已完整校验的三资产安装视图；KnownFolder fixture 清理保留 lexical 身份，不用可能虚拟化的 `resolve()` 替换；测试安装根缩短到仓库外 `D:\CodeProject\review-artifacts\t\F1\f\s\i`，避免准备阶段的 nonce partial 目录触发 WinError 206。没有改系统长路径设置、正式源码/资产或生产配置。

真实作业 `2cc8dbfb5b2e447c854322d1774a712e` 已完成固定 EXE 启动、健康、实际超级管理员登录、当前密码授权 HTTP execute 和 detached handoff，但预期成功场景最终失败：

| 实际阶段 | 观测结果 |
| --- | --- |
| 源固定 EXE 启动与健康 | `started`；readiness 全部 true |
| target_start | exit 2；`RUNTIME_CONTROL_ERROR`；`failure_stage=service_host_create`；`errno=13`；`winerror=5` |
| target_stop | exit 0；`SYSTEM_UPDATE_RUNTIME_PHASE_OK` |
| source_start 自动恢复 | exit 2；相同创建宿主阶段和 OS 错误 |
| 最终状态 | `RECOVERY_REQUIRED / SYSTEM_UPDATE_ROLLBACK_HEALTH_FAILED`；原始 `failure_code=RUNTIME_CONTROL_ERROR` 保留 |

证据保留在 `D:\CodeProject\review-artifacts\t\F1` 的真实安装副本、作业 status/events 与 native 结果中；未生成成功 SUMMARY。失败注入的 rollback/recovery-required 两场景因首场景失败而未执行，不报告三条链路通过。阶段/错误落盘有效，但恢复闭环尚未通过。

测试实例和 worker 已结束，开发机历史根通过原字节/mtime/目录身份恢复验证；曾因旧清理 helper 的 resolve 别名误拒绝留下的两个 fixture marker 目录也保留，没有删除历史内容。下一步应以该失败为输入核清 Windows 创建宿主条件（包括 Job Object 继承/脱离策略），修复并重验真实成功与失败链路；Job 机制目前仅为待核验假设，不能从 WinError 5 单独认定根因，也不能反推旧生产失败的缺失字段。

#148 继续保持 Draft，不合并未通过的完整验收，不发布新版本。定向安全/清理/诊断测试扩至 **53 passed**；文档和后续 CI 以实际 Head 记录，不以初版绿 CI 代表这些补充已经验证。
