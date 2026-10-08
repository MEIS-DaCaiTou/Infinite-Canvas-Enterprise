# 开发基线对齐与文档收口记录（2026-10-09）

本文是本次整合的固定证据和运维参考；当前状态只由 [CURRENT](../CURRENT_PROJECT_STATUS.md) 维护，任务顺序只由 [路线图](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md) 维护。它不授权操作生产、运行历史任务书或发布新版本。

## 1. 范围与准确来源

- main 基点：`309b35fb41956bd457d009cd54762bb647db15a3`。
- 正式 10.1 维护来源：`bf1143a7bc54ac24d53b9e7d7db5a9b50da8b57c`，PR #144；合并基点 `ee4281022d01f50bb75c2609009bd329c2cc6aa6`。
- main 兼容的页面/API 移植来源：PR #143，`0f79ff2489ed28a4755d9a3c9f29e7a83fe13a6a`。
- 10.2 诊断候选：PR #145，`83e18c44357ec491dced0d6ba70bc4e691e420e1`；不纳入本次整合、不发布。
- main 与维护线分别有 62/24 个分叉提交，整目录差异 159 文件。不能整体覆盖或仅改 VERSION。

本轮使用隔离工作树 `codex/development-baseline-closeout-20261009`，保留原配置 checkout 和其他工作树未提交内容。后续通用开发/构建以收口后的 main 为唯一基线；已发布版本继续从冻结 refs/准确资产追溯。

## 2. 源码差异处置

| 项目 | 处置 | 原因/保护 |
| --- | --- | --- |
| 后台三角色标签、统计、筛选 | 保留 main 的角色治理与 UI，补标签宽度/不折行 | 10.1 的成员写入接口不同，不覆盖 main 的管理员边界 |
| 更新 access/拒绝提示 | 移植 main 兼容版本；保留旧字段，加独立部署/功能开关及拒绝码 | 角色→部署→功能/权限裁决；刷新失败危险操作先关闭，不自动 execute |
| 数据库 v2 登记 | 接回已发布的 `ice_096_security_schema_v2`（1→2）与事务初始化 | 不在普通应用启动中自动迁移，不放松源库身份检查 |
| 发布构建 | 接回三种构建模式；统一默认与明确维护模式均产出正式 v2 evidence | 保持 wire contract；不让主线旧标记生成无版本/v1目标覆盖生产 v2 |
| Greenfield | 重新核验已 materialize evidence 的哈希，按受支持 v1/v2 初始化，再核对结构/版本/账本 | 保留固定 EXE、实例身份、密码长度、原子发布、pointer-last 及本次拥有者限定恢复 |
| 恢复核验 | v2 使用实际 canonical schema 哈希和元数据核验 | 严格保留 schema_id 对齐、完整性/外键和未版本化对象比对，不放松来源 |
| Runtime health/supervisor | 两线字节相同，保留 main，无重复移植 | 本轮没有新的启动/退出算法，不能声称修好现场根因 |
| 浏览器隔离、CanvasTaskJournal、修复 lease/fence、只读恢复查询 | 原样保留 main | 不删除主线较新的安全、任务和维护能力 |
| 特定 09.6 28 对象桥接、固定历史目录/工具 | 留在冻结维护来源；普通更新不默认开启 | 特定接管证据不是任意来源的兼容承诺 |
| 10.2 候选诊断 | 独立待验证 | 不借 10.1 的成功结果给候选背书 |
| 旧交接/重复规划文档 | 不复活；复用当前权威体系 | 不恢复 AGENT_CONTEXT/HANDOVER 等第二份任务队列 |

main 的 `VERSION=2026.08.5` 历史标记本轮不变；这不是生产版本，也不是允许用新主线重建旧客户包的声明。下一次发行需独立选定准确版本、commit/tree、完整资产及 source/target 路由，不自动发布 10.2。

## 3. 数据契约闭包

统一 v2 fixture 与正式 09.9/10.1 的固定身份：

- 30 对象、schema version 2；
- 对象 SHA-256：`cd8790a1ef22a97b96c76105b26f14c309ed02396249ab97d36034bb88d25284`；
- registry SHA-256：`34dedc0c49d4cb4b9f69231bdcbe24a3ebb49fb04199544aab531d7602fc7774`；
- versioned migration IDs：`["ice_096_security_schema_v2"]`。

`same-schema-no-migration`（默认）和 `same-versioned-schema-no-migration`（明确维护构建）均输出 v2，后者的 wire 仍为同结构/code-pointer；`versioned-forward-migration` 使用同一受审 registry 与明确 database-backup-restore 分类。该参数是构建选择，不提供路由授权，也不让数据库与 Manifest 不匹配的来源通过。

旧 v1 已验证 evidence 的 Greenfield 回归保留；无版本或未知 evidence 拒绝新装。原维护线的历史 unversioned 包须从冻结 ref 重建，特殊旧部署仍走单独接管，不在此处扩展许可。

## 4. 本轮验证

- 页面/更新/安装/入口/数据定向组：**129 passed / 1 skipped**。包含真实 HTML 脚本回归、权限矩阵、v1/v2 Greenfield、evidence 篡改拒绝、固定入口保护、迁移/恢复及默认 v2 契约。skip 为明确平台条件，不计通过。
- 资产/恢复/主线用户治理/程序修复/静态受影响组：初次 **159 passed / 4 skipped**，另一个写入指纹用例揭示构建移植后的指纹变化；审查 467 个写入点均映射、无新未覆盖点后刷新摘要，该用例单独复验通过。没有删除审计或放宽规则。
- v2 evidence 与上述正式 hash/registry 固定值一致；同结构更新 prepare 在临时 fixture 上通过，并验证源数据库字节不变。
- Chromium 内核现有 Edge + Playwright **1.62.1** 隔离渲染：`127.0.0.1` 随机端口、1440×1000 / 390×844，实际 admin HTML + 本地合成 API。Browser plugin 不可用，默认 Playwright 浏览器未安装，因此使用现有 Edge，不安装依赖。
- 页面身份/非空、无框架覆盖层、三角色显示、超管保护行、角色筛选、部署禁用/功能禁用/允许只读检查、权限刷新失败关闭危险按钮均通过；**0 升级写请求、0 未处理 JS 错误**。注入 503 是预期失败测试，既有 Tailwind CDN 警告保留。成员表/页签的既有横向滚动不在本次重设计。
- 本地截图/临时脚本在产品外 artifact 根，不入 Git、不接生产或付费 Provider。GitHub 自动 CI 与 PR 审查结果由承载 PR 保存，不复用旧 PR 的 CI 冒充本次通过。

以上是源码/fixture/渲染证据，不是完整干净发行包、真实升级启停或生产长期稳定性验收。本轮没有触碰任何客户服务、配置、账号、数据库和已发布资产。

## 5. 最新现场结果的证据边界

负责人提供的两个 ZIP 经只读哈希核验：

| 文件 | SHA-256 | 能证明的范围 |
| --- | --- | --- |
| update-diagnostics.zip | 9b410f058cfc685b2b05954485cae7fd993189c4363a335746dc9e6de1ebbfb8 | 2026-10-09 01:49 导出时的 10.1 Runtime、作业成功和有界日志 |
| canvas-native-20261009-015017.zip | 16b4ee974d775cc1ce797a8791dd791f34f6883fb116b07b999ba2e91e1bb608 | native worker 返回 0 的摘要，不是完整 lifecycle 记录 |

生产成功作业源 09.9/目标 10.1，创建北京时间 01:45:33，成功 01:46:41；EXE 手动停止/启动时间约 01:41:16/01:41:51。采集显示 Runtime healthy、三个进程新身份、Gateway/Upstream HTTP 200、计数 0；并非当前仍实时保持健康的远程确认。

仍记录 `graceful_timeout`、拥有者释放而 Supervisor 退出确认 false。82 条空 Broadcast error 与 4 条图片比例 Provider 错误缺各自时间，不能断言是新版本崩溃。此前两次失败缺错误阶段/errno，继续保持 not_recorded；成功不能补猜根因。

## 6. 运维收口与后续规则

1. 已上线 10.1 继续使用；从固定根 EXE 操作，由更新中心走明确正式路由。开启入口不自动触发升级，普通管理员不能代替 super_admin。
2. Aidan02 身份/密码保留，不再创建替代超管或重新 bootstrap；不再拷贝单个 HTML/Python 到不可变发行目录。
3. 正式更新前确认实际 source、目标完整资产、路由、数据库证据、活动任务与最新一致性备份；窗口内由共用 Runtime 更新。失败按可证明的版本/数据身份恢复，未知状态保留阻断，不能删锁试错。
4. 业务开放后产生的新数据不能被升级前备份覆盖；没有新版/旧 TEST 双向同步或任意无损降级能力。回退只能按兼容性和当前数据的独立方案设计。
5. 原版本化 15 分钟备份、每分钟监控至 10-12 15:49 的成功记录来自此前现场；登录依赖仍在。10.1 之后的调度接续需要实际结果，不能仅因健康接口 200 写成已确认。监控应解析实际指针/Release/进程身份，不固定旧 PID/旧程序路径。
6. 下一步在统一基线补诊断并复现真实升级、目标启动、失败自动恢复；不新增全盘盘点、不扩大付费模型实验、不自动部署候选。维护窗口与现场操作另行批准。

