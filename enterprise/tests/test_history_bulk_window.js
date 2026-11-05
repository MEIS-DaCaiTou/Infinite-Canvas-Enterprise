'use strict';
const assert=require('assert/strict'),fs=require('fs'),vm=require('vm');
class Node{
 constructor(){this.children=[];this.dataset={};this.handlers={};this.classes=new Set();this.classList={add:k=>this.classes.add(k),remove:k=>this.classes.delete(k),toggle:(k,v)=>v?this.classes.add(k):this.classes.delete(k)};}
 set innerHTML(_){this.label=new Node();}querySelector(){return this.label;}
 append(...children){children.forEach(c=>{c.parentNode=this;this.children.push(c);});}
 appendChild(c){this.append(c);}insertBefore(c,next){c.parentNode=this;this.children.splice(this.children.indexOf(next),0,c);}
 querySelectorAll(){return this.children.filter(c=>c.dataset.historyTs!==undefined);}
 addEventListener(name,fn){this.handlers[name]=fn;}contains(c){return this.children.includes(c);}
 closest(){return this;}remove(){this.parentNode.children=this.parentNode.children.filter(c=>c!==this);}
}
async function check(model){
 const parent=new Node(),grid=new Node(),body=new Node();parent.append(grid);
 const visible=new Node();visible.dataset.historyTs='1';grid.append(visible);
 let rows=Array.from({length:480},(_,i)=>({timestamp:i+1})),fail=true,requests=[];
 const scope=vm.createContext({window:{addEventListener(){}},document:{head:new Node(),body,getElementById:()=>true,querySelector:()=>grid,createElement:()=>new Node()},
  confirm:()=>true,alert(){},fetch:async(_,options)=>{const ts=JSON.parse(options.body).timestamp;requests.push(ts);if(fail){fail=false;return{ok:false,json:async()=>({success:false})};}return{ok:true,json:async()=>({success:true})};}});
 vm.runInContext(fs.readFileSync(require('path').join(__dirname,'../../static/js/history-bulk-manager.js'),'utf8'),scope);
 const api=scope.window.HistoryBulkManager.attach(model?{entries:()=>rows,remove:ts=>{rows=rows.filter(r=>String(r.timestamp)!==ts);}}:{});
 api.enter();parent.children[0].children[3].handlers.click();
 assert.equal(api.isSelected(1),true);assert.equal(api.isSelected(480),model);
 // Keep only record 1 selected and release its DOM card, as window scrolling does.
 parent.children[0].children[3].handlers.click();
 grid.handlers.click({target:visible,preventDefault(){},stopPropagation(){}});
 if(model)visible.remove();
 const button=parent.children[0].children[4];
 await button.handlers.click();assert(api.isSelected(1),'failure preserves selected record');
 await button.handlers.click();assert(!api.isSelected(1));assert.deepEqual(requests,['1','1']);
 if(model)assert.equal(rows.length,479);else assert.equal(grid.children.length,0);
 api.exit();
}
(async()=>{await check(true);await check(false);console.log('history bulk: offscreen selection, failed-delete retry, model removal and legacy DOM consumer passed');})().catch(e=>{console.error(e);process.exitCode=1;});
