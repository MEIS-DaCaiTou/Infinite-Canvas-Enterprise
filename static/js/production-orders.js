(() => {
    const endpoint = '/enterprise/api/me/production-orders';
    const taskEndpoint = '/enterprise/api/me/generation-tasks';
    const slots = { main: '商品主图', detail: '详情模块' };
    const statusNames = { queued: '已排队', running: '制作中', succeeded: '已完成', partial: '部分完成', failed: '失败', unknown: '待核对', cancelled: '已取消' };
    const element = id => document.getElementById(id);
    const query = new URLSearchParams(location.search);
    let order = null;
    let busy = false;
    let providers = [];
    let newOrderId = token();

    function token() {
        return Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');
    }

    function node(tag, label, className) {
        const item = document.createElement(tag);
        if (label) item.textContent = label;
        if (className) item.className = className;
        return item;
    }

    async function api(url, options) {
        const response = await fetch(url, {cache: 'no-store', ...options});
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            const message = [data.detail, data.message, data.error].find(value => typeof value === 'string');
            const error = new Error(message || (response.status === 422 ? '请输入有效的款号、颜色或制作要求' : '请求未完成，请刷新核对原记录'));
            error.status = response.status;
            throw error;
        }
        return data;
    }

    function post(url, data) {
        return api(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
    }

    function notice(message, isError = false) {
        const output = element('notice');
        output.textContent = message;
        output.toggleAttribute('data-error', isError);
    }

    async function act(fn) {
        if (busy) return;
        busy = true;
        element('orders').disabled = true;
        notice('');
        try {
            await fn();
        } catch (error) {
            notice(error.message, true);
        } finally {
            busy = false;
            element('orders').disabled = false;
        }
    }

    function button(label, handler) {
        const item = node('button', label);
        item.type = 'button';
        item.addEventListener('click', () => act(handler));
        return item;
    }

    function addReference() {
        const list = element('references');
        if (list.childElementCount >= 6) return;
        const row = node('div', '', 'reference');
        const color = node('input');
        color.required = true;
        color.maxLength = 48;
        color.placeholder = '颜色名称';
        color.setAttribute('aria-label', '颜色名称');
        const url = node('input');
        url.required = true;
        url.placeholder = '平台图片地址';
        url.setAttribute('aria-label', '参考图地址');
        const upload = node('input');
        upload.type = 'file';
        upload.accept = 'image/jpeg,image/png,image/webp';
        upload.hidden = true;
        const trigger = node('button', '上传参考图');
        trigger.type = 'button';
        trigger.addEventListener('click', () => upload.click());
        upload.addEventListener('change', () => act(async () => {
            if (!upload.files.length) return;
            const form = new FormData();
            form.append('files', upload.files[0]);
            const result = await api('/api/ai/upload', {method: 'POST', body: form});
            if (!result.files?.[0]?.url) throw new Error('参考图上传失败');
            url.value = result.files[0].url;
            notice('参考图已上传');
        }));
        row.append(color, url, trigger, upload);
        list.append(row);
        element('add').disabled = list.childElementCount >= 6;
    }

    async function loadOrders(id = '') {
        const rows = await api(endpoint);
        const chooser = element('orders');
        chooser.replaceChildren(new Option('选择生产单', ''));
        for (const row of rows) {
            chooser.add(new Option(row.style + ' · ' + row.title, row.id));
        }
        chooser.value = id;
        if (id) await openOrder(id);
    }

    async function openOrder(id) {
        order = id ? await api(endpoint + '/' + id) : null;
        element('order').hidden = !order;
        if (!order) {
            if (query.has('id')) {
                query.delete('id');
                history.replaceState(null, '', query.size ? '?' + query : location.pathname);
            }
            return;
        }
        if (query.get('id') !== order.id) {
            query.set('id', order.id);
            history.replaceState(null, '', '?' + query);
        }
        element('order-title').textContent = order.style + ' · ' + order.title;
        await displayOrder();
    }

    async function readTask(id) {
        if (!id) return null;
        try {
            return await api(taskEndpoint + '/' + id);
        } catch (error) {
            return { status: error.status === 404 ? 'unknown' : 'unavailable', items: [] };
        }
    }

    async function displayOrder() {
        const colors = element('colors');
        const views = await Promise.all(order.colors.map(async (color, index) => {
            const group = node('article', '', 'color');
            group.append(node('h3', color.name + (index === 0 ? ' · 代表色' : '')));
            if (color.asset?.url) {
                const reference = node('div', '', 'results source');
                reference.append(sample(color.asset.url, '本色参考图'));
                group.append(reference);
            }
            const grid = node('div', '', 'slots');
            const plates = await Promise.all(Object.keys(slots).map(name => displaySlot(index, name)));
            grid.append(...plates);
            group.append(grid);
            return group;
        }));
        colors.replaceChildren(...views);
        element('batch').disabled = !representativeApproved() || !batchSlots().length;
    }

    function representativeApproved() {
        return Object.values(order.colors[0].slots).every(slot => slot.approved);
    }

    function batchSlots() {
        return order.colors.flatMap((color, index) => {
            if (!index) return [];
            return Object.entries(color.slots).filter(([, slot]) => !slot.attempts.length)
                .map(([name]) => ({index, name}));
        });
    }

    async function displaySlot(index, name) {
        const slot = order.colors[index].slots[name];
        const latest = slot.attempts.at(-1);
        const task = latest?.dispatch !== 'rejected' ? await readTask(latest?.task_id) : null;
        const status = latest?.dispatch === 'rejected' ? '已拒绝' : statusNames[task?.status] || (latest ? '回执暂不可读' : '待制作');
        const plate = node('section', '', 'slot');
        plate.append(node('h3', slots[name]), node('p', status));
        if (latest) plate.append(node('small', latest.task_id));
        const ready = !latest || latest.dispatch === 'rejected' || ['failed', 'succeeded', 'cancelled'].includes(task?.status);
        const generate = button(latest ? '重做此图位' : '制作候选', () => submitOne(index, name));
        generate.disabled = !ready || (index > 0 && !representativeApproved());
        const controls = node('div', '', 'row');
        controls.append(generate);
        plate.append(controls);
        const gallery = node('div', '', 'results');
        if (slot.approved) {
            gallery.append(sample(slot.approved.asset.url, '已批准'));
        }
        for (const [position, item] of (task?.items || []).filter(item => item.kind === 'image').entries()) {
            const figure = sample(item.url, '候选 ' + (position + 1));
            figure.lastElementChild.append(
                button('批准此图', async () => {
                    order = await post(slotUrl(index, name) + '/approve', {task_id: latest.task_id, url: item.url});
                    await displayOrder();
                    notice('已批准 ' + slots[name]);
                })
            );
            const modify = button('继续改此图', () => submitOne(index, name, item.url));
            modify.disabled = !ready;
            figure.lastElementChild.append(modify);
            gallery.append(figure);
        }
        plate.append(gallery);
        return plate;
    }

    function sample(url, label) {
        const figure = node('figure');
        const link = node('a');
        link.href = url;
        link.target = '_blank';
        link.rel = 'noopener';
        const image = node('img');
        image.src = url;
        image.alt = label;
        image.loading = 'lazy';
        link.append(image);
        figure.append(link, node('figcaption', label));
        return figure;
    }

    function slotUrl(index, name) {
        return endpoint + '/' + order.id + '/colors/' + index + '/' + name;
    }

    function parameters() {
        const provider = element('provider').value;
        const model = element('model').value;
        const instruction = element('instruction').value.trim();
        if (!provider || !model || !instruction) throw new Error('请选择渠道和图像模型，并填写制作要求');
        return {provider, model, instruction, size: element('size').value};
    }

    async function submit(index, name, params, candidates, previousCandidate = null) {
        const prior = order.colors[index].slots[name].attempts.at(-1);
        return post(slotUrl(index, name) + '/generate', {
            ...params, candidates, previous_candidate: previousCandidate,
            operation_id: token(), parent_id: prior?.task_id || null,
        });
    }

    async function submitOne(index, name, previousCandidate) {
        try {
            await submit(index, name, parameters(), index === 0 ? 2 : 1, previousCandidate);
            notice('请求已记录，可刷新查看原任务');
        } finally {
            await openOrder(order.id);
        }
    }

    function selectModels() {
        const current = providers.find(provider => provider.id === element('provider').value);
        const models = current?.image_models || [];
        element('model').replaceChildren(...models.map(model => new Option(model, model)));
    }

    element('add').addEventListener('click', addReference);
    element('new').addEventListener('click', () => {
        element('create').hidden = false;
        element('create').elements.style.focus();
    });
    element('cancel').addEventListener('click', () => { element('create').hidden = true; });
    element('orders').addEventListener('change', () => act(() => openOrder(element('orders').value)));
    element('refresh').addEventListener('click', () => act(() => loadOrders(order?.id)));
    element('provider').addEventListener('change', selectModels);
    element('batch').addEventListener('click', () => act(async () => {
        const params = parameters();
        try {
            for (const {index, name} of batchSlots()) await submit(index, name, params, 1);
            notice('本批请求已记录，可刷新查看各图位');
        } finally {
            await openOrder(order.id);
        }
    }));
    function download(blob, name) {
        const link = node('a');
        link.href = URL.createObjectURL(blob);
        link.download = name;
        link.click();
        setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    }

    element('export').addEventListener('click', () => act(async () => {
        const manifest = await api(endpoint + '/' + order.id + '/delivery');
        download(new Blob([JSON.stringify(manifest, null, 2)], {type: 'application/json'}), '生产单-' + order.id + '.json');
        notice('已下载交付清单');
    }));

    element('zip').addEventListener('click', () => act(async () => {
        const manifest = await api(endpoint + '/' + order.id + '/delivery');
        const items = manifest.items.filter(item => item.status === 'approved').map((item, index) => {
            const url = item.output.asset.url;
            const suffix = url.slice(url.lastIndexOf('.'));
            const safeColor = item.color.replace(/[<>:"/\\|?*]/g, '_');
            return {url, name: (index + 1) + '-' + safeColor + '-' + slots[item.slot] + suffix};
        });
        if (!items.length) throw new Error('暂无可下载的已批准图');
        const response = await fetch('/api/canvas-assets/download', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({filename: 'approved-images.zip', items}),
        });
        if (!response.ok) throw new Error('已批准图片打包失败，请刷新后核对权限与素材');
        download(await response.blob(), '已批准商品图-' + order.id + '.zip');
        notice('已下载 ' + items.length + ' 张已批准图');
    }));
    element('create').addEventListener('submit', event => {
        event.preventDefault();
        const form = event.currentTarget;
        act(async () => {
            const data = Object.fromEntries(new FormData(form));
            const colors = Array.from(element('references').children, row => ({
                name: row.children[0].value.trim(), reference: row.children[1].value.trim(),
            }));
            const created = await post(endpoint, {...data, id: newOrderId, canvas_id: query.get('canvas_id') || '', colors});
            newOrderId = token();
            element('create').reset();
            element('references').replaceChildren();
            addReference();
            element('create').hidden = true;
            await loadOrders(created.id);
        });
    });
    addReference();
    act(async () => {
        const [configuration] = await Promise.all([api('/api/config'), loadOrders(query.get('id') || '')]);
        providers = (configuration.api_providers || []).filter(provider => provider.enabled !== false && provider.image_models?.length);
        element('provider').replaceChildren(...providers.map(provider => new Option(provider.name || provider.id, provider.id)));
        selectModels();
    });
})();
