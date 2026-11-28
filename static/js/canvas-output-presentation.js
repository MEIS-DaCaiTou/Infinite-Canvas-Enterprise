/* Output slots and submitted references only; no requests, task state or storage. */
(function(root){
    'use strict';
    const orderOf = (value, fallback) => Number.isInteger(value) && value >= 0 ? value : fallback;
    const taskOf = item => item?.run?.canvasTaskId || '';

    function reserve(node, tasks){
        const images = node.images || [], pending = node._pending || [];
        pending.forEach((item,index) => {
            item.outputOrder = orderOf(item.outputOrder, images.length + index);
        });
        let next = Math.max(-1, ...images.map((item,index) => orderOf(item?.run?.outputOrder,index)),
            ...pending.map(item => item.outputOrder)) + 1;
        tasks.forEach(item => {item.outputOrder = next++;});
    }
    function entries(node){
        const images = node.images || [], pending = node._pending || [];
        const byTask = new Map(pending.filter(item=>item.canvasTaskId).map(item=>[item.canvasTaskId,item]));
        const represented = new Set(images.map(taskOf).filter(Boolean));
        return [
            ...images.map((item,index) => ({item, pending:byTask.get(taskOf(item)),
                order:orderOf(item?.run?.outputOrder,index)})),
            ...pending.filter(item=>!represented.has(item.canvasTaskId)).map((item,index) => ({pending:item,
                order:orderOf(item.outputOrder,images.length + index)}))
        ].sort((left,right)=>left.order-right.order);
    }
    function model(item, pending){
        const run = item?.run || pending?.run || {};
        return String(pending?.model || run.request?.model || run.node?.apiModel || run.settings?.model ||
            run.node?.msCustomModel || run.node?.msgenModel || run.node?.model || '');
    }
    function references(item, legacy){
        const sources = [...(item?.run?.refs || []), ...(Array.isArray(legacy) ? legacy : legacy ? [legacy] : [])];
        const seen = new Set();
        return sources.map(value => typeof value === 'string' ? {url:value} : value).filter(ref=>{
            if(!ref?.url || (ref.kind && ref.kind !== 'image') || seen.has(ref.url)) return false;
            seen.add(ref.url);return true;
        }).map((ref,index)=>({url:ref.url,name:ref.name || '',index}));
    }
    function smartEntries(node){
        const items = node.images || [], tasks = (node.pendingTasks || []).filter(task=>task?.taskId);
        const represented = new Set(items.map(item=>item.canvasTaskId).filter(Boolean));
        const legacyOrders = new Set(items.filter(item=>!item.canvasTaskId).map(item=>
            orderOf(item.outputOrder,items.indexOf(item))));
        const result = items.map((item,index)=>({item,index,order:orderOf(item.outputOrder,index)}));
        tasks.filter(task=>Number.isInteger(task.imageIndex) && !represented.has(task.taskId) &&
            !legacyOrders.has(task.imageIndex)).forEach(task=>result.push({pending:task,order:task.imageIndex}));
        // Before the original task IDs are saved, retain the requested empty slots.
        const missing = Math.max(0, Number(node.pending || 0) - tasks.length);
        for(let index=0;index<missing;index++) result.push({pending:{},order:items.length+tasks.length+index});
        return result.sort((left,right)=>left.order-right.order);
    }
    const images = node => entries(node).filter(entry=>entry.item).map(entry=>entry.item);
    root.CanvasOutputPresentation = {reserve,entries,images,model,references,smartEntries};
})(window);
