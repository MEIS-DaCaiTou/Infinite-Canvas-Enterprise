# 2026.09.3 前置热修记录（历史参考）

基线：公开 2026.08.4，commit fe3fc73b74e0310f9415bc1456b7fe791ef7a0b0。
从开发修复 28ad93735e75a86891e1461e407dc62d0f7f03c9 仅移植 Supervisor、健康探测、Gateway 线程卸载、资源引用缓存和资源归属批量写入。

不改变 main.py、账号/权限模型、数据库 Schema、现有任务格式、API 配置；不引入开发主线的 DATA-MVP-1 或 USER-GOV-MVP-1。任务持久化不在本次止血范围，历史丢失任务不承诺自动恢复。

本地专项 16 项回归和 ownership isolation 通过。使用既有 3.14.6 Runtime 及完整来源证据构建独立 Manifest v2 Release；不重新发布或覆盖 2026.08.4 资产。生产安装只使用离线包、原配置和原数据根，保留旧 Release 作为代码回退目标，禁止重新初始化数据库。

开发分支完整回归中的独立后台 worker 创建 service host 曾被本机 Windows 拒绝（WinError 5）；不得忽略目标生产设备真实 launcher 的启动结果或把本包描述为已经生产验收。

本记录不代表当前客户交付。面向客户准确基线 `2026.08.5-ee4281022d01` 的 V3 健康探针移植、验证与离线升级边界见 `CUSTOMER-RUNTIME-HOTFIX-2026-09-11.md`。
