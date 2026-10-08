# Infinite Canvas Enterprise 当前项目状态

更新时间：2026-10-08
核验对象：下列历史 PR/主线表仍为 2026-10-05 快照。本轮刷新主线基线 `309b35fb41956bd457d009cd54762bb647db15a3`、正式 09.9 与 2026.10.1 维护 Release、PR #143/#144 及单台设备已提供的 10-08 上线/超管修订/入口准备证据；未重新验证整张历史 PR/CI 表。

## 1. 基线与交付必须分开

| 层级 | 本次核验事实 | 不能据此声称 |
| --- | --- | --- |
| GitHub 主线 | `main@095867641453e62458f8398ec98d4302d8acacf8`，PR #137 文档、#138 固定入口、#139 安装接线、#140 维护演练/路径修正、#141 程序修复/进程中断恢复已合并；源码 `VERSION` 仍是 `2026.08.5` | 主线文件的版本号不等于客户当前 Release |
| 主线已合并能力 | Runtime、安全边界、数据迁移/恢复接线、审计恢复解除阻断、一次确认进度、正式/开发通道、旧库登记与路由检查 | 不等于完整统一安装维护或自动多跳已完成 |
| 正式应用 Release（10-08 刷新） | [2026.10.1](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/releases/tag/v2026.10.1)，非 Draft/非 prerelease，`ice-2026.10.1-bf1143a7bc54`；仅开放精确正式 09.9 来源的同结构后台维护路线；原 09.9 资产未覆盖 | 维护 Release 不等于 main 已合并或该设备已经完成维护 |
| 维护线差异 | PR #132–#135 在维护线合并，含正式过渡、受控安全数据库桥接、原生工具和定位；未整体合并到上述 main | 这些 PR 的 MERGED 状态不等于合并 main |
| 通用工具 | [2026.09.9-unified-upgrader.1](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/releases/tag/2026.09.9-unified-upgrader.1) 是工具验收预发布；[PR #136](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/136) OPEN/Draft，基于维护分支，Head `f86754867c2ecf10ca1b32b66dc926371fe9f0b2`，两项 CI 已通过 | 不是正式新装器、完整员工桌面客户端，也未进入 main |
| 付费提交止损 | [PR #123](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/123) OPEN，Head `05a349c9ce75e394f5ef6321816831600d97182f`，两项 CI 已通过 | 不能写成主线已全面防止重复付费 |
| 设计与文档 | [PR #137](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/137) 10-05 合并，Merge `a7ff9ba689f310b419c7c4d375898068e4e80bd7`；复用准确 Head 的三项已通过 CI | ADR Accepted 和文档合并不代表完整安装/更新实现完成 |
| 固定入口主线基础 | [PR #138](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/138) 10-05 合并，Merge `65d3f8a936e082e6e991be24f0800901c497f3fd`；C# 薄入口、版本无关构建与编译后契约已回归，见 [DELIVERY-1](./ops/DELIVERY-1-FIXED-NATIVE-ENTRY-2026-10.md) | 不是新应用 Release、完整安装维护或客户启停验收 |
| 安装接线主线成果 | [PR #139](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/139) 10-05 审查后合并，Merge `dc6a24fae88a74848d2c6d0eb6a088d892a1e2e3`；新装接入根目录 EXE、独立实例 ID、HKCU 定位提示及入口专用修复；修复不换程序版本或修改业务数据 | 该 PR 不包含程序修复，后续增量见 #141/图形候选；标准卸载及完整图形维护验收仍待完成 |
| 维护验证主线增量 | [PR #140](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/140) 的准确 Head `c8715ebe534d7453e0222725d50c258e7eb0cfbe`：四项 CI 全通过，审查后合并为上述 main，合并 tree 与测试 tree 一致；澄清向导修复范围、修正 portable host 目录身份，安装副本/实际 EXE 启停证据见 DELIVERY-1 第 7–8 节 | 修正包尚无完整图形安装执行/客户验收，也不是新的正式应用 Release |
| 程序修复主线增量 | [PR #141](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/141) 准确 Head `c04b0938eb90ae3b4b022663d116882307abc793` 的四项 CI 全通过，审查后合并为上述 main，merge tree 与测试 tree 一致；同 Release 程序/Python 修复和 v3 handler、四类完整副本修复/进程退出恢复及真实启停证据见 DELIVERY-1 第 8–9 节 | 合并不等于新客户 Release；该 PR 本身未接图形维护，不包含业务升级/迁移 |
| 图形维护候选 | `codex/delivery-graphical-repair-20261005`，实现 `84e46a1c1a26e0887c5f8dd9989bcd6ca0292695`：Inno 接 v4 程序修复、恢复与只读状态；持久阶段和跨窗口查看，窗口断开不取消后台事务；准确验证及构建见 DELIVERY-1 第 9 节 | 尚待新 PR CI/审查与图形点击验收；不代替历史无身份接管、业务恢复、多跳或标准卸载 |

主线及相关 PR/公开 Release 状态于 2026-10-05 核验；本轮复核 #141 的准确 Head、CI 和影响后合并，未整合维护线整个目录。开始任务应重新核验准确 Base/Head，不能以显示版本号替代软件和数据库身份。客户维护线与主线收敛不是通过修改 `VERSION` 就能解决。

## 2. 已合并主线的实现

| 工作 | 主线合并证据 | 当前范围 |
| --- | --- | --- |
| Runtime 可靠性 | [PR #108](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/108) | 独立 liveness/readiness、降级/退避、进程所有权、阻塞工作隔离及两类画布任务回执基础 |
| 浏览器与路由安全 | [PR #119](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/119)，#111 CLOSED | 未知请求/事件默认拒绝、同源写入、登录限流、跳转/Cookie/静态目录约束 |
| 数据基础复核与接线 | [PR #120](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/120)、[#121](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/121)，#109/#114 CLOSED | Manifest 约束下的备份、版本化前向迁移、目标验证、数据库/指针恢复与不明状态阻断 |
| 升级故障与恢复 | [PR #124](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/124)、[#125](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/125)、[#126](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/126)，#115 CLOSED | 定向故障演练、恢复提示及有审计的恢复核验/解除阻断接口 |
| 更新操作简化 | [PR #127](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/127) | 管理后台一次确认、真实阶段显示、作业记录恢复查看；不是完整多跳协调器 |
| 发布通道选择 | [PR #129](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/129) | 正式/开发版显示和选择基础；兼容性检查仍是必要条件 |
| 旧库迁移保护 | [PR #130](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/130) | 先备份，再登记版本/迁移，失败恢复数据库及代码指针 |
| 准确升级路径 | [PR #131](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/131) | 核验路由声明并规划；非直接可达目标仍阻止执行；未自动跨重启多跳 |
| 统一文档与固定入口 | [PR #137](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/137)、[#138](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/138) | 生命周期设计事实源、固定 C# 薄入口和确定性构建；不是完整维护产品 |
| 安装器接线与入口修复 | [PR #139](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/139) | 同源新装入口、实例身份及共用锁下的入口专用修复；不重置业务数据库和管理员 |
| 安装副本与路径修正 | [PR #140](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/140) | 实际内置 Python 新装/重复安装阻止、入口修复/故障回退、真实 EXE/Supervisor 启停；目录身份修正不放宽 containment 校验 |
| 同版本程序修复与恢复 | [PR #141](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/141) | 外部完整包修复已登记、停止状态的同 Release 程序/Python；独占 lease、启动 fence、自己的计划/结果恢复；不是业务升级或数据库迁移 |

详细实施记录是对应时点证据，不应把它们的旧“未合并”字段再次当作当前状态。

## 3. 发布与现场证据

### 2026-10-08 2026.10.1 维护发布增量

- 负责人批准新维护 Release 后发布 `v2026.10.1@bf1143a7bc54ac24d53b9e7d7db5a9b50da8b57c`，精确基于正式 09.9 的 `54f9e67d1643a313ff7f0aca71d4bf76aa406e32`；PR #144 OPEN、Windows affected-scope CI 137 passed / 6 skipped，不合并 main 或旧维护基线。主线对应修复仍由 PR #143 单独收敛。
- 修复超管真实标签、筛选/统计和更新部署/权限双开关提示；不改账号/密码、初始化、后端写入权限、迁移或 Runtime。标准构建新增版本化同结构的 build-time 选择，但消费协议仍是既有 `same-schema-no-migration`；完整 v2 结构证据及 Runtime 与 09.9 相同，不能误发旧 18 对象快照。
- 正式四资产已重新下载并哈希回验；本地精确 09.9 原更新引擎配真实合成 v2 DB 的 prepare/成功切换/目标启动失败回退通过，逐行数据、配置和素材保留。进程启动结果在此实验中是合成的，不是现场服务启停验收。包内 HTML 的真实 Chromium 桌面/移动检查通过；既有 Tailwind CDN 警告及极长 Windows 路径限制保留。
- 现场阶段 A 报告包 `9531ae134129f1c596b0b84a86651700f3702289ffe438375922e0d819477018` 已回验：仍为 09.9，Aidan02=super_admin，部署更新关闭，功能权限开启，原备份/监控继续。维护包和任务书已准备；没有新的现场窗口，开发端没有启用该设备配置、停止服务或执行升级。
- 精确版本/哈希/兼容性、验证与未完成边界见 [维护发布记录](./ops/MAINTENANCE-2026.10.1-RELEASE-RECORD.md)。以后该安装通过既有统一更新引擎和准确发行资产更新；这一次单跳不等于更新器自更新、无限历史兼容或完整交付闭环已完成。

### 2026-10-08 单设备上线、超管及更新入口增量

- 负责人提供的 v4 报告包 `510a29255b11c742c64c1b1f04d7e2899f69e25d207da5998df966231d94b1c2` 已开发端回验。该旧 TEST 生产部署已接管到 `D:\Infinite-Canvas-Enterprise\install`，09.9 于 10:16:55 开放业务，12 原表保留及实际业务读写检查通过；旧写入者停止。开发端未远程操作生产设备，不能外推为所有旧客户验收。
- 同设备超管修订报告包 `6a27935abd794f2a1449c2a78f7e863c5e907f61af9b7dfdc009391145eb4fe3` 的哈希、成员/CRC、索引大小/哈希及单独报告字节已开发端回验。现场真实登录和成员接口返回 `Aidan02=super_admin`，原密码保留；初始化/审计成功结论成立。此前“页面已显示超管”的验收结论撤回，不重新初始化账号。
- 准确正式 `2026.09.9@54f9e67d1643a313ff7f0aca71d4bf76aa406e32` 的成员页只按 `is_admin` 显示角色，而主线已经有三角色标签、筛选、统计和固定角色保护；这不是重新创建用户的理由。现场更新入口被 `ENTERPRISE_UPDATE_ENABLED=false` 禁用，权限表全局允许不能覆盖部署禁用。对应新提示尚未发布给该设备。
- 本轮分支 `codex/admin-update-guidance-20261008` 基于上述 10-08 主线：复用现有三角色能力并补真实行级脚本/浏览器回归；角色徽标保持单行；只读授权接口补充部署/权限开关及拒绝码，保留旧组合字段；页面分别说明角色不足、部署禁用和权限开关禁用，刷新失败隐藏危险动作。不改变服务端权限、数据库结构、用户/密码或现有 Release 资产。
- 本轮本地验证：CI 指定的 Python 3.11 下 38 项受影响范围检查通过（API 授权原因、真实成员脚本、文档契约和 APP_ROOT 写入审计）；Chromium 在本地合成数据页面的桌面/手机视口通过角色行、筛选、两类开关提示及只读检查交互，未调用升级写入接口。浏览器插件不可用，采用现有 Playwright；无页面 JS 错误，既有 Tailwind CDN 警告保留。该证据不是生产登录、真实升级或长期崩溃验收。
- [现场启用更新入口任务](./operations/ONSITE-ENABLE-UPDATE-ENTRY.zh-CN.md) 是此前只启用配置、不执行升级的两阶段任务。新 2026.10.1 维护包已独立发布，合并范围的现场任务书随维护交付；仍不沿用过期窗口。当前已提供现场证据只证明业务继续使用 09.9，不能把 main 文件拷贝进生产或把新发布误写成现场已完成。
- 现场 15 分钟版本化备份及每分钟监控已接续，但依赖 Windows 账号登录，原监控 10-12 15:49:40 到期；不能恢复旧快照丢失开放后新数据，不承诺新旧实时双向同步或任意无损降级。普通账号登录、长期实流量崩溃稳定性仍待现场证据。

以下为其他设备的历史反馈，不覆盖全部客户，也不是本轮远程实测。

- 客户设备 `09.4→09.5` 在线升级成功；项目负责人报告普通画布生成正常。
- 测试设备 `09.5→09.6` 在线升级成功，并确认登录、已有画布和图片可用。
- 同一测试设备的 09.6 数据库为已激活安全治理的 28 对象结构；旧页面直接到 09.8/09.9 被 `SYSTEM_UPDATE_DATABASE_SOURCE_IDENTITY_MISMATCH` 阻止。只读结构/资产核验通过，不是数据库损坏，也不能删除审计对象解决。
- 项目负责人执行受控桥接后，报告 `09.6→09.9` 作业 `SUCCEEDED`，后台显示准确 09.9 Release。这是一个已核准安装的结果，不覆盖所有旧版本或客户。
- 最近通用 EXE 截图显示对已到 09.9 的安装“只读检查通过”。尚未收到完整的图形升级、固定入口启停/重启和异常恢复现场验收；不能把只读通过写成全部完成。
- 09.9 已发布真实改表目标；旧文档“尚无 schema-changing 正式 Release”已过期。但来源、路径、数据保留和恢复仍按设备/安装状态分别核验。

开发端没有连接客户设备、迁移客户数据、执行付费模型调用或开启云端数据上传。上面的实际生产迁移/启停来自现场报告，不是开发端操作。

## 4. 通用工具的当前支持边界

PR #136 的历史目录已登记 10 个准确 Release：08.1、08.2、08.3、08.4、09.4、09.5、09.6、09.7（开发）、09.8、09.9。其中 **9 个旧来源**用于到固定正式目标 09.9 的升级矩阵；09.9 是已达目标时的固定入口核验/补装，不是第十条升级跳转。

资格还取决于完整程序/运行环境/Manifest 与数据库结构：旧来源的 18 对象基础结构，或完整定义及治理状态符合的 28 对象变体；目标 09.9 核验 30 对象及版本元数据。不能以对象数量单独判定。缺少完整公开资产的 08.5 现场版、被修改的代码、未知结构或未完成恢复应阻止并诊断。

这表示“经核验历史基线共用实现”，不表示任意版本、任意热修或无限年限可跳转。当前工具固定目标 09.9；更新器自更新、任意后续目标、目录长期扩容与自动多跳仍待统一交付实现。目录和测试来自维护分支，不应在 main 中寻找并误判其已合并。

## 5. 当前阶段与关键缺口

当前处于 **阶段 3：统一安装与在线升级体验收敛**。阶段 1 安全及阶段 2 数据基础已有合并成果，不表示其所有长期加固和所有客户迁移都已验收。

1. **交付分叉与安装维护**：固定入口、安装接线、#140 验证/路径修正及 #141 同 Release 程序/Python 修复已选择性回归 main，维护线整体仍未合并。新装、入口修复和程序修复已有真实内置 Python/EXE 副本证据。图形维护候选已接 v4 修复/恢复/状态与跨窗口阶段，不升级业务版本、不接管无身份历史安装，尚待自身 CI/审查和图形点击验收。`Uninstallable=no` 仍未改变；标准卸载、入口旧锁恢复、维护缓存容量/拥有者限定清理及客户验收仍待完成。不能把程序修复称为全部修复/全版本升级。
2. **长期更新**：当前路由目录最多最近 50 个 Release、规划最多 8 跳；一次授权跨重启多跳、更新器自身接管、维护通知、业务写入隔离及图形恢复仍不完整。正式版不以开发版作为必经站。
3. **权限使用问题**：旧安全治理未激活时的 `TRANSITIONAL_POLICY_DENIED` 403 有真实反馈；不能放宽授权来“修好按钮”。需在准确新装/接管状态复现管理员授予/撤销及操作授权并完成前后端回归，尚无所有客户修复通过的证据。
4. **可靠任务与费用**：#123 未合并；当前回执基础不等于统一持久任务、费用账本、预算或对账。“未提交暂停、已受理继续查、未知待对账”是已确认实施规则，不是旧内存任务已可恢复的声明。
5. **资源与桌面**：完整 CAS、持久缓存、员工桌面客户端尚未交付。固定 EXE 启停入口不能代表完整桌面产品。
6. **规模与部署**：当前业务是 SQLite＋文件/JSON 的单机/LAN 部署。团队服务端 PostgreSQL 是目标；单机 SQLite 长期保留，员工端未来仅保存缓存/设置。不以用户数猜测容量，不支持把 SQLite 共享网络盘当多节点 HA。
7. **企业集成与诊断**：SSO/目录、Agent 委托、可选远程诊断采集未交付；云资源、遥测授权及协议未落地。
8. **签名和支持期**：没有付费 EXE 签名预算，不把签名或干净独立设备作为前提；未签名风险仍披露。支持年限、资产/备份保留政策和磁盘预算待明确。

## 6. 任务关联与后续边界

| 入口 | 当前状态/下一动作 |
| --- | --- |
| #109、#111、#114、#115 | 已关闭，保留合并和测试证据，不重新包装为待开始任务 |
| PR #136 | 维护线 Draft，CI 已通过；审查、图形/固定入口定向验收、主线差异收敛是下一阶段输入 |
| PR #137 / #138 / #139 / #140 / #141 / DELIVERY-1 | 文档、固定入口、安装接线、维护副本/路径修正和程序修复/恢复已合并；新图形候选先完成自身 CI/审查及图形操作验收，再补维护缓存、入口旧锁恢复和保留数据卸载，不整分支覆盖 |
| PR #123 / #110 | 止损 PR 待审查合并；持久任务仍待实施，不扩大付费测试 |
| #112 / #113 / #116 | 可观测性、浏览器/Provider 闭环、策略模块化仍 OPEN，随相应阶段推进 |
| #117 | GitHub 旧标题仍为签名/干净 Windows Gate B；与已批准政策不一致，需后续协调其范围，本轮未修改 Issue |

下一步任务的顺序、进入/退出条件只在 [路线图](./roadmap/DEVELOPMENT-ROADMAP-2026-2027.md) 维护。统一交付规则只在 [ADR-DELIVERY-001](./decisions/ADR-DELIVERY-001-UNIFIED-INSTALL-UPDATE-LIFECYCLE-2026-10.md) 维护；本文只记录“到哪里了”。

## 7. 本轮核验来源与证据边界

- GitHub main、PR #123/#136/#139 与 Release：2026-10-05 API/CLI 核验；工具目录/实现仍由各自准确工作树说明。
- [PR #136 历史升级/固定 EXE CI](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/36767107026) 与 [桥接 CI](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/36767106957) 均通过；[#123 CI](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/35833836185) 通过，但两个 PR 都未合并 main。
- 现场部分来自项目负责人此前提供的日志、只读 JSON、截图和使用反馈，本轮未重做现场测试。CI 回调、安装副本、独立 HTTP 启动、真实 Supervisor 与客户操作分别报告。
- 本轮文档整改及其检查不是业务功能验收；整改记录见 [DOC-3](./ops/DOC-3-DOCUMENT-SYSTEM-AUDIT-2026-10.md)。不得据此新发应用版本或扩大生产批准。
- 2026-10-05 复用 #137 的 [Documentation CI](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/37045196365) 与 [Enterprise/Runtime CI](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/37045196234)；#138 的 [固定 EXE CI](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/37256319194)、[Enterprise/Runtime CI](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/37256319206) 和 [Documentation CI](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/37256319231) 均通过。重定基线时确认 Git 合成 tree 与已测试 tree 相同，再合并；未手动重跑旧 PR 全套门禁。
- #139 准确 Head `2bad146d39a08f8bf744633baa3a1a993b85d692` 的 [Documentation CI](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/37261511743)、[Enterprise/Runtime CI](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/37261511722)、[固定 EXE/安装接线 CI](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/37261511699) 全通过；审查后核对 merge tree 与测试 tree 相同，再合并，未手动重跑旧 PR 全套门禁。
- DELIVERY-1 第 6 节所引旧安装接线测试只执行身份核验；本轮额外构建干净完整候选包，以实际安装 handler/内置 Python 和临时数据库验证新装、重复安装阻止、入口修复及故障回退。修正目录身份传递后，实际根 EXE 的 start/health/status/stop 通过，Gateway/Upstream HTTP 200、进程退出及端口释放得到核验。向导浏览到准备页即取消，不执行 GUI 安装或改变登记；未连接客户设备。准确构建身份、复测和限制见 DELIVERY-1 第 7 节。
- #140 准确 Head 的 [Documentation CI](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/37276623880)、[Enterprise/Runtime CI](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/37276623886) 和 [原生/安装检查](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/37276623710) 全通过。只读补丁影响审查后合并，未额外重跑旧 PR 全套门禁；新修复候选不能借用这些 CI 作为自身通过证据。
- #141 准确 Head 的 [Documentation CI](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/37284812060)、[Enterprise/Runtime CI](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/37284812091) 和 [原生/安装检查](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/37284812161) 全通过；只读风险审查后按准确 Head 合并，未手动重跑旧 PR 全套门禁。新图形候选的验证是另一个范围，见 DELIVERY-1 第 9 节，不能借旧 CI 宣称通过。
