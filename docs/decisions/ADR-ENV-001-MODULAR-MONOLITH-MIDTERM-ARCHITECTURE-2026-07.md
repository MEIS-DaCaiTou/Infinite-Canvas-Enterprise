# ADR-ENV-001：中期总体架构形态

- 状态：Accepted
- 决策日期：2026-07-16
- 事实基线：`main@396cccc68d63bd16393a2cb72d24e4a48fcf47cb`
- 实施状态：已决策，尚未开始结构性重构

## 背景

当前系统由对外的 Enterprise Gateway、仅本机访问的 Upstream Infinite Canvas、企业 SQLite、上游 JSON / 本地文件以及 Windows runtime supervisor 组成。Gateway 集中处理登录、鉴权、HTTP / WebSocket 代理和企业兼容，`enterprise/interceptors.py` 则承担大量路径识别、授权、过滤、owner 记录与审计触发。

这种架构适合当前单机、小规模企业多用户场景，也最大限度保留了上游能力。但继续把新增业务判断堆入 Gateway / interceptors 会增加上游同步、测试和安全审查成本。

## 决策

未来 1 至 2 个阶段继续采用模块化单体：

1. 保留 `Enterprise Gateway -> Upstream Infinite Canvas` 的运行拓扑。
2. Gateway 继续作为统一安全入口、兼容边界和代理入口。
3. 不把新的领域逻辑继续集中到 Gateway / interceptors。
4. 按项目、画布、对话、资源、历史、任务、设置和 WebSocket 等业务域，渐进抽取 Policy、Application Service、Repository 和 Upstream Adapter。
5. 保留现有入口和 API 行为，每次只迁移一个业务域，并提供对应回归和回滚路径。
6. 当前不实施微服务拆分。

## 备选方案

### 继续扩大 Gateway / interceptors

未选择。短期改动较少，但会持续扩大单文件策略耦合，并使未知上游路由、owner 一致性和响应重写越来越难以审查。

### 立即拆分微服务

未选择。当前仍是单发布单元、单机文件与进程内状态，上游能力高度集中；过早拆分会先引入网络事务、部署、观测和数据一致性成本，却没有独立扩缩容收益。

### 重写上游主应用

未选择。会失去受控上游同步能力，并扩大画布、工作流、模型和静态前端的重写风险。

## 后果

- 企业代码可以形成清晰的领域和适配边界，同时继续复用上游。
- 在 Repository、任务和 realtime 状态外置前，系统仍是单实例架构。
- 模块化工作必须按小型 PR 进行，不允许创建大量空目录或一次性搬迁全部代码。
- Gateway 仍是安全边界，但业务授权应逐步下沉到 Policy / Service / Repository，而不是只靠响应后过滤。

## 重新评估微服务的触发条件

只有出现至少一项可验证需求时重新评估：

- 某业务域必须独立扩缩容。
- 某业务域需要独立故障隔离或部署周期。
- 已形成独立团队和稳定所有权边界。
- 单体发布和资源竞争已经无法满足已定义 SLO。
- PostgreSQL、共享任务、对象存储、realtime backbone 和集中观测已经完成。

微服务数量本身不构成架构先进性的证明。
