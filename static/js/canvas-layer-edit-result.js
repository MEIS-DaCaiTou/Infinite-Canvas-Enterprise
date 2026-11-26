/* A bounded edit reuses source pixels outside the user's boxes. This is local
 * composition, independent of supplier protocols and persistent task storage.
 * Transparent bounded edits keep the source silhouette; unrestricted edits
 * still require a real transparent response from the selected supplier.
 */
(function(root){
    function regionsFor(marks){
        if(!marks.length||marks.some(m=>m.kind!=='marker'||!m.rect||m.rect.width<=0||m.rect.height<=0))return [];
        return marks.map(m=>({...m.rect}));
    }
    function compose(source,generated,width,height,regions,{keepAlpha=false}={}){
        const output=new Uint8ClampedArray(source);
        for(const r of regions){
            const left=Math.max(0,Math.floor(r.x*width)),top=Math.max(0,Math.floor(r.y*height));
            const right=Math.min(width,Math.ceil((r.x+r.width)*width)),bottom=Math.min(height,Math.ceil((r.y+r.height)*height));
            for(let y=top;y<bottom;y++)for(let x=left;x<right;x++){
                const i=(y*width+x)*4;
                output[i]=generated[i];output[i+1]=generated[i+1];output[i+2]=generated[i+2];
                output[i+3]=keepAlpha?source[i+3]:generated[i+3];
            }
        }
        return output;
    }
    async function prepare(regionEdit,item,{loadImage,upload,createCanvas}){
        const {width,height,regions,source,keepAlpha}=regionEdit;
        const [original,generated]=await Promise.all([loadImage(source.url),loadImage(item.url)]);
        const canvas=createCanvas();canvas.width=width;canvas.height=height;
        const ctx=canvas.getContext('2d');ctx.drawImage(original,0,0,width,height);
        const sourcePixels=ctx.getImageData(0,0,width,height);
        ctx.clearRect(0,0,width,height);ctx.drawImage(generated,0,0,width,height);
        const generatedPixels=ctx.getImageData(0,0,width,height);
        sourcePixels.data.set(compose(sourcePixels.data,generatedPixels.data,width,height,regions,{keepAlpha}));
        ctx.putImageData(sourcePixels,0,0);
        const asset=await upload(canvas.toDataURL('image/png'),'smart-edit-local.png');
        return {...asset,kind:'image',natural_w:width,natural_h:height,width,height};
    }
    const api={regionsFor,compose,prepare};root.CanvasLayerEditResult=api;
    if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
