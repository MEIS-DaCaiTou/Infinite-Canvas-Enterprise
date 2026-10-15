'use strict';
// The subject vm has no fs/process/require/network. Rendering and background
// polling are substitutes; save/open, serialization and text readers are real.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const [phase, kind, input, output] = process.argv.slice(2);
const root = path.resolve(__dirname, '../..');
const source = file => fs.readFileSync(path.join(root, 'static/js', file), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));

function loadFunctions(context, file, names) {
    const text = source(file);
    for (const name of names) {
        const match = new RegExp('(?:async )?function ' + name + '\\(').exec(text);
        assert.ok(match, `${file}: missing ${name}`);
        const after = match.index + match[0].length;
        const next = text.slice(after).search(/\n(?:async )?function \w+\(/);
        vm.runInContext(text.slice(match.index, next < 0 ? undefined : after + next), context, {timeout:1000});
    }
}

const workflow = 'custom/fixture-qwen.json';
const parameters = {instruction:'更换服装，保留人物', seed:42, filename_prefix:'result'};
const results = [
    {url:'/output/run-one.txt', name:'第一轮.txt', kind:'text', text:'第一轮提示词\nkeep this selection', result_id:'run-one:save:0', run_id:'run-one'},
    {url:'/output/run-one.png', kind:'image', result_id:'run-one:save:1', run_id:'run-one'},
    {url:'/output/run-two.txt', name:'第二轮.txt', kind:'text', text:'第二轮提示词', result_id:'run-two:save:0', run_id:'run-two'},
    {url:'/output/run-two.mp4', kind:'video', result_id:'run-two:save:1', run_id:'run-two'},
];

function fixture(canvas) {
    const smart = kind === 'smart';
    return {...canvas,
        nodes:[
            {id:'result', type:smart?'smart-image':'output', images:plain(results), selectedResultId:results[0].result_id, selectedResult:plain(results[0]), x:20, y:30},
            {id:'next', type:smart?'smart-image':'comfy', mode:'custom', comfyWorkflow:workflow, comfyParams:plain(parameters),
                runSettings:{engine:'comfy', comfyWorkflow:workflow, comfyParams:plain(parameters)}, images:[], x:420, y:30},
        ],
        connections:[{from:'result', to:'next', ...(smart?{kind:'input'}:{})}],
        viewport:{x:12, y:24, scale:0.75},
        logs:[{id:'log-one', status:'success', nodeId:'result', outputs:[results[0].url, results[1].url], createdAt:1000},
              {id:'log-two', status:'success', nodeId:'result', outputs:[results[2].url, results[3].url], createdAt:2000}],
        settings:{engine:'comfy', comfyWorkflow:workflow, comfyParams:plain(parameters)},
    };
}

function contextFor(data) {
    const context = vm.createContext({
        URL, structuredClone, console,
        location:{href:'http://fixture/', origin:'http://fixture'},
        canvas:plain(data), nodes:plain(data.nodes || []), connections:plain(data.connections || []),
        canvasId:data.id, viewport:plain(data.viewport || {}), settings:{},
        initialSmartSettings:data.settings || {}, canvasDefaultSmartSettings:data.settings || {},
        CLIENT_ID:'persistence-fixture', smartClientId:'persistence-fixture',
        applyingRemoteCanvas:false, savingCanvasNow:false, saveCanvasAgain:false,
        localCanvasDirty:true, lastCanvasUpdatedAt:data.updated_at, currentCanvasTime:null,
        selected:new Set(), saveTimer:null, canvasSyncInFlight:false, smartLoopContext:null,
        comfyWorkflows:[{name:workflow}], comfyWorkflowCache:{},
        smartNodeRunTokens:new Map(), nowMs:()=>3000, safeScale:value=>value,
        tr:key=>key, setStatus:value=>context.status=value,
        toast:message=>{throw new Error(message);},
        document:{getElementById:()=>({textContent:''})},
        setTimeout:()=>{throw new Error('unexpected save retry');}, clearTimeout:()=>{},
        fetch:async()=>{throw new Error('unexpected HTTP request');},
    });
    context.window=context;
    context.location.replace=()=>{throw new Error('unexpected navigation after failed reopen');};
    // UI-only refreshes, device-local viewport lookup and background task polling
    // are outside this persistence contract. No generation function is supplied.
    for (const name of ['loadCanvasList', 'rememberCanvasListProject', 'resetCascadeRuntimeState',
        'setCanvasMode', 'renderCanvasList', 'render', 'resumeCanvasImageTasks', 'startCanvasRemotePolling',
        'savePromptDraftForCurrent', 'updateProviderModels', 'applyViewport', 'loadRecentSmartSettings',
        'resumeSmartPendingTasks', 'resumeJimengPendingNodes', 'startCanvasMetaPoll']) context[name]=()=>{};
    context.localViewportForCanvas=(_id, value)=>value;
    context.touchCanvasOpened=async()=>null;
    context.refreshMissingCanvasAssets=async()=>{};
    for (const name of ['migrateSmartGroupImageMembers', 'clearCompletedNodeBusyStates',
        'recoverStuckLoopOutputsFromLogs', 'hideCompletedRunTimers', 'cleanupDetachedRunInputRefs']) context[name]=()=>false;
    vm.runInContext(source('comfy-outputs.js'), context, {timeout:1000});
    if (kind === 'classic') {
        const text=source('canvas.js');
        for (const name of ['CANVAS_GENERATOR_TYPES', 'CANVAS_MEDIA_OUTPUT_TYPES']) {
            const declaration=text.match(new RegExp('^const ' + name + ' = .+;$','m'));
            assert.ok(declaration, name); vm.runInContext(declaration[0], context);
        }
        loadFunctions(context, 'canvas.js', ['serializableCanvasNode', 'serializableCanvasNodes', 'saveCanvas',
            'openCanvas', 'resetTransientRunState', 'canConnect', 'sanitizeConnections',
            'hasComfyWorkflow', 'pruneMissingComfyWorkflows', 'generatorSources']);
    } else {
        const declaration=source('smart-canvas.js').match(/^const SMART_LOG_PREVIEW_NODE_ID = .+;$/m);
        assert.ok(declaration); vm.runInContext(declaration[0], context);
        loadFunctions(context, 'smart-canvas.js', ['cloneSmartSettings', 'settingsForStorage', 'mediaItemForStorage',
            'stripImageGenerationMeta', 'smartGenerationLogKey', 'normalizeSmartGenerationLogs', 'canvasForStorage',
            'normalizeLegacySmartNode', 'normalizeSmartVideoModeSettings', 'smartPendingTasks',
            'smartNodeHasDisplayResult', 'clearSmartNodeBusyState', 'markSmartNodeComplete',
            'saveCanvas', 'loadCanvas', 'inputPromptTextFor']);
        context.promptInputNodesFor=()=>[];
    }
    return context;
}

async function main() {
    assert.ok(['classic','smart'].includes(kind));
    const response=JSON.parse(fs.readFileSync(input,'utf8'));
    if (phase === 'save') {
        const data=fixture(response.canvas), context=contextFor(data);
        let request, calls=0;
        context.fetch=async (url, options)=>{
            calls++;
            assert.equal(url, '/api/canvases/'+data.id);
            assert.equal(options.method, 'PUT');
            request=JSON.parse(options.body);
            return {ok:true, status:200, json:async()=>({canvas:{...data, updated_at:data.updated_at+1}})};
        };
        await context.saveCanvas();
        assert.equal(calls,1);
        assert.equal(request.title,data.title);
        assert.equal(request.icon,data.icon);
        assert.deepEqual(request.nodes.map(node=>node.id),data.nodes.map(node=>node.id));
        assert.deepEqual(request.nodes[0],data.nodes[0]);
        assert.deepEqual(request.nodes[1].comfyParams,parameters);
        assert.deepEqual(request.nodes[1].runSettings.comfyParams,parameters);
        assert.deepEqual(request.connections, data.connections);
        assert.deepEqual(request.logs, data.logs);
        assert.equal(request.base_updated_at, data.updated_at);
        fs.writeFileSync(output, JSON.stringify(request));
    } else {
        assert.equal(phase,'reopen');
        // A brand-new vm starts with no nodes, selected outputs or cached text.
        const context=contextFor({...response.canvas, nodes:[], connections:[]});
        let calls=0;
        context.fetch=async (url, options)=>{
            calls++; assert.equal(url, '/api/canvases/'+response.canvas.id);
            assert.equal(options,undefined);
            return {ok:true, json:async()=>plain(response)};
        };
        if (kind === 'classic') await context.openCanvas(response.canvas.id);
        else await context.loadCanvas();
        assert.equal(calls,1);
        const outputNode=context.nodes.find(node=>node.id==='result');
        const generator=context.nodes.find(node=>node.id==='next');
        assert.deepEqual(plain(outputNode.images), results, 'all runs and media kinds survive');
        assert.equal(outputNode.selectedResultId, results[0].result_id, 'a later run does not replace the pinned prompt');
        assert.deepEqual(plain(outputNode.selectedResult), results[0]);
        assert.equal(generator.comfyWorkflow,workflow);
        assert.deepEqual(plain(generator.comfyParams),parameters);
        assert.deepEqual(plain(context.canvas.logs),fixture(response.canvas).logs);
        const connections=kind==='classic'?context.connections:context.canvas.connections;
        assert.deepEqual(plain(connections),fixture(response.canvas).connections);
        context.ComfyOutputs.validateSource(outputNode,outputNode.images);
        const downstreamPrompt=kind==='classic'
            ?context.generatorSources(generator)[0].prompt
            :context.inputPromptTextFor(generator);
        assert.equal(downstreamPrompt,results[0].text, 'saved text is reusable without another download or generation');
        fs.writeFileSync(output,JSON.stringify({kind,reopened:true}));
    }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
