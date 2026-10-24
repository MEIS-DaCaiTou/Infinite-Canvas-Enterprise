/* Activate the directory UI only after the existing controlled upgrade. */
(async () => {
    let context;
    try {
        const response = await fetch('/enterprise/api/business/workspace/context');
        if (response.ok) context = await response.json();
        else if (response.status !== 404) throw new Error('工作台暂不可用，请刷新重试');
    } catch (error) {
        document.getElementById('boardStatus').textContent = error.message;
        return;
    }
    const legacy = !context?.enabled || new URLSearchParams(location.search).get('layout') === 'board';
    if (!legacy) window.CanvasWorkspaceContext = context;
    const script = document.createElement('script');
    script.src = legacy ? '/static/js/canvas-list.js?v=2026.07.5.1783077284' : '/static/js/canvas-workspace.js?v=20261024.1';
    if (legacy && new URLSearchParams(location.search).get('trash') === '1') {
        script.onload = () => window.openTrashView?.();
    }
    document.body.append(script);
    if (legacy && context?.enabled) {
        const back = document.createElement('a');
        back.href = '/static/canvas-list.html'; back.className = 'ws-primary-btn'; back.textContent = '返回项目目录';
        document.querySelector('.ws-topbar-right').prepend(back);
    }
})();
