/* Layer document coordinates are always relative to the output base image. */
(function(root){
    const clone = value => JSON.parse(JSON.stringify(value));
    function box(value, width, height){
        if(value?.absolute?.length === 4) return value.absolute;
        if(value?.normalized?.length === 4) return value.normalized.map((n,i)=>n/1000*(i%2 ? height : width));
        return [0,0,width,height];
    }
    function fromOutputs(items, source={}){
        const ordered=items.filter(item=>item?.url).map((item,index)=>({...item,z_index:item.z_index ?? index})).sort((a,b)=>a.z_index-b.z_index);
        const base=ordered.find(item=>item.z_index===0) || ordered[0] || source;
        const width=Number(base.natural_w || base.width || source.natural_w || source.width || 1024);
        const height=Number(base.natural_h || base.height || source.natural_h || source.height || 1024);
        return {version:2,width,height,source:clone(source),layers:ordered.map((item,index)=>{
            const [x,y,right,bottom]=index===0 ? [0,0,width,height] : box(item.bounding_box,width,height);
            return {id:'layer-'+index,kind:'image',name:item.name || '',asset:clone(item),x,y,
                width:right-x,height:bottom-y,rotation:0,opacity:1,visible:true,locked:false};
        })};
    }
    function textLayers(layer, doc){
        const recognition=layer.asset?.text_recognition;
        if(!recognition) return [];
        const lines=recognition.lines?.length ? recognition.lines : [{runs:[{text:recognition.text}],bounding_box:layer.asset.bounding_box}];
        return lines.map((line,index)=>{
            const [x,y,right,bottom]=box(line.bounding_box,doc.width,doc.height);
            const style=line.runs?.[0]?.style || {};
            return {id:layer.id+'-text-'+index,kind:'text',name:'',text:(line.runs || []).map(run=>run.text).join(''),
                x,y,width:right-x,height:bottom-y,fontSize:Math.max(12,Math.round((bottom-y)*8.2)/10),
                fontFamily:style.similar_font_family==='unknown' ? 'Arial' : (style.similar_font_family || 'Arial'),
                color:style.foreground_color || '#111827',bold:Boolean(style.bold),italic:Boolean(style.italic),
                visible:true,locked:false,opacity:style.translucent ? .7 : 1,rotation:0,sourceLayerId:layer.id};
        });
    }
    function addText(doc, text){
        const size=Math.max(18,Math.round(doc.width*.055));
        const layer={id:'text-'+Date.now().toString(36),kind:'text',name:'',text,x:doc.width*.1,y:doc.height*.1,
            width:doc.width*.8,height:size*1.4,fontSize:size,fontFamily:'Arial',color:'#111827',bold:false,italic:false,
            rotation:0,opacity:1,visible:true,locked:false};
        doc.layers.push(layer);return layer;
    }
    function moveLayer(doc,id,direction){
        const i=doc.layers.findIndex(layer=>layer.id===id), next=i+direction;
        if(i<0 || next<0 || next>=doc.layers.length) return;
        [doc.layers[i],doc.layers[next]]=[doc.layers[next],doc.layers[i]];
    }
    function hit(doc,x,y){
        return [...doc.layers].reverse().find(layer=>{
            if(!layer.visible || layer.locked) return false;
            const angle=-layer.rotation*Math.PI/180,dx=x-layer.x-layer.width/2,dy=y-layer.y-layer.height/2;
            return Math.abs(dx*Math.cos(angle)-dy*Math.sin(angle))<=layer.width/2 &&
                Math.abs(dx*Math.sin(angle)+dy*Math.cos(angle))<=layer.height/2;
        });
    }
    function resize(layer,initial,corner,dx,dy,keepAspect=true){
        const angle=initial.rotation*Math.PI/180,c=Math.cos(angle),s=Math.sin(angle);
        const localX=dx*c+dy*s,localY=-dx*s+dy*c;
        let width=initial.width+(corner.includes('e')?localX:corner.includes('w')?-localX:0);
        let height=initial.height+(corner.includes('s')?localY:corner.includes('n')?-localY:0);
        width=Math.max(5,width);height=Math.max(5,height);
        if(keepAspect && corner.length===2)height=width*initial.height/initial.width;
        const offsetX=(width-initial.width)*(corner.includes('w')?-.5:corner.includes('e')?.5:0);
        const offsetY=(height-initial.height)*(corner.includes('n')?-.5:corner.includes('s')?.5:0);
        layer.width=width;layer.height=height;
        layer.x=initial.x+initial.width/2+offsetX*c-offsetY*s-width/2;
        layer.y=initial.y+initial.height/2+offsetX*s+offsetY*c-height/2;
        if(layer.kind==='text')layer.fontSize=initial.fontSize*width/initial.width;
    }
    async function paint(doc,canvas,{scale=1,loadImage,selection=''}={}){
        canvas.width=Math.round(doc.width*scale);canvas.height=Math.round(doc.height*scale);
        const ctx=canvas.getContext('2d');ctx.scale(scale,scale);
        for(const layer of doc.layers){
            if(!layer.visible) continue;
            const image=layer.kind==='image' ? await loadImage(layer.asset.url) : null;
            ctx.save();ctx.globalAlpha=layer.opacity;ctx.translate(layer.x+layer.width/2,layer.y+layer.height/2);
            ctx.rotate(layer.rotation*Math.PI/180);ctx.scale(layer.flipX?-1:1,layer.flipY?-1:1);ctx.translate(-layer.width/2,-layer.height/2);
            if(image){
                const c=layer.crop || {x:0,y:0,width:1,height:1};
                ctx.drawImage(image,c.x*image.width,c.y*image.height,c.width*image.width,c.height*image.height,0,0,layer.width,layer.height);
            }
            else {
                ctx.fillStyle=layer.color;ctx.textBaseline='top';
                ctx.font=`${layer.italic ? 'italic ' : ''}${layer.fontWeight || (layer.bold ? 700 : 400)} ${layer.fontSize}px ${JSON.stringify(layer.fontFamily)},sans-serif`;
                String(layer.text).split('\n').forEach((line,index)=>ctx.fillText(line,0,index*layer.fontSize*(layer.lineHeight||1.2),layer.width));
            }
            if(layer.id===selection){ctx.globalAlpha=1;ctx.strokeStyle='#4f9cf9';ctx.lineWidth=2/scale;ctx.strokeRect(0,0,layer.width,layer.height);}
            ctx.restore();
        }
        for(const annotation of doc.annotations || []){
            const points=annotation.points;if(!points?.length)continue;
            ctx.save();ctx.strokeStyle=annotation.color;ctx.fillStyle=annotation.color;ctx.lineWidth=annotation.width;ctx.lineCap='round';ctx.lineJoin='round';
            ctx.beginPath();ctx.moveTo(points[0].x,points[0].y);points.slice(1).forEach(p=>ctx.lineTo(p.x,p.y));ctx.stroke();
            if(annotation.kind==='arrow' && points.length>1){
                const a=points[0],b=points.at(-1),angle=Math.atan2(b.y-a.y,b.x-a.x),length=annotation.width*4+12;
                ctx.beginPath();ctx.moveTo(b.x,b.y);ctx.lineTo(b.x-length*Math.cos(angle-.45),b.y-length*Math.sin(angle-.45));
                ctx.lineTo(b.x-length*Math.cos(angle+.45),b.y-length*Math.sin(angle+.45));ctx.closePath();ctx.fill();
            }
            ctx.restore();
        }
    }
    // Keep source pixels and editing parameters separate from the canvas preview.
    function extractLayer(doc,id){
        const layer=doc.layers.find(l=>l.id===id),r=layer.rotation*Math.PI/180;
        const width=Math.abs(layer.width*Math.cos(r))+Math.abs(layer.height*Math.sin(r));
        const height=Math.abs(layer.width*Math.sin(r))+Math.abs(layer.height*Math.cos(r));
        const x=Math.floor(layer.x+layer.width/2-width/2),y=Math.floor(layer.y+layer.height/2-height/2);
        const direct=layer.kind==='image'&&layer.rotation%360===0&&layer.opacity===1&&!layer.crop&&!layer.flipX&&!layer.flipY;
        const bounds=direct?{x:layer.x,y:layer.y,width:layer.width,height:layer.height}:{x,y,width:Math.ceil(layer.x+layer.width/2+width/2)-x,height:Math.ceil(layer.y+layer.height/2+height/2)-y};
        const remaining=clone(doc);remaining.layers=remaining.layers.filter(l=>l.id!==id);
        const isolated={...clone(layer),x:layer.x-bounds.x,y:layer.y-bounds.y};
        for(const key of ['sourceNodeId','sourceUrl','sourceLayerId'])delete isolated[key];
        return {bounds,remaining,directAsset:direct?clone(layer.asset):null,document:{width:bounds.width,height:bounds.height,annotations:[],layers:[isolated]}};
    }
    function placeLayer(fragment,bounds){
        const layer=clone(fragment.layers[0]),scale=Math.min(bounds.width/fragment.width,bounds.height/fragment.height);
        layer.x=bounds.x+(bounds.width-fragment.width*scale)/2+layer.x*scale;
        layer.y=bounds.y+(bounds.height-fragment.height*scale)/2+layer.y*scale;
        layer.width*=scale;layer.height*=scale;if(layer.kind==='text')layer.fontSize*=scale;
        return layer;
    }
    const api={clone,box,fromOutputs,textLayers,addText,moveLayer,hit,resize,paint,extractLayer,placeLayer};
    if(typeof module!=='undefined') module.exports=api;
    root.CanvasLayerDocument=api;
})(typeof window!=='undefined' ? window : globalThis);
