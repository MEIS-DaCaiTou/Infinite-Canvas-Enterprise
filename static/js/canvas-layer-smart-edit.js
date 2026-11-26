/* Focused layer redraw. Public UI reference: Jimeng SmartEditCommerceEditor,
 * 3545.1333477ea9 / imageLayerBoardRedraw. Suppliers still use our image API.
 * The source image, transient editing marks and generated layers stay separate.
 */
(function(root){
    const D=root.CanvasLayerDocument||(typeof require==='function'?require('./canvas-layer-document.js'):null);
    const t=key=>root.StudioI18n.t('layers.'+key),clone=value=>D.clone(value);
    const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const icon=name=>`<i data-lucide="${name}"></i>`,clamp=n=>Math.max(0,Math.min(1,n));
    const hasInstruction=text=>Boolean(text.replace(/【\d+】/g,'').trim());
    const hasAlpha=pixels=>pixels.some((value,index)=>index%4===3&&value<250);
    function modelsFor(config){
        return (config.api_providers||[]).filter(p=>p.enabled!==false).flatMap(p=>(p.image_models||[]).map(model=>({
            key:p.id+'|'+model,provider_id:p.id,model,label:(p.name||p.id)+' · '+model,
            profile:root.CanvasModelPicker.profileFor(p,model),managedSource:p.managed_source_supported===true
        }))).filter(m=>!m.profile.layer_output&&!m.model.endsWith('/layer-decomposition')&&m.profile.max_references!==0);
    }
    function sourceKey(layer){return JSON.stringify([layer.kind,layer.asset?.url,layer.crop,layer.rotation||0,Boolean(layer.flipX),Boolean(layer.flipY)]);}
    function sourceDocument(layer,image){
        const scale=Math.max(image.width*(layer.crop?.width||1)/layer.width,image.height*(layer.crop?.height||1)/layer.height);
        const width=Math.max(1,Math.round(layer.width*scale)),height=Math.max(1,Math.round(layer.height*scale));
        return {width,height,layers:[{...clone(layer),x:0,y:0,width,height,rotation:0,opacity:1,visible:true}]};
    }
    function parametersFor(model,doc,resolution,sizeFor){
        const profile=model.profile,ratio=doc.width+':'+doc.height;
        const size=/^\d+x\d+$/.test(resolution)?resolution:sizeFor(ratio,resolution);
        const parameters={aspect_ratio:ratio,resolution:(profile.fixed_resolution||resolution).toUpperCase()};
        const error=root.CanvasModelPicker.sizeError(profile,size,parameters);
        return {size,parameters,error};
    }
    function resolutionsFor(model,doc,sizeFor){
        if(!model)return [];
        const p=model.profile,values=p.size_presets|| (p.fixed_resolution?[p.fixed_resolution]:p.resolutions?.length?p.resolutions:
            p.supports_image_size===false?['default']:['1K','1.5K','2K','4K',...(p.supports_auto_size?['auto']:[])]);
        return values.map(value=>({value:value.toLowerCase(),label:value==='default'?t('auto'):value,...parametersFor(model,doc,value.toLowerCase(),sizeFor)})).filter(v=>!v.error);
    }
    function protocolPrompt(text,marks){
        const number=n=>Math.round(clamp(n)*1000),point=p=>`(${number(p.x)},${number(p.y)})`;
        const locations=marks.map(m=>{
            if(m.kind==='marker')return `【${m.number}】${m.rect?`框选区域 ${point(m.rect)}–${point({x:m.rect.x+m.rect.width,y:m.rect.y+m.rect.height})}`:`位置 ${point(m.points[0])}`}`;
            if(m.kind==='text')return `文字“${m.text}”的位置 ${point(m.points[0])}`;
            return `${m.kind==='arrow'?'箭头':'画笔'}指示 ${point(m.points[0])}–${point(m.points.at(-1))}`;
        });
        return text.trim()+'\n保持原图比例、商品身份、服装纹理、文字和未指定修改的内容。'+(marks.length?
            '\n第一张为原图，第二张仅为编辑位置示意，坐标归一化为0–1000。'+locations.join('；')+'。依据用户要求修改对应位置；生成结果中去除定位数字、选框、画笔和箭头等辅助标记，不把示意图当作新商品。':'');
    }
    function applyResult(session,binding,taskId,item){
        if(session.doc.layers.some(l=>l.editTaskId===taskId))return 'applied';
        const original=session.doc.layers.find(l=>l.id===binding.layerId);
        if(!original||sourceKey(original)!==binding.sourceKey)return 'source-changed';
        if(session.selected===original.id&&['crop','mask'].includes(session.tool))return 'source-changed';
        session.remember();
        const replacement={...clone(original),id:original.id+'-edit-'+taskId,asset:clone(item),visible:true,flipX:false,flipY:false,editTaskId:taskId};
        delete replacement.crop;delete replacement.sourceAsset;delete replacement.sourceNodeId;delete replacement.sourceUrl;
        const w=Number(item.natural_w||item.width),h=Number(item.natural_h||item.height);
        if(w>0&&h>0){const fit=Math.min(original.width/w,original.height/h);replacement.width=w*fit;replacement.height=h*fit;
            replacement.x=original.x+(original.width-replacement.width)/2;replacement.y=original.y+(original.height-replacement.height)/2;}
        original.visible=false;session.doc.layers.splice(session.doc.layers.indexOf(original)+1,0,replacement);if(session.selected===original.id)session.selected=replacement.id;
        return 'applied';
    }
    function outputNotice(node){const binding=node.layerEditTarget,state=binding?.state;
        const key=state==='applied'&&binding.regionEdit?'editRawOutput':state==='alpha-missing'?'editAlphaMissing':state==='source-changed'?'editSourceChanged':'';
        return key?`<div class="smart-image-task-status" role="status"><div>${esc(t(key))}</div></div>`:'';}
    function drawMarks(canvas,marks){
        const ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height,unit=Math.max(w,h)/600;
        ctx.clearRect(0,0,w,h);
        for(const m of marks){
            ctx.save();ctx.strokeStyle=m.color||'#ff4757';ctx.fillStyle=ctx.strokeStyle;ctx.lineWidth=(m.width||4/600)*w;ctx.lineCap='round';ctx.lineJoin='round';
            const points=m.points.map(p=>({x:p.x*w,y:p.y*h})),p=points[0];
            if(m.kind==='marker'){
                ctx.strokeStyle='#26a9ff';ctx.fillStyle='#26a9ff';ctx.lineWidth=2*unit;
                if(m.rect)ctx.strokeRect(m.rect.x*w,m.rect.y*h,m.rect.width*w,m.rect.height*h);
                ctx.beginPath();ctx.arc(p.x,p.y,12*unit,0,Math.PI*2);ctx.fill();ctx.fillStyle='white';ctx.font=`600 ${14*unit}px sans-serif`;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(String(m.number),p.x,p.y);
            }else if(m.kind==='text'){const font=(m.fontSize||.04)*w;ctx.font=`600 ${font}px sans-serif`;ctx.textBaseline='top';String(m.text).split('\n').forEach((line,i)=>ctx.fillText(line,p.x,p.y+i*font*1.25));}
            else{ctx.beginPath();ctx.moveTo(p.x,p.y);points.slice(1).forEach(q=>ctx.lineTo(q.x,q.y));ctx.stroke();
                if(m.kind==='arrow'){const q=points.at(-1),angle=Math.atan2(q.y-p.y,q.x-p.x),len=18*unit;ctx.beginPath();ctx.moveTo(q.x,q.y);ctx.lineTo(q.x-len*Math.cos(angle-.45),q.y-len*Math.sin(angle-.45));ctx.lineTo(q.x-len*Math.cos(angle+.45),q.y-len*Math.sin(angle+.45));ctx.closePath();ctx.fill();}}
            ctx.restore();
        }
    }
    class SmartEdit{
        constructor(adapter,editor){
            this.adapter=adapter;this.editor=editor;this.portal=document.createElement('div');this.portal.className='layer-smart-edit';this.portal.hidden=true;document.body.append(this.portal);
            this.promptEditor=new root.CanvasLayerSmartPrompt.Prompt({remember:()=>this.remember(),change:prompt=>{if(this.state){this.state.prompt=prompt;this.sync();}},select:id=>{if(this.state){this.state.selected=id;this.paint();}}});
            this.portal.addEventListener('pointerdown',e=>e.stopPropagation());this.portal.addEventListener('mousedown',e=>e.stopPropagation());
            this.portal.addEventListener('click',e=>this.click(e));this.portal.addEventListener('change',e=>this.change(e));
            document.addEventListener('pointerdown',e=>{if(this.state&&!this.presentation().contains?.(e.target)&&!(root.StudioDropdowns?.contains(this.portal,e.target)??this.portal.contains(e.target)))this.close();},true);
            document.addEventListener('keydown',e=>this.keydown(e),true);
            document.addEventListener('keyup',e=>{if(e.code==='Space'&&this.state)this.state.pan=false;});
            window.addEventListener('studio-lang-change',()=>{if(this.state)this.render();});
        }
        owns(id){return this.state?.nodeId===id;}
        presentation(){return this.state?.presentation||this.adapter;}
        async open(nodeId,layerId,presentation){
            this.close();const node=this.adapter.node(nodeId),session=CanvasLayerSession.get(node),layer=session.doc.layers.find(l=>l.id===layerId);
            if(!layer||layer.kind!=='image'||!layer.visible)return;
            if(layer.rotation%360||layer.flipX||layer.flipY)throw Error(t('editResetTransform'));
            const saved=node.layerSmartEdit||{},state=this.state={nodeId,layerId,session,presentation,source:clone(layer),sourceKey:sourceKey(layer),marks:[],undo:[],redo:[],tool:'marker',textColor:'#ff3355',prompt:'',selected:'',models:[],modelKey:'',resolution:saved.resolution||'',authorization:'loading',preparing:true,error:'',pendingTaskId:this.adapter.pendingEdit(nodeId,layerId)};
            const host=this.presentation();host.onEditOpen();(host.container?.()||document.body).append(this.portal);this.portal.classList.toggle('is-fullscreen',Boolean(host.fullscreen));
            this.portal.hidden=false;this.render();
            try{
                const response=await fetch('/api/config');if(!response.ok)throw Error(t('editNoModel'));
                const config=await response.json(),image=await this.editor.loadImage(layer.asset.url,false);if(this.state!==state)return;
                state.document=sourceDocument(layer,image);state.base=document.createElement('canvas');await D.paint(state.document,state.base,{loadImage:url=>this.editor.loadImage(url,false)});if(this.state!==state)return;
                const rgba=state.base.getContext('2d').getImageData(0,0,state.base.width,state.base.height).data;
                state.transparent=hasAlpha(rgba);
                state.models=modelsFor(config);
                const savedKey=saved.provider_id&&saved.provider_id+'|'+saved.model;
                const prior=[session.imageModelKey,node.runSettings?.provider_id+'|'+node.runSettings?.model,node.layerSettings?.provider_id+'|'+node.layerSettings?.model];
                state.modelKey=savedKey||prior.map(key=>state.models.find(m=>m.key===key)?.key).find(Boolean)||state.models[0]?.key||'';
                this.chooseResolution(state,!state.resolution);state.preparing=false;
                state.viewport=host.focusLayer(nodeId,layerId,state.document);this.render();this.readSource(state);
                this.tick=()=>{if(this.state!==state)return;if(this.adapter.node(nodeId)!==node){this.close(false);return;}this.layout();this.frame=requestAnimationFrame(this.tick);};this.frame=requestAnimationFrame(this.tick);
            }catch(error){if(this.state===state){state.preparing=false;state.error=error.message;this.render();}}
        }
        close(restore=true){const s=this.state;if(!s)return;
            const host=this.presentation();this.state=null;this.textInput?.cancel();
            this.hideMarkGuide();this.promptEditor?.close();cancelAnimationFrame(this.frame);this.portal.hidden=true;this.portal.replaceChildren();if(host.fullscreen)document.body.append(this.portal);if(restore&&s.viewport)host.restoreViewport(s.viewport);host.onEditClose();}
        model(){return this.state?.models.find(m=>m.key===this.state.modelKey);}
        choices(){return this.state?.document?resolutionsFor(this.model(),this.state.document,this.adapter.imageSize):[];}
        chooseResolution(s,initial=false){const options=this.choices();if(initial||!s.resolution)s.resolution=options.find(v=>v.value==='1.5k')?.value||options[0]?.value||'';}
        async readSource(s){
            const model=this.model(),key=s.modelKey;s.authorization='loading';this.sync();
            try{const value=model?.managedSource?await this.adapter.sourcePreview(model.provider_id):{state:'legacy'};
                if(this.state===s&&s.modelKey===key){s.authorization=value.state;this.sync();}}
            catch(error){if(this.state===s&&s.modelKey===key){s.authorization='unconfirmed';s.error=error.message;this.sync();}}
        }
        error(){const s=this.state;if(s.preparing)return t('working');if(s.prompt.length>2000)return t('editPromptLimit');if(!this.model())return t('editNoModel');if(!this.choices().some(c=>c.value===s.resolution))return t('editInvalidSize');
            if(s.transparent&&this.model().profile.supports_transparent_background===false&&!root.CanvasLayerEditResult.regionsFor(s.marks).length)return t('editNativeAlphaUnavailable');
            if(s.authorization==='not_authorized')return t('editNotAuthorized');if(s.authorization==='loading')return t('editCheckingSource');if(s.authorization==='unconfirmed')return t('editSourceUnknown');return '';}
        render(){
            const s=this.state;if(!s)return;const busy=s.preparing||s.submitting||s.pendingTaskId,restoreFocus=this.promptEditor.capture();this.promptEditor.hidePreview();this.hideMarkGuide();
            const tool=(name,label,ico)=>`<button type="button" data-edit-action="${name}" aria-label="${esc(t(label))}" title="${name==='marker'?'':esc(t(label))}" aria-pressed="${s.tool===name}" ${name==='text'?`aria-expanded="${Boolean(s.optionsOpen)}"`:''} ${busy?'disabled':''}>${icon(ico)}${name==='marker'?`<span>${esc(t(label))}</span>`:''}</button>`;
            const options=this.choices();
            this.portal.innerHTML=`<section class="layer-smart-stage" role="region" aria-label="${esc(t('editCanvas'))}" ${s.base?'':'hidden'}><canvas data-edit-base></canvas><canvas data-edit-marks tabindex="0" role="application" aria-label="${esc(t('editMarkHint'))}"></canvas><div class="layer-smart-markers"></div><div class="layer-smart-text-selection" hidden>${['nw','ne','se','sw'].map(c=>`<button type="button" data-text-corner="${c}" aria-label="${esc(t('geometry'))} ${c}"></button>`).join('')}</div></section>
                <div class="layer-smart-controls"><div class="layer-smart-toolbar-shell"><div class="layer-smart-toolbar" role="toolbar" aria-label="${esc(t('editTools'))}">${tool('marker','editMarker','map-pin')}${tool('pen','pen','pencil')}${tool('arrow','arrow','arrow-up-right')}${tool('text','text','type')}${tool('eraser','eraser','eraser')}<span class="layer-smart-divider"></span><button type="button" data-edit-action="undo" aria-label="${esc(t('undo'))}" ${!s.undo.length||s.pendingTaskId?'disabled':''}>${icon('undo-2')}</button><button type="button" data-edit-action="redo" aria-label="${esc(t('redo'))}" ${!s.redo.length||s.pendingTaskId?'disabled':''}>${icon('redo-2')}</button>${!this.presentation().fullscreen?`<span class="layer-smart-divider"></span><button type="button" data-edit-action="close" aria-label="${esc(t('close'))}">${icon('x')}</button>`:''}</div>${s.optionsOpen?`<div class="layer-smart-tool-options">${root.CanvasLayerAnnotations.palette(s.textColor)}</div>`:''}</div>
                <section class="layer-smart-prompt" data-layout="single-line" role="region" aria-label="${esc(t('edit'))}"><div class="layer-smart-prompt-editor" data-edit-prompt role="textbox" aria-multiline="true" data-placeholder="${esc(t('editDescription'))}" aria-label="${esc(t('editDescription'))}" contenteditable="${!busy}" aria-disabled="${Boolean(busy)}"></div><span class="layer-smart-actions-spacer" aria-hidden="true"></span>
                <footer><select data-edit-model aria-label="${esc(t('provider'))}" ${s.preparing||busy?'disabled':''}>${s.models.map(m=>`<option value="${esc(m.key)}" ${m.key===s.modelKey?'selected':''}>${esc(m.label)}</option>`).join('')}${s.modelKey&&!this.model()?`<option selected disabled value="${esc(s.modelKey)}">${esc(s.modelKey)} · ${esc(t('editNoModel'))}</option>`:''}</select><select data-edit-resolution aria-label="${esc(t('resolution'))}" ${s.preparing||busy||options.length===1?'disabled':''}>${options.map(o=>`<option value="${o.value}" ${o.value===s.resolution?'selected':''}>${esc(o.label)}</option>`).join('')}${s.resolution&&!options.some(o=>o.value===s.resolution)?`<option selected disabled value="${esc(s.resolution)}">${esc(s.resolution)} · ${esc(t('editInvalidSize'))}</option>`:''}</select><button type="button" class="layer-smart-submit" data-edit-action="generate" aria-label="${esc(t('runEdit'))}">${icon(s.pendingTaskId?'loader-circle':'arrow-up')}</button></footer></section>
                <div class="layer-smart-status" role="status"></div></div><div class="layer-smart-reference-preview" role="tooltip" aria-label="${esc(t('editMarkerPreview'))}" hidden><div class="layer-smart-reference-preview-window"><canvas></canvas></div><div class="layer-smart-reference-preview-box"></div><span class="layer-smart-reference-preview-pin"></span></div>
                <aside class="layer-smart-marker-guide" role="tooltip" aria-label="${esc(t('editMarkerGuide'))}" hidden><video muted loop playsinline preload="metadata" src="/static/media/smart-edit-marker-guide.mp4" aria-hidden="true"></video><div><strong>${esc(t('editMarkerGuide'))}</strong><p>${esc(t('editMarkerGuideDescription'))}</p></div></aside>`;
            if(s.base){const base=this.portal.querySelector('[data-edit-base]');base.width=s.base.width;base.height=s.base.height;base.getContext('2d').drawImage(s.base,0,0);}
            this.promptEditor.mount(this.portal.querySelector('[data-edit-prompt]'),this.portal.querySelector('.layer-smart-reference-preview'),s.prompt,s.marks,s.base);
            const markerButton=this.portal.querySelector('[data-edit-action=marker]');markerButton.onmouseenter=markerButton.onfocus=()=>this.showMarkGuide();markerButton.onblur=()=>this.hideMarkGuide();markerButton.onmouseleave=()=>{if(document.activeElement!==markerButton)this.hideMarkGuide();};
            this.bindStage();this.paint();root.lucide?.createIcons({root:this.portal});this.layout();this.sync();if(restoreFocus)this.promptEditor.restore(true);
        }
        sync(){const s=this.state;if(!s)return;const error=this.error();this.portal.querySelector('[data-edit-action=generate]').disabled=Boolean(s.preparing||s.submitting||s.pendingTaskId||!hasInstruction(s.prompt)||error);
            this.portal.querySelector('[data-edit-action=undo]').disabled=!s.undo.length||Boolean(s.preparing||s.pendingTaskId||s.submitting);this.portal.querySelector('[data-edit-action=redo]').disabled=!s.redo.length||Boolean(s.preparing||s.pendingTaskId||s.submitting);
            this.portal.querySelector('[data-edit-action=undo]').title=t(s.undo.length?'undo':'noUndo');this.portal.querySelector('[data-edit-action=redo]').title=t(s.redo.length?'redo':'noRedo');
            this.portal.querySelector('.layer-smart-status').textContent=s.error||error||(s.pendingTaskId?t('pending'):root.CanvasLayerEditResult.regionsFor(s.marks).length?t(s.transparent?'editBoundedAlpha':'editBounded'):'');this.presentation().syncHistory?.(s);}
        layout(){const s=this.state;if(!s)return;const host=this.presentation(),r=host.layerBounds(s.nodeId,s.layerId)||s.bounds;if(!r)return;s.bounds=r;
            const stage=this.portal.querySelector('.layer-smart-stage');Object.assign(stage.style,{left:r.left+'px',top:r.top+'px',width:r.width+'px',height:r.height+'px'});
            const area=host.controlBounds?.()||{left:12,top:54,width:innerWidth-24,right:innerWidth-12,bottom:innerHeight-90};
            const controls=this.portal.querySelector('.layer-smart-controls'),width=Math.min(680,area.width),height=controls.offsetHeight;
            Object.assign(controls.style,{width:width+'px',left:Math.max(area.left,Math.min(area.right-width,r.left+r.width/2-width/2))+'px',top:Math.max(area.top,Math.min(area.bottom-height,r.bottom+16))+'px'});
            const options=this.portal.querySelector('.layer-smart-tool-options'),textButton=this.portal.querySelector('[data-edit-action=text]');if(options)options.style.left=(textButton.offsetLeft+textButton.offsetWidth/2)+'px';
            this.textInput?.layout();
            this.promptEditor?.layoutPreview();
            this.layoutMarkGuide();
        }
        showMarkGuide(){if(!this.state||this.state.submitting||this.state.pendingTaskId)return;const guide=this.portal.querySelector('.layer-smart-marker-guide');guide.hidden=false;const video=guide.querySelector('video');video.muted=true;video.play().catch(()=>{});this.layoutMarkGuide();}
        hideMarkGuide(){const guide=this.portal.querySelector('.layer-smart-marker-guide');if(guide){guide.hidden=true;guide.querySelector('video').pause();}}
        layoutMarkGuide(){const guide=this.portal.querySelector('.layer-smart-marker-guide');if(!guide||guide.hidden)return;const r=this.portal.querySelector('[data-edit-action=marker]').getBoundingClientRect();Object.assign(guide.style,{left:Math.max(8,Math.min(innerWidth-288,r.left+r.width/2-140))+'px',top:Math.max(8,r.top-235.55)+'px'});}
        paint(){const s=this.state,canvas=this.portal.querySelector('[data-edit-marks]');if(!s?.base||!canvas)return;canvas.width=s.base.width;canvas.height=s.base.height;drawMarks(canvas,s.marks.filter(m=>m.kind!=='marker'&&!(s.textEditing&&m.id===s.selected)));this.paintMarkers(s.marks);this.paintTextSelection();canvas.style.cursor=s.tool==='text'?'text':s.pan?'grab':s.tool==='select'?'default':'crosshair';}
        paintTextSelection(){
            const s=this.state,selection=this.portal.querySelector('.layer-smart-text-selection'),mark=s.marks.find(m=>m.id===s.selected&&m.kind==='text');if(!selection)return;
            selection.hidden=!mark||Boolean(s.textEditing);if(!mark)return;
            const box=root.CanvasLayerAnnotations.markBox(mark);Object.assign(selection.style,{left:box.x*100+'%',top:box.y*100+'%',width:box.width*100+'%',height:box.height*100+'%'});
        }
        paintMarkers(marks){
            const overlay=this.portal.querySelector('.layer-smart-markers');if(!overlay)return;
            overlay.innerHTML=marks.filter(m=>m.kind==='marker').map(m=>{const r=m.rect,p=m.points[0];return `<div class="layer-smart-marker ${r?'box':'point'} ${m.id===this.state.selected?'is-selected':''}" style="left:${(r?r.x:p.x)*100}%;top:${(r?r.y:p.y)*100}%;width:${(r?.width||0)*100}%;height:${(r?.height||0)*100}%">${r?['nw','ne','se','sw'].map(c=>`<span class="layer-smart-marker-corner ${c}"></span>`).join(''):''}<span class="layer-smart-marker-pin">${root.CanvasLayerSmartPrompt.pin(m.number,24)}</span></div>`;}).join('');
        }
        remember(){const s=this.state;s.undo.push({marks:clone(s.marks),prompt:s.prompt});s.redo=[];}
        history(direction){const s=this.state,source=direction<0?s.undo:s.redo,target=direction<0?s.redo:s.undo;if(!source.length)return;target.push({marks:clone(s.marks),prompt:s.prompt});Object.assign(s,source.pop());s.selected='';this.render();}
        removeMark(mark){this.remember();const s=this.state;s.marks=s.marks.filter(m=>m!==mark);if(mark.kind==='marker')s.prompt=s.prompt.replaceAll('【'+mark.number+'】','');s.selected='';this.render();}
        bindStage(){
            const canvas=this.portal.querySelector('[data-edit-marks]');let drag;
            const point=e=>{const r=canvas.getBoundingClientRect();return {x:clamp((e.clientX-r.left)/r.width),y:clamp((e.clientY-r.top)/r.height)};};
            canvas.onpointerdown=e=>{const s=this.state;if(s.pendingTaskId||s.preparing||s.submitting||e.button!==0&&e.button!==1)return;e.preventDefault();e.stopPropagation();canvas.focus({preventScroll:true});
                if(e.button===1||s.pan){drag={pan:true,x:e.clientX,y:e.clientY};canvas.setPointerCapture(e.pointerId);return;}
                s.optionsOpen=false;this.portal.querySelector('.layer-smart-tool-options')?.remove();this.portal.querySelector('[data-edit-action=text]').setAttribute('aria-expanded','false');
                const p=point(e),hit=[...s.marks].reverse().find(m=>{const r=m.kind==='text'?root.CanvasLayerAnnotations.markBox(m):m.rect;return r?p.x>=r.x&&p.y>=r.y&&p.x<=r.x+r.width&&p.y<=r.y+r.height:m.points.some(q=>Math.hypot((q.x-p.x)*canvas.clientWidth,(q.y-p.y)*canvas.clientHeight)<18);});
                if(s.tool==='eraser'){if(hit)this.removeMark(hit);return;}
                if(hit?.kind==='text'){s.selected=hit.id;drag={kind:'text-move',mark:hit,initial:clone(hit),start:p,x:e.clientX,y:e.clientY};canvas.setPointerCapture(e.pointerId);this.paint();return;}
                if(s.tool==='text'){this.textAt(p);return;}
                if(s.tool==='select'){s.selected=hit?.id||'';this.paint();return;}
                if(s.tool==='marker'&&hit?.kind==='marker'){s.selected=hit.id;this.paint();this.promptEditor.focusMarker(hit.id);return;}
                drag={kind:s.tool,start:p,points:[p],x:e.clientX,y:e.clientY};canvas.setPointerCapture(e.pointerId);
            };
            canvas.onpointermove=e=>{if(!drag)return;if(drag.pan){this.presentation().pan(e.clientX-drag.x,e.clientY-drag.y);drag.x=e.clientX;drag.y=e.clientY;return;}
                if(drag.kind==='text-move'){if(Math.hypot(e.clientX-drag.x,e.clientY-drag.y)<3&&!drag.moved)return;if(!drag.moved){this.remember();drag.moved=true;}const p=point(e);root.CanvasLayerAnnotations.moveText(drag.mark,drag.initial,p.x-drag.start.x,p.y-drag.start.y);this.paint();return;}
                const p=point(e);if(drag.kind==='pen')drag.points.push(p);else drag.points=[drag.start,p];this.paint();const ctx=canvas.getContext('2d');
                const mark={kind:drag.kind,number:Math.max(0,...this.state.marks.filter(m=>m.kind==='marker').map(m=>m.number))+1,points:drag.points,...drag.kind==='marker'?{rect:{x:Math.min(p.x,drag.start.x),y:Math.min(p.y,drag.start.y),width:Math.abs(p.x-drag.start.x),height:Math.abs(p.y-drag.start.y)}}:{}};
                if(drag.kind==='marker')this.paintMarkers([...this.state.marks,mark]);else{const preview=document.createElement('canvas');preview.width=canvas.width;preview.height=canvas.height;drawMarks(preview,[mark]);ctx.drawImage(preview,0,0);}
            };
            canvas.onpointerup=e=>{if(!drag)return;const gesture=drag;drag=null;if(gesture.pan)return;if(gesture.kind==='text-move'){this.sync();return;}const s=this.state,p=point(e),distance=Math.hypot(e.clientX-gesture.x,e.clientY-gesture.y);if(gesture.kind!=='marker'&&distance<3){this.paint();return;}
                this.remember();const mark={id:'mark-'+Date.now()+'-'+s.marks.length,kind:gesture.kind,points:gesture.kind==='pen'?gesture.points:[gesture.start,p],width:4/canvas.clientWidth};
                if(mark.kind==='marker'){mark.number=Math.max(0,...s.marks.filter(m=>m.kind==='marker').map(m=>m.number))+1;mark.points=[gesture.start];if(distance>6)mark.rect={x:Math.min(p.x,gesture.start.x),y:Math.min(p.y,gesture.start.y),width:Math.abs(p.x-gesture.start.x),height:Math.abs(p.y-gesture.start.y)};}
                s.marks.push(mark);s.selected=mark.id;if(mark.kind==='marker'){this.promptEditor.marks=s.marks;this.promptEditor.insertMarker(mark);}this.render();};
            canvas.onpointercancel=()=>{drag=null;this.paint();};
            canvas.onwheel=e=>{e.preventDefault();if(e.ctrlKey||e.metaKey)this.presentation().zoom(e.clientX,e.clientY,e.deltaY);else this.presentation().pan(-e.deltaX,-e.deltaY);};
            canvas.ondblclick=e=>{const p=point(e),mark=this.state.marks.find(m=>m.id===this.state.selected&&m.kind==='text');if(mark)this.textAt(p,mark);};
            const selection=this.portal.querySelector('.layer-smart-text-selection');let resizing;
            selection.onpointerdown=e=>{const corner=e.target.closest('[data-text-corner]')?.dataset.textCorner,mark=this.state.marks.find(m=>m.id===this.state.selected);if(!corner||!mark)return;e.preventDefault();e.stopPropagation();this.remember();resizing={corner,mark,initial:clone(mark),start:point(e)};selection.setPointerCapture(e.pointerId);};
            selection.onpointermove=e=>{if(!resizing)return;const p=point(e),r=resizing;root.CanvasLayerAnnotations.resizeText(r.mark,r.initial,r.corner,p.x-r.start.x,p.y-r.start.y);this.paint();};
            selection.onpointerup=()=>{resizing=null;this.sync();};
        }
        textAt(p,existing){
            const s=this.state,stage=this.portal.querySelector('.layer-smart-stage');this.textInput ||= new root.CanvasLayerAnnotations.TextInput();
            const original=existing?clone(existing):null,mark=existing||{id:'text-'+Date.now(),kind:'text',points:[p],text:'',color:s.textColor||'#ff3355',fontSize:24/stage.clientWidth};
            const before={marks:clone(s.marks),prompt:s.prompt};s.textEditing=true;if(!existing)s.marks.push(mark);s.selected=mark.id;this.paint();
            this.textInput.open(stage,{text:mark.text,x:mark.points[0].x,y:mark.points[0].y,fontSize:mark.fontSize||.04,color:mark.color||'#ff3355'},
                {change:(text,box)=>{mark.text=text;mark.box=box;this.paint();},commit:(text,box,reason)=>{if(this.state!==s)return;s.undo.push(before);s.redo=[];if(text.trim()){mark.text=text;mark.box=box;}else s.marks=s.marks.filter(m=>m!==mark);s.textEditing=false;if(reason==='blur'){this.paint();this.sync();}else this.render();},
                    cancel:()=>{if(this.state!==s)return;if(original)Object.assign(mark,original);else s.marks=s.marks.filter(m=>m!==mark);s.textEditing=false;this.render();}});
        }
        change(e){const s=this.state;if(!s||s.submitting||s.pendingTaskId)return;
            if(e.target.matches('[data-edit-model]')){s.modelKey=e.target.value;s.resolution='';this.chooseResolution(s,true);s.error='';this.render();this.readSource(s);}
            if(e.target.matches('[data-edit-resolution]')){s.resolution=e.target.value;s.error='';this.sync();}}
        click(e){
            const color=e.target.closest('[data-annotation-color]')?.dataset.annotationColor;
            if(color&&this.state){e.preventDefault();const s=this.state,mark=s.marks.find(m=>m.id===s.selected&&m.kind==='text');if(mark){this.remember();mark.color=color;}s.textColor=color;this.render();return;}
            const action=e.target.closest('[data-edit-action]')?.dataset.editAction;if(!action||!this.state)return;e.preventDefault();
            if(action==='close'){this.close();return;}if(this.state.preparing||this.state.submitting||this.state.pendingTaskId)return;
            if(action==='generate'){this.generate();return;}if(action==='undo'||action==='redo'){this.history(action==='undo'?-1:1);return;}
            this.state.optionsOpen=action==='text'?!this.state.optionsOpen:false;this.state.tool=action;this.render();}
        keydown(e){const s=this.state;if(!s)return;const input=e.target.closest('input,textarea,select,[contenteditable=true]');
            if(e.target.closest('[data-layer-annotation-text]'))return;
            if(!input&&this.presentation().keyAction?.(e)){e.preventDefault();e.stopImmediatePropagation();return;}
            if(e.key==='Escape'&&this.portal.querySelector('.layer-smart-marker-guide')?.hidden===false){e.preventDefault();e.stopImmediatePropagation();this.hideMarkGuide();return;}
            if(e.target.closest('[data-edit-prompt]')){
                if(this.promptEditor.keydown(e))return;
                if(!s.submitting&&!s.pendingTaskId&&(e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();e.stopImmediatePropagation();this.history(e.shiftKey?1:-1);return;}
                if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();e.stopImmediatePropagation();this.generate();return;}
                if(e.key!=='Escape')return;
            }
            if(e.key==='Escape'){e.preventDefault();e.stopImmediatePropagation();if(e.target.matches('.layer-smart-text')){e.target.remove();return;}if(s.selected){s.selected='';this.paint();return;}this.close();return;}
            if(input){if(e.target.matches('[data-edit-prompt]')&&e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();e.stopImmediatePropagation();this.generate();}return;}
            if(e.code==='Space'){e.preventDefault();s.pan=true;this.paint();}
            if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();e.stopImmediatePropagation();if(!s.submitting&&!s.pendingTaskId)this.history(e.shiftKey?1:-1);}
            if(['Delete','Backspace'].includes(e.key)){e.preventDefault();e.stopImmediatePropagation();const mark=s.marks.find(m=>m.id===s.selected);if(mark&&!s.submitting&&!s.pendingTaskId)this.removeMark(mark);}
        }
        async generate(){
            const s=this.state;if(!s||s.preparing||s.submitting||s.pendingTaskId||this.error()||!hasInstruction(s.prompt))return;
            const model=this.model(),choice=this.choices().find(c=>c.value===s.resolution),prompt=protocolPrompt(s.prompt,s.marks),binding={nodeId:s.nodeId,layerId:s.layerId,sourceKey:s.sourceKey,preserveAlpha:s.transparent};
            if(model.profile.max_references===1&&s.marks.length){s.error=t('editMarkReferences');this.sync();return;}
            s.submitting=true;s.error='';this.render();
            try{
                const original=await this.adapter.upload(s.base.toDataURL('image/png'),'smart-edit-source.png');if(this.state!==s)return;
                const regions=root.CanvasLayerEditResult.regionsFor(s.marks);
                if(regions.length)binding.regionEdit={source:original,width:s.base.width,height:s.base.height,regions,keepAlpha:s.transparent};
                const references=[original];
                if(s.marks.length){const marked=document.createElement('canvas');marked.width=s.base.width;marked.height=s.base.height;marked.getContext('2d').drawImage(s.base,0,0);const ink=document.createElement('canvas');ink.width=marked.width;ink.height=marked.height;drawMarks(ink,s.marks);marked.getContext('2d').drawImage(ink,0,0);references.push(await this.adapter.upload(marked.toDataURL('image/png'),'smart-edit-guide.png'));}
                if(this.state!==s)return;
                if(sourceKey(s.session.doc.layers.find(l=>l.id===s.layerId)||{})!==s.sourceKey)throw Error(t('editSourceChanged'));
                this.adapter.saveEditSettings(s.nodeId,{provider_id:model.provider_id,model:model.model,resolution:s.resolution});
                const target=await this.adapter.separate(s.nodeId,0,{provider_id:model.provider_id,model:model.model,size:choice.size,prompt,
                    ...(model.profile.mode==='aspect-size'?choice.parameters:{}),_references:references,_editTarget:binding,_stayOnSource:true,
                    ...(s.transparent&&!regions.length&&model.profile.supports_background?{background_mode:'transparent'}:{}),
                    creation_title:t('edit'),...model.profile.supports_quality?{quality:'auto'}:{}});
                if(this.state===s){s.pendingTaskId=target.sourceTaskId;const issue=target.imageTaskIssues?.find(i=>i.taskId===target.sourceTaskId);
                    if(target.layerEditTarget?.state)this.completed(target,target.layerEditTarget.state);else if(issue&&!target.pendingTasks?.length)this.failed(target.sourceTaskId,issue.error);else this.render();}
            }catch(error){if(this.state===s){s.error=error.message;this.sync();}}
            finally{if(this.state===s){s.submitting=false;this.render();}}
        }
        async validateOutput(binding,item){
            if(!binding.preserveAlpha)return 'ready';
            const image=await this.editor.loadImage(item.url,false),canvas=document.createElement('canvas');canvas.width=image.width;canvas.height=image.height;
            canvas.getContext('2d').drawImage(image,0,0);
            return hasAlpha(canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data)?'ready':'alpha-missing';
        }
        async prepareOutput(binding,item){
            if(!binding.regionEdit)return {state:await this.validateOutput(binding,item),item};
            if(!binding.preparedAsset){
                this.outputPreparations??=new WeakMap();
                if(!this.outputPreparations.has(binding))this.outputPreparations.set(binding,root.CanvasLayerEditResult.prepare(binding.regionEdit,item,{
                    loadImage:url=>this.editor.loadImage(url,false),upload:(data,name)=>this.adapter.upload(data,name),createCanvas:()=>document.createElement('canvas')}).finally(()=>this.outputPreparations.delete(binding)));
                binding.preparedAsset=await this.outputPreparations.get(binding);
            }
            return {state:'ready',item:binding.preparedAsset};
        }
        completed(target,result){
            if(this.state?.pendingTaskId!==target.sourceTaskId)return;
            if(result==='applied')this.close();else{this.state.pendingTaskId='';this.state.error=t(result==='alpha-missing'?'editAlphaMissing':'editSourceChanged');this.render();}
        }
        failed(taskId,message){if(this.state?.pendingTaskId===taskId){this.state.pendingTaskId='';this.state.error=message;this.render();}}
    }
    const api={modelsFor,sourceKey,sourceDocument,parametersFor,resolutionsFor,protocolPrompt,hasInstruction,hasAlpha,applyResult,outputNotice,drawMarks,SmartEdit,install:(adapter,editor)=>new SmartEdit(adapter,editor)};
    root.CanvasLayerSmartEdit=api;if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
