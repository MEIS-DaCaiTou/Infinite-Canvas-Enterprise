/* The same layer, crop and mask gestures are used inline and fullscreen. */
(function(){
    const D=CanvasLayerDocument,B=CanvasLayerBitmap,t=key=>StudioI18n.t('layers.'+key);
    const handles=['nw','n','ne','e','se','s','sw','w'];
    const esc=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const html=()=>`<canvas class="layer-preview" aria-label="${esc(t('preview'))}"></canvas><div class="layer-render-items"></div><canvas class="layer-ink-preview"></canvas>
        <div class="layer-selection">${handles.map(c=>`<button type="button" class="layer-handle" data-corner="${c}" aria-label="${esc(t('geometry'))} ${c}"></button>`).join('')}</div>
        ${handles.map(c=>`<button type="button" class="layer-board-handle" data-board-edge="${c}" aria-label="${esc(t('boardResize'))} ${c}"></button>`).join('')}
        <div class="layer-crop-frame" hidden><div class="layer-crop-area">${handles.map(c=>`<button type="button" class="layer-handle" data-crop-edge="${c}" aria-label="${esc(t('crop'))} ${c}"></button>`).join('')}</div></div><canvas class="layer-mask-preview" hidden></canvas>`;
    function toolHtml(s){
        if(s.tool==='crop')return `<div class="layer-composition-settings" role="toolbar" aria-label="${esc(t('crop'))}">${['21:9','16:9','4:3','1:1','3:4','9:16'].map(value=>`<button data-surface-action="ratio-${value}" class="${s.crop?.ratio===Number(value.split(':')[0])/Number(value.split(':')[1])?'active':''}">${value}</button>`).join('')}<button data-surface-action="apply-crop" class="primary">${esc(t('confirm'))}</button><button data-surface-action="cancel">${esc(t('cancel'))}</button></div>`;
        if(s.tool==='mask')return `<div class="layer-composition-settings mask-settings" role="toolbar" aria-label="${esc(t('cutout'))}">${['brush','erase','quick'].map((mode,i)=>`<button data-surface-action="mask-${mode}" aria-label="${esc(t('mask'+mode))}" class="${s.maskMode===mode?'active':''}"><i data-lucide="${['paintbrush','eraser','scan-face'][i]}"></i></button>`).join('')}
            <button data-surface-action="mask-subject" ${s.mask?.busy?'disabled':''}>${esc(t('autoSubject'))}</button><button data-surface-action="mask-auto" ${s.mask?.busy?'disabled':''} title="${esc(t('autoBackgroundHint'))}">${esc(t('autoBackground'))}</button><button data-surface-action="mask-invert" title="${esc(t('invert'))}"><i data-lucide="flip-horizontal-2"></i></button>
            <input aria-label="${esc(t('brushSize'))}" type="range" min="2" max="100" value="${s.maskSize || 24}" data-mask-size><button data-surface-action="mask-undo" aria-label="${esc(t('undo'))}"><i data-lucide="undo-2"></i></button><button data-surface-action="mask-redo" aria-label="${esc(t('redo'))}"><i data-lucide="redo-2"></i></button>
            <button data-surface-action="apply-mask" class="primary" ${s.mask?.busy?'disabled':''}>${esc(t('applyMask'))}</button><button data-surface-action="cancel">${esc(t('cancel'))}</button><span class="layer-mask-status" role="status">${esc(s.mask?.busy?t('subjectLoading'):(s.maskError || ''))}</span></div>`;
        return '';
    }
    function local(layer,p){const a=-layer.rotation*Math.PI/180,dx=p.x-layer.x-layer.width/2,dy=p.y-layer.y-layer.height/2;return{x:dx*Math.cos(a)-dy*Math.sin(a)+layer.width/2,y:dx*Math.sin(a)+dy*Math.cos(a)+layer.height/2};}
    class Surface{
        constructor(root,session,options){this.root=root;this.s=session;this.o=options;this.elements=new Map();this.bind();this.paint();}
        point(event){const r=this.root.getBoundingClientRect();return{x:(event.clientX-r.left)/r.width*this.s.doc.width,y:(event.clientY-r.top)/r.height*this.s.doc.height};}
        hit(p){
            return [...this.s.doc.layers].reverse().find(layer=>{
                if(!layer.visible || layer.locked)return false;const q=local(layer,p);
                if(q.x<0 || q.y<0 || q.x>=layer.width || q.y>=layer.height)return false;
                const canvas=this.elements.get(layer.id);if(layer.kind!=='image' || !canvas?.width)return true;
                return canvas.getContext('2d').getImageData(Math.floor(q.x/layer.width*canvas.width),Math.floor(q.y/layer.height*canvas.height),1,1).data[3]>8;
            });
        }
        layout(){
            const doc=this.s.doc,scale=this.root.clientWidth/doc.width;
            this.root.style.setProperty('--layer-control-scale',String(this.root.clientWidth/Math.max(1,this.root.getBoundingClientRect().width)));
            doc.layers.forEach((layer,index)=>{const el=this.elements.get(layer.id);if(el)Object.assign(el.style,{left:layer.x*scale+'px',top:layer.y*scale+'px',width:layer.width*scale+'px',height:layer.height*scale+'px',transform:`rotate(${layer.rotation}deg)`,opacity:layer.opacity,display:layer.visible?'block':'none',visibility:layer.id===this.editingText?'hidden':'',zIndex:index+1});});
            const editable=!this.o.canEdit || this.o.canEdit(),layer=this.s.layer(),selection=this.root.querySelector('.layer-selection');selection.hidden=Boolean(this.editingText) || !editable || !layer || !layer.visible || this.s.tool!=='select';
            if(layer)Object.assign(selection.style,{left:layer.x*scale+'px',top:layer.y*scale+'px',width:layer.width*scale+'px',height:layer.height*scale+'px',transform:`rotate(${layer.rotation}deg)`,zIndex:doc.layers.length+3});
            this.root.querySelectorAll('[data-board-edge]').forEach(el=>el.hidden=!editable || this.s.tool!=='select');
            const crop=this.root.querySelector('.layer-crop-frame'),mask=this.root.querySelector('.layer-mask-preview');crop.hidden=this.s.tool!=='crop';mask.hidden=this.s.tool!=='mask' || !this.s.mask;
            if(layer && this.s.tool==='crop'){
                const r=this.s.crop;Object.assign(crop.style,{left:layer.x*scale+'px',top:layer.y*scale+'px',width:layer.width*scale+'px',height:layer.height*scale+'px',transform:`rotate(${layer.rotation}deg)`,zIndex:doc.layers.length+4});
                if(r)Object.assign(crop.firstElementChild.style,{left:r.x*scale+'px',top:r.y*scale+'px',width:r.width*scale+'px',height:r.height*scale+'px'});
            }
            if(layer && this.s.mask)Object.assign(mask.style,{left:layer.x*scale+'px',top:layer.y*scale+'px',width:layer.width*scale+'px',height:layer.height*scale+'px',transform:`rotate(${layer.rotation}deg)`,zIndex:doc.layers.length+4});
            this.o.onLayout?.();
        }
        async paint(){
            const doc=this.s.doc,container=this.root.querySelector('.layer-render-items'),ids=new Set(doc.layers.map(l=>l.id));
            for(const [id,el] of this.elements)if(!ids.has(id)){el.remove();this.elements.delete(id);}
            for(const layer of doc.layers){
                let el=this.elements.get(layer.id);if(!el){el=document.createElement('canvas');el.className='layer-render-item';el.dataset.surfaceLayer=layer.id;el.setAttribute('aria-label',layer.name || layer.text || t('image'));container.append(el);this.elements.set(layer.id,el);}
                const signature=JSON.stringify([layer.asset?.url,layer.crop,layer.width,layer.height,layer.flipX,layer.flipY,layer.text,layer.fontSize,layer.fontFamily,layer.color,layer.bold,layer.italic,layer.fontWeight,layer.lineHeight]);
                if(el.dataset.rendered!==signature){
                    el.dataset.rendered=signature;const copy={...layer,x:0,y:0,rotation:0,opacity:1,visible:true};
                    try{await D.paint({width:layer.width,height:layer.height,layers:[copy]},el,{scale:Math.min(1,1200/Math.max(layer.width,layer.height)),loadImage:this.o.loadImage});}
                    catch(error){this.o.onError?.(error);}
                }
            }
            const ink=this.root.querySelector('.layer-ink-preview');ink.style.zIndex=doc.layers.length+2;
            await D.paint({...doc,layers:[]},ink,{scale:Math.min(1,1200/Math.max(doc.width,doc.height))});this.layout();if(this.s.mask)this.paintMask();
        }
        notify(){this.o.onChange();}
        bind(){
            const root=this.root;let drag;
            root.onpointerdown=event=>{
                if(this.o.canInteract?!this.o.canInteract():this.o.canEdit&&!this.o.canEdit())return;
                if(event.button!==0 || event.altKey || event.ctrlKey || event.metaKey || event.target.closest('input,textarea'))return;
                this.o.onGestureStart?.();
                const p=this.point(event),s=this.s,edge=event.target.closest('[data-board-edge]')?.dataset.boardEdge;
                event.preventDefault();event.stopPropagation();this.o.onSelect?.();
                if(s.mask?.busy && s.tool==='mask')return;
                if(s.tool==='mask' && s.mask){this.maskDown(p);drag={kind:'mask'};}
                else if(s.tool==='crop' && s.crop){
                    const layer=s.layer(),q=local(layer,p);drag={kind:'crop',start:q,initial:{...s.crop},edge:event.target.closest('[data-crop-edge]')?.dataset.cropEdge};
                }else if(edge){s.remember();drag={kind:'board',start:p,doc:D.clone(s.doc),edge};this.o.onBoardStart?.();}
                else if(event.target.closest('[data-corner]')){
                    const layer=s.layer();if(!layer || layer.locked)return;s.remember();drag={kind:'resize',layer,initial:D.clone(layer),start:p,edge:event.target.closest('[data-corner]').dataset.corner};
                }else if(s.tool==='text'){
                    s.remember();const layer=D.addText(s.doc,'');Object.assign(layer,{x:p.x,y:p.y,color:s.textColor||'#ff3355',fontSize:24*this.s.doc.width/root.clientWidth,fontWeight:600,lineHeight:1.25,fontFamily:'sans-serif'});s.selected=layer.id;s.tool='select';this.paint();this.editText(layer,true);return;
                }else if(s.tool==='pen' || s.tool==='arrow'){
                    s.remember();const stroke={kind:s.tool,color:s.penColor,width:Number(s.penWidth),points:[p]};(s.doc.annotations ||= []).push(stroke);drag={kind:'draw',stroke};
                }else if(s.tool==='eraser'){
                    s.remember();s.doc.annotations=(s.doc.annotations || []).filter(stroke=>!stroke.points.some(q=>Math.hypot(q.x-p.x,q.y-p.y)<Number(s.penWidth)*3));this.notify();return;
                }else{
                    const layer=this.hit(p);
                    s.selected=layer?.id || '';if(!layer || layer.locked){this.layout();this.o.onSelection?.();return;}
                    s.remember();drag={kind:'move',layer,start:p,x:layer.x,y:layer.y};
                }
                drag.clientStart={x:event.clientX,y:event.clientY};
                root.setPointerCapture(event.pointerId);this.layout();this.o.onSelection?.();
            };
            root.onpointermove=event=>{
                if(!drag)return;
                if(!drag.moved&&Math.hypot(event.clientX-drag.clientStart.x,event.clientY-drag.clientStart.y)<3)return;
                const p=this.point(event),s=this.s;drag.moved=true;
                if(drag.kind==='move'){drag.layer.x=drag.x+p.x-drag.start.x;drag.layer.y=drag.y+p.y-drag.start.y;this.layout();}
                if(drag.kind==='resize'){D.resize(drag.layer,drag.initial,drag.edge,p.x-drag.start.x,p.y-drag.start.y,!event.altKey);this.paint();}
                if(drag.kind==='board'){
                    // Use the initial screen rectangle so resizing never feeds back into pointer coordinates.
                    const r=drag.screen,scale=r.width/drag.doc.width,x=(event.clientX-drag.clientX)/scale,y=(event.clientY-drag.clientY)/scale;
                    const left=drag.edge.includes('w')?Math.min(drag.doc.width-32,x):0,top=drag.edge.includes('n')?Math.min(drag.doc.height-32,y):0;
                    const width=drag.edge.includes('e')?Math.max(32,drag.doc.width+x):drag.doc.width-left,height=drag.edge.includes('s')?Math.max(32,drag.doc.height+y):drag.doc.height-top;
                    s.doc.width=Math.round(width);s.doc.height=Math.round(height);
                    s.doc.layers.forEach((layer,index)=>{layer.x=drag.doc.layers[index].x-left;layer.y=drag.doc.layers[index].y-top;});
                    s.doc.annotations=(drag.doc.annotations || []).map(stroke=>({...stroke,points:stroke.points.map(q=>({x:q.x-left,y:q.y-top}))}));
                    this.o.onBoardResize?.({left,top,width:s.doc.width,height:s.doc.height},drag.doc);this.layout();
                }
                if(drag.kind==='draw'){if(drag.stroke.kind==='arrow')drag.stroke.points=[drag.stroke.points[0],p];else drag.stroke.points.push(p);this.paint();}
                if(drag.kind==='crop'){
                    const q=local(s.layer(),p),r={...drag.initial},layer=s.layer(),dx=q.x-drag.start.x,dy=q.y-drag.start.y;
                    if(!drag.edge){r.x=Math.max(0,Math.min(layer.width-r.width,r.x+dx));r.y=Math.max(0,Math.min(layer.height-r.height,r.y+dy));}
                    else{
                        if(drag.edge.includes('w')){r.x=Math.max(0,Math.min(r.x+r.width-5,r.x+dx));r.width=drag.initial.x+drag.initial.width-r.x;}
                        if(drag.edge.includes('n')){r.y=Math.max(0,Math.min(r.y+r.height-5,r.y+dy));r.height=drag.initial.y+drag.initial.height-r.y;}
                        if(drag.edge.includes('e'))r.width=Math.max(5,Math.min(layer.width-r.x,r.width+dx));
                        if(drag.edge.includes('s'))r.height=Math.max(5,Math.min(layer.height-r.y,r.height+dy));
                        if(r.ratio){if(drag.edge==='n'||drag.edge==='s')r.width=Math.min(layer.width-r.x,r.height*r.ratio);else r.height=Math.min(layer.height-r.y,r.width/r.ratio);}
                    }
                    s.crop=r;this.layout();
                }
                if(drag.kind==='mask')this.maskDraw(p);
            };
            root.addEventListener('pointerdown',event=>{if(drag?.kind==='board'){drag.screen=root.getBoundingClientRect();drag.clientX=event.clientX;drag.clientY=event.clientY;}});
            root.onpointerup=event=>{
                if(!drag)return;const gesture=drag;drag=null;this.maskLast=null;
                if(gesture.kind==='crop' || gesture.kind==='mask')return;
                if(!gesture.moved && ['move','resize','board'].includes(gesture.kind)){this.s.undo.pop();this.o.onSelection?.();return;}
                const p=this.point(event),doc=this.s.doc;
                if(gesture.kind==='move'&&this.o.onDropOutside&&(p.x<0||p.y<0||p.x>doc.width||p.y>doc.height)){
                    this.o.onDropOutside(gesture.layer).catch(error=>this.o.onError?.(error));return;
                }
                this.notify();
            };
            root.onpointercancel=()=>{
                if(!drag)return;const kind=drag.kind;drag=null;
                if(['move','resize','board','draw'].includes(kind)){this.s.history(-1);this.paint();this.o.onMode?.();}
            };
            root.ondblclick=event=>{if(event.target.closest('input,textarea'))return;const layer=this.hit(this.point(event));if(layer?.kind==='text'){event.preventDefault();event.stopPropagation();this.s.selected=layer.id;this.editText(layer);}};
        }
        editText(layer,isNew=false){
            this.textInput ||= new CanvasLayerAnnotations.TextInput();
            this.textInput.commit('blur');
            if(!isNew)this.s.remember();
            const original=D.clone(layer),doc=this.s.doc;this.editingText=layer.id;this.layout();
            const update=(text,box)=>{layer.text=text;layer.width=box.width*doc.width;layer.height=box.height*doc.height;this.paint();};
            this.textInput.open(this.root,{text:layer.text,x:layer.x/doc.width,y:layer.y/doc.height,fontSize:layer.fontSize/doc.width,color:layer.color,fontFamily:layer.fontFamily,fontWeight:layer.fontWeight||(layer.bold?700:400),lineHeight:layer.lineHeight||1.2},
                {change:(text,box)=>{update(text,box);this.o.onDraft?.();},commit:(text,box,reason)=>{this.editingText='';if(text.trim())update(text,box);else this.s.doc.layers=this.s.doc.layers.filter(l=>l.id!==layer.id);if(reason==='blur'){this.paint();this.o.onDraft?.();this.o.onSelection?.();}else this.notify();},
                    cancel:()=>{this.editingText='';if(isNew)this.s.doc.layers=this.s.doc.layers.filter(l=>l.id!==layer.id);else Object.assign(layer,original);this.s.undo.pop();this.paint();this.o.onDraft?.();this.o.onMode?.();}});
        }
        async startMask(){
            const layer=this.s.layer();if(!layer || layer.kind!=='image')return;
            const canvas=document.createElement('canvas');await D.paint({width:layer.width,height:layer.height,layers:[{...layer,x:0,y:0,rotation:0,opacity:1,visible:true}]},canvas,{scale:Math.min(1,2048/Math.max(layer.width,layer.height)),loadImage:this.o.loadImage});
            const pixels=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height);
            this.s.mask={layerId:layer.id,width:canvas.width,height:canvas.height,data:pixels.data,keep:new Uint8Array(canvas.width*canvas.height).fill(255),source:canvas.toDataURL('image/png'),undo:[],redo:[]};this.s.maskMode='brush';this.s.tool='mask';this.s.maskError='';this.o.onMode?.();this.paintMask();this.layout();
            await this.autoSubject();
        }
        async autoSubject(){
            const s=this.s,m=s.mask;if(!m || m.busy)return;m.busy=true;s.maskError='';this.o.onMode?.();
            try{
                const url=await this.o.segmentImage(m.source),image=await this.o.loadImage(url);if(s.mask!==m)return;
                const canvas=document.createElement('canvas');canvas.width=m.width;canvas.height=m.height;canvas.getContext('2d').drawImage(image,0,0,m.width,m.height);
                const data=canvas.getContext('2d').getImageData(0,0,m.width,m.height).data;m.undo.push(m.keep.slice());m.redo=[];m.keep=Uint8Array.from({length:m.width*m.height},(_,i)=>data[i*4]);
            }catch(error){if(s.mask===m)s.maskError=error.message;}
            finally{m.busy=false;if(s.mask===m){this.paintMask();this.layout();this.o.onMode?.();}}
        }
        paintMask(){
            const m=this.s.mask;if(!m)return;const canvas=this.root.querySelector('.layer-mask-preview');canvas.width=m.width;canvas.height=m.height;
            const data=new Uint8ClampedArray(m.width*m.height*4);for(let i=0;i<m.keep.length;i++){data[i*4]=147;data[i*4+1]=91;data[i*4+2]=227;data[i*4+3]=Math.round(m.keep[i]*.55);}
            canvas.getContext('2d').putImageData(new ImageData(data,m.width,m.height),0,0);
        }
        maskDown(p){const m=this.s.mask;m.undo.push(m.keep.slice());if(m.undo.length>12)m.undo.shift();m.redo=[];this.maskLast=null;this.maskDraw(p);}
        maskDraw(p){
            const layer=this.s.layer(),m=this.s.mask,q=local(layer,p),x=Math.round(q.x/layer.width*m.width),y=Math.round(q.y/layer.height*m.height);
            if(this.s.maskMode==='quick'){const found=B.region(m.data,m.width,m.height,x,y);for(let i=0;i<found.length;i++)if(found[i])m.keep[i]=255;}
            else{const r=Math.max(1,(this.s.maskSize || 24)/layer.width*m.width/2),value=this.s.maskMode==='erase'?0:255;
                const previous=this.maskLast || {x,y},steps=Math.max(1,Math.ceil(Math.hypot(x-previous.x,y-previous.y)/Math.max(1,r/2)));
                for(let step=1;step<=steps;step++){
                    const cx=previous.x+(x-previous.x)*step/steps,cy=previous.y+(y-previous.y)*step/steps;
                    for(let py=Math.max(0,Math.floor(cy-r));py<Math.min(m.height,cy+r);py++)for(let px=Math.max(0,Math.floor(cx-r));px<Math.min(m.width,cx+r);px++)if((px-cx)**2+(py-cy)**2<=r*r)m.keep[py*m.width+px]=value;
                }this.maskLast={x,y};
            }
            this.paintMask();
        }
        async action(action){
            const s=this.s;if(action.startsWith('ratio-')){const [a,b]=action.slice(6).split(':').map(Number);s.cropRatio(a/b);this.layout();this.o.onMode?.();return;}
            if(action==='mask-subject'){await this.autoSubject();return;}
            if(action==='apply-crop'){s.action(action);this.notify();return;}
            if(action==='cancel'){s.tool='select';s.crop=null;s.mask=null;this.layout();this.o.onMode?.();return;}
            if(!s.mask)return;const m=s.mask;
            if(['mask-brush','mask-erase','mask-quick'].includes(action))s.maskMode=action.slice(5);
            if(action==='mask-undo' || action==='mask-redo'){const source=action==='mask-undo'?m.undo:m.redo,target=action==='mask-undo'?m.redo:m.undo;if(source.length){target.push(m.keep);m.keep=source.pop();}}
            if(action==='mask-auto' || action==='mask-invert'){m.undo.push(m.keep.slice());m.redo=[];m.keep=action==='mask-auto'?B.foreground(m.data,m.width,m.height):m.keep.map(v=>255-v);}
            if(action==='apply-mask'){
                const canvas=document.createElement('canvas');canvas.width=m.width;canvas.height=m.height;canvas.getContext('2d').putImageData(new ImageData(B.apply(m.data,m.keep),m.width,m.height),0,0);
                await this.o.onMaskResult(s.layer(),canvas);s.mask=null;s.tool='select';this.notify();return;
            }
            this.paintMask();this.o.onMode?.();
        }
    }
    window.CanvasLayerSurface={html,toolHtml,Surface};
})();
