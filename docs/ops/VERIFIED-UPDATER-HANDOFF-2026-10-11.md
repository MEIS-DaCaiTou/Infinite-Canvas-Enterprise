# 工作包 C5：经验证的目标更新执行器接管

> 2026-10-13 文档同步：本文来自候选 #154@64c2adff3358e7f806d3cf04a26d86639597e573，PR 仍 OPEN/Draft，运行代码尚未合并 main。复制实现记录不改变其源码、构建、GUI 或客户验收范围；后续状态只见 [CURRENT](../CURRENT_PROJECT_STATUS.md)。

2026-10-11。从 `main@bc33339fd11df4c0303f29257766f0f2e53560fe` 的独立工作区开发，实施顺序继续沿用 [唯一路线图 3.3](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md#33-日常更新与长期跨版本)。#153 已独立审查并合并，准确 main 的 Enterprise、Runtime、文档三项 CI 最终成功；真实固定 EXE opt-in 跳过，原生编译未触发。正式 Release 仍 v2026.10.1。本记录保存同一完整工程包的实现及证据，不增加路线图。

## 问题与交付边界

此前路径规划可以报告中间版本，但每次实际执行仍固定运行来源 Release 的 Python 更新代码。新应用包即使携带更新引擎修正，也不能在本次维护中接管执行。C5 先建立目标执行器的身份及协议检查，再使用原有单跳事务完成切换/恢复，为后续逐跳授权与检查点提供前提。

本包只交付 **目标 Python 执行引擎接管**。原生固定 EXE/Setup 二进制替换、跨重启自动多跳、未知未来 Schema 的迁移、跨版本重装及完整原生 GUI 验收均不包含在本包完成声明中。已发布不可变旧包不重写；无新契约的目标仍走既有来源执行器路径。

## 实现与安全契约

- `enterprise/ops/update/updater.py` 是纯读取选择边界；目标包内固定 `updater-worker-v1.json` 分开声明控制器契约 1、worker 协议 2、引擎能力版本 4 和固定入口。引擎版本可以增加，稳定交接协议必须被当前来源明确支持。契约缺失才允许旧路径；损坏、额外字段、布尔冒充整数、越界、未知协议/控制器或不安全路径均拒绝，不降级绕过。
- prepare 完整校验并物化目标后，将目标 Release、Manifest、payload tree、契约摘要写入既有不可变计划，并与状态中的计划摘要绑定。状态转换保留该绑定；公开输出没有执行命令、绝对路径或密码。原有来源 DB/迁移 registry 资格检查不扩展为未知迁移授权。
- Supervisor 在创建目标进程之前再次完整验证目标包、inventory、固定 worker 和固定 `python/python.exe`；只向目标 worker 传递已经校验的来源 Release basename。准备后被改动的包不能据 READY 状态停服务。
- 目标代码/目标 Python 与来源数据根分开：导入目标代码，仍使用同一安装的来源 PathRoots 和持久作业。worker 独立复核绑定、自身代码/运行时和引擎契约；READY v2 包含准确计划/执行器身份，v1 或字段类型变化不能授权此路径。
- 保留原 source-process lease、独立 Job、host 创建/清理验证、跨进程接受 gate、超时/取消保护；收到 READY 后及接受 gate 内再核对绑定。只有持久接受后来源才停机。目标进程或清理不能证明时仍保留恢复阻断，不启动第二次猜测性执行。
- 仍使用原有数据库备份/迁移、pointer 切换、目标启停/健康、来源恢复和审计事务，不另建更新状态机。目标引擎执行失败不能使旧包恢复依赖被删除。页面显示目标更新工具和固定中文拒绝提示；不把协议细节作为普通用户操作步骤。

Windows Python/进程入口留在既有交付及 Runtime 边界，未增加业务核心的注册表、Job 或桌面交互依赖。专业企业/云服务器、500+ 员工和 200+ 峰值活跃创作仍是长期约束，本包不宣称 Linux/容器/云生产支持，不启动整体架构重构。

## 验证与证据

本地已完成 183 项交接/更新/路由针对性测试，`t/C5a/unit-b.xml`；另有 30 项 APP_ROOT 写入审计与 static 关联检查，`t/C5a/audit-a.xml`，以及 18 项管理页面提示/文档契约检查，先完成 231 项定向通过。随后根据准确 PR CI 失败补验 84 项 Runtime 诊断测试，`t/C5a/diagnostics-repair.xml`，合计 315 项不同定向检查通过。没有手工重跑 C4 充分证明的完整门禁。新契约模块没有写入操作；审计并不代替运行时或数据保护证据。Runtime 的 CP314 CI 清单补入目标执行器、交接生命周期和接受 gate 测试，既有 Enterprise CI 仍按原规则执行。

PR #154 的初始 Head `1bb2e9a57b6268a53643a27ddf1cd2e81899094b` 在 Runtime CI 中有 10 failed / 344 passed：旧 Job 故障测试夹具只模拟预留、未模拟新增执行器选择，因缺少真实计划而提前进入 updater 拒绝，没有到达待验证的故障分支。修正只为该来源 worker 夹具声明 legacy selection；目标拒绝由独立契约测试覆盖，没有放宽产品 gate 或修改运行实现。保留 `ci-runtime-a.log`；本地诊断模块 84 passed 后推送同一 Draft PR，最终准确 Head 的 CI 另在集中索引和 PR 中核对。

真实固定 EXE 演练使用独立的完整合成源/目标包、CP314 和新建合成账号、SQLite、画布及素材，证据归 `t/C5a/`，与客户数据、公开 Release 分开。构建来源 `6505d367e9dbdcddecb0bc13fe24b347fdd169c6`；合成目标 Git 提交 `978720c91d7dd20467097f64cabda8de1d699c8d` 同时更新源码 VERSION 和执行器为 5，不伪改 Manifest。协议不兼容目标为独立合成提交 `a780f22e812e98c55ac7bdb0ea337eacfcc13d81`。构建输入、运行观察、终态及目录恢复结果按实际完成情况集中记录，未将仅构建成功写成升级成功。

首轮命令宿主下，来源 Job `0x2000` 拒绝 `0x01000208` worker 创建（WinError 5/errno 13），作业安全 FAILED，未持久接受；`real-a/` 保留该失败，原测试目录经完整字节/mtime/FileId 核验恢复。演练入口现先运行严格交接资格，再允许安装副本和历史目录保护；`restricted-context/` 在不合格上下文拒绝，未物化或启动产品。普通当前用户 Explorer ShellExecute/隐藏 PowerShell 7 的 CP314 资格检查 `desktop-qualification.json` 已通过，Job `0x1800`、准确 source lease、独立 worker、host 创建/清理及 worker/源 Job 关闭均核验。此资格不是完整应用升级成功，不修改外部 Job 限制或降级安全要求。

| 完整安装副本场景 | 有效记录 | 核验结果 |
| --- | --- | --- |
| 成功切换 | `real-b/success/result.json` | `SUCCEEDED / SYSTEM_UPDATE_SUCCEEDED`；观察到准确目标 Python worker；来源三进程退出，指针切到目标，目标健康、数据保留 |
| 目标启动失败后恢复 | `real-c/rollback/result.json`、`fault-acquired.json` | 注入目标网关端口占用；`ROLLED_BACK / PORTABLE_RUNTIME_OWNERSHIP_UNTRUSTED`；目标引擎 5 实际执行，来源指针/健康恢复、数据保留 |
| READY 后 worker 被改动 | `real-c/tampered/result.json` | `FAILED / SYSTEM_UPDATE_UPDATER_UNVERIFIED`；没有目标 worker，来源三进程身份及指针保持、健康/数据通过 |
| 目标 worker 协议不兼容 | `real-c/incompatible/result.json` | prepare 拒绝 `SYSTEM_UPDATE_UPDATER_INCOMPATIBLE`；来源服务未停、指针/健康/数据通过；表中的 FAILED 是演练拒绝结果，不伪称已经执行升级作业 |

`real-b` 的回滚作业虽到达 ROLLED_BACK，但脚本错误读取 `FAULT.json`，使该轮最终健康/数据断言未完成。原记录保留；修正为准确 `fault-acquired.json`，核对 bound/port 后只补验回滚和尚未执行的两种拒绝，`real-c/SUMMARY.json` 与 `REMAINING-DONE.json` 确认退出 0。成功场景没有重跑。每个完成场景都执行固定入口健康检查、SQLite quick/FK 检查和账号/权限/画布映射/feature flag 语义快照比对，并比较画布、素材、配置、安装身份、固定 EXE 五类文件的准确字节；升级审计新增不要求数据库文件整体字节不变。关联 `stop-*.json` 证明测试拥有进程退出和端口释放，worker 与作业 reservation 亦已清理。首轮历史目录恢复证明保存在 `first-run-restored.json`；普通桌面上下文的演练没有发现既有 KnownFolder 根，`historical_roots_preserved=false` 不写成再次移动和复核了历史内容。

维护页面使用已启用的 **Codex 内置 Browser 26.1007.21434** 和实际 `enterprise-static/admin.html`、loopback 合成接口，验证“更新中心 → 更新到新版本 → 密码确认 → 确认并开始升级”、目标执行器显示及拒绝/恢复提示；协议不兼容返回后没有 execute POST。1440×1000 桌面、请求 390×844 的移动视口检查页面身份、非空、无错误覆盖层和相关 console error/warn，并保留截图；移动截图实际像素为 375×812，二者分列，不把截图尺寸当作设置尺寸。修正“已核验”为“准备时已核验”，区分准备记录与后续重新核验；UPDATING 显示“正在核验并交接服务”，避免停机前拒绝被误读为已经停止。合成接口不执行真实升级；Windows 卸载按钮仍未验收。原 C4 使用 Edge/Playwright 的有效证据继续保留；此前 Browser 不可用的归类已修正，无需重复安装。

开发机集中证据根为 `D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/t/C5a/`：`handover-evidence.json` 汇总准确 Git/CI、构建、定向测试、四类真实副本场景和清理；`browser-evidence.json` 汇总页面身份、流程、视口、console 和截图。原始终态、进程观察、故障注入和失败记录随索引保留，不进入客户业务目录或公开 Release。

## 剩余阻断与审查要求

准确 PR Head、CI 与独立技术审查分别记录；成功测试不自动授权合并、发行或生产部署。旧源码中的历史 VERSION 保持原值；合成目标版本仅用于开发演练。未操作客户设备、未调用付费 Provider、未发行 Release。

后续仍需完整事务工作包实施跨重启多跳授权和逐跳恢复、原生更新入口/Setup 自身替换、完整业务维护态；跨版本重装与原生卸载确认按钮未验收范围继续如实保留。不得以本包的页面或静默入口证明完整 GUI 验收。
