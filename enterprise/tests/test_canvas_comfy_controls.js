const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const calls=[],timers=[],cards=[],ended=[];
let panelState=null;
class Element{
    constructor(){this.children=[];this.dataset={};this.attrs={};this.isConnected=true;}
    append(...items){items.forEach(item=>{item.parent=this;this.children.push(item);});}
    replaceChildren(){this.children=[];}
    setAttribute(key,value){this.attrs[key]=value;}
    querySelector(selector){return this.children.find(child=>selector==='button'?child.type==='button':child.className===selector.slice(1)) || null;}
    remove(){this.isConnected=false;if(this.parent)this.parent.children=this.parent.children.filter(child=>child!==this);}
    focus(){this.onfocus?.();}
    set innerHTML(_){throw Error('Task details must use textContent for user content');}
}
const context={document:{documentElement:{lang:'zh'},createElement:()=>new Element(),body:new Element(),querySelectorAll:()=>cards},
    StudioDropdowns:{openPanel(panel,anchor,onClose){panelState={panel,anchor,onClose};},closePanel(panel){if(panelState?.panel===panel){const prior=panelState;panelState=null;prior.onClose();}}},
    setTimeout:fn=>(timers.push(fn),timers.length),clearTimeout(){},Date,Map,Set,WeakMap,Promise};
vm.runInNewContext(fs.readFileSync('static/js/canvas-comfy-tasks.js','utf8'),context);
const jobs=['a','b'].map((key,index)=>({id:'job-'+key,status:'running',phase:index?'queued':'running',can_cancel:true,created_at:1+index,source:{canvas_id:'canvas',node_id:'same-node'}}));
const entries=jobs.map(task=>({id:'pending-'+task.id,canvasTaskId:task.id,canvasTaskType:'comfy',startedAt:task.created_at*1000,
    run:{nodeType:'comfy',node:{id:'same-node'},prompt:'<img onerror=bad()> editable input',taskLabel:'workflow',refs:[{url:'input.png'}]}}));
const controls=context.CanvasComfyTasks.create({onChange(){},hasPending:id=>entries.some(entry=>entry.canvasTaskId===id&&!entry.canvasTaskStatus),
    onTerminal:task=>{ended.push(task.id);context.CanvasComfyTasks.settle(entries.find(entry=>entry.canvasTaskId===task.id),task);},
    fetcher:async(url,options)=>{
        calls.push([options.method||'GET',url]);
        const task=jobs.find(task=>url.includes(task.id));
        const data=url.includes('?canvas_id=')?{items:jobs}:options.method==='POST'?{task:{...task,cancellation:{acknowledged:true}}}:task;
        return {ok:true,json:async()=>data};
    }});
const event=()=>({preventDefault(){this.prevented=true;},stopPropagation(){this.stopped=true;}});
(async()=>{
    await controls.load('canvas');
    entries.forEach(entry=>{const card=new Element();cards.push(card);controls.bindOutput(card,()=>entry);});
    assert.equal(cards[0].querySelector('.comfy-output-status').textContent,'运行中');
    assert.equal(cards[1].querySelector('.comfy-output-status').textContent,'后端排队');
    // Shared source nodes still have distinct output task identities.
    cards[1].onmouseenter();timers.at(-1)();
    assert.equal(panelState.anchor,cards[1]);assert.equal(panelState.panel.attrs.role,'tooltip');
    const rightClick=event();cards[1].oncontextmenu(rightClick);
    assert(rightClick.prevented&&rightClick.stopped);assert.equal(panelState.panel.attrs.role,'menu');
    assert.equal(panelState.anchor,cards[1]);assert.equal(panelState.panel.querySelector('button').textContent,'取消该任务');
    assert(panelState.panel.children.some(child=>child.textContent===entries[1].run.prompt));
    await panelState.panel.querySelector('button').onclick();
    assert.equal(ended.length,0,'POST acknowledgement is not terminal cancellation');
    assert.equal(cards[1].querySelector('.comfy-output-status').textContent,'取消中');
    assert.equal(cards[0].querySelector('.comfy-output-status').textContent,'运行中');
    jobs[1]={...jobs[1],status:'cancelled',phase:'cancelled',can_cancel:false};controls.record(jobs[1]);
    assert.deepEqual(ended,['job-b']);assert.equal(controls.active('same-node').length,1);
    assert.equal(cards[1].querySelector('.comfy-output-status').textContent,'已取消');
    const restored=JSON.parse(JSON.stringify(entries[1]));assert.equal(context.CanvasComfyTasks.outputInfo(restored).status,'cancelled');
    cards[1].oncontextmenu(event());assert.equal(panelState.panel.querySelector('button').disabled,true);
    panelState.panel.onkeydown({...event(),key:'Escape'});assert.equal(panelState,null);
    assert.deepEqual(calls.filter(call=>call[0]==='POST'),[['POST','/enterprise/api/me/comfy-tasks/job-b/cancel']]);
    assert(!calls.some(([,url])=>url.includes('/prompt')||url.includes('/interrupt')));
    const result=context.CanvasComfyTasks.outputInfo({url:'result.png',run:{nodeType:'comfy',canvasTaskId:'completed',taskLabel:'workflow',prompt:'saved prompt'}});
    assert.equal(result.status,'succeeded');assert.equal(result.canCancel,false);assert.equal(result.id,'completed');
    assert.equal(context.CanvasComfyTasks.outputInfo({canvasTaskType:'video'}),null);
    const uncertain=context.CanvasComfyTasks.outputInfo(entries[0],{...jobs[0],status:'failed',recovery_required:true});
    assert.equal(uncertain.phase,'unknown');assert.equal(uncertain.canCancel,true);
    const source=fs.readFileSync('static/js/canvas.js','utf8');
    const start=source.indexOf('function renderPendingOutput('),end=source.indexOf('\nfunction ',start+1);
    Object.assign(context,{langIsEn:()=>false,escapeAttr:value=>value,tr:key=>key,pendingOutputStyle:()=>''});
    vm.runInNewContext(source.slice(start,end),context);
    const html=context.renderPendingOutput(restored);assert(html.includes('已取消'));assert(!html.includes('output-spinner'));
    // Real completion/persistence code carries the same task ID onto output media.
    const findFunction=name=>{const start=source.indexOf('function '+name+'(');const end=source.indexOf('\nfunction ',start+1);return source.slice(start,end);};
    const pending={...entries[0],run:{...entries[0].run}},out={_pending:[pending]},generator={id:'same-node'};let appended;
    Object.assign(context,{nodes:[generator],findPendingTask:()=>({out,pending}),requestMetaFromResult:()=>({}),nowMs:()=>Date.now(),
        appendOutputImages:(_out,_images,_reference,metas)=>appended=metas[0],mergeGeneratedOutputs(){},addGenerationLog(){},refreshRunNodes(){},scheduleSave(){}});
    vm.runInNewContext(findFunction('completeCanvasImageTask'),context);
    context.completeCanvasImageTask('job-a',{images:['/output/result.png']});
    assert.equal(appended.run.canvasTaskId,'job-a');assert.equal(appended.run.canvasTaskStatus,'succeeded');assert.equal(out._pending.length,0);
    controls.track({task_id:'stage-one',status:'queued'},'same-node','stage-scope');
    controls.record({id:'stage-one',status:'succeeded',source:{canvas_id:'canvas',node_id:'same-node'}});
    assert(controls.locallyWaiting('same-node'),'a local multi-stage run stays busy after its first stage');
    controls.track({task_id:'stage-two',status:'queued'},'same-node','stage-scope');
    controls.releasePending('different-scope');assert(controls.locallyWaiting('same-node'));
    controls.releasePending('stage-scope');assert(!controls.locallyWaiting('same-node'));
    const stageCalls=[],released=[],stageOut={_pending:[]},stageNode={id:'enhance',type:'comfy',mode:'enhance',enhanceUpscale:true};let finalImages;
    const chain={CLIENT_ID:'fixture',nodes:[stageNode],checkTextSelection:()=>true,cascadeTargetIdFromOptions:()=>'',orderedSources:(_node,values)=>values,
        generatorSources:()=>[{refs:[{url:'subject.png'}]}],imageRefsOnly:values=>values,outputForNode:()=>stageOut,uid:()=> 'stage-card',
        runSnapshot:()=>({nodeType:'comfy',node:{id:'enhance'}}),comfyRunLabel:()=> 'enhance',makePendingForRun:(id,run)=>({id,run}),
        refreshRunNodes(){},tr:key=>key,comfyNameForRef:async()=> 'subject.png',uploadCanvasUrlToComfy:async()=> 'enhanced.png',
        runQueuedComfyGenerate:async(payload,options)=>{stageCalls.push({payload,options});return {images:[payload.workflow_json==='upscale.json'?'upscaled.png':'enhanced.png']};},
        requestMetaFromResult:()=>({}),collectRunMeta:()=>({run:stageOut._pending[0].run,runMs:1}),nowMs:()=>Date.now(),
        appendOutputImages:(_out,images)=>finalImages=images,mergeGeneratedOutputs(){},addGenerationLog(){},scheduleSave(){},
        comfyTaskControls:{releasePending:id=>released.push(id),active:()=>[]}};
    const asyncFunction=name=>{const start=source.indexOf('async function '+name+'('),next=source.slice(start+1).search(/\n(?:async )?function /);return source.slice(start,next<0?undefined:start+1+next);};
    vm.runInNewContext(asyncFunction('runComfyUpscale')+'\n'+asyncFunction('runComfyNode'),chain);
    await chain.runComfyNode('enhance',{cascade:true});
    assert.deepEqual(stageCalls.map(call=>call.payload.workflow_json),['Z-Image-Enhance.json','upscale.json']);
    assert(stageCalls.every(call=>call.options.sourceNode===stageNode&&call.options.pendingId==='stage-card'));
    assert.deepEqual(released,['stage-card']);assert.equal(finalImages[0],'upscaled.png');
    // Queue refusal of a later stage retains the completed first stage and its identity.
    stageOut._pending=[];let retained;
    chain.pendingById=()=>stageOut._pending[0];
    chain.comfyResultOutputs=result=>result.images;
    chain.completeCanvasImageTask=(id,result)=>retained={id,result};
    chain.comfyTaskControls.get=()=>({id:'completed-first',status:'succeeded',result:{images:['enhanced.png']}});
    chain.runQueuedComfyGenerate=async(payload)=>{
        if(payload.workflow_json==='upscale.json')throw Object.assign(new Error('queue limit'),{code:'COMFY_QUEUE_LIMIT'});
        stageOut._pending[0].canvasTaskId='completed-first';return {images:['enhanced.png']};
    };
    await assert.rejects(()=>chain.runComfyNode('enhance',{cascade:true}),error=>error.code==='COMFY_QUEUE_LIMIT');
    assert.equal(retained.id,'completed-first');assert.equal(retained.result.images[0],'enhanced.png');
    // A finished summary contains no result bytes. Both restoration reads may fail once.
    for(const failedRead of ['list','receipt']){
        const retries=[],reads=[];let pending=true,applied=0,unavailable=true;
        const task={id:'restored-result',status:'succeeded',source:{canvas_id:'restored',node_id:'comfy'}};
        const restoredContext={document:{documentElement:{lang:'zh'},querySelectorAll:()=>[]},
            setTimeout:fn=>(retries.push(fn),retries.length),clearTimeout(){},Date,Map,Set,WeakMap,Promise};
        vm.runInNewContext(fs.readFileSync('static/js/canvas-comfy-tasks.js','utf8'),restoredContext);
        const restoredControls=restoredContext.CanvasComfyTasks.create({onChange(){},hasPending:()=>pending,
            onTerminal:value=>{assert.equal(value.result.images[0],'/output/restored.png');pending=false;applied++;},
            fetcher:async url=>{
                if(url==='/enterprise/api/me/comfy-queue')return {ok:true,json:async()=>({})};
                const kind=url.includes('?canvas_id=')?'list':'receipt';reads.push(kind);
                if(unavailable&&kind===failedRead){unavailable=false;return {ok:false,json:async()=>({detail:'temporary 503'})};}
                return {ok:true,json:async()=>kind==='list'?{items:[task]}:{...task,result:{images:['/output/restored.png']}}};
            }});
        await restoredControls.load('restored');
        assert.equal(applied,0);assert.equal(retries.length,1,failedRead+' failure schedules original-receipt recovery');
        await retries.shift()();
        assert.equal(applied,1);assert.equal(pending,false);assert.equal(retries.length,0,'settled output stops polling');
        assert.equal(reads.filter(kind=>kind===failedRead).length,2);
    }
    const staleRetries=[],listed=[];
    const staleContext={document:{documentElement:{lang:'zh'},querySelectorAll:()=>[]},
        setTimeout:fn=>(staleRetries.push(fn),staleRetries.length),clearTimeout(){},Date,Map,Set,WeakMap,Promise};
    vm.runInNewContext(fs.readFileSync('static/js/canvas-comfy-tasks.js','utf8'),staleContext);
    const staleControls=staleContext.CanvasComfyTasks.create({onChange(){},hasPending:()=>false,onTerminal(){},fetcher:async url=>{
        if(url==='/enterprise/api/me/comfy-queue')return {ok:true,json:async()=>({})};
        listed.push(url);return {ok:!url.endsWith('old'),json:async()=>({items:[],detail:'temporary 503'})};
    }});
    await staleControls.load('old');const staleRetry=staleRetries.shift();
    await staleControls.load('new');await staleRetry();
    assert.equal(listed.length,2,'a delayed retry cannot reopen the previous canvas');
    console.log('Output task controls passed, including list/receipt outage recovery and stale-canvas isolation.');
})().catch(error=>{console.error(error);process.exitCode=1});
