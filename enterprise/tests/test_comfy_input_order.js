'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../..');
const source = fs.readFileSync(path.join(root, 'static/js/canvas.js'), 'utf8');
function actual(name){
    const start = source.indexOf(`function ${name}(`);
    assert.ok(start >= 0, name);
    const end = source.slice(start + 1).search(/\n(?:async )?function /);
    return source.slice(start, end < 0 ? undefined : start + 1 + end);
}
class Element {
    constructor(){this.dataset={};this.children=[];this._html='';}
    set innerHTML(value){this._html=value;this.children=[];}
    get innerHTML(){return this._html;}
    appendChild(item){this.children.push(item);}
}
const list = new Element(), count = {};
let hidden = false, refreshes = [], saves = 0;
const section = {classList:{toggle:(_name,value)=>{hidden=value;}},querySelector:()=>list};
const container = {querySelector:selector=>({'.comfy-images':section,'[data-comfy-input-count]':count}[selector])};
const config = {fields:[],image_groups:[{id:'images',source_nodes:['load'],min_images:1,max_images:10}]};
let inputs = ['A','B','C','D'].map(id=>({id,label:id+'.png',preview:id+'.png',refs:[{url:id+'.png',kind:'image'}]}));
inputs.push({id:'prompt',prompt:'edit the subject',refs:[]});
const context = vm.createContext({
    document:{createElement:()=>new Element()},
    currentComfyWorkflow:()=>({config}),
    generatorSources:()=>inputs,
    imageRefsOnly:refs=>refs.filter(ref=>ref.kind==='image'),
    mediaKindForRef:ref=>ref?.kind || 'image',
    comfyFieldKind:field=>context.ComfyWorkflowFields.kind(field),
    tr:key=>key, trf:(key,values)=>key+JSON.stringify(values),
    escapeHtml:value=>value,isMissingAssetUrl:()=>false,
    canvasPreviewImgHtml:url=>`<img src="${url}">`,canvasVideoPreviewHtml:url=>`<video src="${url}">`,
    missingAssetHtml:()=>'',refreshIcons:()=>{},
    refreshNodes:ids=>refreshes.push([...ids]),scheduleSave:()=>saves++,
    render:()=>{throw new Error('input reordering must not redraw every node');}
});
vm.runInContext(fs.readFileSync(path.join(root,'static/js/comfy-workflow-fields.js'),'utf8'),context);
vm.runInContext(['renderImageInputList','renderComfyImages','refreshComfyInputViews','orderedSources','reorderInput'].map(actual).join('\n'),context);
const node = {id:'comfy',mode:'custom',inputs:['A','B','C','D','prompt']};
const order = ()=>context.orderedSources(node,inputs);
context.refreshComfyInputViews(container,node,order());
assert.equal(hidden,false,'an image group with no individual exposed fields still shows its connected media');
assert.equal(list.children.length,4);
assert.match(count.textContent,/"count":4/);
assert.match(count.title,/1–10/);
list.children.forEach((item,i)=>{
    assert.equal(item.draggable,true);
    assert.equal(item.dataset.sourceId,['A','B','C','D'][i]);
    assert.ok(item.innerHTML.includes(`<span class="input-index">${i+1}</span>`));
});
const transfer = {data:{},setData(type,value){this.data[type]=value;},getData(type){return this.data[type];}};
const event = {dataTransfer:transfer,preventDefault(){},stopPropagation(){}};
list.children[3].ondragstart(event);
list.children[1].ondrop(event);
assert.deepEqual([...node.inputs],['A','D','B','C','prompt']);
assert.deepEqual(refreshes,[['comfy']]);assert.equal(saves,1);
context.refreshComfyInputViews(container,node,order());
assert.deepEqual(list.children.map(item=>item.dataset.sourceId),['A','D','B','C']);
const restored = JSON.parse(JSON.stringify(node));
assert.deepEqual([...context.orderedSources(restored,inputs)].map(item=>item.id),['A','D','B','C','prompt']);
(async()=>{
    const values = await context.ComfyWorkflowFields.canvasValues(config,{
        media:{image:order().flatMap(src=>src.refs)},mediaName:async ref=>'uploaded/'+ref.url
    });
    assert.deepEqual([...values.images],['uploaded/A.png','uploaded/D.png','uploaded/B.png','uploaded/C.png']);
    inputs.push({id:'video',label:'clip',preview:'clip.mp4',refs:[{url:'clip.mp4',kind:'video'}]});
    context.refreshComfyInputViews(container,node,order());
    assert.equal(list.children.length,5);assert.match(list.children[4].innerHTML,/<video/);
    inputs = inputs.filter(src=>src.id!=='B');
    context.refreshComfyInputViews(container,node,order());
    assert.deepEqual(list.children.map(item=>item.dataset.sourceId),['A','D','C','video']);
    node.mode='text';context.refreshComfyInputViews(container,node,order());assert.equal(hidden,true);
    console.log('Comfy media thumbnails, shared drag handlers, persisted input order and workflow submission order passed; provider calls 0');
})().catch(error=>{console.error(error);process.exitCode=1;});
