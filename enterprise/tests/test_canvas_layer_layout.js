const assert=require('node:assert/strict');
const {resultRect,frame}=require('../../static/js/canvas-layer-layout.js');
const source={x:400,y:100,width:340,height:258};
const doc={width:1536,height:1168};
const first=resultRect(source,doc,[]);
assert.equal(first.x,900);assert.equal(first.width,340);assert.equal(first.height,259);
const second=resultRect(source,doc,[first]);assert.equal(second.y,first.y+first.height+100);
assert.equal(second.x,first.x);
const third=resultRect(source,doc,[first,second]);assert.equal(third.y,second.y+second.height+100);
const view=frame(source,third,{width:1280,height:720,scale:1});assert.ok((third.y+third.height-source.y)*view.scale<720-180);assert.ok(view.scale<=1);
console.log('Final result dimensions, source gap and repeated output placement passed');
// Exercise the existing task completion path: it previously discarded the
// reserved result size after the image arrived and made the nodes overlap again.
const fs=require('node:fs'),vm=require('node:vm');
const sourceJs=fs.readFileSync(require('node:path').join(__dirname,'../../static/js/smart-canvas.js'),'utf8');
const complete=sourceJs.slice(sourceJs.indexOf('function finalizeSmartPendingTask('),sourceJs.indexOf('async function resumeSmartPendingNode('));
function finish(layerResult){
    const node={layerParentNodeId:layerResult?'parent':undefined,w:340,h:258,images:[],pending:1,pendingTasks:[{taskId:'one'}]};
    vm.runInNewContext(complete+'\nfinalizeSmartPendingTask(node,"one",[],"image",{recordLog:false});',{
        node,smartPendingTasks:n=>n.pendingTasks || [],appendSmartPendingResults:()=>true,nowMs:()=>100,
        CanvasTaskQuery:{runTiming:()=>null},pendingSmartGenerationLog:()=>({}),
        mediaNodeDefaultScale:()=>1,MEDIA_NODE_DEFAULT_SCALE:1,MEDIA_GROUP_PREVIOUS_DEFAULT_SCALE:.5,MEDIA_GROUP_DEFAULT_SCALE:.5
    });return node;
}
assert.equal(finish(true).w,340);assert.equal(finish(true).h,258);assert.equal(finish(false).w,undefined);
console.log('Layer result size survives task completion; ordinary image behavior unchanged');
