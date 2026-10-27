/* Canvas presentation of owned original jobs. Vendor controls stay server-side. */
(function(root){
    'use strict';
    const terminal=task=>['succeeded','cancelled'].includes(task.status)||(task.status==='failed'&&!task.recovery_required);
    const en=()=>document.documentElement.lang?.startsWith('en');
    const text=(zh,english)=>en()?english:zh;
    const labels=()=>en()?{platform_queued:'Platform queue',queued:'Backend queue',running:'Running',preparing:'Preparing',reconnecting:'Reconnecting',retrieving:'Saving result',succeeded:'Completed',failed:'Failed',cancelled:'Cancelled',unknown:'Needs checking'}:
        {platform_queued:'平台等待',queued:'后端排队',running:'运行中',preparing:'准备中',reconnecting:'重新连接中',retrieving:'保存结果中',succeeded:'已完成',failed:'失败',cancelled:'已取消',unknown:'待核对'};
    function outputInfo(entry,record={},cancelling=false,error=''){
        if(!entry)return null;
        const run=entry.run || {},id=entry.canvasTaskId || run.canvasTaskId;
        if(entry.canvasTaskType!=='comfy'&&run.nodeType!=='comfy')return null;
        const status=entry.canvasTaskStatus || run.canvasTaskStatus || (entry.url?'succeeded':record.status==='failed'&&record.recovery_required?'unknown':record.status || 'queued');
        const phase=terminal({status})||status==='unknown'?status:record.phase || status;
        return {id,status,phase,cancelling:cancelling||(!terminal({status})&&Boolean(record.cancellation?.acknowledged)),
            canCancel:Boolean(id&&!terminal({status})&&phase!=='retrieving'&&record.can_cancel),
            workflow:record.workflow_json || run.taskLabel || '',prompt:run.prompt || '',refs:(run.refs || []).length,
            startedAt:entry.startedAt || run.taskStartedAt || record.created_at*1000,
            finishedAt:entry.finishedAt || run.taskFinishedAt,queue:record.queue,error:error || entry.error || record.error || ''};
    }
    function settle(entry,task){
        entry.canvasTaskStatus=task.status;entry.finishedAt=Date.now();entry.failed=false;
        entry.error=task.error || '';
        if(entry.run)Object.assign(entry.run,{canvasTaskId:task.id,canvasTaskStatus:task.status,taskFinishedAt:entry.finishedAt});
    }
    function create({onChange,onTerminal,hasPending,fetcher=fetch}){
        let canvasId='',epoch=0,timer;
        const tasks=new Map(),waiting=new Map(),sending=new Set(),errors=new Map();
        let usage=null,lastUsage=0;
        const bindings=new WeakMap();
        let overlay=null;
        async function json(url,options={}){
            const response=await fetcher(url,{cache:'no-store',...options});
            const data=await response.json();
            if(!response.ok)throw new Error(data.detail || text('任务暂不可读','Task temporarily unavailable'));
            return data;
        }
        const active=nodeId=>[...tasks.values()].filter(task=>task.source?.node_id===nodeId&&!terminal(task));
        function update(task){
            if(task.source?.canvas_id!==canvasId)return;
            const prior=tasks.get(task.id);
            tasks.set(task.id,task);
            if(terminal(task))errors.delete(task.id);
            if(JSON.stringify(prior)!==JSON.stringify(task))onChange(task.source.node_id,active(task.source.node_id).length>0);
            if(terminal(task)&&!waiting.has(task.id)&&hasPending(task.id))onTerminal(task);
            paintOutputs();
        }
        async function poll(token){
            refreshUsage();
            const current=[...tasks.values()].filter(task=>!waiting.has(task.id)&&(!terminal(task)||hasPending(task.id)));
            await Promise.all(current.map(async task=>{
                try{
                    const data=await json('/api/canvas-comfy-tasks/'+encodeURIComponent(task.id));
                    if(token===epoch)update(data);
                }catch(_){ /* A query outage is not evidence of generation failure. */ }
            }));
            if(token===epoch&&[...tasks.values()].some(task=>!terminal(task)))timer=setTimeout(()=>poll(token),3000);
        }
        async function load(id){
            const token=++epoch;clearTimeout(timer);canvasId=id;tasks.clear();errors.clear();
            closeOverlay();
            refreshUsage(true);
            try{
                const data=await json('/enterprise/api/me/comfy-tasks?canvas_id='+encodeURIComponent(id));
                if(token!==epoch)return;
                // Summary rows have no output bytes; terminal pending cards need one full receipt read.
                data.items.forEach(task=>tasks.set(task.id,task));
                new Set(data.items.map(task=>task.source?.node_id).filter(Boolean)).forEach(nodeId=>onChange(nodeId,active(nodeId).length>0));
                paintOutputs();
                await poll(token);
            }catch(_){ /* Existing generation receipts remain intact if the list is unavailable. */ }
        }
        function track(task,nodeId,pendingId){
            waiting.set(task.task_id,pendingId);
            update({id:task.task_id,status:task.status,phase:task.phase || 'preparing',can_cancel:Boolean(task.can_cancel),created_at:Date.now()/1000,source:{canvas_id:canvasId,node_id:nodeId}});
            refreshUsage(true);
            clearTimeout(timer);timer=setTimeout(()=>poll(epoch),1000);
        }
        async function cancel(id){
            if(sending.has(id))return;
            const task=tasks.get(id);if(!task||terminal(task))return;
            const token=epoch;sending.add(id);errors.delete(id);onChange(task.source.node_id,true);paintOutputs();
            try{
                const data=await json('/enterprise/api/me/comfy-tasks/'+encodeURIComponent(id)+'/cancel',{method:'POST'});
                if(token===epoch)update(data.task);
            }catch(error){if(token===epoch)errors.set(id,error.message);}
            finally{
                sending.delete(id);
                if(token===epoch){onChange(task.source.node_id,active(task.source.node_id).length>0);paintOutputs();clearTimeout(timer);timer=setTimeout(()=>poll(token),300);}
            }
        }
        function info(entry){
            const id=entry?.canvasTaskId || entry?.run?.canvasTaskId;
            return outputInfo(entry,tasks.get(id),sending.has(id),errors.get(id));
        }
        const stateLabel=value=>value.cancelling?text('取消中','Cancelling'):labels()[value.phase] || text('核对中','Checking');
        function paint(wrap){
            const entry=bindings.get(wrap)?.(),value=info(entry);if(!value)return;
            let badge=wrap.querySelector('.comfy-output-status');
            if(!badge){badge=document.createElement('span');badge.className='comfy-output-status';badge.setAttribute('role','status');wrap.append(badge);}
            badge.textContent=errors.has(value.id)?text('取消未确认','Cancellation unconfirmed'):stateLabel(value);
            badge.hidden=['cancelled','failed'].includes(entry.canvasTaskStatus);
            badge.dataset.state=value.status;
            wrap.setAttribute('aria-label',text('输出任务：','Output task: ')+stateLabel(value));
        }
        function paintOutputs(){
            document.querySelectorAll('[data-comfy-output-task]').forEach(paint);
            if(overlay){
                if(!overlay.wrap.isConnected)closeOverlay();
                else renderDetails(overlay.panel,info(overlay.getEntry()),overlay.kind);
            }
        }
        function closeOverlay(){
            if(overlay)root.StudioDropdowns.closePanel(overlay.panel);
        }
        function renderDetails(panel,value,kind){
            panel.replaceChildren();if(!value)return;
            const heading=document.createElement('div');heading.className='comfy-output-detail-title';
            heading.textContent=text('输出任务详情','Output task details');panel.append(heading);
            const fields=[[text('状态','Status'),stateLabel(value)],[text('工作流','Workflow'),value.workflow],
                [text('提交时间','Submitted'),value.startedAt?new Date(value.startedAt).toLocaleString():'—'],
                [text('任务 ID','Task ID'),value.id || (terminal(value)?text('未记录','Not recorded'):text('等待后端受理','Awaiting acceptance'))],
                [text('输入素材','Input media'),String(value.refs)]];
            if(value.queue){
                fields.push([text('本人任务','My tasks'),text(`${value.queue.running} 运行或核对 · ${value.queue.waiting} 等待`,`${value.queue.running} running/checking · ${value.queue.waiting} waiting`)]);
                if(value.queue.backend_available===false)fields.push([text('后端连接','Backend'),text('暂不可用，任务保留在平台等待','Unavailable; task remains in the platform queue')]);
            }
            fields.forEach(([name,content])=>{
                const row=document.createElement('div');row.className='comfy-output-detail-row';
                const label=document.createElement('span'),data=document.createElement('span');label.textContent=name;data.textContent=content || '—';
                row.append(label,data);panel.append(row);
            });
            if(value.prompt){const prompt=document.createElement('p');prompt.className='comfy-output-prompt';prompt.textContent=value.prompt.slice(0,260);panel.append(prompt);}
            if(value.error){const error=document.createElement('p');error.className='comfy-output-error';error.textContent=value.error;panel.append(error);}
            if(kind==='menu'){
                const button=document.createElement('button');button.type='button';button.setAttribute('role','menuitem');
                button.className='comfy-output-cancel';
                button.textContent=value.cancelling?text('等待取消确认','Awaiting cancellation'):
                    terminal(value)?text('任务已结束','Task ended'):text('取消该任务','Cancel this task');
                button.disabled=!value.canCancel || value.cancelling;
                button.onclick=async()=>{closeOverlay();await cancel(value.id);};panel.append(button);
            }
        }
        function openDetails(wrap,getEntry,kind){
            if(overlay?.kind==='menu'&&kind==='tooltip')return;
            closeOverlay();
            const value=info(getEntry());if(!value)return;
            const panel=document.createElement('div');panel.className='comfy-output-popover';panel.dataset.kind=kind;
            panel.setAttribute('role',kind==='menu'?'menu':'tooltip');
            panel.setAttribute('aria-label',text('输出任务详情','Output task details'));
            panel.onpointerdown=event=>event.stopPropagation();panel.onclick=event=>event.stopPropagation();
            panel.onkeydown=event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeOverlay();}};
            renderDetails(panel,value,kind);document.body.append(panel);
            overlay={panel,wrap,getEntry,kind};
            root.StudioDropdowns.openPanel(panel,wrap,()=>{if(overlay?.panel===panel)overlay=null;panel.remove();});
            if(kind==='menu')panel.querySelector('button')?.focus({preventScroll:true});
        }
        function bindOutput(wrap,getEntry){
            if(!info(getEntry()))return;
            bindings.set(wrap,getEntry);wrap.dataset.comfyOutputTask='';wrap.tabIndex=0;
            let hoverTimer;
            wrap.onmouseenter=()=>{hoverTimer=setTimeout(()=>openDetails(wrap,getEntry,'tooltip'),220);};
            wrap.onmouseleave=()=>{clearTimeout(hoverTimer);if(overlay?.wrap===wrap&&overlay.kind==='tooltip')closeOverlay();};
            wrap.onfocus=()=>openDetails(wrap,getEntry,'tooltip');
            wrap.onblur=()=>{if(overlay?.kind==='tooltip')closeOverlay();};
            wrap.oncontextmenu=event=>{clearTimeout(hoverTimer);event.preventDefault();event.stopPropagation();openDetails(wrap,getEntry,'menu');};
            wrap.onkeydown=event=>{
                if(event.key==='ContextMenu'||event.shiftKey&&event.key==='F10'){event.preventDefault();event.stopPropagation();openDetails(wrap,getEntry,'menu');}
                if(event.key==='Escape')closeOverlay();
            };
            paint(wrap);
        }
        function paintUsage(){
            document.querySelectorAll('[data-comfy-queue-usage]').forEach(node=>{
                node.textContent=usage?text(`本人 ${usage.running} 运行或核对 · ${usage.waiting} 等待 · 未结束上限 ${usage.limits.user_outstanding}`,`Mine: ${usage.running} running/checking · ${usage.waiting} waiting · limit ${usage.limits.user_outstanding}`):'';
            });
        }
        async function refreshUsage(force=false){
            if(!force&&Date.now()-lastUsage<3000)return;lastUsage=Date.now();
            try{usage=await json('/enterprise/api/me/comfy-queue');paintUsage();}catch(_){ /* Usage display does not replace server admission. */ }
        }
        return {load,track,bindOutput,active,cancel,record:update,paintUsage,get:id=>tasks.get(id),
            locallyWaiting:nodeId=>[...waiting.keys()].some(id=>tasks.get(id)?.source?.node_id===nodeId),
            releasePending:pendingId=>{for(const [id,scope] of waiting)if(scope===pendingId)waiting.delete(id);}};
    }
    root.CanvasComfyTasks={create,outputInfo,settle};
})(typeof window==='undefined'?globalThis:window);
