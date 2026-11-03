"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "../..");
let created = 0, destroyed = 0;
const context = vm.createContext({
  window: {},
  document: { createElement: () => ({dataset:{}}) },
  CharacterMotionPreview: class { constructor() {created++;} destroy() {destroyed++;} },
});
vm.runInContext(fs.readFileSync(path.join(root,"static/js/character-library-view.js"),"utf8"),context);
const Library = context.window.CharacterLibraryView;
const filters = [{dataset:{filterLabel:"性别"},open:true,classList:{remove(){}},
  inputs:[{checked:true}],summary:{replaceChildren(...nodes){this.nodes=nodes;}},
  querySelectorAll(){return this.inputs;},querySelector(){return this.summary;}}];
const library = Object.assign(Object.create(Library.prototype), {
  root:{querySelectorAll(selector){return selector===".character-filter"?filters:[];}},
  filters:{gender:["female"]},search:{value:"验收"},searchButton:{hidden:true},
  searchLabel:{hidden:false},clearFiltersButton:{hidden:false},
  picked:new Set(["owned"]),mode:"grid",source:"official",archived:true,multiple:true,
  items:[{id:"owned"}],closeAssets(){},
});
const items = library.items;
library.resetHome();
assert.equal(library.search.value,"");
assert.equal(filters[0].inputs[0].checked,false);
assert.equal(filters[0].summary.nodes[0].textContent,"性别");
assert.equal(library.source,"personal");
assert.equal(library.mode,"carousel");
assert.equal(library.selectedId,"character-studio-create-slot");
assert.equal(library.items,items,"landing reset must not replace owned role data");
Object.assign(library,{grid:{querySelectorAll(){return [];},querySelector(){return {};}},
  syncTabs(){},syncFooter(){},callbacks:{onSelect(){}}});
library.choose({id:"owned",source:"personal"});
const mannequin=library.motion;
library.choose({id:"another",source:"personal"});
assert.equal(created,1);
assert.equal(destroyed,0);
assert.equal(library.motion,mannequin,"neighbor selection must retain the mannequin");
vm.runInContext(fs.readFileSync(path.join(root,"static/js/character-studio.js"),"utf8")
  .replace("window.CharacterStudio = {","window.TestStudio = CharacterStudio; window.CharacterStudio = {"),context);
(async()=>{
  for (const state of ["clean","dirty","creation","image"]) {
    let resets=0,loads=0;
    const draft={id:"owned"};
    const studio={dirty:state==="dirty",draft,creation:{root:{hidden:state!=="creation"}},
      imageAction:{root:{hidden:state!=="image"}},dialog:{open:false,showModal(){this.open=true;}},
      setEditing(){},gallery:{resetHome(){resets++;}},async load(){loads++;}};
    await context.window.TestStudio.prototype.open.call(studio);
    assert.equal(loads,1);
    assert.equal(resets,state==="clean"?1:0);
    assert.equal(studio.draft,state==="clean"?null:draft,"unsaved/recoverable context must survive");
  }
  console.log("Character library: complete landing, clear filters, retained mannequin and unsaved/recovery context passed");
})().catch(error=>{console.error(error);process.exitCode=1;});
