/* Shared by both canvases. Bound receipts use the local task ID; legacy
   records retain the existing explicit query path. Neither path generates. */
(function () {
    async function query({canvasTaskId, canReconcile, providerId, upstreamTaskId}) {
        const bound = Boolean(canvasTaskId && canReconcile);
        const response = await fetch(bound
            ? `/api/canvas-image-tasks/${encodeURIComponent(canvasTaskId)}/reconcile`
            : '/api/image-task-query', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(bound ? {} : {provider_id: providerId || 'comfly', task_id: upstreamTaskId})
        });
        if (!response.ok) {
            const text = await response.text();
            let detail = text;
            try { detail = JSON.parse(text).detail || text; } catch (_) {}
            throw new Error(detail || '查询失败');
        }
        return response.json();
    }
    function requestId() {
        const bytes = new Uint8Array(16);
        crypto.getRandomValues(bytes);
        bytes[6] = (bytes[6] & 15) | 64;
        bytes[8] = (bytes[8] & 63) | 128;
        return Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
    }
    async function runVideo(payload, {fetcher = fetch, wait = ms => new Promise(resolve => setTimeout(resolve, ms)), maxPolls = 1200} = {}) {
        const id = payload.request_id || requestId();
        let taskId = '';
        async function read(url, options) {
            const response = await fetcher(url, options);
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.detail || '视频任务请求未完成');
            }
            return response.json();
        }
        try {
            // One POST per invocation. Polling and task-center recovery never submit.
            const accepted = await read('/api/canvas-video-tasks', {method:'POST', headers:{'Content-Type':'application/json'},
                body:JSON.stringify({...payload, request_id:id})});
            taskId = accepted.task_id;
            if (!taskId) throw new Error('视频受理回执缺少平台任务 ID');
            for (let index = 0; index < maxPolls; index++) {
                const task = await read('/api/canvas-video-tasks/' + encodeURIComponent(taskId), {cache:'no-store'});
                if (task.status === 'succeeded' || task.status === 'jimeng_pending') return task.result;
                if (!['queued','running'].includes(task.status)) throw new Error(task.error || '视频状态待核对');
                await wait(1500);
            }
            throw new Error('视频仍在服务器跟踪中');
        } catch (error) {
            if (error.name === 'AbortError') throw error;
            error.message += taskId ? `；可在“日志 → 生成任务”查看原视频任务 ${taskId}，不要重复生成。` : '；请先在“日志 → 生成任务”核对是否已受理，不要自动重试。';
            throw error;
        }
    }
    window.CanvasTaskQuery = {query, runVideo, requestId};
})();
