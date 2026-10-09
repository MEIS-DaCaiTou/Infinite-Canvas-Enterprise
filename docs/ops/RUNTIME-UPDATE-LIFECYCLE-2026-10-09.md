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

测试实例和 worker 已结束，开发机历史根通过原字节/mtime/目录身份恢复验证；曾因旧清理 helper 的 resolve 别名误拒绝留下的两个 fixture marker 目录也保留，没有删除历史内容。F1 当时仅提出 Job 继承/脱离的待核验假设，没有从 WinError 5 单独认定根因，也不能反推旧生产失败的缺失字段。随后新增真实创建上下文及保护验证见下一节，不改写这次原始失败证据。

#148 继续保持 Draft，不合并未通过的完整验收，不发布新版本。定向安全/清理/诊断测试扩至 **53 passed**；文档和后续 CI 以实际 Head 记录，不以初版绿 CI 代表这些补充已经验证。

## 8. 真实 Job 上下文与停机前安全阻断

本节记录 #148 在 2026-10-09 的定向调查和工程修复，不变更正式路线图、需求范围、数据库表或客户环境。根因证据及最小建议先记录于 [PR 调查记录](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/148#issuecomment-6079147935)，随后实施停机前保护。

### 8.1 真实失败上下文，不以匿名探针代替

只读诊断提交 `283ef49a896532b5465efbb7abffc9bbd977109f` 不改创建行为。源 fixture `84eafac563ecff5cab921bd5a805044c0f79c423` 与目标诊断提交分别构建完整测试包；固定 EXE 字节及 CP314 Runtime 不变，Manifest/Inventory/ZIP 校验通过。原 F1 和正式 10.1 资产未修改。

真实作业 `ee3e9ebffd7c4257b1d6eee62ca56f02` 在仓库外 `D:\CodeProject\review-artifacts\t\J2` 复现：

| 真实创建位置 | 观测的 Python creationflags 请求值 | 查询到的 immediate Job flags | 结果 |
| --- | --- | --- | --- |
| 固定 EXE 初次启动源 service-host | 0x01000208 | 0x2800 | 启动、健康成功 |
| Supervisor 创建 handoff | 0x00000208 | 0x2000 | 普通 detached 创建成功 |
| handoff 创建目标和恢复 launcher | 0 | 0x2000 | launcher 创建成功 |
| 目标及恢复 launcher 创建 service-host | 0x01000208 | 0x2000 | 两次 service_host_create，errno=13 / winerror=5 |

`0x01000208` 包含 BREAKAWAY_FROM_JOB、DETACHED_PROCESS 与 NEW_PROCESS_GROUP；`0x2000` 仅 KILL_ON_CLOSE，`0x2800` 另含 BREAKAWAY_OK。Job 查询成功、源/目标两个真实阶段均保留这些白名单字段和 worker 上下文，终态仍为 RECOVERY_REQUIRED。诊断/清理定向测试 **55 passed**；不是完整升级通过。

标志精度边界：日志记录的是实际调用 `subprocess.Popen/run` 的请求参数，不是独立 WinAPI Hook/ETW 记录。[CPython 3.14.6 的 _winapi 后端源码](https://github.com/python/cpython/blob/v3.14.6/Modules/_winapi.c#L1304-L1315) 在 `CreateProcessW` 时再 OR `EXTENDED_STARTUPINFO_PRESENT`（0x00080000）及 `CREATE_UNICODE_ENVIRONMENT`（0x00000400）。按这份已固定版本源码推导，上表请求 0 / 0x208 / 0x01000208 对应 API 参数 0x00080400 / 0x00080608 / 0x01080608；这些附加位不改变 breakaway 判断。原始诊断值不补改，也不声称捕获了 .NET 初始 launcher 创建时的全部 API 标志。

本次真实失败的直接条件得到核验：禁止 breakaway 的调用 Job 与必须脱离的宿主创建不相容。初次成功后变成另一个 Job 的解释与 [Windows 嵌套 Job 部分脱离契约](https://learn.microsoft.com/en-us/windows/win32/procthread/nested-jobs) 一致；没有枚举全部祖先、取得外部 Job 名称/句柄或证明其创建者。`QueryInformationJobObject(NULL)` 只代表 immediate Job。后续 J7 真实日志进一步确认 Supervisor **不属于自己创建的 runtime Job**，因此不能靠放宽业务子进程 Job 来修复外部限制。旧生产失败的缺失字段仍不补猜测。

### 8.2 最小保护与影响

- handoff 在停止源服务前明确请求 Job 独立性；普通 SILENT_BREAKAWAY 情形使用其自动脱离契约，其他 Windows 创建请求包含 BREAKAWAY。
- 创建失败不取消隔离标志重试；创建成功也使用原 Popen 进程句柄核验 worker 不属于任何 Job。无法证明独立性时，仅回收刚创建的 worker，源服务不进入 stopping。遇查询失败仍阻断，不伪造“无 Job”。
- WinError 5 只有在已查明的 restrictive Job 条件下归为 Job 创建阻断；其他拒绝保留一般创建失败。新 handoff 创建失败日志也使用 stage 之外的固定上下文、errno/winerror 白名单，不保存异常正文。
- 更新持久记录专用结果码 `SYSTEM_UPDATE_HANDOFF_JOB_BLOCKED`，释放自身预约；不创建 target_start/source_start 假阶段、不切换指针或迁移数据库。
- runtime 业务子进程 Job 的 KILL_ON_CLOSE、gateway/upstream 创建标志、身份/fence/lease、端口停止确认、目标 stop 与数据库 expected-current 恢复保护不变。不修改外部 Job、不向所有业务子进程开放 breakaway、不运行逃逸 broker 或系统调度绕过限制。

### 8.3 真实负向保护演练通过，不是升级成功

安全保护提交 `21145a02fc2760c369fe615c99404f4cbc4187cc` 的合成源 fixture 为 `17f3662d92a1088d6185313b821e006dcbfa868a`，仅使用 older-only 路由所需 VERSION 差异。源码和固定 EXE 从干净提交完整构建，包校验通过。固定 EXE SHA-256 仍为 `570ad6885cae124e39f534bc6a95073212eec0ad4d9c1d8085f5e0888d3987fd`；不是对已发布文件打补丁。

可重复调用 opt-in `--restricted-job-guard` 模式；证据 `D:\CodeProject\review-artifacts\t\J7`，真实作业 `ad3d2528eb3e41e78b5c1db3e9f9a02a`：

- 真实源 EXE 启动、super_admin 登录、密码授权 HTTP execute 均执行。
- 源 Supervisor 的外部 Job 为 0x2000，`process_in_owned_runtime_job=false`；带 BREAKAWAY 的 handoff 在源仍 healthy 时被拒绝。
- 终态 **FAILED / SYSTEM_UPDATE_HANDOFF_JOB_BLOCKED** 为预期负向结果；`runtime_phases` 没有执行项、指针保持 source。
- 原三进程的创建身份未变化，源健康与再次登录通过；预约释放、无残留 worker、业务身份/数据/配置/画布/素材保留，以及源/目标完整 payload 校验通过。
- 最后只停止自己的测试实例；原开发历史 Runtime/cache 已通过字节/mtime/目录身份恢复。无生产操作、付费请求或 GUI 点击验收。

故障前阻断、更新/诊断/隔离安全定向组 **115 passed**；APP_ROOT 写入审计定向 **7 passed**。最后增加的 handoff 错误落盘属于同一策略的诊断补充，另做定向复核；不冒充 J7 已重建执行该后续日志补充。

| 完整真实门禁 | 本轮状态 |
| --- | --- |
| 固定 EXE 完整升级成功 | 未通过；受限环境现在正确停在停机前保护 |
| 目标失败后自动恢复 source | 未通过；J2 已观测失败，J7 未运行该场景 |
| 持续失败后的恢复安全阻断 | 未完成完整场景；现有执行器定向检查不替代它 |

#148 保持 Draft。完成三门禁需要真实允许独立宿主的启动上下文及完整安装副本；不会以去掉隔离标志或绕过外部 Job 的方式制造通过结果。本节不形成第二套路线图，也不把源码、定向测试、CI、合并、Release 与现场验收合并为一个完成状态。

## 9. 工作包 B：关联异常收口与测试环境门槛

负责人已确认以一个可靠性交付工作包连续处理相关实现、回归和真实验收，不逐项申请小修改审批；本工作包仍使用 #148，不增加产品范围或另一套路线图。#149 的 Docs-only 需求基线已独立批准并合入 main（`b9a9d860bf202737dd4dc491e2b7ce9ea9058d15`），不授权核心业务代码、Release 或生产操作。

### 9.1 本轮关联修复

- 新 worker 的身份缺失、解释器不匹配、身份读取失败及 Job 查询失败统一走原 Popen 句柄回收，不能只返回失败而遗留等待源停止的 worker。正常确认退出才允许作为安全失败释放自身预约。
- 回收被拒绝、等待超时或无法确认退出时，源不进入 stopping；API 持久化 `RECOVERY_REQUIRED / SYSTEM_UPDATE_HANDOFF_CLEANUP_UNCONFIRMED` 并保留预约，阻止再次升级。无须停止仍健康的业务服务，但也不自动解除恢复警告。
- 未取得 handoff 确认属于未知，不猜测未创建 worker；迟到/丢失确认不覆盖已完成的终态。审计写入失败不降级恢复阻断，不释放不确定 worker 的预约。
- 被拒绝的 worker 后续超时或执行失败不得把既有终态改成普通 FAILED，也不得清除已保存的阻断/预约。只有 UPDATING 作业可进入执行器；不确定清理的作业不能迁移或切换指针。
- 不改 gateway/upstream Job 隔离、角色创建标志、停止确认、expected-current 数据恢复、身份权限或业务数据库格式。真实停止未确认仍不能启动 source 或盲目恢复数据。

### 9.2 集中验证与环境结论

关联回归集中覆盖身份失败、Job 查询失败、创建拒绝、清理超时、预约/终态保留、迟到确认、数据指针不变，以及原诊断、执行恢复与烟测清理保护。另用自己的真实 Windows 子进程验证成功回收与 5 秒超时；超时测试的终止请求被定向抑制，最后仅回收原子进程，不操作其他 PID。

本轮四个直接相关模块集中回归：158 passed（含两个真实子进程用例），23.28 秒；`tools/check_docs.py` 通过，`git diff --check` 通过。这些结果不是固定 EXE 三门禁或现场稳定性证据。

此前 J2 真实失败和 J7 真实停机前阻断直接复用，未再次在同一受限宿主运行完整升级。本轮仓库外 `D:\CodeProject\review-artifacts\t\WPB1` 仅评估替代启动上下文：

- 当前账户、RunLevel=0、InteractiveToken 的一次性调度资格检查运行后已移除自建任务；观察到 Job flags=0，未证明独立性。未用 SYSTEM、提权、账户密码、持久运行任务或修改 Job。
- 普通 Shell 自动化创建仍保留原受限链；经现有 Explorer/桌面上下文的资格检查观察到 0x800 → 0x1800。实际 CP314 Runtime 在有限三层创建后仍报告属于 Job，未达到当前 handoff 的强独立性检查。
- 0x1800 包含允许 breakaway 的位，不能写成“禁止创建”；也不能把成功创建等同于 worker 已不属于任何 Job。没有据此扩大到读全部祖先句柄、改外部限制、假定其所有者或放宽产品保护。
- 资格检查不移动历史 Runtime/cache，不安装应用、不切换指针、不连接业务库；所有临时子进程已结束。它不是三条固定 EXE 完整场景的执行结果。

**环境状态：INDEPENDENT_HANDOFF_ENVIRONMENT_NOT_VERIFIED。** 不继续重复相同无新证据的失败演练，也不以 CI 或上述小探针替代真实门禁。后续仍为本工作包 B：优先使用现有 GitHub Windows Runner 或可证明独立性的开发/测试会话；不强制要求新设备、干净用户或关闭系统安全保护。选定宿主后，用同一 `fixed_exe_update_windows_smoke` 的 `--run-all` 一次集中执行完整升级、目标失败自动恢复和持续失败安全阻断；沿用准确合成源码/Manifest/Inventory/Runtime/EXE 身份与原数据保留检查。

现有 `enterprise-checks.yml` 增加手动 `fixed_exe_gates=true` 入口（默认关闭），先用普通 detached 宿主及产品相同的 breakaway 策略验证原句柄独立性，未通过即停止。不降低 Job 门槛，也不重复执行默认两组 CI。通过后才下载 SHA-256 固定的 Runtime/轮子/编译器，使用当前准确 clean Head 构建合成目标和仅 VERSION 不同的本地合成源提交，再运行上述三门禁。只保留小型合成证据 7 天，不发布正式版本，不携带客户数据或凭据。Runner 资格用例新增 7 项定向检查，烟测保护模块共 32 passed；资格检查通过本身仍不等于 EXE 演练通过。

在三项真实门禁全部通过前，#148 仍 Draft，工作包 B 尚未完整交付，也不启动阶段 3 之外的业务开发。集中交付证据在 PR 汇总，不为各错误条件建立新项目或重复交接包。
