const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
let tabs = [{id:7,url:'http://127.0.0.1:8000/'}];
let requests = [];
let opened = [];
let status = 200;
const context = vm.createContext({window:{}, URL, location:{origin:'http://127.0.0.1:8000'},
    fetch:async (url, init) => {requests.push({url,init});return {ok:status===200,status,text:async()=>JSON.stringify({count:1})};},
    chrome:{tabs:{query:async()=>tabs,create:async input=>opened.push(input)},
        scripting:{executeScript:async input=>[{result:await input.func(...input.args)}]}},
});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../../tools/chrome-local-asset-importer/platform-client.js'),'utf8'),context);
const client=context.window.CanvasPlatformClient;
(async()=>{
    const imported=await client.request('http://127.0.0.1:8000','/api/local-assets/import-urls',{method:'POST',body:'fixture-bytes'});
    assert.equal(imported.count,1);
    assert.equal(requests[0].init.credentials,'same-origin');
    assert.equal(requests[0].url,'/api/local-assets/import-urls');
    assert.equal(requests[0].init.body,'fixture-bytes');
    status=401;
    await assert.rejects(()=>client.request('http://127.0.0.1:8000','/api/config'),/登录/);
    context.location.origin='https://unrelated.invalid';
    const count=requests.length;
    await assert.rejects(()=>client.request('http://127.0.0.1:8000','/api/config'),/地址已变化/);
    assert.equal(requests.length,count);
    tabs=[];
    await assert.rejects(()=>client.request('http://127.0.0.1:8000','/api/config'),/已打开平台页面/);
    assert.equal(opened[0].url,'http://127.0.0.1:8000/');
    await assert.rejects(()=>client.request('http://127.0.0.1:8000','/enterprise/api/users'),/不支持/);
    console.log('same-origin relay, expired session, navigated tab and endpoint restrictions passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
