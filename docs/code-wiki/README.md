# Infinite Canvas Enterprise Code Wiki

更新时间：2026-10-14
项目：`MEIS-DaCaiTou/Infinite-Canvas-Enterprise`

Wiki 是源码/运行参考，不是第二份状态表、路线图或生产批准。本轮核验 main@01c2977359ffdf2751711f151ef91ad634e0fd75（已合并 #123/#154–#159），产品功能基点 #156@4bdd9a16074abac86ce47fc1e81b55bfb12cf63c；新增模块说明明确来源归属，C5/C6/C7 已合并，引用准确实现和验收记录。本轮复核全部九章的源码/运行入口，历史测试结果不改成新跑分。

## 1. 阅读范围

- 数据迁移/恢复、一次确认与路由检查已接入 main，不能再笼统写“只支持同 Schema 更新”。
- 正式应用最新为 v2026.10.2，准确 source `7da593b`；固定入口/安装维护和 v2 数据基础来自统一 main。正式 10.1 v2 单跳与必要失败恢复已验证；BAT 仍是源码/旧安装兼容路径，完整历史/GUI 及客户范围见 CURRENT。
- [已合并产品修复](../ops/PRODUCT-INTEGRATION-FIXES-2026-10-13.md) 索引图像能力/请求模块、个人模型及扩展；[C5](../ops/VERIFIED-UPDATER-HANDOFF-2026-10-11.md)/[C6](../ops/OFFLINE-RETAINED-UPGRADE-2026-10-12.md)/[C7](../ops/ONLINE-UPGRADE-SEQUENCE-2026-10-12.md) 索引已合并生命周期及其准确验收边界。文档存在不表示运行代码合并。
- 最新主线、PR/CI、Release 和现场结果只见 [CURRENT](../CURRENT_PROJECT_STATUS.md)，每轮重新核验。
- 安装更新设计见 [统一交付 ADR](../decisions/ADR-DELIVERY-001-UNIFIED-INSTALL-UPDATE-LIFECYCLE-2026-10.md)，任务只按 [路线图](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md)。

## 2. 章节

1. [系统架构](./01-system-architecture.md)
2. [仓库结构与模块职责](./02-repository-map.md)
3. [后端类与函数参考](./03-backend-reference.md)
4. [前端、API 与 WebSocket](./04-frontend-api-and-websocket.md)
5. [数据、权限与安全](./05-data-permissions-and-security.md)
6. [Runtime、安装、发布与在线更新](./06-runtime-install-release-update.md)
7. [依赖与外部集成](./07-dependencies-and-integrations.md)
8. [运行、测试与开发方式](./08-running-testing-and-development.md)
9. [已知限制、风险与维护建议](./09-known-limitations-and-maintenance.md)

## 3. 维护

模块/接口/入口实质变化时更新对应章节，不每个 PR 重写全部 Wiki。历史测试记录保留日期，不改写为本轮跑分；代码路径区分 main、维护线和已安装产品。

原则、边界和任务分别回到 [架构](../../ARCHITECTURE.md)、[范围](../../PROJECT_SCOPE_LOCK.md) 和 [路线图](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md)。新增/移动资料同步 [登记表](../document-register.json) 并做轻量检查；不把源码快照当永久当前值。

2026-10-14 ComfyUI 修复定位时的快照：main@e89a288fe（#156 已合并）；本轮 ComfyUI 修复候选的共用字段模块见 [前端/API 章节](./04-frontend-api-and-websocket.md#9-comfyui-输入修复候选) 和 [完整记录](../ops/COMFY-WORKFLOW-INPUT-REPAIR-2026-10-14.md)。前述 10-13 九章快照保留采集时点，PR/CI/发行仍以 CURRENT 为准。

2026-10-14 发行收口：#123/#157/#158 独立审查后已合并，10.2 准确构建源码随 #159 进入 main；上述 10-13 快照与早期“候选”指采集时点。包级真实单跳及失败恢复、10.1 裸库限制见 [Runtime 章节](./06-runtime-install-release-update.md#102-发行包的准确升级边界) 与 CURRENT。正式 Release 与源码合并分别核验。

10.2 测试设备反馈续修候选已补充到后端、前端/API 与限制章节：ComfyUI HTTP 适配、双视图共享状态、指定后端和原任务查询；目前为独立分支开发，未合并/发布。正式状态仍见 CURRENT。

2026-10-15 #161 输入输出增量候选：新增共用可变图片组、类型结果、文本视图/Prompt 复用与选定结果快照；后端和前端章节继续引用同一实施记录。已按负责人反馈对齐画布视觉，源码/PR/CI 与正式发行分开记录。

2026-10-15 收口：#161 已独立复审并合并 main6603550，三项 main 常规 CI 成功；此前“候选未合并”为历史采集时点。后续本人持久任务中心与 Zhenzhen 图像边界候选已更新后端、前端/API、限制章节；尚待独立审查，未发布。设计/必要证据继续集中在 [任务工程记录](../ops/PAID-SUBMISSION-STOPLOSS-2026-10-13.md#2026-10-15-持久任务中心与供应商边界续包)，唯一任务顺序仍见路线图。
