'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const context = vm.createContext({window:{}, setTimeout});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../../static/js/canvas-save-navigation.js'),'utf8'),context);
const leave = context.window.CanvasSaveNavigation.leave;

async function run(){
    let finish, saves=0, navigated=false, failed=0, cancelled=false;
    const options={cancelDebounce:()=>{cancelled=true;}, isSaving:()=>false, hasPending:()=>false,
        save:()=>{saves++; return new Promise(resolve=>{finish=resolve;});},
        failed:()=>{failed++;},navigate:()=>{navigated=true;}};
    const pending=leave(options);
    assert.ok(cancelled); assert.equal(saves,1); assert.equal(navigated,false);
    assert.equal(await leave(options),false,'double click cannot start a second save');
    finish(true); assert.equal(await pending,true); assert.equal(navigated,true);
    for(const result of [false,'retry']){
        navigated=false;
        assert.equal(await leave({...options,save:async()=>result}),false);
        assert.equal(navigated,false,'failure or conflict must keep the editor open');
    }
    navigated=false;
    assert.equal(await leave({...options,save:async()=>true,hasPending:()=>true}),false);
    assert.equal(navigated,false,'an edit made during the save must remain pending');
    let busy=true;
    const idle=leave({...options,isSaving:()=>busy,save:async()=>true});
    assert.equal(navigated,false);
    busy=false;
    assert.equal(await idle,true);
    assert.equal(failed,3);
    console.log('canvas save-before-return: passed');
}
run().catch(error=>{console.error(error);process.exitCode=1;});
