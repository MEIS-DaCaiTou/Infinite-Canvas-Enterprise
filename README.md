# Infinite Canvas Enterprise

更新时间：2026-10-31。本页不复制整份状态和任务队列。

`Infinite-Canvas-Enterprise` 是独立维护的企业无限画布产品，仓库为 [MEIS-DaCaiTou/Infinite-Canvas-Enterprise](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise)。与 Aidan-OS、Aidan-Canvas、Aidan-App-SDK 不同，需求、分支和验收不能互相套用。

项目基于 `hero8152/Infinite-Canvas@2026.07.6` 的冻结历史来源独立演进；保留归属/许可证，不再要求持续同步。

## 文档入口


| 需要了解 | 入口 |
| --- | --- |
| 主线、PR、正式应用、工具与客户验证到哪里了 | [当前状态](docs/CURRENT_PROJECT_STATUS.md) |
| 后续开发顺序与验收 | [唯一路线图](docs/roadmap/DEVELOPMENT-ROADMAP-2026-2027.md) |
| 当前模块和数据架构 | [ARCHITECTURE](ARCHITECTURE.md) / [Code Wiki](docs/code-wiki/README.md) |
| 已认可的完整安装更新方案 | [ADR-DELIVERY-001](docs/decisions/ADR-DELIVERY-001-UNIFIED-INSTALL-UPDATE-LIFECYCLE-2026-10.md) |
| 完整文档导航与维护规则 | [文档索引](docs/README.md) / [登记表](docs/document-register.json) |
| 开发、代码边界和安全 | [工作流](CODEX_WORKFLOW.md) / [代码边界](CODE_BOUNDARIES.md) / [安全基线](SECURITY_BASELINE.md) |

当前源码、预览、main、正式Release及设备反馈分别见[当前状态](docs/CURRENT_PROJECT_STATUS.md#当前摘要与开发基线2026-10-31核验)，本页不维护另一份版本表。角色原人体提交已存在于远端；角色续修、数据/资源收敛及拖拽资产整理仍有本地未提交内容，不能从某个HEAD或旧安装包推定包含全部功能。

当前正式形态为Windows单机/LAN；服务器适配、单企业试部署与桌面小样已获准按[唯一路线图](docs/roadmap/DEVELOPMENT-ROADMAP-2026-2027.md)推进，尚未成为现成Linux/容器/多实例产品。开放PR建议见[文档/PR盘点](docs/ops/DOC-3-DOCUMENT-SYSTEM-AUDIT-2026-10.md#2026-10-31-开发前状态清理与pr盘点)。

## 运行入口：先区分源码与安装产品

下面是 Windows **源码开发/旧安装兼容脚本**，不是长期要求客户执行的安装方式：

```powershell
.\启动企业版.bat
.\停止企业版.bat
```

应用入口为 `http://127.0.0.1:8000/`，管理后台为 `/enterprise/admin`，存活/健康为 `/enterprise/live` 和 `/enterprise/health`。内部 Canvas 服务 `:3001` 仅绑定 loopback，不直接暴露给 LAN。

源码部署按安全基线配置唯一 JWT 密钥；受控新装器管理首次配置和管理员凭据。`ADMIN_USERNAME`/`ADMIN_PASSWORD` 为历史显式 bootstrap 兼容项，普通启动不会用它们重置管理员；旧安装更新沿用配置/数据库，不复制示例重置管理员。

通用工具接管后的安装可用根目录 `InfiniteCanvas.exe`；未接管旧安装仍可能只有 BAT。固定入口的当前交付与现场验证范围见项目状态，不能把下载或只读检查当作接管完成。

## 验证

以 [测试说明](enterprise/tests/README.md) 与既有 GitHub Actions 为准。默认受影响范围，不无理由手动重跑全套门禁；不要求独立干净 Windows 设备。文档检查无需业务依赖：

```powershell
python -B tools/check_docs.py
python -B -m unittest discover -s enterprise/tests -p test_documentation_contract.py
```

生命周期和升级测试可能停止服务或修改隔离数据，先读对应测试边界。不得提交真实密钥、数据库、素材、输出、运行日志或 Runtime 构建产物。

## 来源与许可证

历史来源：[hero8152/Infinite-Canvas](https://github.com/hero8152/Infinite-Canvas)。许可证、vendor 声明和原始验收证据保留；它们不是可随意清理的“过时规划”。
