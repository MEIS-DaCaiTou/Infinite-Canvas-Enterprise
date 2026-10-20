/* A media element belongs to its node/result slot, never a global URL cache. */
(function(root){
    'use strict';
    function slots(node){
        const occurrences=new Map(),result=new Map();
        node?.querySelectorAll('video[data-url],audio[data-url],img[data-preview-kind="video"]').forEach(media=>{
            const card=media.closest('[data-output-url]');
            const kind=media.tagName.toLowerCase()==='audio'?'audio':'video';
            const url=media.dataset.url || media.dataset.originalSrc || '';
            const identity=card?.dataset.resultId || card?.dataset.outputUrl || '';
            const base=JSON.stringify([identity,kind,url]);
            const index=occurrences.get(base) || 0;occurrences.set(base,index+1);
            result.set(JSON.stringify([base,index]),media);
        });
        return result;
    }
    function transplant(oldNode,newNode,capture,restore){
        if(oldNode?.dataset.canvasId!==newNode?.dataset.canvasId)return;
        const previous=slots(oldNode);
        for(const [key,target] of slots(newNode)){
            const media=previous.get(key);
            if(!media || !['VIDEO','AUDIO'].includes(media.tagName))continue;
            // Both roots are attached before moving. Current Edge can move
            // atomically; older engines retain the existing playback fallback.
            const parent=target.parentElement;
            if(parent.moveBefore && media.isConnected && target.isConnected){
                parent.moveBefore(media,target);target.remove();
            }else{
                const state=capture(media);target.replaceWith(media);restore(media,state);
            }
            media.onclick=target.tagName===media.tagName?target.onclick:null;
            if(media.controls)parent.querySelector('.canvas-video-play')?.style.setProperty('display','none');
        }
    }
    const preparing=new Map();
    root.CanvasMediaRetention={transplant};
    root.CanvasRunPreparation={
        has:(node,canvasId)=>preparing.get(canvasId)?.has(node?.id) || false,
        active:canvasId=>Boolean(preparing.get(canvasId)?.size),
        begin(node,canvasId){
            if(!node?.id || !canvasId || this.has(node,canvasId))return false;
            if(!preparing.has(canvasId))preparing.set(canvasId,new Set());
            preparing.get(canvasId).add(node.id);return true;
        },
        end(node,canvasId){
            const ids=preparing.get(canvasId);ids?.delete(node?.id);
            if(!ids?.size)preparing.delete(canvasId);
        }
    };
})(window);
