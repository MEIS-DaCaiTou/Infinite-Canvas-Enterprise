// Actual admin functions; synthetic DOM. Browser acceptance is recorded separately.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../../enterprise-static/admin.html'), 'utf8');
const script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).join('\n');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    value: '', textContent: '', disabled: false, children: [],
    replaceChildren() { this.children = []; this.value = ''; },
    appendChild(child) { this.children.push(child); },
  });
  return elements.get(id);
}
const context = vm.createContext({
  adminT: value => value,
  adminTF: (text, values) => text.replace(/\{(\w+)\}/g, (_, key) => String(values[key])),
  document: {getElementById: element, createElement: () => ({value: '', textContent: ''}), querySelectorAll: () => []},
  sessionStorage: {getItem: () => null}, clearTimeout() {}, setTimeout() {},
});
vm.runInContext(script.replace('\n  initializeAdmin();', ''), context);
vm.runInContext("_updateAccess = {can_operate: true}; showToast = () => {};", context);
assert.match(vm.runInContext("formatApiError({status:400}, '', {detail:{code:'RELEASE_CATALOG_INCOMPLETE',message:'private-response'}})", context), /未启动升级/);
assert.doesNotMatch(vm.runInContext("formatApiError({status:400}, '', {detail:{code:'RELEASE_CATALOG_INCOMPLETE',message:'private-response'}})", context), /private-response/);
const valid = {
  current_release_id: 'synthetic-source', current_version: '2026.07.6',
  catalog: {complete: true, record_count: 51, page_count: 2},
  releases: [{provider_release_id: 'page-two-target', tag_name: 'v2026.08.1',
    version: '2026.08.1', stage: 'stable', route_status: 'direct'}],
};
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
function check(request) {
  context.fixtureRequest = () => request;
  vm.runInContext('apiFetch = fixtureRequest;', context);
  return vm.runInContext('checkSystemUpdate()', context);
}
(async () => {
  await check(Promise.resolve(valid));
  assert.equal(element('updateReleaseSelect').value, 'page-two-target');
  assert.equal(element('startUpdateBtn').disabled, false);
  assert.match(element('updateReleaseSummary').textContent, /历史发布目录已完整核验/);
  const old = deferred();
  const loading = check(old.promise);
  assert.equal(element('startUpdateBtn').disabled, true);
  assert.equal(element('updateReleaseSelect').disabled, true);
  await check(Promise.reject(new Error('历史发布目录未能完整核验；未启动升级。')));
  old.resolve(valid);
  await loading;
  assert.equal(element('updateReleaseSelect').children.length, 0);
  assert.equal(element('startUpdateBtn').disabled, true);
  assert.match(element('updateReleaseSummary').textContent, /未启动升级/);
  await check(Promise.resolve({...valid, catalog: {complete: false}}));
  assert.equal(element('startUpdateBtn').disabled, true);
  assert.equal(element('updateReleaseSelect').children.length, 0);
  const lateFailure = deferred();
  const obsolete = check(lateFailure.promise);
  await check(Promise.resolve(valid));
  lateFailure.reject(new Error('obsolete request'));
  await obsolete;
  assert.equal(element('updateReleaseSelect').value, 'page-two-target');
  assert.equal(element('startUpdateBtn').disabled, false);
  vm.runInContext("_preparedUpdate = {state: 'READY'};", context);
  await check(Promise.reject(new Error('catalog unavailable')));
  assert.equal(element('startUpdateBtn').disabled, false); // verified READY job uses its own authority
  assert.match(element('startUpdateBtn').textContent, /继续已准备/);
  console.log('catalog availability, loading, failure, incomplete response and request-race controls passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
