'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const js = path.resolve(__dirname, '../../static/js');

async function check(kind){
    const smart = kind === 'smart', board = {id:'board',updated_at:10};
    let active = true, revision = 10, reply;
    const requests = [];
    const ctx = vm.createContext({document:{hidden:false},frameElement:{matches:()=>!active},
        canvas:board,canvasId:board.id,canvasSyncInFlight:false,smartSaveConflict:false,
        dragState:null,selectionState:null,canvasMetaPollBusy:false,applyingRemoteCanvas:false,
        localCanvasDirty:false,savingCanvasNow:false,canvasSaveConflict:false,
        remoteSyncBusy:false,remoteCanvasReadBusy:false,lastCanvasUpdatedAt:10,
        fetch:async(url,options)=>{
            requests.push(url);assert.equal(options.cache,'no-store');
            if(reply) await reply;
            return {ok:true,json:async()=>url.endsWith('/meta')?{updated_at:revision}:{canvas:{id:board.id,updated_at:revision}}};
        },applyRemoteCanvasData:data=>{ctx.lastCanvasUpdatedAt=data.updated_at;},
        applyMergedServerCanvas:data=>{ctx.canvas=data;}});
    ctx.window=ctx;
    vm.runInContext(fs.readFileSync(path.join(js,'canvas-view-activity.js'),'utf8'),ctx);
    const source=fs.readFileSync(path.join(js,smart?'smart-canvas.js':'canvas.js'),'utf8');
    const load=name=>{
        const start=source.indexOf('async function '+name+'(');
        assert(start>=0,name);
        const next=source.slice(start+1).search(/\n(?:async )?function \w+\(/);
        vm.runInContext(source.slice(start,start+1+next),ctx);
    };
    const poll=smart?'checkSmartCanvasVersion':'checkRemoteCanvasVersion';
    load(smart?'mergeReloadCanvasNow':'syncRemoteCanvasNow');load(poll);
    active=false;await ctx[poll]();assert.equal(requests.length,0);
    active=true;ctx.document.hidden=true;await ctx[poll]();assert.equal(requests.length,0);
    ctx.document.hidden=false;await ctx[poll]();assert.deepEqual(requests,['/api/canvases/board/meta']);
    requests.length=0;revision=20;
    let release;reply=new Promise(resolve=>{release=resolve;});
    const pending=ctx[poll]();await ctx[poll]();assert.equal(requests.length,1);
    active=false;release();await pending;assert.equal(requests.length,1,'a late version response cannot fetch a hidden board');
    active=true;ctx.frameElement=null;reply=null;requests.length=0;
    await ctx[poll]();
    assert.deepEqual(requests,['/api/canvases/board/meta','/api/canvases/board']);
    assert.equal(smart?ctx.canvas.updated_at:ctx.lastCanvasUpdatedAt,20);
}
(async()=>{await check('classic');await check('smart');console.log('canvas visibility, fresh revision, in-flight deduplication and late response: PASS');})()
    .catch(error=>{console.error(error);process.exitCode=1;});
