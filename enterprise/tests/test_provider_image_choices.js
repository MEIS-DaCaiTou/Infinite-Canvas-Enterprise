/* Exercise the actual shared controls: no DOM fixture or supplier request. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const context = {window:{}, document:{querySelectorAll:()=>[]},
    fetch:async()=>({ok:true,json:async()=>({favorites:[],view:'all'})})};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../static/js/model-picker.js'),'utf8'), context);
const picker = context.window.CanvasModelPicker;
const ratios = [['square','1:1'],['portrait','2:3'],['wide','16:9'],['ultratall','9:21'],['custom','自定义'],['source','原图']];
const resolutions = ['auto','1k','2k','4k','custom'];
const sizes = {square:{'1k':'1024x1024','2k':'2048x2048','4k':'4096x4096'},
    portrait:{'1k':'1024x1536','2k':'1360x2048','4k':'2352x3520'},
    wide:{'1k':'1280x720','2k':'2048x1152','4k':'3840x2160'}};
const sizeFor = (ratio,resolution)=>sizes[ratio]?.[resolution] || '1024x1024';
const gpt = {mode:'pixel',supports_auto_size:true,supports_custom_size:true,
    size_rules:{multiple:16,max_edge:3840,max_aspect:3,min_pixels:655360,max_pixels:8294400}};
assert.match(picker.sizeError(gpt,'4096x4096'),/3840/);
assert.match(picker.sizeError(gpt,'1537x1024'),/16/);
assert.equal(picker.sizeError(gpt,'3840x2160'),'');
assert.equal(picker.sizeError(gpt,'auto'),'');
const gpt25 = {...gpt,supports_auto_size:false};
assert.match(picker.sizeError(gpt25,'auto'),/自动/);
assert(!picker.sizeChoices(gpt25,ratios,resolutions,{ratio:'square'},sizeFor).resolutions.includes('auto'));
assert.equal(picker.sizeError(gpt25,'1024x1024'),'');
// Opening or switching a saved GPT node must not turn an explicit auto into 4K.
const smartSource = fs.readFileSync(path.join(__dirname,'../../static/js/smart-canvas.js'),'utf8');
const smart = vm.createContext({settings:{engine:'api',apiKind:'image',model:'gpt-image-2.5-flare',resolution:'auto'},
    clearVolcengineSelectionOutsideVolcengine:()=>{},providerImageModels:()=>['gpt-image-2.5-flare'],
    isGptImageAutoSizeModel:()=>true,defaultSmartApiResolution:()=> '4k'});
for(const name of ['sanitizeSmartApiSelection','normalizeApiSizeSettings']){
    const start = smartSource.indexOf('function '+name+'(');
    assert(start>=0,name);
    vm.runInContext(smartSource.slice(start,smartSource.indexOf('\n}',start)+2),smart);
}
const saved = {engine:'api',provider_id:'zhenzhen',model:'gpt-image-2.5-flare',resolution:'auto'};
smart.sanitizeSmartApiSelection(saved);
assert.equal(saved.resolution,'auto');
smart.normalizeApiSizeSettings();
assert.equal(smart.settings.resolution,'auto');
smart.settings.resolution='1k';smart.normalizeApiSizeSettings();
assert.equal(smart.settings.resolution,'1k');
smart.settings.resolution='';smart.normalizeApiSizeSettings();
assert.equal(smart.settings.resolution,'4k','missing settings keep the existing default policy');
let choices = picker.sizeChoices(gpt,ratios,resolutions,{ratio:'square'},sizeFor);
assert(!choices.resolutions.includes('4k'), '4K square must not be selectable');
choices = picker.sizeChoices(gpt,ratios,resolutions,{ratio:'wide'},sizeFor);
assert(choices.resolutions.includes('4k'), '4K landscape remains selectable');
const banana = {mode:'aspect-size',ratios:['1:1','2:3','16:9'],supports_image_size:false,
    fixed_resolution:'2K',supports_custom_size:false};
choices = picker.sizeChoices(banana,ratios,resolutions,{ratio:'square'},sizeFor);
assert(!choices.ratios.some(([value])=>value==='custom' || value==='ultratall'));
assert.equal(choices.resolutions.length,0);
assert.match(picker.sizeError(banana,'768x2048',{aspect_ratio:'3:8'}),/3:8/);
assert.equal(picker.sizeError(banana,'1024x1536',{aspect_ratio:'2000:3000'}),'');
assert.equal(picker.imageParameters({ratio:'source',customRatio:'3:8',resolution:'2k'}).aspect_ratio,'3:8');
assert.equal(picker.imageParameters({ratio:'square',resolution:'1.5k'}).resolution,'1.5K');
assert.equal(picker.imageParameters({ratio:'portrait',resolution:'auto'}).aspect_ratio,'auto');
assert.equal(picker.sizeError({mode:'pixel',resolutions:['1K','1.5K','2K']},'1024x1024',{resolution:'4K'}).includes('分辨率'),true);
assert.equal(picker.sizeChoices({},ratios,resolutions,{ratio:'custom'},sizeFor).ratios,ratios);
context.window.StudioI18n={lang:()=> 'en'};
assert.match(picker.validationNotice(picker.sizeError(gpt,'4096x4096'),true),/3840px.*no task submitted/);
console.log('SUP-01 shared image choices: legal combinations, fixed models, exact source ratio, 1.5K and other-provider compatibility passed.');
