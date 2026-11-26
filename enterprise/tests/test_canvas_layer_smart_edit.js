const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.resolve(__dirname,'../..'),read=name=>fs.readFileSync(path.join(root,'static/js',name),'utf8');
const D=require('../../static/js/canvas-layer-document.js'),{Session}=require('../../static/js/canvas-layer-session.js');
const context={window:{StudioI18n:{t:k=>k,lang:()=> 'zh'},CanvasLayerDocument:D},document:{querySelectorAll:()=>[]},
    fetch:async()=>({ok:true,json:async()=>({favorites:[],view:'all'})})};
vm.runInNewContext(read('model-picker.js'),context);vm.runInNewContext(read('canvas-layer-smart-prompt.js'),context);vm.runInNewContext(read('canvas-layer-edit-result.js'),context);vm.runInNewContext(read('canvas-layer-smart-edit.js'),context);
const E=context.window.CanvasLayerSmartEdit;
const P=context.window.CanvasLayerSmartPrompt;
assert.equal(P.needsMultiline('短描述',180,180),false);
assert.equal(P.needsMultiline('',0,180),false);
assert.equal(P.needsMultiline('自动折行',181,180),true);
assert.equal(P.needsMultiline('第一行\n第二行',40,500),true);
assert.equal(P.needsMultiline('窄窗口',40,0),true);
const marker={id:'stable-box',kind:'marker',number:1,points:[{x:.2,y:.3}],rect:{x:.2,y:.3,width:.1,height:.2}};
const pointMarker={id:'stable-point',kind:'marker',number:3,points:[{x:.99,y:0}]};
const sourcePixels={width:1000,height:1000};
assert.deepEqual(JSON.parse(JSON.stringify(P.thumbnailCrop(marker,sourcePixels))),{x:126,y:276,width:248,height:248});
assert.deepEqual(JSON.parse(JSON.stringify(P.thumbnailCrop(pointMarker,sourcePixels))),{x:820,y:0,width:180,height:180});
const frame=P.previewFrame(marker,sourcePixels,true);
assert(Math.abs(marker.rect.height*sourcePixels.height*frame.scale-132)<.001);
assert.equal(P.previewFrame(marker,sourcePixels,false).target.x,70);
const draft='先改【3】的颜色，再把【1】改成秋冬特惠\n保留【99】原文';
const tokens=P.parts(draft,[marker,pointMarker]);
assert.deepEqual(Array.from(tokens.filter(p=>p.mark),p=>p.mark.id),['stable-point','stable-box']);
assert.equal(tokens.map(p=>p.text??'【'+p.mark.number+'】').join(''),draft,'inline references preserve their position and unknown literal text');
const domText=text=>({nodeType:3,textContent:text}),domElement=(name,children=[],attributes={})=>({nodeType:1,nodeName:name,childNodes:children,getAttribute:key=>attributes[key]});
const atom=domElement('SPAN',[domText('1')],{'data-edit-reference':'stable-box','data-reference-text':'【1】'});
assert.equal(P.serialize(domElement('DIV',[domText('修改'),atom,domText('后保留\n文字')])),'修改【1】后保留\n文字','thumbnail and pin captions cannot leak into the API prompt');
assert.equal(P.serialize(domElement('DIV',[domElement('DIV',[domText('甲')]),domElement('DIV',[atom])])),'甲\n【1】');
assert.equal(P.serialize(domElement('DIV',[domText('甲'),domElement('BR'),domElement('BR',[],{'data-edit-tail':'true'})])),'甲\n','a visual end-of-line caret is not an extra newline in the request');
assert.equal(E.hasAlpha(new Uint8ClampedArray([1,2,3,255,4,5,6,255])),false);
assert.equal(E.hasAlpha(new Uint8ClampedArray([1,2,3,255,4,5,6,0])),true);
const gpt={mode:'pixel',supports_auto_size:true,supports_custom_size:true,supports_quality:true,
    size_rules:{max_edge:3840,multiple:16,max_aspect:3,min_pixels:655360,max_pixels:8294400}};
const seedream={mode:'pixel',resolutions:['1K','1.5K','2K'],max_references:10,supports_custom_size:true,
    size_rules:{min_pixels:921600,max_pixels:4624220,max_aspect:16}};
const config={api_providers:[{id:'t8',name:'贞贞',managed_source_supported:true,image_models:['seedream-v5.5','gpt-image-2','layers','text-only'],
    builtin_model_image_profiles:{'seedream-v5.5':seedream,'gpt-image-2':gpt,layers:{layer_output:true},'text-only':{max_references:0}}},
    {id:'disabled',enabled:false,image_models:['model']}]};
const models=E.modelsFor(config);assert.equal(models.length,2);assert.equal(models[0].managedSource,true);
// Use the actual API node's source-aspect size calculation.
const smartSource=read('smart-canvas.js'),start=smartSource.indexOf('function apiImageSize(');
const sizeContext=vm.createContext({window:context.window,parseRatioValue:value=>{const [w,h]=value.split(':').map(Number);return w/h;}});
for(const constant of ['RES_LONG_SIDE','RES_PIXEL_LIMIT'])vm.runInContext(smartSource.match(new RegExp('^const '+constant+' = .*;$','m'))[0],sizeContext);
vm.runInContext(smartSource.slice(start,smartSource.indexOf('\n}',start)+2),sizeContext);
const sizeFor=(ratio,res)=>sizeContext.apiImageSize('source',res,ratio),doc={width:1024,height:1536};
const seedChoices=E.resolutionsFor(models[0],doc,sizeFor);
assert.deepEqual(Array.from(seedChoices,c=>c.value),['1k','1.5k','2k']);
assert(seedChoices.every(c=>!c.error&&c.size!=='auto'));assert.equal(seedChoices[0].size,'1024x1536');
const gptChoices=E.resolutionsFor(models[1],doc,sizeFor);
assert(gptChoices.some(c=>c.value==='1k'));assert(!gptChoices.some(c=>c.value==='4k'));
assert(E.parametersFor(models[1],doc,'4k',sizeFor).error);
const aspect={profile:{mode:'aspect-size',ratios:['3:4'],fixed_resolution:'2K',supports_image_size:false}};
assert.equal(E.resolutionsFor(aspect,{width:300,height:400},sizeFor)[0].parameters.resolution,'2K');
assert.equal(E.resolutionsFor(aspect,{width:3,height:8},sizeFor).length,0,'an unsupported aspect is never offered');
const preset={profile:{mode:'pixel',supports_custom_size:false,size_presets:['1024x1024','1536x1024']}};
assert.deepEqual(Array.from(E.resolutionsFor(preset,doc,sizeFor),c=>c.size),['1024x1024','1536x1024']);
assert.equal(E.hasInstruction('【1】 【2】'),false);assert.equal(E.hasInstruction('【1】改为酒红色'),true);
const marks=[{kind:'marker',number:1,points:[{x:.2,y:.3}],rect:{x:.2,y:.3,width:.1,height:.2}},
    {kind:'arrow',points:[{x:.1,y:.1},{x:.5,y:.6}]},{kind:'text',text:'新文字',points:[{x:.3,y:.2}]}];
const prompt=E.protocolPrompt('【1】改为酒红色',marks);assert(prompt.includes('(200,300)–(300,500)'));assert(prompt.includes('第一张为原图'));assert(prompt.includes('新文字'));
const asset={url:'/assets/clothing.png',width:1018,height:1030};
const session=new Session({images:[asset]}),layer=session.doc.layers[0];layer.width=130;layer.height=132;layer.x=55;layer.y=30;layer.opacity=.6;
layer.crop={x:.1,y:.1,width:.6,height:.6};
const native=E.sourceDocument(layer,{width:1018,height:1030});assert(native.width>=610);assert(native.height>=618);assert.equal(native.layers[0].opacity,1);
assert.equal(layer.opacity,.6);assert.equal(native.layers[0].asset.url,asset.url);
const binding={layerId:layer.id,sourceKey:E.sourceKey(layer)},item={url:'/assets/edited.png',width:1024,height:1536};
session.selected=layer.id;session.tool='mask';assert.equal(E.applyResult(session,binding,'original-task',item),'source-changed');assert.equal(layer.visible,true);
session.tool='select';
layer.x=200; // Moving the original while waiting keeps its current placement.
assert.equal(E.applyResult(session,binding,'original-task',item),'applied');assert.equal(session.doc.layers.length,2);assert.equal(layer.visible,false);
const derived=session.layer();assert(derived.x>=200);assert.equal(derived.opacity,.6);assert.equal(derived.flipX,false);assert.equal(derived.crop,undefined);
assert.equal(E.applyResult(session,binding,'original-task',item),'applied');assert.equal(session.doc.layers.length,2,'re-reading the original task cannot add another layer');
session.history(-1);assert.equal(session.doc.layers.length,1);assert.equal(session.doc.layers[0].visible,true);
session.doc.layers[0].asset.url='/assets/user-changed.png';assert.equal(E.applyResult(session,binding,'original-task',item),'source-changed');assert.equal(session.doc.layers.length,1);
session.doc.layers[0].asset.url=asset.url;session.selected='another-layer';assert.equal(E.applyResult(session,binding,'next-task',item),'applied');assert.equal(session.selected,'another-layer','background completion must not steal another layer selection');
// Closing destroys transient UI state, so a board reselect cannot reopen it.
let restored=0,closed=0;
const controller=Object.create(E.SmartEdit.prototype);controller.state={viewport:{id:'view'}};controller.portal={hidden:false,replaceChildren(){},querySelector:()=>null};
controller.adapter={restoreViewport:()=>restored++,onEditClose:()=>closed++};context.cancelAnimationFrame=()=>{};
controller.close();controller.close();assert.equal(restored,1);assert.equal(closed,1);assert.equal(controller.state,null);assert.equal(controller.portal.hidden,true);
let hostClosed=0,hostRestored=0,mounted=0;
context.document.body={append:()=>mounted++};
const embedded=Object.create(E.SmartEdit.prototype);embedded.state={viewport:{zoom:1},presentation:{fullscreen:true,restoreViewport:()=>hostRestored++,onEditClose:()=>hostClosed++}};
embedded.portal={hidden:false,replaceChildren(){},querySelector:()=>null};embedded.adapter={onEditClose:()=>{throw Error('host close cannot trigger outer canvas lifecycle');}};
embedded.close();assert.equal(hostClosed,1);assert.equal(hostRestored,1);assert.equal(mounted,1);
// A text draft must not be drawn below its live transparent textarea.
let textPaints=0;const editingMarks={width:0,height:0,style:{},getContext:()=>({clearRect(){},save(){},restore(){},fillText(){textPaints++;}})};
const textController=Object.create(E.SmartEdit.prototype);textController.state={base:{width:100,height:100},marks:[{id:'text',kind:'text',text:'保留纹理',points:[{x:.1,y:.2}],fontSize:.1}],selected:'text',textEditing:true,tool:'text'};
textController.portal={querySelector:key=>key==='[data-edit-marks]'?editingMarks:null};textController.paintMarkers=textController.paintTextSelection=()=>{};
textController.paint();assert.equal(textPaints,0);textController.state.textEditing=false;textController.paint();assert.equal(textPaints,1);
let refreshedControls=0;const rejected=Object.create(E.SmartEdit.prototype);rejected.state={pendingTaskId:'opaque-task'};rejected.render=()=>refreshedControls++;
rejected.completed({sourceTaskId:'opaque-task'},'alpha-missing');assert.equal(rejected.state.pendingTaskId,'');assert.equal(refreshedControls,1,'failed visual validation must re-enable model and tool controls');
// During a canvas rerender, later layers mount after the base image decodes.
// A missing DOM rectangle for one frame must not close the focused editor.
context.innerWidth=1200;context.innerHeight=800;
const stage={style:{}},controls={style:{},offsetHeight:140},pendingLayout=Object.create(E.SmartEdit.prototype);
pendingLayout.state={nodeId:'board',layerId:'second',bounds:{left:300,top:90,width:350,height:400,bottom:490}};
pendingLayout.adapter={layerBounds:()=>undefined};pendingLayout.portal={querySelector:s=>s==='.layer-smart-stage'?stage:s==='.layer-smart-controls'?controls:null};pendingLayout.close=()=>{throw Error('Async layer mount is not a close action');};
pendingLayout.layout();assert.equal(stage.style.width,'350px');assert.equal(controls.style.top,'506px');
// Execute the actual adapter: two references use ONE original image task;
// internal UI bindings are saved on the node, never sent to the provider.
const adapterCode=smartSource.slice(smartSource.indexOf('    separate:async(id,index,parameters)=>{'),smartSource.indexOf('    query:async id=>'));
let posted=0,requestPayload,target;
const execution={canvas:{id:'qa'},nodes:[{id:'source',images:[asset],layerDocument:D.fromOutputs([asset])}],
    pushUndo(){},render(){},scheduleSave(){},tr:k=>k,structuredClone,
    createLayerResultNode:(original,document,images,settings,options)=>{assert.equal(options.select,false);target={id:'out',images};return target;},
    taskCanvasSource:async node=>({canvas_id:'qa',node_id:node.id}),
    CanvasTaskQuery:{imageRequest:payload=>{requestPayload=payload;return {taskId:'original-task',payload};},submitImage:async()=>{posted++;return {task_id:'original-task'};}},
    resumeSmartPendingNode:async()=>{},toast:()=>{}};
vm.runInNewContext('adapter={'+adapterCode+'};',execution);
(async()=>{
    const cancelSession=new Session({id:'cancel-board',images:[asset]}),cancelNode=cancelSession.node,cancelLayer=cancelSession.doc.layers[0];
    const reopen=Object.create(E.SmartEdit.prototype);let cancelledInput=0,openedState;
    const acceptedTasks=[{taskId:'already-accepted'}];cancelNode.pendingTasks=acceptedTasks;
    reopen.adapter={node:()=>cancelNode,pendingEdit:()=>acceptedTasks[0].taskId,onEditOpen(){},onEditClose(){},restoreViewport(){}};
    reopen.portal={hidden:false,classList:{toggle(){}},replaceChildren(){},querySelector:()=>null};reopen.render=()=>{openedState={marks:reopen.state.marks,prompt:reopen.state.prompt,undo:reopen.state.undo,redo:reopen.state.redo};};
    reopen.state={marks:[marker],prompt:'取消的描述',undo:[{}],redo:[{}]};reopen.textInput={cancel(){assert.equal(reopen.state,null);cancelledInput++;}};
    reopen.close();assert.equal(cancelledInput,1);
    context.CanvasLayerSession={get:()=>cancelSession};const originalFetch=context.fetch;context.fetch=async()=>({ok:false});
    await reopen.open(cancelNode.id,cancelLayer.id);assert.equal(openedState.marks.length,0);assert.equal(openedState.prompt,'');assert.equal(openedState.undo.length,0);assert.equal(openedState.redo.length,0);
    assert.equal(reopen.state.pendingTaskId,'already-accepted');assert.equal(cancelNode.pendingTasks,acceptedTasks,'discarding UI marks cannot discard an accepted task');reopen.close();context.fetch=originalFetch;
    const rgba=new Uint8ClampedArray([0,0,0,255,10,20,30,255]);
    context.document.createElement=()=>({getContext:()=>({drawImage(){},getImageData:()=>({data:rgba})})});
    const outputCheck=Object.create(E.SmartEdit.prototype);outputCheck.editor={loadImage:async()=>({width:2,height:1})};
    assert.equal(await outputCheck.validateOutput({preserveAlpha:true},item),'alpha-missing');
    rgba[7]=0;assert.equal(await outputCheck.validateOutput({preserveAlpha:true},item),'ready');
    assert.equal(await outputCheck.validateOutput({preserveAlpha:false},item),'ready');
    const localAsset={url:'/assets/local-edit.png',width:200,height:300};let localPreparations=0;
    const realPrepare=context.window.CanvasLayerEditResult.prepare;
    context.window.CanvasLayerEditResult.prepare=async()=>{localPreparations++;return localAsset;};
    const localBinding={regionEdit:{source:asset,width:200,height:300,regions:[marker.rect],keepAlpha:true}};
    outputCheck.adapter={upload(){throw Error('The prepared result must be reused');}};
    const localResults=await Promise.all([outputCheck.prepareOutput(localBinding,item),outputCheck.prepareOutput(localBinding,item)]);
    assert.equal(localPreparations,1,'concurrent original-task readback prepares one derived image');
    assert.equal(localResults[0].item,localAsset);assert.equal(localResults[1].state,'ready');
    await outputCheck.prepareOutput(JSON.parse(JSON.stringify(localBinding)),item);
    assert.equal(localPreparations,1,'saved derived asset remains reusable after reopening');
    context.window.CanvasLayerEditResult.prepare=realPrepare;
    // Execute the actual completion hook. An opaque result from a transparent
    // source stays an archived output, without hiding or modifying the source.
    const hookCode=smartSource.slice(smartSource.indexOf('async function applySmartLayerEditResult('),smartSource.indexOf("world.addEventListener('pointerdown',event=>{if(layerCanvasPick"));
    const original={id:'source'},out={id:'out',sourceTaskId:'same-task',layerEditTarget:{nodeId:'source',preserveAlpha:true}};
    let notices=0,finished;
    const hook={canvas:{id:'same-canvas'},nodes:[original,out],canvasLayerEditor:{smartEdit:{prepareOutput:async()=> ({state:'alpha-missing',item}),completed:(_n,result)=>{finished=result;}}},
        CanvasLayerSmartEdit:{applyResult(){throw Error('An opaque result must not replace the transparent source');}},render(){},scheduleSave(){},toast(){notices++;},tr:k=>k};
    vm.createContext(hook);vm.runInContext(hookCode,hook);await hook.applySmartLayerEditResult(out,item);
    assert.equal(out.layerEditTarget.state,'alpha-missing');assert.equal(finished,'alpha-missing');assert.equal(notices,1);
    await execution.adapter.separate('source',0,{provider_id:'t8',model:'gpt-image-2',size:'1024x1536',prompt,
        _references:[asset,{url:'/assets/guide.png'}],_editTarget:binding,_stayOnSource:true});
    assert.equal(posted,1);assert.equal(requestPayload.reference_images.length,2);assert.equal(requestPayload._editTarget,undefined);assert.equal(requestPayload._stayOnSource,undefined);
    assert.deepEqual(target.layerEditTarget,binding);assert.equal(target.sourceTaskId,'original-task');assert.equal(target.pendingTasks[0].taskId,'original-task');
    assert.equal(requestPayload.source.node_id,'out');
    console.log('Focused smart edit: model contracts, native source, mark input, original task, idempotent layer application and close lifecycle passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
