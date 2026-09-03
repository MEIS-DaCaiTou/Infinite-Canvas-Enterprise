# 2026-09-03 Runtime 可靠性修复实施记录

状态：开发分支实现；未发布、未修改生产设备，不是生产故障已关闭的声明。

## 基线与证据边界

- 分支：`codex/runtime-reliability-20260903`。
- 开发基线：`origin/main@58dc98c09e213ee747024d2934aa181d14cf0c1d`。
- 使用者反馈的现场版本：`2026.08.4`，不是本分支。
- 现场证据包 SHA-256：`0c9d6b9792f77fbea9758d1c959e4a2a3c49a1ba34ab85d3359ed26243a91613`。
- 已确认：09:11、09:20 的 Gateway 替换由连续健康检查 `read_timeout` 触发；这不是此前已经修复的单次 `startup_timeout` 缺陷。Gateway 的计划退避为 1/2 秒，但现场约 0.22 秒就重新启动，代码也存在相应绕过路径。
- 未确认：现场每一次超时具体卡在哪个函数。同步文件解析、权限数据库访问和健康检查连接池耦合是已查明的结构性风险，不能将代码定位冒充现场 CPU 栈证据。此次也没有证明所有用户所说的“任务丢失”均由同一个机制造成。

## 已实施

### Supervisor 与健康检查

1. Gateway 增加 `/enterprise/live`，只检查自身事件循环能否响应，不访问数据库、认证或 Upstream。
2. `/enterprise/health` 仍作为 readiness，保留旧响应形状；使用独立的小型 HTTP 连接池，禁用环境代理，Upstream 请求设 1 秒总时限，短于 Supervisor 的 3 秒探测时限。
3. readiness 读超时时再用 1 秒探测 liveness。只有 liveness 确实响应才标记 `readiness_timeout/degraded`，不破坏性重启；liveness 也失败时仍累计失败、有限重试和进入 crash-loop 保护，不是永久忽略故障。
4. `_start_role` 检查退避截止时间；Gateway bootstrap 只启动合法的初始 stopped 状态，不能绕过 restarting/degraded/crash_loop。
5. 真正 starting 的进程使用 startup deadline，避免稳态连续失败阈值提前耗尽启动宽限期；健康运行后的阈值逻辑保留。
6. 健康日志新增 `elapsed_ms`。进程、监听器身份与 owned-only 终止规则没有放宽。

### Gateway 阻塞路径

- Token 校验、登录、前后置拦截、部分请求重写和页面权限数据读取转到 Starlette 工作线程，不在 ASGI 事件循环同步执行 SQLite / 文件工作。
- WebSocket 广播仍在原事件循环执行；响应过滤与用户隔离逻辑保留。
- 资源引用索引按文件身份、大小及纳秒时间戳失效，并限制缓存文件数/引用数；只缓存引用，不缓存许可或用户权限。每次访问仍查询当前归属，变更/删除/归属变更均有回归覆盖。
- 资源归属批量登记改成单连接、单事务 `INSERT OR IGNORE`，不覆盖原有所有者，避免每个 URL 重复开库与提交。
- 这不是把整个 Gateway 或 Upstream 的所有同步工作全部改为异步；没有改多 worker 或引入分布式服务。

### 两类画布后台任务的持久化

- 覆盖 `/api/canvas-image-tasks`、`/api/canvas-comfy-tasks`。原内存字典替换为 `DATA_ROOT/canvas-tasks/<task_id>.json`，独占临时文件写入、flush/fsync 后原子替换；APP_ROOT 不写入。
- 先持久化任务回执和企业用户归属，之后才调度供应商调用并返回 queued。Gateway 丢失创建响应不再阻止后台任务拥有归属记录。
- 同一回执只允许 queued → running 一次；结果、错误和已取得的外部任务标识持久化，查询不依赖旧进程内存。
- 启动时将遗留 queued/running 明确标记为 `failed + recovery_required + runtime_interrupted`。已经 succeeded、failed 或 jimeng_pending 的记录保留；不自动重提可能已经计费的外部任务。
- 不另行持久化完整请求输入和供应商设置；保留 provider/model/工作流文件名等原任务元数据。结果本身可能包含提示词、引用和业务数据，任务目录须按用户数据保护和备份，不能作为脱敏日志导出。

## 明确没有解决/承诺的事情

- 不能凭空恢复启用此实现前已经消失的内存任务；现场 7,455 条历史任务的可恢复性没有在此任务中验证。
- `recovery_required` 是可追踪的中断，不等于自动续跑。尚未实现全部供应商的提交阶段外部 ID 提前落盘、自动结果对账、跨网络重试幂等或 exactly-once。
- 未改变前端所有网络失败/轮询恢复路径；任务有持久记录，不等于所有界面断线情形均自动恢复。
- 仍为单 Upstream 写入者；未支持多个 worker/多设备共享此任务目录，也未添加自动归档删除策略。长期数据增长需要另行评估启动盘点和保留策略。
- 原子单文件写入可防进程中断产生半份已发布 JSON，不构成数据库、画布、任务结果的跨文件一致性快照，也不保证磁盘损坏/所有断电情形下零丢失。
- 本任务没有再次迁移用户数据、修改账号密码、调整生产配置或重启生产进程。

## 验证

开发解释器：CPython 3.11。使用 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，因为本机自动加载的 pytest-asyncio 插件与当前 pytest 不兼容；此次测试不依赖该插件。

- 新增事故回归：启动宽限、稳态阈值、退避绕过、blocked 状态、readiness/liveness 区分、健康独立连接池及总时限、事件循环可响应、广播线程、缓存失效与权限、批量归属。
- 新增任务回归：真实子进程 `os._exit` 后恢复、完成结果与外部 ID 保留、重复执行拒绝、原子替换失败保留旧记录、损坏记录不静默丢弃、路径边界、先落盘/归属再执行、写失败不调用供应商、临时 portable 根下的 main 集成。
- 六个独立脚本通过：ownership、task-history、feature-flags、websocket、upload、asset-library isolation。
- 第一次整体检查暴露 base branch 的 DATA-MVP-1 写入审计缺项；已补 W49 映射，另用 W48 显式登记本次任务文件写入。未跳过审计或执行数据库 migration。相关静态构建与 DATA 测试复查通过。
- `test_real_cli_lifecycle_and_acknowledgements` 在独立后台测试 worker 内创建 service host 时被 Windows 拒绝：`service_host_create / errno=13 / winerror=5`，重复可见。没有为了通过测试修改生产启动/Job 安全规则。普通隔离 CLI 路径已验证 start/health/owned-only stop 成功、两个随机测试端口释放；这不能替代失败的独立会话场景。
- 整体回归：`903 passed, 10 skipped, 1 deselected`，401.85 秒。命令为 `py -3.11 -m pytest -q enterprise/tests -k 'not real_cli_lifecycle_and_acknowledgements'`；唯一 deselected 是上面已独立运行并失败的后台测试，不能把这个结果描述为全部测试通过。上述场景仍须在允许相应 Windows 进程/Job 操作的测试环境复核。
- 收尾补充了资源缓存字符总量上限、工作流文件名兼容性；最终定向检查 `test_runtime_reliability.py + test_canvas_task_journal.py` 共 28 项，另重跑 ownership isolation。此计数不与整体回归相加。
- 本地旧 bundled Python 为 3.10.11，仅做修改文件的 AST 语法检查通过，不冒充生产包 CP314 运行验证。

## 发布与回退约束

1. 当前只是开发修复，不应把 `main` 或此工作目录直接复制覆盖生产不可变 Release。尚未生成新版本包或更新现有公开 `2026.08.4`。
2. 发布前固定 commit，使用既有 Manifest v2 构建/校验；补齐 bundled CP314 与独立 Windows lifecycle 验证，然后在隔离副本验证故障窗口对应负载。
3. 切换时记录 Gateway/Upstream PID 与版本基线，使用维护窗口、任务排空和可恢复的完整快照。快照必须同时包含有效 DB_PATH、DATA_ROOT（包括任务目录及结果文件）和实际 CONFIG_ROOT。
4. 使用数据库旧备份回退会丢失备份后写入，不能当作无损回滚。旧代码不认识新任务回执：需要保留新任务目录和切换后的业务数据，不能直接删新目录或宣称旧代码会恢复这些任务。
5. 验收必须确认忙碌时不误杀、真正卡死可恢复、重启后任务状态可查询且不重复调用供应商；HTTP 200 或单次启动成功均不足以判定生产稳定。

## 上游补丁边界

`main.py` 是明确必要的最小兼容接入：startup recovery、两类任务创建/执行/查询改用企业持久回执。核心实现放在 `enterprise/canvas_task_journal.py`，未修改供应商算法或前端。后续受控 upstream sync 必须保留/重应用这些接入并运行新增测试；本任务没有向上游或 GitHub 发布内容。
