/* Only new submissions read these selections. Original task queries use their receipt. */
(function(root){
    'use strict';
    let request;
    const context=()=>request ||= fetch('/enterprise/api/business/context',{cache:'no-store'}).then(async r=>{
        if(!r.ok)throw new Error('调用来源暂不可读，请刷新后再试');return r.json();
    });
    const selection=(value,provider)=>({
        ...(value?.callSources?.[provider]?{call_source_id:value.callSources[provider]}:{}),
        ...(value?.businessProjectId?{business_project_id:value.businessProjectId}:{})
    });
    function mount(parent,{getProvider,getValue,onChange}){
        const box=document.createElement('div');box.className='call-source-picker';box.hidden=true;
        const line=document.createElement('div');line.className='call-source-line';
        const source=document.createElement('select');source.className='select-lite';source.setAttribute('aria-label','调用来源');
        const project=document.createElement('select');project.className='select-lite';project.setAttribute('aria-label','部门项目');
        const caption=document.createElement('span');caption.textContent='调用来源';
        const note=document.createElement('span');note.className='call-source-note';note.setAttribute('role','status');
        line.append(caption,source);box.append(line,project,note);
        const anchor=parent.querySelector('.gen-btn');if(anchor)anchor.before(box);else parent.append(box);
        for(const event of ['mousedown','click','keydown'])box.addEventListener(event,e=>e.stopPropagation());
        const option=(select,value,text)=>{const o=document.createElement('option');o.value=value;o.textContent=text;select.append(o);};
        let data;
        function draw(){
            if(!data?.enabled)return;
            const provider=getProvider(),value=getValue(),chosen=value?.callSources?.[provider] || '';
            const sources=data.sources.filter(s=>s.provider_id===provider);
            box.hidden=!(data.configured_providers || []).includes(provider) && !chosen && !value?.businessProjectId;
            source.replaceChildren();option(source,'','自动选择（优先部门专用）');
            sources.forEach(s=>option(source,s.id,`${s.scope==='department'?'部门专用':'公司共享'} · ${s.name}`));
            if(chosen && !sources.some(s=>s.id===chosen))option(source,chosen,'原来源不可用 · 请重新选择');
            source.value=chosen;
            project.replaceChildren();option(project,'','个人创作 · 无部门项目');
            const projects=data.projects.filter(p=>p.can_write && p.department_id===data.department_id);
            projects.forEach(p=>option(project,p.id,p.name));
            if(value?.businessProjectId && !projects.some(p=>p.id===value.businessProjectId))option(project,value.businessProjectId,'原项目不可执行 · 请重新选择');
            project.value=value?.businessProjectId || '';
            const active=sources.find(s=>s.id===chosen) || (!chosen?sources[0]:null);
            note.textContent=active?`${active.procurement==='company'?'公司采购':'部门自购'} · 仅影响新任务`:'来源不可用；不会换用其他密钥';
        }
        source.onchange=()=>{const v=getValue();onChange({...v,callSources:{...v.callSources,[getProvider()]:source.value}});draw();};
        project.onchange=()=>{onChange({...getValue(),businessProjectId:project.value});draw();};
        box.refresh=draw;
        context().then(result=>{data=result;draw();}).catch(error=>{box.hidden=false;line.hidden=true;project.hidden=true;note.textContent=error.message;});
        return box;
    }
    root.CanvasCallSources={mount,selection,context};
})(window);
