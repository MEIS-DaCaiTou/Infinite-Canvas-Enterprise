/* Personal model shortcuts. Enterprise provider configuration stays unchanged. */
(function () {
    const VIDEO_TOGGLE_FIELDS = ['enhance_prompt','enable_upsample','camerafixed','return_last_frame','watermark','generate_audio','multimodal','frame_roles','trusted_asset'];
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
                if(config.getProfile?.(model)?.supported === false){
                    option.disabled = true;
                    option.textContent += parameterText('（尚未适配）',' (not adapted)');
                }
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
    function videoProfileFor(provider, model, channel='') {
        const profile = provider?.builtin_model_video_profiles?.[model] || {};
        return profile.variants?.[channel] ? {...profile,...profile.variants[channel]} : profile;
    }
    function videoToggleSupported(profile, key) {
        const field = {
            enhancePrompt:'enhance_prompt', enableUpsample:'enable_upsample', cameraFixed:'camerafixed',
            watermark:'watermark', generateAudio:'generate_audio', multimodal:'multimodal',
            useFrameRoles:'frame_roles', returnLastFrame:'return_last_frame',
            videoEnhancePrompt:'enhance_prompt', videoEnableUpsample:'enable_upsample', videoCameraFixed:'camerafixed',
            videoWatermark:'watermark', videoGenerateAudio:'generate_audio', videoMultimodal:'multimodal', videoUseFrameRoles:'frame_roles', videoTrustedAsset:'trusted_asset',
        }[key] || key;
        return profile?.supported !== false && (!profile?.route || (profile.toggles || []).includes(field));
    }
    function videoChoices(values, current, ignoreCase=false) {
        const options = [...values];
        if(current && !options.includes(current)){
            const alias = ignoreCase ? options.findIndex(value=>value.toLowerCase() === current.toLowerCase()) : -1;
            if(alias >= 0) options[alias] = current;
            else options.unshift(current);
        }
        return options;
    }
    function videoParameters(source, profile={}) {
        const parameters = {
            duration:Number(source.videoDuration ?? source.duration ?? 5),
            aspect_ratio:source.videoAspect ?? source.aspectRatio ?? source.aspect_ratio ?? '16:9',
            resolution:source.videoResolution ?? source.resolution ?? '',
            video_channel:source.videoChannel ?? source.video_channel ?? '',
            enhance_prompt:!!(source.videoEnhancePrompt ?? source.enhancePrompt ?? source.enhance_prompt),
            enable_upsample:!!(source.videoEnableUpsample ?? source.enableUpsample ?? source.enable_upsample),
            camerafixed:!!(source.videoCameraFixed ?? source.cameraFixed ?? source.camerafixed),
            watermark:!!(source.videoWatermark ?? source.watermark),
            generate_audio:!!(source.videoGenerateAudio ?? source.generateAudio ?? source.generate_audio),
            multimodal:!!(source.videoMultimodal ?? source.multimodal),
            frame_roles:!!(source.videoUseFrameRoles ?? source.useFrameRoles),
            return_last_frame:!!(source.returnLastFrame ?? source.return_last_frame),
            trusted_asset:!!(source.videoTrustedAsset ?? source.trusted_asset),
        };
        // Stored options belong to the canvas. Only effective options for the
        // current model enter validation and new requests.
        for(const field of VIDEO_TOGGLE_FIELDS){
            if(!videoToggleSupported(profile, field)) parameters[field] = false;
        }
        return parameters;
    }
    function videoError(profile, value) {
        const text = (zh,en) => parameterText(zh,en);
        if(profile.supported === false) return text(profile.message || '该视频型号尚未适配，请选择已适配型号','This video model is not adapted; choose a supported model');
        if(!profile.route) return '';
        if(profile.channel_required && !profile.variants?.[value.video_channel]) return text('请按密钥分组选择 Sora 官方或兼容通道','Choose the Sora channel that matches your key group');
        if(profile.durations && !profile.durations.includes(value.duration)) return text('支持的时长：','Supported durations: ') + profile.durations.join(' / ') + 's';
        if(profile.ratios && !profile.ratios.includes(value.aspect_ratio)) return text('该模型不支持当前比例，请重新选择','Choose a supported aspect ratio');
        if(profile.resolutions && value.resolution && !profile.resolutions.some(r=>r.toLowerCase() === value.resolution.toLowerCase())) return text('该模型不支持当前清晰度，请重新选择','Choose a supported resolution');
        for(const field of VIDEO_TOGGLE_FIELDS) {
            if(value[field] && !profile.toggles?.includes(field)) return text('请取消该模型不支持的选项：','Disable the unsupported option: ') + field;
        }
        for(const [kind, label] of [['images','图片'],['videos','视频'],['audios','音频']]) {
            if(!Array.isArray(value[kind])) continue;
            const key = kind === 'images' ? 'images' : kind;
            if(value[kind].length > (profile['max_' + key] ?? Infinity)) return text(label + '数量超过当前模型范围','Too many input ' + kind);
        }
        if(profile.max_media && ['images','videos','audios'].reduce((total,key)=>total + (value[key]?.length || 0),0) > profile.max_media) return text('参考素材总数超过当前模型范围','Too many total input references');
        if(value.seed != null && !profile.toggles?.includes('seed')) return text('该模型不支持 seed','This model does not accept seed');
        if(Array.isArray(value.images) && value.images.length < (profile.min_images || 0)) return text('该模型需要参考图，请先添加图片','This model requires a reference image');
        if(value.images?.some(ref=>ref.role) && !profile.toggles?.includes('frame_roles')) return text('该模型不支持首尾帧，请取消该选项','Disable frame roles for this model');
        if(profile.family === 'seedance' && value.images){
            const roles = value.images.map(ref=>ref.role || '');
            if(roles.some(role=>!['','first_frame','last_frame','reference_image'].includes(role))) return text('图片角色不受当前模型支持','Unsupported image role');
            if(roles.filter(role=>role === 'first_frame').length > 1 || roles.filter(role=>role === 'last_frame').length > 1) return text('首帧与尾帧各只能选择一张','Select at most one first and last frame');
            if(roles.includes('last_frame') && !roles.includes('first_frame')) return text('尾帧需要同时提供首帧','A last frame requires a first frame');
            if(value.multimodal && roles.some(role=>['first_frame','last_frame'].includes(role))) return text('全部参考与首尾帧不能同时使用','Reference mode and first/last frames cannot be combined');
            if(value.images.length > 1 && !value.multimodal && !roles.some(Boolean)) return text('多张图片请选择首尾帧或全部参考','Choose frame roles or reference mode for multiple images');
        }
        if(profile.family === 'vidu' && value.images?.length > 1 && !value.multimodal) return text('Vidu 多图输入请选择全部参考','Choose reference mode for multiple Vidu images');
        if(profile.family === 'xai' && (value.images?.length > 1 || value.multimodal) && value.duration > 10) return text('参考图模式最多 10 秒','Reference mode allows at most 10 seconds');
        if(['grok','xai'].includes(profile.family) && value.images?.length > 1 && value.resolution?.toLowerCase() === '1080p') return text('多参考图模式最高支持 720p','Multiple image references allow up to 720p');
        return '';
    }
    function videoInputNote(profile, parameters={}) {
        if(!profile.route) return '';
        const parts = [parameterText('参考图 ','Images ') + (profile.min_images || 0) + '–' + profile.max_images,
            parameterText('视频 ','Videos ') + profile.max_videos,
            parameterText('音频 ','Audio ') + profile.max_audios];
        if(profile.media_duration_total) parts.push(parameterText('音视频总长 ≤ ','Total media duration ≤ ') + profile.media_duration_total + 's');
        const resolutionNote = profile.resolution_notes?.[String(parameters.resolution || '').toLowerCase()];
        if(resolutionNote) parts.push(resolutionNote);
        return parts.join(' · ');
    }
    function imageParameters(source) {
        const ratios = {square:'1:1', portrait:'2:3', landscape:'3:2', portrait43:'3:4', landscape43:'4:3', story:'9:16', wide:'16:9', ultrawide:'21:9', ultratall:'9:21'};
        const ratio = ['custom','source'].includes(source.ratio) ? source.customRatio : (ratios[source.ratio] || source.ratio);
        return {aspect_ratio:source.resolution === 'auto' ? 'auto' : ratio || '', resolution:['512','1k','1.5k','2k','4k'].includes(source.resolution) ? source.resolution.toUpperCase() : ''};
    }
    function parameterText(zh,en) { return window.StudioI18n?.lang?.() === 'en' ? en : zh; }
    function validationNotice(error,submitting=false) {
        return error ? error + (submitting
            ? parameterText('；原参数已保留，本次未提交','; original settings kept; no task submitted')
            : parameterText('；原参数已保留','; original settings kept')) : '';
    }
    function sizeError(profile, size, parameters={}) {
        if(!profile.mode) return '';
        const raw = String(size || '').trim().toLowerCase();
        if(profile.mode === 'aspect-size'){
            const ratio = parameters.aspect_ratio || raw;
            if(ratio === 'auto') return '';
            const parts = String(ratio).split(':').map(Number);
            if(profile.ratios?.length && !profile.ratios.some(value => {
                const [w,h] = value.split(':').map(Number);
                return parts.length === 2 && parts[0] * h === parts[1] * w;
            })) return parameterText('当前模型不支持画幅 ' + ratio + '，请重新选择','Unsupported aspect ratio ' + ratio + '; choose another ratio');
            if(profile.supports_image_size !== false && profile.resolutions?.length && !profile.resolutions.includes(String(parameters.resolution || '').toUpperCase())) return parameterText('当前模型不支持该分辨率，请重新选择','Unsupported resolution; choose another resolution');
            return '';
        }
        if(!['size_rules','size_presets','resolutions','supports_auto_size'].some(key => key in profile)) return '';
        if(raw === 'auto') return profile.supports_auto_size === false ? parameterText('当前模型不支持自动尺寸，请重新选择','Automatic size is unavailable for this model') : '';
        if(profile.resolutions?.includes(raw.toUpperCase())) return '';
        if(profile.size_presets?.length && !profile.size_presets.includes(raw)) return parameterText('当前模型仅开放已维护尺寸，请重新选择','Choose a maintained size preset for this model');
        if(profile.supports_custom_size === false && !profile.size_presets?.length) return parameterText('当前模型不支持自定义像素尺寸，请选择已维护分辨率','Choose a supported resolution instead of custom pixel dimensions');
        if(parameters.resolution && profile.resolutions?.length && !profile.resolutions.includes(parameters.resolution.toUpperCase())) return parameterText('当前模型不支持该分辨率，请重新选择','Unsupported resolution; choose another resolution');
        const match = raw.match(/^([1-9]\d*)x([1-9]\d*)$/);
        if(!match) return parameterText('请填写有效的宽高像素','Enter a valid width and height in pixels');
        const [w,h] = match.slice(1).map(Number), rules = profile.size_rules || {};
        if(rules.multiple && (w % rules.multiple || h % rules.multiple)) return parameterText(`宽高必须都是 ${rules.multiple} 的倍数`,`Width and height must be multiples of ${rules.multiple}`);
        if(rules.max_edge && Math.max(w,h) > rules.max_edge) return parameterText(`当前模型最长边不能超过 ${rules.max_edge}px`,`The maximum edge is ${rules.max_edge}px`);
        if(rules.max_aspect && Math.max(w,h) > Math.min(w,h) * rules.max_aspect) return parameterText(`当前模型长短边比例不能超过 ${rules.max_aspect}:1`,`The maximum aspect ratio is ${rules.max_aspect}:1`);
        if((rules.min_pixels && w*h < rules.min_pixels) || (rules.max_pixels && w*h > rules.max_pixels)) return parameterText('当前尺寸的像素总数超出模型范围，请重新选择','The pixel count is outside this model’s range');
        return '';
    }
    function sizeChoices(profile, ratios, resolutions, source, sizeFor) {
        if(!profile.mode) return {ratios, resolutions};
        const allowedRes = values => values.filter(value => {
            if(value === 'custom') return profile.supports_custom_size !== false;
            if(value === 'auto') return profile.supports_auto_size === true;
            return !profile.resolutions?.length || profile.resolutions.includes(value.toUpperCase());
        });
        const ratioChoices = [...ratios];
        for(const ratio of profile.ratios || []){
            if(!ratioChoices.some(([value]) => imageParameters({ratio:value}).aspect_ratio === ratio)) ratioChoices.push([ratio,ratio,'模型支持']);
        }
        const legal = (ratio,resolution) => !sizeError(profile,sizeFor(ratio,resolution),imageParameters({...source,ratio,resolution}));
        return {
            ratios:ratioChoices.filter(([value]) => value === 'source' || (value === 'custom' ? profile.supports_custom_size !== false : allowedRes(resolutions).filter(r => !['auto','custom'].includes(r)).some(r => legal(value,r)))),
            resolutions:profile.supports_image_size === false ? [] : allowedRes(resolutions).filter(value => ['auto','custom'].includes(value) || legal(source.ratio || 'square',value)),
        };
    }
    function syncSizeSelect(select, choices, current) {
        select.replaceChildren(...choices.map(([value,label]) => new Option(label,value)));
        if(current && !choices.some(([value]) => value === current)){
            const option = new Option(current + parameterText('（原值）',' (saved value)'), current);
            option.disabled = true; select.add(option);
        }
        select.value = current || '';
    }
    function preferredModel(kind, providerId, models) {
        return models.find(model => favorites.has(JSON.stringify([kind,providerId,model]))) || models[0] || '';
    }
    window.CanvasModelPicker = {mountSelect, mountList, profileFor, videoProfileFor, videoToggleSupported, videoChoices, videoParameters, videoError, videoInputNote, imageParameters, sizeError, sizeChoices, syncSizeSelect, validationNotice, preferredModel};
})();
