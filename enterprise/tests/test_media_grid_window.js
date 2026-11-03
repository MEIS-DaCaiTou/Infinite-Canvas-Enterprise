'use strict';
const assert=require('node:assert/strict');
const {range}=require('../../static/js/media-grid-window.js');
for(const count of [0,1,24,480,5000,20000])for(const columns of [2,5]){
    for(const top of [0,140,1000,10000000]){
        const height=142,gap=8,viewport=440,window=range(count,columns,height,gap,top,viewport);
        assert.ok(window.start>=0 && window.end<=count && window.end>=window.start);
        assert.equal(window.start%columns,0);
        assert.ok(window.end-window.start<=columns*(Math.ceil(viewport/(height+gap))+5),'DOM window must not grow with loaded metadata');
        const visibleRows=Math.ceil((window.end-window.start)/columns);
        const spacerCount=Number(window.before>0)+Number(window.after>0);
        const extent=window.before+window.after+visibleRows*height+Math.max(0,visibleRows+spacerCount-1)*gap;
        assert.equal(extent,Math.max(0,Math.ceil(count/columns)*height+(Math.ceil(count/columns)-1)*gap),'partial last row must preserve scroll extent');
    }
}
assert.equal(range(480,5,194,12,206*40,500).start,190);
assert.equal(range(480,2,125,8,0,220).start,0);
console.log('media grid: bounded visible range, resize columns, exact spacers and partial end rows passed');

// Exercise the actual DOM lifecycle without a browser dependency: only the
// active window may be created, retained cards survive, removed media releases.
class Element{
    constructor(){this.children=[];this.style={};this.clientHeight=440;this.offsetHeight=142;this.scrollTop=0;this.parentNode=null;}
    append(...nodes){for(const node of nodes){node.remove();this.children.push(node);node.parentNode=this;}}
    insertBefore(node,next){if(node===next)return;node.remove();const index=this.children.indexOf(next);this.children.splice(index<0?this.children.length:index,0,node);node.parentNode=this;}
    remove(){if(this.parentNode){const index=this.parentNode.children.indexOf(this);this.parentNode.children.splice(index,1);this.parentNode=null;}}
    get nextSibling(){return this.parentNode?.children[this.parentNode.children.indexOf(this)+1]||null;}
    setAttribute(){}addEventListener(){}removeEventListener(){}
}
global.document={createElement:()=>new Element()};
global.getComputedStyle=()=>({gridTemplateColumns:'140px 140px',rowGap:'8px'});
global.ResizeObserver=class{observe(){}disconnect(){}};
global.requestAnimationFrame=()=>1;global.cancelAnimationFrame=()=>{};
const element=new Element(),created=[],released=[];
const grid=new global.MediaGridWindow(element,{columns:2,height:142,key:item=>item.id,
    create:item=>{created.push(item.id);const card=new Element();card.id=item.id;return card;},
    release:card=>released.push(card.id)});
const items=Array.from({length:20000},(_,id)=>({id})),footer=new Element();
grid.setItems(items,{footer});assert.ok(grid.cards.size<=16);
const first=grid.cards.get(0);grid.setItems(items,{footer});assert.strictEqual(grid.cards.get(0),first);
element.scrollTop=150*400;grid.paint();assert.ok(grid.cards.size<=16);assert.ok(released.includes(0));
const last=grid.reveal(19999);assert.equal(last.id,19999);assert.ok(grid.cards.size<=16);
assert.strictEqual(element.children.at(-1),footer,'paging control stays after full scroll extent');
grid.clear();assert.equal(grid.cards.size,0);assert.ok(released.length===created.length);
grid.dispose();assert.equal(element.children.length,0);
console.log('media grid: real window lifecycle, retained DOM, released offscreen cards, reveal and dispose passed');
