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
        const config = completeFrameFields(data.workflow || {},data.config || {fields:[]});
        return {...data, config:{...config, fields:(config.fields || []).map(field => {
            // Repair the old filename/file heuristic without changing IDs or other controls.
            const raw = data.workflow?.[field.node]?.inputs?.[field.input];
            const definition = data.definitions?.[data.workflow?.[field.node]?.class_type];
            const profile = definitionField(raw,field.input,definition);
            const nativeFloat=data.workflow?.[field.node]?.class_type==='PrimitiveFloat' && field.input==='value';
            field = {...field,value_type:profile.value_type || (nativeFloat?'number':'') || field.value_type || valueType(raw) || ''};
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

    function imageInputCandidates(workflow={}){
        // Only suggest real file widgets on known loaders; never replace IMAGE links.
        return Object.entries(workflow).flatMap(([node,data])=>{
            if(data.class_type!=='LoadImage' || typeof data.inputs?.image!=='string')return [];
            const targets=Object.entries(workflow).flatMap(([id,target])=>Object.entries(target.inputs || {})
                .filter(([,v])=>isLink(workflow,v) && String(v[0])===node)
                .map(([input])=>({node:id,input})));
            if(!targets.length)return [];
            const roles=[...new Set(targets.map(t=>t.input).filter(key=>['first_frame','last_frame'].includes(key)))];
            const name=roles.length===1 ? (roles[0]==='first_frame'?'首帧图片':'尾帧图片') : `图片 #${node}`;
            return [{node,input:'image',type:'image',name,targets}];
        });
    }

    function imageMappingSummary(workflow,config,english=false,frameMode){
        const slots=frameSlots(workflow);
        const fields=runtimeFields(frameMode ? frameConfig(workflow,config,frameMode) : config).filter(f=>kind(f)==='image');
        const disabled=new Set(slots.filter(s=>frameMode && frameMode!=='both' && s.port!==frameMode+'_frame').map(s=>s.target+'.'+s.port));
        const matches=(field,source)=>field.type==='image_group' ? field.source_nodes.includes(source)
            : String(field.node)===source && field.input==='image';
        const unmapped=imageInputCandidates(workflow).filter(c=>c.targets.some(t=>!disabled.has(t.node+'.'+t.input))
            && !fields.some(f=>matches(f,c.node)));
        const sourceLabel=(field,index)=>field.type==='image_group' ? `${field.name} (${field.min_images}–${field.max_images})`
            : `${english?'Image':'图片'} ${Number.isInteger(field.media_index)?field.media_index+1:index+1}`;
        const frames=slots.map(slot=>{
            const first=slot.port==='first_frame',label=english?(first?'First frame':'Last frame'):(first?'首帧':'尾帧');
            if(disabled.has(slot.target+'.'+slot.port))return `${label}：${english?'Disabled':'未启用'}`;
            const index=fields.findIndex(field=>matches(field,slot.source));
            return `${label}${english?'':'图片'}：${index<0?(english?'Not mapped':'未映射'):sourceLabel(fields[index],index)}`;
        });
        const mapped=fields.flatMap((f,i)=>{
            if(slots.some(s=>!disabled.has(s.target+'.'+s.port) && matches(f,s.source)))return [];
            return [f.type==='image_group' ? sourceLabel(f,i) : `${f.name || f.input} ← ${sourceLabel(f,i)}`];
        }).join(' · ');
        const warning=unmapped.length ? (english ? 'Template images are still fixed: ' : '仍使用模板图片：')+unmapped.map(c=>c.name).join('、')
            +(english?'; map them in Workflow Settings.':'；可在工作流设置中补齐映射。') : '';
        return [...frames,mapped,warning].filter(Boolean).join('；');
    }

    function frameSlots(workflow={}){
        return Object.entries(workflow).flatMap(([target,node])=>node.class_type!=='MiniMaxH3ImageToVideo'?[]:
            ['first_frame','last_frame'].flatMap(port=>{
                const value=node.inputs?.[port];
                return isLink(workflow,value) && value[1]===0 && workflow[value[0]].class_type==='LoadImage'
                    ? [{target,port,source:String(value[0])}] : [];
            }));
    }
    function completeFrameFields(workflow,config){
        const fields=(config.fields || []).map(f=>({...f}));
        for(const slot of frameSlots(workflow)){
            if((config.image_groups || []).some(g=>g.source_nodes.includes(slot.source)))continue;
            const field=fields.find(f=>String(f.node)===slot.source && f.input==='image');
            const name=slot.port==='first_frame'?'首帧图片':'尾帧图片';
            if(field){field.type='image';field.default='';if(!field.name || ['图片','image'].includes(field.name))field.name=name;}
            else fields.push({id:'ice_frame:'+slot.source,node:slot.source,input:'image',name,type:'image',role:'parameter',default:''});
        }
        return {...config,fields};
    }
    function frameConfig(workflow,config,mode){
        config=completeFrameFields(workflow,config);
        if(!mode)return config;
        const slots=frameSlots(workflow);
        if(!['first','last','both'].includes(mode) || new Set(slots.map(s=>s.target)).size!==1 || slots.length!==2)
            throw new Error('此工作流不支持所选首尾帧模式；请重新选择工作流');
        const disabled=new Set(slots.filter(s=>mode!=='both' && s.port!==mode+'_frame').map(s=>s.target+'.'+s.port));
        const unused=new Set(slots.map(s=>s.source).filter(source=>{
            const targets=Object.entries(workflow).flatMap(([id,node])=>Object.entries(node.inputs || {})
                .filter(([,v])=>isLink(workflow,v) && String(v[0])===source).map(([key])=>id+'.'+key));
            return targets.length && targets.every(t=>disabled.has(t));
        }));
        return {...config,fields:config.fields.filter(f=>!unused.has(String(f.node)) || f.input!=='image')};
    }
    function frameOptionsHtml(workflow,options={},attribute='data-field',english=false){
        const slots=frameSlots(workflow);
        if(slots.length!==2 || new Set(slots.map(s=>s.target)).size!==1)return '';
        const mode=options.comfyFrameMode || 'both';
        const choices=english?[['first','First frame + prompt'],['last','Last frame + prompt'],['both','First + last frames + prompt']]
            :[['first','首帧 + 提示词'],['last','尾帧 + 提示词'],['both','首尾帧 + 提示词']];
        return `<label class="field comfy-frame-mode"><span class="setting-title">${english?'Keyframe inputs':'图片输入模式'}</span><select class="select-lite" aria-label="图片输入模式" ${attribute}="comfyFrameMode">${choices.map(([value,label])=>`<option value="${value}" ${mode===value?'selected':''}>${label}</option>`).join('')}</select></label>`;
    }

    function imageUploadQuery(options={}){
        const mode=options.comfyImageMode || 'off';
        if(mode==='off')return {};
        const edge=mode==='lossless'?0:Number(mode==='custom'?options.comfyImageMaxEdge:mode);
        if(!Number.isInteger(edge) || edge<0 || edge>16384 || mode!=='lossless' && edge<64)
            throw new Error('图片长边上限需为 64–16384 像素');
        return {image_max_edge:String(edge),image_lossless:'true'};
    }

    function imageOptionsHtml(options={},attribute='data-field',english=false){
        const mode=options.comfyImageMode || 'off',edge=Number(options.comfyImageMaxEdge) || 2048;
        const choices=english?[['off','Off (original)'],['lossless','Lossless only'],['2048','2K long edge'],['4096','4K long edge'],['custom','Custom long edge']]
            :[['off','关闭（使用原图）'],['lossless','仅无损压缩'],['2048','长边不超过 2K'],['4096','长边不超过 4K'],['custom','自定义长边']];
        return `<details class="comfy-image-options-panel" ${mode==='custom'?'open':''}><summary onmousedown="event.stopPropagation()" onclick="event.stopPropagation()">${english?'Input optimization':'输入图片优化'}：${choices.find(([value])=>value===mode)?.[1] || choices[0][1]}</summary><label class="field comfy-image-options"><span class="setting-title">${english?'Input image optimization':'输入图片优化'}</span><select class="select-lite" aria-label="输入图片优化" ${attribute}="comfyImageMode">${choices.map(([value,label])=>`<option value="${value}" ${mode===value?'selected':''}>${label}</option>`).join('')}</select></label>${mode==='custom'?`<input class="setting-input" type="number" aria-label="图片长边上限" min="64" max="16384" step="1" ${attribute}="comfyImageMaxEdge" value="${edge}">`:''}<div class="comfy-image-help">${english?'Originals are kept. Resizing changes resolution; lossless compression alone does not reduce GPU memory.':'原图保留，仅处理提交副本。缩小尺寸会改变分辨率；仅压缩文件不能降低显存需求。'}</div></details>`;
    }

    function imageUploadDescription(info){
        if(!info)return '';
        const mb=n=>(n/1048576).toFixed(2)+' MB';
        return `${info.original_width}×${info.original_height} → ${info.width}×${info.height} · ${mb(info.original_bytes)} → ${mb(info.bytes)}`;
    }

    function mediaBindings(config,media,english=false){
        const bindings=[];
        for(const type of mediaKinds){
            const refs=media[type] || [],fields=runtimeFields(config).filter(f=>kind(f)===type),used=new Set();
            let offset=0;
            for(let i=0;i<fields.length;i++){
                const field=fields[i];let indices;
                if(field.type==='image_group'){
                    const remaining=fields.slice(i+1).reduce((n,f)=>n+(f.type==='image_group'?f.min_images:f.media_index==null?1:0),0);
                    const count=Math.min(field.max_images,refs.length-offset-remaining);
                    if(count<field.min_images)throw new Error(missingMessage([field],english));
                    indices=Array.from({length:count},(_,j)=>offset+j);offset+=count;
                }else{
                    const index=field.media_index ?? offset;
                    if(!Number.isInteger(index) || index<0)throw new Error(english?'Invalid media input mapping':'媒体输入映射无效，请在工作流设置中重新选择');
                    indices=[index];offset++;
                    if(index>=refs.length)throw new Error(missingMessage([field],english));
                }
                indices.forEach(index=>used.add(index));bindings.push({field,type,indices});
            }
            if(refs.some((_,index)=>!used.has(index))){
                const label=english?type:({image:'图片',video:'视频',audio:'音频'}[type]);
                if(fields.some(f=>f.type==='image_group'))throw new Error(english ? `At most ${used.size} images are accepted; remove unused connections.` : `此工作流最多接收 ${used.size} 张图片；请移除多余连接`);
                throw new Error(english ? `Connected ${label} would be ignored. Map inputs in Workflow Settings or remove unused connections.`
                    : `有连接的${label}未映射到工作流输入；请在工作流设置中补齐映射，或移除多余连接。`);
            }
        }
        return bindings;
    }

    function requireMedia(config, media, english=false){
        mediaBindings(config,media,english);
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
            if(values.__ice_frame_mode && kind(field)==='image' && !Object.hasOwn(values,field.id))return;
            if(field.input==='image' && (config.image_groups || []).some(group=>group.source_nodes.includes(field.node)))return;
            (params[field.node] ||= {})[field.input] = coerceValue(field, values[field.id]);
        });
        return params;
    }

    async function canvasValues(config, {prompt='', media={}, parameters={}, mediaName, randomValue, english=false, workflow,frameMode}){
        if(workflow)config=frameConfig(workflow,config,frameMode);
        const bindings=mediaBindings(config,media,english);
        const values = {};
        if(frameMode)values.__ice_frame_mode=frameMode;
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
        const names=new Map();
        for(const {field,type,indices} of bindings){
            const uploaded=await Promise.all(indices.map(index=>{
                const key=type+':'+index;
                if(!names.has(key))names.set(key,Promise.resolve().then(()=>mediaName(media[type][index])));
                return names.get(key);
            }));
            values[field.id]=field.type==='image_group'?uploaded:uploaded[0];
        }
        return values;
    }

    root.ComfyWorkflowFields = {inferType, definitionField, normalizeWorkflow, dropdownOptions, kind, missingMessage, requireMedia, coerceValue, paramsFromValues, canvasValues, runtimeFields, executionState, isLink, imageInputCandidates, imageMappingSummary, imageUploadQuery, imageOptionsHtml, imageUploadDescription,frameSlots,completeFrameFields,frameConfig,frameOptionsHtml};
})(typeof window === 'undefined' ? globalThis : window);
