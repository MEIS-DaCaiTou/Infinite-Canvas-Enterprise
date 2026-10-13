# ComfyUI 单图工作流的字段与画布输入修复

日期：2026-10-14。基线：`main@e89a288fe1ce8e5066ebebe1971e69bf5d4c7945`。本记录描述独立修复候选；不是合并、正式 Release 或客户部署验收。正式 Release 保持 `v2026.10.1`。

## 问题与使用效果

负责人提供正式 10.1 内网/公网截图及最小复现：LoadImage.image 与 SaveImage.filename_prefix 各暴露一个字段，原设置页用 `filename/file` 子串把文件名前缀识别成图片。普通画布因此要求两张图片，在发送请求前阻止只有一张真实图片的工作流。智能画布还可能用历史示例文件名代替缺少的连接，且无提示词的自定义工作流受通用提示词检查阻止。

操作保持现有流程：选择工作流 → 连接图片 → Run ComfyUI（智能画布原有“运行”）→ 结果回填。没有新增页面或配置步骤。文件名前缀显示为文本；缺少输入时列出名称和节点/输入，例如 `请连接 ComfyUI 缺少的输入：图片 (#8.image)`。

## 实现与兼容

- `static/js/comfy-workflow-fields.js` 共用字段推断、旧配置读取修正、输入角色、缺少素材检查、字段值转换和节点参数映射。设置页、普通画布、智能画布及智能级联均调用它，HTML 同步加入脚本并更新版本引用。
- `filename_prefix` 优先认作普通参数，图片扩展名或较长前缀也不会变成图片/提示词。通用 `filename/file` 子串不再足以推断图片；真实图片、视频、音频仍根据具体输入名或文件扩展名识别，既有其他人工配置保留。
- 加载历史配置时，只把 `filename_prefix` 的错误媒体控件改成 `text`，保留字段 ID、节点、标签、顺序和默认值；空缺默认值可读原工作流。读取不写配置文件，现有画布不要求先打开设置页或删除重建；用户正常保存配置时落盘正确类型。未改数据库 Schema 或工作流节点连接。
- 两类画布按各媒体类别的字段顺序匹配已连接素材，在上传/提交前检查缺失。历史媒体 default 是示例文件名，不能满足画布实际连接要求。第一提示词使用连接文本或默认值，其他提示词保留自己的参数/默认值；设置测试画布采用相同顺序。数值、布尔、下拉与随机种子复用已有控件。
- 智能画布自定义模式在读取工作流后按真实字段检查，不再要求每个自定义工作流都有提示词。普通文生图、增强、编辑模式保持原有入口。
- 设置页收到 `data.error` 后显示失败，避免 HTTP 200 错误被写成“运行成功”。
- 后端 `is_comfy_input_media_value()` 排除 `filename_prefix`，包括看起来像图片文件的前缀，避免作为输入素材探测/同步。后端提交、查询、归档、Gateway 授权和原有任务回执继续复用。

## 定向验证

自动验证入口：

```text
python -m pytest -q enterprise/tests/test_comfy_workflow_fields.py
python -m pytest -q enterprise/tests/test_env_1b1a_static_build.py -k "repository_static_tree or app_root_write_audit_anchors"
node --check static/js/comfy-workflow-fields.js
node --check static/js/comfyui-settings.js
node --check static/js/canvas.js
node --check static/js/smart-canvas.js
python tools/check_docs.py
```

字段测试执行实际共用 JS，覆盖错误配置不变更原对象/修正幂等、单图加前缀、真正缺图/遮罩的准确名称、视频音频、独立负向提示词、数字/布尔/下拉/随机值和空缺参数。后端测试提取实际素材检查函数，证明前缀不会进入素材同步列表，真实 filename/mask/video/audio 保留。静态构建检查验证新共用脚本进入现有离线资源闭包；没有重跑安装维护全套本机回归。

## Browser 与实际请求路径

隔离副本使用开发 Python 3.11、真实 Canvas application 和 Gateway、合成账号/数据、回环 ComfyUI 协议服务（50165/50166/50167）。协议服务响应上传、prompt、history、view，保存实际提交的节点图；不执行 GPU 或第三方自定义节点计算。

| 路径 | 结果与证据范围 |
| --- | --- |
| 设置页加载旧 image 类型前缀 → 上传一张图 → 运行测试 | 文件名前缀是文本；实际 prompt 的 `8.image=uploaded.png`，`6.filename_prefix=ComfyUI`；返回本机归档输出 |
| 普通画布缺图提醒 → 连线 → Run ComfyUI → Output | Browser 原生 alert 操作超时，负责人协助点击“确定”、连接图片并运行；新标签及 reload 核验只计一张图片、输出及连线保存 |
| 智能画布连接图片 → 选择目标 → 运行 → 回填 | Browser 实际拖线与点击；无提示词可运行；实际节点图与设置页一致，reload 后图片自然尺寸 240×160、连线和结果保留 |
| 保存工作流配置 → 重新加载 | 持久前缀类型为 text，字段 ID/默认值保留；两类画布此前已直接使用未保存修正的旧配置成功运行 |
| 最终后端请求，前缀设为 result.png | `/api/workflows/custom/qa-depth.json/run` 返回归档图片；协议调用记录没有把 result.png 当输入素材访问 |

Browser 为已启用 Codex 内置浏览器，无需安装或 Playwright 回退。默认桌面视口随面板为 1280×720 / 942×704，未扩大移动端矩阵。页面身份、非空内容、无错误覆盖层、控件、连线、执行及重开均核验；控制台保留已有 Tailwind 浏览器构建警告，没有观察到本修复相关 JS 错误。

脱敏本机证据目录：`D:\CodeProject\Infinite-Canvas-Enterprise-Artifacts\t\comfy-input-fix-20261013`。包含 `run_qa.py`、`resume_qa.py`、`prepare_canvases.py`、`check_results.py`、`qa-result.json`、协议调用记录及 `settings-result.jpg`、`classic-reopened.jpg`、`smart-reopened.jpg`。截图绿色图块是合成输入/输出，不能作为深度/姿态模型质量证据。后端两行修复后仅重启所属隔离进程验证影响路径，保留已完成前端证据。

## 交付边界

- 本包不操作截图中的公网/LAN 主机、不修改客户配置/素材/数据库、不发布或覆盖正式 10.1。
- 真实 ComfyUI GPU、自定义节点版本、各客户模型/显存与网络依赖没有在本机验收；设置页已运行的客户截图是问题定位来源，不是新候选现场验收。
- Draft PR 和其准确 Head CI 供独立审查；主线 CI、候选 CI、正式发行和客户验证分别记录。#123/#157 继续独立待审，不夹带到本修复。
- 唯一路线图顺序不重建；先解除这项直接创作阻断，再按既定可靠任务与供应商工作包推进。
