/* Member presentation and selection state. Writes use existing administration services. */
window.AdminMembers = {
    selected: null, editing: false, model: null, listScroll: 0,
    initialize(actions) {
        this.actions = actions;
        document.getElementById('userTable').onclick = event => {
            const row = event.target.closest('[data-member-row]');
            if (row) this.open(row.dataset.memberRow);
        };
        document.getElementById('departmentTable').onclick = event => {
            const button = event.target.closest('[data-department-members]');
            if (!button) return;
            document.getElementById('membersTab').click();
            document.getElementById('memberDepartmentFilter').value = button.dataset.departmentMembers;
            actions.filter();
        };
        document.getElementById('memberInspector').onclick = event => {
            const button = event.target.closest('[data-member-action]');
            if (button) this.action(button.dataset.memberAction);
        };
        document.getElementById('memberFilterReset').onclick = () => {
            document.getElementById('memberSearchInput').value = '';
            document.getElementById('memberDepartmentFilter').value = '';
            document.getElementById('memberStatusFilter').value = 'active';
            document.getElementById('memberRoleFilter').value = 'all';
            document.getElementById('memberSortMode').value = 'last_login';
            actions.filter();
        };
    },
    departmentMember(id) { return this.model.departmentData?.members.find(m => m.id === id); },
    departmentName(id) { return this.model.departmentData?.departments.find(d => d.id === id)?.name || adminT('未分配部门'); },
    render(model) {
        this.model = model;
        const select = document.getElementById('memberDepartmentFilter'), value = select.value;
        const departments = model.departmentData?.departments || [];
        const choices = [['',adminT('全部部门')],['none',adminT('未分配部门')],...departments.map(d => [d.id,d.name])];
        const key = JSON.stringify(choices);
        if (select.dataset.options !== key) {
            select.innerHTML = choices.map(([id,name]) => `<option value="${escapeHtml(id)}">${escapeHtml(name)}</option>`).join('');
            select.value = choices.some(([id]) => id === value) ? value : '';
            select.dataset.options = key;
        }
        select.hidden = !model.departmentData;
        document.getElementById('userCount').textContent = model.visibleCount === model.allUsers.length ? `${model.visibleCount} ${adminT('位成员')}` : `${model.visibleCount} / ${model.allUsers.length} ${adminT('位成员')}`;
        document.getElementById('memberPagination').hidden = model.page.totalPages === 1;
        document.getElementById('memberPaginationBottom').hidden = model.page.totalPages === 1;
        const changed = [document.getElementById('memberStatusFilter').value !== 'active',document.getElementById('memberRoleFilter').value !== 'all',document.getElementById('memberSortMode').value !== 'last_login'].filter(Boolean).length;
        document.querySelector('#memberFilters>summary').dataset.count = changed ? String(changed) : '';
        if (this.selected && !model.allUsers.some(u => u.id === this.selected)) { this.selected = null; this.editing = false; }
        this.drawRows(); this.drawDetail(); this.drawDepartments();
    },
    drawRows() {
        const model = this.model;
        document.getElementById('userTable').innerHTML = model.rows.map(user => {
            const membership = this.departmentMember(user.id), active = boolFlag(user.is_active);
            const name = user.display_name || user.username;
            return `<tr data-member-row="${escapeHtml(user.id)}" aria-selected="${this.selected === user.id}" class="${active ? '' : 'disabled-user-row'}">
                <td><button class="member-open" type="button" aria-label="${adminT('查看成员 ')}${escapeHtml(name)}"><strong>${escapeHtml(name)}</strong>${user.display_name && user.display_name !== user.username ? `<small>${escapeHtml(user.username)}</small>` : ''}</button></td>
                <td title="${escapeHtml(this.departmentName(membership?.department_id))}">${escapeHtml(this.departmentName(membership?.department_id))}</td>
                <td class="member-system-role">${escapeHtml(rolePresentation(user).label)}</td>
                <td class="member-duty">${membership?.manager ? adminT('部门负责人') : adminT('普通成员')}</td>
                <td><span class="member-status-mark ${active ? '' : 'disabled'}">${active ? adminT('正常') : adminT('停用')}</span><svg class="member-row-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg></td></tr>`;
        }).join('') || `<tr><td colspan="5" style="text-align:center;height:130px;color:var(--muted)">${adminT('没有符合当前筛选条件的成员')}<br><small>${adminT('请调整状态、角色或搜索关键词')}</small></td></tr>`;
    },
    open(id) {
        if (!this.selected) this.listScroll = window.scrollY;
        this.selected = id; this.editing = false;
        document.getElementById('memberFilters').open = false;
        this.drawRows(); this.drawDetail();
        document.getElementById('memberDetailBack').focus({preventScroll:true});
    },
    close() {
        this.selected = null; this.editing = false; this.drawRows(); this.drawDetail();
        window.scrollTo({top:this.listScroll,behavior:'instant'});
    },
    drawDetail() {
        const panel = document.getElementById('memberInspector'), workspace = document.getElementById('membersWorkspace');
        const user = this.model?.allUsers.find(u => u.id === this.selected);
        panel.hidden = !user; workspace.classList.toggle('has-selection', Boolean(user));
        document.getElementById('adminContent').classList.toggle('has-member-selection',Boolean(user));
        if (!user) { panel.replaceChildren(); return; }
        const membership = this.departmentMember(user.id), name = user.display_name || user.username;
        const canEditDepartment = Boolean(this.model.departmentData?.company_admin);
        const button = (action,label) => `<button type="button" class="row-btn" data-member-action="${action}">${adminT(label)}</button>`;
        const field = (label,value) => `<div><dt>${adminT(label)}</dt><dd>${escapeHtml(value)}</dd></div>`;
        panel.innerHTML = `<div class="member-detail-head"><button class="member-text-button" id="memberDetailBack" data-member-action="back">${adminT('← 返回成员列表')}</button>${canEditDepartment && !this.editing ? button('edit',adminT('编辑')) : ''}</div>
            <h2>${escapeHtml(name)}</h2><p class="member-handle">${escapeHtml(user.username)}</p>`;
        if (this.editing) {
            panel.insertAdjacentHTML('beforeend',`<form class="member-edit-form"><label>${adminT('所属部门')}<select name="department_id"><option value="">${adminT('未分配部门')}</option>${this.model.departmentData.departments.map(d => `<option value="${escapeHtml(d.id)}" ${d.id === membership?.department_id ? 'selected' : ''}>${escapeHtml(d.name)}</option>`).join('')}</select></label>
                <label>${adminT('部门职责')}<select name="manager"><option value="false">${adminT('普通成员')}</option><option value="true" ${membership?.manager ? 'selected' : ''}>${adminT('部门负责人')}</option></select></label>
                <p role="status" aria-live="polite"></p><footer><button class="action-btn" type="button" data-member-action="cancel">${adminT('取消')}</button><button class="action-btn primary" type="submit">${adminT('保存')}</button></footer></form>`);
            const form = panel.querySelector('form'), id = user.id;
            const department = form.elements.department_id, manager = form.elements.manager;
            department.onchange = () => { manager.disabled = !department.value; if (!department.value) manager.value = 'false'; };
            department.onchange();
            form.onsubmit = async event => {
                event.preventDefault();
                const values = Object.fromEntries(new FormData(form)), submit = form.querySelector('[type=submit]');
                submit.disabled = true;
                try {
                    await this.actions.saveDepartment(id,values.department_id,values.manager === 'true');
                    if (this.selected === id) this.editing = false;
                    await this.actions.reload(); showToast(adminT('部门归属已更新'));
                } catch (error) { form.querySelector('[role=status]').textContent = error.message; submit.disabled = false; }
            };
            return;
        }
        const canManage = this.actions.canManage(user), canRole = this.actions.canChangeRole(user);
        panel.insertAdjacentHTML('beforeend',`<dl class="member-detail-fields">${field(adminT('所属部门'),this.departmentName(membership?.department_id))}${field(adminT('系统角色'),rolePresentation(user).label)}${field(adminT('部门职责'),membership?.manager ? adminT('部门负责人') : adminT('普通成员'))}${field(adminT('账号状态'),boolFlag(user.is_active) ? adminT('正常') : adminT('已停用'))}</dl><details class="member-secondary-info"><summary>${adminT('账号信息')}</summary><dl class="member-detail-fields">${field(adminT('创建时间'),fmtDate(user.created_at))}${field(adminT('最后登录'),fmtDate(user.last_login))}</dl></details>
            <div class="member-detail-actions">${canManage ? button('profile',adminT('编辑名称')) : ''}${canRole ? button('role',adminT('变更系统角色')) : ''}${canManage ? button('password',adminT('重置密码')) + button('active',boolFlag(user.is_active) ? adminT('停用账号') : adminT('启用账号')) + button('impact',adminT('影响预览')) : ''}${!this.model.departmentData?.company_admin && membership?.department_id && !membership.manager ? button('remove',adminT('移出部门')) : ''}</div>`);
    },
    action(action) {
        const user = this.model?.allUsers.find(u => u.id === this.selected);
        if (action === 'back') { this.close(); return; }
        if (!user) return;
        if (action === 'edit') { this.editing = true; this.drawDetail(); return; }
        if (action === 'cancel') { this.editing = false; this.drawDetail(); return; }
        this.actions[action]?.(user);
    },
    drawDepartments() {
        if (!this.model) return;
        const data = this.model.departmentData;
        document.getElementById('departmentTable').innerHTML = (data?.departments || []).map(department => {
            const members = data.members.filter(m => m.department_id === department.id);
            const managers = members.filter(m => m.manager).map(m => m.display_name || m.username).join('、') || adminT('未设置');
            return `<tr><td>${escapeHtml(department.name)}</td><td>${members.length}</td><td>${escapeHtml(managers)}</td><td><button class="row-btn" data-department-members="${escapeHtml(department.id)}">${adminT('查看成员')}</button></td></tr>`;
        }).join('') || `<tr><td colspan="4" style="text-align:center;height:120px;color:var(--muted)">${adminT('暂无部门')}</td></tr>`;
        document.getElementById('departmentCount').textContent = `${data?.departments.length || 0} ${adminT('个部门')}`;
    }
};
