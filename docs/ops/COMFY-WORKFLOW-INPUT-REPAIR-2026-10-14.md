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

## 同日独立审查修正

独立审查在原 Head d1d0d82 发现冷工作流读取的 await 早于 ordinary Run busy 标记，两次快速点击可重复提交；预检查 catch 的 alert-return 还会让级联误标完成并继续下游。现已在非级联首次读取前设置既有 busy 标记，失败释放标记；级联预检查错误设置 failed 并抛给既有 caller，停止下游，不新增持久临时状态。实际 runComfyNode 的无网络 VM 回归覆盖延迟读取双击仅一次上传/提交、级联读取失败拒绝，以及普通读取失败可释放 busy。已有正常单图 Browser/保存重开证据仍有效，不重复全部 GUI。

## 10.2 测试设备反馈后的续修候选（2026-10-14）

负责人在正式 10.2 测试设备发现：设置页左侧上传与右侧测试画布结果不一致。已批准本次完整「ComfyUI 工作流节点调用修复与适配」工作包。开发来源为 main@ef4c1e4e3d8edff252221764dcdfa889f00939ab；候选分支 codex/comfy-workflow-adapter-20261014，尚不属于正式 10.2。当前只连接一台 ComfyUI；以后多台的节点和模型相同，本包仍指定后端，不增加自动分流。

### 原因与交互

- 原设置页保存 previewValues 和 miniTestNodes 两套素材状态，onRun 按当前页签选值；测试画布开启时，右侧旧素材会覆盖左侧新素材。两处运行按钮重用 runBtn ID，结果又共用一个 URL。上传未检查 HTTP 成功、未等待实际文件引用，旧结果未随输入变化标记。
- 两处视图现在复用 ComfyWorkflowSession，测试输入节点按已暴露字段 ID/名称生成；左、右任何一侧替换素材或参数都同步。移除测试画布中无字段对应关系的额外素材节点添加操作，不改变普通创作画布的自由连线。
- 上传中禁用两处运行；失败清除旧文件引用。每次运行冻结输入/配置，旧结果明确标记。设置页运行改用现有 canvas-comfy-tasks 持久回执，排队期间刷新页面会查询原任务。测试回执 ID 存于浏览器 sessionStorage，不保存提示词、凭据或图片字节。
- 管理员在现有工作流标题下选择已配置的执行后端，默认第一台；普通用户继续「选工作流 → 连素材 → 调必要参数 → 运行 → 输出」。不增加新页面或用户接口模板。

### 模块和协议边界

- enterprise/providers/comfyui.py：完整 HTTP(S) base URL 与路径前缀、上传实际 name/subfolder、一次提交、精确 prompt_id 队列/历史查询、错误和超时。默认 TLS 校验保留；不接受 URL 内嵌凭据/查询参数。需认证的穿透服务尚未增加专用凭据管理，不宣称所有穿透方式可用。
- static/js/comfy-workflow-session.js：一份测试状态、上传/运行互斥、冻结输入、多类型结果引用。设置页仍是原布局；多结果限制显示高度并提供文件链接。
- 后端 object_info 用于新暴露字段的上传控件、枚举和数值范围推断；离线时保留旧配置并提示，不自动重写所有已保存字段。filename_prefix 的旧配置兼容继续复用 #158。
- 两类画布自定义工作流的上传和提交携带同一后端，避免在不同实例之间借用缓存文件名。未指定的旧配置默认第一台；本包不再按队列自动为一次工作流更换执行实例。旧 host:port 配置仍可读取；只有显式保存才更新配置。
- main.prepare_comfy_workflow 只对内置预设应用历史固定节点编号规则，导入图不再因碰巧存在 #14/#23/#144 等编号被改写。结果归档沿用既有图片/视频/音频/文本/文件及节点元数据；设置页不再只取 images[0]。下载失败保留可恢复任务，不返回其他后端的通用预览 URL 冒充已归档结果。
- CanvasTaskJournal 在现有 v1 JSON 上添加 comfy_receipt，保存后端、受理 ID、阶段和最小输出节点类快照；不改变企业数据库 Schema。受理 ID 在轮询前落盘，重启后只查询原任务。HTTP 请求可携带 UUID request_id，重复身份返回原回执并校验 owner，不二次提交；旧客户端仍可省略。提交回包丢失而没有 prompt_id 时保持待核对，不猜测受理成功或自动重投。
- 所有后端均需在平台服务主机可达；浏览器不直接连接 ComfyUI。原 GET/POST 任务归属和设置管理授权继续有效。新任务字段是加法兼容；旧记录无受理 ID 不能凭空恢复。未实现整个 Task/Attempt/费用账本。

### 定向证据与限制

- 21 项定向测试通过，覆盖旧配置/普通画布冷加载、共享上传与冻结输入、单次提交、HTTP 路径前缀与返回子目录、精确队列/执行错误、受理身份持久化/原任务查询、重复请求身份与跨 owner 拒绝、工作流 overlay、设置权限及入口守卫；三处修改脚本通过 node --check。未重跑无关安装/更新演练。
- Browser 使用现有 Codex 内置浏览器和 loopback 隔离副本；真实上传、prompt/history/view HTTP 和归档代码，协议后端不执行 GPU。左上传 A→右同步→左运行、右替换 B→左运行均走通；归档输出像素与 B 对应，两个输出均保留。排队中刷新续查，以及相同请求身份重放，没有新增后端 POST。
- 独立隔离子进程在受理 ID 落盘后退出，新进程恢复并取回原 prompt_id 的结果，新增提交 0。首次合成 MP4 使用浏览器不支持的 MPEG-4 Part 2；后续改用 H.264 样例核验视频展示，不能将编码失败的首次观察记为通过。
- 脱敏证据位于 D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/comfy-adapter-20261014，包含 UI/协议结果、重启探针和截图。测试只使用自己生成的图片/视频，没有调用用户公网/LAN ComfyUI，也没有操作客户配置/数据。
- 用户清单中的 BiRefNet、Qwen 编辑/分层、MiniMax H3、视频深度、SeedVR2、Bernini 等尚未逐项取得实际 API 文件并在 GPU/对应自定义节点上验收；不能按文件名宣称全部适配。分层图片保留实际结果顺序/名称，不承诺工作流没有输出的 PSD；未知格式作为文件交付，浏览器播放受实际编码支持限制。
- 本候选需 Draft PR/CI 和独立审查；main 合并、正式发行、真实网络/TLS/认证及客户验证分开记录。正式 Release 仍为 v2026.10.2，本次没有新的发布或生产操作授权。
