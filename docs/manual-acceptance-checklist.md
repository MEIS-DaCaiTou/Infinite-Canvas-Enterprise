# Manual Acceptance Checklist

更新时间：2026-06-30

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
- A 在无限画布运行本地 ComfyUI 工作流成功后，Output 节点图片可显示，生成结果可保存到画布和日志。
- A 可在本地上传素材面板上传、预览、移动、重命名、删除自己的文件。
- A 保存图片到素材库后，素材库页面和画布右侧素材库面板中 A 自己可见、可用、可移动、可重命名、可删除。
- A 上传后的 `/assets/input/*`、`/assets/uploads/*`、`/api/view?type=input`、`/api/media-preview`、`/api/image-jpeg` 可正常访问。

### 普通用户 B

- B 的本地上传素材列表不显示 A 的文件。
- B 直链访问 A 的 `/assets/input/*`、`/assets/uploads/*` 返回无权限或 404 风格拒绝。
- B 不能通过 `/api/view?filename=...&type=input` 预览 A 的 Comfy input。
- B 不能通过 `/api/view?filename=...&type=output`、`/assets/output/*` 读取 A 的 ComfyUI output，除非 B 拥有引用该 output 的画布。
- B 不能通过 `/api/media-preview` 或 `/api/image-jpeg` 读取 A 的上传文件。
- B 不能删除、移动、重命名、caption、classify A 或 unowned 的 local-assets path/name。
- B 的素材库页面和画布右侧素材库面板不显示 A、管理员或 unowned 的 `/assets/library/*` 图片。
- B 不能删除、移动、重命名、批量删除、分类、裁剪 A、管理员或 unowned 的素材库 item。
- B 不能把 A 的 URL/path/Comfy name 传给在线生图、GPT 对话、Smart Canvas、Comfy、RunningHub 作为模型输入。
- B 仍可上传和使用自己的文件，核心生成链路不被误伤。

### 管理员

- 管理员可访问 A/B/unowned 上传资源。
- 管理员执行 local-assets delete/move 等关键操作后，审计日志有记录。
- 管理员可看到 A/B/unowned 素材库图片，执行素材库 delete/move/rename/classify 等关键操作后，审计日志有记录。
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
- 普通用户本地 ComfyUI 工作流本身成功时，output owner 记录、显示、画布保存和日志保存不应被企业鉴权误伤。

## 不属于 3G-4A 的验收

- 素材库 library/category/item 完整业务 owner、共享、分组权限、批量迁移和完整素材治理：3G-4B。3G-4A 只做 `/assets/library/*` item 级最小安全兜底。
- WebSocket `new_image`、任务状态、素材库广播隔离：3G-5。
- Comfy/video/图片转换/RunningHub 任务历史隔离：3G-6。
- Provider token、ModelScope Key、中转站、2K/high、模型质量：非企业隔离任务。
- ComfyUI `missing_node_type`、自定义节点缺失、模型缺失、工作流本身 400：非企业隔离任务。
