// Catalog and request contract only. No real credential, provider request or browser write.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
let config={api_providers:[
    {id:'zhenzhen',name:'贞贞 API',enabled:true,managed_source_supported:true,has_key:false,key_preview:'excluded'},
    {id:'company',name:'公司代理',managed_source_supported:true},
    {id:'disabled',name:'已停用平台',enabled:false,managed_source_supported:true},
    {id:'runninghub',name:'RunningHub',managed_source_supported:false},
]};
const requests=[];let html,submit,refreshed=0;
const controls={
    '[name=provider_id]':{value:''}, '[name=secret]':{}, '[type=submit]':{}, '[data-platform-help]':{},
    '[name=scope]':{value:'company'}, '[name=procurement]':{value:'company',querySelector:()=>({disabled:false})},
    '[name=account_ref]':{value:'',addEventListener:(_event,fn)=>{controls.accountChanged=fn;}}, '[data-duplicate-help]':{textContent:''}
};
const form={querySelector:selector=>controls[selector]};
const context=vm.createContext({adminT:value=>value,
    document:{querySelectorAll:()=>[]},
    DepartmentMembers:{data:{company_admin:true,departments:[{id:'design',name:'设计部'}]},
        form:(_title,body,handler)=>{html=body;submit=handler;return form;}},
    escapeHtml:value=>String(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])),
    apiFetch:async(url,options)=>{requests.push({url,options});return url==='/api/config'?config:{id:'synthetic'};},
});
context.window=context;
vm.runInContext(fs.readFileSync(path.join(__dirname,'../../static/js/department-credentials.js'),'utf8'),context);
const ui=context.DepartmentCredentials;
ui.load=async()=>{refreshed++;};
(async()=>{
    await ui.create();
    assert.match(html,/<select name="provider_id" aria-label="调用平台" required>/);
    assert.doesNotMatch(html,/<input name="provider_id"/);
    assert.match(html,/贞贞 API（zhenzhen）/);
    assert.doesNotMatch(html,/已停用平台/);
    assert.match(html,/<option value="runninghub" disabled>RunningHub（runninghub） · 暂未接通渠道密钥/);
    assert.equal(controls['[type=submit]'].disabled,true);
    assert.equal(controls['[name=secret]'].disabled,true);
    controls['[name=provider_id]'].value='zhenzhen';
    ui.rows=[{provider_id:'zhenzhen',account_ref:'company-main',scope:'company'}];
    controls['[name=account_ref]'].value='company-main';
    controls['[name=provider_id]'].onchange();
    assert.match(controls['[data-duplicate-help]'].textContent,/已有来源/);
    controls['[name=account_ref]'].value='another';controls.accountChanged();
    assert.equal(controls['[data-duplicate-help]'].textContent,'');
    assert.equal(controls['[type=submit]'].disabled,false);
    assert.equal(controls['[name=secret]'].placeholder,'填写贞贞 API的 API Key');
    assert(!('key_preview' in ui.providers[0]));
    await submit({provider_id:'zhenzhen',scope:'company',procurement:'company',name:'公司共享',account_ref:'company-main',secret:'synthetic-test-only'});
    const request=requests.find(item=>item.options?.method==='POST');
    const body=JSON.parse(request.options.body);
    assert.equal(body.provider_id,'zhenzhen');assert.equal(body.department_id,null);
    assert(!('base_url' in body));assert.equal(refreshed,1);
    assert.match(ui.providerLabel('unmatched'),/未匹配平台（unmatched）/);
    config={api_providers:[]};await ui.create();
    assert.equal(controls['[type=submit]'].disabled,true);
    assert.match(controls['[data-platform-help]'].textContent,/暂无已接通/);
    console.log('Configured platform choices, capability labels, native selection and source request passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
