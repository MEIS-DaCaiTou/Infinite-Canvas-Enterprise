# 正式 09.6 后续升级与回退核验

更新时间：2026-09-28。项目：`Infinite-Canvas-Enterprise`，不涉及 Aidan OS/Canvas。

## 准确起点和证据范围

正式源版本是 GitHub [`2026.09.6`](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/releases/tag/2026.09.6) 的 `ice-2026.09.6-8f65c5cd328f`，不是同名开发分支或早期 `5ea5fae` 候选。三项资产 SHA-256 分别为：归档 `863e67d8a8323fee49425ac96e21c41adce8af4b70069118b1980ad9ac66cecb`、Manifest `e183631d52bbd0955477dfc6f6540aea99a0e173bb11821544a1db926a2cb85d`、Inventory `a8832354fdb9cc9123c6270bf5cb1dddb5d0e41f31e4ddc24945400b8b0920a1`。本次从 GitHub 下载、计算 SHA-256、验证三资产和物化文件树，结果通过；只在本机隔离副本中创建模拟数据，未读取客户数据库。

正式 09.6 数据库证据是旧式三字段 `schema_id/migration_ids/objects`，18 个 Schema 对象，没有 `enterprise_schema_state` 或版本记录。`migration_ids` 包含 `sqlite_existing`。最新主线新装数据库快照有 30 个对象，增加版本元数据、安全审计和引导标记等 12 个对象；主线旧式 `migration_ids` 列表也少了 `sqlite_existing`。因此“改一个版本号，把主线打包”既不满足同 Schema 合同，也不是受控迁移。

最重要的执行限制：**正式 09.6 内置的 `DEFAULT_MIGRATIONS` 为空。** 已用正式包自带 Python 对合成的改表目标执行源端计划，返回 `SYSTEM_UPDATE_DATABASE_MIGRATION_PLAN_INVALID`。目标包不能事后把新 Python 迁移步骤注入不可变的 09.6 更新器。开发分支用显式测试步骤跑通迁移，只证明迁移原语和回退策略可行，不证明现装 09.6 可直接执行未来新步骤。

## 已实现和已验证的基础

本地开发分支 `codex/096-data-upgrade-20260928` 在主线迁移器中接入准确旧库证据核对、只读版本登记预演、停机后 WAL 收敛、一致性备份、同一事务的版本登记与前向迁移、目标失败后恢复，以及恢复不确定时的 `RECOVERY_REQUIRED`。旧式备份有独立 Manifest 类型；源/备份 Schema 和数据库文件指纹均需核对，恢复时还核对数据库文件名。

定向测试包括原有 DATA/更新/Manifest 用例，以及使用正式 09.6 物化包创建三份安装副本的可选演练。模拟用户画布归属、配置和素材在成功、目标健康失败、迁移校验失败三条路径中得到检查；成功后数据库版本为 2，目标健康失败恢复为无版本记录的旧库和 09.6 指针。演练的**目标 Manifest、目标安装包和启动回调是测试桩**，不代表下一正式 Release 已构建、真实 Supervisor 重启已通过或客户数据已迁移。

可选演练入口：在已经独立核验并物化正式 09.6 三资产、且使用短的测试临时目录后，设置 `ICE_096_RELEASE_ROOT` 指向该物化目录，执行 `py -3.11 -m pytest enterprise/tests/test_customer_096_upgrade_drill.py -q --basetemp <隔离短路径>`。该测试从不修改源物化目录或客户安装。

## 下一版交付路径

1. **同 Schema 代码过渡版**：以准确 09.6 为唯一已验证源版本。目标仍保留 09.6 的旧数据库证据和配置/素材路径，不登记版本、不改变业务表；代码预置经过审查的首个真实迁移步骤。验证 09.6 原更新器能接收完整三资产、启动后旧画布/图片/登录可用，以及目标启动失败时恢复旧指针。版本号和目标 SHA 随正式构建确定，不能把此测试的 `migration-drill` ID 当作 Release。
2. **独立改表版**：由第一步安装后的更新器运行其已内置迁移步骤。Release Manifest 和目标 Schema 绑定准确旧库指纹、登记后指纹、迁移 ID/校验和与目标 Schema；先一致性备份，再原子登记和迁移，验证目标进程健康。失败恢复数据库、版本指针和旧服务；若恢复无法证明一致，保持 `RECOVERY_REQUIRED`，不可盲目重试。
3. **正式发布前的剩余工作**：冻结首个真实迁移（优先与任务持久化相关，但不提前虚构业务字段），让 Release 构建器产出 `versioned-forward-migration` 的真实目标证据，而非目前硬编码的 `same-schema-no-migration`；对齐旧/新 `migration_ids`；证明新装与旧库迁移后的 Schema 一致。再用准确第一跳安装副本和完整目标三资产演练真实启动、健康、失败恢复与页面基本回归。

未完成第 1、2 步时，现装 09.6 **不能直接在线更新到新增业务表的版本**。这里不设置独立干净 Windows 主机门禁，也不以模拟目标测试冒充正式发布验收。
