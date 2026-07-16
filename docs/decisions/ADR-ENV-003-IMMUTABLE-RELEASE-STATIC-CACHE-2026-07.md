# ADR-ENV-003：不可变 Release 与 static 缓存策略

- 状态：Accepted
- 决策日期：2026-07-16
- 事实基线：`main@396cccc68d63bd16393a2cb72d24e4a48fcf47cb`
- 实施状态：已决策，ENV-1B1A 尚未开始

## 背景

上游启动当前会同步 HTML 中的 `?v=` 参数并改写受版本管理的 `static/*.html`。候选运行时生命周期验证因此留下 13 个静态文件变化，阻止 APP_ROOT 被视为不可变 Release。

只修复 `static/` 仍不足以证明 APP_ROOT 可只读；上游还可能写入数据、资源、配置、日志、重启脚本、缓存和临时文件。

## 决策

1. 正式 Release 的整个 APP_ROOT 在运行时必须只读。
2. 启动、导入、重启、停止和业务运行不得修改 static、源码、Python 或版本目录。
3. 正式 Release 的 `?v=` 参数在 Release staging 构建阶段根据资源内容哈希生成。
4. 构建结果稳定后，再计算文件清单、runtime / release manifest 和归档 SHA-256。
5. 不使用启动时间、随机数、文件复制时间或本机绝对路径作为缓存版本。
6. development 模式不写源码，可使用 `no-cache`、ETag 或统一内存响应策略。
7. 验证必须覆盖全部 HTML 路由和静态文件服务路径，不得只验证根页面。

## ENV-1B1A 写入审计范围

必须定位并迁出 APP_ROOT 的写入至少包括：

- `static/`。
- `assets/`、`output/`、uploads 和生成结果。
- `history.json`、global config 和其它上游 JSON。
- SQLite 数据库、WAL、SHM 和 journal。
- `enterprise.env`、`API/.env` 与配置模板实例。
- launcher、upstream、gateway、health 和 crash 日志。
- `_self_restart.bat`、`_self_restart.log`。
- `__pycache__`、cache、temporary files。
- update staging、release package、OPS report 和 backup。

每个写入必须映射到 ADR-ENV-004 定义的外部路径根；无法迁移的写入必须阻止 `portable-release` 通过自检。

## 验收门禁

- 导入、启动、健康、重启、停止后 APP_ROOT 全树哈希不变。
- 只读 APP_ROOT 可完成真实生命周期。
- 构建期静态转换具备确定性，相同输入得到相同输出。
- Git 工作区不因启动而产生静态变化。
- ENV-1B1A 不修改正式 Python 运行时。

## 后果

- 开发源码、发布产物和运行数据边界明确。
- OPS 可以对不可变目录执行可靠的哈希、切换和回滚判断。
- 上游同步需要保留一个小而清晰的 static 构建适配层，不能继续依赖启动时自修改。
