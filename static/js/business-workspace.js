/* Authenticated metadata management; no balance inference or generation API. */
(function(){
    'use strict';
    const $=s=>document.querySelector(s),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const status=$('#businessStatus'),panel=$('#businessPanel'),scope=$('#businessScope'),department=$('#businessDepartment');
    const api='/enterprise/api/business';let context,tab=new URLSearchParams(location.search).get('tab')==='costs'?'costs':'projects',epoch=0,directory=[],costRows=[],costCursor=null;
    let requestedScope=new URLSearchParams(location.search).get('scope'),requestedDepartment=new URLSearchParams(location.search).get('department_id');
    const names={DEPARTMENT_PERMISSION_DENIED:'当前账号没有此操作权限',NO_AUTHORIZED_CALL_SOURCE:'尚未获授权使用调用来源',STALE_AUTHENTICATION:'登录已失效，请重新登录',INVALID_BUSINESS_REQUEST:'请检查填写内容',CREDENTIAL_VAULT_UNAVAILABLE:'当前运行身份无法使用凭据存储，请联系管理员',DEPARTMENT_SCHEMA_UPGRADE_REQUIRED:'请先完成支持部门项目的受控版本升级'};
    const visibility={private:'私有',department_readonly:'本部门只读',company_readonly:'企业内部只读'};
    const state={queued:'排队中',running:'运行中',succeeded:'已完成',failed:'失败',unknown:'待核对',partial:'部分完成',unavailable:'回执不可读'};
    async function json(path,method='GET',body){
        const r=await fetch(api+path,{method,cache:'no-store',...(body?{headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});
        const data=await r.json().catch(()=>({}));if(!r.ok){const code=data.detail?.code;throw new Error(names[code] || (r.status===401?'请重新登录后继续':'操作未完成，请检查权限与配置（'+(code || r.status)+'）'));}return data;
    }
    const query=()=>'?'+new URLSearchParams({scope:scope.value,...(scope.value==='department'?{department_id:department.value}:{})});
    const deptName=id=>context.departments.find(d=>d.id===id)?.name || (id?'原部门 '+id.slice(0,8):'未分配部门');
    const projectName=id=>context.projects.find(p=>p.id===id)?.name || (id?'原项目 '+id.slice(0,8):'个人创作');
    const personName=id=>directory.find(p=>p.id===id)?.display_name || (id===context.user_id?'本人':id);
    const unitName=unit=>unit==='platform_units'?'平台额度':unit;
    const date=t=>t?new Date(t*1000).toLocaleString():'未确认';
    const btn=(action,label,id='')=>`<button class="business-btn small" data-action="${action}" data-id="${esc(id)}">${label}</button>`;
    const empty=text=>`<div class="business-empty">${text}</div>`;
    const table=(headers,rows)=>`<div class="business-table-wrap"><table><thead><tr>${headers.map(x=>'<th>'+x+'</th>').join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
    const options=items=>items.map(([value,label])=>`<option value="${esc(value)}">${esc(label)}</option>`).join('');
    function dialog(title,fields,submit,help=''){
        const d=document.createElement('dialog');d.className='business-dialog';
        d.innerHTML=`<header><h2>${esc(title)}</h2></header><form>${fields.map(f=>`<label>${esc(f.label)}${f.options?`<select name="${f.name}" required>${options(f.options)}</select>`:`<input name="${f.name}" type="${f.type || 'text'}" ${f.required===false?'':'required'} maxlength="${f.type==='password'?8192:160}" autocomplete="${f.type==='password'?'new-password':'off'}">`}</label>`).join('')}${help?`<p class="business-help">${esc(help)}</p>`:''}<p class="business-form-error" role="status"></p><footer><button class="business-btn" type="button" data-cancel>取消</button><button class="business-btn primary" type="submit">保存</button></footer></form>`;
        fields.forEach(f=>{if(f.value!==undefined)d.querySelector(`[name=${f.name}]`).value=f.value;});
        d.querySelector('[data-cancel]').onclick=()=>d.close();d.addEventListener('close',()=>d.remove());
        d.querySelector('form').onsubmit=async e=>{e.preventDefault();const button=d.querySelector('[type=submit]');button.disabled=true;
            try{await submit(Object.fromEntries(new FormData(e.target)));d.close();await reload();}
            catch(error){d.querySelector('[role=status]').textContent=error.message;}
            finally{d.querySelectorAll('[type=password]').forEach(i=>i.value='');button.disabled=false;}
        };document.body.append(d);d.showModal();return d;
    }
    async function reload(){
        const token=++epoch;status.textContent='正在更新视图…';
        try{
            context=await json('/context');if(token!==epoch)return;
            if(!context.enabled){$('#businessContent').hidden=true;status.textContent='部门项目功能尚未启用；请等待正式版本升级，现有个人创作继续使用。';return;}
            const managed=context.departments.filter(d=>d.can_manage),oldScope=requestedScope||scope.value,oldDepartment=requestedDepartment||department.value;
            requestedScope=requestedDepartment=null;
            scope.innerHTML=options([['me','我的创作'],...(managed.length?[['department','本部门']]:[]),...(context.company_admin?[['company','全公司']]:[])]);
            if([...scope.options].some(o=>o.value===oldScope))scope.value=oldScope;
            department.innerHTML=options(managed.map(d=>[d.id,d.name]));if(managed.some(d=>d.id===oldDepartment))department.value=oldDepartment;
            scope.parentElement.hidden=!['costs','tasks'].includes(tab);$('#departmentFilter').hidden=scope.parentElement.hidden || scope.value!=='department';$('#businessContent').hidden=false;
            for(const name of ['sources','members'])$(`[data-tab=${name}]`).hidden=!managed.length && !context.company_admin;
            directory=managed.length || context.company_admin?await json('/directory'):[];if(token!==epoch)return;
            await draw(token);if(token===epoch)status.textContent='';
        }catch(error){if(token===epoch)status.textContent=error.message;}
    }
    async function draw(token){
        if(tab==='projects'){
            const projects=context.projects;
            panel.innerHTML=`<div class="business-card-head"><div><h2>部门项目</h2><p class="business-note">默认私有。只读共享不授予生成权限，也不公开密钥、费用或私人画布。</p></div>${context.department_id || context.company_admin?btn('new-project','新建部门项目'):''}</div>`+(projects.length?`<div class="business-grid">${projects.map(p=>`<article class="business-card"><div class="business-card-head"><h3>${esc(p.name)}</h3><span class="business-tag">${visibility[p.visibility]}</span></div><p class="muted">${esc(deptName(p.department_id))} · ${p.can_write?'可参与创作':'只读共享'}</p>${p.can_manage?`<div class="business-actions" style="margin-top:16px">${btn('share','共享范围',p.id)}${btn('project-member','成员权限',p.id)}</div>`:''}</article>`).join('')}</div>`:empty('还没有可查看的部门项目。个人创作无需先创建项目。'));
        }else if(tab==='costs'){
            const [summary,entries]=await Promise.all([json('/costs/summary'+query()),json('/costs'+query())]);if(token!==epoch)return;
            panel.innerHTML=`<div class="business-card-head"><div><h2>费用记录</h2><p class="business-note">实际与预估分开；供应商没有明确金额或单位时保留待核对，不同单位不相加。</p></div><span class="business-tag">待核对 ${summary.pending_reconciliation} 笔</span></div>`+
                (summary.groups.length?table(['业务归属','员工 / 模型','采购与支付账户','已知实际','预估'],summary.groups.map(g=>`<tr><td>${esc(deptName(g.department_id))}<small>${esc(projectName(g.project_id))}</small></td><td>${esc(personName(g.user_id))}<small>${esc(g.provider_id)} / ${esc(g.model)}</small></td><td>${g.procurement==='company'?'公司采购':'部门自购'} · ${g.scope==='company'?'公司共享':'部门专用'}<small>${esc(g.account_ref)}</small></td><td>${esc(g.actual)} ${esc(unitName(g.unit))}</td><td>${esc(g.estimated)} ${esc(unitName(g.unit))}</td></tr>`)):empty('暂无已核实的费用事实。没有费用记录不代表供应商一定未扣费。'))+
                '<section id="costEntries"></section>';
            costRows=entries.entries;costCursor=entries.next_cursor;drawCostEntries();
            if(scope.value==='department')await budgets(token);
        }else if(tab==='tasks'){
            const data=await json('/tasks'+query());if(token!==epoch)return;
            panel.innerHTML=`<h2>生成任务</h2><p class="business-note">按任务受理时的部门和项目归属显示元数据。本人完整结果与原任务续查仍在画布“日志 → 生成任务”。</p><br>`+(data.tasks.length?table(['状态','模型','业务归属','调用来源','受理时间'],data.tasks.map(t=>`<tr><td>${esc(state[t.status] || t.status)}</td><td>${esc(t.model)}<small>${esc(t.id)}</small></td><td>${esc(deptName(t.context.department_id))}<small>${esc(projectName(t.context.project_id))} / ${esc(personName(t.context.user_id))}</small></td><td>${esc(t.context.source_name)}</td><td>${esc(date(t.created_at))}</td></tr>`)):empty('暂无已持久受理的任务。旧版没有来源回执的记录不会补造归属。'))+(data.next_cursor?'<p class="business-note">显示最近 50 个记录；更早结果请从本人生成任务查询。</p>':'');
        }else if(tab==='sources'){
            const sources=await json('/sources?manage=true');if(token!==epoch)return;context.managed_sources=sources;
            panel.innerHTML=`<div class="business-card-head"><div><h2>调用来源</h2><p class="business-note">使用范围与采购来源分别维护。同一支付账户下的不同密钥，不代表独立余额。</p></div><div class="business-actions">${context.company_admin?btn('adopt-source','接纳现有共享密钥'):''}${btn('new-source','添加调用来源')}</div></div>`+(sources.length?`<div class="business-grid">${sources.map(s=>`<article class="business-card"><div class="business-card-head"><h3 class="business-source-name">${esc(s.name)}</h3><span class="business-tag">${s.enabled?'已启用':'已停用'}</span></div><p class="muted">${s.scope==='company'?'公司共享':esc(deptName(s.department_id))+'专用'} · ${s.procurement==='company'?'公司采购':'部门自购'}</p><p class="business-note">${esc(s.provider_id)} · 支付账户：${esc(s.account_ref)}</p><div class="business-actions" style="margin-top:16px">${btn('grant-source','使用权限',s.id)}${btn('rotate-source','更换密钥',s.id)}${btn('enable-source',s.enabled?'停用新任务':'启用',s.id)}</div></article>`).join('')}</div>`:empty('尚未配置来源。添加后必须明确授权员工使用；密钥原文不会返回页面。'));
        }else if(tab==='members'){
            const depts=context.departments.filter(d=>d.can_manage);
            panel.innerHTML=`<div class="business-card-head"><div><h2>部门成员</h2><p class="business-note">首版一人一部门。调部门与任命负责人由公司管理员操作。</p></div>${context.company_admin?btn('new-department','新建部门'):''}</div>`;
            for(const d of depts){const members=await json('/departments/'+d.id+'/members');if(token!==epoch)return;
                const section=document.createElement('section');section.className='business-card';section.innerHTML=`<div class="business-card-head"><h3>${esc(d.name)}</h3>${context.company_admin?btn('assign-member','分配成员',d.id):''}</div>`+(members.length?table(['成员','身份','操作'],members.map(m=>`<tr><td>${esc(m.display_name)}</td><td>${m.manager?'部门负责人':'部门成员'}</td><td>${context.company_admin || (!m.manager && m.user_id!==context.user_id)?btn('remove-member','移出部门',d.id+':'+m.user_id):''}</td></tr>`)):empty('暂无成员'));panel.append(section);
            }
        }
    }
    function drawCostEntries(){
        const target=$('#costEntries');if(!target)return;
        target.innerHTML=`<p class="business-note">已显示 ${costRows.length} 条费用事件；退款与修正保留独立记录。</p>`+
            (costRows.length?table(['记录时间','任务 / 归属','事件','金额'],costRows.map(e=>`<tr><td>${esc(date(e.created_at))}</td><td>${esc(e.task_id)}<small>${esc(personName(e.context.user_id))} · ${esc(projectName(e.context.project_id))}</small></td><td>${esc({charge:'实际扣费',refund:'退款',adjustment:'修正',estimate:'预估',unknown:'待核对'}[e.kind])}</td><td>${e.amount===null?'待核对':esc(e.amount)+' '+esc(unitName(e.unit))}</td></tr>`)):'')+
            (costCursor?btn('cost-more','加载更早记录'):'<p class="business-note">已显示全部费用事件</p>');
    }
    async function moreCosts(button){
        if(!costCursor||button.disabled)return;const token=epoch,cursor=costCursor;button.disabled=true;
        try{
            const data=await json('/costs'+query()+'&before='+encodeURIComponent(cursor));
            if(token!==epoch||tab!=='costs')return;
            costRows.push(...data.entries);costCursor=data.next_cursor;drawCostEntries();
        }finally{button.disabled=false;}
    }
    async function budgets(token){
        const id=department.value,data=await json('/departments/'+id+'/budgets');if(token!==epoch)return;
        const el=document.createElement('section');el.className='business-card';el.innerHTML=`<div class="business-card-head"><h3>部门预算提醒</h3>${btn('budget','设置提醒',id)}</div>`+(data.length?data.map(b=>`<div class="${b.exceeded?'business-warning':'business-note'}">${esc(b.period)}：预算 ${esc(b.amount)} ${esc(unitName(b.unit))} · 已知实际 ${esc(b.actual)} ${esc(unitName(b.unit))} · 待核对 ${b.pending_reconciliation} 笔${b.exceeded?' · 超出 '+esc(b.over_amount)+' '+esc(unitName(b.unit))+'，生成继续可用':''}</div>`).join(''):'<p class="muted">尚未设置预算提醒。预算不会阻断生产。</p>');panel.append(el);
    }
    panel.addEventListener('click',async e=>{
        const b=e.target.closest('[data-action]');if(!b)return;const id=b.dataset.id,action=b.dataset.action;
        const managed=context.departments.filter(d=>d.can_manage),memberOptions=directory.map(m=>[m.id,m.display_name]);
        const fields=(...rows)=>rows.map(([name,label,extra={}])=>({name,label,...extra}));
        try{
            if(action==='cost-more'){await moreCosts(b);return;}
            if(action==='new-department')dialog('新建部门',fields(['name','部门名称']),v=>json('/departments','POST',v));
            if(action==='assign-member')dialog('分配部门成员',fields(['user','成员',{options:memberOptions}],['manager','部门身份',{options:[['false','部门成员'],['true','部门负责人']]}]),v=>json('/departments/'+id+'/members/'+v.user,'PUT',{manager:v.manager==='true'}),'调部门会影响后续任务权限；历史费用与已受理任务保留原归属。');
            if(action==='remove-member')dialog('移出部门',[],()=>{const [dept,user]=id.split(':');return json('/departments/'+dept+'/members/'+user,'DELETE');},'移出后不再具备本部门专用来源权限；历史任务与归属不会被删除。');
            if(action==='new-project')dialog('新建部门项目',fields(['department_id','所属部门',{options:context.departments.map(d=>[d.id,d.name])}],['name','项目名称']),v=>json('/projects','POST',v),'新项目默认私有。个人创作不要求先创建部门项目。');
            if(action==='share')dialog('项目共享范围',fields(['visibility','共享范围',{options:Object.entries(visibility),value:context.projects.find(p=>p.id===id).visibility}]),v=>json('/projects/'+id+'/visibility','PUT',v),'共享项目关联的完整画布、提示词、参考图与成果；密钥不共享，费用按现有角色查看，未关联的私人内容保持私有。');
            if(action==='project-member'){const members=await json('/projects/'+id+'/members');dialog('项目成员权限',fields(['user','本部门成员',{options:members.map(m=>[m.id,m.display_name])}],['can_write','访问权限',{options:[['false','只读'],['true','可参与创作']]}]),v=>json('/projects/'+id+'/members/'+v.user,'PUT',{can_write:v.can_write==='true'}));}
            if(action==='adopt-source')dialog('接纳现有共享密钥',fields(['name','来源名称'],['provider_id','已配置的贞贞供应商 ID'],['scope','使用范围',{options:[['company','公司共享'],...managed.map(d=>[d.id,d.name+'专用'])]}],['procurement','采购来源',{options:[['company','公司统一采购'],['department','部门自行采购']]}],['account_ref','支付账户标识（请勿填写密码或 Token）']),async v=>{
                const r=await fetch('/api/call-sources/adopt',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...v,scope:v.scope==='company'?'company':'department',department_id:v.scope==='company'?null:v.scope})});
                if(!r.ok)throw new Error('接纳未完成，请核对供应商配置、采购来源与权限');
            },'只在服务端读取现有密钥并加密保存，不向页面回显；不会自动授权员工。接纳后请配置来源使用权限，未获授权的调用会被拒绝。');
            if(action==='new-source')dialog('添加调用来源',fields(['name','来源名称'],['provider_id','平台统一供应商 ID（当前接线：贞贞）'],['scope','使用范围',{options:[...(context.company_admin?[['company','公司共享']]:[]),...managed.map(d=>[d.id,d.name+'专用'])]}],['procurement','采购来源',{options:[['company','公司统一采购'],['department','部门自行采购']]}],['account_ref','支付账户标识（请勿填写密码或 Token）'],['secret','API Key',{type:'password'}]),v=>json('/sources','POST',{...v,scope:v.scope==='company'?'company':'department',department_id:v.scope==='company'?null:v.scope}),'平台地址、协议及模型仍由统一配置管理。公司共享来源须选公司采购；来源创建后需要授权员工。');
            if(action==='rotate-source'){const source=context.managed_sources.find(s=>s.id===id);dialog('更换来源密钥',fields(['secret','新的 API Key',{type:'password'}]),v=>json('/sources/'+id+'/secret','PUT',{...v,expected_revision:source.current_revision}),'新密钥仅用于新任务；已受理任务继续使用原密钥版本查询。');}
            if(action==='enable-source'){const source=context.managed_sources.find(s=>s.id===id);dialog(source.enabled?'停用新任务':'启用调用来源',[],()=>json('/sources/'+id+'/enabled','PUT',{enabled:!source.enabled}),'不改变已受理任务的查询身份，也不会自动换用其他来源。');}
            if(action==='grant-source'){const source=context.managed_sources.find(s=>s.id===id),grants=await json('/sources/'+id+'/grants');dialog('来源使用权限',fields(['user','员工',{options:directory.filter(m=>source.scope==='company' || m.department_id===source.department_id).map(m=>[m.id,m.display_name])}],['allowed','使用权限',{options:[['true','允许用于新任务'],['false','撤销新任务权限']]}]),v=>json('/sources/'+id+'/grants/'+v.user,'PUT',{allowed:v.allowed==='true'}),'当前已授权：'+(grants.map(g=>g.display_name).join('、') || '无')+'。授权不会向员工显示密钥原文。');}
            if(action==='budget')dialog('部门预算提醒',fields(['period','提醒名称'],['start','开始日期',{type:'date'}],['end','结束日期（不含当天）',{type:'date'}],['unit','统计单位',{options:[['platform_units','平台额度'],['CNY','人民币'],['USD','美元']]}],['amount','预算额度']),v=>json('/departments/'+id+'/budgets','PUT',{period:v.period,starts_at:Date.parse(v.start+'T00:00:00')/1000,ends_at:Date.parse(v.end+'T00:00:00')/1000,unit:v.unit,amount:v.amount}),'超额只在负责人视图提醒，不阻断员工生成，不新增生产审批。');
        }catch(error){status.textContent=error.message;}
    });
    $('.business-tabs').onclick=e=>{const b=e.target.closest('[data-tab]');if(!b)return;tab=b.dataset.tab;document.querySelectorAll('[data-tab]').forEach(v=>v.classList.toggle('active',v===b));reload();};
    document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));
    scope.onchange=reload;department.onchange=reload;$('#businessRefresh').onclick=reload;reload();
})();
