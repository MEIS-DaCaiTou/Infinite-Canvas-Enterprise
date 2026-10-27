/* Department settings inside the existing member administration. */
window.DepartmentMembers={
    data:null,
    async initialize(actor){
        const context=await apiFetch('/enterprise/api/business/context');
        if(context.enabled)this.data=await apiFetch('/enterprise/api/business/member-workspace');
        this.departmentOnly=Boolean(this.data&&!this.data.company_admin);
        document.getElementById('departmentsTab').hidden=!this.data;
        if(this.departmentOnly){
            document.querySelectorAll('.tab-btn').forEach(button=>{
                button.hidden=!['members','credentials'].includes(button.dataset.adminGroup);
            });
            document.getElementById('primaryActionBtn').hidden=true;
            document.getElementById('logsTab').hidden=true;
        }
    },
    async members(){this.data=await apiFetch('/enterprise/api/business/member-workspace');return this.data.members;},
    match(user){const value=document.getElementById('memberDepartmentFilter')?.value;const m=this.data?.members.find(m=>m.id===user.id);return !value||(value==='none'?!m?.department_id:m?.department_id===value);},
    form(title,body,submit){
        const bg=document.createElement('div');bg.className='modal-backdrop show';bg.setAttribute('role','dialog');bg.setAttribute('aria-modal','true');
        bg.innerHTML=`<form class="modal"><h3>${title}</h3>${body}<p role="status"></p><div class="modal-actions"><button type="button" class="action-btn" data-cancel>${adminT('取消')}</button><button type="submit" class="action-btn primary">${adminT('保存')}</button></div></form>`;
        const close=()=>bg.remove();bg.querySelector('[data-cancel]').onclick=close;bg.onkeydown=e=>{if(e.key==='Escape')close();};
        bg.querySelector('form').onsubmit=async e=>{e.preventDefault();const b=bg.querySelector('[type=submit]');b.disabled=true;try{await submit(Object.fromEntries(new FormData(e.target)));close();await loadUsers();}catch(err){bg.querySelector('[role=status]').textContent=err.message;b.disabled=false;}};
        document.body.append(bg);bg.querySelector('input,select,button').focus();return bg;
    },
    createDepartment(){this.form(adminT('新建部门'),'<label>部门名称<div class="field-frame"><input name="name" required maxlength="160"></div></label>',async v=>{
        await apiFetch('/enterprise/api/business/departments',{method:'POST',body:JSON.stringify(v)});
    });},
    async save(id,department,manager){
        const current=this.data.members.find(member=>member.id===id)?.department_id;
        if(department)await apiFetch('/enterprise/api/business/departments/'+encodeURIComponent(department)+'/members/'+encodeURIComponent(id),{method:'PUT',body:JSON.stringify({manager})});
        else if(current)await apiFetch('/enterprise/api/business/departments/'+encodeURIComponent(current)+'/members/'+encodeURIComponent(id),{method:'DELETE'});
    },
    edit(id){
        const member=this.data.members.find(m=>m.id===id),current=member?.department_id;
        if(!this.data.company_admin){this.form('移出本部门','<p>只移除部门关系，不删除账号、任务或历史费用。</p>',()=>apiFetch('/enterprise/api/business/departments/'+encodeURIComponent(current)+'/members/'+encodeURIComponent(id),{method:'DELETE'}));return;}
        this.form('设置成员部门','<label>所属部门<div class="field-frame"><select name="department"><option value="">未分配部门</option>'+this.data.departments.map(d=>`<option value="${escapeHtml(d.id)}" ${d.id===current?'selected':''}>${escapeHtml(d.name)}</option>`).join('')+'</select></div></label><label>部门职责<div class="field-frame"><select name="manager"><option value="false">成员</option><option value="true" '+(member?.manager?'selected':'')+'>部门负责人</option></select></div></label><p>新调用使用新归属；历史任务、费用和已受理任务身份保持。</p>',async v=>{
            if(v.department)await apiFetch('/enterprise/api/business/departments/'+encodeURIComponent(v.department)+'/members/'+encodeURIComponent(id),{method:'PUT',body:JSON.stringify({manager:v.manager==='true'})});
            else if(current)await apiFetch('/enterprise/api/business/departments/'+encodeURIComponent(current)+'/members/'+encodeURIComponent(id),{method:'DELETE'});
        });
    }
};
