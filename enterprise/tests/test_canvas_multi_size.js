const assert=require('node:assert/strict');
global.window=global;
global.document={querySelectorAll:()=>[]};
global.fetch=async()=>({ok:true,json:async()=>({favorites:[]})});
global.StudioI18n={t:key=>key,lang:()=> 'zh'};
require('../../static/js/model-picker.js');
const Multi=require('../../static/js/canvas-multi-size.js');
const rule={model_family:'seedream-5.5',mode:'pixel',supports_custom_size:true,
    size_rules:{min_pixels:921600,max_pixels:4624220,max_aspect:16}};
const config={api_providers:[
    {id:'t8',image_models:['seedream','split','generic'],builtin_model_image_profiles:{seedream:rule,split:{...rule,layer_output:true},generic:{mode:'pixel'}}},
    {id:'ark',image_models:['official'],builtin_model_image_profiles:{official:rule}},
    {id:'off',enabled:false,image_models:['disabled'],builtin_model_image_profiles:{disabled:rule}}
]};
const models=Multi.modelsFor(config);
assert.deepEqual(models.map(m=>m.key),['t8|seedream','ark|official']);
assert.equal(Multi.ratio({width:2520,height:1080}),'7:3');
assert.equal(Multi.ratio(Multi.PRESETS[5]),'21:9');
for(const preset of Multi.PRESETS){
    assert.equal(Multi.sizeError(preset,models[0]),'');
    assert.equal(Multi.sizeError(preset,models[1]),'');
}
assert.match(Multi.sizeError({width:512,height:512},models[0]),/像素总数/);
assert.match(Multi.sizeError({width:800,height:13000},models[0]),/长短边比例/);
const body=Multi.requestFor({name:'服装方图',width:1200,height:1200},models[0]);
assert.equal(body.size,'1200x1200');
assert.equal(body.provider_id,'t8');
assert.equal(body.layer_options,undefined);
assert.match(body.prompt,/重新构图/);
assert.match(body.prompt,/全部文字与价格/);
assert.throws(()=>Multi.requestFor({width:0,height:1200},models[0]),/invalidSize/);
(async()=>{
    const started=[];let finish;
    const barrier=new Promise(resolve=>{finish=resolve;});
    const result=Multi.submitTargets([{id:1},{id:2}],async p=>{started.push(p.id);await barrier;if(p.id===2)throw new Error('fixture failure');return 'archived-1';});
    assert.deepEqual(started,[1,2]);finish();
    const settled=await result;
    assert.equal(settled[0].value,'archived-1');assert.equal(settled[1].status,'rejected');
    console.log('Multi-size: source capabilities, preset sizes, model requests and independent parallel outcomes passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
