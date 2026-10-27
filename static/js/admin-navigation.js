/* Navigation groups existing panels; authorization and their actions stay separate. */
window.AdminNavigation = {
    group: 'members',
    titles: {users:['成员','管理企业成员及所属部门'],departments:['部门','管理部门及成员归属'],
        projects:['资源归属','管理原有项目、画布与对话的归属'],canvases:['资源归属','管理原有项目、画布与对话的归属'],conversations:['资源归属','管理原有项目、画布与对话的归属'],
        credentials:['渠道密钥','管理公司共享与部门专用密钥'],features:['系统管理','管理平台权限与维护操作'],updates:['系统管理','管理平台权限与维护操作'],logs:['系统管理','查看成员账号的操作记录'],
        'comfy-queue':['算力与队列','管理 ComfyUI 算力、用户限额和工作流排队']},
    initialize(openTab) {
        for (const button of document.querySelectorAll('[data-admin-nav]')) {
            const group = button.dataset.adminNav;
            button.hidden = ![...document.querySelectorAll(`.tab-btn[data-admin-group="${group}"]`)].some(b => !b.hidden && b.style.display !== 'none');
            button.onclick = () => {
                const first = [...document.querySelectorAll(`.tab-btn[data-admin-group="${group}"]`)].find(b => !b.hidden && b.style.display !== 'none');
                if (first) first.click();
            };
            button.disabled = false;
        }
        this.update('users', document.getElementById('membersTab'));
    },
    update(name, button) {
        this.group = button.dataset.adminGroup;
        document.getElementById('adminSectionTabs').dataset.group = this.group;
        document.getElementById('adminContent').dataset.tab = name;
        document.querySelectorAll('[data-admin-nav]').forEach(b => {
            if (b.dataset.adminNav === this.group) b.setAttribute('aria-current','page'); else b.removeAttribute('aria-current');
        });
        const [title,description] = this.titles[name];
        document.getElementById('adminPageTitle').textContent = adminT(title);
        document.getElementById('adminPageDescription').textContent = adminT(description);
    }
};
