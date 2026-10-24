# 产品集成修复：供应商图像适配、个人模型与企业入口

记录日期：2026-10-13。main 基点 `bc33339fd11df4c0303f29257766f0f2e53560fe`；功能提交 `4bdd9a16074abac86ce47fc1e81b55bfb12cf63c`；[Draft #156](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/156)。本文记录该工程包，不替代 [CURRENT](../CURRENT_PROJECT_STATUS.md) 或[唯一路线图](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md)。尚未合并 main、未发行。

## 实际问题与模块边界

- 正式 10.1 的后台管理员创建表单缺少后端所需确认，当前 main 已有相应表单。候选补齐重置密码、启用/禁用、软删除和权限覆盖清理的原因/确认；创建管理员仍由现有超级管理员策略保护，普通管理员不因此获得越权能力。软删除不移除客户素材或 Owner 记录。
- 长期供应商适配由项目内置维护。`enterprise/providers/zhenzhen.py` 集中维护模型家族、别名、画幅、分辨率及支持字段，并构造一次提交；`provider_image_profiles.py` 内置能力优先，未知新模型才用临时配置。普通用户无需维护模板。
- 模块接受现有 HTTP client、地址、请求头和已转换参考图，不写数据库/素材目录，不调用 Windows API。鉴权、部分供应商分派、尺寸推断、异步查询、解析及归档仍在 main.py；本包是图像能力和请求构造提取，未完成整个 Provider 体系的模块化。
- 两类画布共用 `static/js/model-picker.js`：节点就地搜索、我的模型批量勾选、常用/全部切换。账号偏好由 `enterprise/user_model_api.py` 和 `user_model_preferences.py` 保存在 DATA_ROOT，不改企业数据库 Schema，不更改已有节点的模型身份或授予管理权限。
- 素材 Chrome 扩展复用已登录平台页的同源请求，只开放 `/api/config` 用户投影及素材导入路径；不读取 JWT、不放宽 CORS/认证。源码版本 1.0.1，未安装/发布扩展。

## 已确认图像契约

依据负责人此前提供的 [Zhenzhen 文档](https://gpt-best.apifox.cn/)、[OpenAPI 目录](https://gpt-best.apifox.cn/llms.txt) 和[供应商公开客户端](https://github.com/T8mars/Comfyui-zhenzhen/blob/main/Comfly.py)；外部接口仍可能演进，本表只描述本提交内置目录。

| 家族及别名 | 该提交的请求差异 |
| --- | --- |
| nano-banana、nano-banana-hd | aspect_ratio；不发送 image_size/quality，hd 固定 4K |
| nano-banana-2、nano-banana-pro | aspect_ratio + 1K/2K/4K image_size，不发送 quality |
| nano-banana-pro-2k、nano-banana-pro-4k | 档位在模型名称固定，不另发 image_size |
| gemini-nano-banana-2.1 | 14 种明确画幅及 auto、1K/2K/4K；9:21 不支持 |
| gemini-3.1-flash-image、gemini-3.1-flash-image-preview | 14 种画幅与 512/1K/2K/4K |
| gemini-3.1-flash-lite-image | 14 种画幅，不发送 image_size |
| gpt-image-2 | 像素 size 与质量；mask 沿用既有 multipart 编辑 |
| seedream-v5-pro | 像素 size，不发送 quality |

上述 12 个模型/别名的文生图和参考图采用已确认 JSON `/v1/images/generations`，参考图放 `image` 数组；失败不探测另一个付费提交入口。以精确 `ai.t8star.org` 或明确 zhenzhen 供应商 ID 选择，不将近似平台/国内服务一概套用。已内置模型优先于历史模板，API 设置的临时兼容面板默认折叠。

## 功能提交的验证

- 请求构造 MockTransport 40 passed：12 个内置模型/别名的文本/参考图、无模板调用、正确字段/Bearer、旧平台协议、错误不重提及其他平台/旧客户端兼容；后续新增头部断言仅重跑对应 1 项，通过。没有付费请求。
- 普通成员真实临时 Gateway 在无手动模板时读取 5 个已选模型能力与 image-params；两类画布实际选择模型，模型默认、512/1:8 及参数标题正确显示。管理员临时面板默认折叠、可展开/折叠。
- 此前有效的 22 项后台/配置检查、18 项正式 10.1 临时包与候选 HTTP 观测、个人偏好/同源边界、实际 JS 请求和模型列表保存/刷新证据继续复用。文档更新不将这些历史证据写成本轮重跑。
- 4bdd9a1 的 [Enterprise/Runtime](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/38351037175) 与[文档](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/38351037192) 三项常规 CI 最终成功；fixed EXE real opt-in 跳过。后续文档提交另看准确 CI。

证据原件保存在仓库外 `D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/product-integration-20261013/`；主要文件为 MODEL-ROUTING-AND-INTEGRATION-REVIEW.md、supplier-http-evidence.json、ci-final-builtin.json 和 GUI PNG，不提交 QA 数据库、账号密钥或服务日志。临时 loopback 服务已停止。

## 未验收与技术债

真实付费调用、供应商其他视频/Flux/BFL/层分解/原生 Google 协议未在本包验收。Chrome 扩展宿主、Photoshop 真实宿主及 PS 企业认证仍有缺口；PS UXP 源码已有资产浏览、置入/打开、PNG 导出、生成/查询/聊天及 WS 接线，不等于真实企业环境全部可用。创建/重置新凭据的 GUI 最终提交未执行，API/真实表单证据不替代该验收。历史 MutationObserver 错误仍在。

main.py 和两类画布大文件仍有耦合。下一次关联业务改动按完整提交/查询/鉴权/错误边界提取 Adapter，新增参数交互尽量共用；不把本包称为完整 Provider 重构，不预建动态插件或通用参数语言。当前单台 Windows 主机；服务器/云和容量保持设计约束，待实际需求实施。

## 2026-10-16 个人模型与工作流可用列表续修候选

Base main `39f4b02d232142c4ede66f0133b759b32178d70f`；独立分支 `codex/model-workflow-selection-20261016`，未合并/发布。个人模型使用现有 `comfy-outputs.css` 弹窗头部、遮罩、主题和圆角按钮，`model-picker.css` 只补搜索、列表和勾选样式。保留节点旁搜索/批选/取消/账号保存，不增加设置页面，不改已有节点模型。

原列表枚举全部内置文件，没有可用状态。配置新增可选 `enabled`；原设置页增加「在画布调用列表中启用」勾选并保存。默认列表只返回启用项，设置页 `include_disabled=true` 查看全部。未配置的 shipped 工作流默认不暴露，历史已配置 fields、用户自定义/覆盖继续可用；明确 false 才停用。停用不删除图或素材，两类画布保留停用/移除工作流原身份并提示改选，不能自动切换执行另一工作流。设置页运行和画布 workflow-custom 提交前检查服务端保存状态。固定本地专用模式继续可用。

「本地」是平台服务端调用已配置的 ComfyUI，不是每位员工电脑执行模型：页面 → `/api/generate` → ComfyUI `/prompt`、`/history` → 平台归档。后端地址复用工作流设置的地址列表与工作流执行后端配置，支持现有完整 HTTP(S) 地址和路径前缀。文生图固定 `Z-Image.json`，细节增强固定 `Z-Image-Enhance.json`（原可选超分接 `upscale.json`），图片编辑固定 `Flux2-Klein.json`，角度控制固定 `2511.json`。工作流名与节点参数仍由程序绑定，页面不能任意替换为另一张图；自定义组合继续使用导入及 ComfyUI 自定义模式，本轮不重构这些入口或增加多机调度。

验证：受影响 overlay/字段契约/账号偏好 9 项通过；随后针对已移除工作流补真实两类画布函数 VM，验证旧身份不改、缺项零加载、目录/详情之间失效仅查一次且不递归重绘。独立审查定位智能画布缺少加载 guard，已修复；经典画布同类问题在 Browser 验证时发现并修复。Browser 使用实际两类画布和设置页、固定隔离 actor + 真实偏好存储，验证搜索、批选、保存、取消、空结果、原模型保持、启停保存及列表同步。1280×720 明/暗主题、390×844 窄屏已截图，深色 checkbox 被既有主题覆盖的问题修复后重验。页面身份、非空、无错误覆盖层和目标交互通过；无新增相关控制台错误，经典画布已有 Tailwind 开发提示保留。

证据：`D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/model-workflow-selection-20261016/`。不冒充正式 Gateway 登录、真实 GPU/付费生成或客户验收。既有账号隔离/同源验证复用；无 Schema、权限、费用、安装更新或正式 Release 变化。回滚为撤销本 PR；旧程序忽略 enabled 字段，不保证仍隐藏停用项；工作流图及素材字节保持。审查及准确 Head CI 以对应 PR 为准。

## 2026-10-19 贞贞视频协议路由候选

Base main `e0dfa843d4bec3ff9c05a6f2ee25337a3687fc3e`；独立分支 `codex/zhenzhen-video-routing-20261019`，候选不改变正式 10.3。`model_catalog.py` 仅纠正已证实的 MiniMax-H3 与 Kling image 分类；`zhenzhen_video.py` 维护精确 ID 的能力和纯请求/查询构造。未知型号保留现有协议，不从目录出现推断全部兼容。参数、受理 ID 与结果仍沿用现有任务中心、账号隔离和归档，无新 Schema、权限、页面或队列。

| 精确型号 | 选定提交 / 查询 | 当前维护边界 |
| --- | --- | --- |
| grok-imagine-video-1.5 | `/v1/videos` / `/v1/videos/{id}` | seconds 字符串；480/720/1080p，1–15 秒；多参考图最高 720p |
| MiniMax-H3 | 同上 | seconds 字符串；768P/2K，5–15 秒；imageUrls/videoUrls/audioUrls |
| wan3.0-video、wan3.0-video-prime | 同上 | duration 整数；480P/720P/1080P，当前最多30秒；image_urls/video_urls/audio_urls |
| grok-imagine-video | `/xai/v1/videos/generations` / `/xai/v1/videos/{id}` | duration、image 或 reference_images；480/720p，参考图模式最多10秒 |

原始依据：[Grok兼容提交](https://gpt-best.apifox.cn/api-472416532)、[MiniMax](https://gpt-best.apifox.cn/api-495802284)、[Wan3](https://gpt-best.apifox.cn/api-505897644)、[xAI格式](https://gpt-best.apifox.cn/api-498242621)、[参考图限制](https://docs.x.ai/developers/model-capabilities/video/reference-to-video)。供应商文档与公开目录可能演进；API Key 仍从现有管理员配置读取，不落任务回执。每个新协议只提交选定入口一次，不用404、5xx或未知回包探测另一个付费接口。已接受的新回执绑定查询模式；历史 generic/v1/v2 回执继续查原路径，不随新映射迁移。两类画布复用现有选择器/按钮，保留旧参数供显式修改；不支持的选项阻止新开启，已开启的可取消，服务端提交前校验，不静默丢参考素材。

验证：首轮受影响 Python 55 passed；后续边界/旧回执定向36 passed（重叠不相加）；三份 JS 语法通过。Browser 使用隔离 loopback、固定测试身份、模拟供应商和自有视频，1440×1000、1024×768 检查页面身份、非空、无错误覆盖层、控制台与截图。两类实际控件切换模型/参数、禁用不支持项和保存重开通过；经典画布模拟生成/归档通过。Browser plugin 未提供，使用已安装 Edge 的 Playwright，无新依赖。初始夹具返回非MP4字节，改用自有有效MP4后实际video元数据加载通过；隔离目录没有固定Runtime媒体预览工具，`/api/media-preview`仍415，作为缩略图未验收限制保留，不伪报控制台全净。既有Tailwind开发警告保留。

真实验证仅使用自有蓝色立方体提示词：Grok1.5 1秒、MiniMax-H3 5秒768P、Wan3 5秒480P，各一次 POST `/v1/videos`；受理身份写 journal 后故意结束前台轮询，再读原回执 GET 续查并归档本地MP4。三项 succeeded，未再次生成。MiniMax JSON提交本轮真实成功，消除了其文档仅列multipart的兼容疑点。累计用量差额6.670022/总授权10，包含前轮1.300022；不是产品费用账本或逐任务结算。未覆盖原生Grok账号通道、Wan prime、参考音视频/多图、每一分辨率/时长或全部目录模型。

独立 Review 定位并修复经典画布时长blur显示15但仍提交旧60的问题；真实UI与定向复审 `NO_ACTIONABLE_BUGS_FOUND`。技术 Review 不等于 GitHub Approval。回滚撤销本候选；新模式回执需保留当前版本续查，旧程序不能保证识别新模式，不能删除回执或重提替代。证据位于仓库外 `zhenzhen-model-routing-20261019/`，凭据/客户素材不入仓库。准确提交、CI和合并状态见原PR。

## 2026-10-19 图片编辑与图层输出候选

分支 `codex/zhenzhen-image-contracts-20261019` 堆叠于 [#179](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/179) 精确 Head `bd341fb80bdad1e2a8972eb6c31aa03d3c7a2e7e`，不修改 main 或该视频分支。沿用 zhenzhen.py 和既有图片任务/归档；精确新增 `gpt-image-2-all`（JSON文生图 generations、参考图 edits，不支持当前维护范围外的mask）和 `seedream-v5-flash/layer-decomposition`（单原图 generations，image为标量，输出透明PNG）。不猜测名称相似的型号别名，也不强行把所有绘图入口归为一种请求。协议源：[文生图](https://gpt-best.apifox.cn/api-510695314.md)、[JSON编辑](https://gpt-best.apifox.cn/api-513955033.md)、[图层拆分](https://gpt-best.apifox.cn/api-522995149.md)；后者文档仍标developing，不代表上游账号真实开放。

特殊输出复用现有图片结果和任务详情：多个图层分别归档，保留层名、z_index和有限坐标/说明字段；RGBA不转换JPEG。相同像素的不同层不合并，单层同时返回URL/base64只收一次；嵌套result.images和旧URL列表继续兼容。`image_outputs.py` 只做有界元数据提取，任务中心继续先校验已有资源归属。经典画布完成/续查优先image_items并保留旧images fallback；Browser发现智能画布生成/恢复映射只复制尺寸，已沿用既有对象展开写法保留图层字段；结果保存重开、作为后续参考图继续使用现有操作，不新增图层编辑器、PSD合成或页面。无Schema、权限、供应商自动重提、Runtime或安装更新变化。

必要验证：请求构造/旧模型兼容41 passed；图像恢复、实际main归档/重开及任务目录42 passed，修复后同一实际main图层用例1 passed（范围重叠不相加）。新用例涵盖单原图、双参考JSON字段、错误/超时只一次提交、未知字段不落元数据、透明PNG及不同层同像素。首轮新夹具缺kind:image被现有引用筛选拒绝，补足真实客户端字段后通过，保留失败证据。原JS共享查询和视频重开脚本继续通过。

独立Review定位嵌套图层先收裸URL再收对象导致重复归档；修正标量及URL-list两种情况，定向复审 `NO_ACTIONABLE_BUGS_FOUND`，准确Head CI以原PR记录为准。不是GitHub Approval。Browser使用固定隔离身份、MockTransport和自有透明PNG，复用现有两类画布控件；模型选择、双图层输出、名称/层号保存重开、1440×1000与1024×768检查通过，页面身份/非空/无错误覆盖层及控制台无新增运行错误；既有Tailwind提示保留，截图及结果记录仓库外image-browser-qa.json，不替代真实Gateway或上游图层效果验收。

真实 `gpt-image-2-all`：文生图单次生成并归档成功；两张自有96×96色块的JSON编辑单次提交返回HTTP500，无受理ID，保留PROVIDER_SUBMISSION_UNKNOWN，未重复提交或切换付费入口。这一结果不能区分当前账号通道故障与接口多图格式限制，编辑验收仍未通过，不据此宣布全目录可用。累计使用差额6.710022/同一授权总计10，未知编辑保留预留，不将无即时扣费视为未受理；不进行第二次付费探测。图层按输出数量收费且当前证据不能可靠限定上界，未执行付费拆层。既有Nano Banana/Seedream等能力沿用原验证，不假装本轮全部重测。

回滚撤销本包，保留原图片/回执；旧版本可继续读取普通URL但可能不展示层名/元数据。正式Release保持10.3，候选未合并，不操作客户设备。后续先收口编辑可用性和各Draft候选兼容，再按独立授权合并/发行；安装入口修复现场成功与跨版本升级未验收分别保留。

## 2026-10-22 视频成片、预览与运行状态收口

Base为待批准#195 fc5d3a8，独立分支codex/video-results-closeout-20261022；#193/#194已合入main2655bd5，正式版本仍10.4。最小受控复现：`RUNNING + preview_url=preview.jpg + last_frame_url=end.png` 原解析返回两条视频URL，原查询判succeeded。这会导致任务提前结束，甚至下载图片内容保存成MP4。

本包提取既有成片解析到providers/video_outputs，排除明确图片/音频、尾帧及来源身份，成片优先于预览回退。签名无扩展名链接及原数据嵌套保留。失败、排队/运行先于URL判定，已受理预览继续原ID GET；实际image/audio响应不存为MP4并保留原任务。无新Schema/UI/付费接口/重提策略，旧任务/部门归属/费用权限不变。

定向64项通过，最后预览优先级修正后新模块7项通过，重叠不累加。真实main归档用例首轮因夹具误用旧output目录失败，按现有assets/output契约修正后通过；无产品权限放宽。Mock证明一次POST后先保存受理，再原ID GET到真正成片；不是实际账号或GPU验收。准确Review、Head/CI与发行状态记本候选PR。

本轮读取[供应商目录](https://gpt-best.apifox.cn/llms.txt)与[原JSON编辑页](https://gpt-best.apifox.cn/api-513955033)：该页现归“123、未开放”但仍标released，不能据此确定原500根因、请求终态或账号可用性；不再次生成、不批量禁用。此前授权预算累计记录仍为6.710022/10，本轮新增付费0。本机8188无ComfyUI，真实工作流验收保留条件限制；继续实际使用缺口，不扩展RunningHub。


## 2026-10-24 成员管理往返导航修复候选

依据负责人10.7现场截图及复现路径，原成员链接在canvas-list iframe中加载后台，后台返回/又在该frame嵌入index，真实浏览器证实两套侧栏及账号栏。首轮点击项目仍响应，不把现场完全卡死列为受控复现。

修正仅为成员入口和后台返回声明target=_top，同时更新canvas-workspace-boot及其引用的缓存参数；不添加路由框架、页面、数据库迁移、权限或付费行为。候选版本10.8，准确构建源由Manifest固定；10.7原记录和资产保持。新安装包先按现有离线维护交付，未声明新在线路径；7→8同Schema4维护沿用既有引擎，本轮不重跑完整安装恢复矩阵。

本机真实Edge+既有Python Playwright，1760×960及390×844；现有main/业务/归属/SQLite/Gateway注入、合成身份Cookie。原代码返回后root_shells=2；修正后5次管理员往返、企业项目筛选、网格/列表、两类画布打开、旧嵌入后台返回、负责人独立入口及普通员工403均通过，root_shells保持1。补齐夹具原user_model_api后最终无页面/控制台/HTTP错误、无生成POST；此前两次404仅来自夹具缺该路由，不计为产品缺陷。Tailwind自带开发提示保留，无框架错误覆盖层。实际登录、客户设备及完全卡死的其他现场因素未验证。后台定向11项通过，JS语法及文档检查随准确Head记录。独立Review结果为NO_ACTIONABLE_BUGS_FOUND，仅审查本次程序差异及关联路径，不代表排除全部现场因素。

证据和脚本集中仓库外产品artifact根D50，不提交客户原图或浏览器原始输出。合并、正式发布和现场结果按原PR与CURRENT分别更新；撤销本补丁只恢复链接目标/缓存参数，无数据回滚。
