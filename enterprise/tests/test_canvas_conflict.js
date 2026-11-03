'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../static/js/canvas.js'),'utf8');
function load(context,names){
    for(const name of names){
        const match=new RegExp('(?:async )?function '+name+'\\(').exec(source);
        assert.ok(match,name);const tail=source.slice(match.index+match[0].length);
        const next=tail.search(/\n(?:async )?function \w+\(/);
        vm.runInContext(source.slice(match.index,next<0?undefined:match.index+match[0].length+next),context);
    }
}
async function run(){
    let saved={id:'board',title:'original',updated_at:1,nodes:[{id:'original'}]},writes=0;
    const stored=new Map(),status=[];
    function tab(id){
        const ctx=vm.createContext({canvas:JSON.parse(JSON.stringify(saved)),nodes:JSON.parse(JSON.stringify(saved.nodes)),
            connections:[],viewport:{},CLIENT_ID:id,lastCanvasUpdatedAt:1,localCanvasDirty:true,
            canvasSaveConflict:false,savingCanvasNow:false,saveCanvasAgain:false,applyingRemoteCanvas:false,
            saveTimer:null,currentCanvasTime:null,gateCanvasList:null,remoteSyncTimer:null,
            sanitizeConnections(){},setStatus:s=>status.push(s),console,clearTimeout(){},setTimeout(){throw Error('must not retry stale PUT');},
            serializableCanvasNodes(){return ctx.nodes;},formatCanvasTime(){return '';},
            applyRemoteCanvasData(){throw Error('must preserve local draft');},
            showCanvasConflict(){ctx.retained=JSON.parse(JSON.stringify(ctx.nodes));stored.set(id,ctx.retained);},
            retainConflictedCanvas(){ctx.showCanvasConflict();},
            fetch:async(_,options)=>{
                const body=JSON.parse(options.body);writes++;
                if(body.base_updated_at<saved.updated_at)return{status:409,ok:false,json:async()=>({detail:{canvas:saved,updated_at:saved.updated_at}})};
                saved={...saved,...body,updated_at:saved.updated_at+1};return{status:200,ok:true,json:async()=>({canvas:saved})};
            }});
        load(ctx,['saveCanvas','handleCanvasUpdatedMessage']);return ctx;
    }
    const a=tab('a'),b=tab('b');a.nodes.push({id:'a-new'});assert.equal(await a.saveCanvas(),true);
    b.nodes.push({id:'b-local'});
    b.handleCanvasUpdatedMessage({type:'canvas_updated',canvas_id:'board',client_id:'a',updated_at:2});
    assert.equal(b.localCanvasDirty,true,'WS notification may not clear dirty state');
    assert.equal(await b.saveCanvas(),false);assert.equal(b.lastCanvasUpdatedAt,1);
    assert.equal(b.canvasSaveConflict,true);assert.equal(writes,2);
    assert.deepEqual(saved.nodes.map(n=>n.id),['original','a-new']);
    assert.deepEqual(stored.get('b').map(n=>n.id),['original','b-local']);
    assert.equal(await b.saveCanvas(),false);assert.equal(writes,2,'conflict remains paused');
    const clean=tab('clean');clean.localCanvasDirty=false;let applied=false;
    clean.applyRemoteCanvasData=()=>{assert.equal(clean.savingCanvasNow,false);applied=true;};
    assert.equal(await clean.saveCanvas(),'retry');assert.equal(applied,true);
    const memory=new Map();const store=vm.createContext({window:{},sessionStorage:{getItem:k=>memory.get(k),setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)}});
    vm.runInContext(fs.readFileSync(path.join(__dirname,'../../static/js/canvas-conflict-draft.js'),'utf8'),store);
    assert.equal(store.window.CanvasConflictDraft.retain('board',{nodes:stored.get('b')}),true);
    assert.deepEqual(JSON.parse(JSON.stringify(store.window.CanvasConflictDraft.read('board'))).nodes.map(n=>n.id),['original','b-local']);
    assert.ok(!source.includes("onclick=\"deleteNodeFromButton('${node.id}'"),'node ID never enters handler attribute');
    const elements=[];let remoteOpens=0;
    function element(tag){return{tag,style:{},append(...children){elements.push(...children);},showModal(){},close(){},remove(){}};}
    const recovery=vm.createContext({document:{getElementById:()=>null,createElement:element,body:element('body')},
        sessionStorage:{setItem(){throw Error('quota');},getItem(){return null;}},
        canvas:{id:'board'},canvasSaveConflict:true,localCanvasDirty:true,saveCanvasAgain:false,
        retainConflictedCanvas:()=>false,conflictedCanvasDraft:()=>({nodes:[{id:'recoverable'}]}),
        openCanvas:async()=>{remoteOpens++;},saveTimer:null,clearTimeout(){}});
    recovery.window=recovery;
    vm.runInContext(fs.readFileSync(path.join(__dirname,'../../static/js/canvas-conflict-draft.js'),'utf8'),recovery);
    load(recovery,['showCanvasConflict']);recovery.showCanvasConflict();
    await elements.find(e=>e.textContent==='读取远端版本').onclick();assert.equal(remoteOpens,0);
    await elements.find(e=>e.textContent==='已下载草稿，读取远端版本').onclick();assert.equal(remoteOpens,1);
    let listActivity;
    const opened=vm.createContext({console,updateCanvasListRecord:r=>{listActivity=r.updated_at;},
        fetch:async()=>({ok:true,json:async()=>({canvas:{id:'board',updated_at:20,content_updated_at:10},updated_at:10})})});
    load(opened,['touchCanvasOpened']);
    assert.equal((await opened.touchCanvasOpened('board')).updated_at,10);
    assert.equal(listActivity,20,'list activity must not become the content save base');
    const opening=vm.createContext({console,window:{location:{replace(){throw Error('unexpected open failure');}}},
        setStatus(){},fetch:async()=>({ok:true,json:async()=>({canvas:{id:'board',kind:'classic',updated_at:10,nodes:[{id:'get-version'}]}})}),
        touchCanvasOpened:async()=>({updated_at:11}),resetCascadeRuntimeState(){},rememberCanvasListProject(){},
        localViewportForCanvas:(_,value)=>value,resetTransientRunState(){},sanitizeConnections(){},
        pruneMissingComfyWorkflows(){},refreshMissingCanvasAssets:async()=>[],selected:new Set(),
        setCanvasMode(){},renderCanvasList(){},render(){},focusTaskSource(){},resumeCanvasLLMTasks(){},
        resumeCanvasImageTasks(){},comfyTaskControls:{load(){}},startCanvasRemotePolling(){},
        CanvasConflictDraft:{read:()=>null}});
    load(opening,['openCanvas']);await opening.openCanvas('board');
    assert.equal(opening.lastCanvasUpdatedAt,10,'a save between GET and touch must not promote stale content');
    assert.equal(opening.nodes[0].id,'get-version');
    console.log('two-page conflict, remote notification, paused retry and draft recovery passed');
}
run().catch(e=>{console.error(e);process.exit(1);});

// Real smart-save functions against a versioned, two-page server fixture.
async function smartConflictRegression(){
    const smartSource=fs.readFileSync(path.join(__dirname,'../../static/js/smart-canvas.js'),'utf8');
    const plain=x=>JSON.parse(JSON.stringify(x));
    let saved={id:'smart-board',kind:'smart',title:'original',updated_at:1,viewport:{x:0,y:0,scale:1},settings:{},logs:[],connections:[],
        nodes:[{id:'one',title:'original',images:[{url:'/output/original.mp4',kind:'video'}]},{id:'deleted',images:[]}]};
    let writes=0;const retained=new Map();
    const names=['smartCanvasSaveContent','hasSmartCanvasChanges','smartConflictDraft','retainSmartCanvasConflict',
        'pauseSmartCanvasConflict','showSmartCanvasConflict','scheduleSave','saveSmartCanvasOnce','saveCanvas',
        'applyMergedServerCanvas','handleCanvasUpdatedMessage','scheduleCanvasMergeReload'];
    function page(id){
        const c=vm.createContext({canvas:plain(saved),canvasId:'smart-board',nodes:plain(saved.nodes),viewport:plain(saved.viewport),
            smartSavedContent:'',smartSaveConflict:false,smartSavePromise:null,smartSaveAgain:false,smartSaveRevision:0,
            saveTimer:null,canvasSyncTimer:null,canvasSyncInFlight:false,smartClientId:id,canvasDefaultSmartSettings:{},initialSmartSettings:{},
            console,URL,window:{location:{href:'http://localhost/static/smart-canvas.html?id=smart-board',replace:u=>{c.replaced=String(u);}}},
            document:{getElementById:()=>({})},clearTimeout(){},setTimeout:f=>{c.pendingTimer=f;return 1;},
            tr:x=>x,mediaItemForStorage:x=>x,stripImageGenerationMeta:x=>x,normalizeSmartGenerationLogs:x=>x||[],
            cloneSmartSettings:plain,normalizeLegacySmartNode:x=>x,canvasForStorage:()=>plain(c.canvas),
            savePromptDraftForCurrent(){},render(){},applyViewport(){},toast(){},clearCompletedNodeBusyStates:()=>false,
            recoverStuckLoopOutputsFromLogs:()=>false,resumeSmartPendingTasks(){},resumeJimengPendingNodes(){},
            CanvasConflictDraft:{retain:(_,d)=>{retained.set(id,plain(d));return true;},clear(){},show:o=>{c.dialog=o;}},
            fetch:async(url,options)=>{
                if(c.block){const wait=c.block;c.block=null;await wait;}
                const body=JSON.parse(options.body);writes++;
                if(options.method==='POST')return{ok:true,json:async()=>({canvas:{id:'copy',title:'copy title',updated_at:1}})};
                if(url.endsWith('/copy')){c.copy=body;return{ok:true,json:async()=>({})};}
                if(body.base_updated_at!==saved.updated_at)return{status:409,ok:false,json:async()=>({detail:{canvas:plain(saved)}})};
                saved={...saved,...plain(body),updated_at:saved.updated_at+1};return{ok:true,status:200,json:async()=>({canvas:plain(saved)})};
            }});
        for(const name of names){
            const m=new RegExp('^(?:async )?function '+name+'\\(','m').exec(smartSource);assert.ok(m,name);
            const rest=smartSource.slice(m.index+m[0].length),end=rest.search(/\n(?:async )?function \w+\(/);
            vm.runInContext(smartSource.slice(m.index,end<0?undefined:m.index+m[0].length+end),c);
        }
        c.smartSavedContent=JSON.stringify(c.smartCanvasSaveContent());return c;
    }
    const a=page('a'),b=page('b'),c=page('c'),clean=page('clean');
    a.nodes[0].title='remote edit';a.nodes.pop();await a.saveCanvas();
    b.nodes[0].title='local edit';b.nodes.push({id:'local-new',images:[]});
    assert.equal(b.applyMergedServerCanvas(plain(saved)),false);
    assert.equal(b.smartSaveConflict,true);assert.equal(b.canvas.updated_at,1);
    assert.equal(b.nodes[0].title,'local edit');assert.ok(b.nodes.some(x=>x.id==='local-new'));
    const before=writes;assert.equal(await b.saveCanvas(),false);assert.equal(writes,before);
    assert.equal(retained.get('b').nodes[0].images[0].url,'/output/original.mp4');
    c.nodes[0].title='dirty without websocket';assert.equal(await c.saveCanvas(),false);
    assert.equal(c.canvas.updated_at,1);assert.equal(c.smartSaveConflict,true);
    assert.equal(clean.applyMergedServerCanvas(plain(saved)),true);
    assert.equal(clean.nodes.some(x=>x.id==='deleted'),false,'clean remote deletion must not resurrect nodes');
    assert.equal(clean.nodes[0].title,'remote edit');
    const cleanWrites=writes;assert.equal(await clean.saveCanvas(),true);assert.equal(writes,cleanWrites);
    let release;const concurrent=page('concurrent');concurrent.nodes[0].title='first';
    concurrent.block=new Promise(resolve=>{release=resolve;});
    const first=concurrent.saveCanvas();concurrent.nodes[0].title='new edit during save';const second=concurrent.saveCanvas();
    const prior=writes;release();await Promise.all([first,second]);assert.equal(writes,prior+1,'single in-flight PUT');
    assert.equal(saved.nodes[0].title,'first');await concurrent.saveCanvas();assert.equal(saved.nodes[0].title,'new edit during save');
    await b.dialog.onCopy();assert.equal(b.copy.title,'copy title');assert.equal(b.copy.nodes[0].title,'local edit');
    assert.ok(b.replaced.includes('id=copy'));
    console.log('smart same-field/deletion conflict, clean remote sync, single-flight save, media draft and copy passed');
}
smartConflictRegression().catch(e=>{console.error(e);process.exitCode=1;});
