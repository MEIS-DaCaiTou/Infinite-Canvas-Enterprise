const assert=require('node:assert/strict');
global.StudioI18n={t:key=>key};
const S=require('../../static/js/canvas-layer-separation.js');
const config={api_providers:[
    {id:'ark-proxy',name:'Ark',image_models:['native55'],builtin_model_image_profiles:{native55:{supports_layer_options:true,layer_profile:{resolutions:['1K','1.5K','2K']}}}},
    {id:'t8',image_models:['normal55','split55'],builtin_model_image_profiles:{normal55:{supports_layer_options:false},split55:{supports_layer_options:true,resolutions:['1K','1.5K','2K']}}},
    {id:'disabled',enabled:false,image_models:['native55'],builtin_model_image_profiles:{native55:{supports_layer_options:true}}}
]};
assert.deepEqual(S.modelsFor(config).map(m=>m.key),['ark-proxy|native55','t8|split55']);
assert.deepEqual(S.regionFromPoints({x:.9,y:.8},{x:.2,y:.1}),{x:.2,y:.1,width:.7,height:.7});
assert.deepEqual(S.moveRegion({x:.2,y:.1,width:.7,height:.7},1,1),{x:.3,y:.3,width:.7,height:.7});
assert.deepEqual(S.resizeRegion({x:.2,y:.1,width:.7,height:.7},'se',1,1),{x:.2,y:.1,width:.8,height:.9});
assert.equal(S.promptFor('  服装  ',{x:.2,y:.1,width:.5,height:.6}),'服装\n只拆分位于图片区域内的元素：横向 20%–70%，纵向 10%–70%（以左上角为原点）');
const state={mode:'smart',prompt:'ignored',region:{x:0,y:0,width:1,height:1},recognize:true,limit:'7',size:'auto'};
const model=S.modelsFor(config)[0];
assert.deepEqual(S.parameters(state,model,'default'),{provider_id:'ark-proxy',model:'native55',size:'auto',prompt:'default',layer_options:{max_images:8,text_recognition:true}});
assert.throws(()=>S.parameters({...state,mode:'selection',region:null},model,'default'),/regionRequired/);
assert.throws(()=>S.parameters({...state,mode:'description',prompt:'   '},model,'default'),/descriptionRequired/);
assert.throws(()=>S.parameters({...state,limit:'100'},model,'default'),/limitHint/);
assert.deepEqual(S.parameters({...state,limit:''},model,'default').layer_options,{text_recognition:true});
const area=S.sourceRegion({x:0,y:0,width:1,height:1},{fit:'cover',width:160,height:160,naturalWidth:100,naturalHeight:200});
assert.deepEqual(area,{x:0,y:.25,width:1,height:.5});
assert.equal(S.parameters({...state,mode:'description',prompt:'针织外套'},model,'default').prompt,'针织外套');
assert.equal(S.parameters({...state,mode:'selection',prompt:'针织外套'},model,'default').prompt.includes('横向 0%–100%'),true);
const restricted={...model,profile:{supports_layer_limit:false,supports_layer_text_recognition:false}};
assert.throws(()=>S.parameters({...state,recognize:false},restricted,'default'),/channelOptionsUnavailable/);
assert.throws(()=>S.parameters({...state,limit:''},restricted,'default'),/channelOptionsUnavailable/);
assert.deepEqual(S.parameters({...state,limit:'',recognize:false},restricted,'default').layer_options,{text_recognition:false});
assert.equal(S.parameters(state,{...model,profile:{supports_empty_layer_prompt:true}},'default').prompt,'');
console.log('Marketing layer separation: capability sources, region geometry, exact prompt, modes and output bounds passed');
