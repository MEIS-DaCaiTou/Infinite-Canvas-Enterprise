# 2026.10.1 后台维护发布记录

日期：2026-10-08。固定发行：[v2026.10.1](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/releases/tag/v2026.10.1)，目标 `ice-2026.10.1-bf1143a7bc54`，提交 `bf1143a7bc54ac24d53b9e7d7db5a9b50da8b57c`。准确源为 `ice-2026.09.9-54f9e67d1643`。仅记录这一次维护发行；当前项目状态仍由 CURRENT_PROJECT_STATUS 维护，不建立新动态事实源。

## 固定资产

| 文件 | SHA-256 |
| --- | --- |
| Infinite-Canvas-Enterprise-ice-2026.10.1-bf1143a7bc54-win-x64.zip | e67056ce5743ccf2a882273398db673a4ab470a82670cf8f59a75074b63941ee |
| ops-release-manifest-v2.json | 36d92d4527a756df8eccf9cae0a09b9186d69e497ea5d43a0c0f81fa98743f71 |
| release-payload-inventory.json | 4e43ce2052bf4f8a0500052f55c257f92241f7647ea359b2f038ceef25622cd7 |
| upgrade-routes-v1.json | 2bd429b7e3e69e9bf040f81d39764c6483d32b285aa4fe98f7daa0e5bdbae410 |

ZIP 30,447,861 字节、2,114 文件；正式上传后四资产重新下载回验通过。原 09.9 资产未覆盖。

## 实现与兼容性

维护 [PR #144](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/144) 精确基于 09.9 维护源码。主线 [PR #143](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/143) 复用已有三角色界面；维护包仅移植与现有 09.9 接口相容的显示/提示，不移植不同的成员写入接口。

正确区分超级管理员、管理员、普通用户；显示/筛选/统计及权限用户选择一致；超管行不呈现与固定角色策略冲突的普通操作。更新只读 access 增加独立部署/功能开关与拒绝码，保留旧字段和服务端授权。权限刷新失败先隐藏危险操作，不发起升级。

Runtime 和完整数据库 evidence 与 09.9 相同：数据库版本 2、30 对象、对象哈希 `cd8790a1ef22a97b96c76105b26f14c309ed02396249ab97d36034bb88d25284`。原构建器的默认同结构选项仍生成旧的未版本化 18 对象 fixture，不能用于此包；维护构建使用新增 `same-versioned-schema-no-migration` build-time 选择，发布 wire contract 保持 `same-schema-no-migration` / `code-release-pointer`。不改数据库迁移、业务数据、用户/密码/治理状态或 CPython 3.14.6 运行环境。

Route 只允许准确 09.9 身份，不能推广成任意旧来源。主线缺失的维护线 v2 发布/桥接基础仍须受控收敛；不能单独把此 build-time 选项复制到旧主线快照后声称主线已能发布相同 v2 维护包。

## 验证与限制

- [PR #144 Windows CI](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/37783852834)：137 passed / 6 skipped；只使用既有受影响升级/数据/安装/桥接范围并纳入新增维护回归，不人工重跑主线全套门禁。
- 本地定向回归 13 项通过；另已检查密码不持久化和非授权角色拦截。标准构建及完整资产验证通过。
- 原正式 09.9 引擎实际 prepare、清单/Inventory 检查、指针切换与失败回退配合真实合成 v2 数据库通过；数据逐行、配置及素材保留。launcher 启停/健康返回是合成故障注入，不是真实生产进程操作。
- 实际包内 HTML 经 Chromium 桌面 1440×1000、移动 390×844 检查：正确角色行、角色筛选、部署禁用/功能禁用/允许只读检查，页面非空、无覆盖层、无 JS 错误、无 prepare/execute 请求。Browser plugin 不可用，使用现有 Playwright 1.62.1；既有 Tailwind CDN 警告保留。
- 包级实验的过长临时路径曾触发 Windows 260 字符限制；缩短本项目隔离测试路径后通过。此版没有更改长路径支持，应保持已核准短安装根，不把该实验失败隐去或冒称现场无此类风险。

## 现场边界

现场阶段 A 是 READY_FOR_MAINTENANCE / NO_SERVICE_CHANGE；当前生产仍是 09.9，部署更新开关仍关闭，Aidan02 已为 super_admin，不重新初始化或改密码。新的现场维护任务书随交付资产提供，不在发行目录中运行临时修补代码。

新批准窗口内，确认当前身份、任务及最新一致性备份，受控启用唯一部署开关、重建整个 Runtime 后，通过现有更新中心明确选择此维护版本。配置和已有资源位置保留，不重新复制大体量素材。原备份/监控必须核验接续，仍按已有授权周期和到期。

业务开放后禁止恢复升级前旧数据库覆盖新数据；不提供旧 TEST 双向同步或任意无损降级。现场角色/权限/原画布素材与普通账号仍须验收，长期实流量稳定性继续观察。本发布不证明历史崩溃彻底解决、零停机能力、main 合并或通用生产批准。
