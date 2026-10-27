/* Shared by workflow settings and both canvases; no network or storage access. */
(function(root){
    'use strict';
    const mediaKinds = ['image', 'video', 'audio'];
    const isOutputPrefix = field => String(field?.input || '').toLowerCase() === 'filename_prefix';
    const valueType = value => typeof value === 'number' ? (Number.isInteger(value) ? 'integer' : 'number') : ['string','boolean'].includes(typeof value) ? typeof value : '';
    const isLink = (workflow,value) => Array.isArray(value) && value.length===2 && Number.isInteger(value[1]) && Object.hasOwn(workflow,String(value[0]));

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
        if(Array.isArray(spec?.[0])) return {type:'dropdown',options:spec[0].map(String),value_type:valueType(spec[0][0]) || valueType(value)};
        if(spec?.[0] === 'BOOLEAN') return {type:'boolean'};
        if(['INT','FLOAT'].includes(spec?.[0])) return {type:'number',value_type:spec[0]==='INT'?'integer':'number',min:options.min,max:options.max,step:options.step ?? (spec[0]==='FLOAT' ? 0.01 : 1)};
        return {type:options.multiline ? 'textarea' : inferType(value,inputName)};
    }

    function normalizeWorkflow(data){
        const config = data.config || {fields:[]};
        return {...data, config:{...config, fields:(config.fields || []).map(field => {
            // Repair the old filename/file heuristic without changing IDs or other controls.
            const raw = data.workflow?.[field.node]?.inputs?.[field.input];
            const definition = data.definitions?.[data.workflow?.[field.node]?.class_type];
            const profile = definitionField(raw,field.input,definition);
            field = {...field,value_type:profile.value_type || valueType(raw) || field.value_type || ''};
            if(field.type === 'dropdown') return {...field, options:dropdownOptions(field, raw, definition)};
            if(!isOutputPrefix(field) || !mediaKinds.includes(field.type)) return field;
            return {...field, type:'text', default:field.default ?? raw ?? ''};
        })}};
    }

    function dropdownOptions(field, raw, definition){
        if(field.options?.length) return [...field.options];
        const profile = definitionField(raw, field.input, definition);
        if(profile.options?.length) return profile.options;
        const value = field.default ?? raw;
        return ['string','number','boolean'].includes(typeof value) && String(value) !== '' ? [String(value)] : [];
    }

    function kind(field){
        if(isOutputPrefix(field)) return 'setting';
        if(field?.type === 'image_group') return 'image';
        if(mediaKinds.includes(field?.type)) return field.type;
        if(['number','slider','boolean','dropdown'].includes(field?.type)) return 'setting';
        if(field?.role) return field.role === 'prompt' ? 'prompt' : 'setting';
        const key = `${field?.input || ''} ${field?.name || ''}`.toLowerCase();
        return field?.type === 'textarea' || /prompt|text|提示词|正向|负向/.test(key) ? 'prompt' : 'setting';
    }

    function missingMessage(fields, english=false){
        const names = fields.map(f => f.type==='image_group' ? `${f.name || '图片输入'}（${f.min_images}–${f.max_images} 张）` : `${f.name || f.input} (#${f.node}.${f.input})`).join('、');
        return english ? `Please connect the missing ComfyUI inputs: ${names}` : `请连接 ComfyUI 缺少的输入：${names}`;
    }

    function requireMedia(config, media, english=false){
        const missing = mediaKinds.flatMap(type => {
            let available = (media[type] || []).length;
            return runtimeFields(config).filter(f=>kind(f)===type).filter(f=>{
                const count = f.type==='image_group' ? f.min_images : 1;
                available -= count;
                return available < 0;
            });
        });
        if(missing.length) throw new Error(missingMessage(missing, english));
        const groups = config.image_groups || [];
        if(groups.length){
            const maximum = runtimeFields(config).filter(f=>kind(f)==='image').reduce((n,f)=>n+(f.type==='image_group'?f.max_images:1),0);
            if((media.image || []).length > maximum) throw new Error(english ? `At most ${maximum} images are accepted` : `此工作流最多接收 ${maximum} 张图片；请移除多余连接`);
        }
    }

    function runtimeFields(config){
        const groups = config.image_groups || [];
        const used = new Set();
        const fields = [];
        for(const field of config.fields || []){
            const group = groups.find(g=>g.source_nodes.includes(field.node) && field.input==='image');
            if(!group){fields.push(field);continue;}
            if(!used.has(group.id)) fields.push({...group,type:'image_group',default:[]});
            used.add(group.id);
        }
        groups.filter(g=>!used.has(g.id)).forEach(g=>fields.push({...g,type:'image_group',default:[]}));
        return fields;
    }

    function coerceValue(field, value){
        if(value === undefined || value === null) value = field.default ?? (field.type === 'boolean' ? false : (field.type === 'number' || field.type === 'slider' ? 0 : ''));
        if(field.type === 'number' || field.type === 'slider'){
            const n = Number(value);
            if(!Number.isFinite(n) || value === '' || typeof value === 'boolean') throw new Error(`${field.name || field.input || '参数'}：数值无效`);
            if(field.value_type==='integer' && !Number.isInteger(n)) throw new Error(`${field.name || field.input}：需要整数`);
            if(field.min!=null && n<field.min || field.max!=null && n>field.max) throw new Error(`${field.name || field.input}：数值超出配置范围`);
            return field.value_type==='number' || field.value_type==='integer' || field.step && Number(field.step)<1 ? n : Math.trunc(n);
        } else if(field.type === 'boolean' || field.value_type==='boolean'){
            if(value===true || value===false) return value;
            if(value===1 || value==='1' || value==='true') return true;
            if(value===0 || value==='0' || value==='false') return false;
            throw new Error(`${field.name || field.input || '参数'}：需要开启或关闭`);
        }
        else if(field.type === 'dropdown' && typeof value === 'string'){
            const s = value.trim();
            if(field.value_type==='string') return value;
            if(s && /^-?\d+(?:\.\d+)?(?:e[+-]?\d+)?$/i.test(s)) return Number(s);
        }
        return value;
    }

    function executionState(workflow, config, values={}){
        const graph=Object.fromEntries(Object.entries(workflow).map(([id,node])=>[id,{...node,inputs:{...node.inputs}}]));
        const link=v=>isLink(graph,v);
        for(const f of config.fields || []){
            if(!graph[f.node] || !(f.input in graph[f.node].inputs) || link(graph[f.node].inputs[f.input])) continue;
            graph[f.node].inputs[f.input]=coerceValue(f,values[f.id]);
        }
        function literal(v,seen=new Set()){
            if(!link(v)) return v;
            const id=String(v[0]);
            if(seen.has(id) || v[1]!==0) return undefined;
            seen.add(id);
            return ['PrimitiveBoolean','PrimitiveInt','PrimitiveFloat'].includes(graph[id].class_type) ? literal(graph[id].inputs.value,seen) : undefined;
        }
        const consumed=new Set(), blocked=new Map(), parents=new Map();
        for(const [id,node] of Object.entries(graph)){
            const choice=node.class_type==='ComfySwitchNode' ? literal(node.inputs.switch) : undefined;
            if(typeof choice==='boolean') blocked.set(id+'.'+(choice?'on_false':'on_true'),{node:id,input:'switch',value:!choice});
            for(const [key,v] of Object.entries(node.inputs)) if(link(v)){
                const source=String(v[0]);consumed.add(source);
                if(!parents.has(source))parents.set(source,[]);
                parents.get(source).push([id,key]);
            }
        }
        const active=new Set(), roots=Object.keys(graph).filter(id=>!consumed.has(id));
        const pending=roots.length?roots:Object.keys(graph);
        while(pending.length){
            const id=pending.pop();if(active.has(id))continue;active.add(id);
            for(const [key,v] of Object.entries(graph[id].inputs)) if(!blocked.has(id+'.'+key) && link(v))pending.push(String(v[0]));
        }
        function gateFor(id,seen=new Set()){
            if(seen.has(id))return null;seen.add(id);
            for(const [target,key] of parents.get(id) || []){
                const gate=blocked.get(target+'.'+key) || gateFor(target,seen);
                if(gate)return gate;
            }
            return null;
        }
        const fields={};
        for(const f of config.fields || []) fields[f.id]={active:active.has(String(f.node)) && !blocked.has(f.node+'.'+f.input),gate:blocked.get(f.node+'.'+f.input) || gateFor(String(f.node))};
        const prompts=(config.fields || []).filter(f=>kind(f)==='prompt' && (values[f.id] ?? f.default));
        const errors=[];
        const activePrompts=new Set(prompts.filter(f=>fields[f.id].active).map(f=>String(values[f.id] ?? f.default)));
        const ignored=prompts.some(f=>!fields[f.id].active && (values[f.id] ?? f.default)!==f.default && !activePrompts.has(String(values[f.id])));
        if(prompts.length && (!activePrompts.size || ignored))errors.push('创作提示词未进入当前执行分支；请开启对应分支，或映射当前分支的提示词。');
        return {fields,errors};
    }

    function paramsFromValues(config, values={}){
        const params = {};
        (config.fields || []).forEach(field => {
            if(!field.node || !field.input) return;
            if(field.input==='image' && (config.image_groups || []).some(group=>group.source_nodes.includes(field.node)))return;
            (params[field.node] ||= {})[field.input] = coerceValue(field, values[field.id]);
        });
        return params;
    }

    async function canvasValues(config, {prompt='', media={}, parameters={}, mediaName, randomValue, english=false, workflow}){
        requireMedia(config, media, english);
        const values = {};
        const promptFields = (config.fields || []).filter(f => kind(f) === 'prompt');
        if(prompt && !promptFields.length) throw new Error(english
            ? 'This workflow has no mapped creative prompt. In Workflow Settings, expose the instruction input and set its purpose to Creative prompt.'
            : '此工作流未配置创作提示词映射；请在工作流设置中暴露实际指令字段，并将输入用途设为“创作提示词”。');
        if(promptFields.length && !prompt && !promptFields[0].default) throw new Error(missingMessage([promptFields[0]], english));
        promptFields.forEach((f, i) => {
            // Explicit creative-prompt bindings can cover alternative graph branches.
            // Unclassified legacy secondary text keeps its configured value.
            values[f.id] = prompt && (i === 0 || f.role === 'prompt') ? prompt
                : i === 0 ? (f.default || '') : (parameters[f.id] ?? f.default ?? '');
        });
        (config.fields || []).filter(f => kind(f) === 'setting').forEach(f => {
            const random = randomValue?.(f);
            values[f.id] = random === undefined ? (parameters[f.id] ?? f.default) : random;
        });
        if(workflow){
            const state=executionState(workflow,config,values);
            if(state.errors.length)throw new Error(state.errors[0]);
        }
        for(const type of mediaKinds){
            const fields = runtimeFields(config).filter(f => kind(f) === type);
            let offset=0;
            for(let i=0; i<fields.length; i++){
                const field=fields[i];
                if(field.type==='image_group'){
                    const remaining=fields.slice(i+1).reduce((n,f)=>n+(f.type==='image_group'?f.min_images:1),0);
                    const count=Math.min(field.max_images,(media[type] || []).length-offset-remaining);
                    values[field.id]=await Promise.all(media[type].slice(offset,offset+count).map(ref=>mediaName(ref)));
                    offset+=count;
                } else values[field.id] = await mediaName(media[type][offset++]);
            }
        }
        return values;
    }

    root.ComfyWorkflowFields = {inferType, definitionField, normalizeWorkflow, dropdownOptions, kind, missingMessage, requireMedia, coerceValue, paramsFromValues, canvasValues, runtimeFields, executionState, isLink};
})(typeof window === 'undefined' ? globalThis : window);
