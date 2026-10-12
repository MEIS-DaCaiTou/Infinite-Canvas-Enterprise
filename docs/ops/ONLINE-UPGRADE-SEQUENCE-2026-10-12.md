# C7：在线连续升级与原生维护工具更新

2026-10-12，2026-10-13 补充真实副本证据。沿用[唯一开发路线图 3.3](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md#33-日常更新与长期跨版本)。从 `main@bc33339fd11df4c0303f29257766f0f2e53560fe` 上的 C5/C6 开发候选继续实现；将 C5 的准确 Head `64c2adff3358e7f806d3cf04a26d86639597e573` 合入 C6 开发分支，扩展同一个 Draft [#155](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/155) 供集中独立审查。该开发合并没有合并 GitHub #154 或 main。正式 Release 仍为 `v2026.10.1`。

## 最终行为

选择直接可达版本时仍走直接路径；需要桥接时一次确认绑定整条已声明路径，最多 8 跳，正式路径不经过开发版本。准备阶段下载并核验全部程序和原生维护资产。最新目标包的 Python 更新执行器负责整条路径，逐跳复用 `execute_update_job` 的数据库资格、备份、迁移、指针、健康和恢复事务。

中间版本始终暂停业务 HTTP/WS；健康、登录和受权限保护的更新/恢复界面可访问。每跳重新检查原操作者的账号、角色、权限和身份版本，密码不进入持久记录。当前仍要求无活动生成任务；后台任务排空和可靠任务中心不由粗粒度请求暂停替代。

原生工具采用可选的 `maintenance-tools-v1.json` 发布资产，绑定准确 Release、Manifest、源码 commit/tree、固定 EXE、原生构建记录、Setup 和安装器构建记录。GitHub 资产摘要与包内身份共同核验。现有稳定卸载器通过保留 Setup 调用 Python 维护逻辑；只在已验证的卸载契约 1 内更新 Setup 和 HKCU 本实例 DisplayVersion，不替换未知卸载器、不改其他安装登记。历史包没有新资产时保留原生工具及原有单跳兼容路径。

固定入口、安装身份、保留 Setup 和 support.ini 使用 C6 的原对象保存/恢复机制。逐跳程序切换成功后才登记版本、保存不可变检查点；进度 JSON 不授权跳过步骤。第二跳失败只恢复到第一跳，不还原最初数据库。窗口关闭不取消后台作业；检查点上的协调器中断可从持久作业继续剩余路径。成功但登记/回执中断时完成登记，不重做数据库升级。中途未知状态继续使用既有只读恢复核验和审计解除流程，显式停止剩余路径前再验证当前服务、数据库和工具，不盲目回旧快照。

安装、入口/程序修复、卸载与缓存清理识别连续升级标记，避免在两跳之间抢占安装。平台文件操作和注册表更新仍在 Windows 适配层；业务请求暂停与现有业务/API 契约复用，未宣称 Linux、容器或云端生产已经支持。

## 集中证据与复用边界

开发机新增证据归 `D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/t/C7a/`，没有手工重跑 C4 和已充分证明的完整安装/卸载矩阵。

| 证据 | 已验证范围 | 限制 |
| --- | --- | --- |
| `sequence-targeted-a.xml` | 已有更新/执行器的 93 项受影响检查通过 | 初轮新夹具有 4 个错误，发现身份版本字段被既有脱敏规则处理；改用无秘密含义的 operator_revision，未放宽脱敏 |
| `sequence-targeted-b.xml` | 4 个连续升级关键场景通过 | 小型真实包校验、SQLite 和 pointer；Runtime 启停为桩 |
| `sequence-native-c.xml`、`native-registration-d.xml`、`checkpoint-stop-g.xml` | 11 个新增不同场景最终通过：两跳、检查点中断、末跳完成回执、当前跳恢复、权限撤销、进度篡改、原生对象替换/恢复、HKCU 精确版本更新、停机前中间包篡改拒绝、保留已完成版本停止剩余步骤 | 保留初轮原生夹具错误；修正使用 enterprise_source 而非 identity 读取 commit/tree。MZ 单元工具及合成卸载器不是真实 GUI 验收 |
| `verified-C6e-online-tools-b/` | 新打包工具对既有冻结 C6e 原生 PE、Setup 及准确构建记录的实际校验通过 | 复用真实构建，无新 Release、无 C7 全量程序重建 |
| Browser 页面与请求记录 | 已启用内置 Browser；实际 admin.html、回环合成 API；任务确认、路径、1/2 检查点、重开/新会话发现、停止确认/取消、继续到 2/2、完成后按钮隐藏；1021×704，相关 console error/warn 为 0 | 合成接口不执行真实升级；本轮没有新增手机视口或跨浏览器矩阵 |
| 原 C5/C6 冻结证据 | C5 真实固定 EXE 执行器接管/失败恢复、C6 完整安装副本/WAL/进程中断和限定跨版本重装、实际标准卸载 Yes 点击 | 来源、目标和源码提交保持原边界；不把旧证据写成 C7 新协调器的完整两跳实际启停或整机重启验收 |

前端验收发现并修正 active 状态恢复按钮未被隐藏、重开页面恢复入口缺失和停止弹窗叠层问题；补验对应操作，不重复全套旧页面门禁。新增控制器/原生事务和有限注册表写入必须独立审查。通常 CI 自动执行；准确最终 Head 结果在 PR 和集中索引记录，不用旧 Head 的成功替代。

## 保留边界

这是已实现的开发候选，尚未合并、发行或获得客户生产批准。本轮未操作客户设备、未迁移生产数据库、未调用付费 Provider。专业服务器/云部署、500+ 员工及 200+ 同时活跃创作仍为正式长期约束。

未定义的未来 Schema 不能预先承诺迁移；目标必须携带明确 registry、结构、来源、备份和恢复契约，由经验证的目标引擎执行。C7 停止来源的完整两跳原生/Runtime 组合已补证，在线交接仍受本轮 Windows 宿主资格阻断；真实整机重启和未列出的维护 GUI 场景尚未新增验收。已有 C6 的限定卸载/重装 GUI 已完成范围继续有效，不虚报所有历史来源兼容。新业务表随对应正式工作包提供准确旧来源证据，当前不启动新业务或整体架构重构。

改动的安装维护入口阻断和 pointer/页面契约另集中通过 34 项及 70 项关联检查（`boundary-closeout-e.xml`、`contracts-f.xml`），合计 208 项不同定向检查；已通过的旧执行器 93 项没有重跑。文档检查为 136 份、11 权威、21 冻结、307 本地链接，APP_ROOT 写入审计 506 点、无未映射/解析错误。正式未知恢复仍要求既有核验与安全审计；不以合成 CLR 标签绕过。

## 2026-10-13：完整副本组合演练与交接失败收口

新增证据位于 `D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/t/C7b/`。三份未签名合成包只在隔离克隆修改 VERSION，来源、桥接、最终目标分别为 `ice-2026.08.8-b69e68472603`、`ice-2026.08.9-2e1843315042`、`ice-2026.08.10-9aaf35b69594`；功能源码基于冻结 `4aadd8f0286e40c55ddc9297d58ace112dc6de91`。它们不是对应版本的客户历史包，没有发布到 GitHub Release，也没有修改正式 10.1。

- `real-c/coordinator-k/verified-complete.json`：来源停止后，由最终目标的真实 Python 执行整条两跳协调器，返回 0、SUCCEEDED 2/2。两跳均使用实际 Runtime、原生入口、保留 Setup、HKCU 登记与 SQLite；最终业务摘要、安装 UUID、目标登记版本和 Setup 内容核对通过。此证据证明停止来源的协调器，不包含来源 Web 进程向更新器的在线交接。
- `real-c/checkpoint-r/verified-checkpoint.json`：第一跳登记及不可变回执完成后协调器硬退出 93，指针、Setup 和登记停在已完成的桥接版本，数据保持，持久状态允许继续或停止。进程中断与整机重启分开记录。
- `real-c/success/`、`success-b/`、`success-c/`：真实 HTTP 执行分别记录演练 runner.lock 长度错误、`SYSTEM_UPDATE_HANDOFF_JOB_BLOCKED`、`SYSTEM_UPDATE_HANDOFF_CLEANUP_UNCONFIRMED`。初轮夹具错误修正后没有覆盖原失败证据；明确停止第二次未受理路径的响应也保留。第三次保留 RECOVERY_REQUIRED、reservation 和维护标记，没有修改事实来伪造恢复。
- `desktop-qualified-c.json`、`task-qualification.json`：普通桌面及临时最小权限任务的宿主资格仍未通过；错误 5、清理/来源租约不可证明分别记录。临时任务已核验并删除。没有关闭 Windows 保护或弱化 Job/进程身份检查。原 C5 在其准确宿主环境上的成功证据继续有效，不替代本轮 C7 在线交接。

本轮实际失败发现并修正三处状态问题：执行前同步拒绝先记录 FAILED 再释放自己创建的 reservation；交接失败保留来源、目标、原创建时间及既有字段；连续路径显示当前跳的真实终态原因，同时显式停止的结果不被旧失败覆盖。本轮 10 项不同状态检查通过；另 5 项历史目录保存/恢复检查验证快照优化仍保留内容、时间、目录身份及链接拒绝。初轮测试夹具 KeyError 与修正后的通过报告分开保存。上述新状态修复在本地检查验证，三份冻结合成包不包含它们。

`enterprise/tests/online_sequence_windows_smoke.py` 为显式运行的开发机工具，不进入普通 pytest 自动演练。它复用现有安装身份、目录归属、程序/原生资产与数据库事实检查，只在准备的新合成副本工作。恢复参数不绕过受理/检查点契约；停止来源协调器演练和 HTTP 在线交接在证据中分列。历史 KnownFolder 原目录按既有完整快照保存，只有准确 nonce 标记的演练根可以清理。

`real-c/checkpoint-r/runtime-cold-restart.json` 记录实际原生 stop/start/health。重启后通过真实 `/enterprise/admin`、真实更新 API 发现 1/2 检查点，点击继续实际准备第二跳，交接被 `SYSTEM_UPDATE_HANDOFF_JOB_BLOCKED` 拒绝，指针、数据、Setup 和登记仍停在 2026.08.9。随后真实点击“保留当前版本，停止剩余升级”，输入演练密码确认，返回 `SYSTEM_UPDATE_SEQUENCE_STOPPED`、完成数仍 1/2；`resume-and-stop-final.json` 证明原检查点文件的身份/内容/时间未变、维护标记解除，`business-reopened.json` 证明根入口不再返回维护 503，`owned-runtime-stopped.json` 证明最终健康及原生停止/端口释放。第二跳未进入目标健康阶段，不能将此次拒绝写成目标失败自动回退；该阶段原有单元与 C6 完整副本证据按其范围复用。

Browser 为已安装启用的内置入口，使用 frontend-testing-debugging 技能；本次实际页面/后端替代之前合成接口的检查点发现范围。DOM 1280×720 视口（页面截图 1265×712），登录/管理页身份正确、内容非空、无框架错误遮罩，检查点继续和密码确认停止均实际操作，捕获相关 console error/warn 为 0。截图/DOM/环境集中于 `real-c/checkpoint-r/browser-*`；未新增手机或跨浏览器矩阵。截图保留冻结代码显示旧 RESUMING 失败原因的事实，新反馈修复另由本轮定向检查验证。登录后直接进入管理页，未把登录默认跳转的其他页面视作验收。

演练收尾：真实 Runtime 停止及端口释放确认，三个合成安装的六个准确 HKCU key 在完整身份核验后清理；这是环境清理，不计为额外卸载验收。原 i 的不确定升级事实仍封存在安装副本，未把它改写成恢复成功。`RESTORED-c.json` 与保存会话的 `RESTORED.json` 确认原 KnownFolder 内容、文件时间及目录身份全部归回；原目录未覆盖/删除。首次独立恢复助手把 JSON 数组与内存 tuple 直接比较而停止，修正序列化比较后核对通过，没有放宽内容/身份检查。其他 worktree 和未提交修改保留，main 及正式 Release 不变。
