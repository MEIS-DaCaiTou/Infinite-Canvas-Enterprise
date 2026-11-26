/* Composer controls share the existing conversation and image-task services. */
(function () {
    'use strict';
    const types = [
        ['agent', 'Agent 模式', 'sparkles'], ['image', '图片生成', 'image-plus'],
        ['video', '视频生成', 'video'], ['music', '音乐生成', 'music-2'],
        ['audio', '音频生成', 'audio-lines'], ['avatar', '数字人', 'user-round'],
        ['motion', '动作模仿', 'person-standing'],
    ];
    const backgrounds = [['auto', '自动'], ['preserve', '保留背景'], ['opaque', '不透明背景'], ['transparent', '透明背景']];
    const byId = id => document.getElementById(id);

    class CreationComposer {
        constructor(host) {
            this.host = host;
            this.state = {type: 'agent', count: 4, background: 'auto', ...host.initial};
            this.popovers = [];
            this.type = this.popup('creationTypeButton', '创作类型', 'creation-type-options', types.map(([value, label, icon]) =>
                this.choice(label, value, 'type', icon, !['agent', 'image'].includes(value))));
            this.quantity = this.popup('creationCountButton', '选择生成数量', 'creation-count-options',
                Array.from({length: 8}, (_, index) => this.choice(String(index + 1), index + 1, 'count')));
            this.background = this.popup('creationBackgroundButton', '背景', 'creation-background-options',
                backgrounds.map(([value, label]) => this.choice(label, value, 'background')));
            const hint = document.createElement('p');
            hint.className = 'creation-popover-hint';
            hint.textContent = '保留背景需参考图；透明背景需模型支持透明 PNG。';
            this.background.append(hint);
            this.sync();
            this.referencesChanged();
            window.addEventListener('resize', () => this.close());
        }

        choice(label, value, field, icon, disabled = false) {
            const button = document.createElement('button');
            button.type = 'button';
            button.dataset.field = field;
            button.dataset.value = value;
            button.disabled = disabled;
            button.innerHTML = (icon ? `<i data-lucide="${icon}"></i>` : '') + `<span>${label}</span>`;
            if (disabled) {
                const note = document.createElement('small');
                note.textContent = '未接入';
                button.append(note);
                button.title = label + '尚未接入当前对话';
            }
            button.onclick = () => {
                if (field === 'count') this.host.onCountChange();
                this.state[field] = field === 'count' ? Number(value) : value;
                if (field === 'type') this.host.onTypeChange(value);
                this.sync();
                this.host.onChange({...this.state});
                this.close();
            };
            return button;
        }

        popup(triggerId, title, className, buttons) {
            const trigger = byId(triggerId);
            const popover = document.createElement('div');
            popover.id = triggerId + 'Popup';
            popover.className = 'creation-popover';
            popover.setAttribute('popover', 'auto');
            const heading = document.createElement('p');
            heading.className = 'creation-popover-title';
            heading.textContent = title;
            const choices = document.createElement('div');
            choices.className = className;
            choices.append(...buttons);
            popover.append(heading, choices);
            document.body.append(popover);
            trigger.setAttribute('aria-controls', popover.id);
            trigger.setAttribute('aria-expanded', 'false');
            popover.addEventListener('toggle', event => trigger.setAttribute('aria-expanded', String(event.newState === 'open')));
            trigger.onclick = async () => {
                if (popover.matches(':popover-open')) return popover.hidePopover();
                this.host.closePickers();
                this.close();
                popover.showPopover();
                const anchor = trigger.getBoundingClientRect();
                const panel = popover.getBoundingClientRect();
                popover.style.left = Math.max(12, Math.min(anchor.left, innerWidth - panel.width - 12)) + 'px';
                popover.style.top = Math.max(12, anchor.top - panel.height - 8) + 'px';
                if (triggerId === 'creationBackgroundButton') void this.refreshBackgroundSupport();
            };
            this.popovers.push(popover);
            return popover;
        }

        async refreshBackgroundSupport() {
            const option = this.background.querySelector('[data-value="transparent"]');
            const opaque = this.background.querySelector('[data-value="opaque"]');
            this.background.querySelector('[data-value="preserve"]').disabled = !this.host.hasReference();
            option.disabled = true;
            opaque.disabled = true;
            option.title = '正在读取模型能力';
            let supported;
            try {
                supported = await this.host.supportsTransparency();
            } catch (_) {
                this.background.querySelector('.creation-popover-hint').textContent = '暂时无法读取模型能力，请关闭后重试。';
                return;
            }
            option.disabled = !supported;
            opaque.disabled = !supported;
            opaque.title = supported ? '输出不透明图像，不代表保留原图场景' : '当前模型未声明原生背景参数能力';
            option.title = supported ? '输出含透明通道的 PNG' : '当前模型未声明透明背景能力，请切换支持的图像模型';
            this.background.querySelector('.creation-popover-hint').textContent = supported
                ? '透明背景输出 PNG；不透明背景与保留原图场景是不同设置。'
                : '当前模型未声明透明背景能力；可使用自动或保留背景。';
        }

        close() {
            for (const popover of this.popovers) if (popover.matches(':popover-open')) popover.hidePopover();
        }

        setCount(value) {
            this.state.count = this.layerOutput ? 1 : (Number(value) || 4);
            this.sync();
        }

        setLayerOutput(enabled) {
            if (Boolean(this.layerOutput) === enabled) return;
            if (enabled) this.regularCount = this.state.count;
            this.layerOutput = enabled;
            this.state.count = enabled ? 1 : (this.regularCount || 4);
            const trigger = byId('creationCountButton');
            trigger.disabled = enabled;
            trigger.title = enabled ? '一次拆分一张原图，图层数量由模型结果决定' : '选择生成数量';
            this.sync();
        }

        referencesChanged() {
            if (this.state.background === 'preserve' && !this.host.hasReference()) {
                this.state.background = 'auto';
                this.sync();
                this.host.onChange({...this.state});
            }
        }

        sync() {
            byId('creationCount').value = this.state.count;
            byId('creationCountLabel').textContent = this.layerOutput ? '分层1次' : this.state.count + '张';
            byId('creationCountButton').setAttribute('aria-label', this.layerOutput ? '图层拆分固定一次请求' : '选择生成数量: ' + this.state.count);
            byId('creationTypeLabel').textContent = types.find(item => item[0] === this.state.type)[1];
            byId('creationBackgroundLabel').textContent = this.state.background === 'auto' ? '自动背景' : backgrounds.find(item => item[0] === this.state.background)[1];
            for (const popover of this.popovers) {
                for (const button of popover.querySelectorAll('[data-field]')) {
                    button.setAttribute('aria-pressed', String(String(this.state[button.dataset.field]) === button.dataset.value));
                }
            }
            if (window.lucide) lucide.createIcons();
        }

        settings() { return {...this.state}; }
    }
    window.CreationComposer = CreationComposer;
})();
