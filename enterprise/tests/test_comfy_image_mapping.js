'use strict';
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const ctx=vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../../static/js/comfy-workflow-fields.js'),'utf8'),ctx);
const api=ctx.ComfyWorkflowFields,plain=v=>JSON.parse(JSON.stringify(v));
// API-format graph with expanded subgraph IDs, as used by MiniMax H3.
const graph={
    '114':{class_type:'LoadImage',inputs:{image:'template.png'}},
    '127':{class_type:'LoadImage',inputs:{image:'template.png'}},
    '115':{class_type:'ResolutionSelector',inputs:{aspect_ratio:'1:1 (Square)',megapixels:0.4,multiple:32}},
    '105:104':{class_type:'MiniMaxH3ImageToVideo',inputs:{prompt:'template prompt',first_frame:['114',0],last_frame:['127',0],width:['115',0],height:['115',1]}},
    '92':{class_type:'SaveVideo',inputs:{video:['105:104',0],filename_prefix:'video/test'}},
};
const original=JSON.stringify(graph);
const prompt={id:'prompt',node:'105:104',input:'prompt',role:'prompt',type:'textarea'};
const config={fields:[prompt]};
(async()=>{
    assert.deepEqual(plain(api.imageInputCandidates(graph)).map(c=>[c.node,c.name]),[['114','首帧图片'],['127','尾帧图片']]);
    assert.match(api.imageMappingSummary(graph,config),/仍使用模板图片/);
    let uploads=0;
    const args={prompt:'user prompt',workflow:graph,media:{image:['fabric.png']},mediaName:async ref=>{uploads++;return 'uploaded/'+ref}};
    await assert.rejects(api.canvasValues(config,args),/尾帧图片/);assert.equal(uploads,0);
    const repaired=api.normalizeWorkflow({workflow:graph,config:{fields:[prompt,{id:'old',node:'114',input:'image',type:'image',default:'template.png'}]}}).config;
    const duration=api.normalizeWorkflow({workflow:{duration:{class_type:'PrimitiveFloat',inputs:{value:5}}},config:{fields:[{id:'duration',node:'duration',input:'value',type:'slider',default:.1}]}}).config.fields[0];
    assert.equal(api.coerceValue(duration,.1),.1,'integer-looking JSON literals do not make a Float duration integer-only');
    assert.equal(repaired.fields.find(f=>f.node==='127').id,'ice_frame:127');
    assert.equal(repaired.fields.find(f=>f.node==='114').default,'');
    assert.equal(api.imageMappingSummary(graph,repaired,false,'first'),'首帧图片：图片 1；尾帧：未启用');
    assert.equal(api.imageMappingSummary(graph,repaired,false,'last'),'首帧：未启用；尾帧图片：图片 1');
    assert.equal(api.imageMappingSummary(graph,repaired,false,'both'),'首帧图片：图片 1；尾帧图片：图片 2');
    assert.equal(api.imageMappingSummary(graph,repaired,true,'first'),'First frame：Image 1；Last frame：Disabled');
    const extraGraph={...graph,extra:{class_type:'LoadImage',inputs:{image:'extra-template.png'}},consumer:{class_type:'CustomImageNode',inputs:{image:['extra',0]}}};
    const warning=api.imageMappingSummary(extraGraph,repaired,false,'first');
    assert.match(warning,/尾帧：未启用/);
    assert.match(warning,/仍使用模板图片：图片 #extra/,'a genuinely unmapped input still warns');
    assert(!warning.includes('仍使用模板图片：尾帧'));
    const shared=structuredClone(repaired);shared.fields.find(f=>f.node==='127').media_index=0;
    assert.equal(api.imageMappingSummary(graph,shared,false,'both'),'首帧图片：图片 1；尾帧图片：图片 1');
    for(const mode of ['first','last','both']){
        uploads=0;
        const refs=mode==='both'?['first.png','last.png']:['chosen.png'];
        const built=await api.canvasValues(repaired,{...args,media:{image:refs},frameMode:mode});
        assert.equal(built.__ice_frame_mode,mode);assert.equal(uploads,refs.length);
        const params=api.paramsFromValues(repaired,built);
        if(mode!=='last')assert.equal(params['114'].image,mode==='both'?'uploaded/first.png':'uploaded/chosen.png');
        else assert(!params['114']);
        if(mode!=='first')assert.equal(params['127'].image,mode==='both'?'uploaded/last.png':'uploaded/chosen.png');
        else assert(!params['127']);
    }
    uploads=0;
    await assert.rejects(api.canvasValues(repaired,{...args,frameMode:'other'}),/模式/);
    assert.equal(uploads,0);
    config.fields.push(...api.imageInputCandidates(graph).map(c=>({...c,id:c.node,default:''})));
    await assert.rejects(api.canvasValues(config,args),/尾帧图片/);assert.equal(uploads,0);
    let values=await api.canvasValues(config,{...args,media:{image:['first.png','last.png']}});
    assert.equal(values['114'],'uploaded/first.png');assert.equal(values['127'],'uploaded/last.png');
    config.fields.find(f=>f.node==='127').media_index=0;
    uploads=0;values=await api.canvasValues(config,args);
    assert.equal(values['114'],'uploaded/fabric.png');assert.equal(values['127'],values['114']);assert.equal(uploads,1,'shared source uploads once per submission');
    assert.equal(api.paramsFromValues(config,values)['105:104'].prompt,'user prompt');
    assert.equal(JSON.stringify(graph),original,'inspection and mapping do not rewrite the template');
    assert.deepEqual(plain(api.imageUploadQuery({})),{});
    assert.deepEqual(plain(api.imageUploadQuery({comfyImageMode:'lossless'})),{image_max_edge:'0',image_lossless:'true'});
    assert.equal(api.imageUploadQuery({comfyImageMode:'4096'}).image_max_edge,'4096');
    assert.equal(api.imageUploadQuery({comfyImageMode:'custom',comfyImageMaxEdge:3072}).image_max_edge,'3072');
    assert.throws(()=>api.imageUploadQuery({comfyImageMode:'custom',comfyImageMaxEdge:-1}),/上限/);
    assert.match(api.imageOptionsHtml(),/关闭（使用原图）/);
    // Both canvas upload adapters must reject an empty successful response;
    // a fallback to the template/original filename would silently use old bytes.
    for(const [file,start,end,args] of [
        ['canvas.js','async function uploadCanvasUrlToComfy(', 'async function comfyNameForRef(', ['/own.png','custom/test.json','backend']],
        ['smart-canvas.js','async function comfyNameForRef(', 'function smartPendingTasks(', [{url:'/own.png'},'custom/test.json','backend']]
    ]){
        const source=fs.readFileSync(path.join(__dirname,'../../static/js',file),'utf8');
        const snippet=source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)));
        const context=vm.createContext({ComfyWorkflowFields:api,URLSearchParams,settings:{},FormData:class{append(){}},langIsEn:()=>false,fetch:async()=>({ok:true,blob:async()=>({}),json:async()=>({files:[{}]})})});
        vm.runInContext(snippet,context);
        const upload=context[file==='canvas.js'?'uploadCanvasUrlToComfy':'comfyNameForRef'];
        await assert.rejects(upload(...args),/未返回上传文件名/);
    }
    console.log('Comfy images: named first/last mapping, unused-input rejection before upload, explicit source reuse and optional optimization');
})().catch(error=>{console.error(error);process.exitCode=1});
