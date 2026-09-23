# OPS-3B 隔离升级与恢复演练记录

状态：进行中；不构成正式 Release 或客户升级批准。

## 范围与安全边界

本演练只使用全新隔离安装根、数据根、随机本地端口和固定 Release 构建产物。不得使用客户设备、现有业务数据库或旧热修分支。项目负责人已取消“独立 Windows 主机”门禁；GitHub Actions 的干净 Windows 环境或其它全新隔离用户环境均可提供真实进程证据。

`enterprise/tests/update_mvp_1_windows_smoke.py` 以前会临时搬动当前用户的 LocalAppData 产品目录。现改为：只要两个产品目录之一已存在，就在创建证据目录和执行升级前拒绝；仅清理本次创建、带随机归属标记的目录。隔离工作区位于指定证据目录下，清理前核对绝对路径、归属和 reparse 边界。不得为了通过演练而手动移动、删除现有用户目录。

## 本轮已验证

| 场景 | 结果 | 证据边界 |
| --- | --- | --- |
| 同 Schema 成功切换、目标启动与健康 | 定向测试通过 | 模拟 Runtime 的隔离单元测试；非真实进程 |
| 目标失败后代码指针回滚、源版本恢复 | 定向测试通过 | 模拟 Runtime 的隔离单元测试；非真实进程 |
| 前向迁移、备份、验证失败与数据库恢复 | 定向测试通过 | 临时 SQLite 数据；非客户数据 |
| 恢复失败进入 `RECOVERY_REQUIRED`、不自动重试 | 定向测试通过 | 临时 SQLite 数据 |
| 现有 LocalAppData 目录保护 | 定向测试通过；本机真实入口返回 `UPDATE_MVP_R1_LOCAL_ROOTS_IN_USE`，没有创建证据目录 | 本机未运行真实进程升级 |

本轮定向命令：`py -3.11 -m pytest -q enterprise/tests/test_ops3b_smoke_safety.py enterprise/tests/test_update_mvp_1.py enterprise/tests/test_data_mvp_1.py`，结果 `55 passed`。未重跑 PR 全套门禁。

## 完成 #115 前仍需

1. 在全新隔离 Windows 用户环境，用当前主线构建的固定 CP314 Release 产物重复真实进程成功、受控失败、代码回滚与数据库恢复场景；不得复用旧版 WU1/WU2 结果冒充当前主线。
2. 每次核对 source/target Release 身份、`current-release.json`、Job 状态和事件、源/目标健康、Supervisor/worker PID、随机端口占用与释放；保留旧 Release、脱敏诊断、构建 SHA-256 和场景摘要。
3. 对 `RECOVERY_REQUIRED` 进行人工恢复演练，证明恢复前不会自动重试或在不兼容 Schema 上启动旧版本。
4. 审阅证据后再决定是否关闭 #115；此处不授权正式 Release、客户更新或生产部署。
