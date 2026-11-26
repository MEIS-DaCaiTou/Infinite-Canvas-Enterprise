/* Marketing layer separation. The adapter owns tasks, assets and canvas saves.
 * UI reference: Jimeng 8774.e122134eb9; region prompt: module 40399.
 * Public UI has smart/selection/description modes; server prompts are not public.
 */
(function(root){
    const clamp=(n,min=0,max=1)=>Math.min(max,Math.max(min,n));
    const rounded=n=>Math.round(n*100)/100;
    const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const t=key=>root.StudioI18n.t('layers.'+key);
    const icon=name=>`<i data-lucide="${name}"></i>`;
    function modelsFor(config){
        return (config.api_providers||[]).filter(p=>p.enabled!==false).flatMap(p=>(p.image_models||[])
            .filter(model=>p.builtin_model_image_profiles?.[model]?.supports_layer_options===true)
            .map(model=>({key:p.id+'|'+model,provider_id:p.id,model,label:(p.name||p.id)+' · '+model,
                profile:p.builtin_model_image_profiles[model].layer_profile||p.builtin_model_image_profiles[model]})));
    }
    function regionFromPoints(start,end){
        const x=clamp(Math.min(start.x,end.x)),y=clamp(Math.min(start.y,end.y));
        return {x:rounded(x),y:rounded(y),width:rounded(clamp(Math.max(start.x,end.x))-x),height:rounded(clamp(Math.max(start.y,end.y))-y)};
    }
    function moveRegion(region,dx,dy){return {...region,x:rounded(clamp(region.x+dx,0,1-region.width)),y:rounded(clamp(region.y+dy,0,1-region.height))};}
    function resizeRegion(region,corner,dx,dy){
        let {x,y,width,height}=region,right=x+width,bottom=y+height;
        if(corner.includes('w'))x=clamp(x+dx,0,right-.01);else right=clamp(right+dx,x+.01,1);
        if(corner.includes('n'))y=clamp(y+dy,0,bottom-.01);else bottom=clamp(bottom+dy,y+.01,1);
        return {x:rounded(x),y:rounded(y),width:rounded(right-x),height:rounded(bottom-y)};
    }
    function sourceRegion(region,geometry){
        if(!geometry||geometry.fit!=='cover')return region;
        const scale=Math.max(geometry.width/geometry.naturalWidth,geometry.height/geometry.naturalHeight);
        const fullW=geometry.naturalWidth*scale,fullH=geometry.naturalHeight*scale;
        return {x:(region.x*geometry.width+(fullW-geometry.width)/2)/fullW,
            y:(region.y*geometry.height+(fullH-geometry.height)/2)/fullH,
            width:region.width*geometry.width/fullW,height:region.height*geometry.height/fullH};
    }
    function promptFor(text,region){
        const prompt=String(text||'').trim();
        if(!region)return prompt;
        const percent=n=>Math.round(clamp(n)*100)+'%';
        const area=`只拆分位于图片区域内的元素：横向 ${percent(region.x)}–${percent(region.x+region.width)}，纵向 ${percent(region.y)}–${percent(region.y+region.height)}（以左上角为原点）`;
        return prompt?prompt+'\n'+area:area;
    }
    function parameters(state,model,fallback){
        if(!model)throw new Error(t('noProvider'));
        if(model.profile?.supports_layer_limit===false&&state.limit!=='' || model.profile?.supports_layer_text_recognition===false&&state.recognize)throw new Error(t('channelOptionsUnavailable'));
        if(state.mode==='selection'&&(!state.region||state.region.width<=0||state.region.height<=0))throw new Error(t('regionRequired'));
        if(state.mode==='description'&&!state.prompt.trim())throw new Error(t('descriptionRequired'));
        if(state.limit!==''&&(!Number.isInteger(Number(state.limit))||Number(state.limit)<1||Number(state.limit)>99))throw new Error(t('limitHint'));
        const region=state.mode==='selection'?sourceRegion(state.region,state.geometry):null;
        return {provider_id:model.provider_id,model:model.model,size:state.size,
            prompt:promptFor(state.mode==='smart'?'':state.prompt,region)||(model.profile?.supports_empty_layer_prompt?'':fallback),
            layer_options:{...(state.limit!==''?{max_images:Number(state.limit)+1}:{}),text_recognition:state.recognize}};
    }
    class Separation{
        constructor(adapter){
            this.adapter=adapter;this.portal=document.createElement('div');this.portal.className='canvas-layer-separation';this.portal.hidden=true;document.body.append(this.portal);
            this.portal.addEventListener('pointerdown',e=>e.stopPropagation());
            this.portal.addEventListener('click',e=>this.click(e));
            this.portal.addEventListener('input',e=>this.change(e));
            this.portal.addEventListener('change',e=>this.change(e));
            this.portal.addEventListener('keydown',e=>{e.stopPropagation();if(e.key==='Escape'){e.preventDefault();this.close();}
                else if(e.target.tagName==='TEXTAREA'&&e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();this.portal.querySelector('[data-separate-action=submit]:not(:disabled)')?.click();}});
            this.selection=document.createElement('div');this.selection.className='layer-separation-region';this.selection.hidden=true;
            this.selection.tabIndex=0;this.selection.setAttribute('role','group');document.body.append(this.selection);
            this.selection.addEventListener('pointerdown',e=>this.startRegion(e));
            this.selection.addEventListener('keydown',e=>this.keyRegion(e));
            this.outside=e=>{if(!this.portal.hidden&&!(root.StudioDropdowns?.contains(this.portal,e.target)??this.portal.contains(e.target))&&!this.selection.contains(e.target)&&!e.target.closest('[data-smart-node-action=marketing]'))this.close();};
            document.addEventListener('pointerdown',this.outside);
            window.addEventListener('studio-lang-change',()=>{if(this.state)this.render();});
        }
        menu(nodeId,anchor){
            this.close();this.nodeId=nodeId;this.portal.hidden=false;this.adapter.onOpen?.();
            const actions=this.adapter.marketingActions||[];
            this.portal.innerHTML=`<div class="layer-marketing-menu" role="menu" aria-label="${esc(t('marketing'))}"><div class="layer-marketing-caption">${esc(t('marketing'))}</div>${actions.map(action=>`<button role="menuitem" data-separate-action="${esc(action.id)}">${icon(action.icon)}<span>${esc(action.label())}<small>${esc(action.description())}</small></span></button>`).join('')}<button role="menuitem" data-separate-action="open">${icon('layers')}<span>${esc(t('split'))}<small>${esc(t('splitDescription'))}</small></span></button></div>`;
            const r=anchor.getBoundingClientRect();Object.assign(this.portal.style,{left:Math.max(8,Math.min(innerWidth-300,r.left))+'px',top:Math.max(8,Math.min(innerHeight-this.portal.offsetHeight-8,r.bottom+8))+'px'});root.lucide?.createIcons({root:this.portal});
        }
        async open(nodeId,index=0){
            this.close();const node=this.adapter.node(nodeId);if(!node)return;
            const reference={...node.images[index]};if(!reference.url)return;
            this.nodeId=nodeId;this.index=index;this.state={mode:'smart',prompt:'',recognize:false,limit:'',size:'auto',region:null,modelKey:'',settings:false,busy:false,error:'',reference};
            const state=this.state;this.portal.hidden=false;this.adapter.onOpen?.();this.render();this.layout();
            this.tick=()=>{if(!this.state)return;this.layout();this.frame=requestAnimationFrame(this.tick);};this.frame=requestAnimationFrame(this.tick);
            try{
                const response=await fetch('/api/config');if(!response.ok)throw new Error(t('noProvider'));
                const models=modelsFor(await response.json());if(this.state!==state)return;
                this.models=models;const saved=node.layerSettings||node.runSettings;
                state.modelKey=models.find(m=>m.provider_id===saved?.provider_id&&m.model===saved?.model)?.key||models[0]?.key||'';
                this.render();
            }catch(error){if(this.state===state){state.error=error.message;this.render();}}
        }
        close(){this.state=null;cancelAnimationFrame(this.frame);this.portal.hidden=true;this.selection.hidden=true;this.adapter.onClose?.();}
        render(){
            const s=this.state;if(!s)return;
            const model=this.models?.find(m=>m.key===s.modelKey),sizes=model?.profile.resolutions||['1K','1.5K','2K'];
            this.portal.innerHTML=`<section class="layer-separation-panel" role="region" aria-label="${esc(t('split'))}" data-testid="layer-decompose-panel" data-layout="${s.mode==='smart'?'compact':'expanded'}">
                <div class="layer-separation-top" role="group" aria-label="${esc(t('split'))}">${[['smart','smartSplit','sparkles'],['selection','selectionSplit','scan'],['description','descriptionSplit','text']].map(([mode,label,ico])=>`<button type="button" data-separate-action="mode-${mode}" aria-pressed="${s.mode===mode}" ${s.busy?'disabled':''}>${icon(ico)}${esc(t(label))}</button>`).join('')}
                <span class="separation-divider"></span><label><input type="checkbox" data-separate-setting="recognize" ${s.recognize?'checked':''} ${model?.profile.supports_layer_text_recognition===false?'disabled':''}>${esc(t('extractText'))}</label></div>
                ${s.mode!=='smart'?`<div class="layer-separation-prompt">${s.mode==='selection'&&s.region?`<button class="layer-region-chip" data-separate-action="clear-region">${esc(t('region'))} ×</button>`:''}<textarea maxlength="800" data-separate-setting="prompt" aria-label="${esc(t(s.mode==='selection'?'selectionHint':'descriptionHint'))}" placeholder="${esc(t(s.mode==='selection'?'selectionHint':'descriptionHint'))}">${esc(s.prompt)}</textarea></div>`:''}
                <div class="layer-separation-actions"><button class="layer-separation-settings-toggle" data-separate-action="settings" title="${esc(t('settings'))}" aria-label="${esc(t('settings'))}">${icon('sliders-horizontal')}</button><button class="layer-separation-submit" data-separate-action="submit" ${s.busy||!model||s.mode==='description'&&!s.prompt.trim()||s.mode==='selection'&&!s.region?'disabled':''}>${esc(t(s.busy?'working':'confirmSplit'))}</button><button class="layer-separation-close" data-separate-action="close" aria-label="${esc(t('close'))}">${icon('x')}</button></div>
                ${s.settings?`<div class="layer-separation-settings"><label>${esc(t('provider'))}<select data-separate-setting="modelKey">${(this.models||[]).map(m=>`<option value="${esc(m.key)}" ${m.key===s.modelKey?'selected':''}>${esc(m.label)}</option>`).join('')}</select></label><div class="layer-fields"><label>${esc(t('limit'))}<input data-separate-setting="limit" type="number" min="1" max="99" placeholder="${esc(t('auto'))}" value="${esc(s.limit)}" ${model?.profile.supports_layer_limit===false?'disabled':''}></label><label>${esc(t('resolution'))}<select data-separate-setting="size">${['auto',...sizes].map(size=>`<option ${s.size===size?'selected':''}>${size}</option>`).join('')}</select></label></div><p>${esc(t(model?.profile.supports_layer_limit===false?'channelOptionsUnavailable':'limitHint'))}</p></div>`:''}
                <div class="layer-separation-message" role="status">${esc(s.error)}</div></section>`;
            this.selection.setAttribute('aria-label',t('regionKeyboardHint'));
            root.lucide?.createIcons({root:this.portal});this.paintRegion();this.layout();
        }
        change(event){
            const key=event.target.dataset.separateSetting,s=this.state;if(!key||!s)return;
            s[key]=event.target.type==='checkbox'?event.target.checked:event.target.value;
            if(key==='modelKey'){
                const profile=this.models.find(m=>m.key===s.modelKey)?.profile;
                s.size='auto';if(profile?.supports_layer_limit===false)s.limit='';if(profile?.supports_layer_text_recognition===false)s.recognize=false;this.render();
            }
            if(key==='prompt')this.portal.querySelector('[data-separate-action=submit]').disabled=s.busy||!s.modelKey||s.mode==='description'&&!s.prompt.trim()||s.mode==='selection'&&!s.region;
        }
        async click(event){
            const action=event.target.closest('[data-separate-action]')?.dataset.separateAction;if(!action)return;event.preventDefault();
            const marketing=(this.adapter.marketingActions||[]).find(item=>item.id===action);
            if(marketing){const id=this.nodeId;this.close();await marketing.open(id,this.adapter.index(id));return;}
            if(action==='open'){await this.open(this.nodeId,this.adapter.index(this.nodeId));return;}
            const s=this.state;if(!s||s.busy)return;
            if(action==='close'){this.close();return;}
            if(action==='settings'){s.settings=!s.settings;this.render();return;}
            if(action==='clear-region'){s.region=null;this.render();return;}
            if(action.startsWith('mode-')){s.mode=action.slice(5);s.error='';this.render();if(s.mode==='selection')this.selection.focus();return;}
            if(action==='submit'){
                try{
                    const body=parameters(s,this.models.find(m=>m.key===s.modelKey),t('smartSplitPrompt'));
                    s.busy=true;s.error='';this.render();
                    await this.adapter.separate(this.nodeId,this.index,{...body,_reference:s.reference});
                    if(this.state===s)this.close();
                }catch(error){if(this.state===s){s.busy=false;s.error=error.message;this.render();}}
            }
        }
        layout(){
            if(!this.state)return;
            const r=this.adapter.bounds(this.nodeId,this.index);if(!r){this.close();return;}
            this.state.geometry=r;
            const width=this.portal.offsetWidth,height=this.portal.offsetHeight;
            Object.assign(this.portal.style,{left:clamp(r.x+r.width/2-width/2,12,Math.max(12,innerWidth-width-12))+'px',top:clamp(r.y+r.height+12,12,Math.max(12,innerHeight-height-12))+'px'});
            Object.assign(this.selection.style,{left:r.x+'px',top:r.y+'px',width:r.width+'px',height:r.height+'px'});
            this.selection.hidden=this.state.mode!=='selection';
        }
        paintRegion(){
            const r=this.state?.region;
            this.selection.innerHTML=r?`<div class="layer-separation-box" data-region-move style="left:${r.x*100}%;top:${r.y*100}%;width:${r.width*100}%;height:${r.height*100}%"><button data-separate-region-clear aria-label="${esc(t('cancel'))}">×</button>${['nw','ne','sw','se'].map(c=>`<span role="button" tabindex="0" data-region-corner="${c}" aria-label="${esc(t('resizeRegion'))}" class="region-${c}"></span>`).join('')}</div>`:'';
        }
        startRegion(event){
            const s=this.state;if(!s||s.busy||event.button!==0)return;event.preventDefault();event.stopPropagation();
            if(event.target.hasAttribute('data-separate-region-clear')){s.region=null;this.render();return;}
            const r=this.selection.getBoundingClientRect(),start={x:(event.clientX-r.x)/r.width,y:(event.clientY-r.y)/r.height},before=s.region?{...s.region}:null;
            const corner=event.target.dataset.regionCorner,move=event.target.closest('[data-region-move]');
            this.selection.setPointerCapture(event.pointerId);
            const update=e=>{const current={x:(e.clientX-r.x)/r.width,y:(e.clientY-r.y)/r.height},dx=current.x-start.x,dy=current.y-start.y;
                s.region=corner?resizeRegion(before,corner,dx,dy):move?moveRegion(before,dx,dy):regionFromPoints(start,current);this.paintRegion();};
            this.selection.onpointermove=update;
            this.selection.onpointerup=e=>{update(e);this.selection.onpointermove=null;this.selection.onpointerup=null;if(s.region.width<=0||s.region.height<=0)s.region=null;this.render();};
            this.selection.onpointercancel=()=>{s.region=before;this.selection.onpointermove=null;this.selection.onpointerup=null;this.render();};
        }
        keyRegion(event){
            const s=this.state;if(!s||s.busy)return;event.stopPropagation();
            if(event.key==='Escape'){event.preventDefault();this.close();return;}
            if(!s.region&&['Enter',' '].includes(event.key)){event.preventDefault();s.region={x:.25,y:.25,width:.5,height:.5};this.render();this.selection.focus();return;}
            if(!s.region||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key))return;
            event.preventDefault();const step=event.shiftKey ? .1 : .01,dx=event.key==='ArrowLeft'?-step:event.key==='ArrowRight'?step:0,dy=event.key==='ArrowUp'?-step:event.key==='ArrowDown'?step:0;
            const corner=event.target.dataset.regionCorner;
            s.region=corner?resizeRegion(s.region,corner,dx,dy):moveRegion(s.region,dx,dy);this.paintRegion();
            if(corner)this.selection.querySelector(`[data-region-corner=${corner}]`).focus();
        }
    }
    const api={modelsFor,regionFromPoints,moveRegion,resizeRegion,sourceRegion,promptFor,parameters,install:adapter=>new Separation(adapter)};
    if(typeof module!=='undefined')module.exports=api;root.CanvasLayerSeparation=api;
})(typeof window!=='undefined'?window:globalThis);
