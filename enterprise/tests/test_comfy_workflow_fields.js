const assert = require('node:assert/strict');
require('../../static/js/comfy-workflow-fields.js');
const fields = globalThis.ComfyWorkflowFields;
const legacy = {
    workflow:{'8':{inputs:{image:'sample.png'}}, '6':{inputs:{filename_prefix:'ComfyUI'}}},
    config:{title:'existing workflow', fields:[
        {id:'input-image', node:'8', input:'image', name:'图片', type:'image', default:'sample.png'},
        {id:'output-prefix', node:'6', input:'filename_prefix', name:'文件名前缀', type:'image', default:'ComfyUI'}
    ]}
};

(async () => {
    for(const prefix of ['ComfyUI', 'result.png', 'a'.repeat(100)]) assert.equal(fields.inferType(prefix, 'filename_prefix'), 'text');
    assert.equal(fields.inferType('photo.png', 'image'), 'image');
    assert.equal(fields.inferType('photo.png', 'filename'), 'image');
    assert.equal(fields.inferType('ComfyUI', 'filename'), 'text');
    assert.equal(fields.inferType('checkpoint.safetensors', 'ckpt_name'), 'text');
    assert.equal(fields.inferType('clip.mp4', 'video'), 'video');
    assert.equal(fields.inferType('sound.wav', 'audio'), 'audio');
    assert.equal(fields.inferType(0.5, 'denoise'), 'slider');

    const normalized = fields.normalizeWorkflow(legacy);
    assert.equal(legacy.config.fields[1].type, 'image', 'read compatibility does not overwrite stored config');
    assert.equal(normalized.config.fields[1].type, 'text');
    assert.equal(normalized.config.fields[1].id, 'output-prefix');
    assert.equal(fields.kind(legacy.config.fields[1]), 'setting');
    assert.deepEqual(fields.normalizeWorkflow(normalized), normalized, 'repair is idempotent');
    const map = refs => fields.canvasValues(normalized.config, {
        media:{image:refs}, mediaName:async ref => 'uploaded-'+ref,
        parameters:{'output-prefix':'department-result'}
    });
    const values = await map(['photo.png']);
    assert.deepEqual(fields.paramsFromValues(normalized.config, values), {
        '8':{image:'uploaded-photo.png'}, '6':{filename_prefix:'department-result'}
    });
    await assert.rejects(map([]), /图片 \(#8\.image\)/);
    assert.throws(() => fields.requireMedia(normalized.config, {}), error => !error.message.includes('文件名前缀'));
    const second = {...normalized.config, fields:[...normalized.config.fields, {id:'mask', node:'9', input:'mask', name:'遮罩', type:'image'}]};
    assert.throws(() => fields.requireMedia(second, {image:['one.png']}, true), /遮罩 \(#9\.mask\)/);

    const mixed = {fields:[
        {id:'positive', node:'1', input:'text', type:'textarea', default:'positive default'},
        {id:'negative', node:'2', input:'text', type:'textarea', default:'negative default'},
        {id:'seed', node:'3', input:'seed', type:'number', default:42, random_enabled:true},
        {id:'strength', node:'3', input:'strength', type:'slider', step:0.1, default:0.5},
        {id:'choice', node:'3', input:'steps', type:'dropdown', default:'10'},
        {id:'flag', node:'3', input:'enabled', type:'boolean', default:false}
    ]};
    const mixedValues = await fields.canvasValues(mixed, {prompt:'connected prompt', parameters:{flag:false}, randomValue:f => f.id === 'seed' ? 123 : undefined});
    assert.deepEqual(fields.paramsFromValues(mixed, mixedValues), {'1':{text:'connected prompt'}, '2':{text:'negative default'}, '3':{seed:123, strength:0.5, steps:10, enabled:false}});
    assert.equal(fields.coerceValue({type:'number'}, -1.9), -1);
    assert.equal(fields.coerceValue({type:'text', default:null}, undefined), '');
    assert.equal(fields.coerceValue({type:'number', default:null}, undefined), 0);
    assert.equal(fields.coerceValue({type:'dropdown'}, '1e+2'), 100);
    const withDefault = await fields.canvasValues(mixed, {mediaName:async value => value});
    assert.equal(withDefault.positive, 'positive default');
    const missingPrompt = {fields:[{id:'prompt', node:'1', input:'text', name:'提示词', type:'textarea', default:''}]};
    await assert.rejects(fields.canvasValues(missingPrompt, {}), /提示词 \(#1\.text\)/);
    let unmappedUploads = 0;
    await assert.rejects(fields.canvasValues({fields:[], image_groups:[{id:'images',source_nodes:['470'],min_images:1,max_images:10}]}, {
        prompt:'将文本去除', media:{image:['selected.png']}, mediaName:async()=>{unmappedUploads++;return 'uploaded.png';}
    }), /未配置创作提示词映射/);
    assert.equal(unmappedUploads, 0, 'an unmapped prompt must fail before uploading or submitting');
    const branches = {fields:[
        {id:'direct',node:'switch',input:'on_false',type:'text',role:'prompt',default:'old instruction'},
        {id:'enhancer',node:'llm',input:'prompt',type:'textarea',role:'prompt',default:'old instruction'},
        {id:'negative',node:'encoder',input:'negative_prompt',type:'textarea',role:'negative',default:'negative default'},
        {id:'system',node:'llm',input:'system_prompt',type:'textarea',role:'system',default:'system default'}
    ]};
    const branchValues = await fields.canvasValues(branches, {prompt:'将文本去除'});
    assert.deepEqual(fields.paramsFromValues(branches, branchValues), {
        switch:{on_false:'将文本去除'}, llm:{prompt:'将文本去除',system_prompt:'system default'},encoder:{negative_prompt:'negative default'}
    });
    const definition = {input:{required:{image:[['sample.png'],{image_upload:true}],model:[['model-a','model-b'],{}],denoise:['FLOAT',{min:0,max:1,step:0.01}]}}};
    assert.equal(fields.definitionField('sample.png','image',definition).type,'image');
    assert.deepEqual(fields.definitionField('model-a','model',definition),{type:'dropdown',options:['model-a','model-b'],value_type:'string'});
    assert.equal(fields.definitionField(0.35,'denoise',definition).step,0.01);
    assert.equal(fields.definitionField('result.png','filename_prefix',definition).type,'text');
    assert.deepEqual(fields.dropdownOptions({input:'model'},'model-a',definition),['model-a','model-b']);
    assert.deepEqual(fields.dropdownOptions({input:'model',default:'saved.safetensors'},'raw.safetensors',{}),['saved.safetensors']);
    assert.deepEqual(fields.dropdownOptions({input:'model',options:['curated']},'raw',definition),['curated']);
    const repaired=fields.normalizeWorkflow({workflow:{'459:451':{class_type:'UNETLoader',inputs:{unet_name:'qwen.safetensors'}}},config:{fields:[{id:'existing',node:'459:451',input:'unet_name',type:'dropdown',options:[]}]}});
    assert.deepEqual(repaired.config.fields[0].options,['qwen.safetensors']);
    assert.equal(repaired.config.fields[0].id,'existing');
    assert.equal(fields.coerceValue({type:'boolean'},'false'),false);
    for(const type of ['boolean','number','slider','dropdown'])assert.equal(fields.kind({type,role:'prompt',input:'sampling_mode.seed'}),'setting');
    assert.equal(fields.coerceValue({type:'dropdown',value_type:'string'},'001'),'001');
    assert.equal(fields.coerceValue({type:'number',value_type:'number'},0.125),0.125);
    assert.throws(()=>fields.coerceValue({type:'number',value_type:'integer'},2.5),/整数/);
    const graph={
        gate:{class_type:'ComfySwitchNode',inputs:{switch:false,on_false:'old costume prompt',on_true:['enhance',0]}},
        enhance:{class_type:'TextGenerate',inputs:{prompt:'old',thinking:false}},
        encode:{class_type:'CLIPTextEncode',inputs:{text:['gate',0]}}
    };
    const config={fields:[{id:'prompt',node:'enhance',input:'prompt',type:'text',role:'prompt',default:'replace background'},
        {id:'enable',node:'gate',input:'switch',type:'boolean',role:'prompt',default:false}]};
    assert.match(fields.executionState(graph,config).errors[0],/当前执行分支/);
    const active=fields.executionState(graph,config,{enable:true});
    assert.deepEqual(active.errors,[]);
    assert.equal(active.fields.prompt.active,true);
    assert.equal(graph.gate.inputs.switch,false,'inspection never edits the saved graph');
    let accidentalUploads=0;
    await assert.rejects(fields.canvasValues(config,{workflow:graph,prompt:'new edit',media:{image:[]},mediaName:async()=>accidentalUploads++}),/当前执行分支/);
    assert.equal(accidentalUploads,0);
    assert.equal(fields.isLink({'1':{}},[1,0]),true,'numeric node IDs are wiring, not editable widgets');
    console.log('Comfy field inference, legacy compatibility, named missing inputs and shared mapping passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
