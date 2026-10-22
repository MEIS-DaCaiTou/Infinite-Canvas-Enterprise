/* Existing canvas entry, now with scoped directory views. No generation calls. */
(() => {
    'use strict';
    const context = window.CanvasWorkspaceContext, base = '/enterprise/api/business';
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const options = rows => rows.map(([id,name]) => `<option value="${esc(id)}">${esc(name)}</option>`).join('');
    const $ = id => document.getElementById(id);
    const link = document.createElement('link'); link.rel='stylesheet';link.href='/static/css/canvas-workspace.css?v=20261022.1';document.head.append(link);
    let preferences={};try{preferences=JSON.parse(localStorage.getItem('canvas-workspace:'+context.user_id)||'{}');}catch{}
    const initialScope=new URLSearchParams(location.search).get('scope');
    let scope=['me','department','company'].includes(initialScope)?initialScope:preferences.scope||'me', department=preferences.department||context.department_id||context.departments[0]?.id||'';
    if(scope==='department'&&!department)scope='me';
    let folder='', data={folders:[],canvases:[],projects:[],members:[]}, selected=new Set(), epoch=0;
    let view=preferences.view==='list'?'list':'grid', query='', archived='active', grouping='none', member='';
    const collapsed=new Set(Array.isArray(preferences.collapsed)?preferences.collapsed:[]);
    const icons=()=>window.lucide?.createIcons();
    const save=()=>{try{localStorage.setItem('canvas-workspace:'+context.user_id,JSON.stringify({scope,department,view,collapsed:[...collapsed]}));}catch{}};
    document.getElementById('workspace').outerHTML=`<div class="cw-shell" id="canvasWorkspace">
      <aside class="cw-side"><nav class="cw-scopes" aria-label="内容范围"><button data-scope="me">个人</button><button data-scope="department">部门</button><button data-scope="company">企业</button></nav>
      <select id="cwDepartment" class="cw-department" aria-label="选择部门">${options(context.departments.map(d=>[d.id,d.name]))}</select>
      <div class="cw-side-head"><span>项目与文件夹</span><button class="cw-btn" id="cwNewProject" title="新建部门项目">＋</button></div>
      <nav id="cwTree" class="cw-tree" aria-label="项目目录"></nav>
      <div class="cw-side-footer"><a class="cw-btn" href="/enterprise/business">${context.company_admin||context.departments.some(d=>d.can_manage)?'成员、来源与费用':'任务与费用'}</a><a class="cw-btn" href="?layout=board&trash=1">回收站</a></div></aside>
      <main class="cw-main"><header class="cw-toolbar"><nav id="cwBreadcrumb" class="cw-breadcrumb" aria-label="当前位置"></nav>
      <div class="cw-controls"><input id="cwSearch" class="cw-search" type="search" placeholder="搜索画布或文件夹" aria-label="搜索画布或文件夹">
      <button class="cw-btn" id="cwRefresh" title="刷新">刷新</button><button class="cw-btn" id="cwNewFolder">新建文件夹</button><button class="cw-btn primary" id="cwNewCanvas">新建画布</button></div></header>
      <section class="cw-content"><div class="cw-summary"><span id="cwCount"></span><select id="cwMember" aria-label="按成员筛选"></select>
      <select id="cwArchive" aria-label="归档状态"><option value="active">进行中</option><option value="archived">已归档</option><option value="all">全部状态</option></select>
      <select id="cwSort" aria-label="排序"><option value="recent">最近更新</option><option value="name">名称</option></select>
      <select id="cwGroup" aria-label="分组"><option value="none">不分组</option><option value="project">按项目分组</option><option value="member">按成员分组</option></select>
      <div class="cw-actions"><button class="cw-btn" id="cwMove" hidden>移动所选</button><button class="cw-btn" id="cwArchiveSelected" hidden>归档所选</button>
      <button class="cw-btn" id="cwGrid">网格</button><button class="cw-btn" id="cwList">列表</button><a class="cw-btn" id="cwBoard" href="?layout=board">自由布局</a></div></div>
      <div id="cwFolders"></div><div id="cwItems"></div></section><p id="cwStatus" class="cw-status" role="status"></p></main></div>`;
    $('cwDepartment').value=department;
    async function request(path, method='GET', body){
        const response=await fetch(path,{method,headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined});
        const result=await response.json().catch(()=>({}));
        if(!response.ok){const code=result.detail?.code||result.code||result.detail;const messages={DEPARTMENT_PERMISSION_DENIED:'当前账号没有此操作权限',WORKSPACE_FOLDER_CYCLE:'上级目录不能是本目录或其子目录',WORKSPACE_PROJECT_PARENT_MISMATCH:'子目录沿用上级目录的部门项目，请选择相同项目',WORKSPACE_OWNER_DEPARTMENT_MISMATCH:'该目录所有者不属于所选项目的部门',CANVAS_WORKSPACE_UPGRADE_REQUIRED:'请先完成支持项目目录的版本升级'};throw new Error(messages[code]||(typeof code==='string'?code:'操作未完成，请刷新重试'));}
        return result;
    }
    const status=(text,error=false)=>{$('cwStatus').textContent=text;$('cwStatus').classList.toggle('cw-error',error);};
    const activeFolder=()=>data.folders.find(f=>f.id===folder);
    const businessId=()=>folder.startsWith('business:')?folder.slice(9):activeFolder()?.business_project_id||null;
    const projectName=id=>data.projects.find(p=>p.id===id)?.name||'个人目录';
    const date=value=>value?new Date(Number(value)).toLocaleDateString('zh-CN'):'';
    function canCreate(){if(scope==='me'&&!folder)return true;const current=activeFolder();if(current)return !current.archived&&current.owner_id===context.user_id&&(current.id.startsWith('default:')||current.can_manage);const id=businessId();return !!id&&data.projects.some(p=>p.id===id&&p.can_write&&p.department_id===context.department_id);}
    function remember(){save();document.querySelectorAll('[data-scope]').forEach(b=>{b.setAttribute('aria-pressed',String(b.dataset.scope===scope));if(b.dataset.scope==='department')b.disabled=!context.departments.length;});$('cwDepartment').hidden=scope!=='department';$('cwNewProject').hidden=scope!=='department'||!department;$('cwBoard').hidden=scope!=='me';}
    async function load(){
        const token=++epoch;status('正在读取目录…');remember();
        try{
            const params=new URLSearchParams({scope,...(scope==='department'?{department_id:department}:{}),...(member?{member_id:member}:{})});
            const next=await request(base+'/workspace?'+params);if(token!==epoch)return;data=next;selected.clear();
            if(folder&&!folder.startsWith('business:')&&!data.folders.some(f=>f.id===folder))folder='';
            if(folder.startsWith('business:')&&!data.projects.some(p=>p.id===folder.slice(9)))folder='';
            $('cwMember').hidden=!data.can_filter_members;
            $('cwMember').innerHTML=options([['','全部成员'],...data.members.map(m=>[m.id,m.display_name])]);$('cwMember').value=member;
            if(!data.can_filter_members)grouping=grouping==='member'?'none':grouping;
            $('cwGroup').querySelector('[value=member]').hidden=!data.can_filter_members;$('cwGroup').value=grouping;
            render();status('');
        }catch(error){if(token===epoch){data={folders:[],canvases:[],projects:[],members:[]};render();status(error.message,true);}}
    }
    const choose=id=>{folder=id;selected.clear();render();};
    function treeRow(id,name,depth=0,manage=false){const children=data.folders.some(f=>id.startsWith('business:')?!f.parent_id&&f.business_project_id===id.slice(9):f.parent_id===id);return `<div class="cw-tree-row ${folder===id?'active':''}" style="padding-left:${depth*13}px">${children?`<button class="cw-toggle" data-collapse="${esc(id)}" aria-label="折叠或展开 ${esc(name)}" aria-expanded="${!collapsed.has(id)}"><i data-lucide="${collapsed.has(id)?'chevron-right':'chevron-down'}" class="cw-icon"></i></button>`:''}<button class="cw-folder-open" data-folder="${esc(id)}"><i data-lucide="${id.startsWith('business:')?'folder-open':'folder'}" class="cw-icon"></i><span>${esc(name)}</span></button>${manage?`<button class="cw-folder-menu" data-manage="${esc(id)}" aria-label="管理 ${esc(name)}">···</button>`:''}</div>`;}
    function renderTree(){
        let html=treeRow('','全部画布');
        const visible=new Set(data.folders.map(f=>f.id));
        const include=f=>archived==='all'||(archived==='archived'?f.archived:!f.archived);
        const seen=new Set();
        function branch(parent,project,depth,hidden=false){let result='';for(const f of data.folders.filter(f=>f.parent_id===parent&&f.business_project_id===project).sort((a,b)=>a.name.localeCompare(b.name,'zh'))){if(seen.has(f.id))continue;seen.add(f.id);if(include(f)||data.folders.some(c=>c.parent_id===f.id)){if(!hidden)result+=treeRow(f.id,f.name,depth,f.can_manage);result+=branch(f.id,project,depth+1,hidden||collapsed.has(f.id));}}return result;}
        if(scope!=='me')for(const p of data.projects){html+=treeRow('business:'+p.id,p.name);html+=branch(null,p.id,1,collapsed.has('business:'+p.id));}
        if(scope!=='me'&&data.folders.some(f=>!seen.has(f.id)&&(!f.parent_id||!visible.has(f.parent_id))))html+='<div class="cw-project-heading">其他可见目录</div>';
        for(const f of data.folders.filter(f=>!f.parent_id||!visible.has(f.parent_id))){
            if(seen.has(f.id))continue;
            seen.add(f.id);if(!include(f)&&!data.folders.some(c=>c.parent_id===f.id))continue;
            html+=treeRow(f.id,(scope==='company'?f.owner_name+' · ':'')+f.name,0,f.can_manage);html+=branch(f.id,f.business_project_id,1,collapsed.has(f.id));
        }
        $('cwTree').innerHTML=html;
    }
    function crumbs(){
        const trail=[],seen=new Set();let f=activeFolder();while(f&&!seen.has(f.id)){seen.add(f.id);trail.unshift(f);f=data.folders.find(p=>p.id===f.parent_id);}
        const bp=businessId();$('cwBreadcrumb').innerHTML=`<button data-folder="">${scope==='me'?'个人创作':scope==='department'?(context.departments.find(d=>d.id===department)?.name||'部门项目'):'企业项目'}</button>`+(bp?`<span>／</span><button data-folder="business:${esc(bp)}">${esc(projectName(bp))}</button>`:'')+trail.map(f=>`<span>／</span><button data-folder="${esc(f.id)}">${esc(f.name)}</button>`).join('');
    }
    function render(){
        renderTree();crumbs();$('cwGrid').setAttribute('aria-pressed',String(view==='grid'));$('cwList').setAttribute('aria-pressed',String(view==='list'));
        $('cwNewCanvas').disabled=!canCreate();$('cwNewFolder').disabled=!canCreate()||!!activeFolder()?.id.startsWith('default:');
        $('cwNewCanvas').title=$('cwNewFolder').title=canCreate()?'':'请在本人可写目录或本人所属部门的项目中创建';
        $('cwBoard').href='?layout=board'+(activeFolder()&&!activeFolder().id.startsWith('default:')?'&project='+encodeURIComponent(folder):'');
        const bp=businessId();let items=data.canvases.filter(c=>(!folder||query||(folder.startsWith('business:')?c.business_project_id===bp:c.folder_id===folder))&&
            (archived==='all'||(archived==='archived'?c.archived:!c.archived))&&(!query||[c.title,c.owner_name,projectName(c.business_project_id)].some(v=>v.toLowerCase().includes(query))));
        items.sort($('cwSort').value==='name'?(a,b)=>a.title.localeCompare(b.title,'zh'):(a,b)=>Number(b.updated_at)-Number(a.updated_at));
        $('cwCount').textContent=items.length+' 张画布'+(selected.size?' · 已选 '+selected.size:'');
        $('cwMove').hidden=!selected.size;$('cwArchiveSelected').hidden=!selected.size;$('cwArchiveSelected').textContent=archived==='archived'?'恢复所选':'归档所选';
        const children=data.folders.filter(f=>(query?true:!folder?!f.parent_id:folder.startsWith('business:')?!f.parent_id&&f.business_project_id===bp:f.parent_id===folder)&&
            (archived==='all'||(archived==='archived'?f.archived:!f.archived))&&(!query||f.name.toLowerCase().includes(query)));
        $('cwFolders').innerHTML=children.map(f=>`<button class="cw-folder-card" data-folder="${esc(f.id)}"><i data-lucide="folder" class="cw-icon"></i> ${esc(f.name)}</button>`).join('');
        if(!items.length){$('cwItems').innerHTML=`<div class="cw-empty"><h2>${query?'没有匹配的画布':archived==='archived'?'暂无归档画布':'这里还没有画布'}</h2><p>${scope==='me'?'选择文件夹，或直接新建画布开始创作。':'只显示获授权项目中明确关联的画布目录。'}</p></div>`;icons();return;}
        const groups=new Map();for(const c of items){const name=grouping==='member'?c.owner_name:grouping==='project'?projectName(c.business_project_id):'';if(!groups.has(name))groups.set(name,[]);groups.get(name).push(c);}
        $('cwItems').innerHTML=[...groups].map(([name,rows])=>(name?`<h2 class="cw-group">${esc(name)}</h2>`:'')+(view==='grid'?`<div class="cw-grid">${rows.map(card).join('')}</div>`:`<table class="cw-list"><thead><tr><th></th><th>画布名称</th><th>成员</th><th>更新时间</th><th>操作</th></tr></thead><tbody>${rows.map(row).join('')}</tbody></table>`)).join('');
        icons();
    }
    function check(c){return c.can_edit?`<input class="cw-check" type="checkbox" data-select="${esc(c.id)}" aria-label="选择 ${esc(c.title)}" ${selected.has(c.id)?'checked':''}>`:'';}
    function card(c){return `<article class="cw-card">${check(c)}<div class="cw-cover">${c.thumbnail_url?`<img loading="lazy" src="${esc(c.thumbnail_url)}" alt="" onerror="this.remove()">`:(c.kind==='smart'?'✧':'▦')}</div><button class="cw-card-main" data-open="${esc(c.id)}"><h3>${esc(c.title)}</h3><div class="cw-card-meta">${c.kind==='smart'?'智能画布':'经典画布'} · ${c.node_count} 节点<br>${esc(c.owner_name)} · ${date(c.updated_at)}</div></button><div class="cw-card-foot"><span>${c.archived?'已归档':c.can_edit?'可编辑':'只读目录'}</span>${c.can_edit?`<button class="cw-folder-menu" data-item="${esc(c.id)}" aria-label="管理 ${esc(c.title)}">···</button>`:''}</div></article>`;}
    function row(c){return `<tr><td style="position:relative;width:32px">${check(c)}</td><td><button class="cw-open" data-open="${esc(c.id)}">${esc(c.title)}</button><div class="cw-card-meta">${c.kind==='smart'?'智能画布':'经典画布'}${c.archived?' · 已归档':''}</div></td><td>${esc(c.owner_name)}</td><td>${date(c.updated_at)}</td><td>${c.can_edit?`<button class="cw-folder-menu" data-item="${esc(c.id)}" aria-label="管理 ${esc(c.title)}">···</button>`:'只读目录'}</td></tr>`;}
    function dialog(title,fields,submit,note=''){
        const el=document.createElement('dialog');el.className='cw-dialog cw-shell';el.style.display='block';el.style.height='auto';
        el.innerHTML=`<form><h2>${esc(title)}</h2>${fields.map(f=>`<label>${esc(f.label)}${f.options?`<select name="${f.name}">${options(f.options)}</select>`:`<input name="${f.name}" value="${esc(f.value||'')}" maxlength="80" ${f.required?'required':''}>`}</label>`).join('')}${note?`<p>${esc(note)}</p>`:''}<p class="cw-error" role="alert"></p><div class="cw-dialog-actions"><button type="button" class="cw-btn" data-cancel>取消</button><button type="submit" class="cw-btn primary">确定</button></div></form>`;
        document.body.append(el);for(const f of fields)if(f.options&&f.value!==undefined)el.querySelector(`[name=${f.name}]`).value=f.value;
        el.querySelector('[data-cancel]').onclick=()=>el.close();el.onclose=()=>el.remove();
        el.querySelector('form').onsubmit=async e=>{e.preventDefault();const button=el.querySelector('[type=submit]');button.disabled=true;try{await submit(Object.fromEntries(new FormData(e.target)));el.close();await load();}catch(error){el.querySelector('[role=alert]').textContent=error.message;button.disabled=false;}};
        el.showModal();el.querySelector('input,select,button')?.focus();
    }
    async function createFolder(name,parent_id,business_project_id){
        const response=await request('/api/projects','POST',{name});const id=response.project.id;
        try{await request(base+'/workspace/folders/'+encodeURIComponent(id),'PUT',{parent_id,business_project_id,archived:false});}
        catch(error){throw new Error('目录已创建在个人根目录，关联未完成：'+error.message);}
        return id;
    }
    function newFolder(){const parent=activeFolder();dialog('新建文件夹',[{name:'name',label:'文件夹名称',required:true}],async v=>{folder=await createFolder(v.name,parent?.id||null,businessId());});}
    function newCanvas(){dialog('新建画布',[{name:'title',label:'画布名称',required:true},{name:'kind',label:'画布类型',options:[['classic','经典画布'],['smart','智能画布']]}],async v=>{
        let target=activeFolder();if(!target||target.id.startsWith('default:')){
            if(businessId()){const existing=data.folders.find(f=>f.business_project_id===businessId()&&f.owner_id===context.user_id&&!f.parent_id&&!f.archived);const id=existing?.id||await createFolder('我的画布',null,businessId());target={id};folder=id;}
        }
        await request('/api/canvases','POST',{...v,project:target&&!target.id.startsWith('default:')?target.id:'default'});
    });}
    function manageFolder(id){const f=data.folders.find(f=>f.id===id);const descendants=new Set([id]);let changed=true;while(changed){changed=false;for(const c of data.folders)if(descendants.has(c.parent_id)&&!descendants.has(c.id)){descendants.add(c.id);changed=true;}}
        dialog('整理文件夹',[{name:'name',label:'文件夹名称',value:f.name,required:true},{name:'parent',label:'上级目录',value:f.parent_id||'',options:[['','根目录'],...data.folders.filter(p=>p.can_manage&&p.owner_id===f.owner_id&&!descendants.has(p.id)).map(p=>[p.id,p.name])]},{name:'project',label:'部门项目归属',value:f.business_project_id||'',options:[['','个人目录'],...data.projects.filter(p=>p.can_write).map(p=>[p.id,p.name])]},{name:'archived',label:'归档状态',value:f.own_archived?'true':'false',options:[['false','进行中'],['true','归档目录及其内容']]}],async v=>{
            await request(base+'/workspace/folders/'+encodeURIComponent(id),'PUT',{parent_id:v.parent||null,business_project_id:v.project||null,archived:v.archived==='true'});
            if(v.name!==f.name)await request('/api/projects/'+encodeURIComponent(id),'POST',{name:v.name});
        },'加入部门项目会让该目录及子目录的画布目录信息按项目权限可见。原画布编辑权和已发生费用归属保持；完整成果共享预览另行接入。');
    }
    function move(ids){const owners=new Set(ids.map(id=>data.canvases.find(c=>c.id===id)?.owner_id));const targets=data.folders.filter(f=>owners.size===1&&owners.has(f.owner_id)&&!f.archived&&(f.can_manage||f.id==='default:'+context.user_id));if(!targets.length){status('请先选择同一成员的画布，并准备可编辑的目标文件夹。',true);return;}dialog('移动画布',[{name:'target',label:'目标文件夹',options:targets.map(f=>[f.id,(f.business_project_id?projectName(f.business_project_id)+' / ':'')+f.name])}],async v=>{
        const destination=data.folders.find(f=>f.id===v.target);if(!destination)throw new Error('请选择目标文件夹');
        for(const id of ids)await request('/api/canvases/'+encodeURIComponent(id)+'/meta','POST',{project:destination.id.startsWith('default:')?'default':destination.id});
        selected.clear();
    },'移动用于整理画布及其项目目录信息，不改变已发生任务的费用归属。');}
    function itemMenu(id){const c=data.canvases.find(c=>c.id===id);dialog('整理画布',[{name:'action',label:c.title,options:[['move','移动到文件夹'],['archive',c.own_archived?'恢复归档':'归档'],['rename','重命名']]},{name:'name',label:'新名称（重命名时使用）',value:c.title}],async v=>{
        if(v.action==='move'){setTimeout(()=>move([id]),0);return;}
        if(v.action==='archive')await request(base+'/workspace/archive','PUT',{canvas_ids:[id],archived:!c.own_archived});
        if(v.action==='rename')await request('/api/canvases/'+encodeURIComponent(id)+'/meta','POST',{title:v.name});
    },c.archived&&!c.own_archived?'此画布随上级文件夹归档，需要恢复上级文件夹才能重新出现在进行中列表。':'');}
    $('canvasWorkspace').onclick=e=>{const b=e.target.closest('[data-scope],[data-folder],[data-manage],[data-open],[data-item],[data-collapse]');if(!b)return;
        if(b.dataset.collapse){collapsed.has(b.dataset.collapse)?collapsed.delete(b.dataset.collapse):collapsed.add(b.dataset.collapse);save();render();}
        else if(b.dataset.scope){scope=b.dataset.scope;folder='';member='';load();}
        else if(b.hasAttribute('data-folder'))choose(b.dataset.folder);
        else if(b.dataset.manage)manageFolder(b.dataset.manage);
        else if(b.dataset.item)itemMenu(b.dataset.item);
        else if(b.dataset.open){const c=data.canvases.find(c=>c.id===b.dataset.open);if(!c.can_edit){status('当前仅共享画布目录信息，完整只读成果预览将在后续工作包接入。');return;}location.href='/static/'+(c.kind==='smart'?'smart-canvas.html':'canvas.html')+'?'+new URLSearchParams({id:c.id,project:c.project});}
    };
    $('canvasWorkspace').onchange=e=>{if(e.target.dataset.select){e.target.checked?selected.add(e.target.dataset.select):selected.delete(e.target.dataset.select);$('cwCount').textContent=data.canvases.filter(c=>selected.has(c.id)).length+' 张已选';$('cwMove').hidden=!selected.size;$('cwArchiveSelected').hidden=!selected.size;}};
    $('cwSearch').oninput=e=>{query=e.target.value.trim().toLowerCase();render();};$('cwSort').onchange=render;
    $('cwArchive').onchange=e=>{archived=e.target.value;selected.clear();render();};$('cwGroup').onchange=e=>{grouping=e.target.value;render();};
    $('cwDepartment').onchange=e=>{department=e.target.value;folder='';member='';load();};$('cwMember').onchange=e=>{member=e.target.value;folder='';load();};
    $('cwGrid').onclick=()=>{view='grid';save();render();};$('cwList').onclick=()=>{view='list';save();render();};
    $('cwRefresh').onclick=load;$('cwNewFolder').onclick=newFolder;$('cwNewCanvas').onclick=newCanvas;
    $('cwMove').onclick=()=>move([...selected]);$('cwArchiveSelected').onclick=()=>dialog(archived==='archived'?'恢复所选画布':'归档所选画布',[],()=>request(base+'/workspace/archive','PUT',{canvas_ids:[...selected],archived:archived!=='archived'}),'归档保留画布和结果，可在已归档列表恢复。');
    $('cwNewProject').onclick=()=>dialog('新建部门项目',[{name:'name',label:'项目名称',required:true}],async v=>{const result=await request(base+'/projects','POST',{department_id:department,name:v.name});folder='business:'+result.id;});
    load();
})();
