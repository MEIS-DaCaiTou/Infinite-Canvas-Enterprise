# v2026.10.4 修复版本发行记录

## 正式发布收口（2026-10-20）

负责人明确批准 #183 合并与正式发布10.4，由负责人自行操作测试主机。准确审查Head `d495915c80c6dbc68b5f65afae0e5899b8408837` 合入main `0d0078f2243bbacf6b24200e0a22a30d94b2a64e`。技术Review为NO_ACTIONABLE_BUGS_FOUND，不是GitHub Approval。准确main自身 [Enterprise/Runtime39379586019](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/39379586019)、[Docs39379586012](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/39379586012)、[Native39379586015](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/39379586015) 最终SUCCESS，不以PR CI替代；固定EXE opt-in在CI为SKIPPED，本地手动验收单独记录。

正式 [v2026.10.4](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/releases/tag/v2026.10.4) 为Latest、非预发布。构建/标签源码固定 `2859a2aefbac5d30829eb7f7aa73c82ee1eb2583`，Release ID `ice-2026.10.4-2859a2aefbac`；后续文档/合并提交不是构建身份。九项核心资产逐项上传后下载回读，与已验收字节一致；另附含main CI和验收边界的发行验证JSON并回读，共10项。没有重打包或覆盖10.3历史资产。沿用固定CPython3.14.6、依赖和原工具链，EXE/Setup未签名，不要求关闭Windows安全保护。

## 功能与验证边界

常用Setup流程只需选择位置、安装/升级或修复、最终确认；新装保留创建管理员。环境说明和附加任务页取消，停机确认、桌面快捷方式及打开窗口选项集中到最终页；十三项恢复/卸载/清理默认隐藏在高级维护。后台身份、Runtime、维护锁、数据库完整性及显式恢复保护不变。具体变更和早期失败按 [C6原记录](./OFFLINE-RETAINED-UPGRADE-2026-10-12.md#2026-10-20-安装向导简化候选) 保留。

10.4纳入已合并的排队任务持久执行/启动恢复、受控空WAL/SHM准备、Grok imagine/MiniMax-H3/Wan3的精确协议路由及图片结果协议增量。此前10.3的ComfyUI图文复用、个人模型、任务来源、视频续接和LLM找回继续保留。不将模型目录出现等同于全账号/全协议已适配。

| 验收路径 | 准确结果与范围 |
| --- | --- |
| 正式10.2→10.4 Setup | 开发机合成安装、受证空WAL/SHM，经真实图形按钮与最终完成；事务COMPLETE、jobSUCCEEDED；Windows登记、原安装ID、Schema/ledger、数据库完整性、原账号登录/后台、画布/素材文件、健康200及业务fence清除均核验 |
| 正式10.3→10.4更新 | 原10.3固定EXE CLI启动，认证更新HTTP执行真实worker，SUCCEEDED；目标Runtime身份/健康正确，原业务行及7文件保持，经典/智能画布经认证HTTP保存重开一致 |
| 10.3目标启动失败 | 只在目标RESTARTING占用合成实例端口，ROLLING_BACK前释放；ROLLED_BACK，正式10.3原Runtime healthy，账号/画布/文件保持 |
| 清理 | 用实际注册卸载器只注销本轮测试GUID；保留合成数据，端口全部关闭；本机原KnownFolder树字节、mtime、目录身份完整恢复，最终会话exit0 |

单元定向94 passed/14 Windows opt-in skipped，文档契约17 passed及check_docs通过。PR准确Head常规CI全部通过；已审后端的中断/恢复、Browser与真实Provider证据沿原范围复用，没有本地重跑无关全量。首轮GUI会话超时后安全回收，后续Install在事务前被BOOTSTRAP_INVALID阻断，原10.2指针保持；该失败不改成首次通过。第二轮同一准确包通过上述完整验收。开发机防火墙提示由负责人点取消，未开放网络权限。

## 公开更新与测试主机操作

以正式10.3原 `_check_update_sync` 无GitHub Token读取完整公开目录，10.4为stable/direct；正式10.2原服务核对为stable/requires_intermediate。两者仅只读检查，不启动Runtime、不准备/执行升级，不是Browser或客户验收。10.2在线须先经过已声明的10.3路由，不伪造10.2→10.4直接路由；本次Setup支持的10.2直接离线升级单独验证。正常启动继续当前版本，不强制更新。

测试主机按负责人操作：先确认任务完成，从原固定EXE停止服务并关闭启动窗口；下载本Release的 InfiniteCanvasSetup.exe，选择原安装目录。如果建议修复启动/登记，先完成修复，再重开同一安装包选择升级到10.4；已有身份正常则直接升级。完成后从原入口启动，核对版本、原账号、两类画布及素材。出现恢复阻断时保留诊断，不能手工删除锁或SQLite日志。代理未操作测试主机原库、客户或生产设备；现场反馈尚待负责人提供。

## 模型与后续限制

Grok imagine、MiniMax-H3、Wan3各一次真实提交/原任务续查和图片文生图成功证据沿用。双参考JSON编辑曾HTTP500且无受理ID，仍未取得明确终态；上游账号通道与多图合同未验证，未自动重提。图层拆分费用上界未明，未作真实付费测试。此前累计6.710022/授权10平台额度，本轮付费生成0；这不是产品费用账本。

下一完整包先收集10.4测试主机升级/数据保留反馈，对实际阻断定向修复；并澄清原JSON编辑未知请求/账号通道后安排预算内、有界真实复测，再收口图片编辑/多参考/图层输出的可用性与提示。4.3部门项目/费用治理、RunningHub #170、Linux/云/多实例继续暂缓。新代码合并、后续Release及生产操作分别按授权处理；不承诺业务开放写入后的任意无损降级。
