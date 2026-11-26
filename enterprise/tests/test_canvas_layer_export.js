const assert=require('node:assert/strict');
const D=require('../../static/js/canvas-layer-document.js');
global.CanvasLayerDocument=D;global.StudioI18n={t:key=>key};
const renders=[];
global.document={fonts:{ready:Promise.resolve()},createElement:()=>({toDataURL:()=> 'data:image/png;base64,fixture'})};
D.paint=async (doc,canvas)=>{renders.push(D.clone(doc));canvas.width=doc.width;canvas.height=doc.height;};
const E=require('../../static/js/canvas-layer-export.js');
const doc={width:200,height:300,layers:[
    {id:'base',kind:'image',name:'原始底图',asset:{url:'/assets/base.png'},x:0,y:0,width:200,height:300,rotation:0,opacity:1,visible:true},
    {id:'subject',kind:'image',name:'人物/服装',asset:{url:'/assets/subject.png'},x:20,y:50,width:80,height:160,rotation:90,opacity:.5,visible:false},
    {id:'text',kind:'text',name:'标题',text:'秋冬新品',x:10,y:10,width:100,height:30,fontSize:20,rotation:0,opacity:1,visible:true},
],annotations:[{kind:'pen',color:'#fff',width:2,points:[{x:1,y:1},{x:10,y:10}]}]};
(async()=>{
    const before=D.clone(doc),uploads=[];
    const options={loadImage:async()=>{},upload:async(data,name)=>{uploads.push(name);return {url:'/assets/'+name};}};
    const psd=await E.psdDocument(doc,options);
    assert.equal(psd.width,200);assert.equal(psd.height,300);
    assert.deepEqual(psd.children.map(x=>x.name),['原始底图','人物/服装','标题','layers.annotations']);
    assert.equal(psd.children[1].hidden,true);assert.equal(psd.children[1].opacity,.5);
    assert.equal(psd.children[1].canvas.width,160);assert.equal(psd.children[1].canvas.height,80);
    assert.equal(psd.children[1].left,-20);assert.equal(psd.children[1].top,90);
    assert.ok(renders.slice(0,3).every(d=>d.layers[0].visible&&d.layers[0].opacity===1),'visibility and opacity are metadata, not baked twice');
    const items=await E.zipItems(doc,options);
    assert.deepEqual(items.map(x=>x.name),['01_原始底图.png','02_人物_服装.png','03_标题.png','04_layers.annotations.png']);
    assert.equal(items[1].url,'/assets/subject.png','ZIP retains the original transparent image, including hidden layers');
    assert.equal(uploads.length,2,'only text and annotations need raster assets');
    assert.deepEqual(doc,before,'export must never rewrite the live layer document or original assets');
    const P=require('../../static/vendor/ag-psd/ag-psd-34.2.3.js');
    P.initializeCanvas(()=>{throw Error('binary fixture must use imageData');},(width,height)=>({width,height,data:new Uint8ClampedArray(width*height*4)}));
    const pixels=(width,height,values)=>({width,height,data:new Uint8ClampedArray(values)});
    const imageData=pixels(2,1,[200,100,20,255,20,30,40,64]);
    const bytes=P.writePsd({width:2,height:1,imageData,children:[{name:'原始底图',imageData},{name:'隐藏人物',hidden:true,opacity:.5,left:1,top:0,imageData:pixels(1,1,[10,20,30,127])}]});
    const restored=P.readPsd(bytes,{useImageData:true});
    assert.equal(restored.children.length,2);assert.equal(restored.children[1].name,'隐藏人物');
    assert.equal(restored.children[1].hidden,true);assert.ok(Math.abs(restored.children[1].opacity-.5)<.003);
    assert.equal(restored.children[1].left,1);assert.equal(restored.children[1].imageData.data[3],127);
    assert.equal(restored.imageData.data[7],64,'the PSD composite retains partial transparency too');
    console.log('Layer exports: original ZIP assets, raster text/annotations, transforms, metadata, immutability and layered PSD roundtrip passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
