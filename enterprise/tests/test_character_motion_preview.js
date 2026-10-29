const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
let observers=0,events=0;
const context={window:{addEventListener(){events++;}},AbortController,
    document:{createElement(){return {setAttribute(){},remove(){this.removed=true;}};}},
    MutationObserver:class{constructor(){observers++;}}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../static/js/character-motion-preview.js'),'utf8'),context);
const host={children:[],append(node){this.children.push(node);},classList:{add(){}}};
const preview=new context.window.CharacterMotionPreview(host,'pending');
assert.equal(host.children.length,1,'a public checkout renders the bundled geometric placeholder');
assert(host.children[0].innerHTML.includes('<svg'));
assert.equal(observers,0);assert.equal(events,0,'no renderer dependencies or theme listeners are required');
preview.setPhase('loading');preview.destroy();preview.destroy();
assert.equal(host.children[0].removed,true);
console.log('Public character preview works and disposes without optional reference assets.');
