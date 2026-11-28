/* A saved pending output is resumed the next day against its original GET receipt. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/js/canvas.js','utf8');
function extract(name){
    const start=source.indexOf(`function ${name}(`);
    const next=source.indexOf('\nfunction ',start+1);
    const asyncNext=source.indexOf('\nasync function ',start+1);
    const end=Math.min(...[next,asyncNext].filter(n=>n>=0));
    return source.slice(source.lastIndexOf('async ',start)===start-6?start-6:start,end);
}
const generator={id:'source',activeImageBatchId:'original'};
const output={id:'out',images:[],_pending:[{id:'pending',canvasTaskId:'original',canvasTaskType:'online-image',
    startedAt:1000000,imageBatchId:'original',run:{node:{id:'source'}}}]};
const calls=[],logs=[];
const context={window:{},nodes:[generator,output],activeCanvasTaskPolls:new Set(),nowMs:()=>56302000,
    findPendingTask:id=>output._pending.find(p=>p.canvasTaskId===id)?{out:output,pending:output._pending[0]}:null,
    cascadeFetch:async(url,options)=>{calls.push([url,options]);return {ok:true,json:async()=>({
        status:'succeeded',created_at:1000,updated_at:56302,result:{timestamp:1106,images:['/output/original.png']}})};},
    updateCanvasImageStatus(){},requestMetaFromResult:()=>({}),mergeGeneratedOutputs(){},refreshRunNodes(){},scheduleSave(){},
    appendOutputImagesWithoutDuplicates:(out,images,ref,metas)=>{out.images=images.map(url=>({url,...metas[0]}));return images.length;},
    addGenerationLog:entry=>logs.push(entry)};
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/js/canvas-task-query.js','utf8'),context);
context.CanvasTaskQuery=context.window.CanvasTaskQuery;
vm.runInContext(fs.readFileSync('static/js/canvas-output-presentation.js','utf8'),context);
context.CanvasOutputPresentation=context.window.CanvasOutputPresentation;
vm.runInContext(['pollCanvasImageTask','completeCanvasImageTask','appendPendingImageResults','finishPendingImageOutput'].map(extract).join('\n'),context);
(async()=>{
    assert.equal(await context.pollCanvasImageTask('original'),'succeeded');
    assert.equal(output._pending.length,0);
    assert.equal(output.images[0].runMs,106000);
    assert.equal(output.images[0].run.taskFinishedAt,1106000);
    assert.equal(logs[0].runMs,106000);
    assert.equal(calls.length,1);
    assert.equal(calls[0][0],'/api/canvas-image-tasks/original');
    assert(!calls[0][1].method,'recovery only reads; it must never submit another paid request');
    console.log('classic image recovery: overnight reload, server duration, log/output consistency, GET only passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
