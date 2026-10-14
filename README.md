# Infinite Canvas Enterprise

`Infinite-Canvas-Enterprise` 是独立维护的企业无限画布产品，仓库为 [MEIS-DaCaiTou/Infinite-Canvas-Enterprise](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise)。与 Aidan-OS、Aidan-Canvas、Aidan-App-SDK 不同，需求、分支和验收不能互相套用。

项目基于 `hero8152/Infinite-Canvas@2026.07.6` 的冻结历史来源独立演进；保留归属/许可证，不再要求持续同步。

## 文档入口

更新时间：2026-10-13。本页不复制整份状态和任务队列。

| 需要了解 | 入口 |
| --- | --- |
| 主线、PR、正式应用、工具与客户验证到哪里了 | [当前状态](docs/CURRENT_PROJECT_STATUS.md) |
| 后续开发顺序与验收 | [唯一路线图](docs/roadmap/DEVELOPMENT-ROADMAP-2026-2027.md) |
| 当前模块和数据架构 | [ARCHITECTURE](ARCHITECTURE.md) / [Code Wiki](docs/code-wiki/README.md) |
| 已认可的完整安装更新方案 | [ADR-DELIVERY-001](docs/decisions/ADR-DELIVERY-001-UNIFIED-INSTALL-UPDATE-LIFECYCLE-2026-10.md) |
| 完整文档导航与维护规则 | [文档索引](docs/README.md) / [登记表](docs/document-register.json) |
| 开发、代码边界和安全 | [工作流](CODEX_WORKFLOW.md) / [代码边界](CODE_BOUNDARIES.md) / [安全基线](SECURITY_BASELINE.md) |

当前主线已接入 Runtime、安全、数据升级/恢复、固定入口、同版维护、保留数据卸载/重装和发布目录分页；阶段 3 仍在收口。最新正式应用为 [v2026.10.2](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/releases/tag/v2026.10.2)，准确 source 为 `7da593b`；正式 10.1 已登记 v2 来源的本机准确包升级与必要失败恢复通过，客户部署尚未操作；准确 PR/CI、GUI 限制和现场范围只见当前状态。

当前企业部署仍采用单台 Windows 主机、SQLite 和本地文件。专业服务器/云部署、500+ 员工与 200+ 活跃创作保留为长期约束；Linux、容器和容量扩展待负责人实际需求再实施，业务核心保持可演进边界。方案 Accepted 不等于已经实现。

## 运行入口：先区分源码与安装产品

下面是 Windows **源码开发/旧安装兼容脚本**，不是长期要求客户执行的安装方式：

```powershell
.\启动企业版.bat
.\停止企业版.bat
```

应用入口为 `http://127.0.0.1:8000/`，管理后台为 `/enterprise/admin`，存活/健康为 `/enterprise/live` 和 `/enterprise/health`。内部 Canvas 服务 `:3001` 仅绑定 loopback，不直接暴露给 LAN。

源码首次部署按安全基线配置唯一 JWT 密钥和强凭据；受控新装器管理首次配置；旧安装更新沿用配置/数据库，不复制示例重置管理员。

通用工具接管后的安装可用根目录 `InfiniteCanvas.exe`；未接管旧安装仍可能只有 BAT。固定入口的当前交付与现场验证范围见项目状态，不能把下载或只读检查当作接管完成。

## 验证

以 [测试说明](enterprise/tests/README.md) 与既有 GitHub Actions 为准。默认受影响范围，不无理由手动重跑全套门禁；不要求独立干净 Windows 设备。文档检查无需业务依赖：

```powershell
py -3.11 -B tools/check_docs.py
py -3.11 -B -m unittest discover -s enterprise/tests -p test_documentation_contract.py
```

生命周期和升级测试可能停止服务或修改隔离数据，先读对应测试边界。不得提交真实密钥、数据库、素材、输出、运行日志或 Runtime 构建产物。

## 来源与许可证

历史来源：[hero8152/Infinite-Canvas](https://github.com/hero8152/Infinite-Canvas)。许可证、vendor 声明和原始验收证据保留；它们不是可随意清理的“过时规划”。
