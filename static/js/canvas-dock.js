/* Additional shortcuts; the original top toolbar owns the existing panels. */
(function () {
    function dockPlacement(viewport, dockHeight, account) {
        const base = 12, gap = 10, center = viewport.width / 2;
        let maxWidth = Math.max(0, viewport.width - 24), bottom = base;
        if (account && account.top < viewport.height - base && account.bottom > viewport.height - base - dockHeight) {
            const room = account.left >= center ? (account.left - gap - center) * 2 :
                account.right <= center ? (center - gap - account.right) * 2 : 0;
            if (room >= 220) maxWidth = Math.min(maxWidth, room);
            else bottom = Math.max(base, viewport.height - account.top + gap);
        }
        return {bottom, maxWidth};
    }
    if (typeof module !== 'undefined' && module.exports) module.exports = {dockPlacement};
    if (typeof document === 'undefined') return;
    const dock = document.getElementById('canvasDock');
    if (!dock) return;
    const add = dock.querySelector('.dock-add'), menu = document.getElementById('canvasAddMenu');
    const actions = dock.querySelector('.dock-actions'), more = dock.querySelector('.dock-scroll');
    const shell = document.getElementById('shell'), map = document.getElementById('minimap');
    // The dock is canvas UI, never a pan/selection/zoom gesture or a node hotkey.
    for (const event of ['pointerdown','mousedown','click','dblclick','wheel','keydown']) {
        dock.addEventListener(event, e => {
            // Existing panel Escape handlers remain responsible for dismissal.
            if (event === 'keydown' && e.key === 'Escape') return;
            e.stopPropagation();
        });
    }
    document.documentElement.classList.toggle('canvas-embedded', window.parent !== window);
    function accountRectangle() {
        try {
            const bar = window.parent.document.getElementById('__ent_bar__');
            if (!bar) return null;
            const box = bar.getBoundingClientRect();
            if (!box.width || !box.height) return null;
            if (window.parent === window) return box;
            const frame = window.frameElement.getBoundingClientRect();
            const sx = frame.width / innerWidth, sy = frame.height / innerHeight;
            return {left:(box.left-frame.left)/sx, right:(box.right-frame.left)/sx,
                top:(box.top-frame.top)/sy, bottom:(box.bottom-frame.top)/sy};
        } catch (_) { return null; }
    }

    const hideMenu = () => window.StudioDropdowns.closePanel(menu);
    add.addEventListener('click', () => {
        hideTooltip();
        if (menu.matches(':popover-open')) { hideMenu(); return; }
        window.StudioDropdowns.openPanel(menu, add, () => add.setAttribute('aria-expanded', 'false'));
        menu.querySelector('button')?.focus({preventScroll:true});
    });
    menu.addEventListener('click', event => {
        if (event.target.closest('button')) { hideMenu(); add.focus({preventScroll:true}); }
    });
    menu.addEventListener('keydown', event => {
        if (event.key === 'Escape') {
            event.preventDefault(); event.stopPropagation(); hideMenu(); add.focus({preventScroll:true});
        }
    });
    dock.querySelectorAll('[data-dock-target]').forEach(button => {
        const target = document.getElementById(button.dataset.dockTarget);
        const panel = document.getElementById(button.getAttribute('aria-controls'));
        if (!target || !panel) { button.disabled = true; return; }
        button.addEventListener('click', () => { hideMenu(); hideTooltip(); target.click(); });
        const sync = () => button.setAttribute('aria-expanded', String(panel.classList.contains('open')));
        new MutationObserver(sync).observe(panel, {attributes:true, attributeFilter:['class']});
        sync();
    });
    dock.addEventListener('keydown', event => {
        if (menu.contains(event.target) || !['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
        const buttons = [...dock.querySelectorAll('.dock-button')].filter(button => !button.hidden);
        const index = buttons.indexOf(document.activeElement);
        if (index < 0) return;
        event.preventDefault(); event.stopPropagation();
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 :
            (index + (event.key === 'ArrowLeft' ? -1 : 1) + buttons.length) % buttons.length;
        buttons[next].focus({preventScroll:true});
        if (actions.contains(buttons[next])) buttons[next].scrollIntoView({block:'nearest', inline:'nearest'});
    });
    function updateOverflow() {
        more.hidden = actions.scrollWidth <= actions.clientWidth + 1;
        const atEnd = actions.scrollLeft + actions.clientWidth >= actions.scrollWidth - 2;
        more.dataset.back = String(atEnd);
        more.setAttribute('aria-label', atEnd ? '前面的工具' : '更多工具');
    }
    more.addEventListener('click', () => {
        const direction = more.dataset.back === 'true' ? -1 : 1;
        actions.scrollBy({left:direction * actions.clientWidth * .75,
            behavior:matchMedia('(prefers-reduced-motion:reduce)').matches ? 'instant' : 'smooth'});
    });
    actions.addEventListener('scroll', updateOverflow);
    actions.addEventListener('wheel', event => {
        if (actions.scrollWidth > actions.clientWidth && Math.abs(event.deltaY) > Math.abs(event.deltaX)) {
            event.preventDefault(); actions.scrollLeft += event.deltaY;
        }
    }, {passive:false});
    let pendingLayout = false;
    function scheduleLayout() {
        if (pendingLayout) return;
        pendingLayout = true;
        requestAnimationFrame(() => {
            pendingLayout = false;
            const placement = dockPlacement({width:innerWidth, height:innerHeight}, dock.getBoundingClientRect().height, accountRectangle());
            dock.style.setProperty('--canvas-dock-bottom', placement.bottom + 'px');
            dock.style.setProperty('--canvas-dock-max-width', placement.maxWidth + 'px');
            updateOverflow();
            if (!map) return;
            const box = dock.getBoundingClientRect(), mapWidth = map.getBoundingClientRect().width;
            // Reserve a separate row only when the centered dock meets the right corner.
            const mapLeft = innerWidth - 22 - mapWidth;
            shell.classList.toggle('dock-map-stacked', box.right + 12 > mapLeft && box.left < innerWidth - 22);
            shell.style.setProperty('--canvas-dock-map-bottom', (innerHeight - box.top + 12) + 'px');
            hideTooltip(); hideMenu();
        });
    }
    new ResizeObserver(scheduleLayout).observe(shell);
    new ResizeObserver(scheduleLayout).observe(dock);
    window.addEventListener('studio-ui-scale-change', scheduleLayout);
    window.addEventListener('focus', scheduleLayout);
    try {
        const bar = window.parent.document.getElementById('__ent_bar__');
        if (bar) new ResizeObserver(scheduleLayout).observe(bar);
    } catch (_) { /* Standalone/cross-origin pages keep the default bottom inset. */ }

    const tooltip = document.createElement('div');
    tooltip.id = 'canvasDockTooltip'; tooltip.className = 'canvas-dock-tooltip';
    tooltip.setAttribute('role','tooltip'); tooltip.setAttribute('popover','manual');
    document.body.append(tooltip);
    let tooltipTimer, tooltipButton;
    function hideTooltip() {
        clearTimeout(tooltipTimer);
        tooltipButton?.removeAttribute('aria-describedby'); tooltipButton = null;
        if (tooltip.matches(':popover-open')) tooltip.hidePopover();
    }
    function showTooltip(button, delay) {
        hideTooltip();
        if (menu.matches(':popover-open')) return;
        tooltipTimer = setTimeout(() => {
            tooltip.textContent = button.getAttribute('aria-label');
            tooltipButton = button; button.setAttribute('aria-describedby', tooltip.id);
            tooltip.showPopover();
            const box = button.getBoundingClientRect(), size = tooltip.getBoundingClientRect();
            tooltip.style.left = Math.max(8, Math.min(innerWidth - size.width - 8, box.left + (box.width - size.width) / 2)) + 'px';
            tooltip.style.top = Math.max(8, box.top - size.height - 10) + 'px';
        }, delay);
    }
    dock.querySelectorAll('.dock-button').forEach(button => {
        button.removeAttribute('title');
        button.addEventListener('pointerenter', () => showTooltip(button, 180));
        button.addEventListener('pointerleave', hideTooltip);
        button.addEventListener('focus', () => showTooltip(button, 0));
        button.addEventListener('blur', hideTooltip);
        button.addEventListener('pointerdown', hideTooltip);
    });
    document.addEventListener('keydown', event => { if(event.key === 'Escape') hideTooltip(); }, true);
    window.addEventListener('blur', hideTooltip);
    scheduleLayout();
})();
