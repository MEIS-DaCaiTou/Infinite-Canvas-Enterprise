// Conflict recovery UI only. Server persistence remains the existing canvas API.
(function(root){
    const key = id => 'canvas-conflict-draft:' + id;
    function read(id){ try { return JSON.parse(sessionStorage.getItem(key(id)) || 'null'); } catch(e){ return null; } }
    function retain(id, draft){
        try { sessionStorage.setItem(key(id), JSON.stringify(draft)); return true; }
        catch(e){ return false; }
    }
    function clear(id){ try { sessionStorage.removeItem(key(id)); } catch(e){} }
    function download(draft){
        const url = URL.createObjectURL(new Blob([JSON.stringify(draft, null, 2)], {type:'application/json'}));
        const a = document.createElement('a'); a.href=url; a.download='canvas-local-draft.json'; a.click();
        setTimeout(()=>URL.revokeObjectURL(url), 1000);
    }
    function show({draft, retained, onRestore, onCopy, onReload}){
        document.getElementById('canvasConflictDialog')?.remove();
        const dialog=document.createElement('dialog'); dialog.id='canvasConflictDialog';
        dialog.style.cssText='width:min(480px,calc(100vw - 32px));padding:24px;border:1px solid #8892a1;border-radius:20px;background:var(--panel,#fff);color:var(--text,#172033);box-shadow:0 20px 80px #0004';
        const title=document.createElement('h2'); title.textContent='画布存在其他页面的修改';
        const info=document.createElement('p'); info.textContent=retained
            ? '已停止自动覆盖，本页草稿已保留在当前浏览器会话中。可另存副本，或读取远端版本。'
            : '已停止自动覆盖。浏览器存储空间不足，请先下载本页草稿后再离开。';
        const actions=document.createElement('div'); actions.style.cssText='display:flex;flex-wrap:wrap;gap:10px;margin-top:20px';
        const add=(label,action)=>{const b=document.createElement('button');b.type='button';b.textContent=label;
            b.style.cssText='padding:9px 14px;border:1px solid #8892a1;border-radius:12px;background:transparent;color:inherit;cursor:pointer';
            b.onclick=async()=>{b.disabled=true;try{await action();}catch(e){info.textContent=e.message || '操作未完成，草稿仍保留。';}finally{b.disabled=false;}};actions.append(b);};
        add('下载本页草稿',()=>download(draft()));
        add('另存为新画布',async()=>{await onCopy();dialog.close();dialog.remove();});
        add('读取远端版本',async()=>{await onReload();dialog.close();dialog.remove();});
        if(!retained) add('已下载草稿，读取远端版本',async()=>{
            await onReload(true);dialog.close();dialog.remove();
        });
        if(onRestore) add('恢复保留的本页草稿',async()=>{onRestore();dialog.close();dialog.remove();});
        add('继续查看本页',()=>{dialog.close();dialog.remove();});
        dialog.append(title,info,actions);document.body.append(dialog);dialog.showModal();
    }
    root.CanvasConflictDraft={read,retain,clear,download,show};
})(window);
