# N37 多模态与跨工具资产联通：下位需求与接口契约草案

日期：2026-10-09。状态：DRAFT_CONTRACT / BUSINESS_IMPLEMENTATION_NOT_AUTHORIZED。

N37 方向已经确认，下面详细接口、字段与政策尚未批准。需求范围只认 [PROJECT_SCOPE_LOCK](../../PROJECT_SCOPE_LOCK.md)，实施顺序只认 [正式路线图](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md)。本文件不创建新任务队列/表，不把草案 API 描述成现有接口。

## 1. 最小目标、复用与现状

经典画布、智能画布、素材库、AI 工作流和 Photoshop 共用 Asset/具体 AssetVersion/来源/operation 许可。B17 管资产身份、字节及引用边界，N34 管工作/冻结/正式版本及来源，B20 管工具适配。N29 在部门工作场景提供项目/任务/固定规格；B13/B14/B16 只在执行/付费路径接线。

N34 的底层版本不等待独立 N31/N33 或整个 PS 产品。跨工具回写先产生工作版本，再可进入 N29 提交/验收和负责人发布；这是数据流程，不构成“验收等 N37、N37 又等验收”的工程循环。

| 已有代码 | 可以复用 | 不能声称已完成 |
| --- | --- | --- |
| [sources.js](../../tools/photoshop-asset-connector/js/sources.js) / [net.js](../../tools/photoshop-asset-connector/js/net.js) | 素材/本地/画布列表、字节下载、上传及素材新增；canvas adapter 当前 editable=false/exportTarget=null | 稳定业务 AssetVersion、企业登录/配对、直接 PS 回写画布节点、原子归档 |
| [ps.js](../../tools/photoshop-asset-connector/js/ps.js) | 置入智能对象、副本文档/图层 PNG 导出 | PNG 不等可编辑 PSD/PSB，不能宣布原生源文件往返已支持 |
| [generate.js](../../tools/photoshop-asset-connector/js/generate.js) / [agent.js](../../tools/photoshop-asset-connector/js/agent.js) | 已有生成、查询与聊天，继续保留 | 本地 jobs/localStorage/X-User-Id 不是企业认证、持久 Attempt 或费用账本 |
| [socket.js](../../tools/photoshop-asset-connector/js/socket.js) / [Gateway](../../enterprise/gateway.py) | 刷新/重连、HTTP cookie/Bearer、服务端重建身份及 WS 边界 | UXP cookie/Origin 与 HTTPS/可信反代兼容未实测；不得放宽 Gateway 或直连 Upstream |
| [main.py](../../main.py) 的 canvas_assets_index/list_canvas_assets、workflow 导出/导入、update_canvas | 两类画布资源索引、JSON/ZIP 包、依赖映射、可选旧写 409 | 当前 URL/索引/可选 base_updated_at 不是业务版本/许可/发布合同 |
| [resource_index.py](../../enterprise/resource_index.py) / [journal](../../enterprise/canvas_task_journal.py) | 资源查找缓存、受理/中断记录与现有任务查询 | 缓存不是持久授权/引用/GC 账本，部分回执不是完整成本/来源恢复 |

核查基点为 SRC-MAIN，未实测 Photoshop。新增适配不得重建现有生成/聊天；泛化上传失败 fallback 不能吞掉 401/403 或不明结果后重复提交。以下契约是如何补缺口的草案，不是本次实现。

## 2. 下位需求草案与追踪命名方案

采用 DRAFT-N37-语义名 作为本文临时引用，不登记为新的正式 BR 或 T 编号。若获准实施，建议正式下位需求命名为 N37/<semantic-slug>，专项场景命名为 N37/<semantic-slug>/<condition>；是否采用此命名、是否进入统一 T 序列及正式 ID 由负责人/独立审查确认。

表中的已有 T 只验证共同基础，不能代替尚未编号的工具专项候选：

| 临时下位需求 | 最小业务/接口要求 | 关联 BR | 复用原 T 基础 | 新场景语义建议（无正式编号） |
| --- | --- | --- | --- | --- |
| DRAFT-N37-AUTH | 企业认证用户/安装与工具会话绑定；服务端身份权威；禁用/过期后拒绝新请求 | BR-AST-02 / BR-PRO-01 | T004/T087/T089/T090 | auth/session-expired；auth/forged-identity；auth/uxp-http-ws |
| DRAFT-N37-SOURCE | classic/smart/library/workflow/PS 解析同一资产和精确源版本，许可/哈希/媒体描述不漂移 | BR-AST-01 / BR-AST-02 | T035/T037/T040/T059 | source/cross-surface-resolution；source/new-head-keeps-fixed-input |
| DRAFT-N37-DERIVE | 平台内受控派生新工作副本，不扩展私人来源或外部导出，不覆正式版 | BR-DER-01 / BR-AST-02 | T013/T053/T054/T058/T061 | derive/published-version-only；derive/private-upstream-denied |
| DRAFT-N37-PS-WRITEBACK | PS 编辑输出登记新的受管理工作版本及准确源链；原正式版字节/ID 不变 | BR-AST-01 / BR-DEL-01 | T028/T035/T053 | writeback/new-work-version；writeback/formal-version-unchanged |
| DRAFT-N37-IDEMPOTENCY | 同 actor/scope/operation/key + 相同 payload 返回同一次操作/版本；改 payload 拒绝复用；不明结果先查 | BR-AST-01 / BR-AI-01 / BR-COST-01 | T023/T044/T076/T085 | writeback/duplicate-commit；writeback/timeout-then-status |
| DRAFT-N37-CONFLICT | 校验目标工作头/来源固定版；并发不静默覆盖，不自动合并正式资产 | BR-AST-01 / BR-AST-02 | T024/T054/T059/T060 | conflict/stale-work-head；conflict/source-advanced |
| DRAFT-N37-COST | 本地复制/编辑无新 Provider 生成费；生成身份/费用快照与 Attempt 分离；UNKNOWN 不重付费 | BR-AI-01 / BR-COST-01 | T055/T056/T071/T072/T075/T081/T086 | cost/local-edit-no-generation；cost/unknown-attempt-query |
| DRAFT-N37-LICENSE | 每个源/目标/操作核许可、保密、导出；派生不减限制，外部交付政策另批 | BR-AST-02 / BR-CLASS-01 / BR-DER-01 | T049—T052/T057/T058/T064 | license/no-export-by-derive；license/revoked-online-external-copy |
| DRAFT-N37-RECOVERY | 字节暂存/哈希/依赖/DB 登记可查询恢复；不假 READY、不覆旧版、不误删保留材料 | BR-DATA-01 / BR-UPD-01 | T029/T030/T091/T092/T094/T096—T099 | recovery/blob-without-record；recovery/disk-full；recovery/new-format-update |
| DRAFT-N37-LINEAGE | 来源边、操作者/工具、版本、操作/提交/发布/执行关联可审计；查询不泄漏私人内容 | BR-AST-01 / BR-OWN-01 / BR-COST-01 | T061/T073/T079/T103 | lineage/cross-tool-correlation；lineage/redacted-upstream |
| DRAFT-N37-CAPABILITY | 模态/格式/工作流依赖与工具能力明确；不虚构 PS 支持全部视频/音频/工作流编辑 | BR-DEL-01 / BR-AST-01 | T026/T027/T031/T032/T033 | capability/png-vs-native-source；capability/dependency-secrets；capability/unsupported-mode |

已确认 N37 核心方向不再询问；上述细节需合同审查与后续具体实施授权。原 104 场景 ID 均不变，本草案没有新增正式场景编号或测试结果。

## 3. 最小业务对象与不变量

逻辑对象建议，不指定新 SQL 表或物理存储实现：

- AssetRef：稳定资产标识、具体 source_version_id、模态/格式、字节哈希及 Bundle/依赖引用。URL 只作受控传输定位，不能是永久授权或版本身份。
- WorkingVersion：actor 的合法目标工作空间/项目、父工作头、固定来源版本集合、操作/工具元数据；不复用正式版本 ID 覆写字节。
- SourceContext：已授权来源/许可快照与可见字段。能够查来源 DAG 不能读取全部上游私人内容/提示词。
- TransferOperation：operation_id、幂等 key、payload_digest、准备/字节/登记结果、correlation_id 和可恢复状态。名字/状态枚举是草案，不宣称仓库已有这些字段。
- OptionalBusinessContext：work_item_id/规格版/提交引用只在真实业务任务存在时记录；服务端检查所属部门/付款主体，不接受客户端自报为权威。

权限在 resolve/read、derive、prepare/upload、commit、submit、publish 与新执行请求各自校验。发布只授具体版本，旧源新头不自动继承许可。无匹配身份、许可、来源或恢复状态时不返回成功。

## 4. 最小逻辑接口草案

下表是共享 facade 的逻辑操作名，不是现有 REST 路径、正式 error-code 注册或本次要创建的 API。B20 工具 adapter 负责绑定现有读/写接口；业务版本/来源登记由共用契约处理，不能做 PS 私有旁路。

| 操作 | 必需输入（身份由服务端建立） | 返回/不变量 |
| --- | --- | --- |
| asset.resolve | source asset/version、surface/node 引用、operation 意图 | 授权后的具体版本、能力、受限字节描述；不枚举无权对象/秘密 |
| version.derive | 固定 source_versions、合法 target scope、幂等 key、可选业务上下文 | 新工作版本/固定来源边；不自动授权 execute/export/publish |
| transfer.prepare | 新工作目标、媒体格式/长度/hash、依赖清单、base working head、key/digest | operation_id/暂存许可；不是 READY，不覆盖正式版 |
| transfer.commit | operation_id、已验证字节/依赖、期望工作头、完整性摘要 | 受管理新工作版本/来源/操作结果；缺字节/旧头冲突不能假成功 |
| transfer.status | operation_id/key、当前合法 actor/scope | 当前准备/完成/需恢复结果；重复查询不提交新版本或新付费任务 |
| version.read | 具体版本、read/export 意图及当前授权 | 当前允许的字节/预览；导出许可独立，撤销后新请求再验证 |

submit/accept/publish 消费同一新工作/冻结版本，由 N29/N34 管理；不作为 transfer.commit 的隐含副作用。生成请求继续用既有 AI 受理/查询体系，绑定已核准 source_versions、费用上下文及 Attempt，不另开一个 PS 收费引擎。

### 4.1 幂等与冲突

- 幂等作用域建议为 actor + target_scope + operation_kind + key；相同 key 相同 digest 返回同一次已记录结果，即使重试到达时响应曾丢失。
- 同 key 不同字节/来源/费用上下文拒绝；状态未知先 transfer.status/原 Provider 查询，不自动重传“创建一次新的成功”。
- base working head 变化返回冲突/需重新选择工作副本；源出现新版仍绑定原 source_version，不能偷换。
- 撤销权限优先于历史幂等成功结果的再次字节交付；能查自己的脱敏操作结果不代表继续有 read/export 权。
- 不设置默认自动合并或最后写入者覆盖；是否允许显式分支/合并及业务审批另审。

### 4.2 字节与登记失败恢复

建议采用“操作预留 → 受控暂存 → 字节/依赖核验 → 登记新工作版本及来源 → 核验完成”的可查询流程。DB 与文件不是同一事务，必须记录可恢复边界，不以一次 HTTP 200 当整个过程原子成功。

| 失败点 | 必须保留的安全行为 |
| --- | --- |
| 上传中断/磁盘满/内容损坏 | 不标 READY；保留明确操作态，续传/重试必须同身份和已核验 key |
| 字节完成、DB 登记失败 | 不新增假正式版；通过原 operation 查询/恢复，不覆旧版本或重复收费 |
| DB 元数据存在、字节未持久 | 不返回可用工作版本/交付成功；阻断引用与发布，保留恢复材料 |
| 并发目标头变化 | 不覆盖正式/工作头；返回冲突并保留已有来源事实 |
| 权限撤销/任务取消但 Provider 已受理 | 限制新使用；原 Attempt 查询/对账继续，不假称取消成功或再付费 |
| 重启/新业务格式升级后恢复 | 复用 B03/统一更新引擎，核数据/引用/版本身份；新写入后不回旧快照丢数据 |

暂存清理/hold/GC/恢复人工责任及保留期限尚未批准，不能为“清理失败片段”删除正式版、未知引用或客户原始资料。操作日志仅记录必要标识和脱敏原因，不记录密钥/私人业务正文。

## 5. 多模态与 Photoshop 外部边界

优先复用现有图像浏览、置入和 PNG 回传。对视频/音频/工作流声明真实支持的模态、格式、时间/尺寸与依赖；工具不支持的操作明确拒绝，而不是转换后宣称保留原生编辑能力。是否扩展 PSD/PSB 原生源文件属于详细需求待确认，不由 N37 方向自动批准。

平台内派生不是外部导出许可；PS 的读取字节、设备/会话、回写均需企业权限保护。可撤销新在线请求，不能保证删除已合法下载至 PS 或外部文件系统的字节。UXP/HTTPS/WS 联调必须保持身份与 Origin 校验，不能为便利关闭 Gateway、透传项目密钥或信任 X-User-Id。

## 6. 需要负责人确认与后续验收边界

详见 [政策登记](../decisions/REQUIREMENTS-DECISION-REGISTER.md)。G0—G3、A/B/C、R1—R4、预算/付款/探索、期限/GC、业务任命、高风险/撤回权及外部导出/设备策略均未批准。现有授权/许可/安全拒绝继续有效。

后续实施前应先批准最小对象/接口和新场景命名，再给具体模块实施授权，按正式阶段交付迁移/失败恢复证据。不要求等待所有长期工程完成，也不以文档完整为理由跳过当前 #148。

本次只有草案：无新表/业务代码/PS 实测/Provider 付费调用，无合并、Release 或生产变更。
