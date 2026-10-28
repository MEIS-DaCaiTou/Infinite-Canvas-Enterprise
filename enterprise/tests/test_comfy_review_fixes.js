'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const root=path.resolve(__dirname,'../..');
const source=file=>fs.readFileSync(path.join(root,'static/js',file),'utf8');
function fn(file,name){
    const text=source(file),match=new RegExp('(?:async )?function '+name+'\\(').exec(text);assert.ok(match,name);
    const start=match.index,next=text.slice(start+match[0].length).search(/\n(?:async )?function \w+\(/);
    return text.slice(start,next<0?undefined:start+match[0].length+next);
}
function setup(extra={}){
    const ctx=vm.createContext({URL,Uint8Array,structuredClone,location:{href:'http://192.0.2.1/',origin:'http://192.0.2.1'},...extra});
    for(const file of ['comfy-workflow-fields.js','comfy-outputs.js','comfy-workflow-session.js'])vm.runInContext(source(file),ctx);
    return ctx;
}
(async()=>{
    let posts=0,body;
    const http=setup({crypto:{getRandomValues:require('node:crypto').webcrypto.getRandomValues.bind(require('node:crypto').webcrypto)},
        selectedName:'custom/test.json',currentWorkflow:{},currentConfig:{fields:[]},sessionStorage:{setItem(){},removeItem(){}},
        refreshTestViews(){},currentLang:()=> 'zh',applyActiveRandomValues:values=>values,tr:key=>key,
        fetch:async(url,options)=>{posts++;body=JSON.parse(options.body);return {ok:true,json:async()=>({task_id:'canvas_comfy_'+body.request_id})};}});
    http.testSession=new http.ComfyWorkflowSession();http.pollTestTask=async()=>({status:'succeeded',result:{images:[]}});
    for(const name of ['testStorageKey','onRun'])vm.runInContext(fn('comfyui-settings.js',name),http);
    await http.onRun();assert.equal(posts,1);assert.equal(http.testSession.error,'');
    assert.match(body.request_id,/^[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}$/);
    assert.notEqual(http.ComfyWorkflowSession.requestId(),body.request_id);
    const item={url:'/assets/output/prompt.txt',kind:'text',text:'pinned upstream instruction',result_id:'run-1:save:0'};
    const node={id:'source',type:'output',images:[item],selectedResultId:item.result_id,selectedResult:item};
    const classic=setup({nodes:[node],connections:[{from:'source',to:'llm'}]});
    for(const name of ['llmInputText','llmInputImages','llmInputVideos'])vm.runInContext(fn('canvas.js',name),classic);
    assert.equal(classic.llmInputText({id:'llm'}),item.text);
    assert.equal(classic.llmInputImages({id:'llm'}).length,0);assert.equal(classic.llmInputVideos({id:'llm'}).length,0);
    node.type='comfy';node.generatedOutputs=node.images;delete node.images;
    assert.equal(classic.llmInputText({id:'llm'}),item.text);
    const smart=setup({nodes:[{...node,type:'smart-image',images:[item]}],smartLoopContext:null,inputNodesFor:()=>smart.nodes});
    for(const name of ['promptNodePromptItems','promptTextItemsForNode','promptNodeUpstreamPromptItems','promptNodeUpstreamPromptText','promptNodeLLMInputText'])vm.runInContext(fn('smart-canvas.js',name),smart);
    assert.equal(smart.promptNodeLLMInputText({id:'llm',type:'smart-prompt',llmInstruction:'rewrite this'}),item.text+'\n\nrewrite this');
    let warning='';smart.nodes=[{id:'llm',type:'smart-prompt'}];smart.validateSmartTextInputs=()=>{throw Error('选择上游文本');};smart.toast=text=>warning=text;
    vm.runInContext(fn('smart-canvas.js','runPromptLLMNode'),smart);await smart.runPromptLLMNode('llm');assert.equal(warning,'选择上游文本');
    const group=setup({currentConfig:{backend:'http://a:8188',fields:[{id:'a',node:'a',input:'image',type:'image',default:'admin-old.png'}],
        image_groups:[{id:'images:a',source_nodes:['a'],min_images:1,max_images:10}]},refreshTestViews(){},refreshWorkflowDefinitions(){},setStatus(){}});
    group.isMediaField=field=>['image','video','audio','file'].includes(group.ComfyWorkflowFields.kind(field));
    group.testSession=new group.ComfyWorkflowSession();group.testSession.values['images:a']=['old-backend.png'];group.testSession.urls['images:a']=['blob:old'];
    vm.runInContext(fn('comfyui-settings.js','changeWorkflowBackend'),group);group.changeWorkflowBackend('http://b:8188');
    assert.equal(group.testSession.values['images:a'].length,0);assert.equal(group.testSession.urls['images:a'],undefined);
    const values=await group.ComfyWorkflowFields.canvasValues(group.currentConfig,{media:{image:['own.png']},mediaName:async x=>x});
    assert.equal(Object.keys(group.ComfyWorkflowFields.paramsFromValues(group.currentConfig,values)).length,0);
    const editor=setup({currentWorkflow:{node:{inputs:{flag:false,cfg:0.65}}},
        currentConfig:{fields:[{id:'flag',node:'node',input:'flag',type:'boolean',default:false},
            {id:'cfg',node:'node',input:'cfg',type:'number',value_type:'number',default:0.65}]},
        testSession:{revision:0},previewValues:{flag:false,cfg:0.65},previewRandomActive:{},
        popupNodeId:null,workspaceMode:'graph',renderEditor(){},renderPreview(){},refreshPopupBody(){}});
    vm.runInContext(fn('comfyui-settings.js','updateField'),editor);
    editor.updateField('flag','default',true);
    assert.equal(editor.currentConfig.fields[0].default,true);
    assert.equal(editor.previewValues.flag,true,'edited boolean defaults take effect in the current preview');
    editor.updateField('cfg','type','slider');
    assert.equal(editor.previewValues.cfg,0.65,'changing widget type retains the actual value');
    console.log('HTTP LAN identity, both LLM text readers, ambiguity, group reset and old defaults passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
