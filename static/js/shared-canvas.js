/* Shared canvases use the original editors, with read-only controls. */
window.CanvasSharedView={
    enabled:new URLSearchParams(location.search).get('readonly')==='1',
    readUrl(id){return this.enabled?'/enterprise/api/business/workspace/canvases/'+encodeURIComponent(id):'/api/canvases/'+encodeURIComponent(id);},
    install(){
        if(!this.enabled)return;
        document.body.classList.add('canvas-readonly');
        const link=document.createElement('link');link.rel='stylesheet';link.href='/static/css/shared-canvas.css?v=20261022.1';document.head.append(link);
        const bar=document.createElement('div');bar.className='panel canvas-share-bar';
        bar.innerHTML='<span>只读共享</span><button class="tool-btn" type="button">保存副本继续创作</button><span role="status"></span>';document.body.append(bar);
        const inputs=()=>document.querySelectorAll('.node input,.node textarea,.smart-node input,.smart-node textarea,.prompt-node input,.prompt-node textarea,.image-node input,.image-node textarea').forEach(el=>{el.readOnly=true;});
        const controls=()=>{inputs();document.querySelectorAll('.node select,.node button,.smart-node select,.smart-node button,.prompt-node select,.prompt-node button,.image-node select,.image-node button,.composer select,.composer button').forEach(el=>{el.disabled=true;});document.querySelectorAll('.composer input,.composer textarea').forEach(el=>{el.readOnly=true;});document.querySelectorAll('#world [contenteditable=true]').forEach(el=>{el.contentEditable='false';});};
        new MutationObserver(controls).observe(document.body,{childList:true,subtree:true});controls();
        const nodeTarget=e=>e.target.closest?.('.node,.smart-node,.prompt-node,.image-node,.composer');
        for(const type of ['mousedown','pointerdown'])document.addEventListener(type,e=>{const node=nodeTarget(e);if(node&&!e.target.closest('input,textarea,video,audio')){if(type==='mousedown'&&node.dataset.id)this.selectNode?.(node.dataset.id);e.stopImmediatePropagation();}},true);
        for(const type of ['dblclick','contextmenu'])document.addEventListener(type,e=>{if(nodeTarget(e)||e.target.closest('#world')){e.preventDefault();e.stopImmediatePropagation();}},true);
        document.addEventListener('click',e=>{const image=e.target.closest?.('img');if(!image||!nodeTarget(e))return;
            e.preventDefault();e.stopImmediatePropagation();const url=image.dataset.originalSrc||image.src;
            if(window.openOutputLightbox)openOutputLightbox(url,null);else if(window.openSmartLogLightbox)openSmartLogLightbox(url,image.dataset.previewKind||'image');
        },true);
        for(const type of ['paste','drop','beforeinput'])document.addEventListener(type,e=>{e.preventDefault();e.stopImmediatePropagation();},true);
        document.addEventListener('keydown',e=>{
            const typing=e.target.closest?.('input,textarea,[contenteditable=false]');
            if((e.ctrlKey||e.metaKey)&&['c','a','f'].includes(e.key.toLowerCase())&&typing)return;
            if(['Escape',' ','Control','Meta','Shift','Alt'].includes(e.key))return;
            e.stopImmediatePropagation();if(!typing)e.preventDefault();
        },true);
        bar.querySelector('button').onclick=async()=>{
            const button=bar.querySelector('button'),notice=bar.querySelector('[role=status]');button.disabled=true;
            const request=async(url,method='GET',body)=>{const r=await fetch(url,{method,headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined});if(!r.ok)throw Error('保存未完成，请核对共享权限及素材文件后重试');return r.json();};
            try{
                const id=new URLSearchParams(location.search).get('id'),source=(await request(this.readUrl(id)+'/reuse','POST',{})).canvas;
                const created=(await request('/api/canvases','POST',{title:(source.title||'共享画布')+' · 副本',kind:source.kind})).canvas;
                await request('/api/canvases/'+encodeURIComponent(created.id),'PUT',{...source,title:created.title,base_updated_at:created.updated_at,client_id:'shared-canvas-copy'});
                location.href='/static/'+(created.kind==='smart'?'smart-canvas.html':'canvas.html')+'?'+new URLSearchParams({id:created.id});
            }catch(e){notice.textContent=e.message;button.disabled=false;}
        };
    }
};
CanvasSharedView.install();
