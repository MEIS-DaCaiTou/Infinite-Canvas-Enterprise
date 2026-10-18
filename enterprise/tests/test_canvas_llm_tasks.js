'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'../../static/js');
const context=vm.createContext({console,URLSearchParams,fetch:()=>assert.fail('unexpected fetch'),setTimeout});
context.window=context;context.CanvasTaskQuery={requestId:()=> '1'.repeat(32)};
vm.runInContext(fs.readFileSync(path.join(root,'canvas-llm-tasks.js'),'utf8'),context);
async function run(){
    const calls=[],events=[];let saved=false,result;
    const fetcher=async(url,options={})=>{
        calls.push({url,options});assert.ok(saved,'ticket save precedes POST');
        return {ok:true,json:async()=>options.method==='POST'?{task_id:'canvas_llm_'+'1'.repeat(32)}:
            {status:'succeeded',result:{text:'恢复的文本'}}};
    };
    const config={fetcher,prepare:async()=>{saved=true;return {canvas_id:'c',node_id:'n'};},
        onState:ticket=>events.push(ticket),onResult:value=>result=value,wait:async()=>{}};
    await context.CanvasLLMTasks.run({message:'input'},config);
    assert.equal(calls.filter(c=>c.options.method==='POST').length,1);assert.equal(result.text,'恢复的文本');
    const binding=events[0];calls.length=0;
    await context.CanvasLLMTasks.run(null,{...config,task:binding,prepare:()=>assert.fail('resume saved a new ticket')});
    assert.ok(calls.every(c=>!c.options.method),'reload only reads existing platform ID');
    calls.length=0;
    await assert.rejects(context.CanvasLLMTasks.run({message:'input'},{...config,fetcher:async(url,options)=>{
        calls.push({url,options});throw new Error('lost acceptance');
    }}),/查看原任务/);
    assert.equal(calls.length,1,'lost acceptance is not automatically submitted again');
    let current=true;
    await assert.rejects(context.CanvasLLMTasks.run(null,{...config,task:binding,isCurrent:()=>current,
        fetcher:async()=>{current=false;return {ok:true,json:async()=>({status:'succeeded',result:{text:'stale'}})};},
        onResult:()=>assert.fail('navigated result entered another canvas')}),{name:'AbortError'});
    console.log('LLM ticket before submit, GET-only resume, lost response and navigation: PASS');
}
run().catch(error=>{console.error(error);process.exitCode=1;});
