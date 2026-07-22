# 临时测试部署反馈（2026-07）

- 状态：反馈记录；不是生产操作记录
- 关联：仓库外 temporary test business deployment 包的项目负责人本地测试
- 生产影响：`production touched=false`

## 已记录反馈

项目负责人反馈的临时测试包操作中，出现了以下可复现的兼容性/可用性问题：

1. PowerShell 从当前目录执行 `.bat` 必须使用 `./` 或 `.\\` 前缀；直接输入文件名不会执行。
2. 中文 `.bat` 提示在部分控制台出现编码显示异常。
3. Windows PowerShell 5.1 不支持 `RandomNumberGenerator.Fill`，首次配置脚本在生成随机 secret 前失败。
4. 测试端口可能已被旧实例占用；在端口所有者未确认停止前，测试包不应启动或终止该进程。

本文件不记录设备名、目录、IP、账号、密码、JWT、Provider Key、数据库或进程命令行。项目负责人
曾在本地测试目录中制作兼容副本以继续诊断；该副本不是仓库修改、不是正式补丁，也不应被提交。

## ENV-1B1B 边界

本 PR 只把上述反馈作为后续 test-package 独立修复任务的输入：不修改 package-only launcher，
不操作测试设备、不停止外部进程、不读取业务数据，不将临时包描述为正式 Release 或 Production
Baseline。

```text
temporary_test_business_deployment_active=true
production_device_touched_by_project_owner=true
production_device_touched_by_codex=false
temporary_test_environment_accessed_by_codex=false
temporary_test_environment_modified_by_codex=false
```
