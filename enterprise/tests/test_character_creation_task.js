'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const context=vm.createContext({crypto:require('node:crypto').webcrypto,Uint8Array,window:{}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../../static/js/character-creation-task.js'),'utf8'),context);
const Task=context.window.CharacterCreationTask;
function storage(){const values=new Map();return {getItem:key=>values.get(key),setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};}
const payload={prompt:'test character',provider_id:'fixture',model:'fixture'};
async function run(){
  const cache=storage(),calls=[];
  let finish;
  const request=async(url,options)=>{
    calls.push({url,options});
    if(options?.method==='POST' && url==='/api/canvas-image-tasks') return new Promise(resolve=>{finish=resolve;});
    if(url.includes('generation-tasks/'))return {type:'online-image',status:'succeeded',items:[{url:'/assets/output/result.png',kind:'image'}]};
    if(url==='/enterprise/api/me/characters')return {id:'saved'};
  };
  const task=new Task(request,cache);task.setOwner('alice');
  const edit=new Task(request,cache,'character-image-v1:role:edit');edit.setOwner('alice');
  const portrait=new Task(request,cache,'character-image-v1:role:portrait');portrait.setOwner('alice');
  edit.state={owner:'alice',createId:'f'.repeat(32),prompt:'edit',stage:'unknown',context:{revision:2}};edit.store();
  assert.equal(portrait.state,null,'typed assets never recover an edit receipt');
  const recoveredEdit=new Task(request,cache,'character-image-v1:role:edit');recoveredEdit.setOwner('alice');
  assert.equal(recoveredEdit.state.context.revision,2,'edit context survives recovery');
  assert.equal(task.state,null,'creation receipt remains separate');
  const submitting=task.submit(payload);
  await assert.rejects(()=>task.submit(payload),/重复提交/);
  finish({task_id:'canvas_img_'+'a'.repeat(32)});await submitting;
  const restored=new Task(request,cache);restored.setOwner('alice');
  assert.equal(restored.state.taskId,task.state.taskId);
  await restored.refresh();await restored.refresh();
  assert.equal(calls.filter(call=>call.url==='/api/canvas-image-tasks').length,1,'recovery is query-only');
  assert.equal(restored.state.stage,'result');
  await restored.save({name:'new'});
  const saved=JSON.parse(calls.find(call=>call.url==='/enterprise/api/me/characters').options.body);
  assert.equal(saved.create_request_id,restored.state.createId);
  assert.deepEqual(saved.images,['/assets/output/result.png']);
  restored.setOwner('bob');assert.equal(restored.state,null,'account switch never carries another account receipt');

  for(const status of [undefined,500,408]){
    const calls=[];
    const uncertain=new Task(async(url,options)=>{calls.push(url);throw Object.assign(new Error('lost response'),{status});},storage());uncertain.setOwner('alice');
    await assert.rejects(()=>uncertain.submit(payload),/待核对/);
    await assert.rejects(()=>uncertain.submit(payload),/重复提交/);
    assert.equal(calls.length,1,'network/5xx/timeout cannot automatically resubmit');
  }
  const editCache=storage();let editPosts=0;
  const editUnknown=new Task(async()=>{editPosts++;throw new Error('lost edit receipt');},editCache,'character-image-v1:one:edit');editUnknown.setOwner('alice');
  await assert.rejects(()=>editUnknown.submit(payload,'edit',{revision:3,reference:'/assets/input/one.png',design:{version:1,values:{smooth:25}}}),/待核对/);
  const editAgain=new Task(async()=>{editPosts++;},editCache,'character-image-v1:one:edit');editAgain.setOwner('alice');
  assert.equal(editAgain.state.context.design.values.smooth,25);
  await assert.rejects(()=>editAgain.submit(payload),/重复提交/);assert.equal(editPosts,1);
  const denied=new Task(async()=>{throw Object.assign(new Error('no grant'),{status:403});},storage());denied.setOwner('alice');
  await assert.rejects(()=>denied.submit(payload),/no grant/);assert.equal(denied.canGenerate(),true);
  let posts=0;
  const blocked=new Task(async()=>{posts++;}, {getItem:()=>null,setItem:()=>{throw new Error('storage blocked');}});blocked.setOwner('alice');
  await assert.rejects(()=>blocked.submit(payload),/本次未提交/);assert.equal(posts,0);assert.equal(blocked.state,null);
  const wrong=new Task(async()=>{throw new Error('not owned');},storage());wrong.setOwner('alice');wrong.state={stage:'unknown',createId:'c'.repeat(32),owner:'alice',taskId:''};
  await assert.rejects(()=>wrong.attach('canvas_img_'+'c'.repeat(32)),/not owned/);assert.equal(wrong.state.taskId,'');
  const saveIds=[];
  const saveRetry=new Task(async(url,options)=>{
    const body=JSON.parse(options.body);saveIds.push(body.create_request_id);
    if(saveIds.length===1)throw new Error('save reply lost');return {id:body.create_request_id};
  },storage());saveRetry.setOwner('alice');saveRetry.state={owner:'alice',createId:'d'.repeat(32),stage:'result',prompt:'original description',images:['/assets/output/result.png']};
  await assert.rejects(()=>saveRetry.save({name:'same'}),/save reply lost/);
  await saveRetry.save({name:'same'});
  assert.deepEqual(saveIds,['d'.repeat(32),'d'.repeat(32)],'a save retry uses the original creation nonce');
  const retained=new Task(async()=>{},cache,'retain');retained.setOwner('alice');retained.state={owner:'alice',createId:'e'.repeat(32),prompt:'old',stage:'unknown',taskId:'old'};retained.store();
  assert.throws(()=>retained.archiveUnknown(false),/核对/);assert.equal(retained.state.taskId,'old');
  retained.archiveUnknown(true);assert.equal(retained.state,null);assert.equal(JSON.parse(cache.getItem('retain:alice:retained'))[0].taskId,'old');
  let voicePosts=0;
  const audio=new Task(async(u,o)=>{if(o){voicePosts++;assert.equal(u,'/api/character-voice-tasks');assert.match(JSON.parse(o.body).request_id,/^[a-f0-9]{32}$/);return {task_id:'audio'};}return {status:'succeeded',items:[{kind:'audio',url:'/assets/output/voice.mp3'}]};},storage(),'voice','audio');audio.setOwner('alice');await audio.submit({input:'hello'});await audio.refresh();assert.equal(audio.state.stage,'result');assert.equal(audio.state.images[0],'/assets/output/voice.mp3');assert.equal(voicePosts,1);
  console.log('character creation: one submit, owned recovery, account cache, uncertain response and save passed');
}
run().catch(error=>{console.error(error);process.exitCode=1;});
