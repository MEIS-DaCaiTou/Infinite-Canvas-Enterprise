'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'../../static/js');
function load(ctx,source,name){
    const start=new RegExp('^(?:async )?function '+name+'\\(','m').exec(source);assert(start,name);
    const after=start.index+start[0].length,next=source.slice(after).search(/\n(?:async )?function \w+\(/);
    vm.runInContext(source.slice(start.index,next<0?undefined:after+next),ctx);
}
for(const filename of ['canvas.js','smart-canvas.js']){
    const source=fs.readFileSync(path.join(root,filename),'utf8');
    const ctx=vm.createContext({cropState:{x:10,y:10,w:200,h:200},imageEditMode:'crop',cropAspectPreset:'free',cropAspectRatio:null,
        cropBounds:()=>({w:450,h:600}),document:{querySelectorAll:()=>[]},renderCropBox:()=>{}});
    for(const name of ['cropRatioFromPreset','syncCropRatioButtons','fitCropRectToAspect','setCropAspectPreset','clampCrop'])load(ctx,source,name);
    for(let i=0;i<6;i++)for(const preset of ['16:9','9:16','1:1','4:3','3:4','source']){
        ctx.setCropAspectPreset(preset);const rect={...ctx.cropState},ratio=preset==='source'?.75:Number(preset.split(':')[0])/Number(preset.split(':')[1]);
        const width=Math.min(450,600*ratio),height=width/ratio;
        assert(Math.abs(rect.w-width)<=1 && Math.abs(rect.h-height)<=1,filename+' fits the whole image rather than the prior crop');
        ctx.setCropAspectPreset(preset);assert.deepEqual({...ctx.cropState},rect,'repeated selection is stable');
    }
    const current={...ctx.cropState};ctx.setCropAspectPreset('free');assert.deepEqual({...ctx.cropState},current,'free mode preserves the current manual selection');
}
const storage=new Map();
function preferences(blocked=false){
    const controls=Object.fromEntries([['paintBrushSize',2,80,14],['maskBrushSize',4,160,42]].map(([id,min,max,value])=>[id,{min,max,value:String(value),addEventListener(type,callback){this[type]=callback}}]));
    const ctx=vm.createContext({document:{getElementById:id=>controls[id]},localStorage:{getItem:key=>{if(blocked)throw Error('storage blocked');return storage.get(key)??null},setItem:(key,value)=>{if(blocked)throw Error('storage blocked');storage.set(key,value)}}});
    ctx.window=ctx;vm.runInContext(fs.readFileSync(path.join(root,'image-edit-preferences.js'),'utf8'),ctx);ctx.ImageEditPreferences.bindBrushSizes();return controls;
}
let controls=preferences();controls.paintBrushSize.value='53';controls.paintBrushSize.input();controls.maskBrushSize.value='98';controls.maskBrushSize.input();
controls=preferences();assert.equal(controls.paintBrushSize.value,'53');assert.equal(controls.maskBrushSize.value,'98');
controls=preferences(true);assert.equal(controls.paintBrushSize.value,'14');assert.doesNotThrow(()=>controls.paintBrushSize.input());
storage.set('canvas_paintBrushSize','999');assert.equal(preferences().paintBrushSize.value,'80','saved values still obey the existing brush range');

(async()=>{
    const source=fs.readFileSync(path.join(root,'canvas.js'),'utf8'),created=[];let read=async()=> 'Full text, not its card summary';
    const ctx=vm.createContext({canvas:{id:'a'},ensureCanvas:()=>true,defaultPoint:()=>({x:0,y:0}),uid:x=>x,
        addNode:node=>{created.push(node);return node},ComfyOutputs:{text:item=>read(item)},mediaKindForOutputItem:item=>item.kind || 'image',outputImageName:()=> 'result'});
    for(const name of ['createPromptFromOutput','createInputFromOutput'])load(ctx,source,name);
    await ctx.createInputFromOutput({url:'/output/video',kind:'video'},{x:22,y:33});assert.equal(created[0].mediaKind,'video');assert.equal(created[0].url,'/output/video');assert.equal(created[0].x,22);
    await ctx.createInputFromOutput({url:'/output/result.txt',kind:'text',result_id:'result',run_id:'run'},{x:55,y:66});
    assert.equal(created[1].type,'prompt');assert.equal(created[1].text,'Full text, not its card summary');assert.equal(created[1].sourceResultId,'result');
    read=async()=>{throw Error('read denied')};await assert.rejects(ctx.createInputFromOutput({kind:'text'}),/read denied/);assert.equal(created.length,2);
    let finish;read=()=>new Promise(resolve=>finish=resolve);const pending=ctx.createInputFromOutput({kind:'text'});ctx.canvas={id:'b'};finish('late result');await pending;assert.equal(created.length,2,'navigation during text read cannot insert into another canvas');
    console.log('Two-editor crop stability, browser-local brush sizes and full-text/media input creation passed');
})().catch(error=>{console.error(error);process.exitCode=1});
