/* Shared provenance and focus for the existing two canvases. No provider calls. */
(function(root){
    'use strict';
    async function source(canvas,node,save,isCurrent){
        if(!canvas?.id || !node?.id)return undefined;
        let saved;
        do {
            saved=await save();
            if(!isCurrent())throw new Error('已离开来源画布，请在当前画布重新确认运行');
            if(saved===false)throw new Error('画布保存失败，本次未提交生成任务，请保存后再试');
        }while(saved==='retry');
        return {canvas_id:canvas.id,node_id:node.id};
    }
    function focus(nodes,select,pan){
        const id=new URLSearchParams(root.location.search).get('focus_node');
        const node=nodes.find(node=>node.id===id);
        if(!node)return;
        select(node);pan(node);
    }
    root.TaskCanvasContext={source,focus};
})(window);
