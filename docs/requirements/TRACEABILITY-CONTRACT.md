# 需求追踪规则与来源登记

日期：2026-10-09。状态：DOCS_ONLY_DRAFT_PR / NOT_A_TEST_RESULT。

本参考文档服务于唯一需求入口 [PROJECT_SCOPE_LOCK](../../PROJECT_SCOPE_LOCK.md)，不成为第二份路线图/任务队列。决定登记见 [REQUIREMENTS-DECISION-REGISTER](../decisions/REQUIREMENTS-DECISION-REGISTER.md)。

## 1. 三个独立状态轴

| 轴 | 枚举/含义 |
| --- | --- |
| 需求确认 | CONFIRMED：所述原则已确认；PARTIALLY_CONFIRMED：方向/原则确认但所列细则未批；PENDING_CONFIRMATION：具体政策/设计待确认；PROJECT_BASELINE：现行工程基线约束 |
| 实现 | IMPLEMENTED：仅 verified_reuse 指明的基础已经实现；PARTIAL：已有基础而 remaining_gap 尚缺；NOT_IMPLEMENTED：所述新能力未实现；NOT_VERIFIED：没有该独立产品完成证据，不能猜为已完成/全部未做 |
| 实施授权 | 本次只准 Docs-only 编写/提交 Draft PR；NO_NEW_BUSINESS_IMPLEMENTATION_AUTHORIZATION 不否定已有工程诊断授权，也不产生业务开发许可 |
| 场景范围 | KEEP_CORE / REWORD_SUPPLEMENT / POLICY_PENDING / LATER_STAGE：82/10/9/3，不是成功/失败或实施排期 |
| 场景执行 | 本次全部 NOT_RUN；代码能力、历史定向测试、CI、正式 Release、客户反馈必须另外给准确来源，不能替换执行列 |

INDEPENDENT_PRODUCT_OUT 是产品范围，不是删除已有能力。历史行的 PARTIAL 可以描述 retained_contracts/verified_reuse 中的已有基础，绝不表示被移出的独立产品进入施工或已交付。原 P0/P1 是输入包候选风险标记（84/20），不是新正式任务优先级。

## 2. 三张表的列契约

- [REQUIREMENT-TRACEABILITY.csv](./REQUIREMENT-TRACEABILITY.csv)：14 行，原 BR ID/题意/旧决策状态和原场景关系留存；confirmation_status 与 implementation_status 分开；test_ids 是本轮完整回链，draft_refs 仅链接未批准 N37 草案。
- [ACCEPTANCE-SCENARIOS.csv](./ACCEPTANCE-SCENARIOS.csv)：104 行，原 id/domain/scenario/expected/evidence/priority 六列逐字保留。原 evidence 是“预期取证方式”，不是执行结果。current_scenario/current_expected 承载修订，scope_reason 记录范围原因，policy_refs 不把未决变已批。
- [HISTORICAL-PLAN-MAPPING.csv](./HISTORICAL-PLAN-MAPPING.csv)：37 行，原编号、准确题名、原文行号与标题中的历史标签保留。original_heading_label 不是今天的实现状态；当前 scope/implementation/授权单列。源码证据固定到核查 main，不把 PR/Release/现场混用。

列表使用分号分隔、UTF-8、RFC 4180 双引号字段；行按原 ID 顺序。BN 字段中的括号仅说明承接/最小契约范围，不改编号。N30/N31/N33 关联表示保留基础，不让移出独立产品复活。历史表的 N37 场景仅是共用契约基础，不能充当 Connector 专项覆盖。

原 48 条唯一场景挂接全部保留；56 条未挂接场景现在 GAP_FILLED。每个场景有 primary_br 及至少一个 br_ids；BR.test_ids 由同一关系逆向生成，禁止出现正向有而反向没有的关系。一个场景可覆盖多个 BR，但不能只为统计给所有场景挂万能 BR-SYS-01。

## 3. 104 个场景范围冻结

| 类别 | 数量 | ID/边界 |
| --- | ---: | --- |
| KEEP_CORE | 82 | 除下面三组之外的原 T001—T104 |
| REWORD_SUPPLEMENT | 10 | T013、T025、T026、T027、T032、T033、T034、T036、T043、T064 |
| POLICY_PENDING | 9 | T049、T050、T051、T057、T062、T063、T065、T070、T080 |
| LATER_STAGE | 3 | T084 多 Worker、T095 对象存储、T104 员工端缓存 |

删除 0、原 ID 改号 0。十条改写分别去除未批分类前提、明确验收与发布、固定 Bundle 引用而不强制物理去重、补在线撤销与离线 PS 副本边界。九条政策待定仍保留默认拒绝/许可/审计/真实费用等安全边界。三条后续工程不取消单机幂等、稳定 ID 或在线撤销基础。

原 104 条没有完整的跨工具/PS 写回专项验收。N37 新候选仅采用草案语义标签；不得自动生成 T105 等正式 ID，也不得宣称 104 条已覆盖 N37 全部链路。

## 4. 来源登记：原始证据不回写

| 来源键 | 准确身份 | 使用边界 |
| --- | --- | --- |
| SRC-PACK | Infinite-Canvas-Enterprise-Full-Requirements-Handoff-2026-10-09.zip；SHA-256 ac25c0b5597c96e214a3e4f8fbe42c9635679e6d4a56743ebc2499ac9db9fbc2 | 原 21 个成员/14 BR/104 场景/37 行模板，原包不改；输入包指令不单独构成执行授权 |
| SRC-PLAN | 无限画布企业版_新版完整开发规划_2026-10-07.md；SHA-256 5935b00dbcf4cbcd53bcee2de0a7301109641e6727a263c1f82f7dc7406b26d6 | 原文历史设计，不整份视为获批；L133—L407 标题位置从原文逐项核对 |
| SRC-SCOPE-REPORT | 37项历史规划范围修订与需求基线调整报告.zh-CN.md；SHA-256 d6561ff924caa369258a4c1eec82010d8d24874019da771412311d5e79dff048 | 负责人已认可范围分析，不是业务实现或生产验收 |
| SRC-SCOPE-APPENDIX | 验收场景范围影响附表.zh-CN.md；SHA-256 7e0319884e4bdbe216f3bed2e4f883cc2362aa5f53a6e67b28ac83fc47ce20a7 | 82/10/9/3 分组与原场景对应，不是 104 次执行记录 |
| SCOPE-2026-10-09 | 本项目负责人 2026-10-09 范围确认及本轮 Docs-only 授权 | 高于原包未决“是否保留核心模块”；不批准其他未决政策或合并/开发 |
| SRC-MAIN | main@a5a6aa10b7882c46f129ec6df854239ee111da18 | 当前源码核查快照；之后变化需更新证据，不把 Draft Head 当 main |
| SRC-ENGINEERING | [#148](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/148)，Head 10990775d37ee28e8d4dfd3f9893135538ed3c2f | Draft，真实固定 EXE 演练失败；绿灯 CI 不是完整闭环通过 |
| SRC-RELEASE | [v2026.10.1](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/releases/tag/v2026.10.1)，bf1143a7bc54ac24d53b9e7d7db5a9b50da8b57c | 已发布资产不改，不等当前 main 或通用生产批准 |

原始文件保留在负责人提供的 Downloads 与仓库外 requirements-intake 证据目录；仓库只保存身份和受控修订，不把原 ZIP/生产数据复制进 Git。首轮 REPORT.zh-CN.md、MAPPING-AND-COVERAGE.zh-CN.md 也保持原状；旧报告中的待审范围由新决定覆盖，不原地美化。

包内 C0—C10 审查分组不变成正式排期。原 N34→N33 见历史原文 L381；N33→N31/N34 在 L369；N31→N33 在 L343；没有 N34→N31 的直接依赖。当前无环关系只见范围入口及 N37 草案。

## 5. 本次文档核验与未验证边界

验收本次文档变更时应分别核对：

1. 37 原编号/准确题名/历史行号，无重复；14 原 BR ID 无改号。
2. T001—T104 唯一、原六列与原 CSV 完全一致；82/10/9/3、84/20 风险来源一致。
3. 104 个 primary_br/br_ids 均有效，BR 反向挂接一致；保留全部旧关系并填 56 条缺口，未映射 0。
4. 确认/实现/实施授权/执行四种信息不混淆；未决政策不自动确认。
5. N37 下位需求标为草案，已有基础与工具专项候选分开；没有新增正式 T ID。
6. 文档登记、链接及冻结原始证据未改；diff 仅文档，正式路线图、源码、数据库与发行资产不动。

CSV 使用表格工具解析、写入与往返核验；运行时原文件哈希另行核对。仓库 tools/check_docs.py 和文档契约单测覆盖 Markdown/text 登记、断链/重复权威和冻结文档，**不验证 CSV 语义**；三张 CSV 作为登记表的 tabular_resources 由本次额外定向核验，不虚称已有 CI 已校验全表。

本次没有执行 T001—T104、真实 Photoshop、付费 Provider、客户登录/生产复查、升级/恢复演练。历史测试仅证明原先有限实现，不能替新部门/版本/工具接口测试。
