'use strict';
// Actual canvas resume/finalization functions, disposable JSON, no paid provider.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const root = require('node:path').resolve(__dirname, '../..');
const read = name => fs.readFileSync(root + '/static/js/' + name, 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));
function functions(ctx, file, names) {
    const source = read(file);
    for (const name of names) {
        const match = new RegExp('(?:async )?function ' + name + '\\(').exec(source);
        assert(match, name);
        const after = match.index + match[0].length;
        const next = source.slice(after).search(/\n(?:async )?function \w+\(/);
        vm.runInContext(source.slice(match.index, next < 0 ? undefined : after + next), ctx);
    }
}
function setup(kind, nodes) {
    const ctx = vm.createContext({console, nodes:plain(nodes), canvas:{id:'original-canvas'}, WeakSet, Set, Map,
        activeCanvasVideoPolls:new WeakSet(), nowMs:()=>100, tr:key=>key, render(){}, refreshNodes(){},
        refreshRunNodes(){}, scheduleSave(){}, logs:[],
        resultMediaUrls:result=>Array.isArray(result)?result:(result.videos || []),
        requestMetaFromResult:result=>({task_id:result.task_id}),
        collectRunMeta:()=>({runMs:20}),
        pendingById:(out,id)=>out?._pending?.find(p=>p.id===id),
        appendOutputImages:(out,items)=>out.images.push(...items),
        mergeGeneratedOutputs:(node,items)=>{node.generatedOutputs=[...(node.generatedOutputs || []),...items];},
        cleanHistoryImages:value=>value, copyMediaSizeFields:(_old,value)=>value, stripImageGenerationMeta:value=>value,
        MEDIA_NODE_DEFAULT_SCALE:1,MEDIA_GROUP_PREVIOUS_DEFAULT_SCALE:1,MEDIA_GROUP_DEFAULT_SCALE:1,
        mediaNodeDefaultScale:()=>1, isActive:()=>true,
    });
    ctx.saveCount=0;ctx.scheduleSave=()=>ctx.saveCount++;
    ctx.window=ctx;
    ctx.JimengPendingSignal=class extends Error {constructor(data){super(data.message);Object.assign(this,data,{jimengPending:true});}};
    ctx.setNodeJimengPending=(node,signal)=>{node.jimengPending={submitId:signal.submitId};};
    ctx.addGenerationLog=ctx.addSmartGenerationLog=value=>ctx.logs.push(plain(value));
    ctx.findOutputByPendingId=id=>ctx.nodes.find(node=>node._pending?.some(p=>p.id===id));
    ctx.showErrorModal=ctx.toast=()=>{};
    ctx.fetch=async (url,options={})=>{
        ctx.calls.push({url,method:options.method || 'GET'});
        assert(!['/api/canvas-video-tasks','/api/generate-video'].includes(url),'resume created a task');
        return {ok:true,json:async()=>ctx.reply};
    };
    ctx.calls=[];ctx.reply={status:'succeeded',task_id:'video-one',result:{task_id:'video-one',videos:['/output/one.mp4']}};
    vm.runInContext(read('canvas-task-query.js'),ctx);
    if(kind==='classic') functions(ctx,'canvas.js',['serializableCanvasNode','completeCanvasVideoTask','failCanvasVideoTask',
        'resumeCanvasVideoTask','resumeCanvasImageTasks','queryRecoverPendingOutput']);
    else functions(ctx,'smart-canvas.js',['smartPendingTasks','pendingSmartGenerationLog','clearSmartPendingGenerationLog',
        'recordSmartPendingGenerationLog','finalizeSmartPendingTask','resumeSmartPendingNode','querySmartImageTaskNow']);
    return ctx;
}
function fixture(kind, taskId='video-one') {
    return kind==='classic' ? [
        {id:'generator',type:'video',generatedOutputs:[{url:'/output/old.mp4',kind:'video'}]},
        {id:'output',type:'output',images:[{url:'/output/old.mp4',kind:'video'}],
            _pending:[{id:'pending',canvasTaskId:taskId,canvasTaskType:'video',run:{node:{id:'generator'}}}]},
    ] : [{id:'output',type:'smart-image',images:[{url:'/output/old.mp4',kind:'video'}],
        pendingTasks:[{taskId,kind:'video',taskType:'video'}],pending:1,
        pendingGenerationLog:{run:{nodeId:'output'},outputs:[],startedAt:10}}];
}
async function resume(ctx,kind) {
    if(kind==='classic')await ctx.resumeCanvasVideoTask(ctx.nodes[1],ctx.nodes[1]._pending[0]);
    else await ctx.resumeSmartPendingNode(ctx.nodes[0]);
}
(async()=>{
    for(const kind of ['classic','smart']){
        let ctx=setup(kind,fixture(kind));
        // Serialization destroys object identity, as a newly opened page does.
        const disk=JSON.stringify(kind==='classic'?ctx.nodes.map(ctx.serializableCanvasNode):ctx.nodes);
        ctx=setup(kind,JSON.parse(disk));
        await Promise.all([resume(ctx,kind),resume(ctx,kind)]);
        let output=ctx.nodes.find(node=>node.id==='output');
        assert.deepEqual(plain(output.images).map(item=>item.url),['/output/old.mp4','/output/one.mp4']);
        assert.equal(ctx.logs.length,1,'duplicate completion log');
        assert.equal(kind==='classic'?output._pending.length:(output.pendingTasks || []).length,0);
        // A later accepted run appends without overwriting the prior results.
        const next=fixture(kind,'video-two');
        if(kind==='classic')output._pending=next[1]._pending;
        else {output.pendingTasks=next[0].pendingTasks;output.pendingGenerationLog=next[0].pendingGenerationLog;}
        ctx=setup(kind,plain(ctx.nodes));
        ctx.reply={status:'succeeded',result:{videos:['/output/two.mp4']}};
        await resume(ctx,kind);
        assert.deepEqual(plain(ctx.nodes.find(node=>node.id==='output').images).map(item=>item.url),
            ['/output/old.mp4','/output/one.mp4','/output/two.mp4']);
        assert(ctx.calls.every(call=>call.method==='GET'));
        // Lost query responses retain the original binding and existing query control.
        ctx=setup(kind,fixture(kind));ctx.reply={status:'failed',can_reconcile:true,error:'authentication needs attention'};
        await resume(ctx,kind);
        output=ctx.nodes.find(node=>node.id==='output');
        const task=kind==='classic'?output._pending[0]:output.pendingTasks[0];
        assert(task.failed && task.recoverTaskId==='video-one');
        ctx.reply={status:'succeeded',videos:['/output/recovered.mp4']};
        if(kind==='classic')await ctx.queryRecoverPendingOutput(task.id);
        else await ctx.querySmartImageTaskNow(output.id,task.taskId);
        assert(ctx.calls.some(call=>call.method==='POST' && call.url.endsWith('/reconcile')));
        assert.equal(output.images.at(-1).url,'/output/recovered.mp4');
        assert(ctx.saveCount>0,'manual recovery result was not saved');
        if(kind==='smart'){
            ctx=setup(kind,fixture(kind));
            ctx.reply={status:'jimeng_pending',result:{jimeng_pending:true,submit_id:'cli-original'}};
            await resume(ctx,kind);
            assert.equal(ctx.nodes[0].pendingTasks.length,0);
            assert.equal(ctx.nodes[0].jimengPending.submitId,'cli-original');
            assert.equal(ctx.nodes[0].images.length,1);
        }
        // Manual original-task query also ignores responses after navigation.
        ctx=setup(kind,fixture(kind));
        output=ctx.nodes.find(node=>node.id==='output');
        const originalTask=kind==='classic'?output._pending[0]:output.pendingTasks[0];
        Object.assign(originalTask,{failed:true,recoverTaskId:'video-one'});
        ctx.fetch=async()=>{ctx.canvas={id:'another-canvas'};ctx.nodes=[];return {ok:true,json:async()=>ctx.reply};};
        if(kind==='classic')await ctx.queryRecoverPendingOutput(originalTask.id);
        else await ctx.querySmartImageTaskNow(output.id,originalTask.taskId);
        assert.equal(output.images.length,1);
        assert.equal(ctx.logs.length,0);
        assert.equal(ctx.saveCount,0,'old query saved another canvas');
        // Navigating to another canvas never receives the old result.
        ctx=setup(kind,fixture(kind));
        ctx.fetch=async()=>{ctx.canvas={id:'another-canvas'};return {ok:true,json:async()=>ctx.reply};};
        await resume(ctx,kind);
        assert.equal(ctx.nodes.find(node=>node.id==='output').images.length,1);
        assert.equal(ctx.logs.length,0);
    }
    console.log('both canvases: saved video receipts resume without creation, retain history, deduplicate and respect navigation');
})().catch(error=>{console.error(error);process.exitCode=1;});
