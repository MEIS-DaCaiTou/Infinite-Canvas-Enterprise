/* Personal durable receipts inside the existing canvas log panel. No generation endpoint. */
(function(root){
    'use strict';
    const esc=value=>String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const labels={queued:'排队中',running:'运行中',succeeded:'已完成',failed:'明确失败',unknown:'待核对',partial:'部分结果',unavailable:'记录不可读'};
    const attemptLabels={...labels,started:'已登记',submitting:'提交中',accepted:'已受理',generated:'待归档',querying:'核对中'};
    const label=value=>attemptLabels[value] || value;
    async function json(url,options={}){
        const response=await fetch(url,{cache:'no-store',...options});
        if(!response.ok){
            if(response.status===401)throw new Error('请通过企业入口登录后查看生成任务');
            const data=await response.json().catch(()=>({}));throw new Error(data.detail || '任务查询暂不可用，请稍后重试');
        }
        return response.json();
    }
    const date=value=>value?new Date(value*1000).toLocaleString():'未记录';
    function attach({modalId,listId,createPrompt,previewMedia}){
        const modal=document.getElementById(modalId),logs=document.getElementById(listId);
        if(!modal || !logs)return;
        const tabs=document.createElement('div');tabs.className='generation-task-tabs';tabs.setAttribute('role','tablist');
        tabs.innerHTML='<button type="button" role="tab" aria-selected="true" data-view="logs">生成日志</button><button type="button" role="tab" aria-selected="false" data-view="tasks">生成任务</button><span>仅显示本人任务</span>';
        const pane=document.createElement('div');pane.className='generation-task-pane';pane.hidden=true;
        pane.innerHTML='<div class="generation-task-filters"><select aria-label="任务状态"><option value="">全部状态</option>'+Object.entries(labels).map(([key,label])=>`<option value="${key}">${label}</option>`).join('')+'</select><select aria-label="任务类型"><option value="">全部类型</option><option value="canvas_image">API 图片</option><option value="canvas_comfy">ComfyUI</option></select><button type="button" data-refresh>刷新</button></div><div class="generation-task-status" role="status"></div><div class="generation-task-list"></div><button type="button" class="generation-task-more" hidden>查看更早任务</button>';
        logs.before(tabs);logs.after(pane);
        const list=pane.querySelector('.generation-task-list'),notice=pane.querySelector('[role=status]'),more=pane.querySelector('.generation-task-more');
        const filters=pane.querySelectorAll('select'),details=new Map();
        let rows=[],cursor=null,view='logs',epoch=0,timer=null,expanded='',loading=false,pending=false;
        function stop(){clearTimeout(timer);timer=null;}
        function schedule(){
            stop();
            if(view==='tasks' && modal.classList.contains('open') && rows.some(row=>['queued','running'].includes(row.status)))timer=setTimeout(()=>load(),5000);
        }
        function draw(){
            list.innerHTML=rows.length?rows.map(row=>`<article class="generation-task-row"><div class="generation-task-row-head"><div><span class="generation-task-badge" data-state="${esc(row.status)}">${esc(labels[row.status] || row.status)}</span><strong>${esc(row.workflow || row.model || row.provider || '生成任务')}</strong><p>${esc(date(row.created_at))} · ${esc(row.provider || row.type || '')} · ${Number(row.output_count || 0)} 个结果</p></div><button type="button" data-detail="${esc(row.id)}" ${row.status==='unavailable'?'disabled':''}>${expanded===row.id?'收起':'详情'}</button></div>${expanded===row.id?'<div class="generation-task-detail"></div>':''}</article>`).join(''):'<div class="log-empty">暂无匹配任务；此前没有持久回执的历史任务无法补录。</div>';
            list.querySelectorAll('[data-detail]').forEach(button=>button.onclick=async()=>{
                expanded=expanded===button.dataset.detail?'':button.dataset.detail;draw();if(expanded)await detail(expanded);
            });
            if(expanded && details.has(expanded))drawDetail(details.get(expanded));
            more.hidden=!cursor;
        }
        async function detail(id){
            const token=epoch;
            try{
                const data=await json('/enterprise/api/me/generation-tasks/'+encodeURIComponent(id));
                if(token!==epoch)return;details.set(id,data);if(expanded===id)drawDetail(data);
            }catch(error){if(token===epoch)notice.textContent=error.message;}
        }
        function drawDetail(data){
            const container=list.querySelector('.generation-task-detail');if(!container)return;
            const query=data.reconciliation;
            const attempts=(data.attempts || []).map(item=>{
                const usage=item.reported_usage || {};
                const counts=Object.entries(usage).filter(([key])=>!['reported_cost','currency'].includes(key));
                return `<div><span>子请求 ${item.index+1} · ${esc(label(item.status))}</span>
                    <small>${esc(item.provider || '')} · ${esc(item.model || '')}</small>
                    <code>${esc(item.upstream_task_id || '未取得供应商任务 ID')}</code>
                    ${item.error?`<small>${esc(item.error)}</small>`:''}
                    ${counts.length?`<small>供应商报告用量：${counts.map(([key,value])=>`${esc(key)} ${esc(value)}`).join(' · ')}</small>`:''}
                    ${usage.reported_cost!==undefined?`<small>供应商报告费用 ${esc(usage.reported_cost)} ${esc(usage.currency || '（币种未提供）')}，尚非平台结算</small>`:''}</div>`;
            }).join('');
            container.innerHTML=`<div class="generation-task-id">平台任务 ID：${esc(data.id)}</div>
                ${data.error?`<p class="generation-task-error">${esc(data.error)}</p>`:''}
                <div class="generation-task-attempts">${attempts}</div>
                <p class="generation-task-note">${esc(data.cost_note || '')}</p>
                ${query?`<p class="generation-task-note">最近核对：${esc(label(query.status))} · ${esc(date(query.finished_at || query.started_at))} · 共 ${query.count || 0} 次</p>`:''}
                <div class="generation-task-results"></div>
                ${data.can_query?'<button type="button" class="generation-task-query">继续查询原任务</button>':data.status==='unknown'?'<p class="generation-task-note">当前没有可安全续查的受理身份，请核对供应商记录；不会自动重新生成。</p>':''}`;
            const results=container.querySelector('.generation-task-results');
            for(const item of data.items || []){
                if(item.kind==='text'){
                    const button=document.createElement('button');button.type='button';button.className='generation-task-text';
                    button.innerHTML=ComfyOutputs.card(item);button.onclick=()=>ComfyOutputs.open(item,{createPrompt});results.append(button);
                }else{
                    const link=document.createElement('a');link.href=item.url;link.target='_blank';link.rel='noopener';link.className='generation-task-media';
                    if(item.kind==='image') {const image=document.createElement('img');image.src=item.url;image.alt=item.name || '生成结果';link.append(image);}
                    else link.textContent=item.name || item.kind || '查看结果';
                    if(previewMedia && ['image','video','audio'].includes(item.kind))link.onclick=event=>{event.preventDefault();previewMedia(item);};
                    results.append(link);
                }
            }
            const queryButton=container.querySelector('.generation-task-query');
            if(queryButton)queryButton.onclick=async()=>{
                const token=epoch;queryButton.disabled=true;notice.textContent='正在核对原任务，不会重新生成…';
                try{
                    const url=data.type==='comfy'?'/api/canvas-comfy-tasks/'+encodeURIComponent(data.id)+'?resume=true':'/api/canvas-image-tasks/'+encodeURIComponent(data.id)+'/reconcile';
                    await json(url,data.type==='comfy'?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
                    if(token===epoch){notice.textContent='已查询原任务';await load();}
                }catch(error){if(token===epoch){notice.textContent=error.message;queryButton.disabled=false;}}
            };
            root.lucide?.createIcons();
        }
        async function load(append=false){
            if(loading){pending=true;return;}
            loading=true;more.disabled=true;const token=epoch;stop();notice.textContent='读取任务记录…';
            const params=new URLSearchParams({status:filters[0].value,kind:filters[1].value,limit:'30'});
            if(append && cursor)params.set('cursor',cursor);
            try{
                const data=await json('/enterprise/api/me/generation-tasks?'+params);
                if(token!==epoch)return;
                rows=append?[...rows,...data.items]:data.items;cursor=data.next_cursor;
                notice.textContent=data.scan_limited?'已检索本批记录，可继续查看更早任务':'任务记录保存在服务器；查询不会重新生成';draw();
                if(expanded && rows.some(row=>row.id===expanded))await detail(expanded);
            }catch(error){if(token===epoch)notice.textContent=error.message;}
            finally{
                loading=false;more.disabled=false;
                if(pending){pending=false;if(view==='tasks' && modal.classList.contains('open'))load();}
                else if(token===epoch)schedule();
            }
        }
        function select(next){
            view=next;epoch++;stop();logs.hidden=next==='tasks';pane.hidden=next!=='tasks';
            modal.querySelector('.log-panel')?.classList.toggle('generation-task-active',next==='tasks');
            tabs.querySelectorAll('button').forEach(button=>button.setAttribute('aria-selected',String(button.dataset.view===next)));
            if(next==='tasks')load();
        }
        tabs.querySelectorAll('button').forEach(button=>button.onclick=()=>select(button.dataset.view));
        filters.forEach(filter=>filter.onchange=()=>{epoch++;expanded='';load();});
        pane.querySelector('[data-refresh]').onclick=()=>load();more.onclick=()=>load(true);
        new MutationObserver(()=>{if(!modal.classList.contains('open')){epoch++;stop();}else select('logs');}).observe(modal,{attributes:true,attributeFilter:['class']});
    }
    root.GenerationTaskCenter={attach};
})(window);
