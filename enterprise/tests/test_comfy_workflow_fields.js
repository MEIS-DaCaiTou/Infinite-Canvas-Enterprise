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
    console.log('Comfy field inference, legacy compatibility, named missing inputs and shared mapping passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
