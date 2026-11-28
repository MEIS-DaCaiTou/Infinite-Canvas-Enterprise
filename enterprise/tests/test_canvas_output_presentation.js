const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const ctx={window:{}};
vm.runInNewContext(fs.readFileSync('static/js/canvas-output-presentation.js','utf8'),ctx);
const presentation=ctx.window.CanvasOutputPresentation;
const plain=value=>JSON.parse(JSON.stringify(value));
const smartSource=fs.readFileSync('static/js/smart-canvas.js','utf8');
function smartActual(name){
    const match=new RegExp('(?:async )?function '+name+'\\(').exec(smartSource);assert(match,name);
    const end=smartSource.slice(match.index+match[0].length).search(/\n(?:async )?function \w+\(/);
    return smartSource.slice(match.index,end<0?undefined:match.index+match[0].length+end);
}
const smart={CanvasOutputPresentation:presentation,CanvasTaskQuery:{runTiming:()=>null},
    pendingSmartGenerationLog:()=>({}),recordSmartPendingGenerationLog:()=>{},nowMs:()=>1000,
    smartPendingTasks:node=>node.pendingTasks || [],resultMediaUrls:value=>value,
    cleanHistoryImages:value=>value,stripImageGenerationMeta:value=>value,copyMediaSizeFields:(_item,value)=>value,
    mediaNodeDefaultScale:node=>node?.scale || 1,MEDIA_NODE_DEFAULT_SCALE:1,
    MEDIA_GROUP_DEFAULT_SCALE:1,MEDIA_GROUP_PREVIOUS_DEFAULT_SCALE:.5,MEDIA_GROUP_THUMB_BASE:180,MEDIA_GROUP_MAX_VISIBLE_ROWS:4,
    singleImageLayout:()=>({width:100,height:150,single:true}),
    imageForDisplay:value=>value,mediaKindForItem:()=> 'image',smartRecoverableImageTask:()=>null,selectedImage:{nodeId:'',index:-1},
    thumbMediaHtml:item=>`<img src="${item.url}">`,imageNameBadgeHtml:()=>'',imageResolutionBadgeHtml:()=>'',
    escapeHtml:String,escapeAttr:String,tr:key=>key,
    cloneSmartSettings:value=>({...value}),stripOutpaintDisplaySettings:value=>({...value}),
    withOutpaintDisplaySettings:(_node,value)=>value,normalizeSmartVideoModeSettings:()=>{},
    canvasDefaultSmartSettings:{count:8,model:'default'},initialSmartSettings:{},
    recentSmartSettingsForMode:()=>({count:3,model:'recent'}),
    settings:{engine:'api',count:1},smartSettingsModeKey:()=> 'api:image',isApiLikeEngine:()=>true,
    clearVolcengineSelectionOutsideVolcengine:()=>{},sanitizeSmartApiSelection:()=>{},
};
vm.createContext(smart);
for(const name of ['groupImageGridLayout','imageLayout','nodeBodyHtml','smartImageTaskStatusHtml',
    'appendSmartPendingResults','finalizeSmartPendingTask','smartNodeHasLiveMedia',
    'smartSettingsForNode','applyRecentSmartSettingsForCurrentMode']) vm.runInContext(smartActual(name),smart);
const batch={id:'batch',type:'smart-image',images:[],pending:3,w:420,h:420,scale:1,
    pendingTasks:['a','b','c'].map((taskId,imageIndex)=>({taskId,imageIndex,imageStatus:'供应商已受理'}))};
const bounds=()=>plain(smart.imageLayout(batch.images,1,batch));
const originalBounds=bounds();
assert.equal(presentation.smartEntries(batch).length,3);
assert.equal(smart.smartImageTaskStatusHtml(batch),'','routine receipts must not appear on the node');
smart.appendSmartPendingResults(batch,[{url:'/b.png'}],'image',batch.pendingTasks[1]);
assert.deepEqual(plain(presentation.smartEntries(batch)).map(e=>e.item?.url || e.pending.taskId),['a','/b.png','c']);
assert.deepEqual(bounds(),originalBounds,'the first result must retain the reserved group dimensions');
const partialBody=smart.nodeBodyHtml(batch,originalBounds);
assert.equal((partialBody.match(/smart-output-placeholder/g)||[]).length,2);
assert(!partialBody.includes('image-wrap'),'a partial batch must not turn into one enlarged image');
assert(smart.smartNodeHasLiveMedia(batch),'returned media must remain reusable while other tasks are pending');
smart.finalizeSmartPendingTask(batch,'b',[{url:'/b.png'}]);
assert.equal(batch.images.length,1,'final receipt must not duplicate its earlier partial image');
const restart=plain(batch);
smart.finalizeSmartPendingTask(restart,'c',[{url:'/c.png'}]);
smart.finalizeSmartPendingTask(restart,'a',[{url:'/a.png'}]);
assert.deepEqual(plain(restart.images).map(item=>item.url),['/a.png','/b.png','/c.png']);
assert.equal(restart.pending,0);assert.equal(restart.w,420);assert.equal(restart.h,420);
assert.deepEqual(plain(smart.imageLayout(restart.images,1,restart)),originalBounds,'batch completion keeps its geometry');
assert(!smart.nodeBodyHtml(restart,originalBounds).includes('smart-output-placeholder'));
assert.equal(presentation.smartEntries({images:[{url:'/old.png'}],pending:3,
    pendingTasks:['a','b','c'].map((taskId,imageIndex)=>({taskId,imageIndex}))}).length,3,'legacy partial output must not add a fourth slot');
const needsReview={pendingTasks:[{taskId:'original',imageIndex:0,imageStatus:'结果待核对',failed:true,canReconcile:true,error:'query interrupted'}]};
assert(smart.smartImageTaskStatusHtml(needsReview).includes('data-task-id="original"'),'original-task query remains available');
assert.equal(smart.smartSettingsForNode({}).count,1,'new nodes ignore recent/canvas batch counts');
assert.equal(smart.smartSettingsForNode({runSettings:{count:3}}).count,3,'explicit saved node counts remain unchanged');
smart.applyRecentSmartSettingsForCurrentMode();
assert.equal(smart.settings.count,1,'mode switching cannot restore the recent batch count');
assert.equal(smart.settings.model,'recent','other recent choices still work');
const node={images:[{url:'/old.png',run:{request:{model:'old-model'}}}],_pending:[]};
const a={id:'a',canvasTaskId:'task-a',model:'model-a'},b={id:'b',canvasTaskId:'task-b',model:'model-b'};
presentation.reserve(node,[a]);node._pending.push(a);
presentation.reserve(node,[b]);node._pending.push(b);
assert(a.outputOrder<b.outputOrder);
const result=(task,url)=>({url,run:{canvasTaskId:task.canvasTaskId,outputOrder:task.outputOrder,request:{model:task.model},refs:[{url:'/input1.png'},{url:'/input2.png'}]}});
node.images.push(result(b,'/b.png'));
assert.deepEqual(plain(presentation.entries(node)).map(e=>e.item?.url||e.pending.id),['/old.png','a','/b.png']);
assert.equal(presentation.entries(node).filter(e=>!e.item).length,1,'a partial result replaces only its own placeholder');
assert.equal(presentation.entries(node).at(-1).pending,b,'tracking status remains attached to the returned image');
// Return order is deliberately reversed; reload must retain original submission positions.
const reopened=plain(node);
reopened.images.push(result(a,'/a.png'));
assert.deepEqual(plain(presentation.images(reopened)).map(e=>e.url),['/old.png','/a.png','/b.png']);
assert.equal(presentation.entries(reopened).filter(e=>!e.item).length,0,'no second card for a returned task');
assert.equal(presentation.model(reopened.images.find(e=>e.url==='/a.png')),'model-a');
assert.equal(presentation.model(null,b),'model-b');
reopened._pending=[];
assert.deepEqual(plain(presentation.images(reopened)).map(e=>e.url),['/old.png','/a.png','/b.png']);
const refs=presentation.references({run:{refs:[{url:'/top.png',name:'上衣'},{url:'/pants.png',name:'裤装'},
    {url:'/shoes.png',name:'鞋'},{url:'/top.png'},{url:'/motion.mp4',kind:'video'}]}},{url:'/top.png'});
assert.deepEqual(plain(refs).map(e=>e.url),['/top.png','/pants.png','/shoes.png']);
assert.equal(refs[2].name,'鞋');
assert.equal(presentation.references(null,'/legacy-input.png')[0].url,'/legacy-input.png');
assert.equal(presentation.model({url:'/unknown.png'}),'','do not infer old models from the current generator');
const source=fs.readFileSync('static/js/canvas.js','utf8');
function actual(name){
    const match=new RegExp('(?:async )?function '+name+'\\(').exec(source);assert(match,name);
    const end=source.slice(match.index+match[0].length).search(/\n(?:async )?function \w+\(/);
    return source.slice(match.index,end<0?undefined:match.index+match[0].length+end);
}
Object.assign(ctx,{CanvasOutputPresentation:presentation,escapeAttr:value=>String(value).replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;').replaceAll('>','&gt;'),
    escapeHtml:value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'),
    outputUrlValue:item=>typeof item==='string'?item:item.url,mediaKindForOutputItem:()=> 'image',isMissingAssetUrl:()=>false,
    canvasPreviewImgHtml:url=>`<img src="${url}">`,formatRunDuration:()=> '1s',pendingOutputStyle:()=>'',
    tr:value=>value,nowMs:()=>1000,langIsEn:()=>false});
for(const name of ['outputResultCaption','outputResultTimePill','renderOutputMedia','renderPendingOutput','outputGridLayout','renderOutputGrid'])vm.runInNewContext(actual(name),ctx);
const partialHtml=ctx.renderOutputGrid(node);
assert.equal((partialHtml.match(/class="output-img-wrap/g)||[]).length,3,'actual renderer has no fourth ghost card');
assert(partialHtml.indexOf('data-pending-id="a"')<partialHtml.indexOf('/b.png'));
assert(partialHtml.includes('model-a')&&partialHtml.includes('model-b'));
assert(ctx.outputResultCaption({run:{request:{model:'<unsafe>'}}}).includes('&lt;unsafe&gt;'));
assert(ctx.outputResultCaption(result(b,'/b.png'),{...b,failed:true,retryReceipt:true}).includes('data-output-query="b"'),'partial results retain original-task lookup');
// A partial card becomes final in place: correct its time/status without replacing its media.
const finalNode={id:'result',images:[{url:'/b.png',runMs:16000,run:{request:{model:'model-b'}}}],_pending:[]};
const badges={'.output-result-caption':{outerHTML:'old partial status'},'.output-time-pill':{outerHTML:'old running duration'}};
const retained={dataset:{outputUrl:'/b.png'},querySelector:selector=>badges[selector]||null};
const grid={children:[retained],classList:{toggle(){}},style:{removeProperty(){}}};
const body={querySelector:()=>grid},element={querySelector:()=>body};
Object.assign(ctx,{nodesEl:{querySelector:()=>element},CSS:{escape:value=>value},bindOutputWrap:()=>assert.fail('do not replace media'),
    bindCanvasPreviewImageFallbacks(){},syncCanvasSelectedImageResolution(){},refreshOutputTimer(){},formatRunDuration:ms=>`${ms/1000}s`});
for(const name of ['outputDomKeyForItem','outputDomKeyForPending','refreshOutputNodeContent'])vm.runInNewContext(actual(name),ctx);
assert(ctx.refreshOutputNodeContent(finalNode));
assert.equal(grid.children[0],retained);
assert.equal(badges['.output-time-pill'].outerHTML,'<span class="output-time-pill">16s</span>');
assert(!badges['.output-result-caption'].outerHTML.includes('partial'));
const recoveryListeners={},lookups=[],partialNode={images:[],_pending:[{id:'b',canvasTaskId:'task-b',retryReceipt:true}]};
const partialWrap={dataset:{},querySelector:()=>null,addEventListener:(name,handler)=>recoveryListeners[name]=handler};
Object.assign(ctx,{bindOutputDrag(){},comfyTaskControls:{bindOutput(){}},pollCanvasImageTask:id=>lookups.push(id)});
for(const name of ['pendingById','bindOutputWrap'])vm.runInNewContext(actual(name),ctx);
ctx.bindOutputWrap(partialWrap,partialNode);
recoveryListeners.click({target:{closest:()=>({dataset:{outputQuery:'b'}})},preventDefault(){},stopPropagation(){}});
assert.deepEqual(lookups,['task-b'],'query the original task without a generation request');
// Exercise the real picker event handler; selecting any input only changes comparison state.
const classes=new Set(['compare-mode']);let resets=0;
const sourceButtons=refs.map((ref,index)=>({dataset:{compareSource:String(index)},setAttribute(key,value){this[key]=value;}}));
const anchorImage={src:''},anchorCount={textContent:''};
Object.assign(ctx,{currentOutputCompareRefs:plain(refs),currentOutputCompareUrl:refs[0].url,
    outputCompareSources:{addEventListener(){},innerHTML:'',hidden:true,querySelectorAll:()=>sourceButtons,
        querySelector:selector=>selector==='[data-compare-current]'?anchorImage:anchorCount},
    outputPreview:{classList:{contains:key=>classes.has(key),toggle:(key,on)=>on?classes.add(key):classes.delete(key)}},
    outputCompareOriginal:{src:''},outputCompareOriginalWrap:{style:{clipPath:'inset(0 31% 0 0)'}},
    outputCompareSlider:{style:{left:'69%'},addEventListener(){}},
    outputCompareContainer:{addEventListener(){}},window:{addEventListener(){}},
    canvasDisplayMediaUrl:url=>url,outputDownloadName:url=>url,resetOutputPreviewZoom:()=>resets++,
    fetch:()=>{throw new Error('comparison must never submit');}});
for(const name of ['renderOutputCompareSources','setOutputCompareMode','initOutputCompareEvents'])vm.runInNewContext(actual(name),ctx);
ctx.initOutputCompareEvents();ctx.renderOutputCompareSources();
assert(ctx.outputCompareSources.innerHTML.includes('输入图 3'));
assert(ctx.outputCompareSources.innerHTML.includes('output-compare-source-drawer'));
assert(ctx.outputCompareSources.innerHTML.includes('>1/3</span>'));
assert(!ctx.outputCompareSources.innerHTML.includes('data-compare-toggle'));
assert(!ctx.outputCompareSources.innerHTML.includes('output-compare-sources-label'));
ctx.outputCompareSources.onclick({stopPropagation(){},target:{closest:()=>sourceButtons[2]}});
assert.equal(ctx.outputCompareOriginal.src,'/shoes.png');assert(classes.has('compare-mode'));assert.equal(resets,0);
assert.equal(anchorImage.src,'/shoes.png');assert.equal(anchorCount.textContent,'3/3');
assert.equal(ctx.outputCompareOriginalWrap.style.clipPath,'inset(0 31% 0 0)');
assert.equal(ctx.outputCompareSlider.style.left,'69%');assert.equal(sourceButtons[2]['aria-pressed'],'true');
assert.equal(sourceButtons[0]['aria-pressed'],'false');
classes.delete('compare-mode');
ctx.outputCompareSources.onclick({stopPropagation(){},target:{closest:()=>sourceButtons[1]}});
assert(!classes.has('compare-mode'),'changing the source does not change the existing comparison mode');
assert.equal(ctx.outputCompareSlider.style.left,'69%');assert.equal(resets,0);
for(const count of [0,1]){
    ctx.currentOutputCompareRefs=plain(refs.slice(0,count));ctx.renderOutputCompareSources();
    assert(ctx.outputCompareSources.hidden);assert.equal(ctx.outputCompareSources.innerHTML,'');
}
ctx.currentOutputCompareRefs=Array.from({length:7},(_,i)=>({url:`/ref${i}.png`}));
ctx.renderOutputCompareSources();assert(!ctx.outputCompareSources.hidden);
assert.equal((ctx.outputCompareSources.innerHTML.match(/data-compare-source=/g)||[]).length,7,'all inputs remain reachable');
console.log('output presentation: reserved submission order, partial replacement, reload, frozen models and all input references passed');
