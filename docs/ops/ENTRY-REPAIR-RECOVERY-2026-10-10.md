# 工作包 C：同版固定入口修复的中断恢复

日期：2026-10-10。实施顺序只认 [正式路线图](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md)，需求和业务授权只认 [范围锁](../../PROJECT_SCOPE_LOCK.md)。本记录不是第二套开发计划。

## 1. 基线与交付边界

#148 在准确 Head `fd8303337ea22bab91d4d1eb84606dcaa410f4ca` 的三项常规 CI 和独立审查通过后，合并为 `main@d95e256f068a014064f299a3655f2c1758f7b3cd`。之前本机合成版本三门禁证据复用，不重复运行未变更链路，也不把合并当成 Release 或客户升级。

本工作包仅处理已核验当前 Release 安装副本的 `repair-entry` / `recover-entry`：固定根 EXE 和实例记录。新装入口 primitive 保持原合同；程序/Python 修复、升级器和数据库迁移不重建。原始数据库、配置、素材、账号与当前版本指针不写入。

不包含旧 v1/未知锁自动接管、缓存清理、卸载重装、完整 GUI 点击验收、付费请求、N29/N34/N37、生产启停或正式发行。未知旧锁继续阻断，不按 PID 或时间猜测解除。

## 2. 持久事务与恢复契约

- 用 `enterprise-entry-maintenance-plan-v2` 预先绑定两个目标的原件、候选和恢复文件：字节 SHA-256、大小与文件 identity；同时绑定 installation ID、current pointer、完整 Release、独立核验的原生构建和安装/Runtime 目录身份。
- 只有固定 EXE 或实例记录真正变更时才发布候选。已有安装 ID 保持不变；合法但缺实例记录的旧布局按既有资格创建 ID，新 ID 在发布前固定入 plan，不接管外来 EXE。
- 不可改写 plan、结果与自有 marker；kernel runner lease 防止第二执行器抢占活跃操作。共用 maintenance marker 和 KnownFolder Runtime fence 以保留副本的硬链接身份绑定；每个保留副本位于其目标同一卷，支持 D 盘安装、C 盘 Runtime，不做跨卷硬链接或复制降级。
- 取得 Runtime fence 后复查静止、完整源与全部目标，再发布；不终止其他实例。恢复先核验所有目标、备份、候选、pointer、plan 和锁，任意未知/替换/外来状态保持阻断。
- 成功结果前中断：恢复自己拥有的修复前文件；已持久成功后中断：只验证并完成自有锁收尾，不能回滚成功入口。恢复文件身份预先登记，恢复到一半进程退出后仍可重入。
- `ROLLED_BACK` 表示回到修复前状态，不表示入口已修好；如果原入口缺失，不能生成快捷方式或自动启动。需重新明确执行入口修复。
- 最后 common lock 已解除后目录同步不确定：保留既定终态并返回准确同步警告，不假称还有可接管的恢复锁；不承诺断电或硬件故障恢复。
- Setup 维护操作的外部解释器包持久保留。关闭窗口不能证明后台退出，也不得删除仍可能被执行器使用的 payload。拥有者限定清理另属后续工作包。

## 3. 验证与状态

集中核验在当前开发设备、独立 worktree 与全新合成安装副本进行。单元 MZ 字节不是实际原生 EXE。真实验证需准确提交构建的完整三资产 Release、同源编译入口、bundled CPython、当前用户管道和独立恢复进程；没有外部资源时的 SKIP 不算 PASS。

### 3.1 集中定向验证

| 验证层次 | 结果 | 明确限制 |
| --- | --- | --- |
| 入口恢复、入口、Setup 契约、文档及静态构建定向回归 | 148 PASS / 1 SKIP，48.79 秒 | Windows 符号链接权限条件跳过；两个既有 FastAPI 弃用警告。不是整套业务测试 |
| 入口、Setup、程序修复及状态的关联回归 | 153 PASS / 1 SKIP，74.17 秒 | 与上一行有重叠，不能累加为不同测试总数；最终锁身份收口由上一行覆盖 |
| runner 显式解锁失败后关闭 handle 的定向复查 | 1 PASS，1.10 秒 | 最终新增断言验证准确 cleanup warning；不以异常注入代替真实进程验收 |
| 已固定 Inno 编译器编译本次 Pascal Setup 两次 | 1 PASS，3.87 秒 | 仅编译与产物确定性；不是 GUI 安装/关闭窗口/注册表验收 |
| 文档登记及链接检查 | PASS：130 文档 / 11 权威入口 / 21 冻结来源 / 271 链接 | 不改原始需求/客户证据；不产生业务授权 |
| APP_ROOT 写入登记 | PASS：482 项，新增 15 项均在 W47；未知/解析/过期映射/锚点问题为 0 | 静态登记不证明不存在所有动态写入 |

对应快速回归分别按受影响模块运行，不重跑 #148 未变更的完整升级三门禁。最终源码之外的收口只更新文档和测试断言；准确 PR Head、CI 与合并结果由 GitHub 分别记录，不把本节本机结果称为远端 CI。

### 3.2 真实 Windows 同版入口修复与恢复

2026-10-10 北京时间 **23:31:58—23:46:13**，在当前开发机普通桌面上下文执行；pytest 用时 **854.32 秒，9 PASS / 10 DESELECTED / 0 SKIP**。真实发布字节为开发验证产物，不上传或覆盖正式资产。

- 实际源码提交：`309b57991b0280dcc83d14a2245b73ddda34714e`；tree：`5a4e7202feeb9f24c6174b35a23117e00fc74b89`。
- 开发 Release：`ice-2026.08.5-309b57991b02`；完整校验 **2,120 文件 / 74,647,498 字节**，复用固定 CPython 3.14.6 Runtime。`2026.08.5` 仍是源码历史 VERSION，未伪造新正式版本号。
- 三资产 SHA-256：ZIP `9d108866ae1e228667b0ee3bbe3e26cffeead5efbf824f01ec41ea4536c26e1c`；Manifest `b9cdb2ced23535aa6715485045011b76c06437d181571ab5cf142a5ffa25fc7f`；Inventory `8cd3829ecace1cc501bb5f7c30413c4c53b43c36b5fd9785195f94f8947e8bf0`。
- 同一源码记录的原生 EXE 两次确定性编译，未签名，22,528 字节；SHA-256 `570ad6885cae124e39f534bc6a95073212eec0ad4d9c1d8085f5e0888d3987fd`。

| 实际进程场景 | 数量/结果 | 验证内容 |
| --- | --- | --- |
| 修复进程在 locked / prepared / entry_published / record_published / committed 硬退出 | 5 PASS | 第二 bundled-Python/current-user 管道进程显式恢复；提交前回退，持久成功后只收尾；回退后缺入口仍如实未修好，明确重试后修复 |
| 恢复进程在 record_restored / entry_restored 再次硬退出 | 2 PASS | 第三进程可重入完成原件恢复，不重新初始化 installation ID 或业务数据 |
| D 盘安装 + C 盘 KnownFolder Runtime | 1 PASS | 两个卷分别持有自己的 retained/active 硬链接 marker，identity 对应；恢复不跨卷复制锁或误解除其他实例 |
| 实际编译固定 EXE / bundled Supervisor 启动、健康、状态、停止 | 1 PASS | 先恢复入口中断再修复；实际应用生命周期约 68.97 秒。准确 Release/Manifest/pointer、PID/创建身份、停止后的进程和端口均核验 |

每个场景使用独立合成安装、合成 SQLite/配置/画布/素材，不使用客户数据库或密钥。入口缺失和实例记录中的 stale native build-record hash 为显式合成故障；Release/原生证据原件未修改。核验合成业务文件、数据行、固定身份、指针保留及数据库完整性，不证明任意历史 EXE 字节或客户环境均可恢复。

开发机本次普通桌面上下文没有现有 KnownFolder Runtime/cache 根，结果中的 `historical_roots_preserved=false`、`restoration.roots=[]`；因此没有移动或覆盖历史根，也**不能声称做过非空历史 Runtime/cache 的封存恢复试验**。结束时只清理 nonce 标记的新建本轮 fixture 根；完整合成安装和日志留仓库外证据目录。原配置 checkout 保持不变。

证据保存在仓库外 `D:\CodeProject\review-artifacts\t\WPC1`：`REAL-RESULT.json` SHA-256 `85f46d39aada85f283e1d225e79645d7feb35eec4b4201598cc8ccd26db02537`；`real1-junit.xml` SHA-256 `3aa39e447ecb0646396873453bf497b4f9669057d85bac70b182669594cd58c9`；`real-run.log` SHA-256 `7ddbd148ae72b75e0847f881056d71ac10795334d6a6f5072d36062138c4f655`。不提交原始数据库、配置或素材。

### 3.3 阻断处理与剩余门禁

本工作包主要阻断是 D 安装/C Runtime 的跨卷 marker 设计及同字节锁替换的身份判断，已通过同卷保留 marker、预登记 original common identity、核验恢复和定向负例收口。没有为了通过演练放宽未知锁、活跃实例、数据或 source qualification 保护。

本机真实九场景通过只完成 **v2 同版入口修复中断恢复** 的限定交付。旧 v1/未知锁接管、维护缓存拥有者/容量限定清理、标准保留数据卸载/重装、完整 GUI 操作和客户回归仍未验收；`Uninstallable=no` 不变。未发布 Release、未操作生产，不宣称整个阶段 3 完成。下一工作包按唯一路线图收口缓存与卸载/重装链路，不拆成独立日志或 UI 小任务；合并仍需准确 Head 的 CI 和独立审查。
