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
    const preparing=new WeakSet();
    root.CanvasMediaRetention={transplant};
    root.CanvasRunPreparation={
        has:node=>preparing.has(node),
        begin(node){if(preparing.has(node))return false;preparing.add(node);return true;},
        end:node=>preparing.delete(node)
    };
})(window);
