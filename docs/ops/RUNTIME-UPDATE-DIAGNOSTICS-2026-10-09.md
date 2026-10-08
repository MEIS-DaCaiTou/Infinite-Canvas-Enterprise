# 升级启动与自动恢复诊断修复

日期：2026-10-09。状态：开发候选，未发布、未合并、未操作生产。

## 客户事实与诊断边界

现场 `failure-lifecycle-redacted.json` 的 SHA-256 为
`8c781db10bc5db1967800a86c33d0489302daedfbcbe82ced6afac6bd6c509e8`。
两次正式 09.9 → 10.1 作业均记录 `RUNTIME_CONTROL_ERROR`，自动恢复最终为
`SYSTEM_UPDATE_ROLLBACK_HEALTH_FAILED`；后续固定 EXE 恢复 09.9 成功。
启动细阶段及 errno / winerror 没有被旧版记录，不能补猜为 Windows 错误 5，
也不能归因于数据库、账号或某次付费生成。不得据此要求现场再次点击旧升级路径。

本轮不继续盘点生产，不修改客户程序、配置、账号、数据库、监控或备份。
正式 09.9 和 10.1 既有 Release 资产不覆盖；10.2 仅为待验证维护候选。

## 实现范围

- 固定 portable 入口保留受白名单约束的启动阶段、errno、winerror、host 退出码和启动失败分类。
  不公开异常正文、路径、命令行、环境变量、密钥或业务数据。
- Controller 分辨日志初始化、bootstrap marker、host 文件检查、进程创建及 readiness 等阶段。
  日志构造失败也释放自己刚预留的锁；不能写日志时由公开响应和升级阶段记录保留安全错误字段。
- UpdateJobStore 持久化 target_start / target_health / target_stop / source_start /
  source_health 的开始事件与结果，包含所属 Release 和 command；保留首个 failure_code，
  不让最终恢复错误覆盖目标启动错误。未执行的阶段不伪造结果。
- 标准诊断 ZIP 直接包含上述新增作业记录；兼容旧记录，不回填历史缺失字段。
- Windows 商店应用上下文下，Known Folder 文件解析可能重定向至 package cache。
  开发安装副本已定位到第二次 portable 身份核验中 runtime root 被 `resolve()` 改写。
  portable CLI 保持契约派生的词法路径，保留 reparse 检查、目录包含检查以及完整启动身份核验。
  development 模式仍使用原解析方式。这是开发端复现的独立问题，不是客户错误根因证明。

## 验证与交付限制

新增诊断测试覆盖字段白名单、日志/marker/进程创建失败、锁释放、阶段归属、自动恢复结果、
超时及 ZIP 导出。原 update / portable 定向回归同时执行；不重跑全套企业门禁。
APP_ROOT 审计仍为 442 项全部映射，指纹清单无需刷新。

真实 Windows 测试脚本支持 `--source-build`，使用各自准确的 manifest/archive/inventory，
不修改两个已核验的发行 payload；为版本化测试数据库显式初始化官方结构。
没有指定该选项的历史低版本 fixture 必须标记 synthetic_fixture_version，不能冒充正式 09.9。
测试前检查并保存开发设备已停止的 per-user Runtime，测试后受控停止自身实例、保存日志并恢复原目录，
不删除已有记录，不接触生产部署。详细结果以开发端证据报告为准。

扩展 STAB 检查的 `test_real_cli_lifecycle_and_acknowledgements` 在本机失败；
未修改的 bf1143a 基线复跑同一项亦失败，不能计为通过或当作本补丁回归已排除所有风险。

旧 09.9 启动的 handoff worker 使用旧 09.9 的更新实现；只把新诊断代码放进目标包，
不会自动修复源版本 worker 的记录缺口。因此新的候选进程链验证不等于旧 09.9 升级路径已验收。
后续需交付版本明确的过渡执行入口并验证准确的 09.9 → 新维护版本，以及目标失败时的 09.9 恢复，
通过后再取得发布和现场维护授权。不在客户现场临时改不可变发行文件。
