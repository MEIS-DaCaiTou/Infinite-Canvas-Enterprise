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
    async function videoRead(url, options, fetcher) {
        const response = await fetcher(url, options);
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.detail || '视频任务请求未完成');
        }
        return response.json();
    }
    function videoActive(isActive) {
        if (!isActive()) {
            const error = new Error('已离开原视频输出节点；原任务仍可在生成任务中查询');
            error.name = 'AbortError';
            throw error;
        }
    }
    async function waitVideo(taskId, {fetcher = fetch, wait = ms => new Promise(resolve => setTimeout(resolve, ms)), maxPolls = 1200, isActive = () => true} = {}) {
        try {
            for (let index = 0; index < maxPolls; index++) {
                videoActive(isActive);
                const task = await videoRead('/api/canvas-video-tasks/' + encodeURIComponent(taskId), {cache:'no-store'}, fetcher);
                videoActive(isActive);
                if (task.status === 'succeeded' || task.status === 'jimeng_pending') return task.result;
                if (!['queued','running'].includes(task.status)) {
                    const error = new Error(task.error || '视频状态待核对');
                    error.canReconcile = Boolean(task.can_reconcile);
                    throw error;
                }
                await wait(1500);
            }
            throw new Error('视频仍在服务器跟踪中');
        } catch (error) {
            error.canvasTaskId = taskId;
            if (error.name !== 'AbortError') error.message += `；可在“日志 → 生成任务”查看原视频任务 ${taskId}，不要重复生成。`;
            throw error;
        }
    }
    async function queryVideo(taskId, {fetcher = fetch} = {}) {
        return videoRead('/api/canvas-video-tasks/' + encodeURIComponent(taskId) + '/reconcile',
            {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'}, fetcher);
    }
    async function runVideo(payload, options = {}) {
        const {fetcher = fetch, onAccepted = async () => {}, isActive = () => true} = options;
        let taskId = '';
        try {
            // One POST per invocation. Polling and task-center recovery never submit.
            videoActive(isActive);
            const accepted = await videoRead('/api/canvas-video-tasks', {method:'POST', headers:{'Content-Type':'application/json'},
                body:JSON.stringify({...payload, request_id:payload.request_id || requestId()})}, fetcher);
            taskId = accepted.task_id;
            if (!taskId) throw new Error('视频受理回执缺少平台任务 ID');
            videoActive(isActive);
            await onAccepted(taskId);
        } catch (error) {
            error.canvasTaskId = taskId;
            if (error.name !== 'AbortError') error.message += taskId ? `；可在“日志 → 生成任务”查看原视频任务 ${taskId}，不要重复生成。` : '；请先在“日志 → 生成任务”核对是否已受理，不要自动重试。';
            throw error;
        }
        const result = await waitVideo(taskId, options);
        return result;
    }
    window.CanvasTaskQuery = {query, runVideo, waitVideo, queryVideo, requestId};
})();
