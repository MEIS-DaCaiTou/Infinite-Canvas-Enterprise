/* Durable text lifecycle shared by both existing canvases. One submit, GET-only resume. */
(function(root){
    'use strict';
    const pending=task=>task?.id && ['pending','queued','running'].includes(task.state);
    async function run(payload,{task,prepare,onState,onResult,isCurrent=()=>true,fetcher=fetch,
        wait=ms=>new Promise(resolve=>setTimeout(resolve,ms)),maxPolls=1200}={}){
        let id=task?.id || '';
        const check=()=>{
            if(!isCurrent()){const error=new Error('已离开原画布，文本任务仍在服务器保留');error.name='AbortError';throw error;}
        };
        const read=async(url,options)=>{
            const response=await fetcher(url,{cache:'no-store',...options});
            if(!response.ok){
                const data=await response.json().catch(()=>({}));
                if(response.status===404 && id)onState({id,state:'unknown',error:'未确认原任务受理，请先核对；再次运行会新建任务，可能重复费用'});
                throw new Error(data.detail || '文本任务暂不可读，请保留原任务');
            }
            return response.json();
        };
        try {
            check();
            if(!id){
                const requestId=root.CanvasTaskQuery.requestId();
                id='canvas_llm_'+requestId;
                onState({id,state:'pending'});
                let source;
                try {source=await prepare(id);check();}
                catch(error){onState(null);throw error;}
                // The ticket was saved before dispatch. Lost acceptance never causes another POST.
                await read('/api/canvas-llm-tasks',{method:'POST',headers:{'Content-Type':'application/json'},
                    body:JSON.stringify({...payload,request_id:requestId,source})});
            }
            for(let index=0;index<maxPolls;index++){
                check();
                const record=await read('/api/canvas-llm-tasks/'+encodeURIComponent(id));
                check();
                const state=record.recovery_required?'unknown':record.status;
                onState({id,state,error:record.error || ''});
                if(record.status==='succeeded'){
                    await onResult(record.result, id);return record.result;
                }
                if(!['queued','running'].includes(record.status))throw new Error(record.error || '文本结果待核对');
                await wait(1500);
            }
            throw new Error('文本任务仍在服务器执行');
        }catch(error){
            if(error.name!=='AbortError')error.message+='；请在“日志 → 生成任务 → LLM 文本”查看原任务'+(id?' '+id:'')+'，查询不会重新生成。';
            throw error;
        }
    }
    const label=(task,idle)=>pending(task)?'查询原任务':task?.state==='unknown'?'新建运行':idle;
    const hint=task=>task?.state==='unknown'?'请先核对原任务；新建运行会再次调用模型，可能产生重复费用':'';
    root.CanvasLLMTasks={run,pending,label,hint};
})(window);
