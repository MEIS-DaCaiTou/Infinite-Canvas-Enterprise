'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {ReferenceShelf,mediaFromNodes,dropIntent,previewUrl}=require('../../static/js/canvas-asset-shelf.js');
function previewRegressions(){
    const previousLocation=global.location,previousPreview=global.canvasMediaPreviewUrl,calls=[];
    try{
        global.location={origin:'http://localhost'};
        global.canvasMediaPreviewUrl=(url,size)=>{calls.push({url,size});return '/preview?size='+size;};
        assert.equal(previewUrl('http://localhost/assets/input/4k.png?version=2'),'/preview?size=240');
        assert.equal(previewUrl('/assets/input/4k.png',96),'/preview?size=96');
        assert.deepEqual(calls,[{url:'/assets/input/4k.png?version=2',size:240},{url:'/assets/input/4k.png',size:96}]);
        assert.equal(previewUrl('https://other.test/4k.png'),'https://other.test/4k.png');
        delete global.canvasMediaPreviewUrl;
        assert.equal(previewUrl('/assets/input/4k.png'),'/assets/input/4k.png');
    }finally{
        if(previousLocation===undefined)delete global.location;else global.location=previousLocation;
        if(previousPreview===undefined)delete global.canvasMediaPreviewUrl;else global.canvasMediaPreviewUrl=previousPreview;
    }
}
function editorDropRegressions(){
    const source=fs.readFileSync(path.join(__dirname,'../../static/js/canvas.js'),'utf8');
    const start=source.indexOf('function endDrag(event=null){'),end=source.indexOf('\nfunction nodeRect(',start);
    let accepted=true,memberships=0,saves=0;
    const first={id:'one',type:'image',url:'/assets/a.png',x:900,y:500},child={id:'two',type:'image',url:'/assets/b.png',x:950,y:500};
    const context=vm.createContext({canvasAssetShelf:{dropNodeDrag:()=>accepted},window:{CanvasAssetShelf:{mediaFromNodes}},
        document:{body:{classList:{remove(){}}}},resizeNode:null,llmPaneDrag:null,knifeChanged:false,tempLink:null,dragBoard:null,minimapDrag:null,
        dragNode:{node:first,ox:10,oy:20,children:[{node:child,ox:60,oy:20}]},knifeNeedsRender:false,textSelectionGuard:null,
        updateGroupMembership(){memberships++;},setKnifeMode(){},render(){},scheduleMinimapRender(){},scheduleSave(){saves++;},scheduleViewportSave(){}});
    vm.runInContext(source.slice(start,end),context);context.endDrag({clientX:20,clientY:200});
    assert.deepEqual([first.x,first.y,child.x,child.y],[10,20,60,20],'collecting a real node restores source and selected siblings');
    assert.equal(memberships,0);assert.equal(saves,1);
    accepted=false;first.x=30;context.dragNode={node:first,ox:10,oy:20,children:[]};context.endDrag({clientX:400,clientY:200});
    assert.equal(first.x,30,'normal canvas movement is preserved');assert.equal(memberships,1);
    const smart=fs.readFileSync(path.join(__dirname,'../../static/js/smart-canvas.js'),'utf8');
    const smartStart=smart.indexOf('        if(canvasAssetShelf?.dropNodeDrag(e,shelfMedia)){');
    const smartEnd=smart.indexOf('        let stateChanged = false;',smartStart);
    const group={id:'group',type:'smart-group',title:'Group',images:[{url:'/assets/later.png'}],w:800,extra:'new task data'};
    const detached={id:'temporary',images:[{url:'/assets/source.png'}]};
    const ownUndo={};const smartContext=vm.createContext({e:{},shelfMedia:[],canvasAssetShelf:{dropNodeDrag:()=>true},
        nodes:[group,detached],dragState:{id:'temporary',thumbDetached:true,shelfOrigin:{nodeId:'group',index:0,image:{url:'/assets/source.png'},title:'Group',w:500},shelfUndoEntry:ownUndo},
        undoStack:[ownUndo],restoreDraggedNodePosition(){},discardPendingUndo(){},clearDropHighlight(){},isSmartGroupNode:()=>true,
        arrangeSmartGroupMembers(){},render(){},scheduleSave(){},Date});
    vm.runInContext('function finish(){'+smart.slice(smartStart,smartEnd)+'} finish();',smartContext);
    assert.equal(smartContext.nodes.length,1,'collecting a detached thumbnail removes the temporary canvas node');
    assert.deepEqual(group.images.map(row=>row.url),['/assets/source.png','/assets/later.png'],'source restoration keeps newer media and unrelated task data');
    assert.equal(group.extra,'new task data');assert.equal(smartContext.undoStack.length,0);
}
async function run(){
    previewRegressions();
    editorDropRegressions();
    await pagingRegressions();
    let actor='alice',libraries=[{id:'b',reference_shelf_owner:'bob',categories:[]}],count=0,loseReply=false;
    const calls=[],files=new Set();
    const fetcher=async(path,init)=>{
        let compact=false;
        if(init.method!=='GET' && path.startsWith('/api/asset-library/')){
            const requestUrl=new URL(path,'http://localhost');assert.equal(requestUrl.searchParams.get('catalog'),'1');
            requestUrl.searchParams.delete('catalog');path=requestUrl.pathname+requestUrl.search;compact=true;
        }
        const body=init.body?JSON.parse(init.body):{};calls.push({path,method:init.method,body});
        let data;
        const own=()=>libraries.find(row=>row.id===(body.library_id || 'mine'));
        if(path==='/enterprise/api/me')data={user_id:actor};
        else if(path==='/api/asset-library')data={library:{libraries}};
        else if(path.startsWith('/api/asset-library?')){
            const params=new URL(path,'http://localhost').searchParams;
            if(params.has('catalog'))data={library:{libraries:libraries.map(lib=>({...lib,categories:lib.categories.map(cat=>({...cat,items:undefined,item_count:cat.items.length}))}))}};
            else {
                let rows=libraries.filter(lib=>lib.id===params.get('library_id')).flatMap(lib=>lib.categories.flatMap(cat=>cat.items.map(row=>({...row,category_id:cat.id}))));
                if(params.has('item_id'))rows=rows.filter(row=>row.id===params.get('item_id'));
                if(params.has('category_id'))rows=rows.filter(row=>row.category_id===params.get('category_id'));
                if(params.has('match_url'))rows=rows.filter(row=>[row.url,row.collected_from].includes(params.get('match_url')));
                data={items:rows.slice(0,1),total:rows.length,next_cursor:null};
            }
        }
        else if(path==='/api/asset-library/libraries'){
            const lib={id:body.name==='我的参考库'?'mine':'product-'+(++count),name:body.name,reference_shelf_owner:actor,categories:[]};libraries.push(lib);data={asset_library:lib};
        }else if(path==='/api/asset-library/categories'){
            const category={id:'c'+(++count),name:body.name,type:'image',items:[]};own().categories.push(category);data={category,library:{libraries}};
        }else if(path==='/api/asset-library/items'){
            const cat=own().categories.find(row=>row.id===body.category_id);
            const item={id:'i'+(++count),url:'/assets/library/copy-'+count+'.png',name:body.name,collected_from:body.url};cat.items.push(item);files.add(item.url);data={item,library:{libraries}};
            if(loseReply){loseReply=false;throw Error('response lost');}
        }else if(path==='/api/asset-library/items/move'){
            let moved;for(const cat of own().categories){moved ||=cat.items.find(row=>row.id===body.ids[0]);cat.items=cat.items.filter(row=>row.id!==body.ids[0]);}
            own().categories.find(row=>row.id===body.target_category_id).items.push(moved);data={library:{libraries}};
        }else if(path.includes('?keep_file=true')){
            const id=path.split('/').pop().split('?')[0];for(const cat of own().categories)cat.items=cat.items.filter(row=>row.id!==id);data={library:{libraries}};
        }else throw Error('unexpected '+path);
        if(compact && data.library){
            const slim=lib=>({...lib,categories:lib.categories.map(cat=>{const {items,...metadata}=cat;return{...metadata,item_count:items.length,preview_items:items.slice(-2)};})});
            data={...data,library:{libraries:data.library.libraries.map(slim)},projection:'catalog'};
            if(data.asset_library)data.asset_library=slim(data.asset_library);
            if(data.category){const {items,...metadata}=data.category;data.category={...metadata,item_count:items.length};}
        }
        return{ok:true,json:async()=>structuredClone(data)};
    };
    const model=new ReferenceShelf(fetcher),source={url:'/assets/output/original.png',name:'服装参考'};
    await model.refresh();assert.equal(model.library,null,'admin-visible libraries are not mistaken for personal collections');
    const clothes={key:'clothes',name:'服装库'},pose={key:'pose',name:'姿势参考'};
    const saved=await model.collect(source,clothes);assert.equal(model.library.reference_shelf_owner,'alice');
    assert.equal(calls.filter(row=>row.path==='/api/asset-library').length,1,'collection must use catalog and exact lookup instead of another full directory read');
    const upload=calls.find(row=>row.path==='/api/asset-library/items');assert.equal(upload.body.classify,false);assert.ok(upload.body.collect_request_id);
    await model.collect(source,clothes);assert.equal(calls.filter(row=>row.path==='/api/asset-library/items').length,1,'repeat drop is not duplicate storage');
    const moved=await model.collect({...saved.item,itemId:saved.item.id},pose);assert.equal(moved.undo.kind,'move');
    assert.equal(calls.filter(row=>row.path==='/api/asset-library/items').length,1,'organizing a saved image does not recopy bytes');
    await model.undo(moved.undo);assert.equal((await model.lookup({item_id:moved.item.id})).category_id,moved.undo.from);
    await model.undo(saved.undo);assert.equal(files.size,1,'collection undo keeps media already used by a canvas');
    loseReply=true;const second={url:'/assets/output/new.png',name:'new'};
    await assert.rejects(model.collect(second,clothes),/response lost/);
    await model.collect(second,clothes);assert.equal(calls.filter(row=>row.path==='/api/asset-library/items').length,2,'lost response is resolved from the refreshed directory');
    const product=await model.createLibrary('女装春夏');
    await model.collect({url:'/assets/input/style.mp4',name:'款式视频'},clothes);
    assert.equal(model.library.id,product.id);
    assert.equal(calls.filter(row=>row.path==='/api/asset-library/items').at(-1).body.library_id,product.id,'saving after a library switch stays in that product library');
    await model.selectLibrary('mine');
    assert.equal(model.library.categories.find(row=>row.name==='服装库').items.length,1,'another product keeps its own folders and media');
    libraries=libraries.filter(row=>row.id!==product.id);
    await assert.rejects(model.selectLibrary(product.id),/权限已变化/);
    const writes=calls.filter(row=>row.method==='POST').length;
    await assert.rejects(model.collect(source,clothes),/权限已变化/);
    assert.equal(calls.filter(row=>row.method==='POST').length,writes,'a deleted/revoked library never falls back to writing into another library');
    await model.selectLibrary('mine');
    actor='bob';const before=calls.filter(row=>row.method==='POST').length;
    await assert.rejects(model.collect(source,pose),/账号已变化/);assert.equal(calls.filter(row=>row.method==='POST').length,before);
    const found=mediaFromNodes([{id:'a',type:'image',url:'/assets/input/a.png'},
        {id:'b',images:[{url:'/assets/input/a.png'},{url:'/assets/input/b.png'}],outputs:{}},
        {id:'c',images:[{url:'/assets/output/movie.mp4',kind:'video'},{url:'/assets/input/voice.wav',kind:'audio'},{url:'/assets/input/workflow.zip',kind:'workflow'}]}]);
    assert.equal(found.length,4);assert.equal(found[0].nodeId,'a');assert.equal(found[2].kind,'video');assert.equal(found[3].kind,'audio');
    for(const origin of ['canvas','library'])for(const target of ['folder','gallery'])assert.equal(dropIntent(origin,target),'collect');
    assert.equal(dropIntent('canvas','canvas'),'none','a canvas-origin gesture never creates a copy on the canvas');
    assert.equal(dropIntent('library','canvas'),'insert','saved assets can still be deliberately reused');
    assert.equal(dropIntent('canvas',''),'none');
    console.log('asset shelf: direct collection/drop origins, multi-library, mixed media, undo, account and lost-response contracts passed');
}
async function pagingRegressions(){
    const calls=[];let fail=false,stale=false,release;
    const model=new ReferenceShelf(async(path)=>{
        const url=new URL(path,'http://localhost');calls.push(url);
        if(url.pathname==='/enterprise/api/me')return{ok:true,json:async()=>({user_id:'a'})};
        if(url.searchParams.has('catalog'))return{ok:true,json:async()=>({library:{libraries:[{id:'mine',reference_shelf_owner:'a',categories:[{id:'c',name:'服装库',type:'image',item_count:26,preview_items:[]}]}]}})};
        if(url.searchParams.get('q')==='old')await new Promise(resolve=>{release=resolve;});
        if(fail){fail=false;return{ok:false,status:503,json:async()=>({message:'retry same page'})};}
        if(stale){stale=false;return{ok:false,status:409,json:async()=>({message:'changed'})};}
        const offset=url.searchParams.get('cursor')?24:0;
        return{ok:true,json:async()=>({items:Array.from({length:offset?2:24},(_,i)=>({id:'i'+(offset+i),name:url.searchParams.get('q') || 'shirt',url:'/assets/library/'+(offset+i)+'.png'})),total:26,next_cursor:offset?null:'next'})};
    });
    await model.refresh({catalog:true});const folder=model.folders().find(row=>row.name==='服装库');
    assert.equal(calls[1].searchParams.get('catalog'),'1');
    await model.loadItems(folder);assert.equal(model.page.rows.length,24);assert.equal(model.page.cursor,'next');
    fail=true;await model.loadItems(folder,'',true);
    assert.equal(model.page.rows.length,24);assert.equal(model.page.cursor,'next');assert.match(model.page.error,/retry/);
    await model.loadItems(folder,'',true);assert.equal(model.page.rows.length,26);assert.equal(model.page.cursor,null);
    assert.equal(calls.at(-1).searchParams.get('cursor'),'next');
    await model.loadItems(folder);stale=true;await model.loadItems(folder,'',true);assert.equal(model.page.refresh,true);
    const slow=model.loadItems(folder,'old');await model.loadItems(folder,'new');release();await slow;
    assert.equal(model.page.rows[0].name,'new','late old query must not replace a new folder/search');
    const closed=model.loadItems(folder,'old');model.cancelItems();const before=model.page.rows;release();await closed;
    assert.strictEqual(model.page.rows,before,'closed shelf ignores late results');
    const count=calls.length;await model.loadItems({key:'new'});assert.equal(calls.length,count,'uncreated folder cannot query every category');
}
run().catch(error=>{console.error(error);process.exit(1);});
