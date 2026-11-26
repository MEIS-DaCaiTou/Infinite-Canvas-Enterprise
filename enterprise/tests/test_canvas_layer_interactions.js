const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const path=require('node:path'),base=path.resolve(__dirname,'../..');
const read=name=>fs.readFileSync(path.join(base,'static/js',name),'utf8');
const D=require('../../static/js/canvas-layer-document.js');
const {Session}=require('../../static/js/canvas-layer-session.js');
const layout=require('../../static/js/canvas-layer-layout.js');
const source=read('smart-canvas.js');
const asset={url:'/assets/reference.png',width:100,height:80};
const doc=D.fromOutputs([asset]);
Object.assign(doc.layers[0],{x:230,y:-25,width:100,height:80,rotation:90,opacity:.6,flipX:true,crop:{x:.1,y:.2,width:.5,height:.7}});
const plan=D.extractLayer(doc,doc.layers[0].id);
assert.equal(plan.remaining.layers.length,0);assert.equal(doc.layers.length,1);
assert.deepEqual(plan.bounds,{x:240,y:-35,width:80,height:100});
assert.equal(plan.document.layers[0].opacity,.6);assert.equal(plan.document.layers[0].flipX,true);
assert.deepEqual(plan.document.layers[0].crop,doc.layers[0].crop);

// Exercise actual surface handlers: single click works before edit mode, tiny
// pointer jitter is a click, and only an outside release requests extraction.
const context={CanvasLayerDocument:D,CanvasLayerBitmap:{},StudioI18n:{t:k=>k},window:{}};
vm.runInNewContext(read('canvas-layer-surface.js'),context);
const Surface=context.window.CanvasLayerSurface.Surface;
const surfaceLayout=Surface.prototype.layout;
Surface.prototype.paint=function(){};Surface.prototype.layout=function(){};
const root={getBoundingClientRect:()=>({left:0,top:0,width:200,height:160}),addEventListener(){},setPointerCapture(){}};
const session=new Session({images:[asset]}),layer=session.doc.layers[0];
let selected=0,changed=0,dropped=0,modeChanges=0;
const surface=new Surface(root,session,{canEdit:()=>false,canInteract:()=>true,onSelect:()=>selected++,onMode:()=>modeChanges++,onChange:()=>changed++,onDropOutside:async l=>{assert.equal(l,layer);dropped++;}});
surface.hit=()=>layer;
const event=(x,y,extra={})=>({button:0,clientX:x,clientY:y,pointerId:1,target:{closest:()=>null},preventDefault(){this.prevented=true;},stopPropagation(){this.stopped=true;},...extra});
let down=event(30,30);root.onpointerdown(down);assert.equal(selected,1);assert(down.prevented&&down.stopped);
root.onpointermove(event(31,30));root.onpointerup(event(31,30));assert.equal(changed,0);assert.equal(session.undo.length,0);
assert.equal(modeChanges,0,'a selection click must not rebuild the surface between the two clicks of a double-click');
root.onpointerdown(event(30,30));root.onpointermove(event(50,50));root.onpointerup(event(50,50));assert.equal(changed,1);assert.equal(dropped,0);
root.onpointerdown(event(50,50));root.onpointermove(event(250,50));root.onpointerup(event(250,50));assert.equal(dropped,1);assert.equal(changed,1);
root.onpointerdown(event(30,30,{ctrlKey:true}));assert.equal(selected,3);

// While typing, the transparent input is the only text renderer. Blurring to a
// toolbar commits the document without removing that toolbar before its click.
const textSession=new Session({images:[asset]}),textLayer=D.addText(textSession.doc,'原文');textSession.selected=textLayer.id;
const elements=new Map(textSession.doc.layers.map(l=>[l.id,{style:{}}])),selection={style:{}},crop={hidden:true},mask={hidden:true};
const textRoot={clientWidth:200,style:{setProperty(){}},getBoundingClientRect:()=>({width:200}),querySelector:key=>key==='.layer-selection'?selection:key==='.layer-crop-frame'?crop:mask,querySelectorAll:()=>[]};
const textSurface=Object.create(Surface.prototype);Object.assign(textSurface,{root:textRoot,s:textSession,o:{},elements,editingText:textLayer.id});
surfaceLayout.call(textSurface);assert.equal(elements.get(textLayer.id).style.visibility,'hidden');assert.equal(elements.get(textSession.doc.layers[0].id).style.visibility,'');assert.equal(selection.hidden,true);
textSurface.editingText='';surfaceLayout.call(textSurface);assert.equal(elements.get(textLayer.id).style.visibility,'');
context.CanvasLayerAnnotations={TextInput:class {commit(){} open(_root,_value,callbacks){this.callbacks=callbacks;}}};
let textChanges=0,textDrafts=0;textSurface.o={onChange:()=>textChanges++,onDraft:()=>textDrafts++};textSurface.editText(textLayer);
textSurface.textInput.callbacks.change('新文字',{width:.3,height:.2});textSurface.textInput.callbacks.commit('新文字',{width:.3,height:.2},'blur');
assert.equal(textChanges,0);assert(textDrafts>0);assert.equal(textLayer.text,'新文字');assert.equal(textSurface.editingText,'');
textSurface.editText(textLayer);textSurface.textInput.callbacks.commit('确认文字',{width:.4,height:.2},'confirm');assert.equal(textChanges,1);
textSession.history(-1);assert.equal(textSession.doc.layers.find(l=>l.id===textLayer.id).text,'新文字','toolbar and double-click text editing share one undo boundary');

// The canvas adapter creates an ordinary, independent image with a single
// undo boundary; no layer-parent/task/source reference is copied to it.
const owner={id:'board',x:10,y:20,w:340,layerDocument:doc},nodes=[owner];let undo=0;
const detachCode=source.slice(source.indexOf('    detach:(node,plan,asset'),source.indexOf('    flush:async id=>'));
const detachedContext={CanvasLayerDocument:D,nodes,tr:k=>k,pushUndo:()=>undo++,createNode:(x,y,images)=>{const n={id:'independent',x,y,images};nodes.push(n);return n;},scheduleSave(){},selectedIds:[],selectedImage:{}};
vm.runInNewContext('const adapter={'+detachCode+'};adapter.detach(nodes[0],plan,asset);',Object.assign(detachedContext,{plan,asset}));
const separate=nodes[1];assert.equal(undo,1);assert.equal(owner.layerDraft.layers.length,0);assert.equal(owner.layerDocument.layers.length,1);
for(const key of ['layerParentNodeId','sourceNodeId','sourceTaskId','layerTaskId'])assert.equal(separate[key],undefined);
separate.x+=500;assert.equal(owner.x,10);

// New boards reserve their final geometry and reuse existing free placement.
const placement={nodes:[{id:'input',x:0,y:0,w:260,h:390}],CanvasLayerDocument:D,CanvasLayerLayout:layout,tr:k=>k,render(){},scheduleSave(){},
    nodeRect:n=>({x:n.x,y:n.y,width:n.w,height:n.h}),createImageNodeAt(p,images){const n={id:String(this.nodes?.length||Math.random()),x:p.x,y:p.y,images};placement.nodes.push(n);return n;}};
vm.runInNewContext(source.slice(source.indexOf('function createSmartLayerBoard('),source.indexOf('async function openSmartLayerBoard('))+'\nfirst=createSmartLayerBoard({x:500,y:0},asset,{x:0,y:0,width:260,height:390});second=createSmartLayerBoard({x:500,y:0},asset,{x:0,y:0,width:260,height:390});',Object.assign(placement,{asset}));
assert.equal(placement.first.x,420);assert(placement.second.y>=placement.first.y+placement.first.h+100);

// Run the real clipboard functions, including multi-select and internal links.
const copiedDoc=D.fromOutputs([asset]);copiedDoc.layers[0].sourceNodeId='input';
const original={id:'board',type:'smart-image',x:20,y:30,layerDocument:copiedDoc,layerParentNodeId:'input',sourceTaskId:'old',layerTaskId:'old'};
let serial=0;
const clipboard={nodes:[original,{id:'input',x:0,y:0}],canvas:{connections:[{from:'input',to:'board'}]},selectedIds:['board'],selectedId:'',selectedImage:{},
    document:{activeElement:{}},isEditableTarget:()=>false,selectedNodeIds:()=>clipboard.selectedIds,uid:()=> 'copy-'+(++serial),
    clearSmartNodeTransientRunState(){},toast(){},pushUndo(){},render(){},scheduleSave(){},lastMouseWorld:{x:500,y:500},Date};
const clipCode=source.slice(source.indexOf('function cloneSmartNode('),source.indexOf('// 跨页"素材库'));
vm.runInNewContext(clipCode+'\ncopySelectedNodes();pasteNodes();',clipboard);
const copy=clipboard.nodes.at(-1);assert.equal(copy.layerParentNodeId,undefined);assert.equal(copy.sourceTaskId,undefined);assert.equal(copy.layerTaskId,undefined);
assert.equal(copy.layerDocument.layers[0].sourceNodeId,undefined);
copy.layerDocument.layers[0].x=999;assert.equal(original.layerDocument.layers[0].x,0);
clipboard.selectedIds=['input','board'];vm.runInNewContext('copySelectedNodes();pasteNodes();',clipboard);
const [inputCopy,boardCopy]=clipboard.nodes.slice(-2);
assert.equal(boardCopy.layerParentNodeId,inputCopy.id);assert.equal(boardCopy.layerDocument.layers[0].sourceNodeId,inputCopy.id);
assert.equal(clipboard.canvas.connections.at(-1).from,inputCopy.id);
// The existing marquee path must include layer boards, not just image outputs.
const marquee={selectionState:{startWorld:{x:0,y:0}},screenToWorld:()=>({x:200,y:200}),
    nodes:[{id:'board',layerDocument:doc,x:10,y:10},{id:'image',x:110,y:10},{id:'outside',x:300,y:10}],
    nodeRect:n=>({...n,width:50,height:50}),selectionBox:{style:{}},render(){},setTimeout(){}};
vm.runInNewContext(source.slice(source.indexOf('function finishSelection('),source.indexOf('function groupSelectedNodes('))+'\nfinishSelection({});',marquee);
assert.deepEqual(Array.from(marquee.selectedIds),['board','image']);
// Repeated moves must never replace the source with a scaled canvas export.
const originalPixels={url:'/assets/high-resolution.png',width:4096,height:3072,z_index:0};
let sharp=D.fromOutputs([originalPixels]);Object.assign(sharp.layers[0],{x:10.25,y:20.75,width:100,height:75});
for(let cycle=0;cycle<20;cycle++){
    const output=D.extractLayer(sharp,sharp.layers[0].id);
    assert.deepEqual(output.directAsset,originalPixels);assert.equal(output.bounds.width,100);
    const restored=D.placeLayer(output.document,{x:10.25,y:20.75,width:100,height:75});
    sharp={...sharp,layers:[restored]};assert.deepEqual(restored.asset,originalPixels);
}
let styled=D.clone(doc);
for(let cycle=0;cycle<20;cycle++){
    const output=D.extractLayer(styled,styled.layers[0].id),restored=D.placeLayer(output.document,output.bounds);
    assert.equal(output.directAsset,null);assert.equal(restored.asset.url,doc.layers[0].asset.url);
    assert.deepEqual(restored.crop,doc.layers[0].crop);assert.equal(restored.rotation,90);assert.equal(restored.opacity,.6);assert.equal(restored.flipX,true);
    styled={...styled,layers:[restored]};
}
// A canvas drag is a move, not an asset import: repeated in/out cycles conserve
// the number of image entities and undo restores both sides of each transfer.
const moving={CanvasLayerDocument:D,nodes:[{id:'target',x:0,y:0,w:340,layerDocument:D.fromOutputs([asset])},{id:'loose',x:500,y:500,images:[asset]}],
    canvas:{connections:[{from:'loose',to:'target'}]},selectedIds:[],selectedId:'loose',selectedImage:{},
    isSmartGroupNode:()=>false,undoStack:[],undoSuppressed:false,UNDO_LIMIT:40,render(){},scheduleSave(){},toast(){},tr:k=>k};
moving.createNode=(x,y,images)=>{const n={id:'loose-'+(++serial),x,y,images};moving.nodes.push(n);return n;};
const undoCode=source.slice(source.indexOf('function snapshotForUndo('),source.indexOf('let comfyWorkflowCache'));
const moveCode=source.slice(source.indexOf('    moveInto:(node,sourceId,doc)=>{'),source.indexOf('    detach:(node,plan,asset'));
vm.runInNewContext(undoCode+'\nconst adapter={'+moveCode+detachCode+'};',moving);
for(let cycle=0;cycle<5;cycle++){
    const target=moving.nodes[0],loose=moving.nodes[1],s=new Session(target);
    s.addImage(loose.images[0],100,80);moving.next=s.doc;moving.oldId=loose.id;
    vm.runInNewContext('adapter.moveInto(nodes[0],oldId,next);',moving);
    assert.equal(moving.nodes.length,1);assert.equal(moving.nodes[0].layerDraft.layers.length,2);
    assert.equal(moving.canvas.connections.some(c=>c.from===moving.oldId||c.to===moving.oldId),false);
    moving.plan=D.extractLayer(moving.next,moving.next.layers.at(-1).id);moving.asset=asset;
    vm.runInNewContext('adapter.detach(nodes[0],plan,asset);',moving);
    assert.equal(moving.nodes.length,2);assert.equal(moving.nodes[0].layerDraft.layers.length,1);
    assert.equal(moving.nodes.filter(n=>n.images).length,1);
}
vm.runInNewContext('performUndo();',moving);
assert.equal(moving.nodes.length,1);assert.equal(moving.nodes[0].layerDraft.layers.length,2);
vm.runInNewContext('performUndo();',moving);
assert.equal(moving.nodes.length,2);assert.equal(moving.nodes[0].layerDraft.layers.length,1);
console.log('Layer gestures, outside extraction, independent node, collision placement and multi-node clipboard passed');
console.log('Five move-in/out cycles conserve images; canvas undo restores both sides without copies');
(async()=>{
    const nodeJs=read('canvas-layer-node.js'),method=nodeJs.slice(nodeJs.indexOf('        async moveAsset('),nodeJs.indexOf('        async output('));
    const target={id:'target',x:10,y:20,w:340,layerDocument:D.fromOutputs([asset])};
    let movedDoc;
    const transfer={D,CanvasLayerSession:{Session},editor:{loadImage:async()=>({width:100,height:80})},
        adapter:{node:()=>null,moveInto:(node,id,doc)=>{movedDoc=doc;},render(){}},boards:new Map(),clearTimeout(){},setTimeout(){},t:k=>k};
    vm.runInNewContext('board={'+method+'};',transfer);Object.assign(transfer.board,{node:target,s:new Session(target),geometry:()=>({x:10,y:20,width:340})});
    let connected=true;
    transfer.board.geometry=()=>{assert(connected,'geometry must be captured before an async canvas render');return {x:10,y:20,width:340};};
    transfer.editor.loadImage=async()=>{connected=false;return {width:100,height:80};};
    await transfer.board.moveAsset(asset,'loose',{x:350,y:190,width:68,height:34});
    const layer=movedDoc.layers.at(-1);assert.deepEqual([layer.x,layer.y,layer.width,layer.height],[100,50,20,10]);
    assert.equal(layer.sourceNodeId,undefined);assert.equal(target.layerDocument.layers.length,1);
    const before=JSON.stringify(transfer.board.s.doc);movedDoc=null;connected=true;
    transfer.editor.loadImage=async()=>{throw new Error('decode failed');};
    await assert.rejects(transfer.board.moveAsset(asset,'loose',{}),/decode failed/);
    assert.equal(movedDoc,null);assert.equal(JSON.stringify(transfer.board.s.doc),before);assert.equal(transfer.board.s.busy,false);
    const preview={url:'/assets/transformed-preview.png',width:200,height:100};
    transfer.adapter.node=()=>({layerElement:{previewUrl:preview.url,document:plan.document}});
    transfer.editor.loadImage=async()=>({width:200,height:100});
    await transfer.board.moveAsset(preview,'loose',{x:350,y:190,width:80,height:100});
    const recovered=movedDoc.layers.at(-1);
    assert.equal(recovered.asset.url,doc.layers[0].asset.url);assert.equal(recovered.rotation,90);
    assert.deepEqual(recovered.crop,doc.layers[0].crop);assert.equal(recovered.opacity,.6);assert.equal(recovered.flipX,true);
    assert.notEqual(recovered.id,doc.layers[0].id);
    await transfer.board.moveAsset({url:'/assets/new-edit.png'},'loose',{x:350,y:190,width:80,height:100});
    assert.equal(movedDoc.layers.at(-1).asset.url,'/assets/new-edit.png','newly edited content must not restore stale pixels');
    const detachMethod=nodeJs.slice(nodeJs.indexOf('        async detach('),nodeJs.indexOf('        popupHtml('));
    let sourceFile;
    const direct={D,boards:new Map(),document:{createElement(){throw new Error('A plain move must not rasterize');}},
        adapter:{upload(){throw new Error('A plain move must not upload a replacement');},detach:(node,plan,asset)=>{sourceFile=asset;},render(){}},clearTimeout(){},setTimeout(){}};
    vm.runInNewContext('board={'+detachMethod+'};',direct);
    Object.assign(direct.board,{s:new Session({layerDocument:sharp}),node:{id:'one'},geometry:()=>({x:0,y:0,width:340})});
    await direct.board.detach(direct.board.s.doc.layers[0]);assert.deepEqual(sourceFile,originalPixels);
    console.log('Move preserves drop geometry and decode failure changes neither side');
    console.log('Twenty plain/styled round trips preserve original pixels and effects; plain move never rasterizes');
})().catch(error=>{console.error(error);process.exitCode=1;});
