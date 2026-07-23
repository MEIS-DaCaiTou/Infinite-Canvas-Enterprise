# ADR-ENV-003：不可变 Release 与 static 缓存策略

- 状态：Accepted
- 决策日期：2026-07-16
- 决策事实基线：`main@396cccc68d63bd16393a2cb72d24e4a48fcf47cb`
- 当前实施核对基线：`main@a53885b026a6c2440acb0fbde72d6571ff6f7723`
- 实施状态：ENV-1B1A 已由 PR #81 合并实现 static 子门禁；完整 APP_ROOT 只读仍待 ENV-1B1B / ENV-1B1C

## 背景

历史上游启动会同步 HTML 中的 `?v=` 参数并改写受版本管理的 `static/*.html`；2026-07-15 候选运行时生命周期验证因此留下 13 个静态文件变化。ENV-1B1A 已在当前 `main` 移除该行为，但这不能改写历史验证结果，也不足以单独证明 APP_ROOT 已不可变。

只修复 `static/` 仍不足以证明 APP_ROOT 可只读；上游还可能写入数据、资源、配置、日志、重启脚本、缓存和临时文件。

## 决策

1. 正式 Release 的整个 APP_ROOT 在运行时必须只读。
2. 启动、导入、重启、停止和业务运行不得修改 static、源码、Python 或版本目录。
3. 正式 Release 的 `?v=` 参数在 Release staging 构建阶段根据资源内容哈希生成。
4. 构建结果稳定后，再计算文件清单、runtime / release manifest 和归档 SHA-256。
5. 不使用启动时间、随机数、文件复制时间或本机绝对路径作为缓存版本。
6. development 模式不写源码，可使用 `no-cache`、ETag 或统一内存响应策略。
7. 验证必须覆盖全部 HTML 路由和静态文件服务路径，不得只验证根页面。

ENV-1B1A 合并实现对第 3 项采用以下确定性细化：独立 CSS 的 `url(...)` 和 `@import` 形成 dependency-first 依赖图，叶子资源按实际 source 字节哈希，CSS 按传递转换后的 output 字节哈希；HTML 引用 HTML 统一使用 `SHA-256(builder_version + NUL + source_tree_digest)`，避免用仍会被改写的 source HTML 单文件哈希代表 output。CSS import cycle、缺失、逃逸和 reparse 均 fail closed。该 builder 尚未接入完整 Release、Manifest 或 activation。

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

已合并的 ENV-1B1A 只关闭 static 构建期转换和源码树不变门禁，并形成 Git tracked 写入 site fingerprint 到 W01-W41 的审计清单和漂移门禁。C1 将 `current-release` persistent-state primitive 独立为 W41，W24 仍只表示 legacy self-restart 生命周期。该静态分析不能证明绝对不存在未知写入。导入/启动/健康/重启/停止的 APP_ROOT 全树不变和真实只读生命周期仍被数据、配置、上传、startup migration、legacy update、bytecode 等写入阻塞，不得因 static 子门禁通过而宣称本 ADR 已完整实施。ENV-1B2P 的 Runtime 文件证据验证也不替代这些 APP_ROOT 生命周期门禁。

## 后果

- 开发源码、发布产物和运行数据边界明确。
- OPS 可以对不可变目录执行可靠的哈希、切换和回滚判断。
- 上游同步需要保留一个小而清晰的 static 构建适配层，不能继续依赖启动时自修改。
