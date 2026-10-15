/* Shared typed result display and prompt reuse. Existing canvas persistence owns these values. */
(function(root){
    'use strict';
    const escape = value=>String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const cache=new Map();
    const kindFor=url=>/\.(txt|md|csv|json|srt|vtt)(?:\?|$)/i.test(url)?'text':/\.(mp4|webm|mov)(?:\?|$)/i.test(url)?'video':/\.(mp3|wav|ogg|m4a)(?:\?|$)/i.test(url)?'audio':'image';
    function items(result){
        const raw=Array.isArray(result)?result:Array.isArray(result?.items)&&result.items.length?result.items:
            ['images','videos','audios','texts','files','outputs'].flatMap((key,i)=>(result?.[key]||[]).map(item=>typeof item==='string'?{url:item,kind:['image','video','audio','text','file'][i] || kindFor(item)}:item));
        const seen=new Set();
        return raw.map(item=>typeof item==='string'?{url:item,kind:kindFor(item)}:{...item}).filter(item=>{
            if(!item.url || seen.has(item.url))return false;
            seen.add(item.url); item.kind ||= kindFor(item.url); item.result_id ||= item.url;
            if(typeof item.text==='string')cache.set(item.url,item.text);
            return true;
        });
    }
    async function text(item){
        const url=new URL(item.url,root.location.href);
        if(url.origin!==root.location.origin || !['http:','https:'].includes(url.protocol))throw new Error('请使用平台已归档的文本结果');
        if(typeof item.text==='string')return item.text;
        if(cache.has(item.url))return cache.get(item.url);
        const response=await fetch(url.pathname+url.search,{credentials:'same-origin'});
        if(!response.ok)throw new Error('文本读取失败，请保留原任务并重试读取');
        const value=await response.text();cache.set(item.url,value);item.text=value;return value;
    }
    function selected(node, values){
        const outputs=items(values);
        return outputs.find(item=>item.result_id===node?.selectedResultId || item.url===node?.selectedResultId)
            || (node?.selectedResult?.result_id===node?.selectedResultId?node.selectedResult:null)
            || (!node?.selectedResultId && outputs.length===1?outputs[0]:null);
    }
    function prompt(node, values){
        const item=selected(node,values);
        if(item?.kind!=='text')return '';
        return item.text ?? cache.get(item.url) ?? '';
    }
    function validateSource(node,values){
        const outputs=items(values);
        if(!outputs.some(item=>item.kind==='text') && node?.selectedResult?.kind!=='text')return;
        const item=selected(node,outputs);
        if(!item)throw new Error('上游有多条结果，请打开所需文本并点击“选作下游输入”');
        if(item.kind==='text' && typeof item.text!=='string' && !cache.has(item.url))throw new Error('请先打开该文本结果并选作下游输入');
    }
    function card(item){
        const summary=(item.text ?? cache.get(item.url) ?? '点击查看正文').slice(0,180);
        const time=item.created_at ? new Date(item.created_at*1000).toLocaleString() : '';
        return `<div class="comfy-text-card"><div class="comfy-text-card-label"><i data-lucide="file-text"></i><span>TEXT</span></div><div class="comfy-text-card-body">${escape(summary)}</div><div class="comfy-text-card-name">${escape(time || item.name || '文本结果')}</div></div>`;
    }
    async function open(item, actions={}){
        const dialog=document.createElement('dialog');
        dialog.className='comfy-text-dialog';
        dialog.setAttribute('aria-label','文本结果');
        dialog.innerHTML='<div class="comfy-text-head"><div class="comfy-text-heading"><span class="comfy-text-heading-icon"><i data-lucide="file-text"></i></span><div><h3 class="comfy-text-title">文本结果</h3><div class="comfy-text-subtitle"></div></div></div><button class="comfy-text-close" type="button" aria-label="关闭"><i data-lucide="x"></i></button></div><div class="comfy-text-content"><textarea class="comfy-text-body" readonly rows="5" aria-label="文本正文"></textarea></div><div class="comfy-text-footer"><div class="comfy-text-actions" data-actions="utility"></div><div class="comfy-text-actions" data-actions="primary"></div></div><p class="comfy-text-status" role="status"></p>';
        dialog.querySelector('.comfy-text-subtitle').textContent=item.name || '本次工作流输出';
        dialog.querySelector('.comfy-text-close').onclick=()=>dialog.close();
        const status=dialog.querySelector('[role=status]');
        const button=(label,handler,icon,primary=false)=>{
            const el=document.createElement('button');el.type='button';el.className='comfy-text-btn'+(primary?' primary':'');
            el.innerHTML=`<i data-lucide="${icon}"></i><span>${escape(label)}</span>`;
            el.onclick=async()=>{try{await handler();}catch(error){status.textContent=error.message;}};
            dialog.querySelector(`[data-actions="${icon==='copy'||icon==='download'?'utility':'primary'}"]`).append(el);return el;
        };
        dialog.addEventListener('close',()=>dialog.remove());document.body.append(dialog);dialog.showModal();
        dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}});
        try{
            const value=await text(item);dialog.querySelector('textarea').value=value;
            dialog.querySelector('textarea').rows=Math.min(18,Math.max(5,value.split('\n').length));
            button('复制',async()=>{
                if(navigator.clipboard?.writeText)await navigator.clipboard.writeText(value);
                else {dialog.querySelector('textarea').select();if(!document.execCommand('copy'))throw new Error('请选中文字后复制');}
                status.textContent='已复制';
            },'copy');
            button('下载',()=>{const a=document.createElement('a');a.href=item.url;a.download=item.name||'prompt.txt';document.body.append(a);a.click();a.remove();},'download');
            if(actions.select)button('选作下游输入',async()=>{await actions.select({...item,text:value});status.textContent='已选中此结果';},'check');
            if(actions.createPrompt)button(actions.promptLabel || '生成提示词节点',async()=>{await actions.createPrompt(value,item);dialog.close();},'text-cursor-input',true);
            root.lucide?.createIcons();
        }catch(error){status.textContent=error.message;}
        return dialog;
    }
    root.ComfyOutputs={items,text,selected,prompt,card,open,validateSource};
})(typeof window==='undefined'?globalThis:window);
