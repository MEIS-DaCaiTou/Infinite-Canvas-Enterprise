const assert=require('node:assert/strict');
const R=require('../../static/js/canvas-layer-edit-result.js');
const marks=[{kind:'marker',rect:{x:.25,y:.25,width:.5,height:.5}}];
assert.deepEqual(R.regionsFor(marks),[marks[0].rect]);
assert.deepEqual(R.regionsFor([...marks,{kind:'marker',points:[{x:0,y:0}]}]),[],'point hints cannot silently become a bounded mask');
assert.deepEqual(R.regionsFor([{kind:'pen',rect:marks[0].rect}]),[]);
const width=4,height=4,source=new Uint8ClampedArray(width*height*4),generated=new Uint8ClampedArray(source.length);
for(let i=0;i<source.length;i+=4){source.set([12+i,35,80,i*4],i);generated.set([200,120,90,255],i);}
const output=R.compose(source,generated,width,height,R.regionsFor(marks),{keepAlpha:true});
for(let y=0;y<height;y++)for(let x=0;x<width;x++){
    const i=(y*width+x)*4,inside=x>=1&&x<3&&y>=1&&y<3;
    assert.deepEqual([...output.slice(i,i+3)],[...(inside?generated:source).slice(i,i+3)]);
    assert.equal(output[i+3],source[i+3],'the original alpha, including partial opacity, is retained');
}
assert.notDeepEqual(output,source,'the selected region must actually use generated pixels');
assert.equal(generated[7],255);assert.equal(source[0],12,'neither source nor raw model output is mutated');
const nativeAlpha=new Uint8ClampedArray(generated);nativeAlpha[23]=0;
assert.equal(R.compose(source,nativeAlpha,width,height,R.regionsFor(marks))[23],0,'an opaque source can gain transparency inside its boxes');
const union=R.compose(source,generated,width,height,[{x:0,y:0,width:.5,height:.5},{x:.25,y:.25,width:.5,height:.5}],{keepAlpha:true});
assert.equal(union[0],200);assert.equal(union[40],200);assert.equal(union[60],source[60]);
console.log('Bounded edit pixels: exact protected region, box union, source alpha and immutable raw output passed');
