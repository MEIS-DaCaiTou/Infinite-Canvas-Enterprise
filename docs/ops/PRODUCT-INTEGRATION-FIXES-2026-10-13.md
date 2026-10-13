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
