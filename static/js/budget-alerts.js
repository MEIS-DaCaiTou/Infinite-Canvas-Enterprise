/* Non-modal, current-period notices. Never participates in generation. */
(function(){
    let panel, pending=false, dismissed=new Set();
    const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    async function refresh(){
        if(pending||document.hidden)return;pending=true;
        try{
            const response=await fetch('/enterprise/api/business/budget-alerts',{cache:'no-store'});
            if(!response.ok)throw Error('unavailable');
            const data=await response.json();
            const storageKey='canvas-budget-notices:'+data.user_id;
            try{dismissed=new Set(JSON.parse(localStorage.getItem(storageKey)||'[]'));}catch(e){}
            const alerts=(data.alerts||[]).filter(a=>!dismissed.has(a.id));
            panel?.remove();panel=null;if(!alerts.length)return;
            const query=new URLSearchParams({tab:'costs',scope:data.company_admin?'company':'department',department_id:alerts[0].department_id});
            panel=document.createElement('aside');panel.className='budget-notice';panel.setAttribute('role','status');
            panel.innerHTML='<strong>部门预算提醒</strong>'+alerts.map(a=>'<p>'+esc(a.department_name)+' · '+esc(a.period)+'<br>已知实际 '+esc(a.actual)+' '+esc(a.unit==='platform_units'?'平台额度':a.unit)+'，超出 '+esc(a.over_amount)+'<br><small>待核对 '+esc(a.pending_reconciliation)+' 笔；生成继续可用</small></p>').join('')+'<div><a href="/enterprise/business?'+esc(query)+'">查看费用</a><button type="button">本期已知晓</button></div>';
            panel.querySelector('button').onclick=()=>{
                alerts.forEach(a=>dismissed.add(a.id));
                try{localStorage.setItem(storageKey,JSON.stringify([...dismissed].slice(-100)));}catch(e){}
                panel?.remove();panel=null;
            };
            document.body.append(panel);
        }catch(e){panel?.remove();panel=null;}finally{pending=false;}
    }
    refresh();setInterval(refresh,60000);
    document.addEventListener('visibilitychange',refresh);
    window.addEventListener('storage',e=>{if(e.key?.startsWith('canvas-budget-notices:'))refresh();});
})();
