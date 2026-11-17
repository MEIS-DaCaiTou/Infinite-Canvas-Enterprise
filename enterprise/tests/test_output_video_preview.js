'use strict';
// Output interactions stay attached to the card when its poster becomes a player.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.resolve(__dirname,'../../static/js/canvas.js'),'utf8');
function load(ctx,name){
    const start=new RegExp('^(?:async )?function '+name+'\\(','m').exec(source);assert(start,name);
    const after=start.index+start[0].length,next=source.slice(after).search(/\n(?:async )?function \w+\(/);
    vm.runInContext(source.slice(start.index,next<0?undefined:after+next),ctx);
}
function fixture(initial='poster',kind='video'){
    const item={url:'/output/result.'+(kind==='video'?'mp4':kind==='text'?'txt':'png'),kind,result_id:'result-1'};
    const state={image:initial==='poster'?{dataset:{url:item.url}}:null,video:initial==='video'?{pause(){state.paused=true}}:null};
    const button={},card=kind==='text'?{}:null,listeners={},captures={},opened=[],inline=[],texts=[],node={id:'output',images:[item]};
    const wrap={dataset:{outputUrl:item.url},querySelector:selector=>({img:state.image,video:state.video,'.canvas-video-play':button,'.output-file-card':card}[selector]||null),
        addEventListener:(name,fn,capture)=>{(listeners[name]||=[]).push(fn);captures[name]=!!capture}};
    const ctx=vm.createContext({setTimeout,openOutputLightbox:(url,out)=>opened.push({url,out}),openCanvasText:item=>texts.push(item),
        canvasActivateVideoPreview:target=>{inline.push(target);state.image=null;state.video={pause(){state.paused=true}};return true;},
        outputUrlValue:item=>typeof item==='string'?item:item?.url || '',mediaKindForOutputItem:item=>item?.kind || 'image',
        isMissingAssetUrl:()=>false,outputImageName:()=> 'result',setOutputDragPreview:()=>{},
        ComfyOutputs:{items:items=>items},comfyTaskControls:{bindOutput(){}},langIsEn:()=>false});
    for(const name of ['bindOutputDrag','bindOutputWrap'])load(ctx,name);ctx.bindOutputWrap(wrap,node);
    const event=()=>({target:{closest:()=>null},preventDefault(){},stopPropagation(){}});
    return {ctx,state,button,card,listeners,captures,opened,inline,texts,node,wrap,item,event};
}
for(const state of ['poster','video']){
    const f=fixture(state);
    assert.equal(f.captures.dblclick,true,'preview intercepts native double-click fullscreen before the video handles it');
    f.button.onclick(f.event());assert.equal(f.inline.length,1);assert.equal(f.opened.length,0,'single click plays inline');
    for(let i=0;i<3;i++)f.listeners.dblclick[0](f.event());
    assert.equal(f.opened.length,3,'double-click reopens the preview without a refresh');assert.equal(f.state.paused,true);
    assert(f.opened.every(call=>call.url===f.item.url&&call.out===f.node));assert.equal(f.node.images.length,1);
}
{
    const f=fixture();f.state.image.onclick(f.event());assert.equal(f.inline.length,1,'poster click also plays inline');
    f.listeners.dblclick[0](f.event());assert.equal(f.opened.length,1,'card listener survives asynchronous poster replacement');
}
for(const kind of ['image','video','text']){
    const f=fixture(kind==='text'?'file':'poster',kind),data={};
    f.wrap.ondragstart({...f.event(),dataTransfer:{setData:(type,value)=>data[type]=value}});
    const payload=JSON.parse(data['application/x-canvas-asset']);assert.equal(payload.kind,kind);assert.equal(payload.url,f.item.url);
    assert.equal(payload.result_id,'result-1');assert.equal(!!data['application/x-canvas-output-image'],kind==='image');
    assert.equal(f.node.images.length,1,'dragging does not delete or duplicate the source result');
    if(kind==='text'){f.card.onclick(f.event());assert.equal(f.texts.length,0,'drag does not also open the text viewer');}
}
{
    const f=fixture('video');Object.assign(f.state.video,{controls:true,offsetHeight:200,getBoundingClientRect:()=>({bottom:200,height:200})});
    f.listeners.dblclick[0]({...f.event(),clientY:185});assert.equal(f.opened.length,0,'native control bar retains rapid pause/play/seek actions');
    f.listeners.dblclick[0]({...f.event(),clientY:80});assert.equal(f.opened.length,1,'the video picture still opens on double click');
}
{
    const f=fixture('poster','image');f.state.image.onclick(f.event());assert.equal(f.opened.length,1,'images retain single-click preview');
}
{
    let open=false,exits=0,insideOutput=true;
    const player={matches:()=>true,closest:()=>insideOutput?{}:null};
    const ctx=vm.createContext({document:{fullscreenElement:player,exitFullscreen:()=>{exits++;return Promise.resolve()},addEventListener(){}},
        outputLightbox:{classList:{contains:()=>open}}});
    load(ctx,'reconcileOutputPreviewFullscreen');
    ctx.reconcileOutputPreviewFullscreen();assert.equal(exits,0,'explicit inline fullscreen remains available');
    open=true;ctx.reconcileOutputPreviewFullscreen();assert.equal(exits,1,'preview intent exits a racing inline fullscreen');
    insideOutput=false;ctx.reconcileOutputPreviewFullscreen();assert.equal(exits,1,'large-preview fullscreen remains available');
}
console.log('Output cards: inline single-click, stable double-click preview, typed media/text drag and source preservation passed');
