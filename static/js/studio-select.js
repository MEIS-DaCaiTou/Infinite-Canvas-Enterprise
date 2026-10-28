/* Shared select presentation. Native values, forms and change handlers remain authoritative. */
(function () {
    function placeMenu(rect, size, viewport) {
        const edge = 8, gap = 6;
        const width = Math.min(size.width, viewport.width - edge * 2);
        const below = Math.max(0, viewport.height - rect.bottom - gap - edge);
        const above = Math.max(0, rect.top - gap - edge);
        const upwards = below < size.height && above > below;
        const height = Math.min(size.height, upwards ? above : below);
        return {left: Math.max(edge, Math.min(rect.left, viewport.width - width - edge)),
            top: upwards ? rect.top - gap - height : rect.bottom + gap, width, height};
    }
    if (typeof module !== 'undefined' && module.exports) module.exports = {placeMenu};
    if (typeof document === 'undefined') return;

    let current = null, panelState = null;
    const text = (zh, en) => document.documentElement.lang.startsWith('en') ? en : zh;
    const eligible = select => select instanceof HTMLSelectElement && !select.disabled &&
        !select.hidden && !select.multiple && select.size <= 1;
    const transientMenus = () => document.querySelectorAll('details[data-studio-menu][open]');
    function dismissDetails(target) {
        transientMenus().forEach(details => { if (!details.contains(target)) details.open = false; });
    }
    function close(restoreFocus = false) {
        if (!current) return;
        const {select, menu} = current;
        current = null;
        select.removeAttribute('aria-expanded');
        select.removeAttribute('aria-controls');
        menu.remove();
        if (restoreFocus && select.isConnected) select.focus({preventScroll: true});
    }
    function closePanel(panel) {
        if (!panelState || panel && panelState.panel !== panel) return;
        const previous = panelState; panelState = null;
        if (previous.panel.matches(':popover-open')) previous.panel.hidePopover();
        previous.anchor.setAttribute('aria-expanded', 'false');
        previous.onClose?.();
    }
    function openPanel(panel, anchor, onClose) {
        close();
        if (panelState?.panel !== panel) closePanel();
        panel.setAttribute('popover', 'manual'); panel.classList.add('studio-dropdown-panel');
        panel.style.width = ''; panel.style.maxHeight = Math.min(480, innerHeight - 16) + 'px';
        panel.style.maxWidth = Math.min(420, document.documentElement.clientWidth - 16) + 'px';
        if (!panel.matches(':popover-open')) panel.showPopover();
        const box = panel.getBoundingClientRect();
        const position = placeMenu(anchor.getBoundingClientRect(), box,
            {width:document.documentElement.clientWidth,height:innerHeight});
        panel.style.setProperty('left', position.left + 'px', 'important');
        panel.style.setProperty('top', position.top + 'px', 'important');
        panel.style.width = position.width + 'px'; panel.style.maxHeight = position.height + 'px';
        anchor.setAttribute('aria-expanded', 'true');
        panelState = {panel, anchor, onClose};
    }
    window.StudioDropdowns = {openPanel, closePanel};
    function choices() {
        return current ? [...current.menu.querySelectorAll('[role=option]:not(:disabled)')] : [];
    }
    function focusChoice(index) {
        const list = choices();
        if (!list.length) return;
        const item = list[(index + list.length) % list.length];
        item.focus({preventScroll: true});
        item.scrollIntoView({block: 'nearest'});
    }
    function commit(index) {
        if (!current) return;
        const select = current.select, option = current.optionNodes[index];
        if (!select.isConnected || select.disabled || !option || option.closest('select') !== select) { close(true); return; }
        if (option.disabled || option.parentElement.disabled) return;
        const changed = select.selectedIndex !== option.index;
        select.selectedIndex = option.index;
        close(true);
        if (changed) {
            select.dispatchEvent(new Event('input', {bubbles: true}));
            select.dispatchEvent(new Event('change', {bubbles: true}));
        }
    }
    function renderOptions(query = '') {
        const {select, list} = current;
        list.replaceChildren();
        let group = null, count = 0;
        current.optionNodes = [...select.options];
        current.optionNodes.forEach((option, index) => {
            if (option.hidden || !option.textContent.toLocaleLowerCase().includes(query.toLocaleLowerCase())) return;
            const parent = option.parentElement;
            if (parent.tagName === 'OPTGROUP' && parent !== group) {
                const heading = document.createElement('div');
                heading.className = 'studio-select-group'; heading.textContent = parent.label;
                list.append(heading); group = parent;
            }
            const button = document.createElement('button');
            button.type = 'button'; button.tabIndex = -1; button.setAttribute('role', 'option');
            button.setAttribute('aria-selected', String(option.selected));
            button.dataset.optionIndex = String(index);
            button.disabled = option.disabled || Boolean(parent.disabled);
            const label = document.createElement('span'); label.textContent = option.textContent;
            const mark = document.createElement('span'); mark.className = 'studio-select-check';
            mark.setAttribute('aria-hidden', 'true'); mark.textContent = option.selected ? '✓' : '';
            button.append(label, mark); list.append(button); count++;
        });
        if (!count) { const empty = document.createElement('p'); empty.className = 'studio-select-empty'; empty.textContent = text('没有匹配选项','No matching options'); list.append(empty); }
    }
    function open(select) {
        if (current?.select === select) { close(true); return; }
        close(); dismissDetails(select);
        if (panelState && !panelState.panel.contains(select)) closePanel();
        const menu = document.createElement('div');
        menu.className = 'studio-select-menu'; menu.setAttribute('popover', 'manual');
        menu.id = 'studio-select-popup';
        const nativeLabel = select.labels?.[0];
        const label = select.getAttribute('aria-label') || (nativeLabel && [...nativeLabel.childNodes].filter(node => node.nodeType === 3).map(node => node.textContent).join('').trim()) || select.title || text('选择选项','Choose an option');
        const list = document.createElement('div'); list.className = 'studio-select-options';
        list.setAttribute('role', 'listbox'); list.setAttribute('aria-label', label);
        const search = document.createElement('input');
        if (select.options.length > 10) {
            search.type = 'search'; search.placeholder = text('搜索选项…','Search options…'); search.setAttribute('aria-label', text('搜索选项','Search options'));
            search.className = 'studio-select-search';
            search.oninput = () => renderOptions(search.value.trim()); menu.append(search);
        }
        menu.append(list);
        (select.closest('dialog[open], [popover]:popover-open') || document.body).append(menu);
        current = {select, menu, list, search, typeText: '', typeTime: 0};
        renderOptions();
        const rect = select.getBoundingClientRect();
        const viewport = {width: document.documentElement.clientWidth, height: innerHeight};
        menu.style.minWidth = Math.min(rect.width, viewport.width - 16) + 'px';
        menu.style.maxWidth = Math.min(420, viewport.width - 16) + 'px';
        menu.showPopover();
        const natural = menu.getBoundingClientRect();
        const position = placeMenu(rect, {width: natural.width, height: Math.min(natural.height, 340)}, viewport);
        Object.assign(menu.style, {left: position.left + 'px', top: position.top + 'px',
            width: position.width + 'px', maxHeight: position.height + 'px'});
        select.setAttribute('aria-expanded', 'true'); select.setAttribute('aria-controls', menu.id);
        menu.onclick = event => {
            const option = event.target.closest('[data-option-index]');
            if (option && !option.disabled) commit(Number(option.dataset.optionIndex));
        };
        if (search.isConnected) search.focus({preventScroll: true});
        else {
            const list = choices(), selected = list.findIndex(button => button.getAttribute('aria-selected') === 'true');
            focusChoice(Math.max(0, selected));
        }
    }
    document.addEventListener('pointerdown', event => {
        const select = event.target.closest('select');
        if (eligible(select) && event.button === 0) {
            event.preventDefault(); event.stopPropagation(); select.focus({preventScroll: true}); open(select); return;
        }
        if (current && !current.menu.contains(event.target)) close();
        if (panelState && !panelState.panel.contains(event.target) && !panelState.anchor.contains(event.target)) closePanel();
        dismissDetails(event.target);
    }, true);
    document.addEventListener('click', event => {
        if (eligible(event.target.closest('select'))) { event.preventDefault(); event.stopPropagation(); }
        const summary = event.target.closest('summary');
        if (summary?.parentElement.matches('details[data-studio-menu]')) dismissDetails(summary);
    }, true);
    document.addEventListener('keydown', event => {
        if (!current) {
            if (eligible(event.target) && ['ArrowDown','ArrowUp','Enter',' '].includes(event.key)) {
                event.preventDefault(); event.stopPropagation(); open(event.target);
            }
            return;
        }
        if (!current.menu.contains(event.target) && event.target !== current.select) return;
        if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(true); return; }
        if (event.key === 'Tab') { close(true); return; }
        const list = choices(), index = list.indexOf(document.activeElement);
        if (['ArrowDown','ArrowUp','Home','End'].includes(event.key)) {
            event.preventDefault(); event.stopPropagation();
            focusChoice(event.key === 'Home' ? 0 : event.key === 'End' ? list.length - 1 :
                index + (event.key === 'ArrowUp' ? -1 : 1));
        } else if (event.key === 'Enter' || event.key === ' ' && event.target !== current.search) {
            event.preventDefault(); event.stopPropagation();
            if (index >= 0) commit(Number(list[index].dataset.optionIndex));
            else if (list.length === 1) commit(Number(list[0].dataset.optionIndex));
        } else if (event.target !== current.search && event.key.length === 1 && !event.ctrlKey && !event.metaKey) {
            event.preventDefault();
            const now = Date.now(); current.typeText = (now - current.typeTime < 700 ? current.typeText : '') + event.key.toLocaleLowerCase();
            current.typeTime = now;
            const match = list.findIndex(button => button.textContent.toLocaleLowerCase().startsWith(current.typeText));
            if (match >= 0) focusChoice(match);
        }
    }, true);
    document.addEventListener('scroll', event => {
        if (current && !current.menu.contains(event.target)) close();
        if (panelState && !panelState.panel.contains(event.target)) closePanel();
    }, true);
    window.addEventListener('resize', () => { close(); closePanel(); });
    window.addEventListener('blur', () => { close(); closePanel(); });
    document.addEventListener('submit', () => close(), true);
})();
