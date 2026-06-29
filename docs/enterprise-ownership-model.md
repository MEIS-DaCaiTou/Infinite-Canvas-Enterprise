# Enterprise Ownership Model

更新时间：2026-06-29

本文记录企业版当前 owner 模型。企业层只保存归属、授权派生和审计信息，不把上游 JSON 或目录结构改造成新的业务数据源。

## 核心表

| 表 | 主键 | 作用 |
|---|---|---|
| `user_canvas_map` | `canvas_id` | 记录画布真实 owner。普通用户只能访问自己的画布；管理员可代管。 |
| `user_project_map` | `project_id` | 记录项目/文件夹 owner。`default` 是每个用户独立呈现的虚拟默认项目，不是全局共享项目。 |
| `user_conversation_map` | `conversation_id` | 记录 GPT 对话 owner，并配合上游 `x-user-id` 目录隔离。 |
| `user_resource_map` | `resource_url` | 记录本地资源真实 owner，包括 output、上传文件、Comfy input key、本地上传素材。 |
| `user_canvas_task_map` | `task_id` | 记录 Smart Canvas 图片任务 owner。 |
| `user_history_map` | `history_id` | 记录 `history.json` 历史条目 owner。 |
| `usage_logs` | `id` | 记录管理员代管、归属迁移、删除、设置修改等审计事件。 |

## 上传资源 Owner

Task 3G-4A 复用 `user_resource_map` 作为上传文件真实 owner 主表，不新增 `user_upload_map`，也不引入复杂 resource grant / ACL。

新上传资源在企业网关后处理阶段自动归属当前登录用户：

- `/api/ai/upload`
- `/api/ai/upload-base64`
- `/api/ai/import-local-image`
- `/api/local-assets/upload`
- `/api/local-assets/import-urls`
- `/api/canvas-workflows/import`
- `/api/upload`
- `/api/comfyui/upload-base64`

`/api/upload` 和 `/api/comfyui/upload-base64` 只返回 ComfyUI input 文件名，企业层统一记录为 `/assets/input/<name>`。选择这个 key 的原因是现有 `/api/view?filename=...&type=input` 已归一化为同一资源路径，可复用现有直链鉴权和输入复用校验。

## 访问原则

普通用户访问本地资源时：

- 真实 owner 是自己：允许。
- 真实 owner 是他人：默认拒绝。
- 未归属 `unowned`：默认拒绝。
- 资源被自己拥有的画布或对话引用：允许读取和作为运行输入使用。

管理员访问本地资源时：

- 可访问 A/B/unowned 资源。
- 删除、移动、迁移等关键操作必须写审计。

## 画布迁移一致性

画布 owner 变化时不直接迁移 `user_resource_map` 的真实 owner。

管理员把 A 的画布移动到 B 的项目后：

- canvas owner 同步为 B。
- A 上传的原始文件 owner 仍是 A。
- B 通过 canvas 引用回溯授权打开该画布内引用资源，并可继续基于该画布生成。
- A 作为真实 resource owner 仍可直链访问自己的上传文件。
- B 不能因为画布转移而删除、移动、重命名、反推或分类 A 的上传文件。

多画布共享同一资源时也遵循同一规则：转移其中一个画布不会改变资源真实 owner，避免破坏其他画布或原始素材归属。

## 旧数据策略

旧 unowned 上传文件对普通用户默认不可见、不可直链、不可删除、不可作为模型输入。管理员可见，并可在后续后台治理任务中处理回填或迁移。

## 后续扩展

如果未来需要用户共享、可撤销授权、团队空间或素材共享，可单独设计 `resource grant`。当前项目主线不引入复杂 ACL、SaaS 多租户或用户共享。
