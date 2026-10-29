/* Credential administration uses the existing admin components and policy API. */
window.DepartmentCredentials = {
    rows: [], providers: [], providerError: '',
    initialize() {
        const tab = document.getElementById('departmentCredentialsTab');
        tab.hidden = !DepartmentMembers.data;
        document.getElementById('credentialCreate').onclick = () => this.create()
            .catch(error => showToast('平台列表读取失败：' + error.message, 'error'));
        document.getElementById('credentialRefresh').onclick = () => this.load();
        document.getElementById('credentialTable').onclick = event => {
            const button = event.target.closest('[data-credential-action]');
            if (button) this.action(button.dataset.credentialAction, button.dataset.id)
                .catch(error => showToast(error.message, 'error'));
        };
    },
    async loadProviders() {
        const config = await apiFetch('/api/config');
        this.providers = (config.api_providers || []).map(provider => ({
            id:provider.id, name:provider.name || provider.id, enabled:provider.enabled !== false,
            supported:provider.managed_source_supported === true
        }));
        this.providerError = '';
        return this.providers;
    },
    providerLabel(id) {
        const provider = this.providers.find(item => item.id === id);
        if (!provider) return `${this.providerError ? '平台信息暂不可用' : '未匹配平台'}（${id}）`;
        return `${provider.name}${provider.enabled ? '' : ' · 已停用'}${provider.supported ? '' : ' · 暂未接通渠道密钥'}`;
    },
    async load() {
        const status = document.getElementById('credentialStatus');
        status.textContent = adminT('正在读取渠道密钥…');
        try {
            const [rows] = await Promise.all([apiFetch('/enterprise/api/business/sources?manage=true'),
                this.loadProviders().catch(error => { this.providers = []; this.providerError = error.message; })]);
            this.rows = rows;
            const departments = DepartmentMembers.data.departments;
            document.getElementById('credentialTable').innerHTML = this.rows.map(source => {
                const scope = source.scope === 'company' ? adminT('公司共享') :
                    (departments.find(d => d.id === source.department_id)?.name || adminT('原部门')) + adminT('专用');
                const button = (action, text) => `<button class="row-btn" data-credential-action="${action}" data-id="${escapeHtml(source.id)}">${text}</button>`;
                return `<tr><td><strong>${escapeHtml(source.name)}</strong><div class="sub">${escapeHtml(this.providerLabel(source.provider_id))}</div></td><td>${escapeHtml(scope)}</td><td>${source.enabled ? adminT('已启用') : adminT('已停用')}</td><td>${button('grants', adminT('授权员工'))} ${button('rotate', adminT('更换密钥'))} ${button('toggle', source.enabled ? adminT('停用') : adminT('启用'))}</td></tr>`;
            }).join('') || '<tr><td colspan="4" style="text-align:center;padding:32px">尚未配置渠道密钥</td></tr>';
            status.textContent = this.providerError ? '平台信息暂不可用，可刷新重试；已有密钥仍可维护。' :
                adminT('调用平台沿用 API 设置；公司共享和部门专用分别授权。');
        } catch (error) {
            this.rows = [];
            document.getElementById('credentialTable').replaceChildren();
            status.textContent = error.message;
        }
    },
    field(name, label, options = {}) {
        const control = options.choices ? `<select name="${name}" aria-label="${escapeHtml(label)}" ${options.required ? 'required' : ''}>${options.choices.map(([id, text, disabled]) => `<option value="${escapeHtml(id)}" ${disabled ? 'disabled' : ''}>${escapeHtml(text)}</option>`).join('')}</select>` :
            `<input name="${name}" aria-label="${escapeHtml(label)}" type="${options.secret ? 'password' : 'text'}" required maxlength="${options.secret ? 8192 : 160}" autocomplete="${options.secret ? 'new-password' : 'off'}" ${options.placeholder ? `placeholder="${escapeHtml(options.placeholder)}"` : ''}>`;
        return `<label class="field"><span class="label">${label}</span><div class="field-frame">${control}</div></label>`;
    },
    form(title, body, submit) {
        return DepartmentMembers.form(title, body, async values => {
            try { await submit(values); await this.load(); }
            finally { document.querySelectorAll('.modal-backdrop input[type=password]').forEach(input => { input.value = ''; }); }
        });
    },
    async create() {
        await this.loadProviders();
        const available = this.providers.filter(provider => provider.enabled);
        const context = DepartmentMembers.data;
        const scopes = [...(context.company_admin ? [['company', adminT('公司共享')]] : []),
            ...context.departments.map(d => [d.id, d.name + adminT('专用')])];
        const form = this.form(adminT('新增渠道密钥'), this.field('provider_id', adminT('调用平台'), {required:true,
            choices:[['', adminT('请选择调用平台')], ...available.map(provider => [provider.id,
                `${provider.name}（${provider.id}）${provider.supported ? '' : ' · 暂未接通渠道密钥'}`, !provider.supported])]}) +
            '<p class="credential-platform-help" data-platform-help></p>' +
            this.field('name', adminT('密钥名称')) +
            this.field('scope', adminT('使用范围'), {choices: scopes}) +
            this.field('procurement', adminT('采购来源'), {choices: [['company', adminT('公司采购')], ['department', adminT('部门自购')]]}) +
            this.field('account_ref', adminT('供应商账号标识'), {placeholder: '英文、数字或短横线，例如 design-main'}) +
            this.field('secret', 'API Key', {secret: true}) +
            '<p class="sub">新增会建立独立来源，不覆盖现有密钥；保存后请在列表中授权员工。已有来源换新 Key 请使用“更换密钥”。</p><p class="sub" data-duplicate-help role="status"></p>', values => apiFetch('/enterprise/api/business/sources', {
                method: 'POST', body: JSON.stringify({...values, scope: values.scope === 'company' ? 'company' : 'department',
                    department_id: values.scope === 'company' ? null : values.scope})
            }));
        const scope = form.querySelector('[name=scope]'), procurement = form.querySelector('[name=procurement]');
        const platform = form.querySelector('[name=provider_id]'), key = form.querySelector('[name=secret]');
        const save = form.querySelector('[type=submit]'), help = form.querySelector('[data-platform-help]');
        const account = form.querySelector('[name=account_ref]'), duplicate = form.querySelector('[data-duplicate-help]');
        const updateDuplicate = () => {
            const matching = this.rows.some(row => row.provider_id === platform.value && row.account_ref === account.value.trim() &&
                (scope.value === 'company' ? row.scope === 'company' : row.scope === 'department' && row.department_id === scope.value));
            duplicate.textContent = matching ? '此平台、范围和账号标识已有来源；如需替换现有 Key，请取消并在列表选择“更换密钥”。继续保存会新增独立来源。' : '';
        };
        platform.onchange = () => {
            const selected = available.find(provider => provider.id === platform.value && provider.supported);
            save.disabled = !selected; key.disabled = !selected;
            key.placeholder = selected ? `填写${selected.name}的 API Key` : adminT('先选择调用平台');
            help.textContent = selected ? adminT('平台地址、协议和模型沿用 API 设置；这里只添加对应账户的密钥。') :
                available.some(provider => provider.supported) ? adminT('选择系统管理员在 API 设置中维护的平台。') :
                adminT('暂无已接通渠道密钥的平台，请先由系统管理员在 API 设置中配置贞贞 HTTP 平台。');
            updateDuplicate();
        };
        platform.onchange();
        scope.onchange = () => {
            const company = scope.value === 'company';
            procurement.querySelector('[value=department]').disabled = company;
            if (company) procurement.value = 'company';
            updateDuplicate();
        };
        account.addEventListener('input', updateDuplicate);
        scope.onchange();
    },
    async action(action, id) {
        const source = this.rows.find(row => row.id === id);
        if (!source) return;
        const path = '/enterprise/api/business/sources/' + encodeURIComponent(id);
        if (action === 'rotate') this.form(adminT('更换渠道密钥'), '<p class="sub">来源：' + escapeHtml(source.name) + ' · ' + escapeHtml(this.providerLabel(source.provider_id)) + '</p>' + this.field('secret', adminT('新 API Key'), {secret: true}) +
            '<p class="sub">保留现有来源和授权，只影响后续新任务；已受理任务继续使用原身份查询。旧密钥若已被供应商停用，原任务可能需要人工核对。</p>', values => apiFetch(path + '/secret', {
                method: 'PUT', body: JSON.stringify({expected_revision: source.current_revision, secret: values.secret})
            }));
        if (action === 'toggle') this.form(source.enabled ? '停用渠道密钥' : '启用渠道密钥',
            '<p class="sub">已受理任务仍按原身份续查。</p>', () => apiFetch(path + '/enabled', {
                method: 'PUT', body: JSON.stringify({enabled: !source.enabled})
            }));
        if (action === 'grants') {
            const [directory, grants] = await Promise.all([apiFetch('/enterprise/api/business/directory'), apiFetch(path + '/grants')]);
            const granted = new Set(grants.map(g => g.user_id));
            const members = directory.filter(user => source.scope === 'company' || user.department_id === source.department_id);
            if (!members.length) { showToast('请先在成员管理中设置部门成员', 'error'); return; }
            const scope = source.scope === 'company' ? '公司共享' : (DepartmentMembers.data.departments.find(d => d.id === source.department_id)?.name || '所属部门') + '专用';
            this.form(adminT('授权员工'), '<p class="sub">正在设置：' + escapeHtml(source.name) + ' · ' + escapeHtml(this.providerLabel(source.provider_id)) + ' · ' + escapeHtml(scope) + (source.enabled ? ' · 已启用' : ' · 已停用') + '</p><p class="sub">授权只作用于此条密钥；添加密钥后，需要为实际使用的账号分别授权并保存。</p>' + this.field('user_id', adminT('员工'), {choices: members.map(user => [user.id,
                user.display_name + (granted.has(user.id) ? ' · 已授权' : ' · 未授权')])}) +
                this.field('allowed', adminT('权限'), {choices: [['true', adminT('允许使用')], ['false', adminT('取消授权')]]}), values => apiFetch(
                    path + '/grants/' + encodeURIComponent(values.user_id), {method: 'PUT', body: JSON.stringify({allowed: values.allowed === 'true'})}));
        }
    }
};
