/* Agent templates and authorized task cards within the existing conversation. */
(function () {
    'use strict';

    const templates = [
        {
            id: 'suite',
            title: '电商套图',
            prompt: '根据参考图制作一组电商商品图。保留商品的外观、颜色和细节，统一光线与视觉风格。',
            shots: [
                ['商品主图', '干净背景，清楚展示商品全貌，主体居中。'],
                ['使用场景', '将同一商品置于可信的使用场景，呈现实际比例。'],
                ['细节特写', '突出商品的真实质感和关键细节，避免虚构卖点。'],
                ['陈列画面', '用规整的道具和构图展示商品，保留用于排版的空间。'],
            ],
        },
        {
            id: 'portrait',
            title: '胶片人像',
            prompt: '拍摄一张自然的胶片人像。柔和晨光、低饱和色彩、细微胶片颗粒，保留真实肤质和自然表情。',
        },
        {
            id: 'poster',
            title: '场景海报',
            prompt: '创作一张产品场景海报。以参考图里的商品为主体，用自然光和简洁道具营造使用氛围，留出排版空间。',
        },
    ];
    const statuses = {
        queued: '排队中', running: '生成中', succeeded: '已完成', partial: '部分完成',
        unknown: '待核对', failed: '失败', cancelled: '已取消', started: '待执行',
        submitting: '正在提交', accepted: '已受理', generated: '正在归档', completed: '已归档',
        unavailable: '暂不可读',
    };
    const taskCatalog = '/enterprise/api/me/generation-tasks';
    const element = id => document.getElementById(id);

    function node(tag, className, text) {
        const item = document.createElement(tag);
        if (className) item.className = className;
        if (text) item.textContent = text;
        return item;
    }

    function icon(name) {
        const item = node('i');
        item.dataset.lucide = name;
        item.setAttribute('aria-hidden', 'true');
        return item;
    }

    function action(label, handler, className = '') {
        const button = node('button', className, label);
        button.type = 'button';
        button.onclick = handler;
        return button;
    }

    async function request(url, options) {
        const response = await fetch(url, {cache: 'no-store', ...options});
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            const detail = typeof data.detail === 'string' ? data.detail : data.detail?.message;
            throw Object.assign(new Error(detail || '请求暂不可用，请稍后重试'), {status: response.status});
        }
        return data;
    }

    class CreationWorkspace {
        constructor(host) {
            this.host = host;
            this.input = element('messageInput');
            this.count = element('creationCount');
            this.composer = new CreationComposer({
                initial: host.composerInitial,
                onCountChange: () => { if (this.template?.shots) this.select(null); },
                onTypeChange: host.creationTypeChanged,
                onChange: host.composerChanged,
                closePickers: host.closePickers,
                supportsTransparency: host.supportsTransparency,
                hasReference: host.hasReference,
            });
            const dialog = element('agentTemplatesDialog');
            for (const template of templates) {
                const button = action('', () => this.select(template), 'creation-template');
                button.setAttribute('aria-pressed', 'false');
                button.dataset.template = template.id;
                const image = node('img');
                image.src = '/static/images/creation-templates/' + template.id + '.jpg';
                image.alt = '';
                const label = node('span', 'creation-template-label');
                label.append(node('span', '', template.title), icon('arrow-up-right'));
                button.append(image, label);
                element('creationTemplates').append(button);
                element('agentTemplateChoices').append(action(template.title, () => {
                    dialog.close();
                    this.select(template);
                }, 'creation-button'));
            }
            element('agentTemplates').onclick = () => dialog.showModal();
            element('agentTemplateSelection').onclick = () => this.select(null);
            element('creationAssets').onclick = () => this.openAssets();
            element('creationPlanForm').onsubmit = event => {
                event.preventDefault();
                const variants = [...event.currentTarget.querySelectorAll('textarea')].map(input => input.value.trim());
                element('creationPlanDialog').close();
                const {prompt, title} = this.pendingPlan;
                void this.host.send(prompt, {...this.imageOptions(), template: title, count: variants.length, variants});
            };
        }

        select(template) {
            if (this.template?.shots) this.count.value = this.unlockedCount;
            this.template = template;
            this.count.disabled = Boolean(template?.shots);
            if (template?.shots) {
                this.unlockedCount = this.count.value;
                this.count.value = String(template.shots.length);
            }
            this.composer.setCount(this.count.value);
            for (const button of element('creationTemplates').children) {
                button.setAttribute('aria-pressed', String(button.dataset.template === template?.id));
            }
            const selection = element('agentTemplateSelection');
            selection.hidden = !template;
            selection.querySelector('span').textContent = template?.title || '';
            selection.setAttribute('aria-label', template ? '取消' + template.title + '模板' : '');
            if (template) {
                this.input.value = template.prompt;
                this.host.resizeInput(this.input);
                this.input.focus();
            }
        }

        notice(message) {
            const notice = element('creationNotice');
            notice.textContent = message;
            notice.hidden = !message;
        }

        openAssets() {
            const dialog = element('creationAssetDialog');
            const picker = new CharacterAssetPicker({
                request,
                cancelLabel: '返回对话',
                onCancel: () => dialog.close(),
                onConfirm: ({url, name}) => {
                    this.notice(this.host.addReference({url, name, kind: 'image'}));
                    dialog.close();
                },
            });
            picker.source = 'saved';
            dialog.replaceChildren(picker.root);
            dialog.addEventListener('close', () => picker.destroy(), {once: true});
            dialog.showModal();
            void picker.load();
        }

        async send(prompt) {
            if (this.composer.settings().background === 'preserve' && !this.host.hasReference()) {
                this.notice('请先添加要保留背景的参考图。');
                return;
            }
            const template = this.template;
            if (this.composer.layerOutput && template?.shots) {
                this.notice('当前为图层拆分模型，请切换普通生图模型后使用套图模板。');
                return;
            }
            if (!template?.shots) {
                await this.host.send(prompt, {...this.imageOptions(), template: template?.title || ''});
                return;
            }
            this.pendingPlan = {prompt, title: template.title};
            const fields = template.shots.map(([title, guidance]) => {
                const label = node('label', '', title);
                const input = node('textarea');
                input.required = true;
                input.maxLength = 20000;
                input.rows = 3;
                input.value = prompt + '\n' + guidance;
                label.append(input);
                return label;
            });
            element('creationPlanSummary').textContent = this.host.imageSettings() + ' · ' + template.shots.length + ' 张';
            element('creationPlanItems').replaceChildren(...fields);
            element('creationPlanDialog').showModal();
        }

        imageOptions() {
            const {type, count, background} = this.composer.settings();
            return {creationType: type, count, background};
        }

        taskCard(message) {
            const card = node('section', 'creation-task');
            card.append(node('h2', '', message.image_title || '图片创作'), node('p', '', '读取生成进度…'));
            queueMicrotask(() => this.refreshTask(card, message));
            return card;
        }

        async refreshTask(card, message) {
            if (!card.isConnected) return;
            try {
                const task = await request(taskCatalog + '/' + encodeURIComponent(message.task_id));
                if (!card.isConnected) return;
                this.renderTask(card, task);
                if (['queued', 'running'].includes(task.status) || ['waiting', 'querying'].includes(task.auto_recovery?.status)) {
                    setTimeout(() => this.refreshTask(card, message), 2200);
                }
            } catch (error) {
                if (!card.isConnected) return;
                card.replaceChildren(
                    node('h2', '', message.image_title || '图片创作'),
                    node('p', '', error.status === 404 ? '原任务受理状态待核对。' : error.message),
                    action('刷新原任务', () => this.refreshTask(card, message), 'creation-button'),
                );
            }
        }

        async chooseCanvas(taskId) {
            const dialog = element('creationCanvasDialog');
            const status = element('creationCanvasState');
            const choices = element('creationCanvasSelect');
            const open = element('creationCanvasOpen');
            status.textContent = '正在读取可访问的画布…';
            choices.hidden = open.hidden = true;
            dialog.showModal();
            try {
                const {canvases} = await request('/api/canvases');
                if (!canvases.length) {
                    status.textContent = '暂无可访问的画布。请先在无限画布中新建。';
                    return;
                }
                choices.replaceChildren(...canvases.map(canvas => {
                    const option = node('option', '', canvas.title || '未命名画布');
                    const page = canvas.kind === 'smart' ? 'smart-canvas' : 'canvas';
                    option.value = '/static/' + page + '.html?' + new URLSearchParams({id: canvas.id, reuse_task: taskId});
                    return option;
                }));
                choices.onchange = () => { open.href = choices.value; };
                choices.onchange();
                choices.hidden = open.hidden = false;
                status.textContent = '打开画布后，可从原任务选择要放入的图片。';
                open.onclick = () => dialog.close();
            } catch (error) {
                status.textContent = error.message;
            }
        }

        renderTask(card, task) {
            const title = node('h2', '', task.creation_title || '图片创作');
            const settings = task.creation_settings;
            const background = {auto:'自动背景', preserve:'保留背景', opaque:'不透明背景', transparent:'透明背景'};
            const layered = String(task.model || '').endsWith('/layer-decomposition');
            const summary = node('p', 'creation-task-summary', [statuses[task.status] || task.status, task.model,
                settings?.count ? settings.count + (layered ? '次拆分' : '张') : '', settings ? background[settings.background] : ''].filter(Boolean).join(' · '));
            summary.setAttribute('role', 'status');
            const steps = node('div', 'creation-steps');
            for (const attempt of task.attempts || []) {
                steps.append(node('span', '', '第 ' + (attempt.index + 1) + (layered ? ' 次拆分 · ' : ' 张 · ') + (statuses[attempt.status] || attempt.status)));
            }
            const gallery = node('div', 'creation-results');
            for (const result of task.items || []) {
                if (result.kind !== 'image') continue;
                const tile = node('article', 'creation-result');
                const preview = action('', () => this.host.preview(result.url), 'creation-result-preview');
                const image = node('img');
                image.src = result.url;
                image.alt = result.name || '生成图片';
                preview.append(image);
                const footer = node('div', 'creation-result-actions');
                const download = node('a', '', '下载');
                download.href = result.url;
                download.download = '';
                footer.append(action('用作参考', () => this.notice(this.host.addReference({url: result.url, kind: 'image', name: result.name}))), download);
                tile.append(preview, footer);
                gallery.append(tile);
            }
            const retry = task.can_query ? action('续查原任务', async event => {
                const button = event.currentTarget;
                button.disabled = true;
                this.notice('正在续查原任务…');
                try {
                    await request('/api/canvas-image-tasks/' + encodeURIComponent(task.id) + '/reconcile', {method: 'POST'});
                    this.notice('');
                    await this.refreshTask(card, {task_id: task.id, image_title: task.creation_title});
                } catch (error) {
                    this.notice(error.message);
                } finally {
                    button.disabled = false;
                }
            }, 'creation-button') : null;
            const error = task.error ? node('p', 'creation-task-error', task.error) : null;
            const canvas = gallery.childElementCount ? action('加入画布', () => this.chooseCanvas(task.id), 'creation-button') : null;
            card.replaceChildren(...[title, summary, steps, gallery, error, canvas, retry].filter(Boolean));
        }
    }

    window.CreationWorkspace = CreationWorkspace;
}());
