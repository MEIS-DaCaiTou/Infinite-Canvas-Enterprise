/* Marketing multi-size: official public module 32829, chunk 8590.b7a65aea9f.
 * The adapter owns canvas mutation and original image tasks. No image scaling.
 */
(function(root){
    const t=key=>root.StudioI18n.t('multiSize.'+key);
    const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const icon=name=>`<i data-lucide="${name}"></i>`;
    // Sizes and purposes are visible in the owner's 103456 recording.
    const PRESETS=[
        {id:'main',key:'main',width:1200,height:1200},
        {id:'portrait',key:'portrait',width:1200,height:1600},
        {id:'story',key:'story',width:1080,height:1920},
        {id:'video',key:'video',width:1920,height:1080},
        {id:'poster',key:'poster',width:1600,height:1200},
        {id:'cinema',key:'cinema',width:2520,height:1080,aspect_ratio:'21:9'}
    ];
    const dimensions=p=>p.width+'x'+p.height;
    function ratio(p){if(p.aspect_ratio)return p.aspect_ratio;let a=p.width,b=p.height;while(b)[a,b]=[b,a%b];return p.width/a+':'+p.height/a;}
    function modelsFor(config){
        return (config.api_providers||[]).filter(p=>p.enabled!==false).flatMap(p=>(p.image_models||[]).map(model=>({
            key:p.id+'|'+model,provider_id:p.id,model,label:(p.name||p.id)+' · '+model,
            profile:root.CanvasModelPicker.profileFor(p,model),managedSource:p.managed_source_supported===true
        })).filter(m=>m.profile.model_family==='seedream-5.5'&&!m.profile.layer_output&&m.profile.supports_custom_size));
    }
    function sizeError(p,model){
        if(!model)return t('noModel');
        if(![p.width,p.height].every(n=>Number.isSafeInteger(n)&&n>0))return t('invalidSize');
        return root.CanvasModelPicker.sizeError(model.profile,dimensions(p));
    }
    function requestFor(p,model){
        const error=sizeError(p,model);if(error)throw new Error(error);
        return {provider_id:model.provider_id,model:model.model,size:dimensions(p),background_mode:'auto',
            creation_title:t('entry')+' · '+p.name+' '+dimensions(p),
            prompt:`将参考海报重新构图为 ${p.width}×${p.height} 像素、${ratio(p)} 比例的营销图片。保持原有商品和人物身份、服装轮廓、颜色、针织蕾丝面料纹理、Logo、全部文字与价格信息准确完整。延续原图场景和视觉风格，针对新画幅自然重排主体与文字、补足背景空间。人物完整头部和关键服装不可截断，不拉伸或重复主体。文字为固定内容，只允许调整原有文字的位置和字号，必须逐字保留；严禁新增英文装饰、手写文案、符号、Logo、水印或任何其他文字。生成完整新构图，不以加边框或简单拉伸充当尺寸适配。`};
    }
    async function submitTargets(targets,generate){
        // Each target has its own original task, receipt, failure and archive.
        return Promise.allSettled(targets.map(target=>generate(target)));
    }
    class MultiSize{
        constructor(adapter){
            this.adapter=adapter;this.portal=document.createElement('div');this.portal.className='canvas-multi-size';this.portal.hidden=true;document.body.append(this.portal);
            this.portal.addEventListener('pointerdown',event=>event.stopPropagation());
            this.portal.addEventListener('click',event=>this.click(event));
            this.portal.addEventListener('input',event=>this.input(event));
            this.portal.addEventListener('change',event=>this.change(event));
            this.portal.addEventListener('keydown',event=>{event.stopPropagation();if(event.key==='Escape'){event.preventDefault();if(this.state?.form){this.state.form=null;this.render();}else this.close();}});
            document.addEventListener('pointerdown',event=>{if(this.state&&!(root.StudioDropdowns?.contains(this.portal,event.target)??this.portal.contains(event.target))&&!event.target.closest('[data-smart-node-action=marketing]'))this.close();});
            window.addEventListener('studio-lang-change',()=>{if(this.state)this.render();});
        }
        async api(path='',options){
            const response=await fetch('/enterprise/api/me/image-size-presets'+path,options),value=await response.json();
            if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:t('saveFailed'));
            return value;
        }
        async open(nodeId,index){
            this.close();const node=this.adapter.node(nodeId);if(!node?.images[index]?.url)return;
            const state=this.state={nodeId,index,reference:{...node.images[index]},custom:[],selected:new Set(),modelKey:'',error:'',busy:false,settings:false,form:null};
            this.portal.hidden=false;this.adapter.onOpen?.();this.render();
            this.tick=()=>{if(!this.state)return;this.layout();this.frame=requestAnimationFrame(this.tick);};this.frame=requestAnimationFrame(this.tick);
            try{
                const [response,personal]=await Promise.all([fetch('/api/config'),this.api()]);
                if(!response.ok)throw new Error(t('noModel'));
                const models=modelsFor(await response.json());if(this.state!==state)return;
                state.models=models;state.custom=personal.presets;
                const saved=node.runSettings;
                state.modelKey=models.find(m=>m.provider_id===saved?.provider_id&&m.model===saved?.model)?.key||models[0]?.key||'';
                this.readSource(state);this.render();
            }catch(error){if(this.state===state){state.error=error.message;this.render();}}
        }
        close(){this.state=null;cancelAnimationFrame(this.frame);this.portal.hidden=true;this.adapter.onClose?.();}
        targets(){return [...PRESETS.map(p=>({...p,id:'system:'+p.id,name:t(p.key)})),...this.state.custom];}
        model(){return this.state.models?.find(m=>m.key===this.state.modelKey);}
        selected(){return this.targets().filter(p=>this.state.selected.has(p.id));}
        async readSource(s){
            const model=this.model(),key=s.modelKey;s.authorization='loading';
            try{
                const result=model?.managedSource?await this.adapter.sourcePreview(model.provider_id):{state:'legacy'};
                if(this.state===s&&s.modelKey===key){s.authorization=result.state;this.render();}
            }catch(error){if(this.state===s&&s.modelKey===key){s.authorization='unconfirmed';this.render();}}
        }
        render(){
            const s=this.state;if(!s)return;
            const selected=this.selected(),model=this.model(),error=selected.map(p=>sizeError(p,model)).find(Boolean);
            const denied=s.authorization==='not_authorized',checking=s.authorization==='loading';
            this.portal.innerHTML=`<section role="region" aria-label="${esc(t('entry'))}" class="multi-size-panel" data-testid="marketing-multi-size-panel">
                <header><strong>${esc(t('choose'))}${selected.length?' ('+selected.length+')':''}</strong><button data-ms-action="close" aria-label="${esc(t('close'))}">${icon('x')}</button></header>
                <div class="multi-size-list">${this.targets().map(p=>{
                    const reason=sizeError(p,model),checked=s.selected.has(p.id),custom=!p.key;
                    return `<div class="multi-size-row" ${reason?`title="${esc(reason)}"`:''}><label><input type="checkbox" data-ms-id="${esc(p.id)}" ${checked?'checked':''} ${s.busy||reason&&!checked||selected.length>=20&&!checked?'disabled':''}><span class="multi-size-shape" style="--size-ratio:${p.width/p.height}"></span><span class="multi-size-name">${esc(p.name)} <b>${ratio(p)}</b></span><small>${dimensions(p)}px</small></label>${custom?`<button data-ms-action="edit" data-ms-id="${esc(p.id)}" aria-label="${esc(t('edit')+' '+p.name)}">${icon('pencil')}</button>`:''}</div>`;
                }).join('')}</div>
                ${s.settings?`<div class="multi-size-model"><label>${esc(t('model'))}<select data-ms-model ${s.busy?'disabled':''}>${(s.models||[]).map(m=>`<option value="${esc(m.key)}" ${m.key===s.modelKey?'selected':''}>${esc(m.label)}</option>`).join('')}</select></label></div>`:''}
                <footer><button data-ms-action="add" ${s.busy?'disabled':''}>${icon('plus')}${esc(t('add'))}</button><button data-ms-action="settings" aria-label="${esc(t('settings'))}">${icon('sliders-horizontal')}</button><button class="multi-size-generate" data-ms-action="generate" ${s.busy||!selected.length||error||denied||checking?'disabled':''}>${esc(t(s.busy?'submitting':'generate'))}</button></footer>
                <div role="status" class="multi-size-status">${esc(s.error||error||(denied?t('notAuthorized'):checking?t('checkingSource'):''))}</div>
            </section>${s.form?this.formHtml():''}`;
            root.lucide?.createIcons({root:this.portal});this.layout();
        }
        formHtml(){
            const f=this.state.form;
            return `<section role="dialog" aria-modal="false" aria-label="${esc(t(f.id?'edit':'add'))}" class="multi-size-form"><strong>${esc(t(f.id?'edit':'add'))}</strong>
                <label>${esc(t('size'))}<div class="multi-size-dimensions"><input type="number" min="1" data-ms-field="width" aria-label="${esc(t('width'))}" value="${esc(f.width)}" ${this.state.busy?'disabled':''}><span>×</span><input type="number" min="1" data-ms-field="height" aria-label="${esc(t('height'))}" value="${esc(f.height)}" ${this.state.busy?'disabled':''}><button data-ms-action="lock" aria-label="${esc(t('lock'))}" aria-pressed="${Boolean(f.ratio)}">${icon(f.ratio?'link':'unlink')}</button></div></label>
                <label>${esc(t('name'))}<input data-ms-field="name" maxlength="60" placeholder="${esc(t('nameHint'))}" value="${esc(f.name)}" ${this.state.busy?'disabled':''}></label>
                <div class="multi-size-form-error" role="status">${esc(this.formError())}</div><div class="multi-size-form-actions">${f.id?`<button data-ms-action="delete">${esc(t('remove'))}</button>`:''}<button data-ms-action="cancel">${esc(t('cancel'))}</button><button class="multi-size-generate" data-ms-action="save" ${this.formError()||this.state.busy?'disabled':''}>${esc(t('save'))}</button></div></section>`;
        }
        formError(){const f=this.state.form;return !f.name.trim()?t('nameHint'):sizeError({width:Number(f.width),height:Number(f.height)},this.model());}
        input(event){
            const key=event.target.dataset.msField,s=this.state;if(!key||!s?.form)return;
            const f=s.form;f[key]=event.target.value;
            if(f.ratio&&['width','height'].includes(key)){
                const other=key==='width'?'height':'width',value=Number(f[key]);
                f[other]=String(Math.max(1,Math.round(key==='width'?value/f.ratio:value*f.ratio)));
                this.portal.querySelector(`[data-ms-field=${other}]`).value=f[other];
            }
            this.portal.querySelector('[data-ms-action=save]').disabled=s.busy||Boolean(this.formError());
            this.portal.querySelector('.multi-size-form-error').textContent=this.formError();
        }
        change(event){
            const s=this.state;if(!s||s.busy)return;
            if(event.target.hasAttribute('data-ms-model')){s.modelKey=event.target.value;this.readSource(s);}
            else if(event.target.type==='checkbox'){const id=event.target.dataset.msId;if(event.target.checked)s.selected.add(id);else s.selected.delete(id);}
            else return;
            s.error='';this.render();
        }
        async click(event){
            const control=event.target.closest('[data-ms-action]'),action=control?.dataset.msAction,s=this.state;if(!action||!s)return;event.preventDefault();
            if(action==='close'){this.close();return;}if(s.busy)return;
            if(action==='settings'){s.settings=!s.settings;this.render();return;}
            if(action==='cancel'){s.form=null;this.render();return;}
            if(action==='lock'){s.form.ratio=s.form.ratio?null:Number(s.form.width)/Number(s.form.height);this.render();return;}
            if(action==='add'||action==='edit'){
                const existing=s.custom.find(p=>p.id===control.dataset.msId);
                s.form=existing?{...existing,ratio:null}:{name:'',width:1200,height:1200,ratio:null};this.render();return;
            }
            if(action==='save'||action==='delete'){
                const f=s.form;if(action==='save'&&this.formError())return;s.busy=true;s.error='';this.render();
                try{
                    const path=f.id?'/'+f.id:'',method=action==='delete'?'DELETE':f.id?'PUT':'POST';
                    const value=await this.api(path,{method,headers:{'Content-Type':'application/json'},...(action==='delete'?{}:{body:JSON.stringify({name:f.name.trim(),width:Number(f.width),height:Number(f.height)})})});
                    if(this.state!==s)return;
                    if(action==='delete'){s.custom=s.custom.filter(p=>p.id!==f.id);s.selected.delete(f.id);}
                    else if(f.id)s.custom=s.custom.map(p=>p.id===f.id?value:p);else s.custom.push(value);
                    s.form=null;
                }catch(error){if(this.state===s)s.error=error.message;}
                if(this.state===s){s.busy=false;this.render();}return;
            }
            if(action==='generate'){
                const targets=this.selected();if(!targets.length||targets.length>20||['loading','not_authorized'].includes(s.authorization)||targets.some(p=>sizeError(p,this.model())))return;
                const model=this.model();s.busy=true;s.error='';this.render();
                const results=await submitTargets(targets,p=>this.adapter.generate(s.nodeId,s.index,requestFor(p,model),p,s.reference));
                if(this.state!==s)return;
                results.forEach((result,i)=>{if(result.status==='fulfilled')s.selected.delete(targets[i].id);});
                const failed=results.filter(result=>result.status==='rejected');
                if(!failed.length)this.close();else{s.busy=false;s.error=failed.map(result=>result.reason.message).join('；');this.render();}
            }
        }
        layout(){
            const s=this.state;if(!s)return;const bounds=this.adapter.bounds(s.nodeId,s.index);if(!bounds){this.close();return;}
            const width=this.portal.offsetWidth,height=this.portal.offsetHeight;
            Object.assign(this.portal.style,{left:Math.max(12,Math.min(innerWidth-width-12,bounds.x+bounds.width/2-width/2))+'px',top:Math.max(12,Math.min(innerHeight-height-12,bounds.y+bounds.height+12))+'px'});
        }
    }
    const api={PRESETS,ratio,modelsFor,sizeError,requestFor,submitTargets,install:adapter=>new MultiSize(adapter)};
    if(typeof module!=='undefined')module.exports=api;root.CanvasMultiSize=api;
})(typeof window!=='undefined'?window:globalThis);
