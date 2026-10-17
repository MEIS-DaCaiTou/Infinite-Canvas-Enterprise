/* Personal model shortcuts. Enterprise provider configuration stays unchanged. */
(function () {
    let favorites = new Set();
    let view = 'all';
    let loaded = false;
    let saveQueue = Promise.resolve();
    let message = '';
    const ready = fetch('/enterprise/api/me/model-preferences', {cache:'no-store'}).then(async response => {
        if(!response.ok) throw new Error('请先登录后设置我的模型');
        const stored = await response.json();
        favorites = new Set(stored.favorites || []);
        view = stored.view === 'favorites' ? 'favorites' : 'all';
        loaded = true;
    }).catch(error => {message = error.message;}).then(refreshAll);

    function key(config, model) { return JSON.stringify([config.kind, config.getProvider(), model]); }
    function isFavorite(config, model) { return favorites.has(key(config, model)); }
    function save() {
        const body = JSON.stringify({favorites:[...favorites], view});
        message = '正在保存个人模型设置…';
        refreshAll();
        saveQueue = saveQueue.catch(() => {}).then(async () => {
            if(!loaded) throw new Error('请先登录后设置我的模型');
            const response = await fetch('/enterprise/api/me/model-preferences', {method:'PUT', headers:{'Content-Type':'application/json'}, body});
            if(!response.ok) throw new Error('个人模型设置保存失败，请重新登录或重试');
            message = '';
        }).catch(error => {message = error.message;}).then(refreshAll);
        return saveQueue.then(() => !message);
    }
    function refreshAll() {
        document.querySelectorAll('.model-picker-tools').forEach(el => el.refreshModels());
    }
    function tools(config, refresh) {
        const el = document.createElement('div');
        el.className = 'model-picker-tools';
        el.style.cssText = 'display:flex;gap:4px;align-items:center;margin:4px 0;min-width:0';
        const search = document.createElement('input');
        search.type = 'search';
        search.placeholder = '搜索模型';
        search.setAttribute('aria-label', '搜索模型');
        search.className = 'select-lite';
        search.style.cssText = 'width:0;flex:1;min-width:70px;font-size:11px';
        const scope = document.createElement('select');
        scope.className = 'select-lite';
        scope.setAttribute('aria-label', '模型范围');
        scope.innerHTML = '<option value="all">全部</option><option value="favorites">常用</option>';
        const star = document.createElement('button');
        star.type = 'button';
        star.className = 'select-lite';
        const manage = document.createElement('button');
        manage.type = 'button'; manage.className = 'select-lite'; manage.textContent = '我的模型';
        const notice = document.createElement('span');
        notice.setAttribute('role','status'); notice.style.cssText = 'font-size:10px;flex-basis:100%;color:#b45309';
        el.style.flexWrap = 'wrap';
        el.append(search, scope, star, manage, notice);
        for(const event of ['mousedown', 'click', 'keydown']) el.addEventListener(event, e => e.stopPropagation());
        el.refreshModels = () => {
            scope.value = view;
            const selected = config.getSelected();
            const starred = isFavorite(config, selected);
            star.textContent = starred ? '★' : '☆';
            star.setAttribute('aria-label', starred ? '取消常用模型' : '设为常用模型');
            star.setAttribute('aria-pressed', String(starred));
            star.disabled = !selected || !loaded;
            star.title = '当前账号的个人模型列表';
            manage.disabled = !loaded;
            scope.disabled = !loaded;
            notice.textContent = message;
            notice.hidden = !message;
            refresh(search.value.trim().toLowerCase());
        };
        search.oninput = el.refreshModels;
        scope.onchange = () => { view = scope.value; save(); };
        star.onclick = () => {
            const id = key(config, config.getSelected());
            if(favorites.has(id)) favorites.delete(id); else favorites.add(id);
            save();
        };
        manage.onclick = () => openPersonalModels(config);
        ready.then(() => el.refreshModels());
        return el;
    }
    function openPersonalModels(config) {
        const dialog = document.createElement('dialog');
        dialog.className = 'comfy-text-dialog personal-model-dialog';
        dialog.setAttribute('aria-labelledby', 'personalModelTitle');
        dialog.innerHTML = `<div class="comfy-text-head">
            <div class="comfy-text-heading"><span class="comfy-text-heading-icon"><i data-lucide="list-checks"></i></span>
                <div><h3 id="personalModelTitle" class="comfy-text-title">我的模型</h3><div class="comfy-text-subtitle">选择日常使用的模型，仅对当前账号生效</div></div></div>
            <button type="button" class="comfy-text-close" data-action="close" aria-label="关闭我的模型"><i data-lucide="x"></i></button></div>
            <div class="personal-model-content"><label class="personal-model-search"><i data-lucide="search"></i><input type="search" aria-label="搜索个人模型" placeholder="搜索模型名称"></label>
            <div class="personal-model-toolbar"><span data-selection-count role="status"></span><div><button type="button" data-action="all">全选搜索结果</button><button type="button" data-action="none">清除搜索结果</button></div></div>
            <div data-model-list class="personal-model-list"></div><div data-empty class="personal-model-empty" hidden>没有匹配的模型，试试其他关键词</div></div>
            <div class="comfy-text-footer"><span class="personal-model-hint">保存后默认显示常用模型，已有节点保持不变</span><div class="comfy-text-actions"><button type="button" class="comfy-text-btn" data-action="cancel">取消</button><button type="button" class="comfy-text-btn primary" data-action="save">保存选择</button></div></div>
            <p data-save-error class="comfy-text-status" role="status"></p>`;
        const list = dialog.querySelector('[data-model-list]');
        const rows = [...new Set(config.getModels())].map(model => {
            const row = document.createElement('label');
            row.className = 'personal-model-row';
            const input = document.createElement('input'); input.type = 'checkbox'; input.checked = isFavorite(config,model);
            const text = document.createElement('span'); text.textContent = model;
            row.append(input,text); list.append(row);
            return {model,row,input};
        });
        const updateSelection = () => {
            dialog.querySelector('[data-selection-count]').textContent = `已选 ${rows.filter(({input}) => input.checked).length} / ${rows.length}`;
            dialog.querySelector('[data-empty]').hidden = rows.some(({row}) => !row.hidden);
            for(const {row,input} of rows) row.classList.toggle('selected', input.checked);
        };
        list.addEventListener('change', updateSelection);
        dialog.querySelector('input[type=search]').oninput = event => {
            const query = event.target.value.trim().toLowerCase();
            rows.forEach(({model,row}) => {row.hidden = !model.toLowerCase().includes(query);});
            updateSelection();
        };
        for(const [action,checked] of [['all',true],['none',false]]) {
            dialog.querySelector(`[data-action=${action}]`).onclick = () => {
                rows.filter(({row}) => !row.hidden).forEach(({input}) => {input.checked=checked;});
                updateSelection();
            };
        }
        dialog.querySelector('[data-action=cancel]').onclick = () => dialog.close();
        dialog.querySelector('[data-action=close]').onclick = () => dialog.close();
        dialog.querySelector('[data-action=save]').onclick = async () => {
            const button = dialog.querySelector('[data-action=save]'); button.disabled = true;
            rows.forEach(({model,input}) => {const id = key(config,model); if(input.checked) favorites.add(id); else favorites.delete(id);});
            view = 'favorites';
            const saved = await save();
            if(saved) dialog.close();
            else {button.disabled = false; dialog.querySelector('[data-save-error]').textContent = message;}
        };
        dialog.addEventListener('close',() => dialog.remove());
        for(const event of ['mousedown','click','keydown']) dialog.addEventListener(event,e => e.stopPropagation());
        updateSelection();
        document.body.append(dialog); dialog.showModal();
        window.lucide?.createIcons({root:dialog});
    }
    function visible(config, model, query) {
        return (!query || model.toLowerCase().includes(query)) && (view !== 'favorites' || isFavorite(config, model));
    }
    function mountSelect(select, config) {
        const controls = tools(config, query => {
            const selected = config.getSelected();
            const models = [...new Set(config.getModels())];
            const filtered = models.filter(model => visible(config, model, query));
            filtered.sort((a,b) => Number(isFavorite(config,b)) - Number(isFavorite(config,a)));
            // Keep the existing node model visible; filtering never edits a saved node.
            if(selected && !filtered.includes(selected)) filtered.unshift(selected);
            select.replaceChildren();
            for(const model of filtered) {
                const option = document.createElement('option');
                option.value = model;
                option.textContent = `${isFavorite(config, model) ? '★ ' : ''}${model}`;
                select.append(option);
            }
            if(!filtered.length) {
                const option = document.createElement('option');
                option.textContent = '没有匹配模型';
                option.value = '';
                option.disabled = true;
                select.append(option);
            }
            select.value = selected || '';
        });
        select.parentElement.after(controls);
        select.addEventListener('change', controls.refreshModels);
        config.providerSelect?.addEventListener('change', controls.refreshModels);
        return controls;
    }
    function mountList(list, config) {
        config.getModels = () => [...list.querySelectorAll('[data-smart-value]')].map(button => button.dataset.smartValue);
        const controls = tools(config, query => {
            let count = 0;
            list.querySelectorAll('[data-smart-value]').forEach(button => {
                button.hidden = !visible(config, button.dataset.smartValue, query);
                button.style.display = button.hidden ? 'none' : '';
                if(!button.hidden) count++;
            });
            empty.hidden = count > 0;
            empty.style.display = count > 0 ? 'none' : '';
        });
        const empty = document.createElement('div');
        empty.className = 'muted-note';
        empty.textContent = '没有匹配模型；可切换到全部，或将当前模型设为常用';
        list.append(empty);
        list.before(controls);
        controls.refreshModels();
    }
    function profileFor(provider, model) {
        return provider?.builtin_model_image_profiles?.[model] || provider?.model_image_profiles?.[model] || provider?.image_profile || {};
    }
    function imageParameters(source) {
        const ratios = {square:'1:1', portrait:'2:3', landscape:'3:2', portrait43:'3:4', landscape43:'4:3', story:'9:16', wide:'16:9', ultrawide:'21:9', ultratall:'9:21'};
        const ratio = source.ratio === 'custom' ? source.customRatio : source.ratio === 'source' ? '' : (ratios[source.ratio] || source.ratio);
        return {aspect_ratio:ratio || '', resolution:['512','1k','2k','4k'].includes(source.resolution) ? source.resolution.toUpperCase() : ''};
    }
    function preferredModel(kind, providerId, models) {
        return models.find(model => favorites.has(JSON.stringify([kind,providerId,model]))) || models[0] || '';
    }
    window.CanvasModelPicker = {mountSelect, mountList, profileFor, imageParameters, preferredModel};
})();
