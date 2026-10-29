const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const {dockPlacement} = require(path.join(root, 'static/js/canvas-dock.js'));
assert.deepEqual(dockPlacement({width:1200, height:704}, 44, null), {bottom:12, maxWidth:1176});
assert.deepEqual(dockPlacement({width:765, height:704}, 44, {left:532, right:755, top:650, bottom:695}),
    {bottom:12, maxWidth:279}, 'compact around the centered axis instead of reserving an empty row');
assert.deepEqual(dockPlacement({width:390, height:704}, 44, {left:80, right:380, top:650, bottom:695}),
    {bottom:64, maxWidth:366}, 'very narrow views still avoid the account controls');
assert.deepEqual(dockPlacement({width:765, height:704}, 44, {left:532, right:755, top:500, bottom:540}),
    {bottom:12, maxWidth:741}, 'an obstacle above the dock does not reserve bottom space');
const html = fs.readFileSync(path.join(root, 'static/canvas.html'), 'utf8');
const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
assert.equal(ids.length, new Set(ids).size, 'top and bottom controls must have unique IDs');
const top = html.slice(html.indexOf('<div class="topbar">'), html.indexOf('<div id="canvasDock"'));
for (const id of ['quickToolbar', 'workflowTransferToggle', 'canvasAssetToggle', 'canvasLogToggle']) {
    assert(top.includes(`id="${id}"`), `${id} remains in the original top toolbar`);
}
assert.equal((top.match(/onclick="add\w+Node\(\)"/g) || []).length, 11);
assert(top.includes('groupSelectedImages()'));

class Element {
    constructor(attrs = {}) {
        this.attrs = attrs; this.dataset = {}; this.handlers = {}; this.hidden = false;
        this.classes = new Set(); this.classList = {
            contains: name => this.classes.has(name),
            toggle: (name, on) => on ? this.classes.add(name) : this.classes.delete(name),
        };
        this.style = {setProperty: (name, value) => this.attrs[name] = value};
    }
    addEventListener(name, fn) { (this.handlers[name] ||= []).push(fn); }
    fire(name, event = {}) { for (const fn of this.handlers[name] || []) fn({target:this, ...event}); }
    setAttribute(name, value) { this.attrs[name] = value; }
    getAttribute(name) { return this.attrs[name]; }
    removeAttribute(name) { delete this.attrs[name]; }
    focus() { document.activeElement = this; }
    matches() { return Boolean(this.open); }
    closest() { return this; }
    scrollIntoView() { this.scrolled = true; }
    getBoundingClientRect() { return this.rect; }
}
const add = new Element(), choice = new Element(), menu = new Element(), more = new Element();
const actions = new Element(), dock = new Element(), shell = new Element(), map = new Element();
const panel = new Element(), target = new Element();
const shortcut = new Element({'aria-controls':'panel', 'aria-label':'资产库'});
shortcut.dataset.dockTarget = 'original';
const allButtons = [add, shortcut, more], frames = [], observers = [];
let targetClicks = 0, onClose;
target.click = () => { targetClicks++; panel.classList.toggle('open', !panel.classList.contains('open')); };
menu.querySelector = () => choice;
menu.contains = element => element === choice;
actions.contains = element => element === shortcut;
actions.clientWidth = 140; actions.scrollWidth = 320; actions.scrollLeft = 0;
actions.scrollBy = options => actions.lastScroll = options;
dock.rect = {left:200, right:580, top:580, height:44}; map.rect = {width:188};
dock.getBoundingClientRect = () => ({...dock.rect,
    top:dock.attrs['--canvas-dock-bottom'] ? 704 - parseFloat(dock.attrs['--canvas-dock-bottom']) - 44 : dock.rect.top});
dock.querySelector = name => ({'.dock-add':add, '.dock-actions':actions, '.dock-scroll':more})[name];
dock.querySelectorAll = name => name === '[data-dock-target]' ? [shortcut] : allButtons;
const elements = {canvasDock:dock, canvasAddMenu:menu, shell, minimap:map, original:target, panel};
const document = {
    getElementById: id => elements[id], activeElement:null,
    documentElement:new Element(), body:{append(){}},
    createElement: () => new Element(), addEventListener(){},
};
const context = {
    document, innerWidth:765, innerHeight:704, requestAnimationFrame: fn => frames.push(fn),
    ResizeObserver: class { observe(){} },
    MutationObserver: class { constructor(fn) { observers.push(fn); } observe(){} },
    matchMedia: () => ({matches:true}), setTimeout: () => 1, clearTimeout(){},
    parent:{}, addEventListener(){},
    StudioDropdowns:{
        openPanel: (_menu, button, close) => { menu.open = true; button.setAttribute('aria-expanded','true'); onClose = close; },
        closePanel: () => { menu.open = false; onClose?.(); },
    },
};
context.window = context;
vm.runInNewContext(fs.readFileSync(path.join(root, 'static/js/canvas-dock.js'),'utf8'), context);
while (frames.length) frames.shift()();
assert(shell.classList.contains('dock-map-stacked'), 'minimap gets its own row on horizontal collision');
assert.equal(shell.attrs['--canvas-dock-map-bottom'], '68px');
assert.equal(more.hidden, false, 'overflow has a visible affordance');
more.fire('click'); assert(actions.lastScroll.left > 0);
add.fire('click'); assert(menu.open); assert.equal(document.activeElement, choice);
menu.fire('keydown', {key:'Escape', preventDefault(){}, stopPropagation(){}});
assert(!menu.open); assert.equal(document.activeElement, add);
add.fire('click'); shortcut.fire('click');
assert.equal(targetClicks, 1, 'shortcut delegates to the existing top action exactly once');
assert(!menu.open); observers.forEach(fn => fn());
assert.equal(shortcut.getAttribute('aria-expanded'), 'true', 'panel state is reflected on the dock');
let gesturesShielded=0;
for(const name of ['pointerdown','mousedown','click','dblclick','wheel','keydown'])
    dock.fire(name,{stopPropagation(){gesturesShielded++;}});
assert.equal(gesturesShielded,6,'toolbar interactions cannot bubble into canvas gestures or node hotkeys');
dock.fire('keydown',{key:'Escape',stopPropagation(){gesturesShielded++;}});
assert.equal(gesturesShielded,6,'Escape still reaches the existing panel close handlers');
document.activeElement = add;
dock.fire('keydown', {key:'ArrowRight', preventDefault(){}, stopPropagation(){}});
assert.equal(document.activeElement, shortcut); assert(shortcut.scrolled);
console.log('Top toolbar preserved; dock panel routing, Escape, keyboard and overflow/corner behavior passed.');

const smartHtml=fs.readFileSync(path.join(root,'static/smart-canvas.html'),'utf8');
const smartIds=[...smartHtml.matchAll(/\bid="([^"]+)"/g)].map(match=>match[1]);
assert.equal(smartIds.length,new Set(smartIds).size);
assert(smartHtml.includes('/static/css/canvas-dock.css?') && smartHtml.includes('/static/js/canvas-dock.js?'),'both canvases load the shared dock');
assert(smartHtml.indexOf('id="canvasDock"')>smartHtml.indexOf('id="smartTitle"'),'smart dock is outside the transformed world');
for(const [button,panelId] of [['smartWorkflowToggle','smartWorkflowTransferModal'],['assetToggle','assetPanel'],['smartLogToggle','smartLogModal']]){
    assert(smartHtml.includes(`data-dock-target="${button}" aria-controls="${panelId}"`));
    assert(smartHtml.includes(`id="${button}"`) && smartHtml.includes(`id="${panelId}"`),'original top controls and panels remain');
}
const smartScript=fs.readFileSync(path.join(root,'static/js/smart-canvas.js'),'utf8');
const adapters=smartScript.slice(smartScript.indexOf('function createSmartDockNode('),smartScript.indexOf("shell.addEventListener('mousedown'",smartScript.indexOf('function createSmartDockNode(')));
const created=[],centers=[];
const smartContext={canvas:{id:'fixture'},createMenuPoint:{x:-100,y:-100},createMenuGroupId:'old-group',
    closeCreateMenu(){smartContext.createMenuGroupId='';},clearSelection(){},viewportCenter:()=>({x:200,y:300}),
    createNodeFromMenu(type){created.push(type);assert.equal(smartContext.createMenuPoint.x,200);assert.equal(smartContext.createMenuGroupId,'');},
    selectedNode:()=>({type:'smart-image'}),isSmartRunnableNode:node=>Boolean(node),zoomPreviewState:null,
    updateComposer(){},composer:{style:{left:'100px',top:'200px'},offsetWidth:540,offsetHeight:300},
    centerViewportOnWorldPoint:point=>centers.push(point),promptInput:{focus:options=>assert.equal(options.preventScroll,true)}};
vm.createContext(smartContext);vm.runInContext(adapters,smartContext);
for(const type of ['image','prompt','loop','group'])smartContext.createSmartDockNode(type);
assert.deepEqual(created,['image','prompt','loop','group']);
smartContext.focusSmartDockGeneration();assert.equal(created.length,4,'selected runnable node is reused');
assert.equal(centers[0].x,370);assert.equal(centers[0].y,350);
smartContext.selectedNode=()=>null;smartContext.focusSmartDockGeneration();assert.equal(created.at(-1),'image');
assert(!adapters.includes('fetch(') && !adapters.includes('runGeneration('),'dock only opens settings and never submits paid work');
console.log('Smart dock reuses original top panels, creation placement and composer without submitting generation.');
