const assert=require('assert/strict'),fs=require('fs'),path=require('path'),vm=require('vm');
const root=path.join(__dirname,'../..');
const source=fs.readFileSync(path.join(root,'static/js/canvas-list.js'),'utf8');
const online=fs.readFileSync(path.join(root,'static/online.html'),'utf8');
function load(ctx,text,names){
 for(const name of names){
  const start=text.search(new RegExp('(?:async )?function '+name+'\\('));assert.ok(start>=0,name);
  const brace=text.indexOf('{',start);let depth=0,quote='',end=brace;
  for(;end<text.length;end++){
   const ch=text[end];
   if(quote){if(ch==='\\'){end++;continue;}if(ch===quote)quote='';continue;}
   if(ch==='"'||ch==="'"||ch==='`'){quote=ch;continue;}
   if(ch==='{')depth++;if(ch==='}'&&--depth===0){end++;break;}
  }
  vm.runInContext(text.slice(start,end),ctx);
 }
}
function element(){const hidden=new Set();return{hidden:false,disabled:false,textContent:'',children:[],
 classList:{toggle:(k,v)=>v?hidden.add(k):hidden.delete(k),add:k=>hidden.add(k),remove:k=>hidden.delete(k),contains:k=>hidden.has(k)},
 appendChild(x){this.children.push(x);},set innerHTML(_){this.children=[];}};}
const response=(key,values,ok=true)=>({ok,json:async()=>({[key]:values})});
function directory(){
 const names=['boardLoadState','boardLoadMessage','boardLoadRetry','boardRefreshBtn','newCanvasBtn','newProjectBtn','boardEmptyHint','boardProjectName','boardCanvasCount','boardWorld'];
 const ctx=vm.createContext(Object.fromEntries(names.map(n=>[n,element()])));
 Object.assign(ctx,{listLoadState:'loading',listHasLoaded:false,listLoadRevision:0,listUnreadableCount:0,projects:[],canvases:[],currentProjectId:'mine',
  L:zh=>zh,console:{warn(){}},rememberProjectId(){},renderProjects(){},resetView(){},refreshTrashCount(){},
  refreshIcons(){},autoLayoutNulls(){},buildCard:x=>x,updatePasteBtn(){}});
 load(ctx,source,['currentProject','canvasesInProject','renderListLoadState','loadAll','projectCanvasCount','updateBoardHeader','renderBoard']);return ctx;
}
async function run(){
 const c=directory(),pending=[];
 c.fetch=url=>new Promise(resolve=>pending.push({url,resolve}));
 const first=c.loadAll();assert.equal(pending[0].url,'/api/projects?include_counts=false');
 assert.equal(c.boardEmptyHint.classList.contains('hidden'),true);assert.equal(c.boardCanvasCount.textContent,'—');
 c.renderBoard();assert.equal(c.boardEmptyHint.classList.contains('hidden'),true,'language render must not show false empty state');
 assert.equal(c.newCanvasBtn.disabled,true);
 pending[0].resolve(response('projects',[{id:'mine',name:'My project',canvas_count:99}]));
 pending[1].resolve(response('canvases',[{id:'one',project:'mine'}]));await first;
 assert.equal(c.listLoadState,'ready');assert.equal(c.boardWorld.children.length,1);assert.equal(c.projectCanvasCount('mine'),1);
 const oldCanvases=c.canvases,oldProjects=c.projects;
 c.fetch=async url=>response(url.includes('projects')?'projects':'canvases',[],!url.includes('canvases'));
 await c.loadAll();assert.equal(c.listLoadState,'error');assert.equal(c.canvases,oldCanvases);assert.equal(c.projects,oldProjects);
 assert.equal(c.boardWorld.children.length,1);assert.equal(c.boardLoadRetry.hidden,false);assert.equal(c.newCanvasBtn.disabled,false);
 c.fetch=async url=>response(url.includes('projects')?'projects':'canvases',[]);await c.loadAll();
 assert.equal(c.projectCanvasCount('default'),0);assert.equal(c.boardEmptyHint.classList.contains('hidden'),false,'only confirmed empty response shows empty state');
 c.fetch=async url=>({ok:true,json:async()=>url.includes('projects')?{projects:[{id:'default'}]}:{canvases:[],unreadable_canvas_count:2}});
 await c.loadAll();assert.equal(c.listLoadState,'partial');assert.equal(c.boardEmptyHint.classList.contains('hidden'),true);
 assert.equal(c.boardLoadRetry.hidden,false);assert.ok(c.boardLoadMessage.textContent.includes('2 个画布文件暂不可读'));
 c.fetch=async url=>response(url.includes('projects')?'projects':'canvases',[]);await c.loadAll();
 assert.equal(c.listLoadState,'ready');assert.equal(c.listUnreadableCount,0);
 const failed=directory();failed.fetch=async()=>({ok:false});await failed.loadAll();
 assert.equal(failed.boardEmptyHint.classList.contains('hidden'),true);assert.equal(failed.listHasLoaded,false);
 assert.equal(failed.boardLoadRetry.hidden,false);
 failed.fetch=async()=>({ok:true,json:async()=>({projects:null})});await failed.loadAll();assert.equal(failed.listHasLoaded,false);
 const race=directory(),replies=[];race.fetch=()=>new Promise(resolve=>replies.push(resolve));
 const older=race.loadAll(),newer=race.loadAll();
 replies[2](response('projects',[{id:'mine',name:'Newest'}]));replies[3](response('canvases',[]));await newer;
 replies[0](response('projects',[{id:'mine',name:'Old'}]));replies[1](response('canvases',[]));await older;
 assert.equal(race.projects[0].name,'Newest');

 const loader=element(),masonry={innerHTML:'existing cards'},cards=[];
 const h=vm.createContext({window:{StudioI18n:{lang:()=> 'zh'}},document:{getElementById:id=>id==='masonry'?masonry:loader},
  tr:x=>x,isLoading:false,historyLoadFailed:false,historyCursor:null,historyHasMore:true,historyRetryPage:0,historyStale:false,historyLegacy:false,historyFailureKind:"",historyFailureStatus:0,allHistory:[{id:'old'}],currentIndex:1,PAGE_SIZE:10,
  renderImageCard:x=>cards.push(x.id),console:{warn(){}},fetch:async()=>({ok:false,status:503})});
 load(h,online,['historyLoaderLabel','loadHistory']);await h.loadHistory(0);
 assert.equal(h.isLoading,false);assert.equal(h.historyLoadFailed,true);assert.equal(masonry.innerHTML,'existing cards');
 assert.equal(h.allHistory[0].id,'old');assert.equal(loader.classList.contains('hidden'),false);
 assert.equal(h.historyFailureKind,'http');
 h.fetch=async()=>{throw new TypeError('controlled offline');};await h.loadHistory(0);assert.ok(h.historyLoaderLabel().includes('网络连接中断'));
 h.fetch=async()=>({ok:false,status:401});await h.loadHistory(0);assert.ok(h.historyLoaderLabel().includes('登录已失效'));
 h.fetch=async()=>({ok:true,json:async()=>{throw new SyntaxError('controlled non-JSON response');}});await h.loadHistory(0);assert.ok(h.historyLoaderLabel().includes('响应格式异常'));
 h.location={href:'http://127.0.0.1:18000/static/online.html'};h.URL=URL;
 h.fetch=async()=>({ok:true,status:200,redirected:true,url:'http://127.0.0.1:18000/enterprise/login'});await h.loadHistory(0);assert.ok(h.historyLoaderLabel().includes('登录已失效'));
 h.fetch=async()=>({ok:true,json:async()=>[{id:'new'}]});await h.loadHistory(0);
 assert.equal(h.historyLoadFailed,false);assert.deepEqual(cards,['new']);
 // Real page envelope: failure retries the original cursor, not the first page.
 cards.length=0;
 h.fetch=async url=>{assert.ok(url.includes('page_size=10'));return {ok:true,json:async()=>({items:[{id:'p1',timestamp:1}],next_cursor:'next-token'})};};
 await h.loadHistory(0);assert.equal(h.allHistory.length,1);assert.equal(h.historyHasMore,true);
 h.fetch=async url=>{assert.ok(url.includes('cursor=next-token'));return {ok:false,status:503};};
 await h.loadHistory(1);assert.equal(h.historyRetryPage,1);assert.equal(h.allHistory.length,1);assert.ok(h.historyLoaderLabel().includes('HTTP 503'));
 h.fetch=async url=>{assert.ok(url.includes('cursor=next-token'));return {ok:true,json:async()=>({items:[{id:'p2',timestamp:2}],next_cursor:'last-token'})};};
 await h.loadHistory(1);assert.deepEqual(cards,['p1','p2']);
 h.fetch=async()=>({ok:false,status:409});await h.loadHistory(1);
 assert.equal(h.historyStale,true);assert.equal(h.historyRetryPage,0);assert.equal(h.allHistory.length,2);
 h.fetch=async url=>{assert.ok(!url.includes('cursor='));return {ok:true,json:async()=>({items:[{id:'fresh',timestamp:3}],next_cursor:null})};};
 await h.loadHistory(0);assert.equal(h.historyHasMore,false);assert.equal(h.historyStale,false);assert.equal(h.allHistory.length,1);
 let finishModels,modelsStarted=false,historyStarted=false,attached=false;
 h.applyLanguage=()=>{};h.setRatio=()=>{};h.setResolution=()=>{};
 h.initModels=()=>{modelsStarted=true;return new Promise(r=>finishModels=r);};
 h.fetch=async()=>{historyStarted=true;return{ok:true,json:async()=>[]};};
 h.observer={observe(){}};h.window.HistoryBulkManager={attach(){attached=true;}};
 const start=online.indexOf('window.onload = async () => {'),end=online.indexOf('</script>',start);
 vm.runInContext(online.slice(start,end),h);const boot=h.window.onload();
 await new Promise(resolve=>setImmediate(resolve));
 assert.ok(historyStarted&&modelsStarted);assert.equal(typeof loader.onclick,'function');
 assert.equal(attached,true,'history controls must not wait for slow model configuration');finishModels();await boot;
 console.log('directory loading/error/retained cards/retry/zero count/stale response; history retry and parallel startup: PASS');
}
run().catch(e=>{console.error(e);process.exitCode=1;});
