/* Comfy scheduling settings; no generation or vendor control lives in this view. */
(function(root){
    'use strict';
    const en=()=>document.documentElement.lang.startsWith('en');
    const t=(zh,english)=>en()?english:zh;
    let policy=null,dirty=false,timer;
    const element=(tag,content,className)=>{const node=document.createElement(tag);if(content!==undefined)node.textContent=content;if(className)node.className=className;return node;};
    async function request(options){
        const response=await fetch('/enterprise/api/admin/comfy-queue',{cache:'no-store',...options});
        const value=await response.json();
        if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:t('队列配置暂不可读','Queue settings unavailable'));
        return value;
    }
    function input(value,label,change,type='number'){
        const node=element('input');node.type=type;node.value=value;node.setAttribute('aria-label',label);
        if(type==='number'){node.min=1;node.max=128;node.step=1;}
        node.oninput=()=>{dirty=true;change(type==='number'?Number(node.value):node.value);};
        return node;
    }
    function table(headings){
        const wrap=element('div',undefined,'table-scroll'),node=element('table'),head=element('thead'),row=element('tr'),body=element('tbody');
        headings.forEach(name=>row.append(element('th',name)));head.append(row);node.append(head,body);wrap.append(node);
        return {wrap,body};
    }
    function section(title,note){
        const node=element('section',undefined,'queue-section');node.append(element('h2',title));
        if(note)node.append(element('p',note,'queue-note'));return node;
    }
    function render(value){
        policy=value.policy;dirty=false;
        const host=document.getElementById('comfyQueueSettings');host.replaceChildren();
        const limits=section(t('用户限额','User limits'),t('所有画布和工作流共用个人限额。任务结束后恢复额度，不限制每日累计次数。','Limits apply across canvases and workflows. Slots return when work ends; there is no daily quota.'));
        const grid=element('div',undefined,'queue-limits');
        for(const [key,name] of [['user_running',t('每人同时运行','Running per user')],['user_outstanding',t('每人未结束总数','Unfinished per user')],['default_workflow_waiting',t('新工作流等待上限','New workflow waiting limit')]]){
            const label=element('label',name);label.append(input(policy[key],name,n=>policy[key]=n));grid.append(label);
        }limits.append(grid);host.append(limits);
        const resources=section(t('算力主机','Compute resources'),t('同一台主机的不同地址请填写相同分组名称和执行上限。当前任务不因调低限额而被取消。','Use the same group and capacity for addresses on one compute host. Lower limits do not cancel accepted work.'));
        const machines=table([t('后端地址','Backend'),t('算力分组','Compute group'),t('同时执行','Concurrent jobs')]);
        policy.backends.forEach(row=>{const tr=element('tr'),url=element('td',row.url);url.className='queue-address';
            const group=element('td'),capacity=element('td');group.append(input(row.resource,t('算力分组','Compute group'),n=>row.resource=n,'text'));
            capacity.append(input(row.capacity,t('主机同时执行上限','Host capacity'),n=>row.capacity=n));tr.append(url,group,capacity);machines.body.append(tr);});
        resources.append(machines.wrap);host.append(resources);
        const workflows=section(t('工作流队列','Workflow queues'),t('限制平台内等待数量。大型图片、视频等耗时工作流可设置较小上限，例如 3。','Limit platform waiting jobs. Long image or video workflows can use a smaller limit, such as 3.'));
        const flows=table([t('工作流','Workflow'),t('等待上限','Waiting limit')]);
        policy.workflows.forEach(row=>{const tr=element('tr'),cell=element('td');cell.append(input(row.waiting_limit,t('等待上限：','Waiting limit: ')+row.name,n=>row.waiting_limit=n));tr.append(element('td',row.name),cell);flows.body.append(tr);});
        workflows.append(flows.wrap);host.append(workflows);
        document.getElementById('comfyQueueSave').disabled=false;
        renderStatus(value.status);
    }
    function renderStatus(status){
        const host=document.getElementById('comfyQueueActivity');host.replaceChildren();
        host.append(element('p',t(`${status.running} 个执行或核对中 · ${status.waiting} 个平台等待 · ${status.outstanding} 个未结束`,`${status.running} running/checking · ${status.waiting} waiting · ${status.outstanding} unfinished`),'queue-note'));
        const states={platform_queued:t('平台等待','Platform queue'),preparing:t('准备中','Preparing'),running:t('运行中','Running'),queued:t('后端排队','Backend queue'),reconnecting:t('重新连接','Reconnecting'),retrieving:t('保存结果','Saving result'),unknown:t('待核对','Needs checking')};
        const jobs=table([t('成员','Member'),t('工作流','Workflow'),t('状态','Status'),t('提交时间','Submitted')]);
        status.items.forEach(row=>{const tr=element('tr');[row.user_name,row.workflow_json,states[row.phase] || row.phase,new Date(row.created_at*1000).toLocaleString()].forEach(text=>tr.append(element('td',text || '—')));jobs.body.append(tr);});
        if(!status.items.length){const row=element('tr'),cell=element('td',t('当前没有未结束任务','No unfinished tasks'));cell.colSpan=4;cell.className='queue-empty';row.append(cell);jobs.body.append(row);}
        host.append(jobs.wrap);
        for(const [group,health] of Object.entries(status.resources || {}))if(status.waiting&&!health.available)host.append(element('p',t(`${group}：后端连接暂不可用，任务保留在平台等待。`,`${group}: backend unavailable; tasks remain in the platform queue.`),'queue-note'));
    }
    function message(content,error=false){const node=document.getElementById('comfyQueueMessage');node.textContent=content;node.dataset.error=String(error);}
    async function load(){
        clearTimeout(timer);
        try{const value=await request();render(value);message('');}catch(error){message(error.message,true);}
        refreshLater();
    }
    function refreshLater(){timer=setTimeout(async()=>{
        if(!document.getElementById('tab-comfy-queue').classList.contains('active'))return;
        try{renderStatus((await request()).status);}catch(error){message(error.message,true);}
        refreshLater();
    },5000);}
    async function save(){
        if(!policy)return;
        const button=document.getElementById('comfyQueueSave');button.disabled=true;
        try{render(await request({method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(policy)}));message(t('队列设置已保存','Queue settings saved'));}
        catch(error){message(error.message,true);}finally{button.disabled=false;}
    }
    root.AdminComfyQueue={load,save,refresh:()=>{if(!dirty||confirm(t('刷新会放弃尚未保存的队列设置，继续？','Discard unsaved queue settings and refresh?')))load();}};
})(window);
