'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..');
const context=vm.createContext({structuredClone,URL,location:{href:'http://127.0.0.1/',origin:'http://127.0.0.1'},fetch:async()=>{throw new Error('unexpected fetch');}});
for(const file of ['comfy-workflow-fields.js','comfy-outputs.js'])vm.runInContext(fs.readFileSync(path.join(root,'static/js',file),'utf8'),context);
const fields=context.ComfyWorkflowFields,outputs=context.ComfyOutputs;
const plain=value=>JSON.parse(JSON.stringify(value));
(async()=>{
    const config={fields:[{id:'a',node:'a',input:'image',type:'image'},{id:'b',node:'b',input:'image',type:'image'},
        {id:'prompt',node:'text',input:'value',role:'prompt',type:'text',default:'old prompt'},
        {id:'system',node:'system',input:'value',role:'system',type:'textarea',default:'keep system'}],
        image_groups:[{id:'group',source_nodes:['a','b'],min_images:1,max_images:10}]};
    assert.equal(fields.runtimeFields(config).filter(f=>fields.kind(f)==='image').length,1);
    const values=await fields.canvasValues(config,{prompt:'connected instruction',media:{image:['A','B','C']},mediaName:async name=>'bound/'+name});
    assert.deepEqual(plain(values.group),['bound/A','bound/B','bound/C']);
    assert.equal(values.prompt,'connected instruction');assert.equal(values.system,'keep system');
    assert.throws(()=>fields.requireMedia(config,{image:[]}),/缺少/);
    assert.throws(()=>fields.requireMedia(config,{image:Array(11).fill('A')}),/最多/);
    const first={url:'/output/first.txt',kind:'text',text:'first\nline',result_id:'run1:save:0',run_id:'run1'};
    const second={url:'/output/second.txt',kind:'text',text:'second',result_id:'run2:save:0',run_id:'run2'};
    const owner={selectedResultId:first.result_id};
    assert.equal(outputs.prompt(owner,[first,second]),'first\nline');
    assert.equal(outputs.prompt({},[first,second]),''); // No implicit switch/concatenation.
    assert.equal(outputs.items({items:[first],texts:[first.url]}).length,1);
    assert.equal(await outputs.text(first),'first\nline');
    assert.match(outputs.card({...first,text:'<img onerror="bad">'}),/&lt;img/);
    assert.equal(outputs.prompt(owner,[first,second,{url:'/output/photo.png',kind:'image'}]),'first\nline');
    owner.selectedResult=first;
    assert.equal(outputs.prompt(owner,[second]),'first\nline');
    assert.throws(()=>outputs.validateSource({},[first,second]),/多条结果/);
    assert.equal(outputs.validateSource(owner,[second]),undefined);
    // Execute the actual canvas source readers rather than reproducing their logic.
    const extract=(file,name)=>{
        const source=fs.readFileSync(path.join(root,'static/js',file),'utf8');
        const start=source.indexOf('function '+name+'(');assert.ok(start>=0);
        const end=source.indexOf('\nfunction ',start+10);
        return source.slice(start,end<0?undefined:end);
    };
    const sourceNode={id:'output',type:'output',images:[first,second],selectedResultId:first.result_id,selectedResult:first};
    const readerContext=vm.createContext({ComfyOutputs:outputs,nodes:[sourceNode],connections:[{from:'output',to:'downstream'}]});
    vm.runInContext(extract('canvas.js','generatorSources'),readerContext);
    assert.equal(readerContext.generatorSources({id:'downstream'})[0].prompt,'first\nline');
    vm.runInContext(extract('canvas.js','outputUrlValue'),readerContext);
    vm.runInContext(extract('canvas.js','appendOutputImages'),readerContext);
    const target={images:[]};readerContext.appendOutputImages(target,[first],null);
    assert.equal(target.images[0].text,first.text);assert.equal(target.images[0].result_id,first.result_id);
    const smartContext=vm.createContext({ComfyOutputs:outputs,canvas:{connections:[{from:'output',to:'downstream',kind:'input'}]},
        nodes:[{...sourceNode,type:'smart-image'}],promptInputNodesFor:()=>[],smartLoopContext:null});
    vm.runInContext(extract('smart-canvas.js','inputPromptTextFor'),smartContext);
    assert.equal(smartContext.inputPromptTextFor({id:'downstream'}),'first\nline');
    smartContext.nodes[0].selectedResultId='';delete smartContext.nodes[0].selectedResult;
    assert.equal(smartContext.inputPromptTextFor({id:'downstream'}),''); // Rendering an unselected group remains safe.
    smartContext.workflowInputNodesFor=()=>smartContext.nodes;
    vm.runInContext(extract('smart-canvas.js','buildPromptRequest'),smartContext);
    assert.throws(()=>smartContext.buildPromptRequest({id:'downstream'}),/多条结果/);
    console.log('variable image groups, prompt roles and pinned typed results passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
