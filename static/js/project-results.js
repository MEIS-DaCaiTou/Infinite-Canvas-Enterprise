/* Results in the existing home. Reuse copies outputs, never requests generation. */
window.ProjectResults={attach({request,state,dialog,refresh}){
    const $=id=>document.getElementById(id),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const base='/enterprise/api/business/workspace/tasks', labels={queued:'排队中',running:'运行中',succeeded:'已完成',partial:'部分完成',failed:'失败',unknown:'待核对',unavailable:'回执暂不可读'};
    const switcher=document.createElement('div');switcher.className='cw-actions';switcher.innerHTML='<button class="cw-btn" id="cwCanvasesTab" aria-pressed="true">画布</button><button class="cw-btn" id="cwTasksTab" aria-pressed="false">任务与成果</button><button class="cw-btn" id="cwProjectSharing" hidden>共享与成员</button>';
    $('cwCount').before(switcher);
    const panel=document.createElement('section');panel.id='cwResults';panel.hidden=true;$('cwItems').after(panel);
    let active=false,epoch=0,cursor=null,rows=[],filterCanvas='',lastKey='',lastNavigation='';
    const hidden=['cwFolders','cwItems','cwSort','cwGroup','cwGrid','cwList','cwArchive','cwMove','cwArchiveSelected','cwBoard'];
    async function load(append=false){
        const token=++epoch,s=state(),q=new URLSearchParams({scope:s.scope});
        if(s.scope==='department')q.set('department_id',s.department);
        if(s.project)q.set('project_id',s.project);
        if(s.member)q.set('member_id',s.member);
        if(filterCanvas)q.set('canvas_id',filterCanvas);
        if(append&&cursor)q.set('before',cursor);
        panel.setAttribute('aria-busy','true');
        try{const result=await request(base+'?'+q);if(token!==epoch)return;rows=append?[...rows,...result.tasks]:result.tasks;cursor=result.next_cursor;draw();}
        catch(error){if(token===epoch)panel.innerHTML='<p class="cw-error">'+esc(error.message)+'</p>';}
        finally{if(token===epoch)panel.removeAttribute('aria-busy');}
    }
    function draw(){
        const q=state().query,visible=rows.filter(r=>!q||[r.model,r.owner_name,r.id].some(v=>String(v||'').toLowerCase().includes(q)));
        $('cwCount').textContent=visible.length+' 项任务'+(filterCanvas?' · 所选画布':'');
        panel.innerHTML=(filterCanvas?'<button class="cw-btn" data-all-results>查看当前范围全部任务</button>':'')+
            '<p class="cw-card-meta">任务保留原归属。完整提示词、参考图及参数可从共享画布查看；费用沿用角色权限，密钥不共享。</p>'+
            (visible.length?'<div class="cw-grid">'+visible.map(t=>`<article class="cw-card"><button class="cw-card-main" data-task="${esc(t.id)}"><h3>${esc(t.model||t.type||'生成任务')}</h3><p>${labels[t.status]||'待核对'} · ${t.output_count||0} 项成果</p><div class="cw-card-meta">${esc(t.owner_name)} · ${t.created_at?new Date(t.created_at*1000).toLocaleString():''}</div></button></article>`).join('')+'</div>':'<div class="cw-empty"><h2>暂无匹配任务</h2><p>此处显示当前范围内可查看的任务；历史任务不会自动改归项目。</p></div>')+
            (cursor?'<button class="cw-btn" data-more-results>加载更早任务</button>':'');
    }
    async function open(id){
        const data=await request(base+'/'+encodeURIComponent(id)),d=document.createElement('dialog');d.className='cw-dialog cw-shell cw-result-dialog';
        d.style.display='block';d.style.height='auto';
        d.innerHTML=`<h2>${esc(data.model||'任务成果')} · ${labels[data.status]||'待核对'}</h2><p>保存为自己的画布不会重新生成，也不改变原任务或费用。</p><div class="cw-result-grid"></div><p role="status"></p><div class="cw-dialog-actions">${data.source?.available?'<a class="cw-btn" data-source>打开来源画布</a>':''}<button class="cw-btn primary" data-reuse disabled>保存所选为我的画布</button><button class="cw-btn" data-close>关闭</button></div>`;
        const grid=d.querySelector('.cw-result-grid');
        for(const item of data.items||[]){
            const card=document.createElement('label');card.className='cw-result-item';
            const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.dataset.key=item.key;checkbox.disabled=!['image','video','audio','text'].includes(item.kind);card.append(checkbox);
            const name=document.createElement('span');name.textContent=item.name||'成果 '+(item.index+1);card.append(name);
            if(['image','video','audio'].includes(item.kind)){
                const media=document.createElement(item.kind==='image'?'img':item.kind);media.src=item.url;if(item.kind!=='image')media.controls=true;else media.alt=name.textContent;media.preload='metadata';card.append(media);
            }else if(item.kind==='text'){
                const text=document.createElement('pre');text.textContent='正在读取文本…';card.append(text);
                fetch(item.url,{cache:'no-store'}).then(async r=>{if(!r.ok)throw Error();text.textContent=await r.text();}).catch(()=>{text.textContent='文本暂不可读，请刷新后重试';});
            }else {const a=document.createElement('a');a.href=item.url;a.textContent='下载成果文件';card.append(a);}
            grid.append(card);
        }
        if(!data.items?.length)grid.textContent='当前还没有已归档的成果，可稍后刷新任务。';
        const reuse=d.querySelector('[data-reuse]'),notice=d.querySelector('[role=status]');
        d.onchange=()=>{reuse.disabled=!d.querySelector('input:checked');};
        d.querySelector('[data-close]').onclick=()=>d.close();d.addEventListener('close',()=>{d.querySelectorAll('video,audio').forEach(v=>v.pause());d.remove();});
        if(data.source?.available)d.querySelector('[data-source]').href=data.source.url;
        reuse.onclick=async()=>{
            reuse.disabled=true;notice.textContent='正在保存所选成果…';
            try{
                const keys=[...d.querySelectorAll('input:checked')].map(i=>i.dataset.key);
                const copied=await request(base+'/'+encodeURIComponent(id)+'/reuse','POST',{keys});
                const created=await request('/api/canvases','POST',{title:(data.model||'项目成果')+' · 成果副本',kind:'classic'});
                const canvas=created.canvas,nodes=copied.items.map((item,i)=>({id:'result-'+Date.now()+'-'+i,type:item.kind==='text'?'prompt':'image',x:(i%3)*380,y:Math.floor(i/3)*360,w:330,h:280,
                    ...(item.kind==='text'?{text:item.text}:{url:item.url,name:item.name||'项目成果',mediaKind:item.kind}),sourceTaskId:id,sourceResultId:item.result_id||item.url}));
                await request('/api/canvases/'+encodeURIComponent(canvas.id),'PUT',{title:canvas.title,icon:canvas.icon,nodes,connections:[],viewport:{x:0,y:0,scale:1},base_updated_at:canvas.updated_at,client_id:'project-results'});
                location.href='/static/canvas.html?'+new URLSearchParams({id:canvas.id});
            }catch(error){notice.textContent=error.message;reuse.disabled=false;}
        };
        document.body.append(d);d.showModal();
    }
    async function sharing(){
        const s=state(),p=s.projects.find(p=>p.id===s.project);if(!p?.can_manage)return;
        const path='/enterprise/api/business/projects/'+encodeURIComponent(p.id),members=await request(path+'/members');
        dialog('共享与项目成员',[{name:'visibility',label:'共享范围',value:p.visibility,options:[['private','私有'],['department_readonly','本部门只读'],['company_readonly','企业内部只读']]},
            {name:'member',label:'调整项目成员（可选）',options:[['','不调整成员'],...members.map(m=>[m.id,m.display_name+(m.can_write?' · 可创作':'')])]},
            {name:'can_write',label:'所选成员权限',options:[['false','只读'],['true','可参与创作']]}],async v=>{
                await request(path+'/visibility','PUT',{visibility:v.visibility});
                if(v.member)await request(path+'/members/'+encodeURIComponent(v.member),'PUT',{can_write:v.can_write==='true'});
            },'共享完整画布、提示词、参考图和生成成果；密钥不共享，费用继续按角色查看。只读查看不授予修改原画布或执行生成的权限。');
    }
    $('cwCanvasesTab').onclick=()=>select(false);$('cwTasksTab').onclick=()=>{filterCanvas='';select(true);};$('cwProjectSharing').onclick=sharing;
    panel.onclick=e=>{const t=e.target.closest('[data-task]');if(t)open(t.dataset.task).catch(e=>{$('cwStatus').textContent=e.message;});if(e.target.closest('[data-more-results]'))load(true);if(e.target.closest('[data-all-results]')){filterCanvas='';load();}};
    function select(next){active=next;lastKey='';update();}
    function update(){
        panel.hidden=!active;hidden.forEach(id=>$(id).hidden=active||(['cwMove','cwArchiveSelected'].includes(id)&&!state().selected));
        $('cwCanvasesTab').setAttribute('aria-pressed',String(!active));$('cwTasksTab').setAttribute('aria-pressed',String(active));
        const s=state();$('cwProjectSharing').hidden=!s.projects.some(p=>p.id===s.project&&p.can_manage);
        $('cwBoard').hidden=active||s.scope!=='me';
        const navigation=JSON.stringify([s.scope,s.department,s.project,s.member]);
        if(lastNavigation&&navigation!==lastNavigation)filterCanvas='';lastNavigation=navigation;
        const key=JSON.stringify([s.scope,s.department,s.project,s.member,filterCanvas]);
        if(active){if(key!==lastKey){lastKey=key;load();}else draw();}else epoch++;
    }
    return {update,open,invalidate(){lastKey='';},canvas(id){filterCanvas=id;select(true);}};
}};
