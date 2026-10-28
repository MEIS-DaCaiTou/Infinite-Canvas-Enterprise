# Infinite Canvas Enterprise 代码与数据边界

更新时间：2026-10-27

## 2026-10-27 本地保存与传输模块

`local_json`不识别用户、画布或任务，调用方传入已验证路径并保留现有锁；既有任务journal的受理/恢复写入不更换。`proxy_transport`不做授权、模型选择或任务重提，Gateway继续决定是否过滤响应，interceptors负责对话/素材归属。运行环境校验只读取原发行policy和锁文件，不维护第二份应用版本表。大文件上传目前按实际请求字节设256MiB总上限，Comfy/AI素材单文件50MiB；是有界缓冲，尚未宣称上传端到端零拷贝。

`canvas-save-navigation`只等待现有编辑器保存并决定是否执行返回动作；两类编辑器继续拥有草稿/冲突/重试语义。不是第二个保存器，不通过关闭页面时的异步请求冒充保存确认。

项目已独立演进，不再把 `main.py`、`static/` 或 `workflows/` 视为永远禁止修改的“上游覆盖区”。所有产品代码都可在明确需求、测试和迁移计划下修改；风险边界取决于职责、数据兼容性和发布影响。

## 2026-10-26 本地队列模块

`enterprise/comfy_queue.py`负责ComfyUI限额与公平派发；`comfy_queue_api.py`负责后台/个人API适配；原dispatch/journal负责输入、受理和重启边界，原Comfy恢复/取消负责已受理身份。`static/js/admin-comfy-queue.js`与对应CSS只负责管理视图，输出状态继续由canvas-comfy-tasks维护。main只组合这些模块及兼容原同步响应，不新增通用调度框架或改动其他供应商执行。

## 1. 常规修改区域

| 区域 | 主要职责 |
| --- | --- |
| `enterprise/` | Gateway、认证授权、管理、数据、Runtime、Release/Update、领域服务 |
| `enterprise-static/` | 企业登录、管理、个人中心和更新体验 |
| `enterprise/tests/` | 单元、集成、故障注入、浏览器和生命周期验证 |
| `docs/`、根目录权威文档 | 当前状态、架构、路线、ADR、实施与验收记录 |
| `.github/workflows/` | CI 检查与构建门禁 |

修改这些区域仍需遵守业务兼容、权限和数据迁移要求，不能因为它们是“企业目录”就降低审查强度。

## 2. 高影响区域

| 区域 | 主要风险 | 最低要求 |
| --- | --- | --- |
| `main.py` | 核心 API、业务生命周期、任务/资源数据 | 接口/任务/启动回归，说明数据兼容 |
| `static/` | 旧版视觉和交互、缓存、浏览器兼容 | 同尺寸视觉对照、关键交互与权限回归 |
| `workflows/`、Provider 适配 | 外部调用、费用、幂等、隐私 | 真实或受控沙箱闭环、超时/未知结果测试 |
| `enterprise/db.py`、`enterprise/migrations/` | schema、事务、恢复 | migration + backup/restore + failure injection |
| `enterprise/runtime/` | 进程所有权、重启、停机 | 生命周期、阻塞、断网、重启和状态恢复 |
| `enterprise/release/`、`enterprise/ops/update/`、`enterprise/update_api.py` | 安装和在线升级 | Manifest/哈希、源版本、恢复和权限测试 |
| `release/`、启动/停止脚本 | 客户安装和运维 | 可复现打包、原位升级、回滚说明 |

这些文件可以修改，但必须小步、可审查、可回滚；不得继续用“等待上游修复”作为阻断本项目演进的理由。

## 3. 不得提交的内容

- `enterprise.env` 或任何真实环境配置。
- API key、Token、Cookie、Authorization、私钥、真实密码。
- `API/.env`、客户日志原件、客户数据库和客户素材。
- `data/`、`assets/`、`output/`、本地缓存、Runtime state/log、临时诊断包。
- 本机 Python/Node 运行时、构建缓存和未批准的大型二进制。

测试夹具必须脱敏、最小化并可从仓库重建。

## 4. 领域放置原则

- HTTP/WebSocket 入口只做协议适配和调用编排，不承载越来越多业务判断。供应商改动按提交、查询、鉴权、错误处理的完整边界逐步提取；#156 图像目录/请求构造只是该边界的一部分。两类画布新增参数逻辑优先进入共用模块；不把每个小函数拆成独立框架。
- 授权放入可复用 Policy；UI、API、Worker、Update、MCP 使用同一语义。
- 业务命令放入 Application Service；数据库/文件/Provider 放入 Adapter 或 Repository。
- 资源字节与元数据分离；路径通过 Storage Adapter 解析。
- 任务受理、执行、对账和费用记录属于持久业务域，不使用进程内字典作为事实源。
- 新增表前先定义 schema version、升级、备份、恢复和旧版本兼容。
- C# 仅薄入口/系统交互，安装器编排；Python 共用业务/更新/迁移，不按应用版本复制实现。
- C6 `install_upgrade` 的离线维护复用共享单跳引擎；原生文件恢复必须核验原对象和作业，不用进度、锁龄或 PID 缺失授权接管。成功激活后的登记恢复不回退数据库。Windows 登记/包装进程解析在 `runtime/windows_install_registration.py`、`runtime/windows_setup_source.py`，请求暂停在跨平台 `runtime/install_maintenance.py`。
- Windows Registry、Job Object、KnownFolder、文件 handle 及安装/卸载 GUI 是平台适配能力；业务模型、API、权限、Repository、Storage Adapter 及数据恢复契约应跨部署形态复用。不得给核心业务新增固定盘符或桌面交互前置。Linux/服务器支持须以依赖调查和真实运行验证判断，不能仅凭接口分层宣称完成。
- `tools/check_docs.py` 是只读开发检查，不是 Runtime；文档整改不夹带产品权限或迁移改动。

### 4.1 低耦合、高内聚的落实方式（2026-10-24）

- 以业务职责组织模块：页面负责呈现和交互，入口负责协议适配，对应领域服务负责业务规则，存储和供应商适配负责各自外部边界。共享行为由明确接口复用，不由页面脚本跨模块修改状态或直接决定权限/费用。
- 新需求先指出涉及哪些模块、现有接口及直接影响面；相关逻辑集中维护，避免组织、凭据、费用、任务和画布渲染继续混入同一大函数或依赖隐式全局状态。
- 修改旧代码时整理与本任务直接相关的完整职责边界，并覆盖受影响调用方；不为本轮功能预建框架、任意拆碎文件或进行无关全仓重构。
- 页面改动进入既有主题和组件体系，先在固定开发预览中与负责人确认效果；未验收的交互修订保持本地，不借正式发版开展试错。

## 5. 临时产物与清理

构建、下载资产、安装副本和诊断原件集中到项目 artifact 根或受管工作区，不散落盘符根目录。清理前核验绝对目标、归属、进程/指针/恢复作业引用；只处理本项目拥有且可删除的对象。其他项目、用户素材、真实数据库与有效备份不能因“整理目录”删除。

## 6. 历史来源

`docs/upstream/` 记录截至 2026.07.6 的历史来源和同步审计。它不再规定文件修改权限，也不要求后续 PR 执行上游 merge/rebase/sync。若未来引入第三方代码更新，应作为新的依赖升级任务，明确许可证、差异、测试和回滚。

## 7. 变更前检查

1. 任务属于哪个固定路线阶段？前置阶段是否完成？
2. 当前 Base/Head/PR 是否与任务一致？
3. 是否改变 schema、资源标识、任务状态或权限语义？
4. 现有客户如何升级，失败如何恢复？
5. 需要哪些自动测试、故障注入和人工验证？
6. 是否错误地把分支、Release 或单设备结果写成主线/生产事实？

C7 `ops/update/sequence.py` 只协调已声明路径，逐跳消费共享 MVP 与 C6 原生对象事务；数据库操作仍由版本化引擎实施，原生注册表更新只在 `runtime/windows_install_registration.py` 中操作已核验本实例 DisplayVersion。恢复/暂停标记不授权删除客户数据，进度状态不授权跳步或恢复旧快照。源码与限定证据见 [C7 记录](docs/ops/ONLINE-UPGRADE-SEQUENCE-2026-10-12.md)。

2026-10-15 前端增量约束：沿用当前页面的主题变量、字体、圆角、面板、按钮和交互层级。新的文本结果视图与已有日志/错误详情保持一致，设置页和两类画布共用 static/css/comfy-outputs.css；不得以临时原生控件、散落硬编码样式另立视觉体系。页面/交互变更先告知负责人方案，再按实际页面路径验收。

2026-10-20 已批准候选的限定增量：`install_database_preparation` 只为 C6 离线升级处理 WAL=0、SHM=32768 的既有成对残留。只读资格与写连接分开，实际 SQLite 处理由原 `install_upgrade` 计划、kernel lease 和启动 fence 保护，并在 SQLite 互斥内重新核验；默认生命周期检查仍拒绝旁路文件。非空 WAL、journal、未知对象/锁与不能证明一致性的状态继续阻断，不手工删除日志、不恢复旧数据库、不替代版本化迁移。新能力以候选 PR 为准，不视为正式 v2026.10.3 已具备。
