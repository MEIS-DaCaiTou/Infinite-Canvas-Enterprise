/* Task controls use server receipts, never output-node DOM. No browser/dependency required. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const elements=[],observers=[],calls=[];
class Element{
    constructor(){this.attrs={};this.dataset={};this.children=[];this.nodes=new Map();this.values=new Set();this.classList={contains:key=>this.values.has(key),toggle:(key,value)=>value?this.values.add(key):this.values.delete(key),add:key=>{this.values.add(key);queueMicrotask(()=>observers.forEach(fn=>fn()));}};elements.push(this);}
    set innerHTML(value){this.html=value;this.nodes.clear();}
    get innerHTML(){return this.html||'';}
    setAttribute(key,value){this.attrs[key]=value;}
    before(){}after(){}append(...items){this.children.push(...items);}
    querySelector(selector){
        if(['.generation-task-cancel','.generation-task-detail','.generation-task-query','[data-open-source]'].includes(selector)&&!this.innerHTML.includes(selector.slice(1).replace(']','')))return null;
        if(!this.nodes.has(selector)){
            const node=new Element();
            if(selector==='.generation-task-cancel')node.disabled=/class="generation-task-cancel" disabled/.test(this.innerHTML);
            this.nodes.set(selector,node);
        }return this.nodes.get(selector);
    }
    querySelectorAll(selector){
        if(selector==='select')return this.selects ||= [new Element(),new Element()];
        if(selector==='button')return this.buttons ||= ['logs','tasks'].map(view=>{const e=new Element();e.dataset.view=view;return e;});
        if(selector==='[data-detail]')return this.detailButtons ||= [...this.innerHTML.matchAll(/data-detail="([^"]+)"/g)].map(match=>{const e=new Element();e.dataset.detail=match[1];return e;});
        return [];
    }
}
const modal=new Element(),logs=new Element();
const context={window:null,document:{getElementById:id=>id==='modal'?modal:logs,createElement:()=>new Element(),addEventListener(){},visibilityState:'visible'},
    MutationObserver:class{constructor(fn){observers.push(fn);}observe(){}},addEventListener(){},setInterval(){},setTimeout(){},clearTimeout(){},URLSearchParams,Map,Set,Date,Number,Promise,console};
context.window=context;
let status='queued',pending=false,fail=false;
context.fetch=async(url,options={})=>{
    calls.push([options.method||'GET',url]);
    if(options.method==='POST'){
        if(fail)return {ok:false,status:503,json:async()=>({detail:'取消尚未确认'})};
        status=pending?'running':'cancelled';return {ok:true,json:async()=>({message:pending?'等待后端确认':'已取消平台等待任务'})};
    }
    const row={id:'original-without-output',type:'comfy',status,created_at:1,output_count:0,can_cancel:status==='queued',cancellation_pending:pending};
    return {ok:true,json:async()=>url.includes('/original-without-output')?{...row,items:[]}:({items:[row],next_cursor:null})};
};
vm.runInNewContext(fs.readFileSync('static/js/generation-task-center.js','utf8'),context);
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
(async()=>{
    context.GenerationTaskCenter.attach({modalId:'modal',listId:'logs'});
    context.GenerationTaskCenter.openTasks({kind:'canvas_comfy'});await flush();
    assert(modal.classList.contains('open'));
    const pane=elements.find(e=>e.className==='generation-task-pane'),list=pane.querySelector('.generation-task-list');
    assert.equal(pane.hidden,false);assert(calls[0][1].includes('kind=canvas_comfy'));
    await list.querySelectorAll('[data-detail]')[0].onclick();
    let detail=list.querySelector('.generation-task-detail'),button=detail.querySelector('.generation-task-cancel');
    assert(button&&!button.disabled,'missing output still has cancel action');
    fail=true;await button.onclick();assert.equal(button.disabled,false);
    fail=false;await button.onclick();
    assert.equal(status,'cancelled');assert.deepEqual(calls.filter(([method])=>method==='POST').map(([,url])=>url),[
        '/enterprise/api/me/comfy-tasks/original-without-output/cancel','/enterprise/api/me/comfy-tasks/original-without-output/cancel']);
    assert(!list.querySelector('.generation-task-detail').querySelector('.generation-task-cancel'));
    pending=true;status='running';context.GenerationTaskCenter.openTasks({kind:'canvas_comfy'});await flush();
    await list.querySelectorAll('[data-detail]')[0].onclick();
    button=list.querySelector('.generation-task-detail').querySelector('.generation-task-cancel');
    assert(button.disabled&&!button.onclick,'acknowledgement is not a confirmed cancellation');
    assert(!calls.some(([,url])=>/\/prompt|\/interrupt/.test(url)));
    for(const path of ['static/canvas.html','static/smart-canvas.html','static/online.html'])assert(fs.readFileSync(path,'utf8').includes('generation-task-center.js?v=20261112.1'));
    assert(fs.readFileSync('static/js/canvas.js','utf8').includes("GenerationTaskCenter.openTasks({kind:'canvas_comfy'})"));
    console.log('task center: no-output cancel, retry, pending ack, both entrypoints; no provider POST');
})().catch(error=>{console.error(error);process.exitCode=1;});
