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

    function imageRequest(payload) {
        const nonce = requestId();
        return {taskId:'canvas_img_' + nonce, payload:{...payload, n:1, request_id:nonce}};
    }
    const imageUrl = taskId => '/api/canvas-image-tasks/' + encodeURIComponent(taskId);
    const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
    async function readImage(taskId, {fetcher=fetch}={}) {
        const response = await fetcher(imageUrl(taskId), {cache:'no-store'});
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.status) throw Object.assign(new Error(typeof data.detail === 'string' ? data.detail : '平台任务暂不可读'), {status:response.status});
        return data;
    }
    async function submitImage(request, {fetcher=fetch, wait=delay}={}) {
        try {
            const response = await fetcher('/api/canvas-image-tasks', {
                method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(request.payload)
            });
            const data = await response.json().catch(() => ({}));
            if (response.ok && data.task_id === request.taskId) return data;
            if (response.status >= 400 && response.status < 500 && response.status !== 408) {
                throw Object.assign(new Error(typeof data.detail === 'string' ? data.detail : '平台拒绝提交（HTTP ' + response.status + '）'), {definiteRejection:true});
            }
        } catch (error) {
            if (error.definiteRejection || error.name === 'AbortError') throw error;
        }
        // A dropped POST response can still have created a task. Only read the original ID.
        for (const pause of [0, 300, 900]) {
            if (pause) await wait(pause);
            try { return await readImage(request.taskId, {fetcher}); }
            catch (error) { if (error.name === 'AbortError') throw error; }
        }
        throw Object.assign(new Error('未收到平台回执。请先核对原任务，再决定是否重试。'), {imageTrackingUnknown:true});
    }
    function imageStatus(task) {
        if (task.submission_status === 'unknown' || task.error_code === 'PROVIDER_SUBMISSION_UNKNOWN') {
            if (task.provider_result_received) return '供应商已返回，归档结果待核对';
            if (task.upstream_task_id) return '供应商已受理，结果待核对';
            return '供应商受理结果待核对';
        }
        if (task.status === 'failed' && task.recovery_required) return '原任务结果待核对';
        if (task.status === 'failed') return '明确失败';
        if (task.status === 'cancelled') return '已取消';
        if (task.status === 'succeeded') return '已完成';
        if (task.submission_status === 'generated') return '供应商已返回，正在归档';
        if (task.status === 'jimeng_pending' || task.submission_status === 'accepted' || task.upstream_task_id) return '供应商已受理';
        return '平台任务已创建';
    }
    async function waitImage(taskId, {fetcher=fetch, wait=delay, onStatus=()=>{}}={}) {
        for (let index = 0; index < 900; index++) {
            const task = await readImage(taskId, {fetcher});
            onStatus(task);
            if (!['queued','running'].includes(task.status)) return task;
            await wait(1800);
        }
        throw new Error('平台仍在跟踪原任务，请在“生成任务”中查看。');
    }

    window.CanvasTaskQuery = {query, runVideo, waitVideo, queryVideo, requestId, imageRequest, readImage, submitImage, imageStatus, waitImage};
})();
