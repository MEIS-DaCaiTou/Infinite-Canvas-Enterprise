# 产品集成修复：供应商图像适配、个人模型与企业入口

<a id="video-multisize-live-20261128"></a>

## 2026-11-28 SUP-04.VID／MKT-02.D 少量真实验收与预算收口

源码先行保全完成后，负责人另批本批新增总费用不超过 10 元、最多 2 个视频＋5 个图片任务；失败计数，不自动重投未知受理。仅旧工坊 `ai.t8star.org`，复用原加密调用来源、持久任务／原供应商 ID 查询及归档。没有新增业务协议实现、任务系统或生产操作；本地测试辅助脚本、实际媒体、原回包和凭据均留在仓库外。

恰好 2 个视频和 5 个单张图片生成任务，七项均 succeeded 并归档；不含前置一次新来源未授权的本机 403（原任务不存在、账单未变、没有供应商提交，记录保留，补来源 grant 后才正式验收）。没有重投七个已受理任务或以 n 扩大数量。

| 实测项目 | 实际产物 | 本机完整链路耗时 | 原平台任务 ID |
| --- | --- | --- | --- |
| Seedance Mini · 4 秒／480p | 560×752／4.042 秒 | 188.16 秒 | `canvas_video_44e9490782c94caa8f97e10216c49cc7` |
| Grok 1.5 · 4 秒／480p | 480×640／4.042 秒 | 87.40 秒 | `canvas_video_339e4e931fbe4db789d50e668b7a3dd5` |
| 多尺寸 · portrait | 1200×1600 | 50.33 秒 | `canvas_img_b686f0f2eea6429c8838dfd4e4c05bc2` |
| 多尺寸 · story | 1080×1920 | 61.26 秒 | `canvas_img_4804a83067b84d35ba86afdf19b3b31a` |
| 多尺寸 · poster | 1600×1200 | 52.66 秒 | `canvas_img_64927ad17c124dafb0329f1a73104850` |
| 多尺寸 · cinema | 2520×1080 | 68.32 秒 | `canvas_img_4529212ca90b4457a47dcce6ec343d38` |
| 多尺寸 · custom | 1440×1800 | 63.06 秒 | `canvas_img_4f1f60f2d59c4e9da134522bc64fe12e` |

两条视频使用相同 4500×6000／6,120,585 字节服装人物 JPEG，原字节上传，比例 3:4；Mini 首帧走 `/seedance/v3/contents/generations/tasks`，Grok 1.5 走 `/v1/videos`。真实 supplier ID 在生成后即写原 journal；本机原任务读取、下载归档及 ffprobe H.264 解码信息正确。浏览器已分别点击播放，Mini currentTime 递增并播放到结尾，Grok currentTime 递增、paused=false、readyState=4；刷新后两者 duration／readyState 保留。请求 480p 的 Mini 实际返回 560×752，Grok 返回 480×640；不得写为二者均严格 480 像素或全部视频型号均已真实通过。Grok 此样本附带音轨，未验证可关闭音频。视频动作／人物服装轮廓可用，背面和微观材质不做原始实物准确性保证。

五张图片调用当前 `CanvasMultiSize.requestFor` 的同一请求构造器、原复杂服装海报与 Seedream 5.5，四项为原固定尺寸 1200×1600、1080×1920、1600×1200、2520×1080，第五项为 1440×1800 自定义。逐文件尺寸完全等于请求，均是模型新构图并各自独立归档；目视核对“秋冬新品”“羊毛针织外套”“¥399”“AUTUMN KNIT”“面料细节”“精致纽扣”，五项均可见且保留。与既有 1920×1080 和 1200×1200 有效证据合并后，六个固定用途及一个自定义尺寸的本样本限定效果证据补齐。人物、针织纹理和构图仍会被生成模型改写，不能称逐像素保真或所有素材稳定通过；负责人视觉认可保持独立。

预算结算观察：七项结束后同 Key 时段聚合增量 **2.6364987 元（约 2.64 元）**，低于 10 元。Mini 运行时曾观察到约 13.5079 元临时扣减，任务完成后回落至约 0.5749 元；期间暂停新增提交并只查原 ID，结算回落后才继续。该读数变化是预扣／回退的观察证据，不是供应商逐任务发票，公开价不能当作最大预扣保证；后续验收先核预扣规则，仍不滚用剩余额度。本批已关闭，临时来源停用，原测试 provider 的启用、名称及视频列表已恢复；原加密版本保留用于追溯。

全七项原 API 下载字节与归档一致；第二普通账号读取七个任务均 404，新验收画布跨账号同为 404。独立审核画布为 **11月28日 · 真实视频与多尺寸验收**（`3cd8ff0f81f341b983c0824662250e81`），未覆盖负责人原画布。仓库外证据位于 `Infinite-Canvas-Enterprise-Artifacts/development/video-acceptance-20261128/` 的 `budget.json`、`verification.json`、`browser-playback.json`、两条 mp4 及逐任务回执。

MKT-01.D 复用已有效 Alpha 拆层、遮挡人物组和原区域保真证据，不新增无收益收费重试。普通旧工坊 5.5 直接透明、两人独立补全和严格重建仍未通过；GPT Image 2.6 官转组透明未实测，本批不将它或新站记为可用。以此明确当前业务可用范围，不把图层全能力标为完成。

<a id="mkt-03-a-20261128"></a>

### MKT-03.A 逐行编辑文字的官网与渠道依赖核对

已读取当前官网公开 `main.806cae0e14.js`、`app-shared.c08727155e.js`、`canvas-core.d41bbfa42d.js` 和 builder runtime；本轮菜单可见“营销 → 编辑文字”，完整编辑面板未取得稳定现场证据，不冒称已完成视觉复刻。公开前端明确以 `imagePostEdit.open({mode:'text-edit',nodeIds,...})` 进入，且依赖 `postEditCatalog`、`imageTextEditServices` 与实际像素源就绪。OCR 服务请求 `/mweb/v1/ocr`，输入 `image_uri`，结果逐行 `text`＋`points: [{x,y}]`，对坐标做有限数值校验。这是官网可见调用契约，私有 OCR／重绘实现与服务端提示词未公开，不能直接搬入本项目或复用其登录凭据。

旧工坊当前 Key 的只读目录包含 `qwen-vl-ocr`、`qwen-vl-ocr-2025-11-20`、`qwen-vl-ocr-latest`；目录存在不等于高精定位接口已通过。[阿里云原始文档](https://www.alibabacloud.com/help/en/model-studio/qwen-vl-ocr)说明 `advanced_recognition` 输出逐行文字及旋转矩形；[API 参数文档](https://www.alibabacloud.com/help/en/model-studio/qwen-vl-ocr-api-reference)列出 `ocr_options.task`。本轮没有发送收费 OCR 或新图片任务，旧工坊是否透传该选项及其坐标／文字准确性仍需核验。

下一个最小实现范围保持原边界：OCR 适配只负责已确认请求和坐标归一化；持久化／身份／费用／查询复用原 LLM 任务；独立前端组件做逐行选中、原图区域联动、替换／删除／重置；明确点击生成后沿原图片编辑任务产生派生结果，保留原图、原记录、回填保护和归档。两类画布只加 adapter，不把供应商或 OCR 状态塞进图层文档组件，不增加新任务账本、SDK 大包或重绘引擎。先落实 MKT-03.B 的单条识别与坐标契约，再做侧栏和真实改字验收；MKT-04～07 仍按原顺序，尚未提前开发／验收。

本记录对应源码为已保全的 `b8b092e`；本轮业务代码未变，新增为真实证据及原事实源更新，main／正式 11.3／生产保持。文档检查 156 文档／770 本地链接、0 错误，17 项文档契约通过，`git diff --check` 无错误；无新业务改动，不重复全量协议回归。

<a id="increment-preservation-20261128"></a>

## 2026-11-28 当前 59 项增量保全与后续顺序

负责人明确授权先保全并整理当前增量，随后少量视频真实验收、图层／多尺寸效果收口，再按 MKT-03～07 顺序实施。开工分支 `codex/zhenzhen-video-compat-20261126`，HEAD `b5251ccc0a7b430318e1f0f96a1419556f8577ff`；暂存 0，49 个修改加 10 个未跟踪文件。原 GitHub main 仍为正式 11.3 基线 `d821098`，11 月 26 日独立备份不包含本次后续修改。

59 项按原职责整理为：文档／状态 7、原任务恢复与耗时 2、视频协议与参数素材 11、参考图清晰度 2、定向测试 25、原入口装配 1、画布输出／交互 11。整体保存一个开发检查点，不通过拆提交、重写历史或清理文件改变本地成果。逐文件结果见[本批源码清单](./backup-audits/2026-11-28-development-files.csv)，恢复方式见[本批恢复说明](./backup-audits/2026-11-28-restore.txt)。

本地外部 `development/increments-backup-20261128/` 已保留开工原始 59 文件 ZIP、完整状态／大小／分类清单及扫描结果。读取所有本批文本，未发现真实 API Key／GitHub Token／私钥特征，Python 源码语法和 19 个 JavaScript 文件语法通过；65 个被忽略项均为缓存，没有被忽略的开发代码。不读取运行凭据，不把数据库、用户素材或外部实验产物提交到公开源码仓库。

源码提交 [`b8b092e67c2e7c984ff6a04be53713161844fed4`](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/commit/b8b092e67c2e7c984ff6a04be53713161844fed4) 已推送 `origin/codex/zhenzhen-video-compat-20261126`。提交包含全部原始 59 项加两份保全记录，共 61 文件；GitHub API 独立回读这 61 个路径的类型／Git 对象，与本地提交逐项一致，完整源码树有 941 个文件。CSV 的全部 59 行均已填入源码提交、已提交／推送、远端一致和准确文件链接；恢复说明已固定源码快照。后续保全报告另作同分支文档提交，不改业务代码，11 月 26 日备份分支保持。

此保全只证明源码可恢复，不代表视频真实出片、MKT 效果审核、合并／发行或生产部署通过。后续工作依然使用旧工坊优先、原任务／来源绑定和原归档边界；旧付费批次不滚用余额，新验收在明确额度内提交且不自动重试未知结果。

<a id="reference-quality-20261128"></a>

## 2026-11-28 SUP-03.Z 参考图清晰度与逐张尺寸

负责人发现任务中心的四张原文件 21.53 MiB 被准备为 2.11 MiB，批准在模型真实限制内保留原分辨率、超限才缩小并逐张展示提交尺寸。原任务 `canvas_img_4ef43325ff264d14ac1f7fa7f74fa115` 的实际提交分别为 1152×1536、1333×1536、1097×1536、1229×1536；原素材仍在。1536／8 MiB 是项目旧策略，并非已核实的贞贞模型限制。

本轮查阅[旧工坊 GPT Image 2](https://gpt-best.apifox.cn/api-447258891)、[2.6 编辑](https://gpt-best.apifox.cn/api-534982355)、[Nano Banana Pro](https://gpt-best.apifox.cn/api-420361512)、[Seedream V5 Pro](https://gpt-best.apifox.cn/api-485030908)及[方舟图片 API](https://docs.volcengine.com/docs/ark/image-generation-api?lang=zh)。旧工坊页面没有完整声明参考输入边长／像素／字节边界；其中 size 的约束属于输出，不可用于压缩输入。新站未加入长期供应商，也未借用其限制。方舟原生 5.5 的输入契约单列：单图 30 MB（本实现按 30,000,000 bytes）、总像素最多 36,000,000、长短边比最多 16、普通输入每边至少 15px；拆层输入至少 262,144 像素且仅 PNG／JPEG。本轮仍以项目已维护的 PNG／JPEG／WebP 直传集合装配，其他可解码格式转 PNG，不声称已新增 HEIC 等格式解码能力。

原 `ImageReferencePreparation` 不再默认缩边或压至 8 MiB；限制内文件原字节复用，方向校正／格式转换先保持分辨率并无损编码；真实单文件限制超限先重编码，仍超限再等比缩小，透明图保留 Alpha。不通过拉伸、裁剪或放大规避宽高比／最小像素要求。批内一次准备／重复引用顺序和 JSON／multipart 的共用副本继续保留。main 沿原模型能力装配，非回执同步入口与既有 JSON 分支也使用同一准备结果；其他供应商路径没有批量迁移。编码总量与实际请求体 32 MiB 仍是项目预算，超限在付费 POST 前阻止，不截断素材或自动低画质重试。

| 原输入尺寸 | 旧提交尺寸 | 本轮离线提交尺寸 | 字节与 Alpha |
| --- | --- | --- | --- |
| 4500×6000 | 1152×1536 | 4500×6000 | JPEG 原字节相同 |
| 3828×4411 | 1333×1536 | 3828×4411 | JPEG 原字节相同 |
| 2926×4096 | 1097×1536 | 2926×4096 | PNG 原字节／Alpha 相同 |
| 3793×4741 | 1229×1536 | 3793×4741 | PNG 原字节／Alpha 相同 |

四图准备总量 22,570,852 bytes（21.53 MiB），当前编码请求模拟 30,094,707 bytes（约 28.70 MiB），在 32 MiB 内；MockTransport 验证实际请求中四个 Base64 内容均还原为原文件字节，外网生成 POST 为 0。这证明项目提交侧未再缩图，不等于供应商内部处理或模型最终服装细节效果已实测。

任务中心复用原 `image_preparation.items`，逐张显示原始／提交尺寸、原图直传／转换／超限缩小、原因及格式／Alpha；旧数据没有新处理字段时根据当时尺寸标为历史缩小，不改写原任务。经典 1280×720 与智能 1311×1013 原页面分别打开“日志 → 生成任务 → 详情”，同一独立本地 QA 回执显示四张原图直传，原反馈任务保留 2.11 MiB／历史缩边。无空白、框架覆盖或新增 JS 错误；经典页仅有既存 Tailwind CDN 使用建议。未移动原画布节点、换提示词或点击生成。

定向验证覆盖原字节保持、总像素／文件限额缩小、Alpha、EXIF／格式处理、批内并发与顺序、请求预算在 transport 前拦截、原生提交／拆层／重启回读、无回执 JSON 路径及任务中心历史兼容。原旧尺寸迁移测试错误地从 HEAD 取已经迁出的旧函数，本轮改用 `d8210980d5c773ff91798cac20e8cfb5c14ee92b` 实际运行捕获的 18 组固定结果，避免随 HEAD 和浅克隆漂移；旧尺寸业务算法未改。外部证据位于 `development/reference-quality-20261128/`，含改前源码／运行副本、离线请求核对、逐图记录、两类页面截图和定向结果。所有素材原件、原任务、凭据与归档保持；本地代码与预览已更新，无新增收费调用、Git 交付、正式发行或生产操作。旧工坊未声明的输入限制和新策略真实生成质量仍需后续独立证据。

<a id="smart-generation-feedback-20261128"></a>

## 2026-11-28 SUP-03.Z.O 智能画布生成节点四项反馈

负责人反馈正常生成出现逐张“供应商已受理”行、首张返回时多图节点布局不合理、新建节点继承 3 张以及底栏弹层和滚动条干扰。本批沿原 `codex/zhenzhen-video-compat-20261126` 本地候选追加，不覆盖既有视频、恢复、图层或预览修改，不操作原用户画布的生成任务。

| 反馈 | 原因与本地修复 |
| --- | --- |
| 正常受理明细干扰 | 原 smartImageTaskStatusHtml 输出所有 imageStatus；现在正常过程行不渲染，异常说明及原任务查询入口保留，回执数据和轮询不删除 |
| 首张导致放大／跳动 | 原 imageLayout／nodeBodyHtml 只按已返回张数选单图或网格，待完成位置随首张消失，pending 时还不复用媒体元素；现在原呈现模块 smartEntries 按 taskId／imageIndex 计算固定格，图片就地替代自己的占位，回执补可选 canvasTaskId／outputOrder 并排序，完整多图保留预留尺寸，部分结果也复用原媒体 DOM |
| 新节点默认多张 | 原 smartSettingsForNode 继承近期设置和画布默认 count；新节点 count 覆盖为 1，旧 runSettings.count 明确值保留，切换模式不从近期值覆盖当前数量 |
| 下拉与底栏 | 数量面板 overflow visible；点击式 top-layer 面板移除旧 ::after 悬停桥，其 8px 高度原本造成额外溢出和双滚动条。四面板共用 rgba(24,28,38,.94)／blur 14px／12px 圆角，长列表 5px 暗色滚动条；搜索框与个人模型按钮深色化，模型按钮 max-width 110→240px。上下／左右边界仍用现有 StudioDropdowns，未另加定位逻辑 |

实现只涉及原纯呈现模块、SmartCanvas 原显示／回执函数、样式与缓存键。正常状态字段仍保存，查询不中断，没有重投任务、替换供应商、限流或迁移。旧部分产物缺少图片任务映射时兼容显示，不能反推缺失的历史任务身份。经典呈现入口不改其业务方法；它只更新同一共享模块的缓存键。

本地受控回执使用原服装画布的四张输入和三张已归档结果，在独立 QA 画布 `a551e0310d894e109e5e90adbaf26848` 中按 B 部分返回、B 完成、C 完成、A 完成推进；夹具只写本地 journal 和原画布 API，没有调用生成提交接口。0／1／2／3 图均保留三格，位置与节点 420×420 尺寸不变，部分和最终 B 不重复。最终存为 A／B／C，原任务 ID 与序号保存在原图片 JSON，GET 回读／页面重开通过。之后为底栏验收主动使用原“生成设置”居中视口，重开后的屏幕坐标随保存的视口变化，节点自身位置和尺寸不变。

实际页面先把当前 QA 节点选为 3 张，再通过底栏添加节点创建上传节点，新节点显示 1 张。旧源节点仍为 3 张。四面板背景／边框／阴影／blur 与要求一致，count 的 scrollHeight=clientHeight=95 且 overflow visible；平台／模型／尺寸面板没有原 8px 多余溢出。长列表滚动条实测 5px／rgba 白色 .16，搜索框 6px 10px padding，模型 gemini-nano-banana-2.1 完整显示，搜索 gemini 仅显示三项匹配。模型／尺寸面板下方空间不足时出现在触发器上方，所有面板位于 1280×720 视口边界内。关闭菜单、选择模型和数量均继续原入口，没有点生成。

原页面和独立页均为同一本地 QA 身份。独立验收页无空白、框架覆盖层或 console error／warn。定向检查复用原输出、智能日志、视频续查、图层尺寸、下拉定位与工具栏入口；测试夹具补齐新共用模块及既有时间投影依赖，不为 CSS 写镜像断言。完整结果保存在外部 `development/smart-generation-feedback-20261127/`，目录名沿用开工日，收口日期为 11 月 28 日；含源码基线、回执脚本／身份、布局阶段数据、四面板截图和 browser-verification.json。没有新增收费生成、生产修改或源码提交，模拟证据不代表新一轮真实模型质量验证。

<a id="output-review-20261127"></a>

## 2026-11-27 SUP-03.Z.O 图片结果重复占位、顺序与多输入审核

负责人提供生产 11.3 录屏及四张截图：结果返回后短暂增加“部分完成，其余仍在跟踪”卡片，多个模型输出按完成先后出现，预览只能与第一张输入比较。本轮在 `codex/zhenzhen-video-compat-20261126@b5251ccc` 加既有未提交候选上实施，未覆盖此前视频／隔夜恢复修改，不新增收费调用或操作生产。录屏文件 71.07 秒，截图直接展示同一任务图片与占位并存；代码定位不以供应商生成速度解释客户端显示问题。

| 问题 | 已定位原因 | 当前行为 |
| --- | --- | --- |
| 短暂多卡 | renderOutputGrid 与局部刷新分别列出图片和全部 pending；部分结果已加入 images，pending 等最终状态才移除 | 同一平台任务有图片即用图片占原位置；跟踪状态附在原卡，失败待核对仍可查原任务，不增加一张活动占位 |
| 顺序及模型难辨 | 结果完成时追加 images；输出没有模型名 | API 图片新任务生成提交前给原 pending 分配 outputOrder，回包将序号／请求模型放原 run；显示和保存数组同序，卡片及预览显示冻结模型 |
| 只有第一张输入 | appendOutputImages 的旧比较映射只存 refs[0]，预览只读取该映射 | 优先读取该结果的 run.refs，识别全部图片引用，去重并过滤非图片；左下胶囊任选输入，原双击切换和滑杆继续有效，旧单图映射作为回退。初版额外按钮已由下述 UI 反馈移除 |

`canvas-output-presentation.js` 只计算条目／位置／模型／输入，调用、任务、存储和凭据继续原边界。HTML 加载该模块并更新缓存键，CSS 只增原卡标签和预览素材条。返回部分图片后仍通过原任务 ID 继续查询；没有取消后端任务、自动换源、重试生成或新调度。局部刷新保留媒体 DOM，只更新模型／状态／耗时徽标，修复本轮验收发现的“最终服务端耗时已正确、原卡尚显示部分结果时耗时”的滞后。旧输出没有提交序号或模型元数据时保留兼容，不从当前生成器编造历史身份。

本地受控任务 A/B/C 的模型为 Seedream 5.5、GPT Image 2、Seedream v5-pro，复用既有复杂服装原图／图层及已归档宽／方图作为返回素材；这些是呈现夹具，不冒称三次新真实模型生成。任务按 B 部分返回、B 完成、C 完成、A 完成推进：初始三占位；B 部分返回后三卡／两个占位；最终三图／零占位，位置始终 A→B→C。保存刷新后原本人接口回读的 URL／模型顺序一致，refs 分别为 3／2／3；没有在换模型或换输入时串用当前配置。

首次恢复与部分返回在 core `127.0.0.1:13001/static/canvas.html` 原页面验证；随后用原本地 QA 身份在 `127.0.0.1:18000/` 首页登录，经无限画布列表打开同一画布，实际点击第一张输出、任选第二／第三张输入、切换只看结果、打开第二张结果的两张输入及滑杆拖动通过。1280×720 内置浏览器无空白、框架错误页和页面 error；仅 core 页面有既有 Tailwind CDN 构建方式警告。未在本轮重做其他浏览器、普通账号鼠标及手机现场验收。

定向验证包括 `test_canvas_output_presentation.js`、`test_canvas_performance.js`、`test_canvas_image_timing.js`、`test_output_video_preview.js`、两份业务 JS 语法，以及原 Python 入口运行。performance 夹具补齐既有 ModelPicker 环境与实际 gcd 比例规范化，未为本次呈现修改尺寸业务规则。文档检查与合同结果记在外部 verification；未跑无关全量回归。证据目录 `D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/development/output-review-fixes-20261127/` 保存改前源码、受控回执脚本／画布身份、browser-verification.json、部分返回／顺序／多输入截图和源码候选副本，不包含环境凭据或数据库。

本批新增供应商生成 POST／费用 **0**。源码待负责人审核，未提交／推送、合并、发行或更新生产 11.3。历史结果的缺失输入快照不能凭空补齐；仅保存一张旧比较引用的历史条目继续能比较该张。新结果的模型标识来自请求快照，不根据供应商实际内部路由推断模型真实性。

### 后续反馈：只改输入切换器 UI

本编号最新深色反馈按两类画布分别处理：复用 `theme.js` 已有的 html／body `theme-dark` 标记，经典 `.output-compare-source*` 和智能 `.compare-thumbs`／`#compareToggleBtn` 增加深色覆盖，背景 rgba(24,28,38,.85)、blur 12px、白色 .12 边框与 .45 阴影；文字／箭头白色 .85，缩略图底色 #262b36、白色选中框及深色 .65 角标。智能画布保持原横向输入选择和原开关，没有改成经典抽屉，也未改变其白天布局。经典 theme.css 对预览 img 强制 background／border-color，因此仅在 `#outputCompareSources` 内以限定重要性覆盖这两项；全局主题和主图样式不改。

本轮 CSS 仅新增 `.theme-dark` 作用域行，两份业务 JavaScript 与改前副本逐字节相同，两份 HTML 只有 CSS 缓存键变化。原首页进入经典预览，白天样式／主图／提示词几何与改前采样完全相同；深色展开及点击第二张更新 2/7，白色 2px outline 和实际缩略图 #262b36／.12 边框确认。智能画布原预览／对比开关启用、缩略图取消／重新选中、明暗切换实测，主图几何不变，原滑杆保持 50%。独立 1280×720 经典与智能页面均无脚本 error，经典保留既有 Tailwind CDN 构建提示；未扩为移动端或全浏览器验收。

证据追加外部 `development/output-compare-dark-20261127/`：六份源码基线、protected-source.json、browser-verification.json 和两类明暗／局部截图。复用现有相关检查，不为纯配色新增实现镜像测试，不触发模型生成或生产操作；源码仍为本地候选。

最新反馈将横向胶囊升级为悬停向上抽屉：左下 16px／z-index 20 保持原定位，收起时为 28px 当前缩略图、1/N 计数与上箭头，玻璃背景 0.88／blur 12px／padding 5px 8px。上方抽屉以 opacity／translateY(8px) 的 200ms ease 过渡展开，箭头旋转 180°；8px 透明区域连接触发器与面板，无鼠标盲区。列表竖排 40px 缩略图、6px 间隔，浅灰底／细边／角标及黑色选中框保留，最多五张高度 230px，超出可纵向滚动且滚动条隐藏。

本轮仍只改原渲染函数、胶囊事件部分和 `.output-compare-source*`，HTML 仅更新缓存键。点击就地更新原输入 src、aria-pressed 和锚点缩略图／计数，不重建列表或重置其滚动位置。其余 JavaScript、CSS 与本轮改前副本逐段一致；原滑杆／对比模式、主图／缩放及底部提示词栏均在保护范围内。

本地首页同一 QA 身份实测：初始 1/6 收起，悬停 opacity 1／translateY 0／箭头 180°；指针位于触发器上方 4px 的透明桥接仍保持展开，移出后隐藏。真实鼠标滚动到第六张再点击，原输入与锚点同步切换、计数 6/6，滑杆 5.60074%、clipPath、1.1 倍 transform、模式、主图与提示词前后一致。横图七张列表高 230／scrollHeight 322／scrollTop 92，末张选中 7/7 且主预览 scrollTop 0；零／单张隐藏且内容为空。原预览、主图和提示词栏几何与改前一致。

证据保存在外部 `development/output-compare-drawer-20261127/`，含保护区域核对、桥接／切源记录、边界数据、收起／展开截图及源码副本。工具对被裁切缩略图的定位点击曾自动滚动隐藏祖先，未计作通过；改用真实鼠标滚动到可见项再点击完成验收。日志保留一条无源码位置的 MutationObserver observe 错误，未扩大修改原功能或据此声称页面无错误。相关原 Python 入口、JS 语法及文档检查通过，未新增模型提交、费用、生产操作或 Git 提交。以下为此前横向胶囊阶段的历史记录。

缩略图边界的再次微调仅在原 img 规则加入 `background:#f3f4f6`、`border:1px solid rgba(0,0,0,.08)` 和 border-box，外部尺寸仍为 36×36，CSS 缓存键更新。JavaScript 与改前逐字节一致；原首页回读三张缩略图样式、选中第二张及原 2.70913% 滑杆恢复核验。其余 CSS 与 HTML 控件不改，无新增测试或收费调用；局部截图与范围核验追加原外部目录 thumbnail-border 文件。

负责人明确禁止改动原滑杆、对比逻辑、主图展示和底部提示词栏。此前移除白底通栏、计数和额外对比按钮，仅留预览容器左下 bottom／left 16px、z-index 20 的毛玻璃胶囊；外层 padding 6px、圆角 12px、0.85／hover 1 透明度，缩略图 36×36、8px 圆角、左上 10px 小角标，选中为黑色 outline，非选中 0.6／hover 1 并 scale(1.05)。超过五张时列表最大 210px，全部输入可横向访问；原 theme.css 全局 thin!important 会显示滚动条，只在胶囊选择器中覆盖为 none，未改全局样式。

运行时代码只改 `renderOutputCompareSources`、`initOutputCompareEvents` 的胶囊事件部分及对应 CSS；HTML 只更新 JS／CSS 缓存键。点击只换当前输入 src 和 aria-pressed，不重建缩略图列表、不重置滚动位置、模式或缩放；胶囊内双击不传给原预览切换。预览其他区域的原双击、滑杆事件、主图样式和提示词栏均与本轮改前源码保持逐段一致。

原首页、同一 QA 身份和原画布在 1056×1013 内置浏览器复验：切源前后 slider=71.3256%、clipPath、主图 URL／transform 和 compare-mode 完全相同；预览、主图、结果图、提示词栏的尺寸／位置相同。横图 1920×1080 和竖图 1024×1536 均左下定位。独立本地边界画布验证 0／1 张时胶囊内容为空且 hidden，单图原双击比较仍有效；7 张列表 clientWidth 210／scrollWidth 294，末张可选择、scrollLeft 约 81.33，原生与 WebKit 滚动条均隐藏。悬停实测父容器 0.85→1，未选中缩略图 opacity 1／scale 1.05，原生 title 为“切换对比输入图 N”。

证据在外部 `development/output-compare-capsule-20261127/`：四份改前源码、前后布局／滑杆数据、边界画布、横／竖图截图及 protected-regions.json。一次跨页工具验收日志出现无源码位置的 MutationObserver observe 错误；未据此改动原功能，独立新开首页沿相同入口进入七图预览后未复现，console error 为 0，分别保留原记录与 fresh-page-health.json。1 项相关 Python 入口、JS 语法和本批文档契约验证通过；未扩成全量回归、收费生成、生产操作或源码提交。

<a id="official-fallback-proposal-20261127"></a>

## 2026-11-27 透明能力分类与火山方舟官方兜底提案

负责人明确旧工坊 `ai.t8star.org` 优先，新站 `api.seedance.nz` 后续单独决定是否长期接入；本轮先给方案，不安装依赖、不接新站、不做新付费验证。直接生成透明图片与拆出透明图层按不同业务合同维护：

| 平台／路径 | 已有依据 | 当前边界 |
| --- | --- | --- |
| 旧工坊普通 seedream-v5.5 | 已测复杂服装根层 background 及 metadata 请求原图均为 RGB | 该场景直接透明未通过；不能扩大成该平台全部型号不支持透明，参数透传／上游原因未明 |
| 旧工坊 seedream-v5.5/layer-decomposition | 原项目任务返回有效 Alpha 图层，位置／层序保留 | 属于拆层成功；复杂独立人物遮挡／重建和规整文字质量不是全部通过 |
| 旧工坊 gpt-image-2.6-flare／sunburst 官转组 | [生成请求](https://gpt-best.apifox.cn/api-534896365)、[编辑请求](https://gpt-best.apifox.cn/api-534982355)与[背景定义](https://gpt-best.apifox.cn/schema-327743737)声明 transparent、PNG／WebP | 直接透明候选，尚未完成本项目复杂服装实测；需要准确 Key 分组，不能只换模型名就认定可用 |
| 旧工坊 gpt-image-2 | [分组说明](https://gpt-best.apifox.cn/api-447258891)：逆向组只列 model／prompt／size／image／quality，官转组声明参数透传 | 逆向组不以 background 当作可用；官转声明仍需真实产物验收 |
| 新站 zhenzhen-image-g-v2.5-flare／sunburst | [新站公开文档](https://api.seedance.nz/docs/llms.txt)列背景参数，透明需 PNG／WebP；lowprice 无透明背景选项 | 文档支持且未实测，当前不接入；新站型号／单数路径／metadata 与旧站严格分开 |

### 官方 SDK 事实

[方舟安装及升级 SDK](https://docs.volcengine.com/docs/ark/install-and-upgrade-sdk?lang=zh)推荐 Python `arkruntime`，导入 `from arkruntime import Ark`；旧 `volcengine-python-sdk[ark]` 仅在新版暂不覆盖所需 API 时考虑，不默认并装两套。[快速入门](https://docs.volcengine.com/docs/ark/quick-start?lang=zh)统一官方基础地址 `https://ark.cn-beijing.volces.com/api/v3`，分别提供文本／理解、`images.generate` 和 `content_generation.tasks.create`。账号仍需开通相应模型服务、可用凭据及余额；SDK 不代办这些条件。

[官方 SDK 源码说明](https://github.com/volcengine/ark-runtime-python)提供同步／异步客户端、类型和超时／重试设置；默认存在自动重试。若后续用于收费创建任务，建议在该提交路径显式关闭 SDK 自动重试，继续原项目的受理未知／原 ID 查询策略。发行只锁定已验证版本，不在员工启动时自动升级。项目固定 CPython 3.14.6 及离线锁文件，实际依赖、打包和重启恢复须独立验收；本轮未宣称兼容性已验证。

SDK 更新可以减少新 API 字段与 HTTP 封装维护，但不等于更新后所有模型可直接出现在产品。相同 API 族的新模型通常只需新增准确模型 ID、能力／素材规则及验收；新 API 或字段再评估升级包与最小映射，不能绕过前后端一致的参数校验。

### 建议的最小接入方案（待负责人决定）

保持现有节点 → 能力规则 → 原素材／凭据／任务服务 → 供应商适配 → 原归档。已有 `enterprise/providers/volcengine_images.py` 就是方舟图片边界，先复用其真实能力和服务；如选择 SDK，只在供应商内部替换传输，不把 SDK 对象带进节点、main 大入口或任务数据库。不新增任务库、调度器、通用路由 DSL、并发门槛或第二套凭据系统。

| 业务族 | 官方备用候选 | 实施和验收边界 |
| --- | --- | --- |
| 生图、智能改图、多图融合、智能多尺寸、分层／透明 | Seedream 家族；5.5 文档列原生 RGBA 与拆层 | 复用已有图片适配；逐功能映射尺寸／图片上限／背景及分层合同，用复杂服装验收框外像素、Alpha、中文和遮挡，不能只看 HTTP 成功 |
| 视频、动态海报 | Seedance 家族 | 在原 CanvasVideoTasks 和媒体预检边界补官方适配，前后端按精确型号显示参数；受理／重启／归档先模拟，再另批少量真实生成 |
| 对话、提示词与图像理解 | 豆包 Seed 系列 | 原文本／Agent 调用边界增加官方配置与必要参数映射，验证视觉输入、工具调用及中断语义，不从图片 SDK 接线推断 Agent 全流程可用 |
| 精确点击抠图、发丝轮廓、严格像素重建 | 现有本地分割或另行核实的官方图像工具 | 方舟生成模型不自动等同确定性分割；[图片 API](https://docs.volcengine.com/docs/ark/image-generation-api?lang=zh)的 RGBA／图层能力不保证每个复杂样本都保真。此项单独列未覆盖，不以“全部业务保底”掩盖 |

建议分三步：①先确认上述覆盖矩阵和旧站／官方主备关系；②只补已选业务族的最小适配，离线／模拟、原页面、普通身份、原任务重启恢复通过；③在另行批准预算且官方账号恢复可调用后，少量复杂服装真实验收、固定版本与正式发行／部署。先让用户明确选择官方备用；自动故障转投另行评估，供应商可能已受理的任务不得换来源重复生成。官方解决稳定的供应路径，并不保证与第三方各型号同价或逐像素同效。本轮没有把提案写成已获实施授权或当前交付完成。

<a id="image-overnight-timing-20261127"></a>

## 2026-11-27 SUP-03.Z.T 员工关机后次日恢复的图片耗时与 ID 提示

负责人报告正式 11.3 的局域网员工客户端生成期间关机，次日显示图片耗时 921m42s、供应商任务 ID 未取得。截图任务为 `canvas_img_752d8fed2f8e4acf91ac8fac50e58f3a`／custom-api／seedream-v5-pro：提交 2026-11-26 18:01:24，平台子请求结束 18:03:10（106 秒），供应商控制台 18:01:25–18:03:04（99 秒），画布日志 2026-11-27 09:23:06。921m42s 精确等于从提交到次日页面取得结果的间隔，不是截图中供应商的实际生成时间。平台时间还包含请求与归档；相差的 7 秒未单独拆分测量。

以 `v2026.11.3@a5613da` 对照当前候选：经典 `appendPendingImageResults` 和智能 `finalizeSmartPendingTask`／恢复日志用本机 now−started 结算，原轮询仅把 result 交给呈现、未采用 journal 的创建及完成时间。故客户端隔夜后才恢复输出时误把离线间隔写入卡片和日志；主机已在前夜完成，与“因客户端关机而上游一直生成”不同。生产 IAB 确认为 11.3／Aidan02；该账号本人任务里没有反馈员工这笔任务，未绕过权限、重试生成或写生产。负责人最后的 nano-banana-pro-2k／image-sync JSON 为另一笔示例，未据此认定 Seedream 原回包类型。

实现保持原任务服务：`canvas_image_recovery.image_task_timing` 只从原记录投影时间，GET 与手动续查携带可选 timing，不用可因续查改变的 updated_at；未知结束时间不补造。`canvas-task-query` 换算毫秒并兼容旧服务端的 created_at／result.timestamp，两类画布继续原 ID GET，经典卡片及日志一致，智能多子任务按最早开始／最晚完成累计且中途保存可恢复。任务中心只把成功图像无异步 ID 改成说明，未知受理仍保留核对提示；`ImageReceiptSink` 增加 x-oneapi-request-id 追踪头兼容，仍与 upstream_task_id 分开，不以追踪 ID 发异步查询。未取得这笔生产原始头，不能声称新增头兼容就是其已证实根因，也不能恢复原来没有保存的 ID。模型、素材、Key 绑定、并发、付费提交与权限无变更。

验证使用同一既有复杂服装海报，创建两份本地 QA 的“已完成服务端记录＋隔夜仍 pending 的画布”夹具；没有供应商生成 POST。原经典／智能页面在 `127.0.0.1:13001` 实测恢复后 1m46s／1:46，图片和日志 106000ms、各一条，保存重开日志不变；控制台错误 0，无框架错误页。经 `127.0.0.1:18000` 原本人接口回读任务与归档；这与生产登录及普通身份端到端验收分开。Node 五组检查覆盖经典原 ID 只读、智能多图中途保存／重开、共享协议、任务中心与既有视频恢复；CP314 定向回执、图像执行及恢复集成验证按本批结果登记，不跑全量回归。证据在外部 `development/image-overnight-timing-20261127`：改前副本、两份 fixture 身份、verification.json、服务日志和源码候选快照。

本批为本地待审核修复：未重新生成这笔任务、未新增付费调用、未改生产配置／文件、未修改历史错误耗时或强行补供应商 ID，未提交／推送或发行。待办为读取原生产回执／响应头核对 ID 来源，负责人审阅后固定正式候选与升级验收；不能将本地页面验证写成已修复生产。

<a id="seedream55-parameter-audit-20261127"></a>

## 2026-11-27 SUP-04.S55 旧工坊参数与新站封装交叉复核

负责人指出此前未测试新站 metadata 在旧站的实际效果，明确批准本批新增 **不超过 3 元、最多 3 次生成提交**。此前各图片批次余额不滚用。本批外部诊断直接请求 `ai.t8star.org`，只使用原 DPAPI 保存的第一个新增工坊 Key，未回显、改写或发送给新站。源码仍为 `codex/zhenzhen-video-compat-20261126@b5251ccc` 加原本地候选，没有将新试验协议接入业务代码、开启正式来源或改生产配置。

### 当前参数依据

旧站鉴权模型列表仅找到 `seedream-v5.5` 与 `seedream-v5.5/layer-decomposition`，未列新站 t2i／i2i／Dola 别名；目录可见不是所有参数可用的证明。旧站 `/api/pricing` 当前说明普通图生图最多 10 张参考、输入不必带透明通道、1K／1.5K／2K 或宽高像素、背景 auto／transparent／opaque，透明需 PNG，默认关闭水印，提示词优化只有 standard，不支持组图／联网搜索。它把相同普通生成描述用于拆层型号，不能据此推断拆层支持多参考图或普通背景控制。

[旧统一格式](https://gpt-best.apifox.cn/api-514194485)与[旧普通接口](https://gpt-best.apifox.cn/api-485030908)仍用 `POST /v1/images/generations`、`model`／`prompt`／`size`／`response_format`／`output_format`／`image[]`；其 5.5 目录关联的[旧拆层页](https://gpt-best.apifox.cn/api-522995149)没有普通 5.5 专用字段说明。[新站文档](https://api.seedance.nz/docs/)和供应商 `Comfyui-zhenzhen@ea1ace13f6a89ca587186e2bedd8e8141364eab9` 的 `seedream55_contracts.py` 则明确使用单数 `/v1/image/generations`、`seedream-v5.5-i2i`／`images`、metadata 背景／格式／分辨率。新站的文档及源码不能直接当作旧站字段已透传的证据。

| 字段／范围 | 已取得的旧站证据 | 尚未证明 |
| --- | --- | --- |
| `model` | `seedream-v5.5` 真实生成；拆层后缀已有原批次证据 | 新站 t2i／i2i／Dola 别名在旧普通接口的可用性 |
| `prompt` | 当前复杂服装改酒红色生效，返回 revised_prompt | 旧站完整长度边界、优化器内部规则 |
| `image` | 一张原始 RGBA PNG data URL 成功；既有请求也使用此字段 | 本批没有另做 10 张上限或全部编码组合 |
| `size` | 根层 `1024x1536` 返回同尺寸；原批次保留其他指定尺寸证据 | 所有档位与自定义宽高边界；新 metadata.resolution 是否生效 |
| `response_format` | `url` 成功并下载供应商原文件 | b64_json 只在本批失败的 volcv 路径请求，未得到图片验证 |
| `output_format` | 原请求和当前结果均有 PNG，目录声明 jpeg／png | 新 metadata.output_format 是否被读取，不能因默认同为 PNG 就认定生效；JPEG 切换未在本批实测 |
| `background` | 此前根层 transparent 与本批 metadata.transparent 都未取得有效透明图 | 参数是否完整透传、上游路由及模型遵循原因 |
| `watermark` | 目录声明默认 false，原请求可携带 false | 开／关对照和新 metadata.watermark 的实际影响 |
| `metadata` | 普通接口接受该对象、请求成功 | 其中 resolution／output_format／background／watermark 是否被透传或使用；200 不证明各子字段生效 |
| 层数／OCR | 旧批次 max_images 没有限住输出数量，text_recognition 未返回 OCR，全部产物仍保留 | 新站 metadata.max_images／text_recognition 在旧工坊未测试；不解除现有能力限制 |
| 其他候选 | 目录提到优化 standard；新站有 safety_identifier 等规则 | seed、quality、mask、组图数量、联网和新站特有字段均未因此认定旧站支持 |

### 三次实际提交与结果

全部使用同一复杂服装透明人物原图，不新增简单自制样本。输入 1024×1536 PNG、RGBA，1,455,153 字节；Alpha 0–255，其中全透明 925,641、半透明 29,054、全不透明 618,169 像素。按新封装、完整新合同和错误回包发现的原生转发逐次推进，各一次 POST，响应不明时不重投；没有绕过三次上限执行更多收费参数扫描。

| 次序 | 实际路径及改动 | 结果 |
| --- | --- | --- |
| 1 | `/v1/images/generations`；`seedream-v5.5`，原 `image[]`／根层 size／url，移除根层背景／格式，将 resolution=1k、output_format=png、background=transparent、watermark=false 放入 metadata | HTTP 200；1 张 1024×1536 PNG，RGB，Alpha 转换后全部 255，透明像素 0。保留女性和复杂服装，开衫改为酒红，背景变成实色白底。不能据此认定 metadata 子字段已生效 |
| 2 | `/v1/image/generations`；完整新站 `seedream-v5.5-i2i`、`images[]`、metadata，域名仍为旧工坊 | HTTP 404 Invalid URL；新站单数入口在旧站本次不可用，未执行模型，不能单独据此判定别名解析行为 |
| 3 | 第 2 次错误回包明确提示存在 `/volcv/v1/images/generations`；用旧 `seedream-v5.5`、原 image／size、根层 transparent／PNG，response_format=b64_json | HTTP 500，供应商返回上游 DNS lookup / no such host；没有图片。它只证明该备用转发本次上游不可达，不能归因于本机 DNS 或据此判断透明／b64_json 参数效果 |

供应商 Request ID、脱敏后的完整请求、原响应、原图与像素统计保留在外部 `D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/development/seedream55-parameter-audit-20261127/`。`verification.json` 记录本批顺序、次数与费用；`parameter-contract.json` 是分证据等级的字段清单，`public-source-evidence.json` 保存准确源码版本。请求记录用本地素材身份代替 Base64，不包含 Key；原响应可能含限时下载地址，不进入公开仓库。

### 费用、收口与剩余边界

共 **3 次生成端点 POST、1 次成功出图、2 次错误回包**。第一笔用量先按预扣观察到增量 1.1475 元，之后回落；最终同 Key 时段聚合增量 **0.2245644 元**，低于批准的 3 元。记录使用供应商既有 total_usage 与公开换算系数 1.35；这是聚合读数，不是逐任务发票，不能外推任何失败均会退款。批次已设 closed，不继续滚用余额。

新 metadata 在旧站没取得透明成功，完整新路径已 404，备用原生路由遇到供应商 DNS 错误；不能声称已还原旧工坊全部服务端参数，也不能仅凭这些失败断言模型本身不支持透明。后续准确缺项是供应商确认普通接口字段透传／有效透明样例及 volcv 路由故障，再决定是否需要另一批有界验证；不对现有业务加入自动切换端点、Key、型号或收费重试。没有改业务源码、原任务／归档、生产或新增凭据，没有提交／推送／发行。与本批前候选副本逐字节比较的 28 份业务文件无变化；155 文档／745 本地链接检查、17 项文档契约及 `git diff --check` 通过，不用这些检查替代本批真实结果。

<a id="sup-04-vid"></a>

## 2026-11-26 SUP-04.VID 视频适配与生成前检查（本地候选）

负责人要求继续实施，最新生产截图确认 `https://ai.t8star.org` 使用“异步协议”且标签 APIMART。本轮在 `codex/zhenzhen-video-compat-20261126`、Base `b5251ccc0a7b430318e1f0f96a1419556f8577ff` 上继续，未提交／推送新修订、建 PR、发行或操作生产。下方只读调查及正式 11.3 表保留其阶段含义，不能作为本候选或生产的最新通过清单。

### 2026-11-27 原页面反馈：仅呈现支持的开关

负责人指出 Grok 下仍显示大量无效开关。旧呈现会保留显式开启的不支持项供用户取消；这虽保留旧设置，但增加了无效内容。现按负责人要求替代该呈现约定：智能和经典画布仅显示当前型号／通道支持的开关，没有支持项时收起整行；隐藏可信素材模式时，其来源入口一并隐藏。

`model-picker.js` 继续读取同一能力规则，同时计算当前有效参数，隐藏项按关闭值参与新请求和本地校验，原画布保存值不变。两类实际生成函数使用该参数构造普通开关、首尾帧角色及可信素材引用，避免隐藏的旧开启状态继续生效或阻止生成。切回支持的型号仍显示原开启状态。时长／比例／清晰度等可见参数的非法旧值保持提示，后端严格校验及已受理任务恢复不变；没有另建能力表、协议或任务分支。

验证：`test_zhenzhen_video_compatibility.py` 与 `test_canvas_video_tasks.py` 共 **30 项通过**；既有 `test_video_canvas_resume.js` 扩展两类实际提交函数，验证隐藏项不发送为开启、参考图不遗留不支持的帧角色／可信地址、原值不被修改，原受理／保存冲突场景继续通过。三份 JavaScript 语法检查、17 项文档契约及 155 文档／742 本地链接检查通过，`git diff --check` 无错误。未重跑全仓回归。

原首页交互：经典画布 Mini 开启水印／固定镜头后切 Grok 1.5，无开关且合法参数下可生成；切回 Mini 水印仍开启。负责人智能画布的 Grok 1.5 开关数量为 0，原非法 adaptive 比例仍提示；主动选择 16:9 后运行可用，切 Mini 显示生成音频、镜头固定、水印、全能参考、首尾帧 5 项，切回 Grok 无残留开关。固定预览 5 份前端文件已同步，原画布和登录保持。此轮未点击生成，真实供应商请求与新增费用为 **0**，未新增提交／推送、发行或生产操作。真实出片、计费／退费、Kling 合同及媒体工具部署仍按原缺项。

### 2026-11-27 原页面反馈：生成面板跟随

负责人指出节点下方生成框的跟随效果不一致，要求先分析官网代码。当前官网登录画布 `23234777-3d5f-45a1-b7e2-6b382bd619e4` 保留 19 节点、未提交生成；公开前端当前主入口 `main.806cae0e14.js`。从本次页面实际加载的脚本定位：`6841.88a21e4f35.js` 的模块 `84904` 通过节点几何和 viewport 计算屏幕位置，浮层 portal 到 renderer、默认不启用视口边缘避让；`7244.f3d117ca75.js` 的 node-toolbar 接线为 Bottom／offset 20，交互时隐藏；`4194.af8a6875e6.js` 给出 680px 宽、窄屏最大宽 `100vw - 48px`。原始公开文件及脚本索引位于外部 `composer-follow-20261127/`，未将竞品整包或登录信息纳入项目。这是公开客户端证据，不是私有后端源码。

官网实测：约 21% 下选中空视频节点，面板宽 680px、高 206px，居中且底部相距 20px；抓手平移 700px 后面板左边为 -163.37px，没有吸附回屏幕；缩放到 50% 后宽高仍 680×206，继续跟随节点。官网只操作选择／视口，未改节点内容或触发生成，结束使用“适配画布”恢复可浏览视图。

原项目 `positionComposerForNode` 在 world 内用世界坐标放置面板，宽度随画布缩放；另外按视口左右、顶部与底部 dock 夹取坐标，节点越界后面板单独停在边缘。现在 `canvas-composer-layout.js` 只负责屏幕投影和宽度，composer 在 shell 内固定挂载。节点底部中心投影后增加 20px，不做独立夹取，保持 680px／两侧 24px 的响应宽度；节点拖动／调整尺寸用原交互 class 隐藏，结束后恢复。节点重绘不再移动输入 DOM，保留原草稿和输入法上下文；引用菜单不再重复除以画布 scale，dock 显式聚焦按当前视口转换回世界坐标。图片／视频共用这套布局，现有控件内容、协议、凭据、任务及归档没有迁移。

定向验证：原 `test_canvas_dock.js` 扩展实际定位与引用菜单函数，覆盖 0.2／0.5／1／2／4 倍缩放的固定面板尺寸和间隔、负坐标／底部越界不吸附、640px 宽窗口、dock 屏幕到世界聚焦、caret／引用按钮定位；既有顶部工具、原面板路由、Escape／键盘和不提交生成检查继续通过。两份 JavaScript 语法、原返回保存检查、17 项文档契约及 155 文档／743 本地链接检查通过，`git diff --check` 无错误。原首页进入 `577c89660c7c4d5b879845ce918e83a6`：82% 时节点宽约 259.12px，30% 时约 94.06px，面板均 680px；缩放、平移与拖动结束后的底部间隔约 20px、中心偏差小于 0.02px。取消选中隐藏、重进恢复、临时输入及引用菜单、图片／视频切换通过，临时测试文字已清空；控制台新增错误 0。此窄屏场景为定向代码检查，未写成实际设备验收。

预览同步当前 4 份前端文件并保留原登录和数据；列表中遮住入口的两张旧测试卡片仅通过界面移开，未改列表源码。源码及交互前副本在本批外部目录保存。本次没有生成 POST 或费用，没有后端／模型协议改动、源码提交／推送、发行或生产操作。负责人本轮效果审核和 VID 原真实出片／计费／Kling／部署缺项分别保留。

### 原因与实现

正式 11.3 将异步语义与 APIMart 专用协议混淆，使贞贞地址进入 `/v1/uploads/images`，上传 404 后没有进入视频生成。现在贞贞身份与 APIMart 互斥，设置页明确显示“APIMart 专用协议”；贞贞本地素材使用供应商画布实际采用的 `/v1/files`。新模型的参数错配独立修复，不能仅把生产协议改为 OpenAI 就宣称全部模型已兼容。

`zhenzhen_video_profiles.py` 只定义精确型号、通道及参数／素材能力；`zhenzhen_video.py` 负责验证与协议转换；`zhenzhen_video_execution.py` 编排已有 HTTP、上传、受理与归档注入；`video_reference_preparation.py` 只读当前授权可解析的素材、解码图片并探测音视频。main 只装配原凭据、素材解析、任务受理和归档，移除原重复构造分支。没有新队列、凭据表、任务表或并发限制。

所有输入先检查，再开始素材上传和生成：文件存在／非空、应用单文件 50MiB 范围、PNG/JPEG/WebP 解码与实际 MIME、音视频容器／真实流和有限时长、当前型号数量与时长上限。原图字节及 Alpha 不重编码；不会截取前几张参考图或前几段音频。官方 Sora 首帧另检查与请求画幅对应的 1280×720／720×1280 像素。此预检减少已知错误，不承诺供应商服务可用、内容审查通过或失败一定不计费。

CanvasVideoTasks 在识别已有请求后、绑定新调用来源前执行参数检查；同请求重复读取不重新校验或提交。已受理任务在查询前保存原 ID、实际路由与原凭据版本；旧 generic 和曾误配 APIMart 的冻结回执按原协议 GET，不能因新映射改成另一个生成入口。未知受理不自动换端点、Key 或型号重交。原权限／Owner／归档仍走现有边界。

两类画布共同读取服务端能力：时长离散集合／范围、比例、分辨率、选项、参考数量及通道联动。时长、比例、清晰度等旧无效值保留可见并禁用生成；功能开关按上方 2026-11-27 反馈隐藏不支持项并从当前有效参数过滤，不改原保存值。新经典节点按模型采用合法初始值。Sora 相同 ID 的两类 Key 分组必须显式选择；分组和时长不能静默推断。1080p 放大另计费用按贞贞 2.5 说明提示。未落实协议的目录型号显示“尚未适配”，不允许收费试错；既有回执续查不受此新提交限制。

### 当前精确型号清单

以下为 **27 个型号的本地协议适配**，不是 27 个当前真实出片通过，也不是对 Key 分组／余额／当前供给的保证。

| 系列 | 本地已适配的精确 ID | 本批接入范围 |
| --- | --- | --- |
| Seedance | `doubao-seedance-2.5`、`doubao-seedance-2.0-mini`、`doubao-seedance-2-0-260128`、`doubao-seedance-2-0-fast-260128` | 原生 `/seedance/v3/contents/generations/tasks`；Mini 4／10／15 秒、480p／720p；参考图／视频／音频和首尾帧，2.5 的 1080p 放大额外费用提示 |
| Grok | `grok-imagine-video-1.5`、`grok-imagine-video`、`grok-1.5-video-6s`、`grok-1.5-video-10s`、`grok-1.5-video-15s` | 前两种保持各自 JSON／XAI 协议；后三种单张图 `input_reference` multipart、固定时长及 720p，不把名称相近当作同一接口 |
| Veo | `veo3`、`veo3-fast`、`veo3-pro`、`veo3-pro-frames`、`veo3-fast-frames`、`veo3.1`、`veo3.1-fast`、`veo3.1-pro`、`veo3.1-components`、`veo3.1-fast-components` | 统一 v2；当前接入 8 秒档，输出分辨率由型号决定；不传接口未支持的通用 duration／resolution／seed，帧／参考数量按型号收敛 |
| Sora | `sora-2`、`sora-2-pro` | 显式 Key 分组：官方 multipart 当前接入 4／8／12 秒、720p；兼容 v2 为 10／15 秒，Pro 15／25 秒和 HD；这是当前维护子集，不宣称覆盖供应商全部档位 |
| MiniMax | `MiniMax-H3` | 既有 `/v1/videos`，5–15 秒、768P／2K，三类素材及专用字段 |
| Wan | `wan3.0-video`、`wan3.0-video-prime` | 既有 `/v1/videos`，1–30 秒、480P／720P／1080P；专用参考字段和选项 |
| Vidu | `viduq2-pro`、`viduq2-turbo`、`viduq4-preview` | 原生 Vidu v2；Q2 Pro 可多图，Turbo 保留已维护 720p；Q4 只启用当前示例明确的单图 5 秒／720p，原任务 `/creations` 查询 |

Kling 尚未开放新提交：当前工坊文档 3.0 图生路径含双斜线 `/kling//image-to-video/kling-3.0`，查询文档则分别使用旧 `/kling/v1/videos/text2video/{id}` 与 `/kling/v1/images/image2video/{id}`；未取得新生成与查询的同一可靠契约。供应商开源画布的 Kling 4 接入又属于另一 `api.seedance.nz` 通道，不能将工坊 Key 发给该站点，也不能凭 `kling-video-4.0` 目录名称拼接接口。相关文档已留在外部证据中，后续先澄清再实施，不能以收费试错补文档。

原始依据为贞贞 [Seedance 原生接口](https://gpt-best.apifox.cn/api-440251336)、[Mini](https://gpt-best.apifox.cn/api-513301405)、[2.5](https://gpt-best.apifox.cn/api-515548387)、[旧 Grok 1.5](https://gpt-best.apifox.cn/api-472416532)、[Veo](https://gpt-best.apifox.cn/api-343590061)、[Sora 原生](https://gpt-best.apifox.cn/api-362481361)／[兼容](https://gpt-best.apifox.cn/api-358024351)、[Vidu](https://gpt-best.apifox.cn/api-374481658)与开源画布固定 `c3292f0f` 的实际请求。参数解释优先相同渠道，目录和示例不足以证明所有组合。

### 验证、预览和未完成项

固定预览仍为 `http://127.0.0.1:18000/`，原开发数据和登录身份保留。本机模拟平台新增六个视频型号供交互检查，仍指向 `127.0.0.1:13002`，没有改真实平台或部门来源。内置浏览器从原首页建立并操作两份独立画布：智能 `577c89660c7c4d5b879845ce918e83a6`、经典 `e570c4a3e19a4076ae3de4fc91aa602f`。Mini 旧 5 秒禁用，选 4 秒恢复；经典新节点默认 4 秒；Veo 只选 8 秒且不再自动开启不支持的全能参考；Sora 未选通道禁用、官方 8 秒合法、切兼容保留 8 秒并提示、只提供 10／15 秒。未适配 Kling 禁用，页面控制台未观察到错误。未点击任何生成按钮，普通用户真实鼠标本轮未另复验。

真实贞贞只补素材上传：使用新增第一个 Key、已存复杂服装海报 PNG 1024×1536／2,632,640 字节，当前执行模块的 `/v1/files` 返回 **HTTP 200**，取得 `webstatic.aiproxy.vip` 地址。没有提交图像或视频模型生成，没有重投原失败；此结果只证明鉴权和素材上传，不证明出片。证据 `video-reference-upload-live.json`，带签名的 URL 只留在私有外部文件。

开发环境以隔离的 `@ffprobe-installer/win32-x64@5.1.0` 为本批参考音视频检查提供工具，未改全局 Python／Node 或项目应用依赖；当前预览进程 PATH 已配置。真实文件使用复杂海报制成 3 秒 512×768 MP4 及 3 秒 WAV，探测通过；音频误放视频槽、33 秒超限音频和不存在文件均生成前拒绝，HTTP 调用 0。外部 `media-preflight-real-files.json` 保留结果。正式部署仍需在实际服务进程 PATH 配置 `ffprobe`，并完成包内依赖／重启验收；未随本轮源码自动发行该二进制。

定向测试覆盖误路由、新旧 Grok、Seedance 全参考、Sora 分组、素材错误不提交、上传失败不生成、原始 RGBA 字节、实际 Python 能力驱动的两类前端规则，以及主进程中断后的原 ID GET 续查。191 项相关定向检查通过；特殊字符原 ID 查询补验所在 56 项通过；JavaScript 语法、17 项文档契约及 155 文档／741 本地链接检查通过。没有重跑全仓企业回归，不以这些结果替代真实视频质量、计费／退费或容量验收。

下一阶段按同一路线图：负责人审阅本地交互；单独明确视频预算与 Key 分组后，以已准备的少量 Seedance／Grok 请求验证真实图生视频、回执与归档；确认 Kling 同渠道生成／查询契约；在候选正式固定后纳入媒体工具、升级包及 11.3 部署验证。普通 5.5 原生透明与双 Key 真实容量仍按下方原结论，不能借本轮视频修复关闭。

<a id="zhenzhen-provider-audit-20261126"></a>

## 2026-11-26 贞贞渠道与正式 11.3 视频只读复核

该只读阶段为负责人要求的兼容与失败原因调查，不是新增收费验收或生产修复。正式源码基准 `v2026.11.3@a5613dabb6307ceeae4d3bdfc67979b78363ccd7`；供应商仓库当前 main 固定为 `T8mars/T8-penguin-canvas@c3292f0fcf92d620490acc62042882387354a976`。本地图片／视频执行纯函数与正式视频模块对照，不把 main 或备份分支当成已部署内容。外部证据目录 `D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/development/provider-audit-20261126/` 保留公共文档、源码片段、只读结果、路由对照；私有凭据只在其 private 子目录中以现有 DPAPI 密文保存，不进入仓库或本记录。

### 多 Key 凭据与容量

按负责人本轮提供顺序，新增第一个 Key 的工坊 `/v1/models` 为 HTTP 200，模型目录 914 项，包含本轮两种 Seedance 与 Grok；订阅查询成功，用量只读查询为 0。新增第二个 Key 的模型与订阅查询为 HTTP 401 Invalid token，不能因此判断其他站点也无效，更不能投入当前容量对比。既有 Key 从原加密版本只读取出，重新鉴权和订阅查询均为 200，模型目录同为 914 项。未将目录可见当作真实生成成功，未将订阅额度单位擅自换算为人民币。

两个新增 Key 已使用原 `WindowsCredentialVault` 加密并回读核对；未改产品配置、部门来源或既有凭据。现有 Key 加新增第一个 Key 可作为后续双 Key 比较材料，仍须确认供应商 Key／分组／账号的限额口径、目标业务并发和单独预算。余额独立不证明运行容量独立。该只读阶段只有 GET；新图片／视频生成 POST 为 0，无视频压测或旧任务重投。

### Seedream 5.5 透明协议

方舟[图片 API](https://docs.volcengine.com/docs/ark/image-generation-api?lang=zh)的普通 5.5 使用根层 `background=transparent` 与 PNG。工坊当前公共定价目录及负责人截图也声明这些选项，但其 `seedream-v5.5` 和拆层型号仍链接 [api-522995149](https://gpt-best.apifox.cn/api-522995149)，正文为旧 `seedream-v5-flash/layer-decomposition`，未提供普通 5.5 的专用透明编码证明。不能把目录声明写成实测通过，或以旧 Flash 的单图拆层参数替代普通编辑。

供应商[工坊通用 Seedream 请求](https://github.com/T8mars/T8-penguin-canvas/blob/c3292f0fcf92d620490acc62042882387354a976/backend/src/routes/proxy.js#L3215)发送根层 model／prompt／size／image／output_format，却没有透传 background，不能作为工坊普通 5.5 透明成功样例。新 [5.5 合同](https://github.com/T8mars/T8-penguin-canvas/blob/c3292f0fcf92d620490acc62042882387354a976/backend/src/shared/seedream55DraftContract.mjs#L12)属于平价 AI 小屋：`api.seedance.nz`、`/v1/image/generations`（image 单数）、`seedream-v5.5-i2i` 等精确型号，透明字段为 `metadata.background`／`metadata.output_format`，素材用 `images`；需该渠道自己的密钥。与现用 `ai.t8star.org/v1/images/generations`、`seedream-v5.5` 不是同一调用合同。本轮未向新域名发送凭据或收费请求。

因此 D1 的“上游原图 RGB、与归档一致”仍有效，不能只改成 metadata 就宣称解决。工坊参数透传、实际路由和原请求的具体生成原因仍需供应商核查；既有框选保留源 Alpha 不变。没有撤销能力限制或重新调用试错。

### 正式 11.3 视频故障与支持范围

负责人最新截图明确显示 `grok-imagine-video-1.5` 与 `doubao-seedance-2.0-mini` 使用本地 `/assets/input/ai_ref_4ab355da6205.png`，分别报 APIMart 上传 404／上传异常；用户另确认 `grok-imagine-video` 也失败。前两项的直接失败点在图片转换阶段，不是上游视频模型的生成拒绝。截图 Mini 还选了 3 秒，另不符合其公开文档列出的 4／10／15 秒。

正式 `is_apimart_provider()` 只检查 `protocol=apimart` 或地址含 `apimart.ai`；`canvas_video()` 优先进入该分支。精确函数离线对照证明，`https://ai.t8star.org/v1` 加 APIMart 协议会同时被识别为贞贞和 APIMart，进而选择 `/v1/uploads/images` 和错误的通用提交；同一地址加 OpenAI 协议则不走 APIMart，Grok 1.5 选择 `/v1/videos`。报错字符串硬编码 APIMart，上传主机跟随当前 Base URL，不能据此断言图片发给了 APIMart 公司。对生产 `http://11.0.0.37:8000/api/config` 仅发一次未认证 GET，返回 401；该只读请求没有取回生产配置；随后负责人设置截图已确认贞贞地址与 APIMart 协议混用，见上方 SUP-04.VID。本机仍未直接核验生产运行包。未登录／更改生产、重投失败任务或设置公网素材地址。

| 精确型号 | 正式 11.3 已有适配 | 实际证明及当前边界 |
| --- | --- | --- |
| grok-imagine-video-1.5 | `/v1/videos` JSON、seconds 字符串及原 ID 查询 | 历史 1 秒文生视频成功；本轮生产图生视频失败，上传路径问题未消除，不列为当前生产通过 |
| grok-imagine-video | `/xai/v1/videos/generations`、专用素材和查询 | 已有协议适配；负责人本轮报告失败，缺原错误，不列为真实可用 |
| MiniMax-H3 | `/v1/videos`、imageUrls／videoUrls／audioUrls | 历史 5 秒 768P 文生视频成功；未复验本次生产主机与多模态全部组合 |
| wan3.0-video | `/v1/videos`、image_urls／video_urls／audio_urls | 历史 5 秒 480P 文生视频成功；未复验本次生产主机 |
| wan3.0-video-prime | 同类专用适配 | 协议检查通过，无对应真实出片证据 |
| doubao-seedance-2.5、doubao-seedance-2.0-mini | 仅走通用 `/v2/videos/generations`，缺专用能力规则 | 本轮报告失败；Mini 时长、camera_fixed、多模态角色／音频及选项存在独立缺项 |
| grok-1.5-video-6s／10s／15s | 无专用适配，回落通用 JSON | 供应商画布要求 `/v1/videos` multipart、size 和单张 input_reference，合同不匹配；不是本轮截图的旧 Grok 型号 |

Seedance 参考[2.5 统一接口](https://gpt-best.apifox.cn/api-515403085)、[Mini 统一接口](https://gpt-best.apifox.cn/api-510506694)、[2.5 原生接口](https://gpt-best.apifox.cn/api-515548387)及供应商 [Seedance 实际请求](https://github.com/T8mars/T8-penguin-canvas/blob/c3292f0fcf92d620490acc62042882387354a976/backend/src/routes/proxy.js#L8134)。当前文档本身有矛盾：2.5 的 schema 型号枚举遗留 2.0，部分 required 与文生示例不一致；不机械照搬错误的枚举／必选项。[新版 Grok 表单路径](https://github.com/T8mars/T8-penguin-canvas/blob/c3292f0fcf92d620490acc62042882387354a976/backend/src/routes/proxy.js#L7806)与[旧 Grok JSON 文档](https://gpt-best.apifox.cn/api-472416532)也不能混用。Veo、Sora、Kling 等目录名称不构成本项目逐型号支持或当前上游可用证明。

建议先核实并校正生产平台协议／地址，再修复供应商识别优先级与缺失的精确视频合同，沿原素材、任务凭据、查询和归档实现。离线／本机模拟先覆盖各输入路径，确认后再按单独预算选最小真实样本；不通过切换型号反复付费排查。本轮未实施业务修复、提交／推送、发行或生产操作，既有营销路线保留。

<a id="pre-cleanup-backup-20261126"></a>

## 2026-11-26 当前目录磁盘清理前备份

范围为本聊天 f2ad 工作树 `C:/Users/22259/.codex/worktrees/f2ad/26-5-27-无限画布`。负责人明确要求确认已修改、已暂存、未跟踪代码和文件全部提交／推送。开工 detached d821098，与实时 fetch 后的 origin/main 相同；实际展开目录后是 58 个修改、72 个未跟踪文件，暂存为 0，共 130 项、7,617,830 原始字节。没有删除、重命名、冲突或 stash。公开仓库中真实凭据不得上传；内容扫描的三个 `sk-` 样式命中均来自历史 task 分支名，无真实 provider／GitHub token 或私钥。忽略项为 58 个 pyc 和 5 个 pytest 缓存，没有忽略开发源码、env 或数据库文件。

创建独立 `codex/backup-20261126-precleanup` 并精确暂存 130 项，保留原业务内容。提交 [`e98731c9865a5952fa6ecb8c6cf230be852aa3f8`](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/commit/e98731c9865a5952fa6ecb8c6cf230be852aa3f8) 已 push 到 origin；`ls-remote` 与本地提交一致，随后调用 GitHub 递归 Git Tree，全部 926 个文件路径／blob ID 与本地树一致，130 项逐一在远端存在。原始行尾由本机 Git 既有 autocrlf 规则处理，不修改业务语义；外部另有提交前原始字节 ZIP 和补丁，不把同盘副本当成远端备份。

每项文件的原状态、字节数、提交 ID、提交／推送状态、远端内容核对和固定提交文件链接保存在[CSV 清单](./backup-audits/2026-11-26-development-files.csv)。后续本轮只提交备份清单／恢复说明和原事实文档更新，源码快照仍可由该固定提交恢复；业务代码没有因备份整理而修订。`main`、正式版本、PR／合并与生产部署保持原状态，不因源码备份就标记营销功能或模型质量通过。

补查同一 Git 仓库其他工作树，只读发现下列目录还有未提交内容（数量为默认 status 条目，目录未展开，不是当前 130 项）：

| 其他工作树 | 状态条目 | 本轮结果 |
| --- | ---: | --- |
| `C:/Users/22259/.codex/worktrees/launcher-upgrade-maintenance/26-5-27-无限画布` | 46 | 当前目录范围外，未提交／推送 |
| `C:/Users/22259/.codex/worktrees/manual-acceptance/26-5-27-无限画布` | 134 | 当前目录范围外，未提交／推送 |
| `C:/Users/22259/.codex/worktrees/one-confirmation-upgrade/26-5-27-无限画布` | 1 | 当前目录范围外，未提交／推送 |
| `D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/t/CHAR1011/source` | 36 | 当前目录范围外，未提交／推送 |

另有 **27 个本地提交不在任何 origin 分支的可达历史内**，固定清单见[本地提交 CSV](./backup-audits/2026-11-26-other-local-commits.csv)。它们未由本次源码提交自动备份；本轮不自动推送其他历史分支，避免扩大当前源码范围。`D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/development/` 的运行副本、测试证据、模型样本、配置和辅助脚本也不属于本仓库源码快照，不能据此删除。没有执行磁盘清理、reset、clean、递归删除或生产操作。

按[恢复说明](./backup-audits/2026-11-26-restore.txt)可从 GitHub 克隆备份分支，或锁定源提交；不需要依赖当前工作树和外部本机索引。恢复源码不等于恢复运行数据库、凭据或未上传实验资料。本轮源码核对、提交和推送结果与完整业务／设备现场验收分开，下一任务仍以原 CURRENT／唯一路线图为准。

本机审计副本：`D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/backups/pre-cleanup-20261126-144534/`，含原始清单、源码 ZIP／补丁、远端树对照和其他工作树只读盘点；审计资料须以 GitHub 上的清单与本段为可跨设备恢复的事实，不依赖清理后本机副本存在。

<a id="mkt-01-b4"></a>

## 2026-11-26 MKT-01.B4 全屏智能改图、文字与视口交互

### 后续五条反馈：文字重叠、逐层显隐与取消清空

负责人实际操作补充了文字输入重叠、侧栏显隐无效，以及取消后 1–7 号标记和输入继续累积。本轮沿原 B4 修订，不启动其他营销节点或模型测试；此前有限页面检查未覆盖这些组合路径，以下追加结果为当前状态。

实际复现与原因：

- 新的透明输入仍与文字 canvas 同时显示，旧 `layer-text-edit` 的深色 textarea 入口也保留；文字工具与双击不是同一路径。首次点击完成后调用整块重绘，破坏后续双击事件；失焦确认同样可能在按钮 click 前替换其 DOM。
- Editor 已取得被点行的 layer，但 `Session.action` 再次只读 selected，故点击非选中行的眼睛实际隐藏另一层；智能改图 document 捕获阶段的关闭／重绘还可能吞掉侧栏同一次点击。
- SmartEdit 在 close 时缓存 marks／prompt／undo，open 时自动恢复。此行为与负责人本轮明确的“取消后清空”要求冲突。

修订只有同一批组件：移除旧全屏文字编辑 DOM、样式和开关，所有文字入口使用 Surface／Annotations 的透明输入。编辑文字时仅隐藏当前层的预览和控制点，输入确认后恢复；使用继承的 visibility，避免破坏智能改图期间普通画板的隐藏。失焦确认更新原文档但不重建被点按钮，普通选中只刷新悬浮工具栏；双击和工具栏文字入口共享一次撤销边界。Surface 阻止 textarea 双击继续冒泡，不再出现额外输入或新文字层。

Session 的 action 接受可选目标 ID，旧调用仍默认 selected；Editor 显式传入被点行 ID，不改选中项。侧栏纳入全屏呈现上下文，点击阶段退出 SmartEdit 后仍处理原目标，避免捕获阶段替换按钮。隐藏选中层同步隐藏控制点与悬浮工具，撤销可恢复。SmartEdit 移除同页草稿 Map，关闭前先断开本次 state 再取消输入，防止取消回调重绘旧会话；重新进入从空 marks／prompt／undo／redo 开始。该规则适用于点外取消、关闭及退出，不删除已保存 LayerDocument、持久模型设置、归档输出或已受理任务；先前 B2 的自动草稿恢复说明保留为历史，由本条新要求取代。原任务绑定和完成幂等回填不变。

官网依据复用本批当前公开 `9054.8f8410c480.js` 的文字编辑器（普通输入元素排除于画布手势、onBlur 提交）和前文全屏模块；没有复制未知私有服务端。取消清空规则来自负责人本轮明确要求。未变更方舟／贞贞协议、Key、HTTP 路由、Schema 或并行策略；本轮生成请求 0、付费 0，不沿用前批预算。

从原首页进入新审核画布 **MKT-01.B4 反馈修复 · 输入与显隐验收**（`6c4573ef5f9d45f1b9014f347fb607ac`，reviewer 所有），使用复杂服装整图和五层分离图。管理员浏览器实际验证：

- 输入期间 `layer-annotation-text` 恰好一个、旧输入为 0，当前文字 canvas 为 hidden；双击 textarea 不增加输入，Enter 后文字预览恢复，双击画布文字也只开一个输入。两行“单一输入／保留纹理”保存关闭重开保持；取消新文字后层数仍为 2。
- 正在输入时直接点另一行眼睛，一次点击即隐藏所点层，原选中层不变；非选中层显隐、隐藏选中层、撤销恢复均验证。智能改图期间点另一行眼睛也一次完成退出与显隐，重新进入无残留标记。
- 三轮各新建三个标记及描述、点外取消再进入，均为 3 → 0 标记、空描述、撤销禁用；关闭全屏再进入同样清空。分离细节图层的两个标记／描述取消重进为空，临时文字输入取消后 textarea／marks／prompt 均清空。正常保存的文字层和五个分离图层保持。
- 最终重载后复验文字双击和显隐，无相关应用控制台错误；曾发现的工具栏刷新作用域错误已修复并加入实际函数检查。原 B4 标签也已重载最终版本，原节点／图层 ID 与素材引用经 API 比较保持。

普通所有者 API 回读成功，新审核画布保存两层整图／文字和五层分离图，六份图片素材 HTTP 200；另一账号访问画布 404。此为普通身份读取与隔离，不冒称普通账号全部浏览器路径已复验。既有模型任务／供应商效果沿用前文与 D1，未新增真实出图或以纯 UI 检查替代原生透明、独立人物分层质量。

CP314 图层／文档契约 **36 项通过**，5 个修改 JS 语法通过；新增检查覆盖显隐目标、空选中时行操作、同一次退出和显隐、单输入绘制、失焦不重建、双击不重建画板、取消后空会话及已受理任务保留。最终文档检查 154 文档／722 链接／0 错误，文档契约 17 项复核及差异空白检查通过。11 个静态文件逐字节匹配运行副本，缓存 `20261126.fullscreen-02`。外部 `marketing-layer-feedback-20261126/` 保存修改前副本、审核画布身份、原画布回读、`delivery-verification.json` 和运行文件映射。页面结果取自中断前已完成的复验，收尾重新连接浏览器不可用，没有转用另一浏览器或重跑模型。未增加报告文档、提交、推送、PR、合并、发行或生产部署，仍待负责人审核；窄屏、其他浏览器及 B3 原生保存／Photoshop 现场项不在本批覆盖。

### 依据、问题原因与模块边界

负责人本轮五条反馈限定为：文字工具、全屏底部交互、空白取消选中及全屏内智能改图。本轮先操作登录态官网的文字色板、百分比输入／菜单、选中项禁用和历史提示，再读取当前公开 `async-canvas-image-layer-board-fullscreen.47ffca273a.js`、`5733.a5becc3c6b.js`、`3166.74b367866b.js`、`5912.cf2f05ed5f.js` 和 `9054.8f8410c480.js`。提取的 65190／31557／69922／80729 模块分别提供全屏内交互编辑上下文、视口命令、标注选项和文字渲染依据。文字使用六色、透明输入、600 字重、1.25 行高、Enter 确认／Shift+Enter 换行、选择／移动／缩放与双击编辑；百分比支持输入、适配画布、聚焦选中项和 50／100／200% 预设。官网源文件和提取片段保存在外部 B4 `public` 目录，未把整份官网 bundle 引入产品。

原问题一是空白取消只发生在图层 Surface 内，外层 stage 没有相应失选；二是全屏 `edit-panel` 显式先调用 `close()`，随后走外部画布聚焦；三是文字只提供简易输入，缺少共用编辑状态、色板和几何。修订后 stage 点击清除选择并隐藏工具／控制点；Editor 提供全屏呈现上下文，将同一 SmartEdit 挂在原 dialog 内，侧栏、标题、关闭及底部视口工具保留，暂时隐藏普通画板与输出按钮。进入与退出恢复原全屏视口，结果通过原回填流程添加派生层，不返回外部画布完成操作。

新增独立 `canvas-layer-viewport.js` 计算适配、焦点、锚点缩放、滚轮和平移／快捷键；`canvas-layer-annotations.js` 管理六色色板、透明多行文字输入、一次确认／取消以及文字几何。Surface 和 SmartEdit 共用输入但各用原历史，普通文字仍写 LayerDocument，智能改图文字仍为临时指示。普通新文字保存可选 fontWeight／lineHeight，旧文字未设置时保持原字重／行高，图片原资产不变。模型加载期间工具显示不可操作，避免尚未准备原图时接受无效输入。呈现上下文只含 UI 回调，不进入画布存储或模型请求；SmartEdit、Editor、Surface、Session／Document、原样式、i18n 和 HTML 负责各自接线。缓存更新为 `20261126.fullscreen-01`，无新增路由、Schema、队列或凭据处理。

### 原页面实际操作

通过 `http://127.0.0.1:18000/` 原首页进入新画布 **MKT-01.B4 全屏与文字交互验收**（`fc033e82cd0043278e711a49700a6836`，普通所有者 reviewer）。保留负责人原 B3 画布，不覆盖旧测试记录；当前共享浏览器身份为管理员，普通身份范围由下面独立 API 验证限定。

- 普通全屏点击画板外 stage：选中行、选框和悬浮工具消失。缩放输入 150% 生效，Shift+Digit1 恢复适配 39%；百分比菜单紧贴底部工具上方，未选择时禁用聚焦。空历史提示分别为“无需撤销操作／无需重做操作”。英文六色标签与 Nothing to redo 检查后恢复中文。
- 普通文字从六色色板创建红色两行“秋冬特惠／针织细节”，Enter 确认、Shift+Enter 换行；24px 显示、600 字重、30px 行高、背景透明。关闭／重开后五层原服装文档加文字共六层，文本及参数保持。
- 全屏选图层进入智能改图，父 dialog 始终打开、编辑 portal 在内部；普通色板及旧弹层被清除。蓝色两行文字输入、拖动 60×55px、比例缩放、双击替换文字、撤销通过，选择框与画面联动。Esc 退出仅返回原全屏并恢复进入前 39% 视口；重新进入和 100% 输入后仍在全屏内。
- 全屏底部保留选择／历史／百分比，普通场景保留标注工具；Ctrl/Meta 加减／0／1、Shift+1／2、滚轮锚点和平移计算有定向函数检查。普通 Space 平移接线已实现，本轮未用浏览器原生按住 Space 同时拖动补证，不将数学检查写成该原生手势现场完成。

最后原页面再次打开复杂服装整图的全屏智能改图，实际六色色板为 182×32px（红／黄／绿／蓝／黑／白），父窗口和侧栏保留。预览交付标签保留此状态；未新增生成或改动负责人原画布。普通文字与智能文字不等于 MKT-03 的图片 OCR 改字，后者仍为独立业务批次。

### 任务、权限、文档和验收边界

本轮核对[方舟图片接口](https://docs.volcengine.com/docs/ark/image-generation-api?lang=zh)与[贞贞 GPT Image 2 接口](https://gpt-best.apifox.cn/api-447258891)，继续原两渠道图片适配。官网公开交互参数不能直接当作贞贞已支持能力，私有后端／隐藏提示词未取得。本轮没有修改模型协议或发起付费请求；原图＋标注参考及文字坐标仍走既有图片 API。

原页面全屏完成两次 **本机协议模拟**（请求地址 `http://127.0.0.1:13002`）：Seedream 5.5 `canvas_img_f7d8f052a0394375a22a634df990d860`，以及 gpt-image-2 `canvas_img_ecb434a069f54908b7e0433eda0b8dba`。各恰好一次提交、两张参考、succeeded、归档一图并回填一次；前者矩形参考、后者绿色文字指示。成功退出 SmartEdit 后父全屏仍在，撤销恢复海报原一层。模型原始 900×675 RGB 模拟输出保留正常独立节点，两个回填绑定均为 applied；不据此宣称真实文字／商品效果通过。

只读回验普通所有者访问该画布、任务、媒体成功，另一账号读取画布及任务为 404。此前真实 `canvas_img_e9bed9d785584466a09444dac7b56762`（普通 Seedream）、`canvas_img_08cb562f7c8d4276baca7aada1695ce2`（GPT）及 `canvas_img_75fbcf6e8ba84db5a50a7ac5480f9e20`（拆层五图）仍可从原 ID 回读，不重新提交。本轮不代表普通账号所有浏览器操作已复验，也不改变 D1 原生透明仍 RGB、复杂人物独立分层未通过的质量边界。

CPython 3.14.6 图层及文档契约定向检查 **36 项通过**，8 个受影响 JS 语法检查通过；开发运行时检查通过，无全仓回归。最终文档检查为 154 文档／717 链接／0 错误，文档契约 17 项复核通过，差异空白检查通过。11 个实际静态文件与预览副本逐字节一致，外部 `delivery-verification.json` 保存原 API 回读与模型模拟证据；最终页面重载后全屏内文字色板仍正常，控制台未见错误。未回显 Key、未改账号费用或生产。源码仍为 d821098 加本地候选，未同步另一端、提交／推送／合并／发行。负责人 UI 审核、B3 系统保存与 Photoshop 现场项、D1 模型质量及下一营销批次不被本轮测试替代，按[原营销路线](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md#marketing-node-batches)继续。

外部证据目录：`D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/development/marketing-fullscreen-interaction-20261126/`。含改动前副本、公开源码、QA 画布身份、静态映射、两份模拟回执和只读验证结果；不含产品新增密钥或运行数据库，不覆盖不可变 COORD-R1 快照。

<a id="mkt-01-b3"></a>

## 2026-11-26 MKT-01.B3 全屏融合与下载对齐

**后续负责人现场确认（2026-11-26）**：负责人反馈“我下载 psd 到能正常打开”，该样本的 PSD 下载及正常打开记为现场通过，替代下文原时点的这两项待验状态。未取得应用名称／版本或全部逐层操作说明，不扩大为所有 Photoshop 版本的人工兼容验收；文字与标注仍为栅格图层。此确认无需重新生成或再次要求负责人下载，同步 CURRENT 和唯一路线图，本轮新增付费调用为 0。

### 官网依据、原因与改动

负责人本轮四条浏览器反馈要求对齐全屏图层编辑右上角。本轮先操作登录态官网的下载、融合及模式菜单，再读取公开 `async-canvas-image-layer-board-fullscreen.47ffca273a.js`、`async-canvas-image-layer-board-psd-export.3c5af20d61.js`、`image-layer-board-psd.47c5b92c82.js`、`async-canvas-image-layer-board-zip-export.6745c14fa7.js`。官网实际入口为“下载／融合图片及下拉／关闭”，下载只有“导出全部图片／导出为 PSD”；模式只有“融合图片／合并图层”。公开调用分别进入 generate 和本地 merge；私有后端代码、模型内部提示词未公开，不将本项目默认指令写成官网隐藏提示词。

原项目缺少独立的画板下载入口，把单层 PNG、合成 PNG、ZIP、拆分等混在弹层；融合主按钮直接调用 run，导致缺少填写提示词和确认生成的步骤。现在 Editor 只维护一个活动弹层，头部下载和单层工具分开；融合点击先开卡片，卡片“生成”才沿原图片任务提交；合并图层继续本地合成。切换菜单、点外、Esc／卡片 X 收起弹层，保留同页提示词，Esc 不直接退出整个编辑器。单层工具仍可下载当前 PNG，原位入口复用同一导出模块。

按官网 DOM 测量实现头部 36px 按钮、28px 模式按钮、8px 间距和 12px 右边距；融合卡片右上对齐、top 56px、320×216、16px 圆角，输入区 288×92，生成按钮 80×36。参数旁显示本项目实际平台／模型来源，不套用即梦的积分价格。中英文文案继续原 i18n；最终原页面切换英文后下载菜单与按钮右边界相等，恢复中文后卡片仍为 320×216／输入区 92px，画布名称保留。缓存为 `20261126.output-01`。

### 职责、导出与实际结果

新增 `canvas-layer-export.js`，仅依赖 LayerDocument 和传入的图片读取／上传／下载；负责 ZIP 条目、图层栅格化及 PSD，不读取密钥、业务数据库、任务或供应商协议。PSD 使用固定 MIT `ag-psd@34.2.3` 本地 bundle，仅点 PSD 时加载，保留原 LICENSE／SOURCE.json，部署不依赖外部 CDN。ZIP 仍 POST 原 `/api/canvas-assets/download`，图片使用原文件，文字与标注通过原上传保存 PNG；PSD 保留中文名称、顺序、位置、Alpha、隐藏和不透明度。文字与标注是栅格图层，未交付可编辑字体样式、PSD 导入或 Photoshop 原生文字。合并、融合和原任务的接口／凭据绑定、权限、归档均未迁移，没有新 Schema、限流或供应商。

固定复杂服装样本的导出夹具包含 5 个原图片层、1 个中文文字层及箭头标注；其中一个图片隐藏、另一个不透明度 0.65。实际导出 PSD 1024×1536、13,384,252 bytes、7 层；ag-psd 完整解码核对层名、顺序、隐藏、不透明度、边界及像素 Alpha。独立 Pillow 成功读取合成图及 7 条图层记录；Pillow 逐层解码存在自身帧限制，不把它写成完整逐层像素验收。ZIP 6,028,284 bytes，含 7 个图片文件及 layers.json，5 个原图片逐字节等同原归档，隐藏层、文字和标注保留。内置浏览器未回报原生下载落盘事件；实际文件通过外部只在本机运行的导出夹具捕获，Photoshop 人工打开及系统保存对话框仍未验证。

### 页面、身份、原任务与费用

原根首页 → 无限画布 → **MKT-01.B3 图层融合与下载对齐验收**（`c16a2a8c7c4e4e5bb56c94623c1b141b`）完成实际点击：两个下载选项、模式选中态、弹层互斥、卡片尺寸、Esc 收起／同页草稿重开、本地合并回到画布。重载后五层原文档保持，合并只新增正常结果节点。管理员原页面提交一次本机模拟融合 `canvas_img_2a4a64e7470b47cda947a07942a61821`，状态 succeeded、归档 1 图，提示词保留；不是新的上游真实效果验收。

普通所有者 reviewer 可读取验收画布、原图片并通过原素材接口导出全部内容；使用本人上传的复杂服装图提交一次本机模拟任务 `canvas_img_60ff6c9b61824939bbb20ab46f4c2bc7`，succeeded 并归档。跨账号上传参考图、其他账号画布及他人任务仍 404；验收画布所有权不赋予读取管理员私有任务回执的权限。原真实拆层任务 `canvas_img_75fbcf6e8ba84db5a50a7ac5480f9e20` 由原身份回读 succeeded、5 图归档，未重投或改变绑定。原负责人画布和前批 D1 文档未改写。普通账号的正向调用与下载是接口验收，不能冒称普通账号浏览器现场逐项操作。

本轮重新读取[贞贞图片编辑文档](https://gpt-best.apifox.cn/api-447258891)，方舟文档本轮读取超时，沿用 SUP-04.S55 已验证编码和 D1 既有真实证据，没有据此更改协议或宣称本轮官方模型补验。新增付费调用 **0**，没有滚用此前预算。34 项 CP314 定向检查（图层／导出／Editor 和文档契约）、4 个变更脚本语法检查和运行时检查通过；最终文档检查 154 文档／709 链接／0 错误，8 个静态运行副本与当前工作区逐字节一致。负责人现场认可、原生透明／独立人物质量、源码审核、双设备增量同步、合并、发行和生产部署仍各自登记。

证据目录：`D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/development/marketing-layer-header-20261126/`，含 before／public 源码、PSD／ZIP／合成预览、psd-layer-metadata、delivery-verification、mock-ui-task、ordinary-owned-reference-task 和运行文件清单。独立导出夹具只存在开发产物目录，不加入产品 HTTP 入口。

<a id="mkt-01-d1"></a>

## 2026-11-26 MKT-01.D1 框选保真与复杂分层效果

### 范围与实施

负责人本轮要求收口局部编辑保真、透明输出及复杂分层。沿原 MKT-01.D 登记 D1，收益是防止框选外服装／文案被整图重绘、在局部改色时保留已知透明轮廓，并减少人物层补全覆盖原遮挡。独立 `canvas-layer-edit-result.js` 只做矩形区域判定、源与生成像素合成；SmartEdit 负责界面、源快照、上传与派生结果，画布 adapter 仍只接原任务和文档。未新增服务、数据库、依赖、限流或任务体系。

本轮复核官网当前登录态智能编辑 DOM、既有公开 SmartEditCommerceEditor／redraw 模块及[方舟图片 API](https://docs.volcengine.com/docs/ark/image-generation-api?lang=zh)、[贞贞编辑文档](https://gpt-best.apifox.cn/api-447258891)和[拆层文档](https://gpt-best.apifox.cn/api-522995149)。公开前端不能提供私有后端提示词；本地像素保护是本项目适配，不冒称即梦内部实现。贞贞公开 `T8-penguin-canvas@c3292f0f` 的新 5.5 文档使用平价小屋型号，不能将其参数或验证外推本项目工坊型号。

只有全部指示均为明确矩形框选时，保存 `layerEditTarget.regionEdit`（原图资产、源尺寸、区域及保留 Alpha）；原模型请求仍是图片＋文字／坐标，不向不支持 mask 的模型发送伪造 mask。候选图对齐源像素网格后只替换框内 RGB，透明源保留原 Alpha；框外逐像素复用，回填保持原尺寸，原模型高分辨率产物仍在原输出／归档。点、画笔、箭头或混合指示不强行猜选区。保留轮廓只适用于局部编辑，不能生成原本不存在的透明轮廓。

派生 PNG 走原上传，存于可选 `preparedAsset`；同一在途完成通知复用一次准备，保存重开复用已存资产，不重做上传或收费提交。原始模型输出、任务 ID 和所有层始终保留；回填复用原 Session.remember／撤销，复制仍移除旧回填绑定。原无该可选字段的任务继续原行为。

### 实际结果

| 范围 | 本轮证据与结论 |
| --- | --- |
| 三份既有真实服装结果，新增费用 0 | 原页面重新应用 Seedream／GPT 原改色回包和原 RGB 透明失败样本。两张海报各 1,147,284 个框外像素 RGB／Alpha 无变化；透明人物整张 Alpha 无变化、范围 0–255。框内实际使用生成像素，不以完全不修改源图冒充通过 |
| 原页面本机模拟 | 透明人物选层聚焦，未框选时显示当前渠道未通过原生透明；框选及输入后允许继续。仅请求本机贞贞模拟服务，原图片任务回填一层；撤销 3→2、重做 2→3，再撤销恢复业务样本。模拟生成内容不作为业务质量验收 |
| 新真实透明补验 | 原任务 `canvas_img_c45aea06739546c09f80bb0fc8ccfa03` succeeded，但原生 `/v1/images/generations`、无 async、`background=transparent`／PNG、RGBA 输入（Alpha 0–255）仍返回 1024×1536 RGB。这是效果失败，不能只归因异步包装。无收益的同步路由试改已撤回，最终 main 接线保持批前原样 |
| 新真实复杂分层 | 原任务 `canvas_img_75fbcf6e8ba84db5a50a7ac5480f9e20` succeeded，底图＋4 个 RGBA 层，全部归档。沿真实 bbox 和 z_index 合成，人物组保留女性开衫／手臂在男性前的关系，标题、价格及两张细节卡片完整。以“互相遮挡的人物作为一组”规避独立补全冲突，不调整层序掩盖旧失败样本；不代表两个人可各自移动或整图逐像素复原 |
| 准确能力 | 当前维护的贞贞 Seedream 5.5 普通生成新增 `supports_transparent_background=false`；共同能力接口不再宣称已通过，后端拒绝新透明要求。opaque、auto、分层 RGBA、方舟原生透明与历史原任务查询分别保留。智能改图的框选合成使用原 Alpha，不将其标记为供应商原生透明成功 |
| 费用 | 负责人另批不超过 3 元、最多两次，独立于已结束的 13 元／5 元批次。恰好两次新提交，对应 Key 时段账单聚合增量约 1.09 元，不是逐任务独立账单；余量不再使用，临时来源及平台已恢复停用，无方舟付费调用 |

新画布 **MKT-01.D1 局部保真与透明输出验收**，ID `54ede8b973fe477c8cf2e48f8ba59256`；从原 `http://127.0.0.1:18000/` 首页进入。业务原画布 `24380129204441859bedb7b9094fb97a` title／nodes／connections 与批前一致，另建本批副本，不覆盖协作快照。普通所有者可读派生结果，另一账号画布与派生文件 404；原真实任务的持有人及跨账号权限另在最终读回记录核验。

最终以固定 CP314 运行图层、creation-settings、双来源、原生任务／重开、贞贞原结果／归档和文档合同共 **98 项通过**；4 个变更 JS 语法检查、文档检查 **154 文档／702 本地链接／0 错误**及定向 diff 检查通过。原入口重开三组各 2 层，未重复上传／回填，新语义分层 5 层，旧失败分层 7 层仍保留；画布共 10 节点（含原始输出、一次本机模拟和新真实样本）。8 个受影响运行文件与候选逐字节一致，main 与批前完全相同。两项新原任务 succeeded、全部 6 张图片在来源停用后可读，另一账号查询任务 404，方舟透明能力仍为 true、当前贞贞为 false。

直接下载新同步请求回包 URL 的供应商原文件，确认本身为 RGB，且与项目归档文件逐字节相同，因此该样本不是归档丢失 Alpha。普通画布所有者经原下载 API 获得 ZIP：5 张 PNG 与归档原文件逐字节相同，4 个图层均保留 0–255 Alpha，`layers.json` 含全部 5 层。原页面触发单层 PNG 导出，但内置浏览器未捕获下载事件，不以 API／ZIP 证明浏览器本机落盘；该现场边界单列。页面本轮未记录新增 error，不能外推其他来源或历史控制台。

资料集中在 `D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/development/marketing-quality-20261126/`，包含源码前副本、实际出站参数摘要／原回包、像素对照、原任务、画布读回、ZIP 及费用。未提交／推送／合并／正式发行／部署生产，也未覆盖不可变 COORD-R1；剩余效果边界与后续只见[同一路线图](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md#marketing-node-batches)。

<a id="mkt-01-b2"></a>

## 2026-11-25 MKT-01.B2 智能改图：聚焦、指示输入与原任务回填

### 2026-11-26 连续预览与多行输入反馈修复

本轮沿用 B2，两项反馈分别是引用预览不流畅、文字被拆在左侧窄区。官网当前 DOM 显示 `data-layout=multiline`、680px 面板内 652px 正文、13px 字号／22px 行高，正文最多 66px，参数独立位于下方右侧。公开 `6680` 按段落／自然文字宽度与操作区可用空间判断布局；`1225` 对图像窗口、图像、选框和编号的 left／top／width／height 使用过渡，公开主题变量为 600ms、cubic-bezier(.4,0,.2,1)。保留原 500ms 悬停等待，不据这些公开 UI 推断私有后端。

原实现等 500ms 后一次重画 canvas，缺少中间过渡；文字区与参数固定为两列，显式换行也只占左侧。现将源图绘制一次作为预览纹理，由浏览器执行同样的几何过渡，选框和图钉同步；同一引用的重复聚焦不会重启计时，退出取消等待，减少动态效果偏好得到保留。正文按内容自然宽度和显式换行切换单／多行，操作区宽度变化重新测量；ResizeObserver 属于本页输入实例，重建／关闭时断开。显示转换不改变源文件、参考图或模型请求。

原首页进入新独立画布 `59fcbb92c3b34e0596829e9a6e1e8346`（MKT-01.B2 连续预览与多行布局验收）：真实鼠标框选后测得图像宽度 174.46 → 178.66 → 268.01 → 363.99 → 406.06 → 417.67 → 418.58px，选框及图钉同步变化；computed transition 为 0.6s 与上述缓动，证明存在中间几何。采样时间从点击工具回包后开始，不能拿它作为绝对悬停延时。原来相邻两次重画的静态预览实现由本段更新，前段验收保留历史范围。

短文本为 56px 紧凑条；长描述无需手工换行即可自动使用 652px 正文宽度，参数位于正文下方、右侧 12px。手动换行保留；两行面板为 108px，三行显示 66px 时面板为 130px。清空、撤销、模型切换与关闭／主动重开均通过，引用未丢失。清空测试发现 Chrome 留下 `<br>` 占位，已在删除输入事件中规范为空内容，复验恢复 56px 单行；该规范不删除用户显式换行。最终缓存 `20261126.smart-marker-04`。

本轮仅改 smart-prompt／smart-edit／CSS／HTML 与原定向检查，无后端或模型接入变更，未点击生成或重试，费用 0；沿用前轮真实回执及未通过的透明／局部保真边界。固定 CP314 图层 14 项、文档契约 17 项共 31 项通过，2 个变更脚本语法检查通过；文档检查 154 文档／695 本地链接／0 错误，定向 diff 检查通过。7 个静态资产与预览逐字节一致；新画布保持 2 节点／7 语义层，普通所有者读取 200、另一账号 404，负责人原画布 title／nodes／connections 与批前副本一致。资料位于 `D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/development/marketing-smart-edit-motion-20261126/`。未提交／合并／发行／生产部署，未覆盖原协作快照。

### 2026-11-26 标记引用与示例卡片反馈修复

两条反馈均沿用 B2。原 textarea 只拼 `【1】`，无法表现选区缩略图、图钉和联动预览。官网当前 DOM 实测引用 34×16px、左右各 4px，含 16px 图片和 16px 图钉；公开 `1225.e85395c15d.js` 的 98901／36491 管理裁切与 320×180 预览，悬停 500ms 后放大。`6680.4ea632437e.js` 使用行内原子引用，`3545.1333477ea9.js` 提供 280×227.55px 提示卡片和 98912 公开视频映射。实际 DOM 与公开代码是本批依据，不据截图猜测私有服务端。

| 改动 | 实现与兼容边界 |
| --- | --- |
| 独立 smart-prompt 组件 | 引用和文字混排、光标、原子删除、行内移动及复制／剪切／粘贴；回调复用改图历史，无新富文本依赖。未知 `【99】` 原文保留 |
| 缩略图与预览 | 点标记取周围 180px，框选按最大边加 48px 并限制在源图内；缩略图只显示为 16px，源图与模型输入不降采样。预览 320×180、绘制 640×360，并关联画面虚线框、右下图钉及白色角点 |
| 原页面交互 | 聚焦期间隐藏底层大控制点和边框，退出恢复。工具切换不重建输入框，保留光标和焦点；短输入条同行展示模型／分辨率 |
| 操作示例 | 官网公开视频 `static/media/marker.731e8c1f9f.mp4` 按公开映射保存到本地 `static/media/smart-edit-marker-guide.mp4`，907090 字节。示例卡片按 280px、圆角和文案显示，隐藏即暂停，不进入模型参考图 |
| 请求与归档 | 引用在提交边界仍为原 `【编号】` 与坐标说明。SVG、显示预览、HTML 和说明视频不写入提示词或参考图；原图片任务、权限、凭据和归档服务不变 |

原首页进入独立画布 `24380129204441859bedb7b9094fb97a`，使用复杂服装“面料细节”层：真实框选插入、缩略图尺寸、原图／局部预览、拖动引用到文字后仍仅一个副本、删除／撤销、画面橡皮同步移除引用、引用前后输入、换行、多标记稳定编号、同页关闭主动重开草稿，以及切换模型不关面板／不丢引用均通过。只有引用无描述仍禁止生成。示例 readyState=4、paused=false，隐藏后 paused=true；最终版本 `20261126.smart-marker-02`。

测试发现末尾换行后续文字落到换行前，已改为 BR 与不参与序列化的末行光标锚点；复验为“第一行 → BR → 第二行”。原位／全屏共用组件，普通重选不会自动弹回。固定 CP314 图层 14 项及文档契约 17 项，共 31 项通过；4 个变更脚本语法检查通过，文档检查 154 文档／694 本地链接／0 错误。7 个静态资产与预览逐字节一致，验收画布仍为 2 节点／7 语义层，普通所有者读取 200、另一账号 404，负责人原画布 title／nodes／connections 与批前副本一致。资料在 `D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/development/marketing-smart-edit-marker-20261126/`。复制／剪切／粘贴接入原生事件，本轮页面验收未覆盖这三项；既有原生画布 Ctrl+C/V 待验状态不变。浏览器曾记录未标来源 URL 的 `MutationObserver.observe` 初始化错误，未归因为本批代码，未宣称所有控制台来源零错误。

本轮没有生成或重试，模型费用为 0；不把前轮费用再计入本轮，不据 UI 对齐宣称透明、复杂分层或局部保真已通过。源码未提交／合并／发行／部署生产，未覆盖不可变协作快照。前轮真实结果保留下文。

负责人提供 `20261125-140352.mp4`，指出旧简易弹窗反复出现、没有选层聚焦、没有复用图片 API 的编辑体验。本批在原 MKT-01 下实施 B2；收益是直接选中图层进入编辑、标记修改位置，减少另建 API 节点和错误选层。未推进其余六项营销功能、增加供应商、限流或执行框架。源码基线为 d821098 加原候选，文件前副本和验证资料在 `D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/development/marketing-layer-edit-20261125/`，不覆盖 ICE-COORD-20261125-R1。

### 公开依据与协议边界

官网实际进入“智能编辑编辑器”，小 Logo 聚焦至 800%，提供标记、模型、分辨率和窄输入条。公开模块 `3545.1333477ea9.js` 的 `SmartEditCommerceEditor` 提供临时文档、编辑工具和提示词提交；`async-canvas-feature-runtime.2ba1970936.js` 的图层 redraw 会校验源身份、导出源尺寸 PNG、上传、提交并将成功结果加入派生图层。其内部 mode、smart_edit.extra 和私有服务端行为不能直接冒充第三方 API 契约。录屏还确认了画笔、箭头、文字、橡皮和退出状态。原当前脚本版本与已有公开缓存相同，新增延迟资源按公开加载映射读取，未调用竞品生成、会员或私有接口。

对照[方舟图片生成 API](https://docs.volcengine.com/docs/ark/image-generation-api?lang=zh)、[贞贞 GPT Image 2 编辑文档](https://gpt-best.apifox.cn/api-447258891)、[贞贞通用图生图](https://gpt-best.apifox.cn/api-302915860)及现有能力表，复用本项目已验证路由。Seedream 5.5 的精确型号仍以现有平台能力和真实调用为证，不把 GPT 2.6 文档或目录中的其他名称套入。官网交互协议没有移植到方舟／贞贞请求中；本项目使用原图＋临时指示图和 0–1000 坐标说明表达用户指令。未声称挖到私有默认提示词或取得所有型号支持。

### 实现与原问题原因

| 原因／职责 | 本批结果 |
| --- | --- |
| `session.popup=edit` 在失选时只是隐藏，重选又按旧值渲染 | 移除旧改图弹窗，独立组件持有活动会话；点外关闭活动 UI，重新选图不会自动弹出，只有显式点击智能改图才进入。关闭／主动重开同源图层保留本页临时草稿 |
| 没有聚焦视口和指示输入，原位／全屏又有重复改图执行 | `canvas-layer-smart-edit.js/css` 组织聚焦、窄提示词条、标记／框选／画笔／箭头／文字／橡皮、撤销重做和关闭；两入口共用，旧分支移除。旋转／翻转按官网已观察限制明确提示先恢复 |
| 后续图层依次异步解码，重绘时短暂没有对应 DOM | adapter 使用当前画板与图层几何，组件保留上一帧位置；不会把尚未挂载的图层误判为退出 |
| 简易弹窗自造输出尺寸，与模型能力脱节 | 新编辑器直接使用 `CanvasModelPicker` 与 API 节点尺寸计算；切换型号重建合法选项，旧失效选择保留并阻止提交，来源授权复用 source-preview |
| 编辑输入、实际画板与任务目标混在一起 | 从原素材按实际像素准备选层副本，临时指示单独导出，不修改画板；原图片任务保留独立输出，节点 JSON 中 `layerEditTarget` 只保存目标身份、源内容及 Alpha 要求。完成／重开读原任务并幂等加入派生层，源已换图则只保留输出，复制不携带目标绑定 |
| 真实透明请求返回 RGB，不能直接贴回透明人物层 | 以实际像素而非 PNG 后缀判断 Alpha；新请求如不满足透明源要求，保留原图层和独立输出，显示“模型未返回透明图”。不伪造 Alpha，不替用户自动抠图或新增付费重试 |

原上传、任务、素材权限、凭据冻结和归档不改；没有后端协议／数据库／依赖变化。`main.py` 本轮未修改。图层编辑组件只读取公开模型能力、组织本地编辑与结果校验；智能画布只装配视口、选择、原任务和保存。

### 验证记录

真实渠道预算：负责人新增批准 5 元，独立于已结束的 13 元。隔离临时渠道 `mkt01-smart-edit-qa` 只授权 QA 账号，使用已保存凭据，不在源码、日志或文档中保存明文 Key。3 次明确生成均使用原 `/api/canvas-image-tasks`，没有原任务不明后重投。

| 原任务 | 输入／实际结果 | 效果判断 |
| --- | --- | --- |
| `canvas_img_e9bed9d785584466a09444dac7b56762` | Seedream 5.5，复杂服装原图＋编号指示图，1024×1536 RGB，原任务 succeeded 并回填 | 开衫酒红、主要中文／英文和价格可见，无定位标记；纹理／纽扣等仍需严格局部保真验收 |
| `canvas_img_08cb562f7c8d4276baca7aada1695ce2` | GPT Image 2，同原图和指示，1024×1536 RGB，原任务 succeeded 并回填 | 改色生效；还改变了细节卡片颜色及针织纹理，不能记为指定区域外完全不变 |
| `canvas_img_100692fe81414b30a441eae1200d7d0b` | Seedream 5.5，真实女性 RGBA 图层，背景要求 transparent；实际返回 RGB | 透明效果未通过。原产物保留，QA 画板通过撤销恢复原层；新增 Alpha 校验之后以实际 RGB 样本／函数及本机模拟复验，不再次付费投同一请求 |

Key 时段用量：基线 `total_usage=609.6148`，收口记录 `738.6364`，渠道公开换算系数 1.35，对应增量约 1.7418 元；期间也读到过 `653.6364`／`694.6148`，对应约 0.5943／1.1475 元。保留各读数；这是同 Key 时段聚合统计，不能确认变动来自本批结算还是同 Key 其他使用，不能当作逐任务发票。最高观察值及收口值均低于 5 元。临时真实来源和平台已停用，保留原凭据版本以便读原任务／结果；方舟本轮未生成。

原页面从根首页 → 无限画布列表 → 本批 QA 画布进入：单击图层、改图、供应商切换、点外关闭／主动重开、同源草稿、全屏图层入口、小细节聚焦（实际画布缩放约 289%）、文字标记与撤销重做、编号指示、两项真实任务的关闭后回填、画布重开和独立输出已观察。只有编号没有实际描述时生成按钮禁用。页面管理员为 `sup02-qa-admin`，没有通过切换共享浏览器登录来冒充普通账号页面；普通账号另走真实 Gateway 原接口的本机协议模拟，任务／结果归档成功，其他账号读取画布／任务／文件均 404，画布所有者可读本轮真实输出。保留前轮原生 Ctrl+C/V 现场尚未补证的状态。

最终定向检查：固定 CP314 图层 14 项、文档契约 17 项、透明请求构造 6 项、双渠道原页面能力控件 1 项，共 38 项通过。另 5 个 Node 脚本验证智能画布日志、两类画布原视频任务恢复、拆层、多尺寸及模型选项；5 个变更脚本语法检查通过。双渠道 UI 脚本需要后端能力 JSON，通过其原 Python 测试入口输入，不能直接空 stdin 运行。文档检查为 154 文档／688 本地链接／0 错误。

原页面最终本机模拟另有两个任务：透明 RGBA 返回可正常回填并关闭编辑器；不透明 RGB 返回被标为 `alpha-missing`，原层保留、独立输出可读并显示原因。两项均为本机协议模拟、付费 0；前者回填后以实际撤销恢复原层，后者不覆盖。修正拒绝回填后按钮状态没有立即刷新，补入实际组件检查。没有把这两项混入上方三项真实调用。

图层检查覆盖实际 JS 函数、源像素、标记坐标、能力选项、单次原任务、复制／旧绑定、重复应用、源变化、透明像素与异步挂载。停用临时真实来源后，三项真实原任务仍为 succeeded，普通画布所有者可回读归档；跨账号画布／任务／文件继续 404。最终 `smart-edit-05` 原首页重开确认 7 个原语义层、透明失败提示及约 350×354 的小图层聚焦控件，关闭正常；7 个静态文件与预览副本逐字节一致，负责人原画布 title／nodes／connections 与批前副本一致。模拟只证明流程与权限，不证明服装效果；真实 3 项不代替负责人现场认可或全型号稳定性。旧画布新增字段均可选，负责人原 `52bdaa9841e6424eb2e30de5d12cd7f3` 没有被本批写入。

当前状态见 [CURRENT](../CURRENT_PROJECT_STATUS.md)，全部后续工作只在[既有营销路线图](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md#marketing-node-batches)。没有提交、推送、合并、发行或生产变更，也未将 B2 回写不可变协作快照。

<a id="mkt-ui-1125"></a>

## 2026-11-25 MKT-02.D1／MKT-01.B1 营销面板与图层移动修复

负责人反馈原 18000 入口的供应商选择关面板、双生成器重叠、图层节点重叠／移动／复制问题；随后明确普通拖入／拖出必须是移动，只有主动复制才增加副本。早先本批把拖入做成导入副本的处理已撤回，最终实现不再保留同一图片的独立原节点。源码仍是 d821098 加本地候选，本批发生于不可变 COORD-R1 快照之后，不覆盖快照，也未提交、推送、合并、正式发行或部署生产。

| 问题与实际原因 | 修复边界与最终行为 |
| --- | --- |
| 公共 select 将菜单挂在面板外的顶层，外部点击判断先关面板，旧 select 断开后无法提交选择 | `studio-select` 提供逻辑包含判断；多尺寸及拆分模块保留自己菜单的点击，真正外部点击仍可关闭 |
| 图片选择自动打开普通生成器，营销入口没有协调；重复打开营销入口可留下旧营销面板 | 画布 adapter 装配面板开关互斥，不把营销领域逻辑放入公共下拉控件；图层节点只显示自己的生成条，多选隐藏单图层编辑条 |
| 新建图层画板固定偏移，拆层返回实际尺寸后也可能变大 | 新建和返回路径共用原布局模块的 `freeRect`，按最终画板大小避让其他节点，不自动重排负责人既有画布 |
| 之前图层只在双击后接管手势，框外仍留在原文档；本批首版拖入又留下原图片 | Surface 单击接管选层／拖动，以框外松手触发移出；Document 保留旋转／裁剪／Alpha 输出 PNG，源层移除，新普通节点独立。完成的单图片节点拖入时按松手世界坐标保持位置／大小，原独立节点及其画布连线移除；不删除文件、归档任务或其他用户素材。文件上传／素材库导入继续属于明确导入入口 |
| 选中高亮缓存未随实际渲染更新；标题按残留 DOM 高亮跳过真正选择，可能复制旧对象 | 更新实际渲染分支缓存、标题读取模型选中状态，保留已有多选。复用原框选／剪贴板，复制移除原任务／外部父节点引用，内部引用重映射；单图层快捷键不拦截多选操作 |

移入先完成本地解码及目标文档准备，再通过 adapter 同时更新两侧；失败不移除原节点。跨边界移动使用画布整体撤销，合成预览的延迟保存不再增加中间撤销条目。移出后的图片没有 layerParentNodeId、sourceNodeId 或原任务绑定；拖动不会牵动原画板。本批不更改协议、模型参数、数据库、账户／凭据或调用并发，无新付费生成。

源码前副本、原画布开始前内容及机器可读结果在 `D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/development/marketing-layer-interaction-20261125/`。第一个旧画布副本用于复现菜单、布局和本地合并；最新独立画布 **MKT-01.B1 图层双向移动 · 无复制验收**（`91f9a99eea7c46829e8ba27e122f04f9`）从首页进入，复杂服装图真实鼠标往返三轮，每轮移入为 1 画板／7 层，移出为 1 画板／6 层＋1 独立图；总图片数始终 7。连续两次撤销恢复两侧，重开仍为 2 节点／6 层，无浏览器错误。移出 RGBA 文件 Alpha 为 0–255，无父节点／任务绑定或连线。此前独立副本连续新建两画板及本地合并通过，新增画板互不相交；原负责人画布 title／nodes／connections 未被本批改写。

定向验证复用 10 个 Node 脚本，其中新 `test_canvas_layer_interactions.js` 运行真实手势、提取、adapter、创建、框选及剪贴板函数；五轮往返数量守恒、跨边界撤销、松手几何、解码失败不丢图通过。文档合同 17 项与图层原协议／新增前端入口共 13 项使用固定 CP314；结果不冒充完整回归或真实模型效果。浏览器工具拦截原生剪贴板组合键，框选／复制粘贴的函数检查通过，**快捷键现场验收仍单列，未用工具失败断言产品失败或宣称已经通过**。已有普通账号跨用户画布／原任务返回隐藏 404，五个已受理原任务可读 succeeded；另两个旧 403 拒绝占位 ID 本来未受理，不重投。前端移动不变更这些服务端规则，本批没有新增进程退出／重启恢复测试。

下一工作仍按同一路线图：本批负责人原页面审核及快捷键现场补证、MKT-01.D 遮挡／保真、MKT-02.D 其余用途效果；MKT-03–07 保留各自前置，不能把本次交互修复写成全部营销功能完成。既有未同步候选的双设备接收和源码审核继续独立记录，源码／合并／发行／生产按对应授权推进。

**同编号后续：反复拖放模糊。** 负责人再次反馈，之前框外提取一直按图层文档显示尺寸调用 `D.paint` 生成 PNG，移回时又使用该 PNG，导致重复降采样。实际纽扣原始产物是 1018×1030 RGBA，而其反馈旧副本为 420×426；这是项目的光栅化链路造成，不是供应商故障。此前数量守恒验证不包含原始像素比较，不能作为清晰度通过证据。

最终将原始素材与显示几何／编辑参数分开：普通图片移出直接复用原文件，不重绘／上传缩小副本；有旋转、裁剪或透明度效果时，从原素材生成具有源像素密度的显示预览，并在普通节点的 `layerElement` 保存独立图层片段。移回仅在预览 URL 对得上当前图片时恢复原素材及参数；图片已被另行编辑则使用新素材，不回填旧内容。片段不保存原节点 ID、父子绑定或连线，旧画布没有该字段仍正常导入；沿用既有画布 JSON，不增加后端 Schema／接口。计算手势几何在异步解码前完成，并按画板实际内容区投影，避免重绘后的空 DOM 尺寸及边框缩放偏差。

新原页面 **MKT-01.B1 原图保真拖放验收**（`52bdaa9841e6424eb2e30de5d12cd7f3`）从首页进入，真实鼠标三轮往返及保存重开后仍为 2 节点／6 层＋1 独立图；源地址保持 `/assets/output/online_edd56704a8.png`，实际尺寸 1018×1030、显示尺寸 130×132，文件字节及解码像素均与原文件完全一致，Alpha 0–255，独立片段中的原素材引用也持久保存，无连线。`quality-verification.json` 记录该证据；此前移动画布后续有负责人继续操作，其快照按所有独立图片计数，不能把移出的第二个不同图层误记为副本。新脚本还执行 20 轮普通／有编辑参数的往返、移回恢复原图／参数、新编辑不被旧片段覆盖，以及解码期间 DOM 重建的几何检查；有编辑参数的 20 轮属于函数验证，不冒充各效果均已完成真实鼠标验收。已缩小的旧副本不会自动变回原图，新验收页直接使用保留的原始高清产物，没有重投模型或新增费用。

最终定向结果：CP314 图层／文档合同 30 项通过，10 个 Node 脚本通过；现有文档检查 154 文档／680 本地链接／0 错误。预览缓存号为 `20261125.interaction-07`，改动静态文件与工作区逐字节一致，不新增哈希。源码、提交、发行及生产状态仍分开。

<a id="coord-1125"></a>

## 2026-11-25 COORD-1125 双设备阶段 0 与任务分配

负责人转交 Antigravity 只读自检：其仓库为 `c:/CodeProject/Antigravity-Project/项目提交审查-Infinite-Canvas-Enterprise`，main@d821098，0 源码改动；保留 review/user-gov-mvp-1@e66b8ea 与 .agents/。文档 152／557、合同 17 项为该端自报，环境检查因只有全局 Python 3.11.9 与缺锁定依赖而未通过，Node 为 24.16.0。整合方未远程操作该设备、未把另一端结果当作本机执行证据。

本机通过已连接 GitHub 的只读接口确认 main=d8210980d5c773ff91798cac20e8cfb5c14ee92b；[PR #213](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/213) 当前 open／Draft／未合并，Head=9a7e1ecaaf943fc4840aff1c5a9fad5061a2de51、Base=22c4a9300198a9e348a9d5b28766217696aecfe8。变更仅 `docs/architecture/MODEL-ACCESS-RUNTIME-CLIENT-PLUGINS-RFC-2026-11-13.md`，257 行；不是当前营销候选，且其正文的旧基线／发行和设计承诺须对当前代码重新判断。未发布审查评论、改 PR、提交／推送或合并。

本机快照从 Git HEAD 加全部已跟踪差异／未忽略新文件组成：R1 采集时 107 条 status 记录，展开为 109 个文件，55 改动／54 新文件／0 删除，包含此前供应商、资产、图层与创作／营销候选，不能都标为 MKT-02。外部源码资料根为 `D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/development/cross-device-coordination-20261125/`，修订 `ICE-COORD-20261125-R1`。只包含相对 Base 的源码增量、机读清单与必要版本参考；没有原 .git、环境／Key／DPAPI 材料、业务 DB／JSON、上传／生成媒体或安装运行时。仓库自带的三张创作模板 JPG 属源码资产，单独列入清单。归档逐项字节对照与自带 CRC 校验，不新增内容哈希；这不是正式 Release，也未传到另一端。

在原唯一路线图分配 RFC-213.R1 给 Antigravity：先基于 main 与 PR 精确版本做静态事实、职责与迁移边界审查。可独立读取候选修订后补候选差异，未收到时不得判断 MKT 新功能已存在或未实现。交付包含可定位问题、最小建议、证据范围和待决定项，不在本轮实施 Adapter/Run/MCP 等提案。ENV-CP314.AG 仅准备该端项目隔离环境，复用正式 runtime policy／锁文件／checker，不改全局 Python；文档检查不等于 CP314 业务测试。共享入口、模型／任务／凭据、营销节点与总文档由整合方写入，首批审查对所有业务源码只读。

另一端需要保留原目录与分支，仅在干净独立 worktree／目录接收增量；接收后回报 Base、快照修订、文件清单及差异，未回报前状态为待接收。源码快照无提交身份，不以相同 HEAD 代替清单；后续修改产生新修订，不覆盖本快照。任务／边界只在[唯一路线图](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md#cross-device-collaboration)，状态仍只在 CURRENT。没有新业务代码、依赖、Schema、API 限流、收费请求、服务重启或生产变更。

<a id="sup-03-z-e"></a>

## 2026-11-25 SUP-03.Z.E 贞贞设置验证／保存权限错误提示

本批为负责人原设置页故障反馈，不新增供应商或营销范围。内置浏览器管理员旧标签页显示 sup02-qa-admin，但只读当前会话接口实际返回“开发测试账号”、role=user、is_admin=false。原设置页点击验证后，Gateway 日志为 POST /api/providers/test-connection HTTP 403；同会话只读 GET /api/providers 返回 `{"error":"需要管理员权限才能访问企业高风险设置","code":403}`。`interceptors.pre_process` 在代理转发前拒绝普通用户高风险设置请求。因此验证未到贞贞，也未调用生图；未验证输入 Key 的上游有效性。

保存同属管理员门禁，原页面“还没有保存 Key”与画布中“未配置 API Key”一致。旧页面显示的用户名不是新请求身份；同浏览器会话切到普通账号后，不能依赖旧页继续管理供应商。前端 `testConnection`／`saveProviders` 只取 detail，网关返回 error 被替换为通用“验证未通过／保存失败”，是项目错误反馈缺口。

小范围修正：`api-settings.js` 增加页内 `readProviderResponse`，供验证／保存／加载读取 detail／error／message 并显示 HTTP 状态；加载拒绝不清空草稿，保存失败不删除未保存 Key。`api-settings.html` 更新脚本缓存号。复用原错误区域和状态栏，不新增模块框架、登录流程、权限绕过或自动保存。同步两个静态文件到既有预览，不需进程重启。负责人现有标签页有未保存输入，本轮没有刷新或重新登录，故旧标签页仍运行旧脚本；新提示的现场复验需恢复管理员会话后重新打开页面，Node 定向验证不冒充该项已完成。

原 `test_settings_feedback_ui.js` 新增实际函数执行测试：Gateway 403 在验证／保存／加载完整显示，保留状态码、平台列表和未保存草稿；兼容原 detail／message 与正常响应，全部使用本机模拟 fetch，无外部请求。该 Node 检查及 JS 语法通过，既有 settings permission guard 检查通过，文档合同 17 项通过；现有文档检查 154 份／672 个本地链接无错误。门禁脚本说明字符串的既有转义 SyntaxWarning 不影响结果，未因此扩范围。没有触发真实模型费用、改变用户角色、保存输入 Key、调整渠道授权或生产部署，也没有源码提交／推送。

外部资料根为 `D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/development/provider-settings-permission-20261125/`，只保存修改前源码、去敏诊断及运行文件对照，不保存浏览器输入的 Key。用户处理步骤为先保留尚未保存的本机输入，再以管理员登录并重新打开设置页，保存成功后验证；普通账号测试与管理员管理建议使用不同浏览器配置，减少同站点会话互换造成的旧页面误解。

<a id="mkt-02"></a>

## 2026-11-25 MKT-02 智能多尺寸与 MKT-01.D 同素材补验

### 范围与公开依据

负责人要求继续营销功能，公开官网前端代码优先，使用复杂服装，真实测试暂用贞贞而非余额不足的方舟。当前为唯一路线图 MKT-02.A–C，附带 MKT-01.D 保真对照。参考累计约 9.72 元时停止新增生成并询问；负责人明确追加 3 元，仅用于 1920×1080 横图与文字保持补验，累计授权 13 元，两项均已完成。没有新增官方方舟付费请求、API 限流、生产操作或源码交付授权。

当前官网 lazy import 指向[公开 chunk 8590.b7a65aea9f.js](https://lf3-lv-buz.vlabstatic.com/obj/image-lvweb-buz/ies/lvweb/octo_web/static/js/async/8590.b7a65aea9f.js)，模块 32829 为 MultiSizeEditorOverlay；结合 async-canvas-feature-overlays、canvas-core 的尺寸政策和 main CSS 分析。可确认 411px 面板、20px 圆角、4px inset、最大高度 358px、多选计数／最多 20 个目标、按账号保存的个人预设、60 字名称、增改删和比例锁。20 是单次营销操作目标数量，不是全部 API 节点的并发或调用上限。本轮从登录官网菜单点击没有展开最终面板，未消费即梦会员或生成；未出现的状态用公开代码与用户录屏交叉核对，不能将研究截图标为该面板已现场打开。

用户 103456 录屏对应固定用途：电商主图 1200×1200、电商长图 1200×1600、竖屏视频封面 1080×1920、横屏视频封面 1920×1080、横屏海报 1600×1200、宽屏电影画幅 2520×1080（显示 21:9）。客户端可见提交为 `mode:multi-size` 和 targets（width／height／source／可选 presetId）；没有找到服务端重构图提示。项目的商品／人物与文字保持提示是本项目实现，**不称为取得即梦私有提示词**。

模型继续核对[方舟图片 API](https://docs.volcengine.com/docs/ark/image-generation-api?lang=zh)、[贞贞图层文档](https://gpt-best.apifox.cn/api-522995149)与既有 `T8-penguin-canvas@6181ef59` 证据。图片编辑与分层能力分别读取现有契约，不能以 native 字段推断代理支持；本轮不再扩供应商协议或将目录全部型号当作真实可用。

### 实现与职责

| 模块 | 本批修改及边界 |
| --- | --- |
| canvas-multi-size.js／CSS／i18n | 多选、自定义尺寸、比例锁、模型／尺寸组合和目标请求计划；每项生成新构图，不用本地缩放替代；使用原主题与语言 |
| canvas-layer-separation.js | 营销菜单装配可选 actions，不反向依赖多尺寸或修改原拆分状态 |
| smart-canvas.js／HTML | 原 adapter 复用节点放置、连线、素材和任务；显式像素用于新结果占位比例；新增控件加载；语言切换保持用户画布名。经典画布／在线生图 HTML 仅同步共享任务中心缓存版本 |
| generation-task-center.js | 仅导出既有 CallSourceHint.preview，面板复用原授权来源预览，不另建密钥／来源服务 |
| image_size_presets.py | 当前用户个人尺寸 JSON；复用 DATA_ROOT、document_lock 和 atomic_write_json，保持 id／顺序；不涉及任务和供应商 |
| image_size_api.py／Gateway | 小型登录用户 CRUD 路由及装配；普通用户仅管理自己的预设，复用 Gateway 身份和同源保护 |

每个目标沿原 CanvasTaskQuery／持久任务／归档独立提交，成功项和失败项分别保留；Promise.allSettled 不引入并发闸门。当前面板只选共同能力明确支持自定义尺寸的普通 Seedream 5.5 编辑型号，排除图层别名。已选值在切换模型后若不兼容可取消，提交禁用并显示原能力校验结果。无新 Schema、运行依赖、队列或跨来源重试。

### 复杂服装真实结果与缺陷

固定输入沿用前批由贞贞 gpt-image-2 生成的 1024×1536 复杂服装海报，含双人遮挡、针织／蕾丝／毛呢、发丝、枝叶、文字／价格与细节卡片。四项经普通 reviewer 账号原 `/api/canvas-image-tasks` 提交，使用隔离加密凭据；没有调用生产账号素材。后台自动化复用原任务 ID 查询，不重投。

| 阶段／原任务 | 实际输出 | 结论 |
| --- | --- | --- |
| split-preserve／canvas_img_0b097d6609284662890f9123efbe38c8 | 底图加六个 RGBA 图层，Alpha 0–255；名称／顺序／位置完整归档 | 指定逐字保留后，“秋冬新品”标题在本样本完整；重组人物仍改变遮挡，MKT-01.D 未通过 |
| resize-square／canvas_img_d1fa2603c266458c83d8973fd31ac18c | 1200×1200 RGB | 初版提示生成了原图没有的装饰英文，保留为质量失败样本 |
| resize-wide／canvas_img_dbd3fbdd8dc4471b8bc6d82a6e059c10 | 1920×1080 RGB | 收紧固定文字约束后，主要原中文、价格、AUTUMN KNIT 及两处细节标题可见，没有新增装饰英文；为新构图，非加边或拉伸 |
| resize-square-strict／canvas_img_e09a46c007f44d8788364a8f917322f7 | 1200×1200 RGB | 使用最终提示，未再出现初版新增英文；主要文字／细节卡片保留 |

最终横图人物头顶靠近／部分触及边界，模型重绘的服装纹理与人物不保证像素等同；尚不能将两张结果推广为所有用途、品牌或即梦同等效果。拆层遮挡仍须分辨供应商生成与合成责任，未擅自改层序、覆盖普通文字或伪造 OCR 来掩盖原始问题。所有十张原始产物及初版缺陷保留。

### 原页面、权限、持久化与检查

审核仍从根首页进入“无限画布”。新建独立 **MKT-02 智能多尺寸 · 贞贞复杂服装验收**，ID `82ce153466ed47bfbb925e1cc57d932b`，当前九个节点含真实对照、原位连线、两项模拟成功及两项原权限失败。旧 MKT-01 画布已有负责人操作，本轮没有重置或用旧快照覆盖。

原页面已检查：多选／数量／空选禁用；无效 512 方图不能保存；新增 1280×1280、比例锁、重开、英文状态修改为 1440×1440；中文／英文、浅／深主题、键盘进入预设编辑；语言切换保留用户画布名。初次页面选择贞贞本机模拟渠道，当前管理员没有授权，原提交返回两次本地 403，未发上游请求；随后接原 source-preview，在生成前显示原因并禁用。没有通过新增授权绕过问题。另一现有 native 本机协议夹具从同一页面完成两个独立任务；夹具固定返回 640×480 色块，仅证明入口／任务接线，**不作为请求像素或模型效果证据**。真实像素与效果以上表为准。

Gateway 实际由 PID 62760 重启为 61664，上游应用 PID 34988 保持。本轮没有执行上游退出恢复，不重复计算前批的该项证据。重启后自定义预设保存仍在；普通账号可保存自己的尺寸，伪造 owner 无效、跨用户更新 404、跨 Origin 写入 403、普通用户供应商管理 403。四个原真实任务及十张图均 owner 200、其他账号 404、逐项内容相同；只读验证新增付费 POST 为 0。既有同步／异步和历史任务凭据规则未改。

本批后端及既有个人偏好 13 项、文档合同 17 项合计 30 项定向检查通过；新多尺寸与原图层分离／布局／文档／session／任务中心共六组 JS 功能检查通过。新 Node 夹具第一次缺 document，虽先打印成功仍退出失败；补齐测试环境后重跑通过，不把该次写作产品失败或首次通过。最终复验另捕获三个原页面的共享任务中心缓存号不一致，已统一为 `20261125.4` 并复验对应检查；其他新营销文件缓存仍为 `20261125.multisize-04`。三项 JS 语法和 git diff --check 通过，现有换行提示不作为业务失败。12 项运行文件与源码逐项字节一致，不新增哈希。现有文档检查核对 154 份文档、669 个本地链接无错误；没有新增独立文档或全仓回归。

### 费用、资料与交付状态

最终只读 usage=609.6148，原基点 32，兑换 1.35；按原口径 `(609.6148-32)/100×1.35 + 1.45 ≈ 9.2478` 元，期间最高参考约 10.1707 元。1.45 为此前方舟公开价格估算；贞贞累计读数发生结算调整，不将差额等同于四项的逐任务最终发票。累计授权 13 元，指定追加补验已完成，未继续消费余量。临时真实贞贞／方舟来源和平台均保持停用，加密原版本供历史任务读取，不回显密钥。

资料在 `D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/development/marketing-mkt02-20261125/`，含公开模块与来源索引、录屏帧、四任务／原回包／十张 PNG、重建图、两套请求、只读费用、权限／重启记录、原页面截图和运行文件映射。预览 `http://127.0.0.1:18000/` 保留；当前面板选择本机协议夹具，不会自动真实消费。源码仍基于 `d8210980d5c773ff91798cac20e8cfb5c14ee92b` 的本地候选，正式 11.3 仍为 `a5613dabb6307ceeae4d3bdfc67979b78363ccd7`。未建分支、提交、推送、建 PR、合并、发行或部署生产。负责人页面／效果认可与代码实现分开记录。

收益是一次选择多种营销用途、独立追踪结果和复用个人尺寸，减少反复配置、手动拉伸及误选参数；未测量实际节时比例或生产收益数字。下一工作仅在[唯一路线图 MKT-01.D／MKT-02.D 和 MKT-03–07](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md#marketing-node-batches)维护，不另建营销路线图。

<a id="mkt-01"></a>

## 2026-11-25 MKT-01 营销图层分离与复杂服装双渠道验收

### 授权、官网代码与实际范围

负责人批准继续实施，并要求今后的效果测试使用复杂服装图；无合适样本时用贞贞 gpt-image-2 生成。本轮源码仍为 `d8210980d5c773ff91798cac20e8cfb5c14ee92b` 加原候选及本批增量，发行基线沿用 11.3 的 `a5613dabb6307ceeae4d3bdfc67979b78363ccd7`。预览为原 `127.0.0.1:18000`，保持持久数据和用户既有编辑，没有准备／重置数据库。未提交、合并、正式发行或部署生产。

登录态页面确认 `main.11a4ab8465.js`、`canvas-core.444262369d.js` 等版本与已存公开资源一致。沿页面 runtime manifest 读取 `async-canvas-feature-runtime.2ba1970936.js`、`8774.e122134eb9.js` 及模块 40399；只分析，不将供应商整包复制执行。实际菜单有七项，图层入口为 `imagePostEdit.open({mode:"layer-decompose"})`。当前官网账号打开时进入会员引导，已退出，未购买／生成；无法直接现场核对的面板细节由相同版本代码与负责人录屏补足。

公开代码能确认：smart／selection／description 三模式，提取文字默认 false，描述最长 800 字，Enter 提交、Shift+Enter 换行；框选以原图坐标生成中文百分比说明，不裁切原图。面板宽 534、圆角 16、内边距 12。智能拆分前端提示词为空，服务端私有默认提示词未公开。方舟 API 允许分层不传提示词，现已接通；贞贞仍使用明确标识的语义分层说明，不冒称即梦服务端预设。官方依据为[图片生成 API](https://docs.volcengine.com/docs/ark/image-generation-api?lang=zh)；贞贞公开[分层文档](https://gpt-best.apifox.cn/api-522995149)仍是 flash 名称，不能替代本次 5.5 的实际验证。

### 模块与兼容改动

- `canvas-layer-separation.js`／CSS 负责独立营销菜单和拆分面板；原智能画布 adapter 负责任务、节点放置、连线、画布保存与结果导入。其余六项没有添加无效按钮。
- 原全屏编辑器复用该模块的模型列表和参数规则，不另维护供应商型号判断。新控件复用原主题、Lucide、中英文和输入习惯；英文窄行自动折行，避免提取文字与确认按钮重叠。
- 贞贞真实同步响应使用 `zindex`／`boundingBox`／`outputType`；原共同解析只识别下划线命名，导致元数据丢失。现由贞贞适配器统一，保留全部图片、名称、顺序和位置。共同图层文档继续使用底图坐标和 bbox 摆放尺寸，不用图片固有尺寸覆盖 bbox。
- 贞贞异步查询包装仅保留 URL，因此新 5.5 拆层改用同步结果；旧已受理任务仍按原 ID 查询，不改绑定或重新 POST。同步响应中断仍是 unknown，不自动重投。
- 贞贞实测 max_images=3 返回六张、text_recognition=true 未返回 OCR。当前维护契约为自动分层，前后端明确关闭这两项；旧编辑器保留不兼容值并提供用户主动重置，后端在付费提交前拒绝。不能静默截掉三张产物或伪造 OCR。方舟保留真实已验证／官方声明能力；新增公开布尔字段无数据库迁移。
- 方舟智能拆分可空提示词，由模型自动识别；普通生图仍拒绝空提示词。账号欠费 403 与权限、429 模型用量上限分别提示；保留原请求标识，无自动重试或充值。

### 真实复杂样本、缺陷与费用

固定样本为贞贞 GPT-image-2 生成的 1024×1536 服装海报：双人遮挡、绞花针织、蕾丝、人字纹毛呢、围巾、细发丝、皮包、枝叶、标题／价格及两个特写卡片。不是简单色块或白底瓶罐。新付费请求均经原 `/api/canvas-image-tasks`，每个阶段独立 request ID，失败／诊断记录不改写为成功，无自动重投。

| 阶段及原任务尾号 | 实际结果与用途 |
| --- | --- |
| GPT-image-2 `bc970985014841109d7065ac17026ce6` | 一张复杂服装样本，后续全部复用 |
| 方舟指定分层 `2809f9da3b4a48839e291e6ed3a7b633` | 底图加五层，前景均有 Alpha 0–255，保留 z_index／bbox；四行中英文 OCR、坐标、近似字体／颜色 |
| 贞贞异步 `e0d77187eff24561842709a1fe456b37` | 六张真实图片，但原任务查询仅有 URL；保留该失败验收证据 |
| 贞贞同步诊断 `84574cd048884a6ea9ca85865119772a`／`19646ee908ca49289e1354fa4c12492d` | 前次未收集原始回包，后一次在隔离进程捕获原响应，明确三项字段命名；捕获仅保存响应 JSON，不保存请求、鉴权头或密钥；临时捕获 launcher 已退出 |
| 贞贞修复后 `e0b7f9357abb458babadd3254edb0889` | 六张全部保留，z=0–5、五个 bbox 和名称正确归档；请求上限三张仍回六张、OCR 缺失，据此收窄维护能力 |
| 方舟自动分层 `8a6f68b0e98c4df891b26f574168747a` | HTTP 403，明确账号 overdue balance；无产物，不重试，自动识别的真实质量仍待账号恢复 |

原始图片与按真实位置重建均已检查。两渠道前景保留真实透明通道；方舟／修复后贞贞按 bbox 还原，已消除客户端把裁切图全幅铺满导致的严重错位。但模型返回的标题 PNG 缺“品”字；人物按返回层序叠放时改变原有遮挡。OCR 识别完整文字并不等于文字图片完整。故 **技术接线与元数据通过，业务保真／即梦同等效果未通过**，需要进一步对照自动识别、分层提示与原图保护策略，不用 UI 修饰掩盖。

贞贞 Key 的原账单基点 32、最终 471.7868，兑换 1.35，按原口径差额 `(471.7868-32)/100×1.35≈5.9371` 元，包含此前约 1.75 元。方舟之前 0.62 元、本轮一输入六输出估算 0.83 元，参考累计 **7.39 元**，仍在原 10 元内；方舟为公开价格估算，不是实付账单，欠费拒绝未取得结算证据。无更多付费调用；两个临时真实来源／平台均停用。没有生产密钥或账号付费设置变更。

### 原页面、普通账号、恢复与检查

从根首页“无限画布”进入同一审核画布，三模式／空描述／空框选、键盘框选移动、原图不裁切、模拟任务受理与三图归档通过；这次模拟只证明页面接线，真实效果仍由上表复杂样本判断。双渠道选择的层数／OCR 差异已在原页面核对。中文／英文、深／浅主题均检查，英文紧凑行修正后复验。通过本机真实鼠标从标题拖动节点、原位拖动男装图层、全屏拖动同一图层；记录节点和图层各自坐标变化，原位图层拖动未改变节点坐标，撤销／拖回恢复原位置。

原任务在应用／Gateway 重启、真实来源停用后仍可读；普通账号取得全部已归档图片，另一普通账号对任务／媒体拒绝。原画布重开保留真实层、用户新增 Logo／显隐／合并结果及连接，没有以测试数据覆盖用户编辑。既有简单模拟样本和旧原生画布继续保留用于协议／恢复验证，不外推为复杂业务效果。

162 项受影响 Python 检查通过，覆盖字段转换、同步选择、能力差异、原 main 归档／重开和旧协议；空提示词的原 main 接口／进程重开验证与后续 42 项适配检查通过。新增错误曾暴露 ValueError 的 JSON 序列化问题，改用既有 PydanticCustomError；欠费提示初次仍用 429 状态，已保留供应商 403 并复验。Node 四组功能检查及语法通过。现有文档合同 17 项通过；最终 `tools/check_docs.py` 核对 154 份受管文档、659 个本地链接，无错误。11 项本批预览运行文件与当前源码逐字节一致；最终缓存版本为 `20261125.marketing-03`，英文紧凑面板折行后不再与确认按钮重叠，恢复中文深色界面。31 张真实归档逐项读回一致，另一普通账号均被拒绝，普通用户修改平台被拒绝；这些检查没有新增付费 POST。不重跑无关全量回归，不将不同批次重叠用例相加。

资料继续存于同一外部根 `D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/development/marketing-mkt01-20261124/`：官网资源索引、真实任务／原回包、全部复杂图片、重建图、鼠标坐标、页面截图、运行文件映射与费用摘要。审核入口仍为 `http://127.0.0.1:18000/`，画布 ID `14a0e44ad8154c01adad4a31efdbf40c`；同一画布已有负责人操作，不重置。下一工作仅在唯一路线图 MKT-01.D 与 MKT-02–07 维护。源码实现、负责人效果认可、合并、正式发行和生产部署分别记录。

<a id="sup-04-s55-live"></a>

## 2026-11-24 SUP-04.S55 账号限制解除后的官方真实样本

负责人在关闭安心体验模式后要求恢复测试，沿用原 10 元总预算。此前失败回执保留，新建两个明确的原持久任务；无自动重试、跨 Key／来源重投或生产配置变更。使用前轮已保存的隔离机加密凭据和自行绘制的 DEMO 商品图，未使用客户素材。

| 原任务 | 请求与真实归档结果 | 完成归档耗时 |
| --- | --- | --- |
| `canvas_img_43541366a60e404285b837d6fa5004ab` | 普通编辑、1K、background=transparent；一张 1200×912 PNG／RGBA，Alpha 0–255，945736 像素完全透明、2944 像素半透明，商品标签保留 | 96.55 秒，单次样本非性能承诺 |
| `canvas_img_91575c6b78304f1a9bba192bbab73d4d` | 分层、1K、max_images=3／text_recognition=true、不传 background；底图及两个前景图层全部归档 | 170.13 秒，单次样本非性能承诺 |

分层底图为 RGB／1175×893，不需伪造透明背景。商品层为 RGBA／807×1300，Alpha 0–255、z_index=1、absolute `[607,78,1093,859]`；文字层为 RGBA／1657×633，Alpha 0–255、z_index=2、absolute `[0,0,803,307]`。normalized 位置同时保留。返回 PNG 的自身像素尺寸与其在底图上的摆放尺寸不同，不能直接用图片固有尺寸覆盖位置矩形。

实际 `static/js/canvas-layer-document.js` 的 `fromOutputs` 使用真实 `image_items`：画板为 1175×893，商品层恢复 `(607,78,486,781)`，文字层恢复 `(0,0,803,307)`，顺序 0／1／2。原 `textLayers` 正确产生两行 `DEMO - BOTANICAL CARE`、`PURE / DAILY`，保留行坐标、Calibri 近似字体及颜色。该验证复用现有函数，不新增前端替代实现；不等于原页面鼠标拖动／视觉已经现场验收。

两次调用均从原 Gateway 的 `/api/canvas-image-tasks` 受理，实际 raw_usage 分别记录 input_images=1、generated_images=1／3。全部四张原产物可读，另一普通账号对任务和媒体均拒绝；重复 request ID 回读原任务。测试结束停用临时真实平台和加密来源后再检查，两项任务及四张产物仍可读取，文件内容与检查副本逐字节一致，没有新生成请求。官方同步 request_id 仅保留诊断，未作异步任务查询。

按[官方公开价格](https://docs.volcengine.com/docs/ark/model-pricing?lang=zh)，两张输入为 0.10 元，四张输出均不超过 2.61M 像素，估算 0.52 元，合计 **0.62 元**；非实际结算账单。此前贞贞最终约 1.75 元的记录保留，总预算 10 元没有扩大。没有更多付费请求，真实来源已停用。

资料沿用同一外部目录 `sup-04-s55-dual-source-20261124/`：`native-live-resumed-verification.json`、`native-real-output-quality.json`、`native-real-final-archive.json` 及四张 `native-live-resumed-*.png`。上一轮 `native-live-verification.json` 的账号上限失败继续保留，没有覆盖成成功。产品业务代码本轮无新增修改；只补真实证据和文档。文档检查与既有文档合同按当前范围运行，不重跑无关全量回归。

**范围结论**：原生方舟 Seedream 5.5 的透明编辑、限量分层、Alpha／顺序／位置／英文 OCR 保存及既有图层文档导入，在本自制商品样本上通过。复杂服装／发丝主体、中文密集海报、大图和原页面视觉拖动仍按后续样本和 MKT-01 验收，不称为即梦全部营销功能已完成。源码、合并、发行及生产部署仍分开，本轮后三项均未执行。

<a id="sup-04-s55"></a>

## 2026-11-24 SUP-04.S55 Seedream 5.5 双渠道与方舟图片执行边界

### 批准、基线与依据

负责人后续明确要求 Seedream 5.5 支持方舟官方与贞贞，避免营销功能绑定单渠道，并提出方舟图片调用应从 main 解耦。本批只扩展该路径，其他供应商待定不阻碍。源码基线 `d8210980d5c773ff91798cac20e8cfb5c14ee92b`，正式 11.3 为 `a5613dabb6307ceeae4d3bdfc67979b78363ccd7`；本地原 Agent／图层／资产等未提交候选保留，没有把 HEAD 当作全部实现。改动前副本和清单在 `D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/development/sup-04-s55-dual-source-20261124/before/`。

采用[方舟图片生成 API](https://docs.volcengine.com/docs/ark/image-generation-api?lang=zh)、[Seedream 5.5](https://docs.volcengine.com/docs/ark/seedream-5-5?lang=zh)及[错误码](https://docs.volcengine.com/docs/ark/error-codes?lang=zh)的当前规则。普通生成支持 1K／1.5K／2K 或合法像素尺寸，总像素 921600–4624220、长短边比不超过 16；最多 10 参考图。分层仅一张原图、auto／分辨率档位、不得传 background；max_images 为含底图的 2–100 张上限，不保证固定图层数。普通透明输出与拆层是不同模式。

### 实现与依赖

| 模块 | 职责及兼容影响 |
| --- | --- |
| `seedream_capabilities.py` | 两渠道共用 5.5 能力与尺寸／参考数规则；普通生成与分层分别声明，不自动截参考图或改画幅 |
| `providers/volcengine_images.py` | 原生请求构造、执行及旧尺寸算法从 main 迁出；正常模型用 native ID，分层用 layer_decomposition 开关；SetLimitExceeded／AccountQuotaExceeded 提示账号处理，不误称稍后重试的流量限制 |
| `providers/zhenzhen.py` | 仍用两个准确渠道名；拆层别名不添加官方专属开关，删除分层 background，保留 PNG／watermark=False；普通 5.5 与官方共享模型规则 |
| `providers/suppliers.py`／能力公开层 | 仅两个已批准供应商的目录、配置预设和能力转接；无插件框架、业务数据库或凭据执行 |
| main 与原素材服务 | 原 facade 只装配端点／鉴权／授权参考图／HTTP client 和结果回调；普通与分层都准备提交副本。当时策略为最长边 1536、单文件 8 MiB、编码总量 32 MiB，不是官方硬限额；缩边／单文件默认值已由 [11 月 28 日原清晰度策略](#reference-quality-20261128)替代，32 MiB 请求预算保留 |
| 原凭据与任务服务 | 方舟复用原公司／部门加密来源和原版本绑定；不新增表、队列、限流或自动换来源重投。同步 request_id 仅诊断，不作可查询任务号；完成结果回读与中断待核对分开 |
| 原设置与共享前端 | 原平台类型增加方舟，复用后端预设、中英文和已有样式。智能画布原生引擎保留实际配置 ID，不再强制回固定 ID；原生 5.5 读取相同参数规则，不提供 4K／无效 quality 选择。分层模型选择读取能力而非只认贞贞名称 |

适配器没有 main／业务权限／数据库／Windows 生命周期反向依赖。服务器或容器可复用协议模块；当前凭据实现仍是 Windows DPAPI，跨系统密钥后端与数据存储部署尚未在本批实现。

### 本地验收及范围

固定 CPython 3.14.6 的开发运行时检查通过，应用无新增依赖；测试工具按现有锁文件安装到外部隔离资料目录。**225 个不同定向用例分批通过**，涉及双渠道构造、原 main 配置／任务路由、旧算法 18 组合对照、旧设置客户端、部门来源、原任务恢复、RGBA 与位置／OCR 元数据。第一次扩展检查有一项旧分层夹具要求 background=transparent，按官方规则修正并保留贞贞原 watermark=False，受影响最终 52 项复验通过；不将首次失败记录覆盖为一遍全绿。实际共享 model-picker／smart-canvas JS 被 Node 调用，新增原生配置 ID 与控件规则通过；既有参数选择脚本及语法检查也通过。

原持久隔离预览只同步 18 个受影响运行文件，用户平台配置／Key／数据库保留。通过真实 Gateway 登录、原 `/api/providers` 与 `/api/canvas-image-tasks`：

- 本机原生协议模拟完成普通透明一张、分层三张；归档保留 Alpha、顺序与 bbox，不把模拟色块当 AI 成品。
- 普通账号不能改供应商设置，另一普通账号不能读取任务／媒体；原生旧智能画布保存重开仍绑定相同配置 ID。
- 实际重启 Gateway／应用后读取原两任务四张产物，新增供应商 POST 为零；旧画布再次重开保持 ID。实际 main 的隔离进程测试还覆盖配置改动后的本地结果回读，无新增请求。
- 账号上限错误模拟经同一任务入口仅一次 POST 返回失败，提示模型暂停、错误码和原 request_id；没有 GET 伪续查或自动重投。

**浏览器／现场边界**：本轮内置浏览器接口返回 `Local browser access is unavailable for this chat`。未绕过接口控制用户浏览器；设置项点击、主题视觉及原页面按钮出图尚未新增现场验收。HTTP 原入口与实际 JS 函数测试不能替代这项验证。此前贞贞原页面证据复用，但不外推为方舟新增 UI 已验收。

### 真实方舟结果与费用

负责人提供凭据后，隐藏终端输入、现有 DPAPI 加密保存，只在隔离库原加密来源执行；源码、命令行、报告不回显密钥。GET `/api/v3/models` 为 200、55 个名称中包含 `doubao-seedream-5-5-261028`。从原持久任务入口唯一一次普通透明编辑使用自行绘制的 DEMO 商品图；返回 HTTP 429，说明账号对该模型达到设置用量上限、服务暂停，要求调整 Safe Experience Mode。该文案与官方 SetLimitExceeded 一致，不能据此认定参数被拒或项目人为限流。

原失败任务 `canvas_img_54eb3f7d0e204d2f9d5fe2d26be8999a` 保留，未自动重试、未提交分层，未生成产物。按[官方定价](https://docs.volcengine.com/docs/ark/model-pricing?lang=zh)预估的两输入／最多四输出上限约 1.02 元只是调用前预算，不是实际扣费；本轮未取得账单，不宣称实付为零。前轮贞贞最终约 1.75 元扣费记录仍保留在 10 元授权内。临时真实平台与来源均停用，原加密版本保留；无生产配置修改。

负责人在得知账号限制后选择“稍后处理，先汇报本地结果”。**真实透明与分层效果验收暂缓**，待负责人恢复账号模型服务；不自动改付费／额度设置。本地开发结果与此待验证项分别交付。

### 资料、状态与收益

资料根 `D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/development/sup-04-s55-dual-source-20261124/` 包含改动前副本、JUnit、原 HTTP 验证、实际重启记录、只读模型目录摘要及真实失败结果；加密凭据不作交付附件。审核入口 `http://127.0.0.1:18000/`，保留模拟方舟平台与旧智能画布供继续查看。公开前端资料分析另在 `marketing-layer-research-20261124/public-frontend/`，只匿名读取页面声明的资源，未将完整供应商 JS 复制执行到产品；登录态版本和实际营销 UI 仍待核对。

文档检查覆盖 154 份、646 个本地链接，0 错误；现有文档合同 17 项通过，JS 参数合同和两项语法检查通过。18 个预览运行文件逐字节与当前源码一致，未采用额外哈希流程。验证索引保留初始失败与最终受影响复验，不重复计算为更多已验收业务场景。

收益是共用准确参数规则，减少不支持参数被选中，保持企业并行、原任务身份及全部图层资产，营销功能可选择两个已接入来源。不能据此承诺供应商容量叠加、自动容灾、透明输出稳定性或即梦同等效果。下一步与七项营销路线见唯一路线图；本地实现、合并、正式发行及生产部署仍分别记录，本轮后面三项均未执行。

<a id="sup-03-z"></a>

## 2026-11-24 SUP-03.Z 贞贞固定供应商入口与阶段收口

### 本轮授权和范围

负责人最新三项批注明确：当前只做好贞贞；其他供应商接入待定，不阻碍推进；测试无阻塞后收口并汇报。按同一 SUP-03 登记子编号 Z，沿用原 16 个生产名称和图层拆分能力，不启动其他供应商适配／通用插件框架。源码为 `d8210980d5c773ff91798cac20e8cfb5c14ee92b` 加原候选和本批增量；本轮前源码、文档及后续 UI 样式原件均保存到外部资料，不覆盖既有 Agent／图层／资产修复。

### 实现与模块边界

| 模块 | 本批变化与兼容边界 |
| --- | --- |
| `providers/zhenzhen.py` | 原独立能力／提交／续查模块增加公开 `provider_preset`、显式保存用 `configure_provider`；维护 16 个生产名称加图层拆分共 17 项默认选择。供应商识别支持明确标签、旧 ID／主机和企业代理，不读业务数据库或密钥 |
| main 配置 API | 原配置新增可选 `supplier`；`/api/providers` 返回预设，保存时装配供应商配置，旧设置客户端缺字段时保留原值。读取旧配置只识别标签，原任务恢复不调用配置重写；不改 Schema、归档或来源权限 |
| 原 API 设置 | 新增“平台类型 → 贞贞平台”，地址／型号从后端读取。显式选择时带入原生协议，隐藏单模型错误协议覆盖入口；保存由后端同样使用原生配置。原 ID、已有型号、Key 与部门来源不重建，Key 不完整回显；首次空模型列表带入预设，后续可获取并选择型号 |
| 原样式与语言 | 使用原表单颜色／尺寸、`StudioI18n` 和公共 `studio-select`；补齐新增控件中英文及相关缓存键。首次截图发现窄白色原生 select，已按原输入框修整为满宽，浅／深主题复验 |

`supplier` 表示使用哪一供应商适配，不代替平台实例 ID 或部门来源。保存所选贞贞时协议为原生 OpenAI 兼容形式，具体图片的 JSON／multipart／同步／异步仍由已有准确型号规则负责；不将一个请求格式套给所有型号。`model_protocols` 冲突覆盖在显式保存该供应商时清空。后台三个 Key 仍使用原加密版本和事务冻结，网络执行没有新增并发／RPM 门槛。

### 供应商依据和真实验证范围

本轮通过 GitHub 只读核对，`T8mars/T8-penguin-canvas` main 仍为 `6181ef59a1cad449db7466185020711910624c75`。复用前轮固定源码中的工坊渠道、`models.ts` 和 `proxy.js` 参数依据；不执行该仓库程序，也不把平价小屋／其他域名模型混入工坊规则。17 名称中 10 个能在所缓存两文件直接找到字面名称，其他名称沿用先前生产别名／分层接口依据与本项目已维护合同；不声称客户端两个文件逐字列齐全部型号。

用隔离库原加密凭据只读 GET `https://ai.t8star.org/v1/models`，HTTP 200，目录含 919 个名称，17 项预设均出现；没有 POST、费用或来源启用。目录出现只证明当前 Key 可见此名称，不等于 919／17 个模型的全部生成组合和账号额度都已真实验收。

沿用此前五个常用模型及 8 次付费生成的有效证据，最终扣费增量约 1.75 元、最高期间读数约 2.23 元，均在原 10 元预算内。本轮新增付费生成 0。透明参数与存储链路：既有同步／异步两项原生 PNG 为 RGBA、Alpha 0–255，本轮原归档链再次保留该通道；先前一项原供应商 PNG 就是 RGB，与归档字节相同，保留为上游输出质量例外，不伪造 Alpha、不宣称每次透明效果必然成功。

真实凭据目前仅一枚，无法据此实测多个账号／Key／分组独立额度能否相加。三 Key 新任务分配、并行接线、原版本续查是本批开发验收；独立额度属于供应商账号／部署配置事实，不再列为等待其他供应商才能完成的代码任务。

### 定向与原页面验收

- **207 项 Python 检查分批通过**：147 项设置、准确请求、模型路由和能力目录；60 项凭据、实际 main 重启、结果归档、恢复及已有视频适配。第一批新夹具的目录参数／子进程输出编码、第二批子进程未接入外部 pytest 测试目录的问题已在测试装配中修正，失败项分别复验通过；没有为此修改应用运行时或加测试依赖。不是一次全量回归。三组既有 JS 合同（参数选择、部门凭据 UI、资产整理）通过。
- **API 设置原页面**：管理员从首页原入口新增贞贞，得到 17 项预设，保留原 ID，改为本机代理后保存／重开正确；已保存 Key 输入留空，完整 Key 不回显。原“获取模型”路径将受控图片、`MiniMax-H3` 视频与 `gpt-5.1` 对话正确分类；普通账号 `/api/providers` 被拒绝。新增文案中英文、满宽选择框及浅／深主题／共享下拉交互通过。
- **三 Key 与实际重启**：原管理后台为该新平台创建部门来源和三行模拟 Key，授权普通用户。经典画布三个任务在结果放行前均获得上游 ID，slot 0／1／2；随后反转当前 Key 顺序，重启隔离 Gateway／应用，三任务仍使用原版本对应 Key 的 GET 取回原任务，归档三项，生成 POST 增量 0。其他用户无来源／任务／媒体访问权。
- **其他原入口与透明参数**：智能画布和在线生图各一项归档；GPT Image2.5 的同步提交规则保持，无 async。另经原 Gateway 图片任务入口提交透明参数，传入 `background=transparent`／PNG，归档结果 RGBA、Alpha 0–255，重复 request ID 回读原任务。合计六项模拟产物均保留 Alpha，旧经典画布重开及跨账号拒绝通过，页面脚本错误 0。模拟色块不作为模型视觉质量证明。

页面准备曾因折叠侧栏的隐藏文本、夹具未填 prompt 和启动尚未就绪而失败；改为原按钮／真实输入并确认 GET 200 后复验。共享菜单的 native option 与按钮 role 重名已收窄测试定位。这些记录属于测试装配，产品实际发现的新增 select 样式不一致另行修复并截图复验。

### 收口、审核与后续

本地开发验收已收口，其他供应商待定不阻塞。原 API／模型参数、素材、任务身份与恢复、权限和归档边界继续原模块；没有新增限流、第三方依赖、数据库迁移或自动换 Key 重投。源码提交、正式发行和生产部署仍待原本地审核后的对应授权，未执行 commit／新分支／push／PR 或生产操作。

资料目录：`D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/development/provider-zhenzhen-sup03-z-20261124/`，包含本轮前源码、JUnit 及失败项复验、只读供应商目录摘要、固定源码比对、原设置／三 Key／重启／透明归档记录及双语言主题截图。审核入口 `http://127.0.0.1:18000/`，管理员在 API 设置选择“SUP-ZZ 贞贞平台审核（本机模拟）”；普通用户可从画布列表进入“SUP-ZZ 审核”。真实来源保持停用，新建贞贞选择仅预填官方地址，不自动填入真实 Key。

下一开发主线恢复原图层编辑节点需求，再按依赖推进 Agent 可恢复运行、营销功能与服务器／客户端适配。新增贞贞型号按同一模块增量维护，其他供应商接入保持待定；完整顺序只在唯一路线图维护。

<a id="sup-03-3-responses"></a>

## 2026-11-24 SUP-03.3.R Responses 图片原任务恢复与协议抽离

本轮属于已批准 SUP-03，开始前保存本轮源码／文档副本与清单。只读核对远端 main 与本地 HEAD 同为 `d8210980d5c773ff91798cac20e8cfb5c14ee92b`；未提交的 Agent／图层／资产／供应商候选保留。当前生产依据为负责人此前提供的 16 个贞贞模型及前轮真实样本，未读取生产实时配置；没有证据说明生产正在使用 APIMart、Responses 或图像视频代理。APIMart 和图像视频代理未选编码分支保持原实现，不因目录存在扩大重构。

### 缺口、修复与职责

原 Responses 后台 POST 取得原生 `id` 后直接在内存中 GET 轮询，受理记录未在首次查询前保存；进程退出后无法凭已知 ID 可靠续查。迁出该路径时一并修复，符合 SUP-03.C 的原任务恢复边界，不是新增供应商产品。

| 模块 | 本轮职责与兼容影响 |
| --- | --- |
| `providers/responses_images.py` | 迁出既有请求体、RS 画幅提示、后台／SSE／直接返回、响应包装和解析辅助。只依赖标准库、HTTPX；原明确拒绝后的形式切换和 SSE 分片兼容保留，不新增 5xx／未知受理后重投 |
| main | 保留旧包装与供应商／能力／素材装配；后台传入可选受理回调，调用原回执后再查询。查询按 Responses 后台状态区分处理中、完成、失败与待核对 |
| `canvas_image_recovery.py` | 原 `ImageReceiptSink` 保存 ID 和原查询地址，恢复时向原查询函数传入可选地址；原 provider scope、当前用户权限与原凭据版本规则保留 |
| `canvas_task_journal.py` | 对新增私有 `query_endpoint` 沿用原 ID 的不可变合并规则，仍存原 JSON 回执；无 Schema 迁移，无前端敏感投影 |

无新字段的旧回执及旧回调不接收新增参数，仍按原规则续查。当前生成 endpoint 改变不覆盖已保存的原 GET 地址。后台处理中回包即使含预览，也不作为成品归档；完成时复用原全部产物保存。通用 Responses 仍从原任务中心手动续查，没有扩大自动查询名单。原 SSE 分片兼容未在此改变，不把本轮后台预览规则外推为所有流式结果政策。

### 实际验证及限制

1. **前后请求对照 10 组一致**：实际旧 main 函数与新独立模块覆盖同步、后台、SSE、直接返回、503、响应丢失、流中断、未知 HTML、后台失败和既有分片返回。端点／字段／请求次数及输出语义可比较；不含真实网络调用。原 ID 特殊字符编码和先持久化再 GET 属新增修复，由独立用例覆盖。
2. **203 项定向检查分批通过**：138 项参数／独立协议／受理回调／恢复测试；另一组 65 项中先有 64 项通过，新硬退出用例因夹具缺 `static`／`workflows` 目录失败，补齐夹具后该项复验通过。不是一次 203 项全绿命令或全量回归。该新用例在实际 main 写入原 ID／地址／request ID 后 `os._exit(37)`，重启且改变当前 endpoint，仍 GET 原地址；先取得处理中预览不归档，再完成并归档两张 20×16 RGBA，重复核对不重新 POST／GET。
3. **原页面 9 项模拟任务**：Gateway 首页进入经典画布、智能画布、在线生图，三种返回形式各覆盖三处入口。后台一 POST；SSE／直接返回按既有明确拒绝分别为二／三 POST，没有额外业务重投。每项归档一个结果，重复平台 request ID 只回读；两类旧画布保存重开、他人画布／任务／媒体访问拒绝通过，页面脚本错误 0。使用自制色块与纯文本提示，不对外发送素材；参考图字段／顺序由离线合同覆盖，不声称真实图生图效果。
4. **实际隔离进程重启**：原在线任务得到后台 ID 后保持处理中，仅重启本机 Gateway／应用，并将当前生成 endpoint 从 `/custom/responses` 改为 `/changed/responses`。原任务中心“继续查询原任务”仍查询 `/custom/responses/{原ID}`；首次处理中预览未归档，再释放模拟任务后两张成品均归档，普通用户隔离通过，新增生成 POST 0。该记录为既有手动续查，不冒充自动恢复或生产中断演练。

应用及测试使用固定 CPython 3.14.6；原页面复用已有 Python 3.11／Edge 浏览器夹具，不新增应用依赖。最后一次硬退出用例复验结果为 1 passed，记录在 `responses-recovery-final.xml`。实际主机与预览映射分别保存，不将模拟供应商或本机 loopback 归档推断为真实渠道容量。

资料目录：`D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/development/provider-compatibility-sup03-3-20261124/`。包括本轮前源码、10 组请求对照、JUnit、原页面任务记录、强制退出和重启后原路径／全产物验证截图。审核入口为 `http://127.0.0.1:18000/`；画布列表选择“SUP-03.3 审核”开头的经典／智能入口，原在线生图可选“Responses 协议模拟（本机）”，色块用于接线验收。本轮付费生成 0，真实测试渠道保持停用，未操作正式生产；没有 commit／分支／push／PR、正式发行或部署。

当前范围本地完成；下一步按唯一路线图 SUP-03.A–D 联合审核已选图片路径和交付清单，复用现有证据。真实透明效果、多个 Key 的独立容量、其他供应商实际路径、图层／Agent 与服务器适配分别保留自身验收范围。

<a id="sup-03-2"></a>

## 2026-11-23 SUP-03.2 通用图片请求编码与素材作用域

本轮沿用已批准的 SUP-03 图片执行抽离，工作编号 SUP-03.2。只读 GitHub 核对 main 与本地 HEAD 同为 `d8210980d5c773ff91798cac20e8cfb5c14ee92b`，保留工作树原有 Agent／图层／供应商候选；正式 11.3 的发行与现场记录沿用原证据，没有本轮发布或生产操作。开发运行时 CPython 3.14.6／固定包检查通过。开始前将原文件副本与差异清单存入外部测试资料，不创建第二份路线图。

### 实现边界与业务收益

| 模块 | 本轮职责及兼容边界 |
| --- | --- |
| `providers/openai_images.py` | 标准 Generations JSON、Edits multipart／无文件 form、Agnes `extra_body` JSON；既有明确拒绝策略。只接端点、鉴权头、参数和素材作用域，无 main／数据库／权限／凭据依赖 |
| `image_reference_preparation.py` | 复用准备副本；旧调用使用授权路径解析回调装配原 image／mask 文件，作用域在编辑 POST 后即释放，异常同样关闭；不跨入供应商协议判断 |
| `main.generate_ai_image` | 保留原签名和 API，选择供应商／模式、验证能力、装配身份／素材和 `image_execution` 结果回调；本轮从 234 行减为 155 行 |
| 原任务／归档服务 | 保留冻结身份、持久回执、部分结果、原任务查询和媒体归属，不重建任务表、队列或归档器 |

这使同协议图片接入可直接复用编码与错误边界，后续模型参数变动不必反复改大型 HTTP 入口。原权限和资源服务继续负责授权，协议模块可独立验证且不依赖 Windows 生命周期，便于后续服务器接线；本批不是服务器／容器交付。未改变 API 正常并行或部门多 Key 分配，没有数据库迁移或新应用依赖。

兼容策略原样保留：只有现有 400／404／405／415／422 加明确 unsupported Images 文本，才允许原协议支持的端点切换；GPT2、比例式编辑或已启用异步端点仍按原规则停止切换。401、429、5xx、解析失败、断线及受理未知不增加生成 POST。该规则是迁移已有行为，不是新增供应商探测或自动重试。

### 验证与未覆盖范围

1. **离线请求前后对照**：外部脚本分别执行本轮前后真实 main 函数的 13 组场景，规范化 multipart boundary 后，端点、字段、文件字节／顺序、错误类别和请求次数一致；每侧 14 个 MockTransport POST。覆盖普通／GPT2 文生图、比例式、Agnes JSON、参考图、mask、明确拒绝、5xx 和响应丢失。对照脚本初次直接比较 Python tuple 与 JSON list，造成假差异，改为统一记录格式后一致，未因此修改产品语义。
2. **定向测试**：175 项通过，构成为 97 参数、18 独立 OpenAI 编码／提交策略、10 素材、6 共同执行、44 实际 main 恢复／结果／止损。新用例覆盖文件在编辑 POST 后关闭、惰性转换只发生在明确拒绝后、Alpha／mask 顺序及模块无业务依赖；不是全量回归。
3. **原页面模拟**：使用已有 Edge／Playwright 夹具，通过 Gateway 根首页进入经典、智能和在线生图。标准与 Agnes 风格两协议各三项，6 项均归档；每项一个模拟提交，重复 request ID 仅回读。两类画布保存重开保持参数，普通用户读取他人任务／媒体／画布被拒绝，JSON 参考图 Alpha 保留，页面脚本错误 0。CLI 已核对登录入口；Browser 插件不可用，复用现有 Python 3.11 浏览器夹具，不改变应用的 3.14 运行时。
4. **受理后重启**：一项通用协议任务得到原供应商 ID 后，重启仅本机隔离 Gateway／应用；原 ID 保持，从原在线任务中心“继续查询原任务”归档一项，供应商生成 POST 增量 0。通用供应商既有策略为手动续查，首轮脚本误等自动恢复，随后改为实际页面入口；未放宽自动续查范围。原6项本轮结果及此前6项真实结果仍可读取。

隔离预览的组合同步／重启命令曾被自动策略拒绝，未执行；核验准确进程身份后分步同步和重启成功。首次恢复脚本在端口就绪前登录失败，确认登录 GET 200 后复验。上述测试准备问题与产品通过证据分开。正式生产地址、真实供应商 Key 和配置未操作；本轮真实付费调用 0，前轮临时真实渠道仍停用。

资料目录：`D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/development/provider-compatibility-sup03-2-20261123/`，包含前后源码、请求对照、JUnit、六条原页面记录、重启回读与截图。审核仍使用 `http://127.0.0.1:18000/`，新增 JSON 模拟来源仅指向 `127.0.0.1:13002`；画布列表有“SUP-03.2 审核”开头的标准／JSON 协议、经典／智能四个入口。16 项累计预览运行文件与当前源码逐字节一致，现有文档检查 154 份无错误、文档合同 17 项通过，Git diff 检查无空白错误。SUP-03.2 本地完成；APIMart、Responses 图像工具及图像视频代理编码仍在 main，后续 SUP-03.3 先按实际使用核对范围。合并、正式包和生产部署待负责人按既定先审核要求分别批准。

<a id="asset-1123-and-supplier-followup"></a>

## 2026-11-23 ASSET-1123 与已批准供应商后续实施

本轮范围按[唯一路线图](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md#provider-compatibility-batches)登记为 ASSET-1123、SUP-02.E 和 SUP-03.1，并补 SUP-01.D 的常用模型真实参数样本。负责人明确批准同渠道多个 Key 的简单录入／首跳分配、图片执行抽离，以及总费用 10 元以内真实测试；不新增 API 限流。以下同日“待沟通”内容保留此前时点，本段更新后续授权和实施状态。

### ASSET-1123 已实现的修复与验证

根因是 shelf 收集素材时直接调用 `root.crypto.randomUUID()`；HTTP loopback 可被浏览器视为可信，普通 LAN HTTP 未提供此 secure-context API。改用原 `CanvasTaskQuery.requestId()` 的 `getRandomValues` 实现，不在全局伪造 crypto。原卡片新增删除／再点击确认，调用现有本人条目 DELETE，使用 `keep_file=true` 保留文件，以免删除库内记录时损坏画布已复用的库文件。当前仅清理库内记录，不代表磁盘回收。

原 `canvas-asset-shelf` JS 合同和 7 项 Python 资产／权限测试通过。使用现有 Edge／Python 3.11 Playwright（Browser 插件不可用），从根首页进入经典／智能画布，在 loopback 和 `asset-lan.test` 两种 origin 共四条流程执行拖入、插回画布、两次点击删除、整页刷新和另一普通账号拒绝。`.test` 通过 Chromium host-resolver 只解析到本机 127.0.0.1，没有代理到生产；浏览器实测 `isSecureContext=false`、`typeof crypto.randomUUID='undefined'`、`getRandomValues='function'`。四条流程通过，页面脚本错误 0；原图与已插入库副本可读。测试准备／重复标题、根页刷新回列表和错误转发 header 的脚本问题已修正，失败演练不是产品通过证据。

### SUP-02.E 与 SUP-03.1 本地范围

`credential_pool.py` 在原加密版本内保存多个 Key；原渠道管理表单按行录入，列表只显示数量并复用中文／英文后台词汇。原部门来源、授权、版本、任务归属和 DPAPI 沿用。每个新平台任务在短事务内读取同版本最后一条不可变快照并冻结下一 slot，同任务多图子调用沿用该 slot；没有每次统计全段历史、网络并发门槛、RPM 或第二套队列。旧单 Key、重复 request ID、并行绑定、重开服务、换 Key 后原任务查询和跨部门拒绝的凭据／权限定向测试共 33 项通过。

原后台创建三个模拟 Key 并授权普通账号，从经典画布一次发起三个任务，完成前全部获得上游 ID，slot 为 0／1／2。更换整个 Key 集合后重启隔离 Gateway／上游，三个原 ID、原 revision 保持，续查并归档三项，新增生成 POST 为零。随后智能画布和在线生图各成功归档一项，新任务绑定新 revision；跨账号任务／媒体访问拒绝。最终源码同步后再用两处入口做冒烟，轮换延续正确、脚本错误 0。模拟证明本地分配与恢复接线，不证明供应商为多个 Key 提供独立额度；没有真实多 Key 容量测试。

`providers/image_execution.py` 只负责共同结果确认、异步持久受理及原任务轮询；供应商执行入口在 `zhenzhen.py`，通用模块没有贞贞依赖。main 的旧函数签名保留，其他请求编码分支仍在 main；模型能力、素材授权、任务数据库和结果归档不进入该模块。最终参数、独立执行、实际 main 恢复／止损／产物及凭据用例合计 172 项通过；后续调整轮换查询后，33 项凭据／权限单独复验通过。迁移时原 AST 合同用例需补入新执行模块依赖，初次测试的 38 个 NameError 属测试装配未更新；补接后通过。对特殊自定义同步／异步端点，按实际响应 request URL 判断异步契约，保留此前行为。

<a id="sup-01-e"></a>

### SUP-01.E 供应商客户端源码交叉核对

负责人提供 `T8mars/T8-penguin-canvas` 作为减少付费试错的依据，固定核对提交 `6181ef59a1cad449db7466185020711910624c75`，不执行其仓库脚本、不增加项目依赖。源码存于本批测试资料的 `supplier-reference/`，后续更新通过准确提交比对，不把动态 main 页面当不变契约。

| 源码依据 | 核对结论及本项目处理 |
| --- | --- |
| [渠道定义](https://github.com/T8mars/T8-penguin-canvas/blob/6181ef59a1cad449db7466185020711910624c75/src/stores/apiKeys.ts#L6) | 工坊 `ai.t8star.org` 与平价小屋 `api.seedance.nz` 分开，不能混用相似型号的参数 |
| [GPT Image2.5 校验](https://github.com/T8mars/T8-penguin-canvas/blob/6181ef59a1cad449db7466185020711910624c75/backend/src/routes/proxy.js#L1534) | 最多 14 参考图，实际像素尺寸而非 auto；倍数 16、最长边 3840、长短边比不超过 3，总像素 655360–8294400。原像素组合规则已一致，本轮补 auto 和参考图上限 |
| [GPT Image2.5 提交](https://github.com/T8mars/T8-penguin-canvas/blob/6181ef59a1cad449db7466185020711910624c75/backend/src/routes/proxy.js#L3132) | 无参考图同步 JSON Generations，有参考图同步 multipart Edits，不附 async；修正本地 flare／sunburst 两款生产名称的新提交，保留原任务续查 |
| [模型目录](https://github.com/T8mars/T8-penguin-canvas/blob/6181ef59a1cad449db7466185020711910624c75/src/providers/models.ts) | 型号、页面可选项和请求字段可交叉核对；客户端保留的少量参考图等页面策略不直接登记为供应商硬上限。未确认的 GPT2.6 工坊契约、Seedream 自定义尺寸与容量保持待核实 |

新增 8 个请求用例覆盖两型号的非法 auto、0／14／15 参考图及已有持久回执场景，和原参数／独立执行测试合计 103 项通过。公共参数组件读取同一能力，JS 检查确认 auto 不可选择；GPT2.6 原异步路径不受此两型号新规则影响。没有为此新增付费请求，源码交叉核对不取代真实效果验收。

原页面复验发现智能画布 `sanitizeSmartApiSelection` 和 `normalizeApiSizeSettings` 会把显式 auto 改为 GPT 默认 4K，导致旧值被静默替换并出现另一种尺寸错误。两处改为仅在未保存分辨率时补默认值，显式旧值由共同能力规则提示修正；新节点原默认规则不变。实际函数的 Node 回归覆盖 auto 保留、人工选 1K 及缺值默认，智能画布 HTML 同步脚本缓存键。初次页面脚本的 JSONL 分行与模态框关闭步骤错误单独修正，不将其失败写成产品通过证据。

最终 Edge 原入口验收通过：经典／智能画布和在线生图对两款型号共六次选择，auto 不作为可用选项；两类旧画布保留 auto 并明确提示，点击生成没有创建平台任务或供应商 POST。人工修正后共完成三项本机模拟生成：经典／智能各一次同步 multipart Edits，在线一次同步 JSON Generations，无 async 查询参数；每项仅一个供应商提交，归档可读、重复 request ID 回读不新增提交，另一普通账号任务／媒体读取拒绝。两类画布修正保存后重开保持 1K，六项此前真实任务仍可读取。页面脚本错误 0；脚本已等待编辑器节点就绪后再操作视口工具，避免在 JS 初始化前点击。该源码修正新增付费调用 0。

本轮现存定向证据合计 187 个不同 Python 检查项（97 参数＋6 执行＋44 恢复／结果／止损＋33 凭据／权限＋7 资产），JS 原合同和文档检查另外登记；44 项在此次模型修正后复验。文档检查覆盖 154 份，文档合同 17 项通过。不是全量回归或生产现场验收。SUP-01.E 本地收口，下一实施编号 SUP-03.2 尚未在本批启动。

### 真实调用与交付分界

预算 10 元以内，测试 Key 仅在本机隔离预览中加密暂存，使用自行绘制的 QA 商品参考图；没有将生产用户素材、生产任务或生产配置迁入测试。以下五个常用型号经原在线入口各完成一项真实任务并归档，重用原 request ID 没有重新生成。

| 模型 | 请求字段／预设 | 实际产物 |
| --- | --- | --- |
| seedream-v5.5 | 1536×1536，1.5K，单参考图 | PNG，1536×1536 |
| gemini-nano-banana-2.1 | 16:9、2K，单参考图；使用命名参数 | PNG，2752×1536 |
| nano-banana-pro-2k | 固定 2K、3:4，单参考图 | PNG，1792×2400 |
| seedream-v5-pro | 1536×1024 维护预设，单参考图 | PNG，1536×1024 |
| gpt-image-2 | 1024×1024，单参考图 | PNG，1024×1024 |

另从原 Gateway 提交一次 Seedream 5.5 `background=transparent` 测试，产物归档成功，但供应商原图为 RGB PNG，Alpha 为全不透明；项目保存字节与原图完全一致。为区分参数／异步能力，另做一项同步和一项异步直连协议对照，两者请求字段一致、明确传 `background=transparent`／`output_format=png`，均获得 RGBA、Alpha 范围 0–255。共 8 次明确的新生成（6 个原 Gateway 任务＋2 个对照），没有 unknown 重投。不能据首次结果认定异步不支持透明，也不能将透明效果标成全部稳定通过；保留未达标样本和原任务 ID，后续按实际提示词／参考图组合补稳定性验收，不伪造 Alpha。

原页面 5 个模型的 6 项产物已归档，2 个协议对照仅保存在测试资料中。本轮真实样本未覆盖另外 11 个生产名称、全部参数组合、大参考图、多 Key 或多人并发。临时付费渠道与来源已在隔离预览停用，原加密版本仍可供已受理任务续查；没有停用供应商 Key。费用按原 Key 的 billing/usage 变化与平台公开兑换系数核对，最终数值见同目录 `budget-final.json`，不从模拟测试推算产能或费用。

验证资料位于 `D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/development/asset-1123-and-provider-followup-20261123/`。本轮未 commit、建分支、push、开 PR、合并、发行或操作生产；公开 11.3 不含这些本地修复。现场安装包和生产入口仍待后续分别审批与验收。

<a id="sup-02-no-throttle"></a>

## 2026-11-23 SUP-02 更正：撤销 API 限流，按部门容量扩展讨论

负责人否决将所有用户 API 节点按同供应商主机、提交 2／在途 2／每人 1 限制。该产品决策优先于此前路线图和本地试验，撤销相关调度器、配置面板和接口，不用无限大阈值、默认关闭或独立 Key 名义保留同类门槛。正常 API 多图和多人请求继续原并行执行；ComfyUI 原算力队列不属于本次否决范围。

### 当前实现与验证边界

撤回 `provider_image_queue.py`、`provider_image_queue_api.py`、专为其抽离的 `queue_gateway.py`、后台图片队列脚本及专用调度用例。dispatch、回执、Gateway、Comfy 队列接口和管理页面按本轮前的副本恢复，仅保留独立素材准备摘要的原 journal／任务详情接线。没有恢复整个工作树，原 Agent、图层、SUP-01 及用户其他改动保留。

`image_reference_preparation.py` 继续在原授权链路内准备引用副本；不进入并发准入，不改变调用来源。JSON／multipart 仍保留参数契约、原件和 Alpha。在线上传等待与失败提示、同文件重选和旧智能画布工具条定位保留。断线与不明受理继续按原 ID 续查，不自动换 Key／供应商再提交。此前排队报告与较低峰值不是当前方案的验收证据。

撤限后的 83 项定向测试通过（恢复、派发、素材、本人任务及原 Comfy 队列），6 项既有警告保留。实际 main 的受控屏障通过：两个平台请求各 8 张图，16 个生成 POST 全部到达后才释放任何回包，随后归档 16 个结果；原 request_id 回读没有新增 POST。另一个临时 URL 过期场景明确返回原供应商错误、不自动再提交。应用为 CPython 3.14.6 和固定应用依赖。

已有 Edge／Playwright 从根首页进入经典／智能画布，两个普通账号各提交 4／3 项，7 项均在任何结果完成前获得原供应商 ID，随后归档 7 项；另一账号读取任务／结果被拒绝。素材摘要及原件／Alpha 保留，页面脚本错误 0。原管理后台的 Comfy 设置可正常加载，`imageQueuePanel`、其脚本和 API 图片管理接口移除。测试使用本机回环假供应商，真实付费调用 0，不能据此认定真实账号可达相同或无限产能。文档检查 154 份、0 错误，文档契约 17 项通过，JS 检查与任务中心原用例通过。

该更正的 `browser-verification.json`、`preview-mapping.json` 和 `verification-summary.json` 保存在本小节末尾的资料目录，预览 15 个运行文件与当前源码按字节一致，4 个撤回的运行模块已从隔离副本移除。没有改动生产数据或密钥，旧试验策略文件保留为本地资料且不再被任何运行接线读取。

### 多密钥／多供应商的沟通方案（尚未实施分流）

| 步骤 | 复用与拟增内容 | 需要确认的事实 |
| --- | --- | --- |
| 核实上游容量 | 用现有错误、原 request／task ID 和供应商合同或账号设置分别核对，不从错误峰值倒推硬上限 | 限制按 Key、账号、分组或模型生效；异步在途与 POST/RPM 是否分别计数；高并发是否需账号扩容或 IP 白名单 |
| 部门接入 | 复用 `DepartmentGovernance` 的来源、部门授权、加密凭据版本及 `task_credentials` 绑定；登记部门可用的供应商／账号／Key | 哪些部门、优先模型、目标并行规模；哪些 Key 确认有独立额度；素材是否允许发往新增供应商 |
| 新任务分配 | 在首个生成提交前，从该部门已批准来源选定一个来源并冻结到原任务；后续才按选定的固定映射或负载分配实现 | 是否只用贞贞独立额度，还是同时接入其他供应商；价格、参数、质量及参考图约束分别验收 |
| 联合验收 | 检查各来源实际流量、成功率和耗时、部门越权拒绝、Key 轮换及原任务续查 | 给定样本、渠道、并行目标和费用预算，按测得结果决定扩容；不宣称多建 Key 必然提升容量 |

当前 `accept_context` 选择一个授权来源，不按负载轮换；`prepare_task_binding` 对来源绑定执行仍限定已验证贞贞 HTTP 协议。已有基础不等于多来源分流已经交付，新供应商需要其模型能力与协议适配。一个已发送或是否受理不明的请求仍绑定原来源，不能为了扩容把它自动重投另一个 Key；这与正常新任务的大量并行分别处理。

本轮仅做本地撤限和兼容修复；没有生产操作、付费调用或 GitHub 写入。待沟通的是部门／供应商容量配置与分配规则，原因是影响账号采购、素材外发、模型效果和费用。实现、提交、正式包、生产部署继续分别记录。源码及验证资料保存在 `D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/development/provider-compatibility-sup02-20261123-no-throttle/`，上一试验副本留在原资料目录。

<a id="sup-02"></a>

## 2026-11-23 SUP-02 低并发方案的历史演练（已撤回）

> 负责人随后明确否决 API 限流。以下队列、默认低限额、名额释放及排队演练仅保留为历史记录，代码和面板已撤除，不能描述为当前功能或产能验收。当前实现以本文件上方“撤销 API 限流”小节为准。

本轮按负责人继续落地指令实施 SUP-02，并收口 SUP-01 的工具条定位余项。没有提交 GitHub、建分支／PR、生成正式包或修改生产设备。原图层和 Agent 的其他候选保留，没有扩大为全供应商重写、Agent SDK 或分布式 Worker。

### 基线与职责

工作区仍为 `C:/Users/22259/.codex/worktrees/f2ad/26-5-27-无限画布`；本地 HEAD 及本轮只读核对的远端 main 为 `d8210980d5c773ff91798cac20e8cfb5c14ee92b`。正式 11.3 沿用原发行记录中的 `a5613dabb6307ceeae4d3bdfc67979b78363ccd7`，本轮未重装或重发。当前内容必须按工作树差异判断，不能只凭 HEAD／VERSION；原有 Agent、图层、SUP-01 及文档增量保留。

| 模块 | 本批实际改动与边界 |
| --- | --- |
| `provider_image_queue.py` | 单 Upstream 的图片提交／在途名额、用户轮转、模型上限及可选 RPM；只调度未发送成员，事实仍在原任务回执 |
| `canvas_task_journal.py`／dispatch／装配／图片回执 | 原 JSON 增补排队阶段、提交时间、准备摘要和本地释放；内存投影从原记录重建，复用领取、权限、配置绑定和原任务恢复 |
| `image_reference_preparation.py` | 在既有授权读取后准备提交副本，统一 JSON／multipart 的格式、体积和 Alpha，不改原资产或归属 |
| `provider_image_queue_api.py`／`queue_gateway.py` | 原后台限额、本人等待取消和管理员本地释放，复用 Gateway 身份及审计；共用原 Comfy 队列代理传输，不把调度移到 Gateway |
| `generation_tasks.py`／任务中心／后台脚本 | 原任务详情显示等待、准备、在途及素材摘要；原“系统管理 → 算力与队列”管理图片策略，无新增业务页面 |
| main 与原页面 | 只装配准备、实际 POST 钩子和原图片链路；在线页等待上传完成，失败不创建任务，移除后可重选相同文件。智能画布 composer 定位在原模块调整 |

无 SQLite Schema、新应用依赖或外部队列。策略复用原原子 JSON 写入，位置为 `STATE_ROOT/image-queue/policy.json`。当前缓存仅在一个平台 API 请求中复用准备副本；两个画布及在线页的多输出实际创建多个 `n=1` 平台任务，每个任务的供应商提交分别计数、各自准备素材。后端一个 `n>1` 请求的子成员同样逐张排队。

### 四项边界与兼容影响

1. **同步与异步。** 同步结果仍经原归档后成功；异步取得 ID 后先持久受理，再查原 ID。生成完成释放在途额度，本地归档失败仍走原恢复，不再次生成。完整结果类型与协议迁出留给 SUP-03。
2. **提交与在途。** 默认同组提交连接 2、在途图片 2、每人同组 1、RPM 0（未设置）。同一 origin 的来源保守共组，Key 轮换不清空原在途事实；管理员仅对已确认账户关系配置分组。不同域名背后的同一账户不会被自动识别，这些数值是工程策略，供应商硬上限仍未知。准备预留、实际 POST 和已发送在途分开显示，原任务 GET 不计新的生成。
3. **素材。** 提交副本最长边 1536px、单件 8MiB、编码引用合计和实际请求体各 32MiB 是项目策略；不是截图中其他站点上传限额或已确认贞贞限额。合法小 PNG／JPEG／WebP 保留原字节，大图生成副本，透明图保留 Alpha，不截断数量或顺序。公开 URL 的 JSON 模式保留；multipart 远程图先通过原素材导入，过期链接上游明确拒绝时保留错误，不自动续期或重提。
4. **历史恢复。** 新建任务和升级前未领取的旧排队任务都进入同组额度。旧排队只在原 `dispatch_version=1`、无领取标记、无上游 ID 的条件下追加队列字段；原 ID、owner、输入及配置绑定不变。已发送的 accepted／unknown 从原回执计数；新批次中断前未发送的成员标 `not_submitted`，受理成员继续原任务查询。管理员释放只记录本地处理，不证明供应商已取消或退款。

### 实际验证与证据

所有供应商响应均为本机受控模拟，实际模型付费调用 **0**，没有对生产任务做查询或处置。应用为正式策略的 CPython 3.14.6 及锁定应用依赖；浏览器为已有 Edge／Playwright，当前没有 Browser 插件，未新增浏览器依赖。

| 验收项 | 已取得的结果及范围 |
| --- | --- |
| SUP-02.A 原画布并发 | 两个普通账号分别真实登录 Gateway，从首页进入 classic／smart，各提交 4／3 个平台任务；同时在途峰值 2，实际提交连接峰值 1（不冒充已压满提交上限）。Bob 的 2 个等待项从原日志任务页取消，剩余 Alice 4＋Bob 1 共 5 项归档；其他账号读取任务、素材和结果被拒绝 |
| SUP-02.B 故障与恢复 | `canvas_img_6732ecdd86894ae5afd33628d3045eab` 在受理后终止并重启隔离 Upstream，保持 `sup02-c7cffa5e5c494b70916b408536c9ba7d`，恢复及原 request_id 回读均新增 POST 0、归档 1 项。响应丢失与 429 的各 3 成员批次只 POST 1 次，另外 2 个 `not_submitted`；管理员释放仅保留未知／原错误，下一合法任务可执行 |
| SUP-02.C 素材及在线上传 | 3 张 1700×1900 RGBA 原件共 38,815,109 字节，准备为 18,097,427 字节、编码 24,129,974 字节，各 1167×1305 且保留 Alpha，原字节完全相同。在线页从实际文件选择器上传 JPEG 后带图归档；人为保持上传未就绪及注入上传 413 时生成 POST 均为 0，移除后重选同文件成功。坏图、总量、重复引用顺序、PNG／LA／调色板 Alpha 以定向测试验证 |
| SUP-02.D 旧任务与权限 | 只在隔离预览停机后为 `canvas_img_39c953894d7e43a59fa10e61ac217c93` 移除新字段，模拟旧版未领取回执，原派发输入、owner 和 ID 保留。新源码启动后先排队，等待原受理任务 `canvas_img_7a8a3143de9948bea9f306329799c4e7` 完成后仅 POST 1 次，两项均归档，已受理任务重放 0 次。已有恢复回归覆盖旧部分结果、本地归档重试及原查询绑定；Key 轮换分组与临时 URL 过期分别为受控配置测试／模拟 HTTP 400，不是实际供应商轮换与 TTL 验收 |
| 原后台 | 从首页“管理后台 → 系统管理 → 算力与队列”打开图片面板，将提交限额从 2 改 1 后保存回读，再恢复 2；普通账号配置／释放 API 均 403，跨账号取消 404，管理员处理复用原操作日志 |
| SUP-01 定位余项 | 旧智能工作流 `cab9abe234974616b1d71415813cc806` 先适配全部节点，再平移到拥挤位置；1600×1000／1024×768 下鼠标均打开尺寸提示。composer 底边距 dock 约 12px，原 3:8 不变，生成 POST 0 |

素材库／画布选图仍复用已有授权引用及原选择器，未单独重跑全部素材库界面。受控主验证 203 项通过（参数、队列、素材、Comfy 共用代理、任务、恢复与结果）；后续旧排队／非本批供应商修整的队列＋dispatch 34 项通过，临时 URL 过期 1 项通过。两组用例存在重叠，不相加为独立总数。页面联调的脚本错误与控制台 error 均为 0，保留既有 Tailwind 开发警告。旧工作流最初目标在可视区外，补验使用原“适配全部节点”后操作，没有用强制点击或键盘替代鼠标通过。

本轮验收发现并修复三类实际问题：并发懒启动重复 worker；未知成员占额度导致同批未发送成员一直等待；在线预览早于上传完成、移除后同文件无法重选。小图复用原有效编码，保留原编辑路径的 PNG／JPEG 兼容。旧 queued 的接纳限制在原领取栅栏，没有通过重写历史 accepted 或自动重提解决占位。

本地资料位于 `D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/development/provider-compatibility-sup02-20261123/`：`baseline.json`、`before/`、`after/`／本轮差异、`affected-tests.txt`、`browser-verification.json`、`online-upload-verification.json`、`restart-verification.json`、`failure-verification.json`、`legacy-queue-verification.json`、`layout-verification.json` 及最终 `validation-summary.json`。浏览器主脚本的旧目标补验单独保留在 layout 记录，不将早期脚本中止写成整脚本一次通过。`supplier-events.jsonl` 只记本机请求／查询及素材尺寸摘要，无 Key 或图像正文；预览源码按 `runtime-files.json` 比对一致，完整新包身份尚不存在。

### 收口与后续

SUP-02 的本地实现与上述模拟范围可供负责人审核。真实渠道小样需要另定模型／模式、素材外发和费用预算；供应商账号硬上限、真实大请求阈值、跨域账户关系及生产负载仍待核实。本轮没有继承此前图层融合的 5 元预算。未来服务器／容器先沿用单一协调进程，逐项验证数据卷、凭据、媒体与备份恢复，多副本／Worker 另验领取及在途协调。

下一顺序仍只见[唯一路线图 4.2.1](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md#provider-compatibility-batches)：完成负责人页面审核及已选真实链路后执行 SUP-03 图片执行抽离，再按实际路径登记 SUP-04 子编号。原图层／Agent 的专项工作保留原范围，源码提交、正式包与生产部署分别取得对应授权并记录；本地测试通过没有改变生产 11.3 的运行内容。

<a id="sup-01"></a>

## 2026-11-21 SUP-01 生产模型参数一致性（本地候选）

负责人要求继续按原路线落地，本轮只实施 SUP-01 的模型能力、页面选项及新提交校验。共享调用来源排队／素材准备仍为 SUP-02，图片执行链抽离为 SUP-03；图层、Agent 及其他原有未提交增量保留。正式 11.3 没有因此更新，未操作生产主机或供应商 Key。

### 来源、范围与模块

- 工作区为 `C:/Users/22259/.codex/worktrees/f2ad/26-5-27-无限画布`。本轮只读核对 GitHub main 与本地 detached HEAD 均为 `d8210980d5c773ff91798cac20e8cfb5c14ee92b`；开始时已有 54 条未提交文件状态。不能用该 HEAD 表示全部候选源码。
- 仓库外资料位于 `D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/development/provider-compatibility-sup01-20261120/`：`baseline.json`、`before/`、`after/`、逐文件 `diff/`、`source-scope.json`、供应商公开文档快照及页面／测试记录。比较以本轮前后副本为准，避免把原图层增量归入 SUP-01。
- 9 份运行文件已与原隔离预览的 `creation-workbench-20261119/app` 逐项内容比对一致：main、贞贞协议、能力模块、公共参数、两类画布脚本及三份 HTML。预览用发行锁定的 CPython 3.14.6；pytest 只安装在外部隔离工具目录，没有改发行依赖。
- `providers/zhenzhen.py` 维护准确名称、参数组合与新增 GPT 编辑编码；`provider_image_profiles.py` 集中后端尺寸验证；`model-picker.js` 集中页面选项及中英文旧值提示。main 只增加校验和能力投影接线（本轮相对快照增加 8 行、移除 3 行），页面沿用原控件和布局。未加入新服务、业务表或队列框架，未提前实施供应商注册层和完整执行器重写。
- 生产名称以负责人提供的 16 个配置为基线，核对供应商公开目录 `/api/models/price`，未读取生产实时配置。本轮维护 ai.t8star.org 工坊规则，没有将这些限制直接套用到平价小屋或其他供应商。

### 本轮维护的模型参数

以下是本地维护契约，文档／请求构造／页面模拟通过与真实渠道通过分别判断。准确名称不改写成相近型号，也不以额外付费提交探测其他端点。

| 准确模型名称 | 本轮规则及兼容影响 |
| --- | --- |
| `gemini-nano-banana-2.1` | 原比例枚举与 1K／2K／4K；原图按实际比例验证 |
| `gemini-nano-banana-2.1-2k` | 补准确名称；同系列比例，固定 2K |
| `gemini-nano-banana-2.1-4k` | 补准确名称；同系列比例，固定 4K |
| `gpt-image-2` | 统一自动／自定义像素与组合校验，保留既有请求路径 |
| `gpt-image-2-all` | 同上，保留既有专用 edits 与受理后原任务查询 |
| `gpt-image-2.5-flare` | 补准确名称及像素规则；参考图走 edits multipart |
| `gpt-image-2.5-sunburst` | 同上，保留准确模型名 |
| `gpt-image-2.6-flare` | 补准确名称及像素规则；参考图走 edits multipart |
| `gpt-image-2.6-sunburst` | 同上，保留准确模型名 |
| `nano-banana-2-2k` | 补准确名称；采用该家族公开比例枚举，固定 2K |
| `nano-banana-2-4k` | 补准确名称；同家族比例，固定 4K |
| `nano-banana-pro` | 原比例枚举与 1K／2K／4K，不再从像素猜测非法自定义比例 |
| `nano-banana-pro-2k` | 原比例枚举，固定 2K，页面档位只读 |
| `nano-banana-pro-4k` | 原比例枚举，固定 4K，页面档位只读 |
| `seedream-v5-pro` | 暂只开放公开客户端的 1024×1024、1536×1024、1024×1536、2048×2048、4096×4096；完整自定义规则待确认 |
| `seedream-v5.5` | 保留本地图层候选的背景／PNG 能力，补 1K／1.5K／2K 和像素尺寸语义；不将 4K 作为可选档位 |

GPT 规则来自供应商公开 API：最长边 3840、宽高为 16 的倍数、长短边最多 3:1、像素总数 655360–8294400；因此 4096×4096 被拦截，合法宽屏组合仍可用。Banana 原图实际为 3:8 或 6:17 时给出不兼容原因，不换成最近比例；旧预设按 16px 取整的兼容保留。固定分辨率由模型决定，不发送可误导的其他 `image_size`。

资料依据：[Banana Pro](https://gpt-best.apifox.cn/api-420361512.md)、[Banana 3.1](https://gpt-best.apifox.cn/api-420646217.md)、[GPT 2](https://gpt-best.apifox.cn/api-447261009.md)、[GPT 2.5 flare](https://gpt-best.apifox.cn/api-515692647.md)、[GPT 2.5 sunburst](https://gpt-best.apifox.cn/api-515693868.md)、[GPT 2.6 文生图](https://gpt-best.apifox.cn/api-534896365.md)／[编辑](https://gpt-best.apifox.cn/api-534982355.md)、[Seedream v5-pro](https://gpt-best.apifox.cn/api-485030908.md)、[供应商公开客户端](https://github.com/T8mars/Comfyui-zhenzhen/blob/main/Comfly.py)及[公开模型目录](https://ai.t8star.org/cn/models)。供应商 API 与客户端的 Seedream 尺寸说明不完整／不一致，当前五个预设是项目明确维护范围，不能声称其他尺寸一定被供应商拒绝；包括 4K 预设在内仍待真实验证。Seedream 5.5 完整像素上限和上传体积没有可靠新证据，本轮不编造阈值。分层模型保留单原图契约，未因目录通用说明而扩成十张图。

### 原页面与定向验证

原页面入口 `http://127.0.0.1:18000/`，两个普通账号通过真实 Gateway 登录。供应商指向本机回环 13002，只保存模拟回执和自有样例图；没有读取真实生成密钥。主审核画布为 classic `9e42ebc2fb9340a0bae7c8d33c79e04f`、smart `b77e24052dba46bbbecac3a0121757d2`，内置浏览器保留 smart 页面。审核标题均为“SUP-01 参数兼容审核 · 类型”。

| 验收项 | 类型与实际结果 | 证据／边界 |
| --- | --- | --- |
| SUP-01.A 原参数入口 | 经典画布、智能画布、在线生图各切换 16 个模型，共 48 次；固定档位、质量、GPT 4K 方形禁选／宽屏可选、Seedream 1.5K、旧值提示通过 | `browser-verification.json`；1600×1000 与 1024×768 截图；普通账号实际页面，没有改版复制界面 |
| SUP-01.B 构造和提交前阻断 | `test_model_request_contract.py` 89 项通过，含 16 名称公开能力、请求编码、非法参数零 HTTP 及共享 Node 选项用例 | `final-request-contract.txt`；纯构造与本地 HTTP 夹具，不表示供应商账号已授权全部型号 |
| SUP-01.C 旧值及权限 | 旧 3:8 参数打开时保留；经典修正保存重开保持型号／画幅／档位；两类画布从原工作流文件入口导入、复制、保存重开均保留旧值／参考图／原结果；两个普通账号验证隔离 | `legacy-workflow-verification.json`：经典 4→8 节点、智能 3→6 节点，额外生成为零；三处跨账号任务／画布 404，媒体 403／404 |
| SUP-01.D 原受理与归档 | 三次模拟生成各新增一次供应商 POST、各归档一项。按相同 request ID 重用并带入当前非法尺寸，仍返回原回执且未新增提交 | classic `canvas_img_cea3352c6bb2429b85dc304799ed991e`；smart `canvas_img_4f303c0ca66244618b16cdff0e969f35`；online `canvas_img_ee183485e3c843aa940d0a714b77da3b` |
| 恢复及受影响增量 | `test_canvas_image_recovery_main.py`、`test_zhenzhen_image_outputs.py`、`test_creation_settings.py` 共 44 项通过 | 包含同步／异步、部分结果、强退后原 ID 查询及归档；旧恢复夹具仅把本来已非法的 GPT 4096 方图请求改为合法 3840×2160，没有移除恢复断言 |
| 前端及环境检查 | 三份 JS 语法、在线 HTML 内联脚本、发行锁定运行时检查通过；页面错误及失败接口均为零 | 已安装 Edge + 现有 Playwright，Browser 插件未提供；保留既有 Tailwind 开发提示，未安装浏览器依赖 |
| 文档及差异检查 | 现有文档检查通过：154 份资料、11 个事实源、21 份冻结资料、0 错误；文档契约 17 项通过；`git diff --check` 通过 | 原文档登记表与导航／Wiki 已同步，没有新建路线图；检查只覆盖文档与差异格式 |
| 真实调用／现场 | 本轮真实付费调用 0，生产操作 0 | 没有使用旧图层融合的 5 元授权；供应商质量、账号容量、所有模型／参数组合及正式安装包现场均待验收 |

预览旧数据库缺少版本元数据曾使来源提示返回 `DEPARTMENT_SCHEMA_UPGRADE_REQUIRED`。只对隔离预览使用现有 `apply_legacy_versioned_migrations` 和正式迁移注册表对齐 Schema 4，保留原账号和成套备份；`preview-schema-alignment.json`、`preview-db-backups/` 保存证据。没有新增应用迁移、变更生产数据或绕过迁移条件。最终页面请求不再出现该 503。

### 状态与下一步

本批源代码和模拟结果用于负责人审核；SUP-01 的真实渠道及所有兼容组合没有被模拟结论代替。旧工作流补验使用独立画布：经典 `27c8a08c708a4498a714b0733b905f9a`、智能 `cab9abe234974616b1d71415813cc806`。智能复制后布局较拥挤，尺寸按钮被底部工具栏遮挡，使用键盘 Enter 打开后不兼容提示正确；此处没有把键盘通过写成鼠标交互已通过。定位修整作为现有工具条的审核余项登记到原路线图，不重做节点。初始化早于画布加载完成的首轮夹具已改为等待准确标题，参数和工作流逻辑未因此变更。

参数契约缺失时记录准确待验证字段。后续按唯一路线图实施 SUP-02 的共享来源提交／在途计数与素材准备，再逐路抽离图片执行链及其他实际路径。原图层和 Agent 候选没有因本批通过而变成正式功能。

本轮没有 commit、push、建 PR、合并、生成正式安装包或生产部署。真实验证先确定渠道、模型／模式、样例及预算；本地页面审核后才能按对应授权进入源码提交和发行，生产升级仍单独安排。

<a id="sup-00"></a>

## 2026-11-20 SUP-00 供应商兼容方案与基线核对

本轮为文档和源码核对，未执行生图、真实供应商请求或生产部署。方案见[ADR-PROVIDER-001](../decisions/ADR-PROVIDER-001-MODEL-COMPATIBILITY-AND-EXECUTION-BOUNDARIES-2026-11.md)，批次及完成条件只见[路线图 4.2.1](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md#provider-compatibility-batches)。本节以下 2026-10-13 内容保留当时实施范围。

### 来源与差异

| 核对项 | 实际结果与边界 |
| --- | --- |
| 仓库与本地候选 | `MEIS-DaCaiTou/Infinite-Canvas-Enterprise`，工作区 `C:/Users/22259/.codex/worktrees/f2ad/26-5-27-无限画布`，detached HEAD `d8210980d5c773ff91798cac20e8cfb5c14ee92b`；本轮开始时原有 46 条未提交文件状态 |
| 正式包 | GitHub API 的 latest 为 `v2026.11.3`，draft=false、prerelease=false，8 项资产；标签直接指向 `a5613dabb6307ceeae4d3bdfc67979b78363ccd7`，main 为上述 d821098；本轮未重新下载或安装 |
| 与正式版相同的关键模块 | `canvas_task_dispatch.py`、`canvas_task_dispatch_app.py`、`providers/submission.py`、`canvas_image_recovery.py`、`task_credentials.py`、`static/js/model-picker.js`、`static/js/canvas.js` 内容比对一致 |
| 原有候选差异 | `providers/zhenzhen.py`、`provider_image_profiles.py`、`main.py`、`static/js/smart-canvas.js` 等已有本地改动；贞贞能力新增 `seedream-v5.5` 与 `seedream-v5.5/layer-decomposition`，不能写成正式版已覆盖 |
| 预览源码映射 | `D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/development/creation-workbench-20261119/app` 中 main、贞贞模块和智能画布脚本与本工作树三项对应文件一致；此次未运行页面或重测模型 |
| 文档前后记录 | `D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/development/provider-compatibility-plan-20261120/` 保存本轮基线、文档前后副本和检查结果，属于本地核对资料 |

### 验收与未覆盖范围

SUP-01 的初始模型清单来自负责人提供的生产配置与排查报告。本轮以正式源码和当前未提交候选离线核对目录命中，未读取生产实时配置、未逐模型调用。下表的“有”仅代表命中专用图片规则；通用路径可能已有成功记录，完整参数、模式与前端一致性仍按 SUP-01 验收。SUP-01 开始时核对配置变化并保留本快照。

| 准确模型名称 | 正式 11.3 专用目录 | 当前本地候选专用目录 |
| --- | --- | --- |
| `gemini-nano-banana-2.1` | 有 | 有 |
| `gemini-nano-banana-2.1-2k` | 无 | 无 |
| `gemini-nano-banana-2.1-4k` | 无 | 无 |
| `gpt-image-2` | 有 | 有 |
| `gpt-image-2-all` | 有 | 有 |
| `gpt-image-2.5-flare` | 无 | 无 |
| `gpt-image-2.5-sunburst` | 无 | 无 |
| `gpt-image-2.6-flare` | 无 | 无 |
| `gpt-image-2.6-sunburst` | 无 | 无 |
| `nano-banana-2-2k` | 无 | 无 |
| `nano-banana-2-4k` | 无 | 无 |
| `nano-banana-pro` | 有 | 有 |
| `nano-banana-pro-2k` | 有 | 有 |
| `nano-banana-pro-4k` | 有 | 有 |
| `seedream-v5-pro` | 有 | 有 |
| `seedream-v5.5` | 无 | 有 |

本地候选另外新增的 `seedream-v5.5/layer-decomposition` 沿用原图层候选范围；其特殊输出属于受影响回归，不据此扩大本批生产模型清单。

| 工作项 | 证据类型 | 实际结果 |
| --- | --- | --- |
| SUP-00.A 版本与候选核对 | 源码及只读 GitHub API | 上表已记录 main、正式标签、工作树差异和三项预览映射；来源判断未触及生产目录 |
| SUP-00.B 方案登记 | 文档审阅 | 四项边界、职责、能力与错误契约已写入 ADR；提议、批准与已有实现分开，四批顺序与稳定编号登记在唯一路线图 |
| SUP-00.C 文档检查 | 文档检查 | `tools/check_docs.py` 通过，154 份文档、11 个事实源角色、21 份冻结资料，0 错误；现有 `test_documentation_contract.py` 17 项通过；`git diff --check` 通过。链接检查为本地链接，业务与外链可用性未在此项验证 |
| 后续原页面联调 | 模拟／页面 | 本轮未执行，SUP-01 至 SUP-04 按各自验收项补齐旧画布、普通用户权限、原任务续查与结果归档 |
| 后续模型与现场验收 | 真实调用／现场 | 本轮未执行；原图层预览的一次 Seedream 5.5 真实融合不作为 16 模型参数或共享 Key 容量验收 |

后续每批在本文件追加 `SUP-编号 + 日期` 小节，记录本批验收项、源码／包与预览身份、原页面路径、账号角色、输入规模、模拟／真实／现场类型、预期／实际结果、生成 POST 与查询次数、回执／归档证据及未验证项。记录脱敏来源引用，密钥和素材正文保留在原凭据／素材系统。当前状态汇总回填 CURRENT，新增工作范围只回填路线图。

---

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

修正仅为成员入口和后台返回声明target=_top，同时更新canvas-workspace-boot及其引用的缓存参数；Gateway原守卫隐藏子frame的重复账号栏，仍完整执行权限治理。不添加路由框架、页面、数据库迁移、权限或付费行为。候选版本10.8，准确构建源由Manifest固定；10.7原记录和资产保持。新安装包先按现有离线维护交付，未声明新在线路径；7→8同Schema4维护沿用既有引擎，本轮不重跑完整安装恢复矩阵。

本机真实Edge+既有Python Playwright，1760×960及390×844；现有main/业务/归属/SQLite/Gateway注入、合成身份Cookie。原代码返回后root_shells=2；修正后5次管理员往返、企业项目筛选、网格/列表、两类画布打开、旧嵌入后台返回、负责人独立入口及普通员工403均通过，root_shells及可见账号栏均保持1。补齐夹具原user_model_api后最终无页面/控制台/HTTP错误、无生成POST；此前两次404仅来自夹具缺该路由，不计为产品缺陷。Tailwind自带开发提示保留，无框架错误覆盖层。实际登录、客户设备及完全卡死的其他现场因素未验证。后台/账号栏定向12项通过，新增Node VM执行实际守卫，先在旧代码失败；顶层保留账号栏、子frame隐藏且权限class仍设置。旧手工_run_checks因历史静态字符串缺失报ValueError，原main728b4bc同样失败，未扩修该旧检查。JS语法及文档检查随准确Head记录。独立Review结果为NO_ACTIONABLE_BUGS_FOUND，仅审查本次程序差异及关联路径，不代表排除全部现场因素。

证据和脚本集中仓库外产品artifact根D50，不提交客户原图或浏览器原始输出。合并、正式发布和现场结果按原PR与CURRENT分别更新；撤销本补丁只恢复链接目标/缓存参数，无数据回滚。
