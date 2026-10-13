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
        dialog.style.cssText = 'border:1px solid #d1d5db;border-radius:14px;padding:20px;width:520px;max-width:90vw;max-height:80vh;color:#111827;background:white';
        dialog.innerHTML = '<h3 style="margin:0 0 6px">我的模型</h3><p style="font-size:12px;color:#64748b">勾选当前平台日常需要的模型，保存后默认显示个人列表。</p><input type="search" aria-label="搜索个人模型" placeholder="搜索模型名称" style="width:100%;padding:8px;box-sizing:border-box"><div style="display:flex;gap:8px;margin:8px 0"><button type="button" data-action="all">勾选搜索结果</button><button type="button" data-action="none">取消搜索结果</button></div><div data-model-list style="overflow:auto;max-height:42vh"></div><div data-save-error role="status" style="color:#b45309;font-size:12px"></div><div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px"><button type="button" data-action="cancel">取消</button><button type="button" data-action="save">保存我的模型</button></div>';
        const list = dialog.querySelector('[data-model-list]');
        const rows = [...new Set(config.getModels())].map(model => {
            const row = document.createElement('label');
            row.style.cssText = 'display:flex;gap:8px;padding:6px 0;overflow-wrap:anywhere';
            const input = document.createElement('input'); input.type = 'checkbox'; input.checked = isFavorite(config,model);
            const text = document.createElement('span'); text.textContent = model;
            row.append(input,text); list.append(row);
            return {model,row,input};
        });
        dialog.querySelector('input[type=search]').oninput = event => {
            const query = event.target.value.trim().toLowerCase();
            rows.forEach(({model,row}) => {row.hidden = !model.toLowerCase().includes(query); row.style.display = row.hidden ? 'none' : 'flex';});
        };
        for(const [action,checked] of [['all',true],['none',false]]) {
            dialog.querySelector(`[data-action=${action}]`).onclick = () => rows.filter(({row}) => !row.hidden).forEach(({input}) => {input.checked=checked;});
        }
        dialog.querySelector('[data-action=cancel]').onclick = () => dialog.close();
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
        document.body.append(dialog); dialog.showModal();
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
        });
        const empty = document.createElement('div');
        empty.className = 'muted-note';
        empty.textContent = '没有匹配模型；可切换到全部，或将当前模型设为常用';
        list.append(empty);
        list.before(controls);
        controls.refreshModels();
    }
    function profileFor(provider, model) {
        return provider?.model_image_profiles?.[model] || provider?.image_profile || {};
    }
    function imageParameters(source) {
        const ratios = {square:'1:1', portrait:'2:3', landscape:'3:2', portrait43:'3:4', landscape43:'4:3', story:'9:16', wide:'16:9', ultrawide:'21:9', ultratall:'9:21'};
        const ratio = source.ratio === 'custom' ? source.customRatio : source.ratio === 'source' ? '' : (ratios[source.ratio] || source.ratio);
        return {aspect_ratio:ratio || '', resolution:['1k','2k','4k'].includes(source.resolution) ? source.resolution.toUpperCase() : ''};
    }
    function preferredModel(kind, providerId, models) {
        return models.find(model => favorites.has(JSON.stringify([kind,providerId,model]))) || models[0] || '';
    }
    window.CanvasModelPicker = {mountSelect, mountList, profileFor, imageParameters, preferredModel};
})();
