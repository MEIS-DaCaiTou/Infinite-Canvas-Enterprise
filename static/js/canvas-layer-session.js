/* One editing session per canvas node; both views share selection and history. */
(function(root){
    const D=root.CanvasLayerDocument || (typeof require==='function'?require('./canvas-layer-document.js'):null),sessions=new Map();
    let serial=0;
    class Session{
        constructor(node){
            this.node=node;this.doc=D.clone(node.layerDraft || node.layerDocument || D.fromOutputs(node.images || [],node.layerSource || {}));
            if(this.doc.version===1){if(this.doc.layers[0])this.doc.layers[0].locked=false;this.doc.version=2;}
            this.selected='';this.tool='select';this.undo=[];this.redo=[];this.penColor='#ff4757';this.penWidth=4;this.textColor='#ff3355';
            this.outputMode='fusion';this.prompt='';this.size='auto';
        }
        layer(){return this.doc.layers.find(layer=>layer.id===this.selected);}
        remember(){this.undo.push({doc:D.clone(this.doc),selected:this.selected});if(this.undo.length>40)this.undo.shift();this.redo=[];}
        history(direction){
            const source=direction<0?this.undo:this.redo,target=direction<0?this.redo:this.undo;if(!source.length)return false;
            target.push({doc:D.clone(this.doc),selected:this.selected});const entry=source.pop();this.doc=entry.doc;this.selected=entry.selected;
            this.crop=null;this.tool='select';return true;
        }
        addImage(asset,width,height,sourceNodeId=''){
            if(sourceNodeId && this.doc.layers.some(layer=>layer.sourceNodeId===sourceNodeId && layer.sourceUrl===asset.url))return null;
            const first=!this.doc.layers.length,fit=first?1:Math.min(1,this.doc.width*.65/width,this.doc.height*.65/height);
            if(first){this.doc.width=width;this.doc.height=height;}
            const layer={id:'image-'+Date.now().toString(36)+'-'+(++serial),kind:'image',name:asset.name || '',asset:{...asset,width,height},
                x:(this.doc.width-width*fit)/2,y:(this.doc.height-height*fit)/2,width:width*fit,height:height*fit,rotation:0,opacity:1,visible:true,locked:false};
            if(sourceNodeId){layer.sourceNodeId=sourceNodeId;layer.sourceUrl=asset.url;}
            this.doc.layers.push(layer);this.selected=layer.id;return layer;
        }
        startCrop(){const layer=this.layer();if(!layer || layer.kind!=='image')return;this.tool='crop';this.crop={x:0,y:0,width:layer.width,height:layer.height,ratio:0};}
        cropRatio(ratio){
            const layer=this.layer();if(!layer || !this.crop)return;
            let width=layer.width,height=layer.height;if(ratio){width=Math.min(width,height*ratio);height=width/ratio;}
            this.crop={x:(layer.width-width)/2,y:(layer.height-height)/2,width,height,ratio};
        }
        action(action,targetId=this.selected){
            const layer=this.doc.layers.find(layer=>layer.id===targetId);if(!layer)return false;
            if(action==='apply-crop' && !this.crop)return false;
            this.remember();
            if(action==='rotate90')layer.rotation=(layer.rotation+90)%360;
            if(action==='flipX' || action==='flipY')layer[action]=!layer[action];
            if(action==='visible' || action==='selected-visible')layer.visible=!layer.visible;
            if(action==='lock')layer.locked=!layer.locked;
            if(action==='up' || action==='down')D.moveLayer(this.doc,layer.id,action==='up'?1:-1);
            if(action==='front' || action==='back'){this.doc.layers=this.doc.layers.filter(l=>l!==layer);this.doc.layers[action==='front'?'push':'unshift'](layer);}
            if(action==='duplicate'){const copy=D.clone(layer);copy.id=layer.id+'-copy-'+(++serial);copy.x+=20;copy.y+=20;this.doc.layers.splice(this.doc.layers.indexOf(layer)+1,0,copy);this.selected=copy.id;}
            if(action==='fit-layer'){
                const fit=Math.min(this.doc.width/layer.width,this.doc.height/layer.height);layer.width*=fit;layer.height*=fit;
                layer.x=(this.doc.width-layer.width)/2;layer.y=(this.doc.height-layer.height)/2;if(layer.kind==='text')layer.fontSize*=fit;
            }
            if(action==='remove'){this.doc.layers=this.doc.layers.filter(l=>l!==layer);this.selected='';}
            if(action==='apply-crop'){
                const r=this.crop,c=layer.crop || {x:0,y:0,width:1,height:1},angle=layer.rotation*Math.PI/180;
                const dx=r.x+r.width/2-layer.width/2,dy=r.y+r.height/2-layer.height/2;
                layer.crop={x:c.x+(layer.flipX?layer.width-r.x-r.width:r.x)/layer.width*c.width,
                    y:c.y+(layer.flipY?layer.height-r.y-r.height:r.y)/layer.height*c.height,width:r.width/layer.width*c.width,height:r.height/layer.height*c.height};
                layer.x+=layer.width/2+dx*Math.cos(angle)-dy*Math.sin(angle)-r.width/2;
                layer.y+=layer.height/2+dx*Math.sin(angle)+dy*Math.cos(angle)-r.height/2;
                layer.width=r.width;layer.height=r.height;this.crop=null;this.tool='select';
            }
            return true;
        }
    }
    function get(node){let s=sessions.get(node.id);if(!s || s.node!==node){s=new Session(node);sessions.set(node.id,s);}return s;}
    const api={get,Session};root.CanvasLayerSession=api;if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
