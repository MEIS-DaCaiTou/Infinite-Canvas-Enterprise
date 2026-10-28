/* Presentation-only vocabulary. User names, department names and provider data stay intact. */
(function(){
    const phrases = {
        "算力与队列":"Compute & Queue", "管理 ComfyUI 算力、用户限额和工作流排队":"Manage ComfyUI capacity, user limits and workflow queues", "保存设置":"Save settings", "当前任务":"Current tasks",
        "管理后台 · 无限画布企业版":"Administration · Infinite Canvas Enterprise",
        "加载中…":"Loading…", "用户覆盖":"User overrides", "请选择用户":"Select a user", "为单个用户设置 inherit / allow / deny。inherit 表示继承全局默认值。":"Set inherit, allow or deny for a user. Inherit uses the global default.", "状态：正常优先":"Status: active first", "每页条数":"Rows per page", "上一页":"Previous", "下一页":"Next", "全部":"All",
        "显示 {start}-{end} / 共 {total}":"Showing {start}–{end} of {total}", "第 {page} / {pages} 页":"Page {page} of {pages}",
        "允许访问 API Provider、Key、Base URL、Provider 测试等高风险设置。":"Access provider configuration, keys, addresses and connection tests.",
        "允许访问工作流、ComfyUI 实例、RunningHub 工作流和相关全局配置。":"Access workflows, ComfyUI instances, RunningHub workflows and global settings.",
        "允许提交 RunningHub 生成任务。":"Submit RunningHub generation tasks.", "允许提交视频生成任务。":"Submit video generation tasks.",
        "允许提交在线生图、ZImage、Angle、ModelScope 等图片工具任务。":"Submit online image, ZImage, Angle and ModelScope tasks.",
        "允许新增、编辑、移动、删除、分类、裁剪、注册或导入素材库对象。":"Create, edit, move, delete, classify, crop, register and import assets.",
        "允许通过历史记录删除接口删除生成历史。":"Delete generation history through the history interface.",
        "允许移动、重命名、删除、标注、分类或通过 URL 导入本地资源。":"Move, rename, delete, annotate, classify or import local resources by URL.",
        "允许使用企业版受控的项目更新接口和更新入口。":"Use the enterprise update interface and Update Center.",
        "平台管理":"Platform Administration", "返回画布":"Back to Canvas", "账号":"Account", "个人中心":"My Account", "退出登录":"Sign out",
        "成员与部门":"Members & Departments", "资源归属":"Resource Ownership", "渠道密钥":"Channel Keys", "系统管理":"System", "管理导航":"Administration navigation",
        "成员":"Members", "位成员":"members", "个部门":"departments", "部门":"Departments", "项目归属":"Projects", "画布归属":"Canvases", "对话归属":"Conversations", "权限开关":"Feature Controls", "更新中心":"Updates", "操作日志":"Activity Log",
        "管理企业成员及所属部门":"Manage members and their departments", "管理部门及成员归属":"Manage departments and membership", "管理原有项目、画布与对话的归属":"Manage existing project, canvas and conversation ownership",
        "管理公司共享与部门专用密钥":"Manage company and department keys", "管理平台权限与维护操作":"Manage platform access and maintenance", "查看成员账号的操作记录":"View member activity",
        "＋ 新建用户":"＋ New User", "新建用户":"New User", "新建部门":"New Department", "＋ 新建部门":"＋ New Department", "当前管理分组":"Administration section",
        "搜索成员":"Search members", "搜索成员…":"Search members…", "全部部门":"All departments", "未分配部门":"Unassigned", "按部门筛选":"Filter by department", "筛选":"Filters",
        "状态":"Status", "正常用户":"Active users", "全部用户":"All users", "已停用用户":"Disabled users", "系统角色":"System role", "全部角色":"All roles", "超级管理员":"Super Administrator", "管理员":"Administrator", "普通成员":"Member",
        "排序":"Sort", "最近登录优先":"Recent login", "创建时间最新":"Newest first", "用户名 A-Z":"Username A–Z", "状态（正常优先）":"Status (active first)", "重置筛选":"Reset filters", "部门职责":"Department role", "部门负责人":"Department manager",
        "正常":"Active", "停用":"Disabled", "已停用":"Disabled", "编辑":"Edit", "取消":"Cancel", "保存":"Save", "确认":"Confirm", "关闭":"Close", "刷新":"Refresh",
        "← 返回成员列表":"← Back to members", "所属部门":"Department", "账号状态":"Account status", "账号信息":"Account information", "创建时间":"Created", "最后登录":"Last login", "编辑名称":"Edit name", "变更系统角色":"Change role", "重置密码":"Reset password", "停用账号":"Disable account", "启用账号":"Enable account", "影响预览":"Impact preview", "移出部门":"Remove from department",
        "查看成员":"View members", "未设置":"Not set", "暂无部门":"No departments", "部门名称":"Department name", "成员数量":"Members", "部门归属已更新":"Department updated", "查看成员 ":"View member ",
        "没有符合当前筛选条件的成员":"No members match these filters", "请调整状态、角色或搜索关键词":"Adjust the filters or search terms",
        "用户名":"Username", "显示名称（可选）":"Display name (optional)", "初始密码（至少6位）":"Initial password (at least 6 characters)", "高级设置":"Advanced settings", "账号角色":"Account role", "当前超级管理员密码":"Current super administrator password", "当前账号密码（仅本次验证，不会保存）":"Current password (verification only)", "操作原因":"Reason", "确认变更":"Confirm change", "目标用户":"User", "新密码（至少6位）":"New password (at least 6 characters)", "展示名":"Display name", "编辑展示名":"Edit display name", "确认保存":"Save changes",
        "变更成员角色":"Change member role", "变更原因":"Reason", "确认用户名":"Confirm username", "停用原因":"Reason for disabling", "启用原因":"Reason for enabling", "确认操作":"Confirm", "当前归属":"Owner", "分配用户":"Assign user", "选择用户":"Select user", "— 选择用户 —":"— Select user —", "分配":"Assign", "项目名称":"Project name", "项目 ID":"Project ID", "画布数量":"Canvases", "画布名称":"Canvas name", "画布 ID":"Canvas ID", "对话标题":"Conversation", "对话 ID":"Conversation ID", "文件目录":"Folder", "消息数":"Messages",
        "项目归属管理":"Project ownership", "画布归属管理":"Canvas ownership", "对话归属管理":"Conversation ownership", "暂无对话":"No conversations", "全局功能开关":"Global feature controls", "用户权限覆盖":"User access overrides", "全局允许":"Enabled", "全局禁止":"Disabled", "启用":"Enable", "禁用":"Disable", "仅超级管理员可修改":"Super administrator only", "暂无功能开关":"No feature controls", "权限开关已更新":"Feature controls updated", "选择用户以查看权限覆盖":"Select a user to view access overrides",
        "API 设置访问":"API Settings access", "工作流设置访问":"Workflow Settings access", "RunningHub 生成功能":"RunningHub generation", "视频生成功能":"Video generation", "图片工具生成功能":"Image tool generation", "素材库管理":"Asset Library management", "历史记录删除":"Delete generation history", "本地资源管理":"Local resource management", "系统更新":"System updates", "项目主页跳转":"Project homepage link",
        "控制首页项目主页按钮是否可打开企业版 GitHub 仓库，对所有账号统一生效；刷新首页后应用。":"Allow the homepage button to open the enterprise GitHub repository for all accounts. Refresh the homepage to apply.",
        "普通功能保留管理员放行；项目主页跳转对所有账号统一生效；系统更新须开启全局开关并由超级管理员执行。":"Administrators retain access to regular features. The project homepage setting applies to all accounts. System updates require the global switch and the current super administrator.",
        "为选中用户设置 inherit / allow / deny；inherit 表示继承全局默认值。":"Choose inherit, allow or deny for the selected user. Inherit uses the global default.",
        "新增密钥":"Add Key", "新增渠道密钥":"Add Channel Key", "密钥名称":"Key name", "调用平台":"API platform", "请选择调用平台":"Select an API platform", "使用范围":"Access scope", "公司共享":"Company shared", "专用":" only", "采购来源":"Procurement", "公司采购":"Company purchased", "部门自购":"Department purchased", "供应商账号标识":"Provider account reference", "名称 / 供应商":"Name / Provider", "操作":"Actions", "授权员工":"Authorize members", "更换密钥":"Replace key", "更换渠道密钥":"Replace Channel Key", "新 API Key":"New API Key", "已启用":"Enabled", "允许使用":"Allow access", "取消授权":"Revoke access", "员工":"Member", "权限":"Access", "已授权":"Authorized", "未授权":"Not authorized", "原部门":"Original department",
        "正在读取渠道密钥…":"Loading channel keys…", "尚未配置渠道密钥":"No channel keys configured", "调用平台沿用 API 设置；公司共享和部门专用分别授权。":"Platforms use API Settings; company and department keys have separate access grants.", "平台地址、协议和模型沿用 API 设置；这里只添加对应账户的密钥。":"Address, protocol and models use API Settings. Enter only the account key here.", "选择系统管理员在 API 设置中维护的平台。":"Choose a platform maintained by an administrator in API Settings.", "暂无已接通渠道密钥的平台，请先由系统管理员在 API 设置中配置贞贞 HTTP 平台。":"No supported platform is configured. Ask an administrator to add a Zhenzhen HTTP platform in API Settings.", "先选择调用平台":"Select a platform first", "只影响后续新任务；已受理任务继续使用原身份查询。":"Applies to new tasks; accepted tasks keep their original identity.", "已受理任务仍按原身份续查。":"Accepted tasks keep their original identity.",
        "正在读取成员…":"Loading members…", "正在读取部门…":"Loading departments…", "正在读取…":"Loading…", "在线更新":"Online updates", "选择目标版本":"Target version", "升级状态":"Update status", "刷新状态":"Refresh status", "更新到新版本":"Update", "重新检查":"Check again", "诊断与脱敏日志":"Diagnostics and redacted logs", "关键字":"Keyword", "全部级别":"All levels", "刷新日志":"Refresh logs", "导出 ZIP":"Export ZIP", "暂无日志":"No logs", "操作完成":"Done"
    };
    const key=text=>'admin.ui.'+text;
    StudioI18n.register(Object.fromEntries(Object.entries(phrases).map(([zh,en])=>[key(zh),{zh,en}])));
    const original=new Map(Object.entries(phrases).map(([zh,en])=>[en,zh]));
    window.adminT=text=>{const zh=original.get(text) || text;return Object.hasOwn(phrases,zh) ? StudioI18n.t(key(zh)) : text;};
    window.adminTF=(text,values)=>adminT(text).replace(/\{(\w+)\}/g,(_,name)=>String(values[name]));
    window.AdminI18n={
        apply(root=document){
            root.querySelectorAll('[data-i18n]').forEach(el=>{el.textContent=StudioI18n.t(el.dataset.i18n);});
        },
        count(n,zh,en){return StudioI18n.lang()==='en'?`${n} ${en}`:`${n} ${zh}`;}
    };
    window.addEventListener('studio-lang-change',()=>{
        document.title=adminT('管理后台 · 无限画布企业版');
        const tab=document.querySelector('.tab-btn.active');
        const name=document.getElementById('adminContent')?.dataset.tab;
        if(tab && name) AdminNavigation.update(name,tab);
        if(window.AdminMembers?.model && !AdminMembers.editing) renderUsers();
        if(name==='features') {renderFeatureFlags();renderFeatureUserSelect();if(document.getElementById('featureUserSelect').value)renderFeatureOverrides();}
        AdminI18n.apply();
    });
})();
