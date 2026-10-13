// Synthetic script/DOM regression, not a browser or production acceptance.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../../enterprise-static/admin.html'), 'utf8');
const script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).join('\n');
assert.equal((script.match(/\n  initializeAdmin\(\);/g) || []).length, 1);
const elements = new Map();
const dangerous = [{style: {}}, {style: {}}, {style: {}}];
function element(id) {
  if (!elements.has(id)) elements.set(id, {value: '', innerHTML: '', textContent: '', disabled: false, style: {}});
  return elements.get(id);
}
const context = vm.createContext({
  document: {getElementById: element, querySelectorAll: selector => selector === '.update-dangerous' ? dangerous : []},
  sessionStorage: {getItem: () => null}, clearTimeout() {}, setTimeout() {},
});
vm.runInContext(script.replace('\n  initializeAdmin();', ''), context);
element('memberStatusFilter').value = 'active';
element('memberRoleFilter').value = 'all';
element('memberSortMode').value = 'username';
vm.runInContext(`
  _currentUser = {user_id: 'super', role: 'super_admin'};
  _users = [
    {id: 'super', username: 'Aidan02', role: 'super_admin', is_admin: true, is_active: true},
    {id: 'admin', username: 'Operator', role: 'admin', is_admin: true, is_active: true},
    {id: 'user', username: 'Member', role: 'user', is_admin: false, is_active: true},
  ];
  renderUsers();
`, context);
function row(username) {
  const rows = element('userTable').innerHTML.match(/<tr\b[\s\S]*?<\/tr>/g) || [];
  return rows.find(r => r.includes(`title="${username}"`)) || '';
}
assert.match(row('Aidan02'), /badge-super-admin">超级管理员<\/span>/);
assert.match(row('Aidan02'), /受固定角色策略保护/);
assert.doesNotMatch(row('Aidan02'), /降级为普通成员|撤销管理员|重置密码|>禁用</);
assert.match(row('Operator'), /badge-admin">管理员<\/span>/);
assert.match(row('Member'), /badge-user">普通成员<\/span>/);
element('memberRoleFilter').value = 'super_admin';
vm.runInContext('applyMemberFilters()', context);
assert.match(row('Aidan02'), /超级管理员/);
assert.equal(row('Operator'), '');
assert.equal(row('Member'), '');
element('memberRoleFilter').value = 'all';
vm.runInContext("_currentUser = {user_id:'admin', role:'admin'}; renderUsers();", context);
assert.doesNotMatch(row('Aidan02'), /重置密码|>禁用</);
assert.doesNotMatch(row('Member'), /提升为管理员/);

function explanation(access) {
  context.fixtureAccess = access;
  return vm.runInContext('updateAccessExplanation(fixtureAccess)', context);
}
assert.match(explanation({role: 'super_admin', can_operate: false, deployment_update_enabled: false, feature_update_enabled: true}), /部署配置禁用了更新入口/);
assert.match(explanation({role: 'super_admin', can_operate: false, deployment_update_enabled: true, feature_update_enabled: false}), /系统更新全局开关未启用/);
assert.match(explanation({role: 'admin', can_operate: false, deployment_update_enabled: false}), /当前账号没有该角色/);
assert.match(explanation({role: 'super_admin', can_operate: false, global_update_enabled: false}), /旧版接口不能区分/);
assert.equal(explanation({role: 'super_admin', can_operate: true}), '');
assert.match(explanation(null), /无法确认更新权限/);

(async () => {
  let checkCalls = 0;
  context.fakeFetch = async () => ({role: 'super_admin', can_operate: false, deployment_update_enabled: false, feature_update_enabled: true});
  context.fakeCheck = async () => { checkCalls++; };
  vm.runInContext('apiFetch = fakeFetch; checkSystemUpdate = fakeCheck;', context);
  await vm.runInContext('loadUpdateCenter()', context);
  assert.match(element('updateAccessNotice').textContent, /部署配置禁用了更新入口/);
  assert(dangerous.every(el => el.style.display === 'none'));
  assert.equal(element('startUpdateBtn').disabled, true);
  assert.equal(checkCalls, 0);
  context.fakeFetch = async () => ({role: 'super_admin', can_operate: true, deployment_update_enabled: true, feature_update_enabled: true});
  context.fakePending = async () => [];
  vm.runInContext('apiFetch = fakeFetch; loadPendingRecoveryJobs = fakePending;', context);
  await vm.runInContext('loadUpdateCenter()', context);
  assert.equal(element('updateAccessNotice').style.display, 'none');
  assert.equal(checkCalls, 1); // Only a read-only availability check; no execution.
  context.fakeFetch = async () => { throw new Error('synthetic refresh failure'); };
  vm.runInContext('apiFetch = fakeFetch;', context);
  await vm.runInContext('loadUpdateCenter()', context);
  assert(dangerous.every(el => el.style.display === 'none'));
  assert.equal(element('startUpdateBtn').disabled, true);
  assert.match(element('updateAccessNotice').textContent, /未发起升级/);
  assert.equal(checkCalls, 1);
  console.log('actual member rows, role filtering, update gate messages and stale-view controls passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
