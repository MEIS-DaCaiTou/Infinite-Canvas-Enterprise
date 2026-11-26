/* Inline view: screen-sized controls around the shared editing surface. */
(function(){
    const D=CanvasLayerDocument,t=key=>StudioI18n.t('layers.'+key),boards=new Map();let adapter,editor;
    const esc=value=>String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const icon=name=>`<i data-lucide="${name}"></i>`;
    const button=(action,label,name,labelled=false)=>`<button type="button" class="layer-button ${labelled?'labelled':'icon'}" data-layer-action="${action}" aria-label="${esc(t(label))}" title="${esc(t(label))}">${icon(name)}${labelled?`<span>${esc(t(label))}</span>`:''}</button>`;
    function html(node,layout){
        const s=CanvasLayerSession.get(node);
        return `<div class="layer-inline-board" data-layer-node="${esc(node.id)}" style="width:${layout.width}px;height:${layout.height}px"><div class="layer-inline-title" title="${esc(t('moveNode'))}">${icon('grip-vertical')}${icon('layers')}<span>${esc(t('title'))}</span><small>${esc(t('doubleClickEdit'))}</small></div><div class="layer-inline-surface">${CanvasLayerSurface.html()}</div>
            ${!s.doc.layers.length?`<div class="layer-empty"><i data-lucide="layers"></i><p>${esc(t('emptyHint'))}</p><button class="layer-button" data-layer-action="import-menu">${esc(t('addImage'))}</button></div>`:''}
            <div class="layer-inline-badges">${button('full','full','maximize-2')}<button type="button" data-layer-action="full" aria-label="${esc(t('layers'))}">${icon('layers')}<span data-layer-count>${s.doc.layers.length}</span></button></div><input type="file" accept="image/*" multiple hidden data-inline-import></div>`;
    }
    class Board{
        constructor(root,node){
            this.root=root;this.node=node;this.s=CanvasLayerSession.get(node);
            this.portal=document.createElement('div');this.portal.className='layer-node-portal';document.body.append(this.portal);
            this.surface=new CanvasLayerSurface.Surface(root.querySelector('.layer-inline-surface'),this.s,{
                canEdit:()=>Boolean(this.s.inlineEditing&&adapter.isSingleSelected(node.id)&&!editor.smartEdit.owns(node.id)),
                canInteract:()=>!this.s.busy&&!editor.smartEdit.owns(node.id),
                onGestureStart:()=>clearTimeout(this.s.commitTimer),
                loadImage:url=>editor.loadImage(url),onChange:()=>this.changed(),onDraft:()=>adapter.draft(node.id,D.clone(this.s.doc)),
                segmentImage:data=>editor.segmentImage(data),
                onSelect:()=>{document.activeElement?.blur();this.s.inlineEditing=true;adapter.select(node.id);},onSelection:()=>this.controls(),onMode:()=>this.controls(),onLayout:()=>this.layout(),onError:error=>this.message(error.message),
                onDropOutside:layer=>this.detach(layer),
                onBoardStart:()=>{this.geometry={x:node.x,y:node.y,w:Number(node.w) || 340};},
                onBoardResize:(bounds,initial)=>{const scale=this.geometry.w/initial.width;node.x=this.geometry.x+bounds.left*scale;node.y=this.geometry.y+bounds.top*scale;node.w=bounds.width*scale;node.h=bounds.height*scale;
                    Object.assign(root.closest('.image-node').style,{left:node.x+'px',top:node.y+'px',width:node.w+'px',height:node.h+'px'});root.style.width=node.w+'px';root.style.height=node.h+'px';},
                onMaskResult:async(layer,canvas)=>{const asset=await adapter.upload(canvas.toDataURL('image/png'),'cutout.png');this.s.remember();layer.sourceAsset ||= D.clone(layer.asset);layer.asset={...asset,width:canvas.width,height:canvas.height};delete layer.crop;layer.flipX=false;layer.flipY=false;}
            });this.bind();this.controls();
        }
        message(value){this.s.message=value;const el=this.portal.querySelector('.layer-inline-message');if(el)el.textContent=value;}
        async changed(){
            this.s.popup=null;adapter.draft(this.node.id,D.clone(this.s.doc));await adapter.flush(this.node.id);this.surface.paint();this.controls();clearTimeout(this.s.commitTimer);
            this.s.commitTimer=setTimeout(()=>this.commit().catch(error=>this.message(error.message)),1500);
        }
        async commit(options){const doc=D.clone(this.s.doc),canvas=document.createElement('canvas');await D.paint(doc,canvas,{loadImage:url=>editor.loadImage(url,false)});await adapter.commit(this.node.id,doc,canvas.toDataURL('image/png'),options);}
        geometry(){
            const outer=this.root.getBoundingClientRect(),inner=this.surface.root.getBoundingClientRect(),scale=outer.width/(Number(this.node.w)||340);
            return {x:this.node.x+(inner.left-outer.left)/scale,y:this.node.y+(inner.top-outer.top)/scale,width:inner.width/scale};
        }
        async detach(layer){
            const s=this.s,plan=D.extractLayer(s.doc,layer.id),geometry=this.geometry();s.busy=true;clearTimeout(s.commitTimer);
            try{
                let asset=plan.directAsset;
                if(!asset){
                    const canvas=document.createElement('canvas');let scale=1;
                    if(layer.kind==='image'){const image=await editor.loadImage(layer.asset.url,false);scale=Math.max(1,image.width*(layer.crop?.width||1)/layer.width,image.height*(layer.crop?.height||1)/layer.height);}
                    await D.paint(plan.document,canvas,{scale,loadImage:url=>editor.loadImage(url,false)});
                    const uploaded=await adapter.upload(canvas.toDataURL('image/png'),layer.name || 'layer.png');asset={...uploaded,width:canvas.width,height:canvas.height};
                }
                adapter.detach(this.node,plan,asset,geometry);
                s.doc=plan.remaining;s.selected='';s.undo=[];s.redo=[];
                s.commitTimer=setTimeout(()=>{if(adapter.node(this.node.id)===this.node)this.commit({skipUndo:true}).catch(error=>this.message(error.message));},1500);
                adapter.render();
            }catch(error){s.history(-1);this.surface.paint();throw error;}
            finally{s.busy=false;boards.get(this.node.id)?.controls();}
        }
        popupHtml(){
            const menu=(action,key,name)=>`<button type="button" class="layer-menu-item" data-layer-action="${action}">${icon(name)}${esc(t(key))}</button>`;
            if(this.s.popup==='import')return menu('upload','upload','upload')+menu('library','fromLibrary','folder')+menu('canvas','fromCanvas','scan');
            if(this.s.popup==='brush')return `<label>${esc(t('color'))}<input type="color" data-layer-setting="penColor" value="${this.s.penColor}"></label><label>${esc(t('brushSize'))}<input type="range" min="1" max="60" data-layer-setting="penWidth" value="${this.s.penWidth}"></label>`;
            if(this.s.popup==='settings')return `${menu('mode-fusion','fusion','scan')+menu('mode-merge','merge','copy')}<label>${esc(t('provider'))}<select data-layer-setting="imageModelKey">${(editor.imageModels || []).map(m=>`<option value="${esc(m.provider+'|'+m.model)}" ${this.s.imageModelKey===m.provider+'|'+m.model?'selected':''}>${esc(m.label)}</option>`).join('')}</select></label><label>${esc(t('resolution'))}<select data-layer-setting="outputResolution">${[1024,1536,2048].map(n=>`<option value="${n}" ${Number(this.s.outputResolution || 1536)===n?'selected':''}>${n}px</option>`).join('')}</select></label>`;
            if(this.s.popup==='download')return menu('download-layer','layerPng','image')+menu('download-all','export','download')+menu('zip','zip','layers')+menu('split','split','scan-line');return '';
        }
        controls(){
            const s=this.s,layer=s.layer(),has=Boolean(layer && layer.visible),popup=this.popupHtml();
            this.root.classList.toggle('is-editing',Boolean(s.inlineEditing));
            const count=this.root.querySelector('[data-layer-count]');if(count)count.textContent=s.doc.layers.length;
            this.portal.innerHTML=`<div class="layer-inline-floating layer-floating-tools" role="toolbar" aria-label="${esc(t('layers'))}" ${!s.inlineEditing || !has || !['select','pen','arrow','text','eraser'].includes(s.tool)?'hidden':''}>
                ${layer?.kind==='text'?button('text-edit','text','type')+button('text-style','textStyle','sliders-horizontal'):button('edit','edit','sparkles')+button('cutout','cutout','scan-face')+button('crop','crop','crop')}
                <span class="layer-tool-divider"></span>${button('rotate90','rotate90','rotate-cw')}${button('flipX','flipX','flip-horizontal-2')}${button('flipY','flipY','flip-vertical-2')}${button('fit-layer','fit','scan')}<span class="layer-tool-divider"></span>${button('full','full','maximize-2',true)}${button('remove','remove','trash-2')}${button('download-menu','export','download')}</div>
                <div class="layer-inline-annotations" role="toolbar" aria-label="${esc(t('tool'))}">${button('import-menu','addImage','plus',true)}${button('tool-pen','pen','pencil')}${button('tool-arrow','arrow','arrow-up-right')}${button('tool-text','text','type')}${button('tool-eraser','eraser','eraser')}<span class="layer-tool-divider"></span>${button('undo','undo','undo-2')}${button('redo','redo','redo-2')}<span class="layer-tool-divider"></span>${s.inlineEditing?button('finish-editing','finishEditing','check',true):''}${button('full','full','maximize-2',true)}</div>
                <div class="layer-inline-fusion"><button class="layer-mode-button" data-layer-action="settings">${icon(s.outputMode==='merge'?'copy':'scan')}${esc(t(s.outputMode==='merge'?'merge':'fusionMode'))}${icon('chevron-down')}</button><input aria-label="${esc(t('fusionHint'))}" placeholder="${esc(t('fusionHint'))}" value="${esc(s.prompt)}" data-layer-prompt><button class="layer-button primary" data-layer-action="output" ${s.busy || !s.doc.layers.length?'disabled':''}>${esc(t(s.outputMode==='merge'?'merge':'fusion'))}${icon(s.outputMode==='merge'?'copy':'sparkles')}</button></div>
                <div class="layer-surface-tools">${CanvasLayerSurface.toolHtml(s)}</div><div class="layer-popup layer-inline-popup ${s.popup==='import' || s.popup==='download'?'menu':''}" ${!popup?'hidden':''}>${popup}</div><div class="layer-inline-message" role="status">${esc(s.message || '')}</div>`;
            this.portal.querySelector('[data-layer-action=undo]').disabled=!s.undo.length;this.portal.querySelector('[data-layer-action=redo]').disabled=!s.redo.length;
            this.portal.querySelectorAll('[data-layer-action^="tool-"]').forEach(b=>b.classList.toggle('active',b.dataset.layerAction==='tool-'+s.tool));
            const footer=this.portal.querySelector('.layer-inline-annotations');footer.hidden=s.tool==='crop'||s.tool==='mask';this.portal.querySelector('.layer-inline-fusion').hidden=footer.hidden;
            this.portal.onmousedown=e=>e.stopPropagation();this.portal.onpointerdown=e=>e.stopPropagation();
            this.portal.onclick=e=>{e.stopPropagation();const surface=e.target.closest('[data-surface-action]'),action=e.target.closest('[data-layer-action]');if(surface){e.preventDefault();this.surface.action(surface.dataset.surfaceAction).catch(error=>this.message(error.message));}else if(action){e.preventDefault();this.action(action.dataset.layerAction).catch(error=>this.message(error.message));}};
            this.portal.oninput=e=>{const key=e.target.dataset.layerSetting;if(key)this.s[key]=e.target.value;if(e.target.hasAttribute('data-layer-prompt'))this.s.prompt=e.target.value;if(e.target.hasAttribute('data-mask-size'))this.s.maskSize=Number(e.target.value);};this.portal.onchange=this.portal.oninput;
            window.lucide?.createIcons({root:this.portal});this.layout();
        }
        layout(){
            this.root.classList.toggle('is-smart-editing',editor.smartEdit.owns(this.node.id));
            const selected=adapter.isSingleSelected(this.node.id);this.portal.hidden=!selected || editor.dialog.open || editor.smartEdit.owns(this.node.id);
            if(!selected){this.s.popup=null;this.portal.querySelector('.layer-inline-popup')?.setAttribute('hidden','');return;}
            const r=this.root.getBoundingClientRect();this.root.style.setProperty('--layer-control-scale',String(this.root.clientWidth/Math.max(1,r.width)));const layer=this.s.layer(),scale=r.width/this.s.doc.width,floating=this.portal.querySelector('.layer-inline-floating');if(!floating)return;
            const x=layer?r.left+(layer.x+layer.width/2)*scale:r.left+r.width/2,y=layer?r.top+layer.y*scale:r.top,clamp=(v,w)=>Math.max(w/2+8,Math.min(innerWidth-w/2-8,v));
            Object.assign(floating.style,{left:clamp(x,floating.offsetWidth)+'px',top:Math.max(46,y-8)+'px'});
            const bottom=Math.min(r.bottom,innerHeight-130);
            for(const [selector,offset] of [['.layer-inline-annotations',12],['.layer-inline-fusion',64],['.layer-surface-tools',12]]){const el=this.portal.querySelector(selector);Object.assign(el.style,{left:clamp(r.left+r.width/2,el.offsetWidth)+'px',top:Math.min(innerHeight-el.offsetHeight-8,bottom+offset)+'px'});}
            const popup=this.portal.querySelector('.layer-inline-popup');if(!popup.hidden)Object.assign(popup.style,{left:Math.max(8,Math.min(innerWidth-popup.offsetWidth-8,r.left-15))+'px',top:Math.max(8,r.bottom-popup.offsetHeight-5)+'px'});
            Object.assign(this.portal.querySelector('.layer-inline-message').style,{left:Math.max(8,r.left)+'px',top:r.bottom+123+'px'});
        }
        async import(files){const assets=[];for(const file of files){const data=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(file);});assets.push(await adapter.upload(data,file.name,file.type));}await this.addAssets(assets);}
        async addAssets(assets,sourceNodeId=''){this.s.remember();for(const asset of assets){const image=await editor.loadImage(asset.url,false);this.s.addImage(asset,image.width,image.height,sourceNodeId);}this.s.inlineEditing=true;adapter.select(this.node.id);await this.changed();adapter.render();}
        async moveAsset(asset,sourceNodeId,rect){
            const s=this.s;if(s.busy)throw new Error(t('working'));const geometry=this.geometry();s.busy=true;clearTimeout(s.commitTimer);
            try{
                const image=await editor.loadImage(asset.url,false);
                const next=new CanvasLayerSession.Session({...this.node,layerDraft:s.doc});
                const layer=next.addImage(asset,image.width,image.height),scale=next.doc.width/geometry.width;
                const bounds={x:(rect.x-geometry.x)*scale,y:(rect.y-geometry.y)*scale,width:rect.width*scale,height:rect.height*scale};
                const element=adapter.node(sourceNodeId)?.layerElement;
                if(element?.previewUrl===asset.url)Object.assign(layer,D.placeLayer(element.document,bounds),{id:layer.id});
                else Object.assign(layer,bounds);
                adapter.moveInto(this.node,sourceNodeId,next.doc);
                s.doc=next.doc;s.selected=layer.id;s.inlineEditing=true;s.undo=[];s.redo=[];
                s.commitTimer=setTimeout(()=>{if(adapter.node(this.node.id)===this.node)this.commit({skipUndo:true}).catch(error=>this.message(error.message));},1500);
                adapter.render();
            }finally{s.busy=false;boards.get(this.node.id)?.controls();}
        }
        async output(){
            if(this.s.busy)return;this.s.busy=true;this.s.message=t('working');this.controls();
            try{clearTimeout(this.s.commitTimer);adapter.draft(this.node.id,D.clone(this.s.doc));await adapter.flush(this.node.id);
                if(this.s.outputMode==='merge'){const canvas=document.createElement('canvas');await D.paint(this.s.doc,canvas,{loadImage:url=>editor.loadImage(url,false)});await adapter.merge(this.node.id,canvas.toDataURL('image/png'),this.s.doc);}else await editor.submitImage(this.s,this.node.id);
                this.s.message='';this.s.popup=null;
            }catch(error){this.s.message=error.message;}finally{this.s.busy=false;boards.get(this.node.id)?.controls();}
        }
        async action(action){
            const s=this.s;adapter.select(this.node.id);
            if(action==='finish-editing'){s.inlineEditing=false;s.tool='select';s.popup=null;this.surface.layout();this.controls();return;}
            if(action==='full' || action==='text-style' || action==='split'){
                clearTimeout(s.commitTimer);s.popup=null;adapter.draft(this.node.id,D.clone(s.doc));await adapter.flush(this.node.id);await editor.open(this.node.id,0,{selectedLayerId:s.selected});
                if(action==='text-style')editor.popup='style';if(action==='split')editor.popup='split';editor.render();this.layout();return;
            }
            if(action==='import-menu' || action==='download-menu'){const key=action.slice(0,-5);s.popup=s.popup===key?null:key;this.controls();return;}
            if(action==='upload'){s.popup=null;this.controls();this.root.querySelector('[data-inline-import]').click();return;}
            if(action==='library'){s.popup=null;this.controls();const items=await adapter.pickLibrary();if(items?.length)await this.addAssets(items);return;}
            if(action==='canvas'){s.popup=null;this.controls();adapter.pickFromCanvas(this.node.id,(items,sourceId)=>this.addAssets(items,sourceId));return;}
            if(action==='crop'){s.inlineEditing=true;s.popup=null;s.startCrop();this.surface.layout();this.controls();return;}
            if(action==='cutout'){clearTimeout(s.commitTimer);s.inlineEditing=true;s.popup=null;this.message(t('working'));await this.surface.startMask();this.message('');return;}
            if(action==='edit'){s.popup=null;clearTimeout(s.commitTimer);await editor.smartEdit.open(this.node.id,s.selected);this.controls();return;}
            if(action==='settings'){editor.chooseImageModel(s,await editor.ensureConfig());s.popup=s.popup===action?null:action;this.controls();return;}
            if(action==='output'){await this.output();return;}
            if(action.startsWith('mode-')){s.outputMode=action.slice(5);s.popup=null;this.controls();return;}
            if(action.startsWith('tool-')){s.inlineEditing=true;s.tool=action.slice(5);s.popup=['pen','arrow','eraser'].includes(s.tool)?'brush':null;this.surface.layout();this.controls();return;}
            if(action==='undo' || action==='redo'){if(s.history(action==='undo'?-1:1))await this.changed();return;}
            if(action==='text-edit'){if(s.layer()?.kind==='text')this.surface.editText(s.layer());return;}
            if(['download-layer','download-all','zip'].includes(action)){await editor.exportFor(s,action);s.popup=null;this.controls();return;}
            if(s.action(action))await this.changed();
        }
        bind(){
            this.root.addEventListener('mousedown',e=>{
                const selected=adapter.isSelected(this.node.id);
                if(!selected)adapter.select(this.node.id);
                if(e.target===this.root || e.target.closest('.layer-inline-title') || e.ctrlKey || e.metaKey)return;
                e.stopPropagation();
            });
            this.root.addEventListener('click',e=>{e.stopPropagation();const action=e.target.closest('[data-layer-action]');if(action)this.action(action.dataset.layerAction).catch(error=>this.message(error.message));});
            this.root.addEventListener('dblclick',e=>{if(e.target.closest('button,input,.layer-inline-title'))return;e.preventDefault();e.stopPropagation();this.s.inlineEditing=true;adapter.select(this.node.id);this.s.selected=this.surface.hit(this.surface.point(e))?.id || '';this.surface.layout();this.controls();});
            this.root.querySelector('[data-inline-import]').onchange=e=>this.import(e.target.files).catch(error=>this.message(error.message));
        }
    }
    document.addEventListener('keydown',event=>{
        if(editor?.dialog.open || editor?.smartEdit.state || event.target.closest('textarea,[contenteditable=true],input:not([type=file]):not([type=range]):not([type=color])'))return;
        const board=[...boards.values()].find(b=>adapter.isSingleSelected(b.node.id));if(!board)return;
        const key=event.key.toLowerCase();let action;
        if((event.ctrlKey || event.metaKey) && key==='z')action=board.s.tool==='mask'?(event.shiftKey?'mask-redo':'mask-undo'):(event.shiftKey?'redo':'undo');
        if((action==='undo' || action==='redo') && !board.s[action].length)return;
        if(key==='escape' && ['crop','mask'].includes(board.s.tool))action='cancel';
        else if(key==='escape' && board.s.inlineEditing)action='finish-editing';
        if((key==='delete' || key==='backspace') && board.s.layer() && board.s.tool==='select')action='remove';
        if(!action)return;event.preventDefault();event.stopImmediatePropagation();
        const task=action.startsWith('mask-') || action==='cancel'?board.surface.action(action):board.action(action);task.catch(error=>board.message(error.message));
    },true);
    window.CanvasLayerNode={html,toolbar:()=>'',install:(a,e)=>{adapter=a;editor=e;},layout:()=>boards.forEach(board=>board.layout()),addAssets:(id,items,sourceNodeId='')=>boards.get(id).addAssets(items,sourceNodeId),
        changed:id=>boards.get(id)?.changed(),
        moveAsset:(id,item,sourceNodeId,rect)=>boards.get(id).moveAsset(item,sourceNodeId,rect),
        bind:world=>{boards.forEach(board=>board.portal.remove());boards.clear();world.querySelectorAll('[data-layer-node]').forEach(root=>{const node=adapter.node(root.dataset.layerNode);if(node)boards.set(node.id,new Board(root,node));});}};
})();
