# Manual Acceptance Checklist

更新时间：2026-06-29

本文记录企业隔离任务的 A/B/admin 人工验收项。每个任务 PR 描述应写明已执行项、未执行原因和风险。

## 通用准备

- 使用最新 `main` 或目标 PR 分支。
- 确认未提交运行时数据、真实数据库、缓存、API Key、Token、Cookie、`enterprise.env`、`API/.env`。
- 确认没有修改本任务禁止的上游覆盖区，或已在 PR 描述说明原因、风险、回滚方案和上游同步影响。
- 使用普通用户 A、普通用户 B、管理员三个角色。

## Task 3G-4A 上传文件隔离

### 普通用户 A

- A 可在在线生图上传参考图并生成。
- A 可在 GPT 对话上传附件并发送。
- A 可在 Smart Canvas 上传图片节点并生成。
- A 可在经典画布拖拽/粘贴图片并保存。
- A 可在 ZImage / Angle / Enhance / Klein 路径上传输入图并运行。
- A 可在本地上传素材面板上传、预览、移动、重命名、删除自己的文件。
- A 上传后的 `/assets/input/*`、`/assets/uploads/*`、`/api/view?type=input`、`/api/media-preview`、`/api/image-jpeg` 可正常访问。

### 普通用户 B

- B 的本地上传素材列表不显示 A 的文件。
- B 直链访问 A 的 `/assets/input/*`、`/assets/uploads/*` 返回无权限或 404 风格拒绝。
- B 不能通过 `/api/view?filename=...&type=input` 预览 A 的 Comfy input。
- B 不能通过 `/api/media-preview` 或 `/api/image-jpeg` 读取 A 的上传文件。
- B 不能删除、移动、重命名、caption、classify A 或 unowned 的 local-assets path/name。
- B 不能把 A 的 URL/path/Comfy name 传给在线生图、GPT 对话、Smart Canvas、Comfy、RunningHub 作为模型输入。
- B 仍可上传和使用自己的文件，核心生成链路不被误伤。

### 管理员

- 管理员可访问 A/B/unowned 上传资源。
- 管理员执行 local-assets delete/move 等关键操作后，审计日志有记录。
- 管理员把 A 画布移动到 B 项目后，canvas owner 同步为 B。
- 画布转给 B 后，不直接把 A 上传资源 owner 改成 B。
- B 可打开被转移画布中的上传图片，并可继续基于该画布生成。
- A 作为真实 resource owner 仍可直链访问自己的原始上传文件。
- 多画布共享同一上传资源时，转移一个画布不改变资源真实 owner。

## 回归项

- PR #24 项目 / 文件夹 / 画布列表隔离不回归。
- PR #28 历史记录隔离不回归；历史删除不物理删除 output。
- PR #30 后端设置权限不回归；普通用户不能管理 API Provider / Key / Base URL / 工作流设置。
- PR #32 设置入口体验不回归；普通用户隐藏 API 设置 / 工作流设置，管理员路径不嵌套。
- 普通用户在线生图、GPT 对话、Smart Canvas、经典画布、ZImage / Angle / Enhance 仍可正常使用。

## 不属于 3G-4A 的验收

- 素材库 library/category/item 完整 owner 和批量管理：3G-4B。
- WebSocket `new_image`、任务状态、素材库广播隔离：3G-5。
- Comfy/video/图片转换/RunningHub 任务历史隔离：3G-6。
- Provider token、ModelScope Key、中转站、2K/high、模型质量：非企业隔离任务。
