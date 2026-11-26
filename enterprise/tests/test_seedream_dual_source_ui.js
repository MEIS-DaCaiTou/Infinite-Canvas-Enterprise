/* Consume backend capability JSON; exercise actual original-page helpers. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0,'utf8'));
const context = vm.createContext({window:{},document:{querySelectorAll:()=>[]},
    apiProviders:input.providers,settings:{engine:'volcengine',apiKind:'image',provider_id:'official-images',
        model:input.model,resolution:'1k',ratio:'square'},
    fetch:async()=>({ok:true,json:async()=>({favorites:[],view:'all'})}),
    clearVolcengineSelectionOutsideVolcengine:()=>{},normalizeApiSizeSettings:()=>{},
    isGptImageAutoSizeModel:()=>false,defaultSmartApiResolution:()=> '1k',
    renderProviderControl:providers=>providers.map(p=>p.id).join(','),renderModelControl:models=>models.join(','),
    renderSizePickerControl:()=>'',renderCountVisualControl:()=>'',dynamicParams:{innerHTML:''}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../../static/js/model-picker.js'),'utf8'),context);
const source = fs.readFileSync(path.join(__dirname,'../../static/js/smart-canvas.js'),'utf8');
for(const name of ['isApiLikeEngine','volcengineImageProviders','volcengineProvider','providerImageModels',
    'apiProviderById','sanitizeSmartApiSelection','renderQualityControl','renderVolcengineParams']){
    const start=source.indexOf('function '+name+'(');
    assert(start>=0,name);
    vm.runInContext(source.slice(start,source.indexOf('\n}',start)+2),context);
}
const saved={...context.settings};
context.sanitizeSmartApiSelection(saved);
assert.equal(saved.provider_id,'official-images');
assert.equal(saved.model,input.model);
assert.equal(context.renderQualityControl(),'');
context.renderVolcengineParams();
assert.equal(context.settings.provider_id,'official-images');
assert.match(context.dynamicParams.innerHTML,/official-images/);
assert(!context.dynamicParams.innerHTML.includes('department-images'));
const picker=context.window.CanvasModelPicker;
const ratios=[['square','1:1'],['wide','16:9'],['custom','custom']];
const resolutions=['auto','1k','1.5k','2k','4k','custom'];
const sizeFor=(ratio,res)=>({ '1k':'1024x1024','1.5k':'1536x1536','2k':'2048x2048','4k':'4096x4096'}[res] || 'auto');
for(const provider of input.providers.filter(p=>p.id!=='volcengine')){
    const model=provider.image_models[0],profile=picker.profileFor(provider,model);
    const choices=picker.sizeChoices(profile,ratios,resolutions,{ratio:'square'},sizeFor);
    assert.deepEqual(Array.from(choices.resolutions),['1k','1.5k','2k','custom']);
    assert(picker.sizeError(profile,'4096x4096',{resolution:'4K'}));
    assert.equal(picker.sizeError(profile,'2880x1440',{resolution:'2K'}),'');
    const layers=profile.layer_profile;
    assert.equal(picker.sizeError(layers,'auto'),'');
    assert(picker.sizeError(layers,'1024x1024'));
}
console.log('Seedream dual-source controls: native identity, shared choices and quality controls passed');
