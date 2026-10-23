# 部门首版组合发行记录（10.5 预置／10.6 启用）

核验日期：2026-10-23。本文固定发行源码、资产、验收边界和原升级说明；当前10.5/10.6已暂停稳定推荐，10.4恢复稳定Latest。动态进度只见 [CURRENT](../CURRENT_PROJECT_STATUS.md)。以下冻结候选和早期验收按原时点保留。

## 现场恢复及暂停推荐（2026-10-23）

负责人测试主机10.4→10.5在线交接失败，后续刷新确认维护503；运行匹配的显式恢复工具后确认原画布恢复，仍为10.4、upgrade_executed=false，原失败序列已停止。未执行部门升级，不把原公开目录检查或10.5→10.6自有验收当成10.4现场在线成功。

按负责人明确批准，两个原Release保留公开，标签、全部原资产ID/名称/大小/摘要/下载URL不变；仅追加问题说明、设为预发布并取消Latest。预发布标记用于撤下原稳定路由，不表示这些原字节变成新的测试构建。准确冻结10.4/10.5程序无Token读取公开目录，均返回update_available=false/latest=null，原5/6稳定路由拒绝匹配。GitHub稳定Latest为10.4。仓库外D47保留元数据前后快照及原控制器只读结果。

下方“简明升级说明”属于原发布时路径，当前暂停执行其中在线步骤。修复交付拟用10.7，不覆盖5/6资产；先验证原5离线预置→10.7，等待修复版的最终说明。当前已恢复10.4的主机继续使用；已正常10.6的主机不因此降级。

## 正式发布收口（2026-10-23）

负责人明确批准#197合并及正式发布10.5/10.6，测试主机由负责人自行操作。#197准确Head05323e6通过CI后合入main`892f32a762bb6c96afe07e9e74a1c3c58d529013`，本地main同步；该main自身[Enterprise/Runtime](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/39886795376)及[Docs](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/39886795360)均SUCCESS，固定EXE opt-in仍SKIPPED，本地验收另列。

[v2026.10.5](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/releases/tag/v2026.10.5)于02:11:39 UTC发布，[v2026.10.6](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/releases/tag/v2026.10.6)于02:11:49 UTC发布，均非Draft、非预发布，10.6为Latest。标签分别固定到下表31e68cb与90b55c4；每版九项原资产直接上传，GitHub回传摘要与冻结记录一致，不重新打包、不覆盖旧正式版本资产。

18项核心资产经无Token的公开下载链接回读，原大小和摘要全部匹配；复用产品原atomic_download，未另建下载器。两个目标ZIP内的数据库证据与公开路由一致。产品GitHubReleasesProvider读取完整21条公开目录，路由规划为正式10.4→10.5→10.6；再以两种准确冻结来源的原_check_update_sync读取公开目录，正式10.4显示stable/requires_intermediate，10.5显示stable/direct，最新均为10.6。后两项仅只读检查，不启动Runtime、不准备或执行升级，不是Browser/客户验收。

发布及回读证据在仓库外D43：preflight.json、draft-upload-result.json、main-ci.json、publish-result.json、public-verification.json及frozen-source-public-checks.json。资产回读夹具首次默认GBK解码中文元数据、随后将stream迭代器误当上下文管理器，均发生在相应下载前；修正夹具并复用产品atomic_download后完成，不改已发布字节或产品代码。本轮没有供应商付费生成，也没有客户安装/数据库操作。

## 变更原因与交付内容

本次将已合并的部门、项目、两类调用来源、费用和画布性能能力组成可升级的发行候选。员工继续从原无限画布入口创作；个人／部门／企业范围、多级目录、网格／列表、成员筛选及归档帮助查找画布。共享项目直接打开原画布，保留提示词、参考原图、参数、连线和成果；保存私有副本后继续创作。共享不暴露密钥，费用仍按原角色权限查看。

公司共享和部门专用来源分开授权，采购来源、实际账户及业务归属分别记录。既有任务继续查询原受理身份；费用按单位分别汇总、未知待核对，预算超额只提醒。视频运行中预览继续查原任务，封面、尾帧及音频不会被当作成片。

沿用现有 Update Center、版本化迁移、Setup 和恢复流程，没有新增页面、迁移器、任务队列或日常生成审批。旧正式10.4先同结构预置迁移目录，再由启用包执行2→4；普通启动不迁移。

## 固定源码及资产

负责人授权后，[#195](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/195)、[#196](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/196) 依次合入 main `419405c58934052aca976b00ebdab110e72e4447`、`1d85f5440f28ae79fe35e84eeb6acc2c162aa94e`。该1d85f54时点的Git tree与准确10.6构建源相同；之后#197仅改五份文档，不替换构建身份。原独立技术审查均为 NO_ACTIONABLE_BUGS_FOUND；准确 Head CI 成功，固定EXE real opt-in跳过。

合并#196后的1d85f54主线[Enterprise/Runtime CI](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/39827022962)和[文档CI](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/39827023056)均SUCCESS；#195合并提交的[固定EXE CI](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/actions/runs/39826951895)也为SUCCESS。#196及后续发行记录未改原生入口，没有额外触发该工作流；不把先前运行记作892f32a的新执行。

| 版本 | 准确源码 | Release ID | 数据结构 |
| --- | --- | --- | --- |
| 2026.10.5 预置 | `31e68cb6739d27647ea47a414d17667895cabd43` | `ice-2026.10.5-31e68cb6739d` | 保持 Schema2 |
| 2026.10.6 部门启用 | `90b55c4e7f66fd078bb0bf3aae0cd043de2e09a2` | `ice-2026.10.6-90b55c4e7f66` | 声明迁移到 Schema4 |

各版本固定九项上传资产：Manifest v2、对应 ZIP、payload inventory、固定EXE及构建记录、InfiniteCanvasSetup.exe及构建记录、maintenance-tools-v1.json、upgrade-routes-v1.json。复用原 CPython3.14.6 和工具链；本轮没有重打包，已验收资产保持原字节。

| 资产 SHA256 | 10.5 | 10.6 |
| --- | --- | --- |
| Manifest | `671d643724d482523821240992a9b30c98c06e5322017361a99f74425d45ecd8` | `22a6fd902e866754cc3126c08a6a54da14b215137b8061d3ad2c79398f810a1a` |
| ZIP | `04571ba7d52e441dfa8cfbd75c633336d26448883e541a7ef59be997800c98d1` | `eb01e6141a98814ff5ebdf664b6e6abb0d2e582bc38d6b3543b75b8fd0c6b5fb` |
| Setup | `fa3e0d59e4bd59b1386de1bc312f7700f4f7f351119cc6ba2b33164e172c1b64` | `9c09c5a4dc907d980aed10c3ac69b618dfa40a18b8c56660eda2558fa3e14c69` |
| 路由 | `f131f42d684d59e86017ef66d10630c10dbefb0abb5989013f62d261ee274af7` | `ae0767033ca517a15634813ca52e0795ebad6a69796a16a1fb69dc43b7780afd` |

仓库外 `D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/t/D36/release/frozen-assets.json` 固定各文件的上传名、原路径、大小及已有发行完整性摘要。10.5构建在 `t/D28/bridge`，10.6在 `t/D34/final`，路由在 `t/D36/release`。这些原字节已上传上述正式Release。两份准确路由和目标归档沿原验证：正式10.4→10.5→10.6，10.5→10.6；缺少预置包时不会伪造直接路径。

## 联合验收

| 场景 | 结果及证据范围 |
| --- | --- |
| 准确10.5→最终10.6在线升级 | 真实固定EXE/CP314、原来源 prepare、真实管理员认证HTTP execute、分离worker、目标启动/健康成功；两类画布经认证HTTP保存重开、原账号/配置/素材保持；开发机合成安装，未发布 |
| 升级后原任务续查 | 源安装已有受理回执，目标自动查询原视频ID与ComfyUI prompt_id并归档；视频第一次RUNNING带预览仍继续查询；只访问原查询/结果地址，无生成POST、无预览/尾帧下载。供应商是本机HTTP夹具，视频字节为合成归档测试，不冒充真实播放/GPU验收 |
| 目标失败恢复 | 复用原故障监听器，在目标启动失败后释放端口：真实worker确认目标已停、恢复数据库、重启来源并通过健康检查，ROLLED_BACK、database_restored=true、Schema2。账号登录及两类画布重开已执行；先前持续占用端口的负例仍保留RECOVERY_REQUIRED，不算回退通过 |
| 回退后原任务 | 原ComfyUI在实际恢复Runtime中完成；原视频ID保持并持续GET。旧10.5尚未包含#196，夹具末帧字段触发其原缺陷；在同地址返回该旧版支持的视频结果后，冻结CP314实际main独立进程用原ID完成归档，GET原ID及结果各一次，无重提。该补验是实际main启动钩子，不是第二次Runtime/在线升级 |
| 原离线Setup/Windows登记 | 沿用#195准确5104334的真实GUI/Runtime、安装ID、原账号/画布、部门角色与来源权限及保留数据卸载证据；不是90b55c4完整GUI重测。准确90b55c4已重新完成完整打包及冻结导入烟测 |

本轮服务定向21项通过，覆盖结果识别、ComfyUI HTTP合同、真实main启动/进程重启及原任务续查；与历史结果重叠不累加。常规CI和固定EXE opt-in分别记录，不把SKIPPED记为通过。

首轮合成ComfyUI回执漏填产品正常提交会保存的seed，归档报缺字段；保留原记录后补齐夹具，原任务续查完成，未修改产品代码或重新提交工作流。首轮故障监听器释放条件也已保留，改复用仓库现有注入函数，只重跑失败场景。复测脚本因期望旧10.5处理新增末帧字段而超时，不能记为整脚本通过；真实回退状态和补验分列。10.6首次运行已覆盖该字段并成功，这也是不在预置版停留的原因。首轮结果文件里的PRAGMA user_version=0不是产品结构版本，补读正式schema metadata为4；不以该pragma当迁移依据。

两轮实际Runtime已停止，八个自建测试端口关闭；开发机原运行根字节、mtime及目录身份核验恢复，没有客户安装或数据库操作。证据保留于仓库外D36（成功及首次负例）、D37（真实回退及整脚本超时）、D38（旧版原任务补验及联合汇总），不将两个退出1的夹具脚本改成退出0。

## 常用模型的实际边界

Grok imagine、MiniMax-H3、Wan3及图片文生图沿用此前真实成功记录；本轮没有重复付费探测。仅GET读取原授权令牌用量仍为6.710022／10平台额度，新付费调用0。令牌日志查询未得到足以判定旧双参考JSON编辑终态的记录，不把用量无变化当作未受理或可重提。

[原编辑文档](https://gpt-best.apifox.cn/api-513955033)仍不能证明该账号通道、多参考格式和旧请求结果；不改变模型路由去探测另一付费入口。旧双参考编辑终态仍待核对，不承诺全目录适配，RunningHub继续暂缓。

### 2026-10-23 真实ComfyUI补验

负责人确认原平台能生成，随后定位并补齐云防火墙中开发机来源IP。此前超时保留为当时事实；放行后开发机直连及环境代理均可访问，system_stats、queue、object_info返回200，开始前队列为空，无须修改产品地址归一化或适配代码。

复用准确10.6冻结CPython3.14/main，在仓库外D42隔离目录运行一次512×512、8步的Z-Image Turbo图，使用远端已有z_image_turbo、qwen_3_4b和ae模型，不下载模型、不修改后端配置。产品原生成函数提交工作流、立即保存真实prompt_id后，由夹具中断本地进程；新CP314进程执行原startup_event，恢复原任务并自动查询同一ID，最终下载、解码及归档PNG成功。归档图片已目视核验为蓝色T恤，任务所属用户保留。请求记录仅一次POST /prompt；恢复阶段只有GET原history、queue及view，没有重复生成。

证据在仓库外`D:/CodeProject/Infinite-Canvas-Enterprise-Artifacts/t/D42`的connectivity.json、accepted.json、result.json及两阶段请求记录；实际prompt_id和结果字节仅留本地。首次夹具调用旧用户创建接口被现有角色治理拒绝，发生在提交前；改用仓库既有显式测试管理员初始化后继续，产品权限未改。补验覆盖真实GPU图、原任务身份、进程中断及图片归档，不是再次固定EXE/安装升级、画布浏览器或全部客户工作流验收。测试进程已经结束；仅在已授权远端执行该测试图，未操作客户安装/数据库、未修改云防火墙，贞贞新增付费调用0。

## 简明升级说明

正式10.4来源由负责人在测试主机执行以下路径；本轮未代操作客户安装或数据库：

1. 确认生成任务完成，备份按原更新流程保留。在线更新选择部门启用版本，由已声明路径经过10.5；公开目录与完整路径可用性以发布后核验结果为准。
2. 使用离线Setup时，从原固定窗口停止服务并关闭启动窗口；先运行[10.5预置包](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/releases/download/v2026.10.5/InfiniteCanvasSetup.exe)，选择原安装位置并升级，再对同一位置运行[10.6启用包](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/releases/download/v2026.10.6/InfiniteCanvasSetup.exe)。两包同名，分别保存到10.5/10.6文件夹；10.5完成后若打开启动窗口，先停止服务并关闭窗口再运行10.6。保留原账号、画布、素材和配置，无需打开高级维护。
3. 从原入口启动并使用原账号登录。公司管理员在既有成员管理中创建部门、分配成员及负责人；旧私人内容保持原归属，需要时明确关联项目或共享。

升级失败遵循原作业状态：已自动回退时确认原版本健康；RECOVERY_REQUIRED保留诊断与原作业，使用匹配恢复流程，不覆盖原目录、不删除锁/WAL或重新提交生成。业务在新结构继续写入后的任意无损降级不在本候选承诺范围。

下一完整工作包是测试主机升级及部门功能实际使用反馈：确认页面2026.10.6、原账号/画布/素材、已有视频播放和一个常用ComfyUI工作流；随后检查部门成员、完整项目共享、两类调用来源及角色费用视图，并按真实缺陷定向处理。10.5只作同结构升级准备，继续完成10.6启用。真实ComfyUI生成/重启续查已补，旧图片未知请求澄清后再做对应有界验收。
