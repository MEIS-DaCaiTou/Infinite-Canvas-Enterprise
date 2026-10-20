'use strict';
// Actual preparation/submission/source functions, with controlled HTTP and time.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'../../static/js'),text=fs.readFileSync(path.join(root,'canvas.js'),'utf8');
function load(ctx,name){
    const match=new RegExp('(?:async )?function '+name+'\\(').exec(text);assert.ok(match,name);
    const end=text.slice(match.index+match[0].length).search(/\n(?:async )?function \w+\(/);
    vm.runInContext(text.slice(match.index,end<0?undefined:match.index+match[0].length+end),ctx);
}
function fixture({size=async()=>'1024x1024',save=async()=>true,result=async()=>({images:['/output/synthetic.png']})}={}){
    const node={id:'gen',type:'generator',count:4,model:'gpt-image-2'},calls=[],timers=[],errors=[];
    const ctx=vm.createContext({console,URLSearchParams,WeakSet,canvas:{id:'canvas'},nodes:[node],savingCanvasNow:false,
        saveCanvas:async()=>{calls.push('save');return save();},sleep:async()=>{},
        checkTextSelection:()=>true,cascadeTargetIdFromOptions:()=>'',generatorSources:()=>[{prompt:'synthetic',refs:[]}],
        orderedSources:(_n,s)=>s,imageRefsOnly:()=>[],outputForNode:()=>null,runSnapshot:()=>({}),
        resolveImageProviderId:()=> 'zhenzhen',resolveImageModel:x=>x,generatorSizeForRun:size,
        normalizedImageQuality:()=>'',CANVAS_REFERENCE_IMAGE_MAX:20,
        refreshRunNodes:()=>calls.push(ctx.CanvasRunPreparation.has(node)?'preparing':'refresh'),
        nowMs:()=>1,tr:x=>x,mergeGeneratedOutputs:()=>{},addGenerationLog:()=>{},scheduleSave:()=>{},
        waitCanvasImageTaskResult:result,setTimeout:callback=>{timers.push(callback);},
        collectRunMetas:()=>[],isCascadeAbortError:()=>false,showErrorModal:error=>errors.push(error),
        responseErrorMessage:async()=> 'controlled failure',
        cascadeFetch:async(_url,options)=>{calls.push(JSON.parse(options.body));return {ok:true,json:async()=>({task_id:'id'+calls.length})};}
    });
    ctx.window=ctx;vm.runInContext(fs.readFileSync(path.join(root,'canvas-media-retention.js'),'utf8'),ctx);
    vm.runInContext(fs.readFileSync(path.join(root,'task-canvas-context.js'),'utf8'),ctx);
    for(const name of ['taskCanvasSource','createCanvasImageTask','runGenerator'])load(ctx,name);
    return {ctx,node,calls,timers,errors};
}
const posts=f=>f.calls.filter(v=>typeof v==='object');
async function run(){
    let release;const f=fixture({size:()=>new Promise(ok=>{release=ok;})});
    const pending=f.ctx.runGenerator('gen');assert.equal(f.ctx.CanvasRunPreparation.has(f.node),true);
    assert.equal(f.node.running,undefined);assert.equal(posts(f).length,0);
    await f.ctx.runGenerator('gen');assert.equal(posts(f).length,0,'a second click during preparation cannot submit');
    release('1024x1024');await pending;
    assert.equal(f.calls.filter(v=>v==='save').length,1,'one confirmed source save per batch');
    assert.equal(posts(f).length,4,'the requested batch still creates four tasks');
    assert.ok(posts(f).every(p=>p.source.canvas_id==='canvas' && p.source.node_id==='gen'));
    assert.equal(f.ctx.CanvasRunPreparation.has(f.node),false);

    const failed=fixture({save:async()=>false});await failed.ctx.runGenerator('gen');assert.equal(posts(failed).length,0);
    const badSize=fixture({size:async()=>{throw new Error('source image unavailable');}});await badSize.ctx.runGenerator('gen');
    assert.equal(posts(badSize).length,0);assert.equal(badSize.ctx.CanvasRunPreparation.has(badSize.node),false);
    let attempts=0;const conflict=fixture({save:async()=>++attempts===1?'retry':true});await conflict.ctx.runGenerator('gen');
    assert.equal(attempts,2);assert.equal(posts(conflict).length,4,'conflict must finish saving before any submission');
    for(const change of [f=>{f.ctx.canvas={id:'another'};},f=>{f.ctx.nodes=[];}]){
        let finish;const moved=fixture({save:()=>new Promise(ok=>{finish=ok;})});const running=moved.ctx.runGenerator('gen');
        await new Promise(ok=>setImmediate(ok));change(moved);finish(true);await running;
        assert.equal(posts(moved).length,0,'navigation/deletion during source save prevents generation');
    }
    const rejected=fixture();rejected.ctx.cascadeFetch=async()=>{rejected.calls.push({post:true});return {ok:false};};
    await rejected.ctx.runGenerator('gen');assert.equal(posts(rejected).length,4,'ambiguous failure does not automatically submit again');

    let finishResult;const concurrent=fixture({result:()=>new Promise(ok=>{finishResult=ok;})});
    const first=concurrent.ctx.runGenerator('gen');await new Promise(ok=>setImmediate(ok));
    assert.equal(posts(concurrent).length,4);concurrent.timers[0]();
    concurrent.ctx.waitCanvasImageTaskResult=async()=>({images:['/output/second.png']});await concurrent.ctx.runGenerator('gen');
    assert.equal(posts(concurrent).length,8,'the existing post-preparation manual concurrency remains allowed');
    finishResult({images:['/output/first.png']});await first;
    console.log('preparation feedback/reentry, one-save batch, 409/failure/navigation, no automatic resubmit, existing concurrency: PASS');
}
run().catch(error=>{console.error(error);process.exitCode=1;});
