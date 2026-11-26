const assert=require('node:assert/strict');
const D=require('../../static/js/canvas-layer-document.js');
const items=Array.from({length:100},(_,index)=>({url:`/assets/output/${index}.png`,z_index:index,
    width:index===0?2000:400,height:index===0?1000:200,
    bounding_box:{normalized:[100,200,300,600]}}));
let doc=D.fromOutputs(items.reverse());
assert.equal(doc.layers.length,100);assert.equal(doc.width,2000);assert.equal(doc.height,1000);
assert.equal(doc.layers[0].asset.z_index,0);
assert.deepEqual([doc.layers[1].x,doc.layers[1].y,doc.layers[1].width,doc.layers[1].height],[200,200,400,400]);
assert.equal(D.hit(doc,220,220).id,'layer-99');
doc.layers[99].visible=false;assert.equal(D.hit(doc,220,220).id,'layer-98');
D.moveLayer(doc,'layer-1',1);assert.equal(doc.layers[2].id,'layer-1');
const source=doc.layers[2];source.asset.text_recognition={text:'Sale',lines:[{
    bounding_box:{absolute:[100,300,700,400]},runs:[{text:'Sale',style:{bold:true,foreground_color:'#123456'}}]}]};
const texts=D.textLayers(source,doc);assert.equal(texts[0].text,'Sale');assert.equal(texts[0].x,100);
assert.equal(texts[0].y,300);assert.equal(texts[0].color,'#123456');assert.equal(texts[0].bold,true);
doc.layers.push(...texts);doc.layers[2].visible=false;
const restored=JSON.parse(JSON.stringify(doc));assert.deepEqual(restored,doc);
assert.equal(restored.layers[2].asset.text_recognition.text,'Sale');
const added=D.addText(doc,'New headline');assert.equal(added.text,'New headline');
assert.equal(doc.layers[0].locked,false);assert.equal(doc.layers[0].width,2000);
const before={x:10,y:20,width:100,height:200,rotation:0,kind:'image'};
const resized={...before};D.resize(resized,before,'se',50,0);
assert.deepEqual([resized.x,resized.y,resized.width,resized.height],[10,20,150,300]);
// Identical URLs at different z indices remain different editable layers.
assert.equal(D.fromOutputs([{url:'/same.png',z_index:0},{url:'/same.png',z_index:1}]).layers.length,2);
console.log('Layer document: 100 outputs, coordinates, hit testing, ordering, OCR and persistence passed');
