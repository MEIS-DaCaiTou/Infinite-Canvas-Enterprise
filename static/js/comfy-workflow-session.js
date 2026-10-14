/* One test session, rendered by both workflow settings views. */
(function(root){
    'use strict';
    class ComfyWorkflowSession {
        constructor(fields=[]){
            this.values = Object.fromEntries(fields.map(f => [f.id, f.default ?? '']));
            this.urls = {};
            this.uploads = new Map();
            this.revision = 0;
            this.result = null;
            this.resultRevision = -1;
            this.running = false;
            this.taskId = '';
            this.phase = '';
            this.error = '';
        }
        set(id, value){ this.values[id] = value; this.revision++; }
        async upload(id, file, uploader, changed=()=>{}){
            const token = {};
            this.uploads.set(id, token);
            this.set(id, ''); // Never silently submit an earlier file after a failed replacement.
            this.error = '';
            changed();
            try {
                const uploaded = await uploader(file);
                if(this.uploads.get(id) !== token) return;
                if(!uploaded?.comfy_name) throw new Error('ComfyUI 未返回上传文件名');
                this.set(id, uploaded.comfy_name);
            } catch(error){
                if(this.uploads.get(id) === token) this.error = error.message;
            } finally {
                if(this.uploads.get(id) === token) this.uploads.delete(id);
                changed();
            }
        }
        async execute(submit, poll, changed=()=>{}){
            if(this.running || this.uploads.size) return;
            this.running = true;
            this.error = '';
            this.phase = 'submitting';
            const snapshot = structuredClone(this.values);
            const revision = this.revision;
            changed();
            try {
                const receipt = await submit(snapshot);
                if(!receipt.task_id) throw new Error('平台未返回任务身份，请先核对任务记录');
                this.taskId = receipt.task_id;
                changed();
                await this.follow(poll, changed, revision);
            } catch(error){
                this.error = error.message;
                // Retain taskId: the next click queries it instead of submitting again.
            } finally { this.running = false; changed(); }
        }
        async follow(poll, changed=()=>{}, revision=-1){
            const task = await poll(this.taskId, phase => { this.phase = phase; changed(); });
            if(task.status !== 'succeeded'){
                if(!task.recovery_required) this.taskId = '';
                throw new Error(task.error || 'ComfyUI 任务尚未完成');
            }
            this.result = task.result;
            this.resultRevision = revision;
            this.taskId = '';
            this.phase = 'succeeded';
        }
    }
    function resultItems(result){
        if(Array.isArray(result?.items) && result.items.length) return result.items;
        return ['images','videos','audios','texts','files'].flatMap((key,i) => (result?.[key] || []).map(url => ({url,kind:['image','video','audio','text','file'][i]})));
    }
    root.ComfyWorkflowSession = ComfyWorkflowSession;
    root.ComfyWorkflowResultItems = resultItems;
})(typeof window === 'undefined' ? globalThis : window);
