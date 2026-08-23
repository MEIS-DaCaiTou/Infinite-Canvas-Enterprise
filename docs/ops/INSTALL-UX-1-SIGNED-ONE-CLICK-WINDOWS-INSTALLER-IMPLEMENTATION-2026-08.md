# INSTALL-UX-1：Signed One-Click Windows Installer 实施记录

更新时间：2026-08-24

## 1. 状态与边界

INSTALL-UX-1 Gate A 在仓库中建立 Windows x64 单文件图形安装器的可审查实现。当前状态为：

```text
INSTALL_UX_1_repository_implementation_present=true
INSTALL_UX_1_repository_implementation_independently_accepted=false
signed_public_installer_published=false
```

Gate A 只包含仓库实现、开发设备上的 unsigned rehearsal、临时测试证书结构签名演练、隔离 real-process smoke 和回归证据。它没有创建或修改 GitHub Release，没有使用生产签名证书，没有进入 Gate B，也没有接触生产设备或生产数据。

## 2. 单一安装安全链

正式链保持为：

```text
Inno Setup 7 x64 GUI
→ 内嵌且逐项绑定的三个 Release 核心资产
→ 固定 bundled CPython 3.14.6 -I -B
→ current-user-only 一次性 Windows named pipe
→ enterprise.install_setup_bridge
→ enterprise.fresh_install.install_greenfield
```

安装器仅提供 UX 与受控编排。`install_greenfield()` 继续是 Greenfield 安装、数据库初始化、首个 `super_admin`、配置发布、APP_ROOT materialization 和 pointer-last 的唯一安全权威；没有新增第二套安装、Runtime 或在线更新引擎。

## 3. Release 与构建绑定

- Setup 只接受构建时固定的单一 `release_id`。
- Setup 内嵌且记录 archive、detached Manifest v2、external inventory 的精确文件名、大小和 SHA-256。
- 运行时不访问网络，不发现 `latest`，也不接受任意 URL。
- 三个核心资产进入独立临时 bundle；Setup 自身不进入 payload 或三资产目录。
- canonical Manifest v2 verifier、materializer、fixed CP314 identity 和 APP_ROOT 不可变边界保持不变。
- Inno Setup 官方工具链固定为 `7.1.0` x64；官方安装器和 compiler closure 的 SHA-256 记录于仓库 policy，编译器本体不进入 Git。

## 4. 凭据与进程边界

- 密码不进入命令行、环境变量、临时文件、安装日志、返回 JSON 或 evidence。
- named pipe 使用当前用户 SID 的显式安全描述符、拒绝远程客户端、只允许一个连接。
- 请求为长度前缀 UTF-8，最大 `16 KiB`，字段集合和 schema 固定。
- pipe nonce 可以进入 bundled Python 的命令行，但不包含用户名或密码。
- bridge 先验证 `-I -B`、fixed Python、Runtime Manifest 和 raw APP_ROOT 身份，再导入正式安装逻辑。
- 失败只返回 bounded `INSTALL_*` 错误，凭据字段在交换完成或失败时立即清空。

## 5. Windows UX

安装器提供欢迎、安装模式、安装目录、环境检查、首个管理员、安装进度和完成页面；默认采用当前用户 Known Folder，不申请管理员权限。自定义目录必须位于本机固定磁盘、为 Greenfield 空目录、无重解析风险并与临时 payload 不重叠。

安装成功后可创建开始菜单或桌面入口，入口指向已发布 Release 内的正式 `start/status/health` wrapper，不指向临时目录，也不直接启动 `main.py`。INSTALL-UX-1 不创建卸载器、repair、machine-wide 安装或静默企业部署能力。

## 6. Gate A 证据范围

仓库外 Gate A evidence 记录：

- 两次 unsigned Setup 编译及确定性身份；
- 临时测试证书 Authenticode 结构签名与验证；
- 真实 GUI Setup → fixed CP314 → setup bridge → `install_greenfield()`；
- exactly-one `super_admin`、bootstrap audit、Manifest/current-release 与 APP_ROOT 结果；
- Runtime real-process lifecycle、进程和端口回收；
- focused/relevant regression、compileall、APP_ROOT audit、secret/local-path scan 和一次最终 enterprise full suite。

这些证据只属于开发设备隔离验证，不是 clean Windows Gate B 验收、生产签名、公开发布、正式 Release 或 production validation。完整哈希和逐项结果位于仓库外 review bundle，并由最终 Draft PR 正文引用。

## 7. 后续门禁

只有 Gate A 经独立审查、合并，且项目负责人另行批准版本与正式代码签名条件后，才能进入 Gate B。Gate B 仍需从精确 merged main 重建、生产 Authenticode SHA-256 + RFC 3161、clean Windows 安装矩阵、远端重新下载校验和独立发布决定。

```text
database_migration_supported=false
database_restore_supported=false
OPS_3B_started=false
production_touched=false
```
