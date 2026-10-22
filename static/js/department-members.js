/* Department settings inside the existing member administration. */
window.DepartmentMembers={
    data:null,
    async initialize(actor){
        const context=await apiFetch('/enterprise/api/business/context');
        if(!context.enabled)return;
        this.data=await apiFetch('/enterprise/api/business/member-workspace');
        this.departmentOnly=!this.data.company_admin;
        if(this.departmentOnly){
            document.querySelectorAll('.tab-btn').forEach((b,i)=>{b.hidden=i>0;});
            document.getElementById('primaryActionBtn').hidden=true;
            document.querySelector('[href="/enterprise/logs"]').hidden=true;
            document.querySelector('.page-head .sub')?.replaceChildren(document.createTextNode('本部门成员；账号创建、调部门和负责人任命由公司管理员设置'));
        }
        const field=document.createElement('label');field.className='member-filter-field';
        field.innerHTML='<span class="label">部门</span><div class="field-frame"><select id="memberDepartmentFilter"><option value="">全部部门</option><option value="none">未分配部门</option>'+this.data.departments.map(d=>`<option value="${escapeHtml(d.id)}">${escapeHtml(d.name)}</option>`).join('')+'</select></div>';
        document.querySelector('.member-filter-grid').append(field);field.querySelector('select').onchange=applyMemberFilters;
        if(this.data.company_admin){const b=document.createElement('button');b.className='row-btn';b.textContent='新建部门';b.onclick=()=>this.createDepartment();field.append(b);}
        const th=document.createElement('th');th.textContent='部门 / 职责';document.querySelector('#tab-users thead tr').children[2].before(th);document.querySelector('.user-table').classList.add('department-enabled');
        document.getElementById('userTable').addEventListener('click',e=>{const b=e.target.closest('[data-department-user]');if(b)this.edit(b.dataset.departmentUser);});
    },
    async members(){this.data=await apiFetch('/enterprise/api/business/member-workspace');return this.data.members;},
    match(user){const value=document.getElementById('memberDepartmentFilter')?.value;const m=this.data?.members.find(m=>m.id===user.id);return !value||(value==='none'?!m?.department_id:m?.department_id===value);},
    cell(user){if(!this.data)return '';const member=this.data.members.find(m=>m.id===user.id),dept=this.data.departments.find(d=>d.id===member?.department_id);
        return '<td><span>'+escapeHtml(dept?.name||'未分配部门')+(member?.manager?' · 负责人':'')+'</span> '+
            (this.data.company_admin?`<button class="row-btn" data-department-user="${escapeHtml(user.id)}">设置部门</button>`:
                member&&!member.manager?`<button class="row-btn" data-department-user="${escapeHtml(user.id)}">移出部门</button>`:'')+'</td>';},
    form(title,body,submit){
        const bg=document.createElement('div');bg.className='modal-backdrop show';bg.setAttribute('role','dialog');bg.setAttribute('aria-modal','true');
        bg.innerHTML=`<form class="modal"><h3>${title}</h3>${body}<p role="status"></p><div class="modal-actions"><button type="button" class="action-btn" data-cancel>取消</button><button type="submit" class="action-btn primary">保存</button></div></form>`;
        const close=()=>bg.remove();bg.querySelector('[data-cancel]').onclick=close;bg.onkeydown=e=>{if(e.key==='Escape')close();};
        bg.querySelector('form').onsubmit=async e=>{e.preventDefault();const b=bg.querySelector('[type=submit]');b.disabled=true;try{await submit(Object.fromEntries(new FormData(e.target)));close();await this.members();await loadUsers();}catch(err){bg.querySelector('[role=status]').textContent=err.message;b.disabled=false;}};
        document.body.append(bg);bg.querySelector('input,select,button').focus();
    },
    createDepartment(){this.form('新建部门','<label>部门名称<div class="field-frame"><input name="name" required maxlength="160"></div></label>',async v=>{
        await apiFetch('/enterprise/api/business/departments',{method:'POST',body:JSON.stringify(v)});location.reload();
    });},
    edit(id){
        const member=this.data.members.find(m=>m.id===id),current=member?.department_id;
        if(!this.data.company_admin){this.form('移出本部门','<p>只移除部门关系，不删除账号、任务或历史费用。</p>',()=>apiFetch('/enterprise/api/business/departments/'+encodeURIComponent(current)+'/members/'+encodeURIComponent(id),{method:'DELETE'}));return;}
        this.form('设置成员部门','<label>所属部门<div class="field-frame"><select name="department"><option value="">未分配部门</option>'+this.data.departments.map(d=>`<option value="${escapeHtml(d.id)}" ${d.id===current?'selected':''}>${escapeHtml(d.name)}</option>`).join('')+'</select></div></label><label>部门职责<div class="field-frame"><select name="manager"><option value="false">成员</option><option value="true" '+(member?.manager?'selected':'')+'>部门负责人</option></select></div></label><p>新调用使用新归属；历史任务、费用和已受理任务身份保持。</p>',async v=>{
            if(v.department)await apiFetch('/enterprise/api/business/departments/'+encodeURIComponent(v.department)+'/members/'+encodeURIComponent(id),{method:'PUT',body:JSON.stringify({manager:v.manager==='true'})});
            else if(current)await apiFetch('/enterprise/api/business/departments/'+encodeURIComponent(current)+'/members/'+encodeURIComponent(id),{method:'DELETE'});
        });
    }
};
