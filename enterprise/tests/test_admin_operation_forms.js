// Execute the real admin page script. No passwords, accounts or data outside fixtures.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../../enterprise-static/admin.html'), 'utf8');
const script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).join('\n');
const elements = new Map();
const element = id => {
    if(!elements.has(id)) elements.set(id, {value:'', textContent:'', innerHTML:'', style:{}, classList:{add(){},remove(){}}});
    return elements.get(id);
};
const calls = [];
const context = vm.createContext({
    document:{getElementById:element, querySelectorAll:() => []},
    sessionStorage:{getItem:() => null}, setTimeout(){}, clearTimeout(){},
    confirm:() => true, prompt:() => 'fixture-member',
    fakeApi:async (url, init) => { calls.push({url, body:JSON.parse(init.body)}); return {success:true, is_active:false}; },
});
vm.runInContext(script.replace('\n  initializeAdmin();', ''), context);
vm.runInContext('apiFetch=fakeApi; loadUsers=async()=>{}; showToast=()=>{}; renderUsers=()=>{}; fetchUsers=async()=>[{id:"member",is_active:false}];', context);
(async () => {
    element('newUsername').value='fixture-admin'; element('newPassword').value='fixture-password';
    element('newRole').value='admin'; element('createCurrentPassword').value='fixture-current'; element('createReason').value='delegate admin';
    await vm.runInContext('submitCreate()', context);
    assert.equal(calls.at(-1).body.role, 'admin');
    assert.equal(calls.at(-1).body.current_password, 'fixture-current');
    assert.equal(calls.at(-1).body.reason, 'delegate admin');
    vm.runInContext('_pwdTargetId="member"', context);
    element('newPwd').value='fixture-replacement'; element('pwdReason').value='reset fixture';
    await vm.runInContext('submitPwd()', context);
    assert.equal(calls.at(-1).body.reason, 'reset fixture');
    context.prompt=() => 'disable fixture';
    await vm.runInContext('setUserActive("member","fixture-member",false)', context);
    element('memberStateReason').value='disable fixture';
    await vm.runInContext('submitMemberState()', context);
    assert.equal(calls.at(-1).body.reason, 'disable fixture');
    vm.runInContext('_impactTarget={userId:"member",username:"fixture-member"}', context);
    element('impactReason').value='offboard fixture'; context.prompt=() => 'fixture-member';
    element('impactConfirmUsername').value='fixture-member';
    await vm.runInContext('softDeleteImpactUser()', context);
    assert.equal(calls.at(-1).body.reason, 'offboard fixture');
    assert.equal(calls.at(-1).body.confirm_username, 'fixture-member');
    const count=calls.length;
    vm.runInContext('_impactTarget={userId:"member",username:"fixture-member"}', context);
    element('impactReason').value='';
    await vm.runInContext('softDeleteImpactUser()', context);
    assert.equal(calls.length,count);
    console.log('actual admin form request fields and empty-reason rejection passed');
})().catch(e => {console.error(e);process.exitCode=1;});
