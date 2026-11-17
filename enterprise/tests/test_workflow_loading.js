'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'../../static/js'),source=fs.readFileSync(path.join(root,'comfyui-settings.js'),'utf8');
function load(ctx,name){const m=new RegExp('^(?:async )?function '+name+'\\(','m').exec(source);assert(m,name);const next=source.slice(m.index+m[0].length).search(/\n(?:async )?function \w+\(/);vm.runInContext(source.slice(m.index,next<0?undefined:m.index+m[0].length+next),ctx);}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const workflow=name=>({name,workflow:{'1':{class_type:'KSampler',inputs:{steps:20}}},config:{title:name,backend:'http://backend-a',fields:[{id:'steps',node:'1',input:'steps',type:'number',label:'步数',default:20}]}});
function setup(){
    let timerId=0;const timers=new Map(),calls=[],pending=[];
    const ctx=vm.createContext({console,AbortController,structuredClone,URLSearchParams,
        setTimeout:(fn,ms)=>{const id=++timerId;timers.set(id,{fn,ms});return id;},clearTimeout:id=>timers.delete(id),
        workflows:[],selectedName:'',currentWorkflow:null,currentConfig:null,currentDefinitions:{},currentDefinitionWarning:'',
        workflowListLoad:null,workflowSelectionRequest:null,definitionRequest:null,imageGroupCandidates:[],currentFieldRoles:{},
        previewImageUrls:{},previewValues:{},previewRandomActive:{},URL:{revokeObjectURL(){}},currentLang:()=> 'zh',tr:key=>key,
        status:'',statusEl:{children:[],appendChild(button){this.children.push(button);}},document:{createElement:()=>({style:{}})},
        setStatus:text=>{ctx.status=text;ctx.statusEl.children=[];},renderList(){},renderEditor(){ctx.renders++;},renders:0,
        renderPreview(){},renderWorkspaceView(){},renderBackendChoice(){},refreshTestViews(){},graphFit(){},restoreTestTask(){},
        defaultMiniCards:()=>({}),defaultMiniTestNodes:()=>[]});
    ctx.window=ctx;ctx.addEventListener=()=>{};
    for(const file of ['comfy-workflow-fields.js','comfy-workflow-session.js'])vm.runInContext(fs.readFileSync(path.join(root,file),'utf8'),ctx);
    ctx.fetch=async(url,options={})=>{
        assert.equal(options.method,undefined,'loading must not submit or save');calls.push(String(url));
        if(ctx.reply)return ctx.reply(url,options);
        if(String(url).includes('include_definitions=true'))return new Promise((resolve,reject)=>{
            options.signal.addEventListener('abort',()=>reject(Object.assign(new Error('aborted'),{name:'AbortError'})));
            pending.push(resolve);
        });
        return {ok:true,json:async()=>workflow('a')};
    };
    for(const name of ['readWorkflowSettings','workflowReadFailed','refreshWorkflowDefinitions','selectWorkflow','loadList'])load(ctx,name);
    return {ctx,timers,calls,pending};
}
(async()=>{
    {
        const {ctx,timers,pending}=setup();await ctx.selectWorkflow('a');
        assert.equal(ctx.selectedName,'a');assert(ctx.currentWorkflow&&ctx.renders>0,'local graph renders before optional network response');
        assert(ctx.currentDefinitionWarning.includes('可编辑'));ctx.currentConfig.fields[0].label='本地修改';ctx.testSession.set('steps',42);
        [...timers.values()].find(t=>t.ms===12000).fn();await flush();
        assert(ctx.currentDefinitionWarning.includes('超时'));assert.equal(ctx.status,'');assert.equal(ctx.definitionRequest,null);
        assert.equal(ctx.currentConfig.fields[0].label,'本地修改');assert.equal(ctx.testSession.values.steps,42);
        ctx.reply=async()=>({ok:true,json:async()=>({...workflow('a'),definitions:{KSampler:{input:{required:{steps:['INT',{default:20,min:1,max:100}]}}}}})});
        await ctx.refreshWorkflowDefinitions();assert.equal(ctx.currentDefinitionWarning,'');
        assert.equal(ctx.currentConfig.fields[0].label,'本地修改');assert.equal(ctx.testSession.values.steps,42);
        pending.forEach(resolve=>resolve({ok:true,json:async()=>({...workflow('a'),definitions:{stale:true}})}));await flush();
        assert(!ctx.currentDefinitions.stale,'late timeout responses cannot overwrite the successful retry');
    }
    {
        const {ctx}=setup();await ctx.selectWorkflow('a');const original=ctx.currentConfig;
        ctx.reply=async()=>({ok:false,status:503,json:async()=>({detail:'unavailable'})});await ctx.selectWorkflow('b');
        assert.equal(ctx.selectedName,'a','a failed selection cannot save the old config under the new workflow name');
        assert.equal(ctx.currentConfig,original);assert.equal(ctx.status,'comfy.openFailed');assert.equal(ctx.statusEl.children[0].textContent,'重试');
        ctx.reply=async url=>({ok:true,json:async()=>String(url).includes('include_definitions')?{...workflow('b'),definitions:{}}:workflow('b')});
        await ctx.statusEl.children[0].onclick();assert.equal(ctx.selectedName,'b');
    }
    {
        const {ctx}=setup();let resolveA;
        ctx.reply=async url=>String(url).endsWith('/a')?new Promise(resolve=>{resolveA=resolve}):({ok:true,json:async()=>workflow('b')});
        const first=ctx.selectWorkflow('a');await ctx.selectWorkflow('b');
        resolveA({ok:true,json:async()=>workflow('a')});await first;assert.equal(ctx.selectedName,'b');assert.equal(ctx.currentConfig.title,'b');
    }
    {
        const {ctx,calls}=setup();let resolveList;
        ctx.reply=async url=>String(url).includes('include_disabled')?new Promise(resolve=>{resolveList=resolve}):({ok:true,json:async()=>workflow('a')});
        const first=ctx.loadList(),second=ctx.loadList();assert.equal(calls.filter(url=>url.includes('include_disabled')).length,1);
        resolveList({ok:true,json:async()=>({workflows:[{name:'a'}]})});await Promise.all([first,second]);assert.equal(ctx.selectedName,'a');
        ctx.reply=async()=>({ok:false,status:503});await ctx.loadList();
        assert.equal(ctx.workflows.length,1,'failed refresh retains the previous list');assert.equal(ctx.status,'comfy.loadFailed');
        assert.equal(ctx.statusEl.children[0].textContent,'重试');
    }
    console.log('workflow loading: local-first render, bounded optional read/retry, draft retention, selection identity and one initial list read');
})().catch(error=>{console.error(error);process.exitCode=1});
