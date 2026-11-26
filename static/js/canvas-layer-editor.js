/* UI owns an editable draft; the canvas adapter owns tasks, media and saves. */
(function(){
    const D=window.CanvasLayerDocument;
    const t=key=>window.StudioI18n.t('layers.'+key);
    const esc=value=>String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const icon=name=>`<i data-lucide="${name}"></i>`;
    const stageSize=stage=>({width:stage.clientWidth,height:stage.clientHeight});
    const button=(key,label,ico,extra='')=>`<button class="layer-button ${extra}" type="button" data-action="${key}" title="${esc(t(label))}" aria-label="${esc(t(label))}">${ico ? icon(ico) : ''}<span>${esc(t(label))}</span></button>`;
    class Editor{
        constructor(adapter){
            this.adapter=adapter;this.images=new Map();
            this.dialog=document.createElement('dialog');this.dialog.className='canvas-layer-editor';document.body.append(this.dialog);
            this.dialog.addEventListener('click',event=>this.click(event));
            this.dialog.addEventListener('change',event=>this.change(event));
            this.dialog.addEventListener('input',event=>this.change(event,true));
            this.dialog.addEventListener('cancel',event=>{event.preventDefault();if(this.popup){this.popup=null;this.render();}else this.close();});
            this.dialog.addEventListener('dragover',event=>{event.preventDefault();event.stopPropagation();});
            this.dialog.addEventListener('drop',event=>{event.preventDefault();event.stopPropagation();this.importFiles([...event.dataTransfer.files].filter(file=>file.type.startsWith('image/')));});
            this.dialog.addEventListener('paste',event=>{const files=[...event.clipboardData.files].filter(file=>file.type.startsWith('image/'));if(files.length){event.preventDefault();event.stopPropagation();this.importFiles(files);}});
            this.dialog.addEventListener('keydown',event=>{
                if(event.target.closest('[data-layer-annotation-text]'))return;
                if(event.code==='Space'&&!this.smartEditing&&!event.target.closest('input,textarea,select,[contenteditable=true]')){event.preventDefault();this.spacePan=true;this.dialog.querySelector('.layer-stage').style.cursor='grab';}
                const zoomAction=CanvasLayerViewport.keyAction(event);
                if(zoomAction&&!event.target.closest('input,textarea,select,[contenteditable=true]')){event.preventDefault();event.stopPropagation();this.setZoom(zoomAction);return;}
                if(event.key==='Enter'&&event.target.matches('[data-zoom-percent]')){event.preventDefault();this.setZoom('zoom-'+event.target.value);return;}
                if(event.key==='Escape' && this.popup){event.preventDefault();this.popup=null;this.render();event.stopPropagation();return;}
                if((event.ctrlKey || event.metaKey) && event.key.toLowerCase()==='z' && !event.target.matches('input,textarea')){
                    event.preventDefault();if(this.tool==='mask')this.surface.action(event.shiftKey?'mask-redo':'mask-undo');else this.history(event.shiftKey ? 1 : -1);
                }
                if(event.key==='Escape' && ['crop','mask'].includes(this.tool)){event.preventDefault();this.surface.action('cancel');}
                event.stopPropagation();
            });
            window.addEventListener('keyup',event=>{if(event.code==='Space'){this.spacePan=false;const stage=this.dialog.querySelector('.layer-stage');if(stage)stage.style.cursor='';}});
            window.addEventListener('studio-lang-change',()=>{
                if(this.prompt===this.defaultPrompt)this.prompt=t('promptDefault');
                this.defaultPrompt=t('promptDefault');if(this.dialog.open)this.render();
            });
            window.addEventListener('resize',()=>{if(this.dialog.open){this.positionBoard();this.surface?.layout();}});
        }
        async open(nodeId,index=0,options={}){
            this.session=CanvasLayerSession.get(this.adapter.node(nodeId));
            this.nodeId=nodeId;this.index=index;this.error='';this.messageKey='';this.editingProperty='';this.busy=false;
            this.popup=null;this.view=null;this.smartView=null;this.smartEditing=false;this.spacePan=false;
            const node=this.adapter.node(nodeId),source=node.layerSource || node.images[index] || {};
            const saved=node.layerSettings;
            if(options.selectedLayerId)this.selected=options.selectedLayerId;
            if(!this.doc.layers.some(layer=>layer.id===this.selected))this.selected=this.doc.layers[0]?.id || '';
            this.defaultPrompt=t('promptDefault');
            this.applySettings(saved);
            this.dialog.showModal();this.render();
            try{
                if(source.url && !source.width && !source.natural_w && !node.layerDocument){
                    const image=await this.loadImage(source.url,false);this.doc=D.fromOutputs([Object.assign({},source,{width:image.width,height:image.height})],source);
                }
                const response=await fetch('/api/config');if(!response.ok)throw new Error(t('noProvider'));
                const config=await response.json();
                this.imageModels=(config.api_providers || []).filter(p=>p.enabled!==false).flatMap(p=>(p.image_models || [])
                    .filter(model=>!model.endsWith('/layer-decomposition')).map(model=>({provider:p.id,model,label:(p.name || p.id)+' · '+model})));
                if(!saved && node.layerTaskId){
                    const receipt=await fetch('/api/canvas-image-tasks/'+encodeURIComponent(node.layerTaskId));
                    if(receipt.ok){const task=await receipt.json();this.applySettings(task.result?.params);}
                }
                this.models=CanvasLayerSeparation.modelsFor(config).map(model=>({...model,provider:model.provider_id}));
                this.modelKey=this.models.some(m=>m.provider+'|'+m.model===this.modelKey) ? this.modelKey :
                    this.models[0] ? this.models[0].provider+'|'+this.models[0].model : '';
                if(this.dialog.open){this.render();if(node.pendingTasks?.length)this.watch();}
            }catch(error){this.error=error.message;this.render();}
        }
        applySettings(saved){
            this.prompt=saved?.prompt || this.defaultPrompt;this.size=saved?.size || 'auto';
            this.limit=saved?.layer_options?.max_images ? saved.layer_options.max_images-1 : '';
            this.recognize=saved?.layer_options?.text_recognition ?? false;
            this.modelKey=saved?.provider_id && saved?.model ? saved.provider_id+'|'+saved.model : '';
        }
        async close(){
            this.surface?.textInput?.commit('blur');
            if(this.smartEditing)this.smartEdit.close(false);
            if(!this.busy && this.adapter.node(this.nodeId)?.layerDraft)await this.run('save');
            await this.adapter.flush?.(this.nodeId);this.dialog.close();clearInterval(this.timer);this.paintVersion=(this.paintVersion || 0)+1;CanvasLayerNode.layout();
        }
        selectedLayer(){return this.doc.layers.find(layer=>layer.id===this.selected);}
        remember(){this.session.remember();}
        changed(){this.messageKey='';this.adapter.draft(this.nodeId,D.clone(this.doc));this.render();}
        history(direction){if(this.session.history(direction))this.changed();}
        layerName(layer){return layer.name || (layer.kind==='text' ? layer.text.split('\n')[0] : layer.asset?.z_index===0 ? t('base') : t('image')+' '+(this.doc.layers.indexOf(layer)+1));}
        floatingTools(selected){
            const tool=(action,label,ico,extra='')=>button(action,label,ico,'icon '+extra),canImage=selected?.kind==='image';
            return selected && !['crop','mask'].includes(this.tool)?`<div class="layer-floating-tools" role="toolbar" aria-label="${esc(t('layers'))}">
                ${canImage?tool('edit-panel','edit','sparkles')+tool('cutout-panel','cutout','scan-face')+tool('crop','crop','crop'):tool('edit-text','text','type')+tool('style-menu','textStyle','sliders-horizontal')}
                <span class="layer-tool-divider"></span>${tool('rotate90','rotate90','rotate-cw')}${tool('flipX','flipX','flip-horizontal-2')}${tool('flipY','flipY','flip-vertical-2')}${tool('fit-layer','fit','scan')}
                <span class="layer-tool-divider"></span>${tool('order-menu','order','layers',this.popup==='order'?'active':'')}<span class="layer-tool-divider"></span>
                ${tool('selected-visible',selected.visible?'hide':'showOnly',selected.visible?'eye':'eye-off')}${tool('duplicate','copy','copy')}${tool('remove','remove','trash-2')}${tool('download-layer','layerPng','download')}
            </div>`:'';
        }
        selectionChanged(){
            const stage=this.dialog.querySelector('.layer-stage');stage.querySelector('.layer-floating-tools')?.remove();
            stage.insertAdjacentHTML('beforeend',this.floatingTools(this.selectedLayer()));window.lucide?.createIcons({root:stage});
            this.positionBoard();this.dialog.querySelectorAll('[data-layer-id]').forEach(row=>row.classList.toggle('selected',row.dataset.layerId===this.selected));
        }
        render(){
            if(!this.dialog.open)return;
            this.surface?.textInput?.commit('blur');
            const smartPortal=this.smartEditing?this.smartEdit?.portal:null;
            const node=this.adapter.node(this.nodeId);if(!node){this.close();return;}
            const selected=this.selectedLayer(),pending=Boolean(node.pendingTasks?.some(task=>!task.failed));
            const tool=(action,label,ico,extra='')=>button(action,label,ico,'icon '+extra);
            const menu=(action,label,ico,disabled=false)=>`<button type="button" class="layer-menu-item" role="menuitem" data-action="${action}" ${disabled?'disabled':''}>${icon(ico)}${esc(t(label))}</button>`;
            this.dialog.setAttribute('aria-label',t('title'));
            const splitProfile=this.models?.find(m=>m.key===this.modelKey)?.profile || {};
            const incompatibleSplit=splitProfile.supports_layer_limit===false&&this.limit!=='' || splitProfile.supports_layer_text_recognition===false&&this.recognize;
            const floating=this.floatingTools(selected);
            let popup='';
            if(this.popup==='board-download')popup=`<div id="layer-board-download" class="layer-popup layer-board-download menu" role="menu" aria-label="${esc(t('download'))}">${menu('zip','exportAll','images')}${menu('psd','exportPsd','layers')}</div>`;
            if(this.popup==='mode')popup=`<div id="layer-output-options" class="layer-popup mode-menu menu" role="menu" aria-label="${esc(t('options'))}">${['fusion','merge'].map(mode=>`<button type="button" class="layer-menu-item" role="menuitemradio" aria-checked="${this.session.outputMode===mode}" data-action="mode-${mode}">${icon(mode==='fusion'?'scan':'layers')}<span>${esc(t(mode))}</span>${this.session.outputMode===mode?icon('check'):''}</button>`).join('')}</div>`;
            if(this.popup==='fusion'){
                const chosen=this.chooseImageModel(this.session,this.imageModels || []);
                popup=`<section id="layer-fusion-panel" class="layer-popup layer-fusion-panel" role="dialog" aria-label="${esc(t('fusion'))}"><div class="layer-fusion-heading"><span>${esc(t('fusion'))}</span>${tool('dismiss-popup','close','x')}</div><textarea data-session-setting="prompt" aria-label="${esc(t('fusionHint'))}" placeholder="${esc(t('fusionHint'))}">${esc(this.session.prompt)}</textarea><div class="layer-fusion-footer"><span class="layer-fusion-source" title="${esc(chosen?.label || t('fusionNoModel'))}">${esc(chosen?.label || t('fusionNoModel'))}</span><button type="button" class="layer-button primary" data-action="fusion"><span>${esc(t('generate'))}</span>${icon('sparkles')}</button></div></section>`;
            }
            if(this.popup==='import')popup=`<div class="layer-popup import-menu menu" role="menu">${menu('import','upload','upload')}${menu('asset-library','fromLibrary','folder')}${menu('canvas-pick','fromCanvas','scan')}</div>`;
            if(this.popup==='order'){
                const index=this.doc.layers.indexOf(selected);
                popup=`<div class="layer-popup order-menu" role="menu">${menu('up','up','arrow-up-from-line',index===this.doc.layers.length-1)}${menu('down','down','arrow-down-to-line',index===0)}${menu('front','front','chevrons-up',index===this.doc.layers.length-1)}${menu('back','back','chevrons-down',index===0)}</div>`;
            }
            if(this.popup==='zoom')popup=`<div class="layer-popup zoom-menu" role="menu" aria-label="${esc(t('zoom'))}">${menu('zoom-in','zoomIn','plus',this.viewScale>=4)}${menu('zoom-out','zoomOut','minus',this.viewScale<=this.minimumZoom)}${menu('zoom-fit','fitBoard','scan')}${menu('zoom-selection','fitSelection','focus',!selected&&!this.smartEditing)}<hr>${[50,100,200].map(n=>`<button class="layer-menu-item" role="menuitem" data-action="zoom-${n}">${esc(t('zoomTo'))}${n}%</button>`).join('')}</div>`;
            if(this.popup==='style' || this.popup==='transform')popup=`<div class="layer-popup">${selected?this.properties(selected):''}</div>`;
            if(this.popup==='brush')popup=`<div class="layer-popup" style="top:auto;bottom:65px;width:220px"><label>${esc(t('color'))}<input data-setting="penColor" type="color" value="${this.penColor}"></label><label>${esc(t('brushSize'))}<input data-setting="penWidth" type="range" min="1" max="40" value="${this.penWidth}"></label></div>`;
            if(this.popup==='split')popup=`<div class="layer-popup"><div class="layer-section-title">${esc(t('settings'))}</div><label>${esc(t('provider'))}<select data-setting="model">${(this.models || []).map(m=>`<option value="${esc(m.provider+'|'+m.model)}" ${this.modelKey===m.provider+'|'+m.model?'selected':''}>${esc(m.label)}</option>`).join('')}</select></label>
                <label>${esc(t('prompt'))}<textarea data-setting="prompt">${esc(this.prompt)}</textarea></label><div class="layer-fields"><label>${esc(t('limit'))}<input data-setting="limit" type="number" min="1" max="99" placeholder="${esc(t('auto'))}" value="${esc(this.limit)}" ${splitProfile.supports_layer_limit===false?'disabled':''}></label><label>${esc(t('resolution'))}<select data-setting="size">${['auto','1K','1.5K','2K'].map(size=>`<option value="${size}" ${this.size===size?'selected':''}>${size==='auto'?esc(t('auto')):size}</option>`).join('')}</select></label></div>
                <p class="layer-note">${esc(t('limitHint'))}</p><label class="layer-check"><input data-setting="recognize" type="checkbox" ${this.recognize?'checked':''} ${splitProfile.supports_layer_text_recognition===false?'disabled':''}>${esc(t('ocr'))}</label><p class="layer-note">${esc(t(splitProfile.supports_layer_limit===false?'channelOptionsUnavailable':'channelHint'))}</p>${incompatibleSplit?button('reset-split','resetSplitOptions','rotate-ccw'):''}${this.models?.length?button('split','start','layers','primary'):`<p class="layer-note">${esc(t('noProvider'))}</p>`}</div>`;
            this.dialog.innerHTML=`<div class="layer-shell"><header class="layer-header"><strong>${esc(t('title'))}</strong><button type="button" class="layer-button layer-board-download-trigger" data-action="board-download-menu" aria-haspopup="menu" aria-controls="layer-board-download" aria-expanded="${this.popup==='board-download'}">${icon('layers')}${esc(t('download'))}</button><div class="layer-output-group"><button type="button" class="layer-button layer-fusion" data-action="output" ${this.session.outputMode==='fusion'?`aria-haspopup="dialog" aria-controls="layer-fusion-panel" aria-expanded="${this.popup==='fusion'}"`:''}>${icon(this.session.outputMode==='merge'?'layers':'scan')}<span>${esc(t(this.session.outputMode==='merge'?'merge':'fusion'))}</span>${this.session.outputMode==='fusion'?icon('sparkles'):''}</button><button type="button" class="layer-button icon chevron" data-action="mode-menu" aria-label="${esc(t('options'))}" aria-haspopup="menu" aria-controls="layer-output-options" aria-expanded="${this.popup==='mode'}">${icon('chevron-down')}</button></div>${button('close','close','x','icon layer-close')}</header>
                <div class="layer-workspace"><aside class="layer-list-pane" aria-label="${esc(t('layers'))}"><div class="layer-list" role="list">${[...this.doc.layers].reverse().map(layer=>`<div class="layer-row ${layer.id===this.selected?'selected':''} ${layer.visible?'':'is-hidden'}" data-layer-id="${esc(layer.id)}"><button class="layer-pick" type="button" data-action="select" title="${esc(this.layerName(layer))}">${layer.kind==='image'?`<img src="${esc(layer.asset.url)}" alt="">`:'<span class="layer-kind">T</span>'}<span>${esc(this.layerName(layer))}</span></button><button class="layer-button icon" type="button" data-action="visible" title="${esc(t(layer.visible?'hide':'showOnly'))}" aria-label="${esc(t(layer.visible?'hide':'showOnly'))}" aria-pressed="${layer.visible}">${icon(layer.visible?'eye':'eye-off')}</button></div>`).join('')}</div>${button('import-menu','import','layers','layer-import')}</aside>
                <section class="layer-stage" aria-label="${esc(t('preview'))}"><div class="layer-artboard">${CanvasLayerSurface.html()}</div>${floating}</section></div>
                <div class="layer-bottom-tools" ${['crop','mask'].includes(this.tool)?'hidden':''} role="toolbar" aria-label="${esc(t('tool'))}">${tool('tool-select','select','mouse-pointer-2',this.tool==='select'?'active':'')}${tool('tool-pen','pen','pencil',this.tool==='pen'?'active':'')}${tool('tool-arrow','arrow','arrow-up-right',this.tool==='arrow'?'active':'')}${tool('tool-text','text','type',this.tool==='text'?'active':'')}${tool('tool-eraser','eraser','eraser',this.tool==='eraser'?'active':'')}<span class="layer-tool-divider"></span>${tool('undo','undo','undo-2')}${tool('redo','redo','redo-2')}<span class="layer-tool-divider"></span>${this.popup==='zoom'?`<input class="layer-zoom-input" data-zoom-percent aria-label="${esc(t('zoomPercent'))}" value="${Math.round((this.viewScale||1)*100)}" inputmode="decimal">`:`<button type="button" class="layer-button icon layer-zoom" style="width:auto;padding:0 9px" data-action="zoom-menu" aria-label="${esc(t('zoom'))}" aria-haspopup="menu" aria-expanded="false">100%</button>`}${this.popup==='annotation-text'?`<div class="layer-annotation-palette">${CanvasLayerAnnotations.palette(this.session.textColor||'#ff3355')}</div>`:''}</div>
                <div class="layer-surface-tools">${CanvasLayerSurface.toolHtml(this.session)}</div>
                <div class="layer-state ${this.error?'layer-error':''}" role="status">${esc(this.error || (this.busy?t('working'):pending?t('pending'):''))}</div>${popup}<input type="file" data-layer-import accept="image/*" multiple hidden></div>`;
            this.dialog.querySelector('[data-action=undo]').disabled=!this.undo.length;
            this.dialog.querySelector('[data-action=redo]').disabled=!this.redo.length;
            this.dialog.querySelector('[data-action=undo]').title=t(this.undo.length?'undo':'noUndo');this.dialog.querySelector('[data-action=redo]').title=t(this.redo.length?'redo':'noRedo');
            const textTrigger=this.dialog.querySelector('[data-action=tool-text]');if(textTrigger){textTrigger.setAttribute('aria-pressed',String(this.tool==='text'));textTrigger.setAttribute('aria-expanded',String(this.popup==='annotation-text'));}
            this.dialog.querySelectorAll('[data-action=split],[data-action=save],[data-action=output],[data-action=fusion]').forEach(b=>b.disabled=this.busy || pending);
            this.dialog.querySelectorAll('[data-action=zip],[data-action=psd],[data-action=download-layer]').forEach(b=>b.disabled=this.busy);
            if(this.popup==='fusion'&&!this.imageModels?.length)this.dialog.querySelector('[data-action=fusion]').disabled=true;
            if(incompatibleSplit)this.dialog.querySelector('[data-action=split]')?.setAttribute('disabled','');
            this.dialog.querySelector('.layer-workspace').inert=this.busy;
            this.dialog.querySelector('[data-layer-import]').onchange=event=>this.importFiles(event.target.files);
            if(smartPortal)this.dialog.append(smartPortal);
            window.lucide?.createIcons({root:this.dialog});
            const downloadMenu=this.dialog.querySelector('.layer-board-download'),downloadTrigger=this.dialog.querySelector('[data-action=board-download-menu]');
            if(downloadMenu)downloadMenu.style.right=(this.dialog.getBoundingClientRect().right-downloadTrigger.getBoundingClientRect().right)+'px';
            const zoomMenu=this.dialog.querySelector('.zoom-menu');if(zoomMenu){const box=this.dialog.querySelector('.layer-bottom-tools').getBoundingClientRect(),dialog=this.dialog.getBoundingClientRect();Object.assign(zoomMenu.style,{right:dialog.right-box.right+'px',bottom:dialog.bottom-box.top+8+'px'});}
            this.bindDrag();this.positionBoard();this.paint();
            if(this.popup==='zoom')this.dialog.querySelector('[data-zoom-percent]')?.select();
        }
        positionBoard(){
            const stage=this.dialog.querySelector('.layer-stage'),board=this.dialog.querySelector('.layer-artboard');if(!stage)return;
            if(!this.view)this.view=CanvasLayerViewport.fit(stageSize(stage),{x:0,y:0,width:this.doc.width,height:this.doc.height});
            this.minimumZoom=Math.min(.25,CanvasLayerViewport.fit(stageSize(stage),{x:0,y:0,width:this.doc.width,height:this.doc.height}).zoom);
            const view=this.smartEditing&&this.smartView?this.smartView:this.view,scale=this.viewScale=view.zoom;
            Object.assign(board.style,{width:this.doc.width*this.view.zoom+'px',height:this.doc.height*this.view.zoom+'px',left:this.view.x+'px',top:this.view.y+'px',transform:'none',margin:0});
            const zoom=this.dialog.querySelector('.layer-zoom');if(zoom)zoom.textContent=Math.round(scale*100)+'%';
            const palette=this.dialog.querySelector('.layer-annotation-palette'),textTool=this.dialog.querySelector('[data-action=tool-text]');if(palette)palette.style.left=(textTool.offsetLeft+textTool.offsetWidth/2)+'px';
            const tools=this.dialog.querySelector('.layer-surface-tools'),r=board.getBoundingClientRect();if(tools){const half=tools.offsetWidth/2+8;Object.assign(tools.style,{left:Math.max(half,Math.min(innerWidth-half,r.left+r.width/2))+'px',top:Math.min(innerHeight-65,r.bottom+12)+'px'});}
            const layer=this.selectedLayer(),selection=this.dialog.querySelector('.layer-selection');
            selection.hidden=!layer || !layer.visible || this.tool!=='select' || Boolean(this.surface?.editingText);
            const floating=this.dialog.querySelector('.layer-floating-tools');if(floating)floating.hidden=!layer || !layer.visible || Boolean(this.surface?.editingText);
            if(layer){Object.assign(selection.style,{left:layer.x*scale+'px',top:layer.y*scale+'px',width:layer.width*scale+'px',height:layer.height*scale+'px',transform:`rotate(${layer.rotation}deg)`});
                const toolbar=this.dialog.querySelector('.layer-floating-tools');
                if(toolbar){const r=board.getBoundingClientRect(),s=stage.getBoundingClientRect();
                    toolbar.style.maxWidth=Math.max(100,stage.clientWidth-20)+'px';toolbar.style.overflowX='auto';
                    const half=Math.min(toolbar.offsetWidth/2+8,stage.clientWidth/2);
                    const x=Math.max(half,Math.min(stage.clientWidth-half,r.left-s.left+(layer.x+layer.width/2)*scale));
                    const y=Math.max(42,r.top-s.top+layer.y*scale-8);toolbar.style.left=x+'px';toolbar.style.top=y+'px';
                    const pop=this.dialog.querySelector('.order-menu');if(pop)Object.assign(pop.style,{left:Math.min(innerWidth-220,s.left+x)+'px',top:s.top+y+5+'px',bottom:'auto'});
                }
            }
        }
        properties(layer){
            const field=(key,label,type='number')=>`<label>${esc(label)}<input data-property="${key}" type="${type}" value="${esc(type==='number'?Math.round(layer[key]*100)/100:layer[key])}" ${type==='number'?'step="any"':''} ${layer.locked?'disabled':''}></label>`;
            return `<div class="layer-section-title">${esc(this.layerName(layer))}</div><div class="layer-actions">${button('up','up','arrow-up')}${button('down','down','arrow-down')}${button('remove','remove','trash-2')}</div>
                <div class="layer-fields">${field('x','X')}${field('y','Y')}${field('width',window.StudioI18n.lang()==='en'?'Width':'宽度')}${field('height',window.StudioI18n.lang()==='en'?'Height':'高度')}${field('rotation',t('rotation'))}<label>${esc(t('opacity'))}<input data-property="opacity" type="number" min="0" max="1" step="0.05" value="${layer.opacity}" ${layer.locked?'disabled':''}></label></div>
                ${layer.kind==='text'?`<label>${esc(t('text'))}<textarea data-property="text" ${layer.locked?'disabled':''}>${esc(layer.text)}</textarea></label>${field('fontFamily',t('font'),'text')}<div class="layer-fields">${field('fontSize',t('fontSize'))}${field('color',t('color'),'color')}</div>${['bold','italic'].map(key=>`<label class="layer-check"><input data-property="${key}" type="checkbox" ${layer[key]?'checked':''} ${layer.locked?'disabled':''}>${esc(t(key))}</label>`).join('')}`:layer.asset?.text_recognition?button('convert','convert','type'):''}
                ${layer.asset?.text_recognition || layer.sourceLayerId ? `<p class="layer-note">${esc(t('fontHint'))}</p>`:''}`;
        }
        change(event,live=false){
            const input=event.target,key=input.dataset.setting,property=input.dataset.property;
            if(input.matches('[data-zoom-percent]')){if(!live)this.setZoom('zoom-'+input.value);return;}
            if(input.dataset.sessionSetting){this.session[input.dataset.sessionSetting]=input.value;return;}
            if(input.hasAttribute('data-mask-size')){this.session.maskSize=Number(input.value);return;}
            if(key){this[{model:'modelKey',prompt:'prompt',limit:'limit',size:'size',recognize:'recognize',penColor:'penColor',penWidth:'penWidth'}[key]]=input.type==='checkbox'?input.checked:input.value;
                if(key==='model'){
                    const profile=this.models.find(m=>m.key===this.modelKey)?.profile;
                    if(profile?.supports_layer_limit===false)this.limit='';if(profile?.supports_layer_text_recognition===false)this.recognize=false;this.render();
                }return;}
            if(!property)return;
            const layer=this.selectedLayer();if(!layer || layer.locked)return;
            if(this.editingProperty!==layer.id+property){this.remember();this.editingProperty=layer.id+property;}
            let value=input.type==='checkbox'?input.checked:input.type==='number'?Number(input.value):input.value;
            if(['width','height','fontSize'].includes(property))value=Math.max(1,value);
            if(layer.kind==='text' && ['width','height'].includes(property)){
                const ratio=value/layer[property];layer.fontSize*=ratio;
                layer[property==='width'?'height':'width']*=ratio;
            }
            if(property==='opacity')value=Math.min(1,Math.max(0,value));layer[property]=value;
            if(live){
                this.messageKey='';
                this.adapter.draft(this.nodeId,D.clone(this.doc));this.positionBoard();this.paint();
                this.dialog.querySelector('[data-action=undo]').disabled=false;
                this.dialog.querySelector('[data-action=redo]').disabled=true;
                const status=this.dialog.querySelector('.layer-state');if(status)status.textContent='';
                const row=[...this.dialog.querySelectorAll('[data-layer-id]')].find(el=>el.dataset.layerId===layer.id);
                if(property==='text' && row)row.querySelector('.layer-pick').textContent='T '+this.layerName(layer);
            }else{this.editingProperty='';this.changed();}
        }
        async click(event){
            const swatch=event.target.closest('[data-annotation-color]');
            if(swatch){this.session.textColor=swatch.dataset.annotationColor;const layer=this.selectedLayer();if(layer?.kind==='text'){this.remember();layer.color=this.session.textColor;this.changed();}else this.render();return;}
            const surfaceAction=event.target.closest('[data-surface-action]');if(surfaceAction){await this.surface.action(surfaceAction.dataset.surfaceAction);return;}
            const control=event.target.closest('[data-action]');
            if(!control){if(this.popup&&!event.target.closest('.layer-popup')){this.popup=null;this.render();}return;}
            const action=control.dataset.action,row=control.closest('[data-layer-id]'),layer=row?this.doc.layers.find(l=>l.id===row.dataset.layerId):this.selectedLayer();
            if(this.smartEditing && control.closest('.layer-list-pane'))this.smartEdit.close();
            if(action==='close'){this.close();return;}
            if(action==='dismiss-popup'){this.popup=null;this.render();return;}
            if(action==='reset-split'){this.limit='';this.recognize=false;this.render();return;}
            if(action==='select'){this.selected=layer.id;this.popup=null;this.tool='select';this.render();return;}
            if(action.endsWith('-menu')){const name=action.slice(0,-5);this.popup=this.popup===name?null:name;this.render();return;}
            if(action.startsWith('tool-')){if(this.smartEditing){this.smartEdit.state.tool='select';this.smartEdit.state.selected='';this.smartEdit.paint();return;}this.tool=action.slice(5);this.popup=this.tool==='text'?(this.popup==='annotation-text'?null:'annotation-text'):this.tool==='pen'||this.tool==='arrow'?'brush':null;this.render();return;}
            if(action.startsWith('zoom-')){this.setZoom(action);return;}
            if(action==='edit-text'){this.surface.editText(layer);return;}
            if(action==='import'){this.dialog.querySelector('[data-layer-import]').click();return;}
            if(action==='asset-library'){await this.pickLibrary();return;}
            if(action==='canvas-pick'){await this.close();this.adapter.pickFromCanvas(this.nodeId,(assets,sourceId)=>CanvasLayerNode.addAssets(this.nodeId,assets,sourceId));return;}
            if(action==='output'){if(this.session.outputMode==='merge')await this.run('merge');else{this.popup=this.popup==='fusion'?null:'fusion';this.render();}return;}
            if(action==='mode-fusion' || action==='mode-merge'){this.session.outputMode=action.slice(5);this.popup=null;this.render();return;}
            if(action==='crop'){this.session.startCrop();this.popup=null;this.render();return;}
            if(action==='cutout-panel'){this.popup=null;await this.surface.startMask();this.render();return;}
            if(action==='cancel-crop'){this.tool='select';this.cropRect=null;this.render();return;}
            if(action==='edit-panel'){this.popup=null;await this.smartEdit.open(this.nodeId,this.selected,this.smartPresentation());return;}
            if(action==='fusion' || action==='download-layer'){await this.run(action);return;}
            if(action==='undo' || action==='redo'){if(this.smartEditing)this.smartEdit.history(action==='undo'?-1:1);else this.history(action==='undo'?-1:1);return;}
            if(['split','save','export','query','zip','psd'].includes(action)){this.popup=null;await this.run(action);return;}
            if(action!=='add' && !layer)return;
            if(layer?.locked && ['remove','up','down','convert'].includes(action))return;
            if(action==='convert'){
                const existing=this.doc.layers.find(item=>item.sourceLayerId===layer.id);
                if(existing){this.selected=existing.id;this.render();return;}
            }
            this.popup=null;
            if(action==='add'){this.remember();this.selected=D.addText(this.doc,t('newText')).id;}
            else if(action==='convert'){this.remember();const text=D.textLayers(layer,this.doc);layer.visible=false;this.doc.layers.splice(this.doc.layers.indexOf(layer)+1,0,...text);this.selected=text[0]?.id;}
            else this.session.action(action,layer.id);
            this.changed();
        }
        async run(action){
            if(this.busy)return;this.busy=true;this.error='';this.render();
            try{
                if(action==='fusion')await this.generate();
                else if(action==='merge'){const canvas=document.createElement('canvas');await D.paint(this.doc,canvas,{loadImage:url=>this.loadImage(url,false)});await this.adapter.merge(this.nodeId,canvas.toDataURL('image/png'),this.doc);this.dialog.close();CanvasLayerNode.layout();}
                else if(['download-layer','export','zip','psd'].includes(action))await this.exportFor(this.session,action);
                else if(action==='split'){
                    const settings=CanvasLayerSeparation.parameters({mode:'description',prompt:this.prompt || t('promptDefault'),
                        limit:this.limit,recognize:this.recognize,size:this.size},this.models.find(m=>m.key===this.modelKey),t('promptDefault'));
                    const target=await this.adapter.separate(this.nodeId,this.index,settings);
                    this.nodeId=target.id;this.session=CanvasLayerSession.get(target);this.index=0;this.popup=null;this.watch();
                }else if(action==='query')await this.adapter.query(this.nodeId);
                else{
                    const canvas=document.createElement('canvas');await D.paint(this.doc,canvas,{loadImage:url=>this.loadImage(url,false)});
                    await this.adapter.commit(this.nodeId,D.clone(this.doc),canvas.toDataURL('image/png'));this.messageKey='saved';
                }
            }catch(error){this.error=error.message;}finally{this.busy=false;this.render();}
        }
        watch(){
            clearInterval(this.timer);this.timer=setInterval(()=>{
                if(!this.dialog.open)return;
                const node=this.adapter.node(this.nodeId);
                if(node?.layerDocument){this.doc=D.clone(node.layerDraft || node.layerDocument);this.selected=this.doc.layers.at(-1)?.id;clearInterval(this.timer);}
                this.render();
            },1500);
        }
        loadImage(url,preview=true){
            const source=preview && url.startsWith('/assets/') ? '/api/media-preview?w=1024&url='+encodeURIComponent(url):url;
            if(preview && this.images.has(source))return this.images.get(source);
            const promise=new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=()=>{this.images.delete(source);reject(new Error(t('imageFailed')));};image.src=source;});
            if(preview)this.images.set(source,promise);return promise;
        }
        async paint(){if(this.surface)await this.surface.paint();}
        setZoom(action){
            const stage=this.dialog.querySelector('.layer-stage'),size=stageSize(stage),doc=this.smartEditing?this.smartDoc:this.doc;
            let view=this.smartEditing?this.smartView:this.view;if(!view)return;
            const full={x:0,y:0,width:doc.width,height:doc.height};
            if(action==='zoom-fit')view=CanvasLayerViewport.fit(size,full);
            else if(action==='zoom-selection'){
                if(!this.smartEditing&&!this.selectedLayer())return;
                view=CanvasLayerViewport.fit(size,this.smartEditing?full:D.extractLayer(this.doc,this.selected).bounds,60);
            }else{
                const value=action==='zoom-in'?view.zoom*1.2:action==='zoom-out'?view.zoom/1.2:Number(action.slice(5).replace('%',''))/100;
                if(!Number.isFinite(value)||value<=0){this.error=t('zoomInvalid');this.render();return;}
                view=CanvasLayerViewport.zoomAt(view,value,{x:size.width/2,y:size.height/2},Math.min(.25,CanvasLayerViewport.fit(size,full).zoom));
            }
            if(this.smartEditing)this.smartView=view;else this.view=view;
            this.error='';this.popup=null;this.render();if(this.smartEditing)this.smartEdit.layout();
        }
        smartPresentation(){
            const editor=this,stage=()=>this.dialog.querySelector('.layer-stage');
            return {fullscreen:true,container:()=>this.dialog,contains:target=>Boolean(target.closest('.layer-header,.layer-bottom-tools,.zoom-menu,.layer-list-pane')),
                onEditOpen(){editor.popup=null;editor.dialog.querySelectorAll('.layer-popup,.layer-annotation-palette').forEach(el=>el.remove());editor.smartEditing=true;editor.dialog.classList.add('is-smart-editing');},
                onEditClose(){editor.smartEditing=false;editor.smartView=null;editor.dialog.classList.remove('is-smart-editing');if(editor.dialog.open)editor.render();},
                focusLayer(id,layerId,doc){editor.smartDoc=doc;editor.smartView=CanvasLayerViewport.fit(stageSize(stage()),{x:0,y:0,width:doc.width,height:doc.height},40);editor.smartMinimumZoom=Math.min(.25,editor.smartView.zoom);editor.positionBoard();return {...editor.view};},
                restoreViewport(view){editor.view=view;},
                layerBounds(){if(!editor.smartView)return;const r=stage().getBoundingClientRect(),v=editor.smartView;return {left:r.left+v.x,top:r.top+v.y,width:editor.smartDoc.width*v.zoom,height:editor.smartDoc.height*v.zoom,bottom:r.top+v.y+editor.smartDoc.height*v.zoom};},
                controlBounds(){const r=stage().getBoundingClientRect();return {left:r.left+12,top:r.top,width:r.width-24,right:r.right-12,bottom:r.bottom-55};},
                pan(dx,dy){editor.smartView.x+=dx;editor.smartView.y+=dy;editor.positionBoard();},
                zoom(x,y,delta){const r=stage().getBoundingClientRect();editor.smartView=CanvasLayerViewport.zoomAt(editor.smartView,editor.smartView.zoom*Math.exp(-delta*.01),{x:x-r.left,y:y-r.top},editor.smartMinimumZoom);editor.positionBoard();},
                syncHistory(s){for(const [key,list] of [['undo',s.undo],['redo',s.redo]]){const button=editor.dialog.querySelector('[data-action='+key+']');if(button){button.disabled=!list.length||Boolean(s.pendingTaskId||s.submitting);button.title=t(list.length?key:key==='undo'?'noUndo':'noRedo');}}},
                keyAction(event){const action=CanvasLayerViewport.keyAction(event);if(action){editor.setZoom(action);return true;}return false;}
            };
        }
        async importFiles(files){
            this.busy=true;this.render();
            try{
                this.remember();
                for(const file of files){
                    const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file);});
                    const response=await fetch('/api/ai/upload-base64',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:file.name,data,content_type:file.type})});
                    const result=await response.json();if(!response.ok)throw new Error(result.detail || t('imageFailed'));
                    const asset=result.files[0],image=await this.loadImage(asset.url,false),fit=this.doc.layers.length?Math.min(1,this.doc.width*.65/image.width,this.doc.height*.65/image.height):1;
                    if(!this.doc.layers.length){this.doc.width=image.width;this.doc.height=image.height;}
                    const layer={id:'import-'+Date.now()+'-'+this.doc.layers.length,kind:'image',name:file.name,asset:{...asset,width:image.width,height:image.height},
                        x:(this.doc.width-image.width*fit)/2,y:(this.doc.height-image.height*fit)/2,width:image.width*fit,height:image.height*fit,rotation:0,opacity:1,visible:true,locked:false};
                    this.doc.layers.push(layer);this.selected=layer.id;
                }
                this.changed();
            }catch(error){this.error=error.message;}finally{this.busy=false;this.render();}
        }
        async ensureConfig(){
            if(!this.configPromise)this.configPromise=fetch('/api/config').then(async response=>{if(!response.ok)throw Error(t('noProvider'));return response.json();}).catch(error=>{this.configPromise=null;throw error;});
            const config=await this.configPromise;
            this.imageModels=(config.api_providers || []).filter(p=>p.enabled!==false).flatMap(p=>(p.image_models || []).filter(model=>!model.endsWith('/layer-decomposition')).map(model=>({provider:p.id,model,label:(p.name || p.id)+' · '+model})));
            return this.imageModels;
        }
        async submitImage(session,nodeId){
            const chosen=this.chooseImageModel(session,await this.ensureConfig());
            if(!chosen)throw Error(t('noProvider'));
            const canvas=document.createElement('canvas'),doc=session.doc;
            await D.paint(doc,canvas,{loadImage:url=>this.loadImage(url,false)});
            const upload=await this.adapter.upload(canvas.toDataURL('image/png'));
            const longest=Number(session.outputResolution || 1536),factor=longest/Math.max(doc.width,doc.height);
            const size=Math.max(64,Math.round(doc.width*factor/16)*16)+'x'+Math.max(64,Math.round(doc.height*factor/16)*16);
            const prompt=session.prompt;
            const target=await this.adapter.separate(nodeId,0,{provider_id:chosen.provider,model:chosen.model,size,
                prompt:prompt || (StudioI18n.lang()==='en'?'Blend the composition. Preserve the product, text and logo.':'融合当前构图，协调光影，保留商品、文字和标志。'),_reference:upload});
            return target;
        }
        chooseImageModel(session,models){
            const preferred=session.node.layerSettings?.provider_id;
            const chosen=models.find(m=>m.provider+'|'+m.model===session.imageModelKey) || models.find(m=>m.provider===preferred && m.model==='seedream-v5.5') || models.find(m=>m.model==='seedream-v5.5') || models[0];
            if(chosen)session.imageModelKey=chosen.provider+'|'+chosen.model;return chosen;
        }
        async generate(){
            await this.submitImage(this.session,this.nodeId);
            this.dialog.close();clearInterval(this.timer);
        }
        bindDrag(){
            const root=this.dialog.querySelector('.layer-artboard');
            this.surface=new CanvasLayerSurface.Surface(root,this.session,{
                canInteract:()=>!this.spacePan,
                loadImage:url=>this.loadImage(url),onChange:()=>this.changed(),onDraft:()=>this.adapter.draft(this.nodeId,D.clone(this.doc)),
                segmentImage:data=>this.segmentImage(data),
                onSelection:()=>this.selectionChanged(),onMode:()=>this.render(),onLayout:()=>this.positionBoard(),onError:error=>{this.error=error.message;},
                onGestureStart:()=>{this.popup=null;this.dialog.querySelectorAll('.layer-popup,.layer-annotation-palette').forEach(el=>el.remove());},
                onBoardStart:()=>{this.boardPan={...this.view};},
                onBoardResize:bounds=>{this.view={...this.boardPan,x:this.boardPan.x+bounds.left*this.boardPan.zoom,y:this.boardPan.y+bounds.top*this.boardPan.zoom};this.positionBoard();},
                onMaskResult:(layer,canvas)=>this.applyMask(layer,canvas)
            });
            const stage=this.dialog.querySelector('.layer-stage');let pan;
            stage.onpointerdown=e=>{if(e.button===1 || e.altKey || this.spacePan){e.preventDefault();pan={x:e.clientX,y:e.clientY,view:{...this.view}};stage.setPointerCapture(e.pointerId);}else if(e.target===stage&&e.button===0){this.selected='';this.tool='select';this.popup=null;this.render();}};
            stage.onpointermove=e=>{if(pan){this.view={...pan.view,x:pan.view.x+e.clientX-pan.x,y:pan.view.y+e.clientY-pan.y};this.positionBoard();}};
            stage.onpointerup=()=>{pan=null;};
            stage.onwheel=e=>{e.preventDefault();const r=stage.getBoundingClientRect();this.view=CanvasLayerViewport.wheel(this.view,e,{x:e.clientX-r.left,y:e.clientY-r.top},this.minimumZoom);this.positionBoard();this.surface.layout();};
        }
        async exportFor(session,action){
            return CanvasLayerExport.exportDocument(session.doc,action,{selected:session.selected,loadImage:url=>this.loadImage(url,false),
                upload:(data,name)=>this.adapter.upload(data,name),download:(blob,name)=>this.download(blob,name)});
        }
        download(blob,name){CanvasLayerExport.download(blob,name);}
        async applyMask(layer,canvas){
            const asset=await this.adapter.upload(canvas.toDataURL('image/png'),'cutout.png');this.remember();layer.sourceAsset ||= D.clone(layer.asset);
            layer.asset={...asset,width:canvas.width,height:canvas.height};delete layer.crop;layer.flipX=false;layer.flipY=false;
        }
        async segmentImage(data){
            const response=await fetch('/api/image-segmentation',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({data})});
            const result=await response.json();if(!response.ok)throw Error(t(result.detail?.code==='SEGMENTATION_UNAVAILABLE'?'subjectUnavailable':'subjectFailed'));
            return result.mask;
        }
        async pickLibrary(){
            this.popup=null;const items=await this.adapter.pickLibrary();if(items?.length)await this.importAssets(items);this.render();
        }
        async importAssets(assets,sourceNodeId=''){
            this.remember();for(const asset of assets){const image=await this.loadImage(asset.url,false);this.session.addImage(asset,image.width,image.height,sourceNodeId);}this.changed();
        }

    }
    for(const key of ['doc','selected','tool','undo','redo','penColor','penWidth'])Object.defineProperty(Editor.prototype,key,{get(){return this.session[key];},set(value){this.session[key]=value;}});
    window.CanvasLayerEditor={install:adapter=>new Editor(adapter)};
})();
