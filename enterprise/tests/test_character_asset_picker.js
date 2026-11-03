'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../..');
const context = vm.createContext({window: {}, URL, URLSearchParams, location: {origin: 'http://localhost'},
  document: {}, CanvasTaskQuery: {requestId: () => 'new-import-id'}});
for (const file of ['character-asset-picker.js', 'character-creation-view.js'])
  vm.runInContext(fs.readFileSync(path.join(root, 'static/js', file), 'utf8'), context);
const Sources = context.window.CharacterAssetSources;
const Picker = context.window.CharacterAssetPicker;
const Creation = context.window.CharacterCreationView;
const previewCalls = [];
context.window.canvasMediaPreviewUrl = (url, size) => { previewCalls.push({url, size}); return '/preview?size=' + size; };
assert.equal(Sources.previewUrl('http://localhost/assets/input/4k.png?version=2'), '/preview?size=320');
assert.deepEqual(previewCalls, [{url: '/assets/input/4k.png?version=2', size: 320}]);
assert.equal(Sources.previewUrl('https://other.test/4k.png'), 'https://other.test/4k.png', 'remote media must not be reinterpreted as a local path');
delete context.window.canvasMediaPreviewUrl;
assert.equal(Sources.previewUrl('/assets/input/4k.png'), '/assets/input/4k.png', 'legacy callers without a thumbnail helper retain the original');
const ctx = Sources.context({canvases: [{id: 'one', project: 'p1'}, {id: 'two', project: 'p2'}], items: [
  {url: '/assets/output/shared.png', canvas_id: 'one', kind: 'image'},
  {url: '/assets/output/shared.png', canvas_id: 'two', kind: 'image'},
  {url: '/assets/input/upload.png', canvas_id: 'one', kind: 'image'},
  {url: '/assets/output/video.mp4', canvas_id: 'one', kind: 'video'},
]});
const rows = Sources.images('generated', [
  {timestamp: 1700000000, images: ['/assets/output/shared.png', 'https://other.test/assets/output/shared.png']},
  {images: ['/assets/output/unlinked.png', 'javascript:alert(1)', '/video.mp4']},
], ctx);
assert.equal(rows.length, 3);
assert.equal(rows.find(row => row.url === '/assets/output/shared.png').projects.size, 2, 'same image can belong to two projects');
assert.equal(rows.find(row => row.url.startsWith('https://')).projects.size, 0, 'external URL must not borrow local project membership');
assert.equal(rows.find(row => row.url.endsWith('unlinked.png')).projects.size, 0, 'unknown project must not become the current project');
assert.equal(rows[0].created, 1700000000000);
assert.equal(rows.find(row => row.url.endsWith('unlinked.png')).created, 0);
assert.equal(Sources.urlKey(undefined), '');
const uploaded = Sources.images('uploaded', {items: [{url: '/assets/uploads/local.webp', kind: 'image'}]}, ctx);
assert.equal(uploaded.length, 2);
assert.ok(uploaded.every(row => !row.url.includes('/output/')), 'uploaded source must not mix in generated outputs');
const saved = Sources.images('saved', {library: {libraries: [{categories: [{items: [
  {url: '/assets/library/saved.png', kind: 'image'}, {url: '/assets/library/workflow.json', kind: 'workflow'},
]}]}]}}, ctx);
assert.equal(saved.length, 1);
assert.equal(saved[0].url, '/assets/library/saved.png', 'thumbnail URLs must not replace the selected original');
const filtered = Object.assign(Object.create(Picker.prototype), {rows, scope: 'project', projectId: 'p2', newest: true});
assert.equal(filtered.visibleRows().length, 1);
filtered.scope = 'all';
assert.equal(filtered.visibleRows().length, 3);

for (const destination of ['library', 'generate', 'import']) {
  let cards = 0, rendered = 0, destroyed = 0;
  const view = Object.assign(Object.create(Creation.prototype), {
    mode: 'assets', assetReturn: destination, imported: {url: '/old.png'},
    assetPicker: {destroy() {destroyed++;}},
    root: {hidden: false, classList: {remove() {}}},
    studio: {dialog: {querySelector: () => ({setAttribute() {}}), classList: {remove() {}}},
      message() {}, renderCards() {cards++;}},
    pause() {}, render() {rendered++;},
  });
  view.back();
  assert.equal(destroyed, 1);
  if (destination === 'library') {
    assert.equal(view.root.hidden, true);
    assert.equal(view.imported, null);
    assert.equal(cards, 1);
    assert.equal(rendered, 0, 'direct asset entry must not render a local-upload form on back');
  } else {
    assert.equal(view.mode, destination);
    assert.equal(rendered, 1, 'explicit generation/import caller keeps its own form');
  }
}

(async () => {
  let nextFailure=false,stale=false;
  const calls=[];
  const paged=Object.assign(Object.create(Picker.prototype), {source:'saved',scope:'all',newest:true,version:0,rows:[],render(){},
    request:async (endpoint,options)=>{
      if(endpoint==='/api/canvas-assets/context'){
        const body=JSON.parse(options.body);assert.ok(body.urls.length<=24);return{canvases:[],items:[]};
      }
      if(endpoint==='/api/canvas-assets')return{canvases:[],items:[]};
      const url=new URL(endpoint,'http://localhost');calls.push(url);
      if(nextFailure){nextFailure=false;throw Object.assign(Error('retry'),{status:503});}
      if(stale){stale=false;throw Object.assign(Error('updated'),{status:409});}
      const offset=url.searchParams.get('cursor')?24:0;
      return{items:Array.from({length:24},(_,i)=>({id:'i'+(offset+i),url:'/assets/library/'+(offset+i)+'.png',kind:'image',unused_server_payload:'server-only-history-detail'.repeat(2000)})),total:48,next_cursor:offset?null:'next'};
    }});
  await paged.load();assert.equal(paged.rows.length,24);assert.equal(calls[0].searchParams.get('page_size'),'24');assert.equal(calls[0].searchParams.get('kind'),'image');
  const chosen=paged.rows[0];paged.selected=chosen;nextFailure=true;await paged.loadMore();
  assert.equal(paged.rows.length,24);assert.equal(paged.cursor,'next');assert.strictEqual(paged.selected,chosen);
  await paged.loadMore();assert.equal(paged.rows.length,48);assert.equal(paged.cursor,null);
  assert.ok(!JSON.stringify(paged).includes('server-only-history-detail'),'picker must retain selection metadata rather than duplicate complete server pages');
  await paged.load();stale=true;await paged.loadMore();assert.equal(paged.needsRefresh,true);
  await paged.loadMore();assert.equal(calls.at(-1).searchParams.has('cursor'),false,'revision refresh restarts the list');
  paged.scope='project';paged.projectId='unknown';assert.equal(paged.visibleRows().length,0);assert.ok(paged.cursor,'unknown project stays incomplete while more server pages exist');
  let resolveHistory, rendered = 0;
  const picker = Object.assign(Object.create(Picker.prototype), {source: 'generated',
    scope: 'project', projectId: 'p1', version: 0, cache: new Map(),
    render() {rendered++;}, request(endpoint) {
      if (endpoint === '/api/canvas-assets') return Promise.resolve({canvases: [], items: []});
      return new Promise(resolve => {resolveHistory = resolve;});
    }, root: {remove() {}},
  });
  const loading = picker.load();
  picker.destroy();
  const atClose = rendered;
  resolveHistory([{images: ['/assets/output/late.png']}]);
  await loading;
  assert.equal(rendered, atClose, 'late read must not revive a cancelled picker');
  assert.equal(picker.rows.length, 0);
  let associationFails=false;const requested=[];
  const uploads=Object.assign(Object.create(Picker.prototype),{source:'uploaded',scope:'all',newest:true,version:0,rows:[],render(){},
    request:async(endpoint,options)=>{
      if(endpoint==='/api/canvas-assets/context'){
        if(associationFails){associationFails=false;throw Object.assign(Error('association retry'),{status:503});}
        return{canvases:[{id:'one',project:'p1'}],items:JSON.parse(options.body).urls.map(url=>({url,canvas_id:'one'}))};
      }
      assert.notEqual(endpoint,'/api/canvas-assets','new servers must not download the complete canvas index');
      const url=new URL(endpoint,'http://localhost');requested.push(url.searchParams.get('cursor'));
      assert.equal(url.searchParams.get('kind'),'image');
      const offset=url.searchParams.get('cursor')?24:0;
      return{items:Array.from({length:24},(_,i)=>({id:'u'+(i+offset),url:'/assets/uploads/'+(i+offset)+'.png',kind:'image'})),total:48,next_cursor:offset?null:'next'};
    }});
  await uploads.load();assert.equal(uploads.rows.length,24);assert.ok(uploads.rows[0].projects.has('p1'));
  uploads.selected=uploads.rows[0];associationFails=true;await uploads.loadMore();
  assert.equal(uploads.cursor,'next','context failure must not advance the source cursor');assert.equal(uploads.rows.length,24);assert.ok(uploads.selected);
  await uploads.loadMore();assert.equal(uploads.rows.length,48);assert.deepEqual(requested,[null,'next','next']);
  console.log('Character asset picker: sources, project isolation, return destinations and cancelled-read lifecycle passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
