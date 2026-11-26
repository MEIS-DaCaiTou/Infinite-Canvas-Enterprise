/* Read-only picker over the existing permission-aware asset catalogue. */
(function(){
    const t=key=>StudioI18n.t('layers.'+key),esc=value=>String(value || '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    async function pick(){
        const model=new CanvasAssetShelf.ReferenceShelf((url,options)=>fetch(url,options)),dialog=document.createElement('dialog');dialog.className='layer-asset-picker';document.body.append(dialog);
        const selected=new Map();let folderId='',query='',timer,error='';
        const folders=()=>model.library?.categories?.filter(c=>(c.type || 'image')==='image') || [];
        async function load(append=false){const folder=folders().find(c=>c.id===folderId);if(folder)await model.loadItems({category:folder},query,append);render();}
        function render(){
            dialog.innerHTML=`<header><strong>${esc(t('fromLibrary'))}</strong><button data-picker="close" aria-label="${esc(t('close'))}">×</button></header><div class="layer-asset-filters"><select data-picker="library" aria-label="${esc(t('library'))}">${model.libraries.map(lib=>`<option value="${esc(lib.id)}" ${model.library?.id===lib.id?'selected':''}>${esc(lib.name)}</option>`).join('')}</select><select data-picker="folder" aria-label="${esc(t('folder'))}">${folders().map(c=>`<option value="${esc(c.id)}" ${folderId===c.id?'selected':''}>${esc(c.name)}</option>`).join('')}</select><input data-picker="search" aria-label="${esc(t('search'))}" placeholder="${esc(t('search'))}" value="${esc(query)}"></div>
                <div class="layer-asset-grid">${model.page.rows.filter(row=>CanvasAssetShelf.mediaKind(row)==='image').map(row=>`<button class="${selected.has(row.url)?'selected':''}" data-asset="${esc(row.id)}"><img src="${esc(CanvasAssetShelf.previewUrl(row.url))}" alt=""><span>${esc(row.name)}</span></button>`).join('')}</div><div role="status">${esc(error || model.page.error || (!model.page.rows.length?t('noAssets'):''))}</div><footer>${model.page.cursor?`<button data-picker="more">${esc(t('more'))}</button>`:''}<button data-picker="cancel">${esc(t('cancel'))}</button><button data-picker="add" class="primary" ${!selected.size?'disabled':''}>${esc(t('addSelected'))} (${selected.size})</button></footer>`;
            dialog.querySelector('[data-picker=library]').onchange=async e=>{await model.selectLibrary(e.target.value,{catalog:true});folderId=folders()[0]?.id || '';await load();};
            dialog.querySelector('[data-picker=folder]').onchange=e=>{folderId=e.target.value;load();};
            dialog.querySelector('[data-picker=search]').oninput=e=>{query=e.target.value;clearTimeout(timer);timer=setTimeout(()=>load(),250);};
        }
        const result=new Promise(resolve=>{
            const finish=value=>{clearTimeout(timer);model.cancelItems();dialog.close();dialog.remove();resolve(value);};
            dialog.addEventListener('cancel',e=>{e.preventDefault();finish([]);});
            dialog.onclick=e=>{const asset=e.target.closest('[data-asset]');if(asset){const row=model.page.rows.find(r=>r.id===asset.dataset.asset);if(selected.has(row.url))selected.delete(row.url);else selected.set(row.url,row);render();return;}
                const action=e.target.closest('[data-picker]')?.dataset.picker;
                if(['close','cancel'].includes(action))finish([]);if(action==='add')finish([...selected.values()]);if(action==='more')load(true);
            };
        });
        dialog.showModal();render();
        try{await model.refresh({catalog:true});if(model.libraries.length){await model.selectLibrary(model.library?.id || model.libraries[0].id,{catalog:true});folderId=folders()[0]?.id || '';await load();}else render();}
        catch(e){error=e.message;render();}return result;
    }
    window.CanvasLayerAssets={pick};
})();
