# 企业版浏览器级回归验收清单

本文档用于每次企业功能变更、上游同步、入口治理或权限相关 PR 之后做真实浏览器回归验收。它只定义验收流程，不修改业务逻辑，也不覆盖第三方图片模型高规格失败问题。

## 一、适用范围

- 适用于 Infinite Canvas Enterprise 企业多用户版本。
- 重点防止登录、角色权限、管理后台、画布访问、对话访问、素材访问、企业项目入口和更新权限被后续改坏。
- 本清单不执行 Issue #8，不处理画布与对话归属隔离加固，不重新打开 Issue #15 / #16。
- 高规格图片编辑组合，例如 `gpt-image-2 /images/edits + 2k + high + 大比例源图`，属于第三方平台或上游通道稳定性问题，不作为本清单阻断项。

## 二、验收前准备

1. 确认当前分支、版本、提交和工作区：

```powershell
git branch --show-current
git status --short
git log --oneline -5
Get-Content .\VERSION
```

2. 确认不会提交运行时数据：

- 不提交 `enterprise.env`。
- 不提交 `API/.env`。
- 不提交 `data/enterprise.db`。
- 不提交 `data/canvases/`。
- 不提交 `data/conversations/`。
- 不提交 `data/api_providers.json`。
- 不提交浏览器截图、控制台日志中的 Cookie、Token、API Key 或个人数据。

3. 准备测试账号：

- 管理员账号：来自本地 `enterprise.env` 或既有测试管理员。
- 普通用户账号：使用可回收的测试用户，避免破坏真实用户。
- 如需要新建用户，验收结束后禁用或恢复该用户状态。

4. 浏览器建议：

- 优先使用无痕窗口，或在测试前 `Ctrl + F5` 强制刷新。
- 打开 DevTools，记录 Network 和 Console 中的阻断性错误。
- 验收中只记录脱敏结果，不保存真实 Cookie、Token 或密钥。

## 三、启动与健康检查

- [ ] 启动企业版：双击 `启动企业版.bat`，或按项目文档从根目录启动。
- [ ] 确认 `127.0.0.1:3001` 为内部上游服务。
- [ ] 确认 `0.0.0.0:8000` 为企业网关。
- [ ] 访问 `http://127.0.0.1:8000/enterprise/health`。
- [ ] 确认返回 `gateway=ok`。
- [ ] 确认返回 `upstream=ok`。
- [ ] 执行诊断脚本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\diagnose.ps1
```

- [ ] 执行非破坏性冒烟脚本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\smoke.ps1
```

- [ ] 如本轮需要启动/停止闭环，提前说明会短暂中断服务，再执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\test_start_stop.ps1 -StopExisting
```

## 四、登录与角色

- [ ] 未登录访问 `http://127.0.0.1:8000/`，应跳转到 `/enterprise/login?next=/`。
- [ ] 未登录访问 `/enterprise/admin`，应跳转登录页或返回鉴权保护结果。
- [ ] 管理员可登录。
- [ ] 管理员退出登录后，受保护页面不应继续访问。
- [ ] 普通用户可登录。
- [ ] 普通用户退出登录后，受保护页面不应继续访问。
- [ ] 禁用用户无法登录，错误提示应清晰。

## 五、管理后台

- [ ] 管理员可进入 `/enterprise/admin`。
- [ ] 普通用户不能进入 `/enterprise/admin`。
- [ ] 成员列表正常显示用户名、展示名、角色、状态、创建时间、最后登录时间和操作按钮。
- [ ] 成员管理表格在常见桌面宽度下不应把按钮挤成竖排。
- [ ] 新建测试用户成功。
- [ ] 新建用户后成员列表刷新，用户状态为正常。
- [ ] 编辑测试用户展示名成功，列表中展示名更新。
- [ ] 重置测试用户密码成功，测试用户可用新密码登录。
- [ ] 禁用测试用户成功，状态变为已禁用，按钮变为启用。
- [ ] 启用测试用户成功，状态恢复正常，按钮变为禁用。
- [ ] 将测试用户设为管理员成功。
- [ ] 撤销测试用户管理员成功。
- [ ] 管理员不能禁用或删除自己。
- [ ] 操作日志页面 `/enterprise/logs` 可打开。
- [ ] 操作日志中能看到本轮用户管理动作，例如 `user_created`、`user_profile_updated`、`user_password_reset`、`user_role_updated`、`user_disabled`、`user_enabled`。
- [ ] 操作日志分页默认每页 20 条。
- [ ] 操作日志每页条数 10 / 20 / 50 / 100 可切换。
- [ ] 操作日志上一页 / 下一页可用。
- [ ] 操作日志用户筛选和操作类型筛选可用。

## 六、企业入口治理

- [ ] 管理员登录后，页面“项目主页”指向企业仓库：`https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise`。
- [ ] 普通用户登录后，页面“项目主页”也不得指向上游 `hero8152/Infinite-Canvas`。
- [ ] 普通用户看不到“一键更新”按钮。
- [ ] 普通用户看不到“更新到 vX”的上游更新提示。
- [ ] 普通用户看不到上游作者社交入口，或该区域已被企业治理隐藏。
- [ ] 普通用户直接请求更新接口返回 403：

```powershell
# 需在普通用户登录态浏览器中验证，或使用对应 Cookie 发起请求。
/api/update-from-github
/api/update-rollback
/api/update-backups
/api/update-connectivity
```

- [ ] 管理员如看到更新入口，文案必须体现“企业版更新”或“企业版受控更新”，不得表现为普通上游一键更新。
- [ ] 企业用户信息栏、管理后台入口、退出按钮仍正常。

## 七、画布基础功能

- [ ] 普通用户可进入画布列表。
- [ ] 普通用户只看到自己有权限的画布。
- [ ] 普通用户可创建新画布。
- [ ] 新建画布后，企业层记录画布归属。
- [ ] 普通用户打开自己的画布正常。
- [ ] 画布保存正常。
- [ ] 从画布返回列表正常。
- [ ] 管理员可进入画布归属管理。
- [ ] 管理员可看到画布归属信息。
- [ ] Smart Canvas 页面可打开。
- [ ] Smart Canvas 打开后 Console 不出现阻断性错误。
- [ ] Smart Canvas 不应出现明显永久 running 异常。第三方模型高规格失败不作为本清单阻断项，但应记录为外部服务风险。

## 八、对话基础功能

- [ ] 普通用户可创建 GPT 对话。
- [ ] 普通用户只看到自己的对话。
- [ ] 普通用户不能通过列表看到其他用户对话。
- [ ] 未登录用户不能访问受保护对话页面。
- [ ] 管理员权限边界需在本轮回归记录中说明：管理员是否可查看全局资源，以当前产品设计和企业文档为准。

## 九、素材与输出资源

- [ ] 素材库页面可打开。
- [ ] 图片资源可预览。
- [ ] 普通用户仅能看到自己应有权限的素材或输出资源。
- [ ] `/api/view` 相关路径不应绕过企业权限边界。
- [ ] `/api/download-output` 相关路径不应绕过企业权限边界。
- [ ] `/assets/` 相关资源访问不应暴露其他用户受保护内容。
- [ ] `/output/` 相关资源访问不应暴露其他用户受保护内容。
- [ ] 本任务只定义验收点；如发现隔离缺陷，应记录新 Issue，不在浏览器回归体系任务中顺手修复。

## 十、上游同步后专项验收

每次同步上游后，除前面所有项外，还必须检查：

- [ ] 根目录 `README.md` 仍是企业版项目入口说明，没有被上游 README 覆盖。
- [ ] 上游 README 如有同步，位于 `docs/upstream/README.upstream.md` 并标注仅供参考。
- [ ] `docs/upstream/SYNC_POLICY.md` 仍记录 README 边界和同步规则。
- [ ] `enterprise/gateway.py` 的企业入口治理仍能治理上游首页 DOM。
- [ ] 项目主页仍指向企业仓库。
- [ ] 普通用户更新入口仍隐藏。
- [ ] 普通用户绕过前端调用更新接口仍返回 403。
- [ ] 普通用户权限隔离没有被上游新增 API 绕过。
- [ ] 新增上游页面或接口如涉及资源列表、输出、下载、更新、资产访问，应记录是否需要纳入企业拦截或响应过滤。
- [ ] `enterprise/`、`enterprise-static/`、`enterprise/tests/` 和企业文档没有被上游同步误覆盖。

## 十一、结果记录格式

建议将每次完整回归结果追加到 `enterprise/tests/UPDATE_TEST_LOG.md`，格式如下：

```markdown
## YYYY-MM-DD - Browser regression - <branch or PR>

- Branch:
- Commit:
- VERSION:
- Tester:
- Browser:
- Admin account: <role only, no password>
- Normal account: <role only, no password>

Automated checks:

- diagnose.ps1:
- smoke.ps1:
- test_start_stop.ps1 -StopExisting: <run / not run, reason>

Manual browser checks:

- Startup and health:
- Login and roles:
- Admin console:
- Enterprise entry governance:
- Canvas basics:
- Conversation basics:
- Assets and output resources:
- Upstream sync checks:

Failures:

- <path / action / expected / actual / severity>

Risk:

- <remaining risk>

Merge recommendation:

- <recommend merge / block merge / merge with documented caveat>
```

## 十二、合并阻断规则

以下问题通常应阻断合并：

- 企业版无法启动。
- `/enterprise/health` 非正常。
- 管理员无法登录或无法进入管理后台。
- 普通用户可进入管理后台。
- 普通用户可触发更新或回滚接口。
- 项目主页回到上游仓库。
- 上游同步覆盖了企业 README 或企业层文件。
- 普通用户明显看到其他用户画布、对话或受保护资源。
- 画布基础打开、保存、返回列表不可用。
- Console 出现阻断性错误导致关键页面不可用。

以下问题应记录风险，但不默认阻断本清单对应 PR：

- 第三方图片模型高规格请求不稳定。
- 外部 API 平台返回限流、系统繁忙或通道错误。
- 需要单独 Issue 才能处理的历史隔离缺口。
