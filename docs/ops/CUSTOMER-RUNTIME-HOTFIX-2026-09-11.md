# 客户 Runtime 定点热修 2026.09.4

## 范围与基线

- 唯一允许的源 Release：`ice-2026.08.5-ee4281022d01`。
- 目标版本：`2026.09.4`；最终 Release ID 由本提交的 12 位 Git SHA 生成。
- 只更新不可变代码 Release，不迁移、不重建、不初始化数据库，不改变配置和素材根目录。
- 交付物是离线 Release Candidate；它不等于正式签名安装器或最终生产发布批准。

## 修复内容

1. 新增不依赖鉴权、数据库、文件扫描和 Upstream 的 `/enterprise/live`。
2. Gateway readiness 超时后以独立 liveness 分类；短暂 `readiness_timeout` / `upstream_unavailable` 只降级，不重启同一 PID。
3. 启动宽限与稳态连续失败阈值分离；所有启动入口遵守 1/2/5/10/30 秒退避。
4. Gateway 到本地 Upstream 的健康探针使用一次性无 keep-alive 连接、并发单飞、2.5 秒外层截止，并设置 `trust_env=False`。
5. 鉴权、数据库、JSON/文件扫描及拦截器同步工作移出 ASGI 事件循环；资源引用缓存有界且不缓存授权结论。
6. Provider 代理问题与 Runtime 健康判断分离；只提供只读诊断，不自动修改客户代理设置。

## 更新与回退

离线执行器先完整校验 Manifest、Inventory、Release archive，并在源 Release 仍活动时物化目标。确认任务排空后，只通过正式 Runtime 入口受控停止源版本。UPDATE-MVP-1 随后原子切换 `current-release.json`、启动目标并执行健康检查；目标失败时自动切回并启动原 Release。

同 Schema 更新不触碰 `data`、`config` 和用户素材目录。由于旧架构的执行中任务仍可能在进程内存，执行器必须得到“无活动任务”的明确确认，不能声称本补丁恢复中断任务。

## 验证边界

- 现场旧版 V3：截至 2026-09-11 10:35，18,798 条监测样本，Gateway/Upstream PID 变化和重启均为 0；两次瞬时失败由同 PID 在约 2–3 秒内恢复。
- 现场材料是旧版行为依据，不是 `2026.08.5` 可直接覆盖的文件，也不是最终生产批准。
- 目标分支需通过专项、完整企业测试、Release v2 校验和隔离升级/失败回退演练后才可交付。
