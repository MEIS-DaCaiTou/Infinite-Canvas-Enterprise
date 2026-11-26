const assert=require('node:assert/strict');
const D=require('../../static/js/canvas-layer-document.js');
const {get}=require('../../static/js/canvas-layer-session.js');
const B=require('../../static/js/canvas-layer-bitmap.js');
const node={id:'shared',layerDocument:D.fromOutputs([{url:'/base.png',width:1000,height:760},{url:'/headline.png',width:300,height:80}])};
const inline=get(node);inline.selected=inline.doc.layers[0].id;inline.remember();inline.layer().x=90;
const fullscreen=get(node);
assert.equal(fullscreen,inline);assert.equal(fullscreen.selected,'layer-0');
assert.equal(fullscreen.layer().x,90);assert.equal(fullscreen.undo.length,1);
fullscreen.history(-1);assert.equal(inline.layer().x,0);fullscreen.history(1);assert.equal(inline.layer().x,90);
fullscreen.startCrop();fullscreen.cropRatio(1);assert.equal(fullscreen.crop.width,760);assert.equal(fullscreen.crop.x,120);
fullscreen.action('apply-crop');assert.equal(inline.layer().width,760);assert.equal(inline.layer().x,210);
assert.equal(inline.layer().crop.x,.12);assert.equal(inline.layer().crop.width,.76);
fullscreen.history(-1);assert.equal(inline.layer().width,1000);assert.equal(inline.layer().crop,undefined);
const linked={url:'/linked.png',name:'Logo'};
inline.addImage(linked,200,200,'source');assert.equal(inline.addImage(linked,200,200,'source'),null);
assert.ok(inline.addImage(linked,200,200)); // Intentional duplicate imports are independent layers.
const width=9,height=9,pixels=new Uint8ClampedArray(width*height*4);pixels.fill(255);
for(let y=2;y<=6;y++)for(let x=2;x<=6;x++){const i=(y*width+x)*4;pixels[i]=220;pixels[i+1]=0;pixels[i+2]=50;}
const center=(4*width+4)*4;pixels[center]=pixels[center+1]=pixels[center+2]=255;
const mask=B.foreground(pixels,width,height),output=B.apply(pixels,mask);
assert.equal(output[3],0);assert.equal(output[center+3],255);assert.deepEqual([...output.slice(center,center+3)],[255,255,255]);
assert.equal(output[(2*width+2)*4+3],255);assert.equal(pixels[3],255); // Original bytes remain intact.
console.log('Shared selection/history, crop, source deduplication and enclosed white logo details passed');
