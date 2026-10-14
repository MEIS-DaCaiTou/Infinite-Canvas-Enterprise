/* Shared by workflow settings and both canvases; no network or storage access. */
(function(root){
    'use strict';
    const mediaKinds = ['image', 'video', 'audio'];
    const isOutputPrefix = field => String(field?.input || '').toLowerCase() === 'filename_prefix';

    function inferType(value, inputName){
        const key = String(inputName || '').toLowerCase();
        if(isOutputPrefix({input:key})) return 'text';
        if(typeof value === 'boolean') return 'boolean';
        if(typeof value === 'number') return /strength|cfg|denoise/.test(key) ? 'slider' : 'number';
        if(typeof value !== 'string') return 'text';
        if(/prompt|text|description/.test(key)) return 'textarea';
        if(/video|movie|mp4|webm|mov|m4v|vhs/.test(key) || /\.(mp4|webm|mov|m4v|avi|mkv)(\?|$)/i.test(value)) return 'video';
        if(/audio|sound|music|voice|wav|mp3/.test(key) || /\.(mp3|wav|m4a|aac|ogg|flac)(\?|$)/i.test(value)) return 'audio';
        if(/(?:^|_)(?:image|img|mask)(?:_|$)/.test(key) || /\.(png|jpe?g|webp|gif|bmp|tiff?)(\?|$)/i.test(value)) return 'image';
        return value.length > 60 ? 'textarea' : 'text';
    }

    function definitionField(value, inputName, definition){
        const spec = definition?.input?.required?.[inputName] || definition?.input?.optional?.[inputName];
        const options = spec?.[1] || {};
        if(inputName === 'filename_prefix') return {type:'text'};
        if(options.image_upload) return {type:'image'};
        if(options.video_upload) return {type:'video'};
        if(options.audio_upload) return {type:'audio'};
        if(Array.isArray(spec?.[0])) return {type:'dropdown',options:spec[0].map(String)};
        if(spec?.[0] === 'BOOLEAN') return {type:'boolean'};
        if(['INT','FLOAT'].includes(spec?.[0])) return {type:'number',min:options.min,max:options.max,step:options.step || (spec[0]==='FLOAT' ? 0.01 : 1)};
        return {type:options.multiline ? 'textarea' : inferType(value,inputName)};
    }

    function normalizeWorkflow(data){
        const config = data.config || {fields:[]};
        return {...data, config:{...config, fields:(config.fields || []).map(field => {
            // Repair the old filename/file heuristic without changing IDs or other controls.
            if(!isOutputPrefix(field) || !mediaKinds.includes(field.type)) return {...field};
            const raw = data.workflow?.[field.node]?.inputs?.[field.input];
            return {...field, type:'text', default:field.default ?? raw ?? ''};
        })}};
    }

    function kind(field){
        if(isOutputPrefix(field)) return 'setting';
        if(mediaKinds.includes(field?.type)) return field.type;
        const key = `${field?.input || ''} ${field?.name || ''}`.toLowerCase();
        return field?.type === 'textarea' || /prompt|text|提示词|正向|负向/.test(key) ? 'prompt' : 'setting';
    }

    function missingMessage(fields, english=false){
        const names = fields.map(f => `${f.name || f.input} (#${f.node}.${f.input})`).join('、');
        return english ? `Please connect the missing ComfyUI inputs: ${names}` : `请连接 ComfyUI 缺少的输入：${names}`;
    }

    function requireMedia(config, media, english=false){
        const missing = mediaKinds.flatMap(type => (config.fields || []).filter(f => kind(f) === type).slice((media[type] || []).length));
        if(missing.length) throw new Error(missingMessage(missing, english));
    }

    function coerceValue(field, value){
        if(value === undefined || value === null) value = field.default ?? (field.type === 'boolean' ? false : (field.type === 'number' || field.type === 'slider' ? 0 : ''));
        if(field.type === 'number' || field.type === 'slider'){
            const n = Number(value);
            if(Number.isFinite(n)) return field.step && Number(field.step) < 1 ? n : Math.trunc(n);
        } else if(field.type === 'boolean') return Boolean(value);
        else if(field.type === 'dropdown' && typeof value === 'string'){
            const s = value.trim();
            if(s && /^-?\d+(?:\.\d+)?(?:e[+-]?\d+)?$/i.test(s)) return Number(s);
        }
        return value;
    }

    function paramsFromValues(config, values={}){
        const params = {};
        (config.fields || []).forEach(field => {
            if(!field.node || !field.input) return;
            (params[field.node] ||= {})[field.input] = coerceValue(field, values[field.id]);
        });
        return params;
    }

    async function canvasValues(config, {prompt='', media={}, parameters={}, mediaName, randomValue, english=false}){
        requireMedia(config, media, english);
        const values = {};
        const promptFields = (config.fields || []).filter(f => kind(f) === 'prompt');
        if(promptFields.length && !prompt && !promptFields[0].default) throw new Error(missingMessage([promptFields[0]], english));
        promptFields.forEach((f, i) => { values[f.id] = i === 0 ? (prompt || f.default || '') : (parameters[f.id] ?? f.default ?? ''); });
        for(const type of mediaKinds){
            const fields = (config.fields || []).filter(f => kind(f) === type);
            for(let i=0; i<fields.length; i++) values[fields[i].id] = await mediaName(media[type][i]);
        }
        (config.fields || []).filter(f => kind(f) === 'setting').forEach(f => {
            const random = randomValue?.(f);
            values[f.id] = random === undefined ? (parameters[f.id] ?? f.default) : random;
        });
        return values;
    }

    root.ComfyWorkflowFields = {inferType, definitionField, normalizeWorkflow, kind, missingMessage, requireMedia, coerceValue, paramsFromValues, canvasValues};
})(typeof window === 'undefined' ? globalThis : window);
