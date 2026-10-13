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
    window.CanvasTaskQuery = {query};
})();
