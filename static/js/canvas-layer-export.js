/* Export the layer document; task submission and credentials belong to the adapter. */
(function(root){
    const D=root.CanvasLayerDocument;
    const t=key=>root.StudioI18n.t('layers.'+key);
    let psdLibrary;
    function loadPsd(){
        if(root.agPsd)return Promise.resolve(root.agPsd);
        if(!psdLibrary)psdLibrary=new Promise((resolve,reject)=>{
            const script=document.createElement('script');
            script.src='/static/vendor/ag-psd/ag-psd-34.2.3.js';
            script.onload=()=>resolve(root.agPsd);
            script.onerror=()=>{script.remove();psdLibrary=null;reject(Error(t('psdLoadFailed')));};
            document.head.append(script);
        });
        return psdLibrary;
    }
    async function render(doc,loadImage){
        if(doc.layers.some(layer=>layer.kind==='text'))await document.fonts?.ready;
        const canvas=document.createElement('canvas');await D.paint(doc,canvas,{loadImage});return canvas;
    }
    function layerName(layer,index){return layer.name || (layer.kind==='text'?layer.text.split('\n')[0]:t('image')+' '+(index+1));}
    function fileName(name){return name.replace(/[\\/:*?"<>|\x00-\x1f]/g,'_').slice(0,120) || 'layer';}
    async function rasterLayer(doc,layer,loadImage){
        const copy=D.clone(doc),item=copy.layers.find(value=>value.id===layer.id);
        item.visible=true;item.opacity=1;
        const fragment=D.extractLayer(copy,layer.id);
        return {canvas:await render(fragment.document,loadImage),left:fragment.bounds.x,top:fragment.bounds.y};
    }
    async function zipItems(doc,{loadImage,upload}){
        const items=[];
        for(const [index,layer] of doc.layers.entries()){
            let asset=layer.asset,extension=asset?.url.split('?')[0].match(/\.[a-z0-9]+$/i)?.[0] || '.png';
            if(layer.kind!=='image'){
                const {canvas}=await rasterLayer(doc,layer,loadImage);
                asset=await upload(canvas.toDataURL('image/png'),'layer.png');extension='.png';
            }
            const name=fileName(layerName(layer,index)).replace(/\.(png|jpe?g|webp|gif|avif)$/i,'');
            items.push({url:asset.url,name:String(index+1).padStart(2,'0')+'_'+name+extension});
        }
        if(doc.annotations?.length){
            const canvas=await render({...doc,layers:[]},loadImage),asset=await upload(canvas.toDataURL('image/png'),'annotations.png');
            items.push({url:asset.url,name:String(items.length+1).padStart(2,'0')+'_'+fileName(t('annotations'))+'.png'});
        }
        return items;
    }
    async function psdDocument(doc,{loadImage}){
        const children=[];
        for(const [index,layer] of doc.layers.entries())children.push({
            ...await rasterLayer(doc,layer,loadImage),name:layerName(layer,index),opacity:layer.opacity,hidden:!layer.visible,
        });
        if(doc.annotations?.length)children.push({name:t('annotations'),left:0,top:0,canvas:await render({...doc,layers:[]},loadImage)});
        return {width:doc.width,height:doc.height,canvas:await render(doc,loadImage),children};
    }
    function download(blob,name){
        const url=URL.createObjectURL(blob),link=document.createElement('a');
        link.href=url;link.download=name;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
    }
    async function exportDocument(doc,action,options){
        let blob,name;
        if(action==='zip'){
            const items=await zipItems(doc,options);
            const response=await fetch('/api/canvas-assets/download',{method:'POST',headers:{'Content-Type':'application/json'},
                body:JSON.stringify({filename:'canvas-layers.zip',urls:items.map(item=>item.url),items,manifest:doc})});
            if(!response.ok)throw Error((await response.json()).detail || t('imageFailed'));
            blob=await response.blob();name='canvas-layers.zip';
        }else if(action==='psd'){
            const library=await loadPsd(),psd=await psdDocument(doc,options);
            blob=new Blob([library.writePsd(psd)],{type:'image/vnd.adobe.photoshop'});name='canvas-layers.psd';
        }else{
            if(action==='download-layer'){
                const layer=D.clone(doc.layers.find(value=>value.id===options.selected));
                Object.assign(layer,{x:0,y:0,rotation:0,visible:true});
                doc={width:layer.width,height:layer.height,layers:[layer]};
            }
            const canvas=await render(doc,options.loadImage);
            blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));name=action==='download-layer'?'layer.png':'composition.png';
        }
        (options.download || download)(blob,name);return blob;
    }
    const api={render,rasterLayer,zipItems,psdDocument,exportDocument,download};
    if(typeof module!=='undefined')module.exports=api;
    root.CanvasLayerExport=api;
})(typeof window!=='undefined'?window:globalThis);
