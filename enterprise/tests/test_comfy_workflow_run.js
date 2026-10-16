'use strict';
// Review-owned, deterministic fixture. The subject VM receives no fs, process, require or network APIs.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const checkout = path.resolve(__dirname, '../..');
const utilitySource = fs.readFileSync(path.join(checkout, 'static/js/comfy-workflow-fields.js'), 'utf8');
const utilityContext = vm.createContext({});
vm.runInContext(utilitySource, utilityContext, {timeout:1000});
const fields = utilityContext.ComfyWorkflowFields;
const plain = value => JSON.parse(JSON.stringify(value));

async function runRace(scenario='race'){
    const source = fs.readFileSync(path.join(checkout, 'static/js/canvas.js'), 'utf8');
    const start = source.indexOf('async function runComfyNode(');
    const end = source.indexOf('async function callCanvasLLM(', start);
    assert.ok(start > 0 && end > start);
    let release, fail;
    const workflowReady = new Promise((resolve,reject) => { release = resolve; fail = reject; });
    const config = {fields:[{id:'image',node:'8',input:'image',type:'image',default:'sample.png'}, {id:'prompt',node:'1',input:'text',type:'textarea',default:'default'}]};
    const node = {id:'node', type:'comfy', mode:'custom', comfyWorkflow:'custom/review.json', comfyParams:{}};
    const out = {id:'out', _pending:[]};
    let submissions = 0, uploads = 0, pendingSeq = 0;
    const alerts = [];
    const context = vm.createContext({
        checkTextSelection:()=>true, nodes:[node], comfyWorkflows:[{name:'custom/review.json'}], CLIENT_ID:'review', ComfyWorkflowFields:fields,
        cascadeTargetIdFromOptions:()=>'', orderedSources:(_node,sources)=>sources,
        generatorSources:()=>[{prompt:'connected prompt',refs:[{url:'synthetic.png'}]}],
        imageRefsOnly:refs=>refs, videoRefsOnly:()=>[], audioRefsOnly:()=>[],
        validComfyWorkflowName:name=>name, hasComfyWorkflow:()=>true, ensureComfyWorkflow:()=>workflowReady,
        comfyFields:(_node,kind)=>config.fields.filter(f=>kind === undefined || fields.kind(f) === kind),
        comfyFieldKind:fields.kind,
        comfyRandomEnabled:()=>false, comfyRandomActive:()=>false,
        comfyParamValue:(_node,f)=>f.default,
        comfyNameForRef:async()=>{ uploads++; return 'uploaded.png'; },
        langIsEn:()=>false, alert:message=>alerts.push(message), tr:key=>key,
        outputForNode:()=>out, uid:()=> 'pending-' + ++pendingSeq,
        runSnapshot:()=>({}), comfyRunLabel:()=> 'review', makePendingForRun:id=>({id}),
        refreshRunNodes:()=>{}, setTimeout:()=>0,
        runQueuedComfyGenerate:async()=>{ submissions++; return {images:[{url:'review-output.png'}]}; },
        requestMetaFromResult:()=>({}), comfyResultOutputs:result=>result.images,
        collectRunMeta:()=>({runMs:0}), appendOutputImages:()=>{}, mergeGeneratedOutputs:()=>{},
        addGenerationLog:()=>{}, scheduleSave:()=>{}, isCascadeAbortError:()=>false,
        actionFailed:(_key,msg)=>msg || 'failed', noReturnedImage:()=> 'empty'
    });
    vm.runInContext(source.slice(start,end), context, {timeout:1000});
    const first = context.runComfyNode('node', {cascade:scenario === 'workflow-failure'});
    const second = scenario === 'race' ? context.runComfyNode('node') : Promise.resolve();
    const runningBeforeWorkflowReady = !!node.running;
    if(scenario === 'race') release({config});
    else fail(new Error('workflow unavailable'));
    const settled = await Promise.allSettled([first,second]);
    return {submissions,uploads,runningBeforeWorkflowReady,alerts,runStatus:node.runStatus || '',firstCompletion:settled[0].status,runningAfterCompletion:!!node.running};
}

function retiredWorkflowKeepsIdentityWithoutRenderLoop(){
    const source = fs.readFileSync(path.join(checkout, 'static/js/canvas.js'), 'utf8');
    const names = ['comfyWorkflowOptions','hasComfyWorkflow','validComfyWorkflowName','pruneMissingComfyWorkflows','currentComfyWorkflow','renderComfySettings'];
    const functions = names.map(name => {
        const start = source.indexOf(`function ${name}(`);
        const next = source.slice(start+1).search(/\n(?:async )?function /);
        return source.slice(start, start+1+next);
    }).join('\n');
    const node = {id:'old',type:'comfy',mode:'custom',comfyWorkflow:'custom/retired.json'};
    let lookups = 0, renders = 0, saves = 0;
    const container = {innerHTML:'',querySelectorAll:()=>[]};
    const context = vm.createContext({nodes:[node],comfyWorkflows:[{name:'custom/current.json',title:'Available'}],comfyWorkflowCache:{},
        escapeHtml:value=>value,tr:key=>key,comfyFieldKind:()=>'',scheduleSave:()=>{saves++;},
        ensureComfyWorkflow:async()=>{lookups++;return null;},render:()=>{renders++;}});
    vm.runInContext(functions,context,{timeout:1000});
    context.pruneMissingComfyWorkflows();
    context.renderComfySettings(container,node);
    assert.equal(node.comfyWorkflow,'custom/retired.json');
    assert.equal(context.validComfyWorkflowName(node.comfyWorkflow),'custom/retired.json');
    assert.ok(container.innerHTML.includes('selected disabled'));
    assert.ok(container.innerHTML.includes('已停用或移除'));
    assert.equal(lookups,0,'unavailable workflow must not create a repeated resolve-render loop');
    assert.equal(renders,0);
    assert.equal(saves,0,'loading a retired selection must not rewrite the saved workflow');
}

(async()=>{
    retiredWorkflowKeepsIdentityWithoutRenderLoop();
    const race = await runRace();
    assert.equal(race.submissions, 1, 'a second click during lookup must not submit');
    assert.equal(race.uploads, 1);
    assert.equal(race.runningBeforeWorkflowReady, true);
    assert.deepEqual(race.alerts, []);
    const cascadeFailure = await runRace('workflow-failure');
    assert.equal(cascadeFailure.firstCompletion, 'rejected');
    assert.equal(cascadeFailure.runStatus, 'failed');
    assert.equal(cascadeFailure.submissions, 0);
    assert.deepEqual(cascadeFailure.alerts, []);
    const manualFailure = await runRace('manual-failure');
    assert.equal(manualFailure.firstCompletion, 'fulfilled');
    assert.equal(manualFailure.submissions, 0);
    assert.equal(manualFailure.runningAfterCompletion, false);
    assert.equal(manualFailure.runStatus, 'failed');
    assert.deepEqual(manualFailure.alerts, ['workflow unavailable']);
    console.log('Comfy cold lookup blocks duplicate clicks and propagates cascade failures');
})().catch(error=>{console.error(error);process.exitCode=1;});
