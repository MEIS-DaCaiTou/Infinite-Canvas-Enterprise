const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.resolve(__dirname,'../..');
const read=name=>fs.readFileSync(path.join(root,'static/js',name),'utf8');
const listeners=new Map(),storage=new Map();
const labels=[{dataset:{entLabel:'admin'}},{dataset:{entLabel:'logout'}}];
const context={localStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)},
    CustomEvent:class{constructor(type,options){this.type=type;this.detail=options?.detail;}},
    document:{title:'',querySelectorAll:selector=>selector.startsWith('#__ent_bar__')?labels:[],querySelector:()=>null,getElementById:()=>null,addEventListener(){},documentElement:{setAttribute(){}}},
    addEventListener(type,fn){const list=listeners.get(type)||[];list.push(fn);listeners.set(type,list);},
    dispatchEvent(event){(listeners.get(event.type)||[]).forEach(fn=>fn(event));}};
context.window=context;vm.createContext(context);
for(const file of ['i18n-core.js','i18n/admin.js','enterprise-shell-ui.js'])vm.runInContext(read(file),context);
assert.equal(labels[0].textContent,'管理后台');
context.StudioI18n.set('en');
assert.equal(context.adminT('成员与部门'),'Members & Departments');assert.equal(labels[0].textContent,'Administration');assert.equal(labels[1].textContent,'Sign out');
assert.equal(context.adminT('设计部·开发预览'),'设计部·开发预览');
storage.set('studio_lang','zh');context.dispatchEvent({type:'storage',key:'studio_lang'});
assert.equal(context.adminT('Members & Departments'),'成员与部门');assert.equal(labels[0].textContent,'管理后台');

// Follow actual port centers under ancestor zoom, then follow a drag without rebuilding cards.
let shift=0,observed=0,disposed=0,d='';
const port=(x,y)=>({getBoundingClientRect:()=>({left:x+shift,top:y,width:10,height:10})});
const from=port(280,190),to=port(380,220);
const cards=[{dataset:{node:'a'},querySelector:()=>from},{dataset:{node:'b'},querySelector:()=>to}];
const link={dataset:{miniFrom:'a',miniTo:'b'},setAttribute:(_key,value)=>d=value};
const world={offsetWidth:900,getBoundingClientRect:()=>({left:100,top:50,width:1125}),querySelectorAll:selector=>selector.includes('mini-card')?cards:[link]};
const geometry={ResizeObserver:class{observe(){observed++;}disconnect(){disposed++;}}};geometry.window=geometry;vm.createContext(geometry);
vm.runInContext(read('comfy-preview-links.js'),geometry);
const binding=geometry.ComfyPreviewLinks.mount(world);assert.equal(observed,2);assert.match(d,/^M 148 116 C .* 228 140$/);
shift=50;binding.update();assert.match(d,/^M 188 116 C .* 268 140$/);binding.dispose();assert.equal(disposed,1);

// The visible node list must refresh, even when no node popup is open.
const source=read('comfyui-settings.js');let renders=0;
let focused=0;const select={};
const options=vm.createContext({currentConfig:{fields:[{id:'f',node:'459:451',options:[]}]},testSession:{revision:0},popupNodeId:null,
    previewValues:{},CSS:{escape:value=>value},document:{querySelectorAll:()=>[select]},nodeListEl:{querySelector:()=>({focus:()=>focused++})},escapeAttr:value=>value,escapeHtml:value=>value,
    renderEditor:()=>renders++,renderPreview(){},refreshPopupBody(){throw Error('No popup should be required');}});
for(const name of ['syncDropdownPreview','updateDropdownOption','addDropdownOption','removeDropdownOption']){
    const start=source.indexOf('function '+name+'('),end=source.indexOf('\n}',start)+2;
    vm.runInContext(source.slice(start,end),options);
}
options.addDropdownOption('f');assert.equal(options.currentConfig.fields[0].options.length,1);assert.equal(renders,1);assert.equal(focused,1);
options.removeDropdownOption('f',0);assert.equal(options.currentConfig.fields[0].options.length,0);assert.equal(renders,2);assert.equal(options.testSession.revision,2);
options.updateDropdownOption('f',0,'new-model.safetensors');assert.equal(options.previewValues.f,'new-model.safetensors');assert.equal(options.currentConfig.fields[0].default,'new-model.safetensors');assert.equal(select.value,'new-model.safetensors');
console.log('Cross-tab language, protected business labels, rendered port geometry and inline option editing passed');
