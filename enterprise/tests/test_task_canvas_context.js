'use strict';
// Real client entry functions in a VM; no DOM, provider, or background timer.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.resolve(__dirname,'../../static/js');
const read=name=>fs.readFileSync(path.join(root,name),'utf8');
const plain=value=>JSON.parse(JSON.stringify(value));
function load(context,file,name){
    const text=read(file),start=text.search(new RegExp('(?:async )?function '+name+'\\('));
    assert.ok(start>=0,name);
    const end=text.slice(start+1).search(/\n(?:async )?function \w+\(/);
    vm.runInContext(text.slice(start,end<0?undefined:start+1+end),context);
}
async function run(){
    for(const kind of ['classic','smart']){
        const node={id:'generator'},saved=[];
        const context=vm.createContext({URLSearchParams,console,nodes:[node],canvas:{id:'original'},
            location:{search:'?focus_node=generator'},
            saveCanvas:async()=>{saved.push('saved');context.canvas={...context.canvas,updated_at:2};},
        });context.window=context;
        vm.runInContext(read('task-canvas-context.js'),context);
        const file=kind==='classic'?'canvas.js':'smart-canvas.js';
        load(context,file,'taskCanvasSource');
        assert.deepEqual(plain(await context.taskCanvasSource(node)),{canvas_id:'original',node_id:'generator'});
        assert.equal(saved.length,1,'source waits for save but accepts the replaced canvas object');
        context.saveCanvas=async()=>{context.canvas={id:'different'};};
        await assert.rejects(context.taskCanvasSource(node),/已离开来源画布/);
        let selected,focused;
        context.TaskCanvasContext.focus(context.nodes,n=>selected=n,n=>focused=n);
        assert.equal(selected,node);assert.equal(focused,node);
        context.location.search='?focus_node=deleted';selected=null;
        context.TaskCanvasContext.focus(context.nodes,n=>selected=n,()=>assert.fail('missing node must not pan'));
        assert.equal(selected,null);

        // Execute the actual integration callbacks, using existing node factory boundaries.
        const created=[];let savedCount=0;
        Object.assign(context,{
            GenerationTaskCenter:{attach:options=>context.options=options},
            addPromptNode:()=>{const n={type:'prompt'};created.push(n);return n;},
            addImageNode:()=>{const n={type:'image'};created.push(n);return n;},
            createPromptNode:()=>{const n={type:'prompt'};created.push(n);return n;},
            createImageNodeAt:(_point,items)=>{const n={type:'smart-image',images:items};created.push(n);return n;},
            viewportCenter:()=>({x:0,y:0}),render:()=>{},scheduleSave:()=>savedCount++,
        });
        vm.runInContext(read(file).slice(read(file).lastIndexOf('GenerationTaskCenter.attach(')),context);
        const target=context.options.canvasContext();context.canvas={...context.canvas};
        assert.equal(target.isCurrent(),true,'normal save/poll replacement is the same canvas');
        context.canvas={id:'other'};assert.equal(target.isCurrent(),false);
        for(const item of [{url:'/output/a.txt',kind:'text',text:'保留完整提示词\n下一行',result_id:'text-1'},
            {url:'/output/v.mp4',kind:'video',name:'v.mp4'}])await context.options.addResult(item,{id:'task-1'});
        assert.equal(created[0].text,'保留完整提示词\n下一行');
        assert.equal(created[0].sourceTaskId,'task-1');assert.equal(created[0].sourceResultId,'text-1');
        const media=kind==='classic'?created[1]:created[1].images[0];
        assert.equal(media.url,'/output/v.mp4');assert.equal(media.mediaKind || media.kind,'video');
        assert.equal(savedCount,2);
    }
    console.log('task canvas source, navigation guard and typed reuse: PASS (classic + smart)');
}
run().catch(error=>{console.error(error);process.exitCode=1;});
