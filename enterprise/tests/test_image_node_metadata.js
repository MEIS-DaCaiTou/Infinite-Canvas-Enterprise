'use strict';
// Exercise the real original-image measurement code; never infer dimensions from a thumbnail.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../../static/js/canvas.js'),'utf8');
const pending=[],labels=new Map();let saves=0;
const ctx=vm.createContext({
    nodes:[],nodesEl:{querySelector:selector=>labels.get(selector)},CSS:{escape:x=>x},langIsEn:()=>false,
    isCanvasPreviewImage:img=>img.preview,
    loadCanvasOriginalImageDimensions:url=>new Promise(resolve=>pending.push({url,resolve})),
    scheduleSave:()=>saves++,
});
function actual(name){
    const start=source.indexOf(`function ${name}(`);assert(start>=0,name);
    const end=source.slice(start+1).search(/\n(?:async )?function /);
    return source.slice(start,end<0?undefined:start+1+end);
}
vm.runInContext(actual('gcdInt')+'\n'+source.slice(source.indexOf('function imageNodeMetadataHtml('),source.indexOf('\nfunction render(){')),ctx);
function fixture(id,url,{preview=true,width=768,height=768}={}){
    const node={id,type:'image',url};ctx.nodes.push(node);
    const info={outerHTML:'',textContent:''};labels.set(`.image-node[data-id="${id}"] .image-metadata`,info);
    const img={dataset:{originalSrc:url},preview,naturalWidth:width,naturalHeight:height,closest:()=>({dataset:{id}})};
    return {node,img,info,root:{querySelectorAll:()=>[img]}};
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
    for(const [w,h,ratio]of [[2048,2048,'1:1'],[4096,2304,'16:9'],[4500,6000,'3:4'],[4096,2160,'256:135']]){
        const html=ctx.imageNodeMetadataHtml({natural_w:w,natural_h:h});assert(html.includes(`${w} × ${h}`));assert(html.includes(`>${ratio}</span>`));
    }
    assert.match(ctx.imageNodeMetadataHtml({}),/读取图片信息/);
    const first=fixture('first','/assets/original-4k.jpg');
    ctx.measureCanvasOriginalImageNodes(first.root);ctx.measureCanvasOriginalImageNodes(first.root);
    assert.equal(pending.length,1,'in-flight reads are reused');
    assert.equal(first.node.natural_w,undefined,'768px preview is not the original');
    pending.shift().resolve({w:4096,h:2304});await flush();
    assert.equal(first.node.natural_w,4096);assert.match(first.info.outerHTML,/16:9/);assert.equal(saves,1);
    ctx.measureCanvasOriginalImageNodes(first.root);assert.equal(pending.length,0,'persisted dimensions avoid another read');

    ctx.clearImageNodeDimensions(first.node);first.node.url='/assets/replacement-2k.jpg';first.img.dataset.originalSrc=first.node.url;
    assert.equal(first.node.natural_h,undefined);ctx.measureCanvasOriginalImageNodes(first.root);
    pending.shift().resolve({w:2048,h:3072});await flush();assert.match(first.info.outerHTML,/2048 × 3072/);assert.match(first.info.outerHTML,/2:3/);

    const stale=fixture('stale','/assets/old.jpg');ctx.measureCanvasOriginalImageNodes(stale.root);
    const old=pending.shift();ctx.clearImageNodeDimensions(stale.node);stale.node.url='/assets/new.jpg';stale.img.dataset.originalSrc=stale.node.url;
    ctx.measureCanvasOriginalImageNodes(stale.root);old.resolve({w:100,h:100});await flush();assert.equal(stale.node.natural_w,undefined);
    pending.shift().resolve({w:4500,h:6000});await flush();assert.equal(stale.node.natural_w,4500);

    const removed=fixture('removed','/assets/removed.jpg');ctx.measureCanvasOriginalImageNodes(removed.root);ctx.nodes=ctx.nodes.filter(n=>n!==removed.node);
    pending.shift().resolve({w:4096,h:4096});await flush();assert.equal(removed.node.natural_w,undefined,'deleted nodes are not updated');

    const direct=fixture('direct','blob:local',{preview:false,width:2048,height:2048});ctx.measureCanvasOriginalImageNodes(direct.root);await flush();
    assert.equal(direct.node.natural_w,2048);assert.equal(pending.length,0,'decoded original/blob needs no extra image read');
    const unavailable=fixture('unavailable','/assets/missing.jpg');ctx.measureCanvasOriginalImageNodes(unavailable.root);pending.shift().resolve(null);await flush();
    assert.equal(unavailable.info.textContent,'尺寸暂不可用');assert.equal(unavailable.node.natural_w,undefined);
    console.log('Image metadata: 2K/4K exact ratios, original vs preview, replacement, stale/deleted reads, blob and failed read passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
