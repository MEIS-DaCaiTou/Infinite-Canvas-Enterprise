(function(){
    'use strict';

    /* ---------------------------------------------------------------------
     * HistoryBulkManager
     * 历史图片批量管理：进入管理模式后可多选 / 全选 / 批量删除。
     * 5 个生成页面（在线生图 / 文生图 / 细节增强 / 图片编辑 / 角度控制）
     * 共用同一套契约：
     *   - 卡片含 [data-history-ts] 属性 与 id="history-{ts}"
     *   - 卡片 onclick 在 body.history-bulk-selecting 时提前 return
     *   - 删除走 POST /api/history/delete {timestamp}
     * 用法：window.HistoryBulkManager.attach({ masonry:'#masonry' })
     * ------------------------------------------------------------------- */

    function tr(key){
        return (window.StudioI18n && StudioI18n.t) ? StudioI18n.t(key) : key;
    }
    function fmt(key, vars){
        let s = tr(key);
        if(vars) Object.keys(vars).forEach(k => { s = s.replace('{' + k + '}', vars[k]); });
        return s;
    }

    function injectStyles(){
        if(document.getElementById('history-bulk-manager-css')) return;
        const style = document.createElement('style');
        style.id = 'history-bulk-manager-css';
        style.textContent = `
            .hbm-toolbar {
                display: flex; align-items: center; gap: 10px;
                margin-bottom: 20px; flex-wrap: wrap;
            }
            .hbm-toolbar .hbm-spacer { flex: 1; }
            .hbm-count {
                font-size: 11px; font-weight: 800; letter-spacing: .05em;
                color: #64748b; text-transform: uppercase;
            }
            .hbm-btn {
                display: inline-flex; align-items: center; gap: 6px;
                height: 36px; padding: 0 16px; border-radius: 999px;
                border: 1px solid #e2e8f0; background: #fff; color: #111827;
                font-size: 11px; font-weight: 800; letter-spacing: .04em;
                text-transform: uppercase; cursor: pointer;
                transition: all .25s cubic-bezier(.4,0,.2,1); white-space: nowrap;
            }
            .hbm-btn:hover { border-color: #111827; transform: translateY(-1px); }
            .hbm-btn:disabled { opacity: .45; cursor: not-allowed; transform: none; }
            .hbm-btn.hbm-primary { background: #111827; color: #fff; border-color: #111827; }
            .hbm-btn.hbm-danger { background: #dc2626; color: #fff; border-color: #dc2626; }
            .hbm-btn.hbm-danger:hover { background: #b91c1c; border-color: #b91c1c; }
            .hbm-hide { display: none !important; }

            /* 选择模式下的卡片浮层 */
            body.history-bulk-selecting [data-history-ts] {
                position: relative; cursor: pointer !important;
            }
            body.history-bulk-selecting [data-history-ts]::after {
                content: ''; position: absolute; top: 12px; left: 12px;
                width: 26px; height: 26px; border-radius: 50%;
                border: 2px solid #fff; background: rgba(15,23,42,.35);
                box-shadow: 0 2px 8px rgba(0,0,0,.25);
                z-index: 30; pointer-events: none;
                display: flex; align-items: center; justify-content: center;
                font-size: 14px; font-weight: 900; color: transparent;
                line-height: 1;
            }
            body.history-bulk-selecting [data-history-ts].hbm-selected::after {
                content: '\\2713'; background: #111827; border-color: #111827; color: #fff;
            }
            body.history-bulk-selecting [data-history-ts].hbm-selected {
                outline: 3px solid #111827; outline-offset: -3px;
            }

            /* 暗色主题 */
            .theme-dark .hbm-btn { background: #0f172a; color: #e2e8f0; border-color: rgba(148,163,184,.3); }
            .theme-dark .hbm-btn:hover { border-color: #e2e8f0; }
            .theme-dark .hbm-btn.hbm-primary { background: #e2e8f0; color: #0f172a; border-color: #e2e8f0; }
            .theme-dark .hbm-count { color: #94a3b8; }
            .theme-dark body.history-bulk-selecting [data-history-ts].hbm-selected,
            body.theme-dark.history-bulk-selecting [data-history-ts].hbm-selected { outline-color: #e2e8f0; }
        `;
        document.head.appendChild(style);
    }

    function attach(opts){
        opts = opts || {};
        const masonrySel = opts.masonry || '#masonry';
        const masonry = document.querySelector(masonrySel);
        if(!masonry) return null;
        if(masonry.dataset.hbmAttached === '1') return masonry._hbm || null;
        masonry.dataset.hbmAttached = '1';

        injectStyles();

        let selecting = false;
        let deleting = false;
        // Selection belongs to loaded history records, including offscreen
        // cards. Other generation pages retain their original DOM source.
        const selected = new Set();

        /* -------- 工具条 -------- */
        const bar = document.createElement('div');
        bar.className = 'hbm-toolbar';

        const manageBtn = document.createElement('button');
        manageBtn.type = 'button';
        manageBtn.className = 'hbm-btn';
        manageBtn.innerHTML = '<i data-lucide="check-square" style="width:14px;height:14px"></i><span></span>';
        const manageLabel = manageBtn.querySelector('span');

        const spacer = document.createElement('div');
        spacer.className = 'hbm-spacer';

        const countEl = document.createElement('span');
        countEl.className = 'hbm-count hbm-hide';

        const selectAllBtn = document.createElement('button');
        selectAllBtn.type = 'button';
        selectAllBtn.className = 'hbm-btn hbm-hide';

        const deleteBtn = document.createElement('button');
        deleteBtn.type = 'button';
        deleteBtn.className = 'hbm-btn hbm-danger hbm-hide';
        deleteBtn.innerHTML = '<i data-lucide="trash-2" style="width:14px;height:14px"></i><span></span>';
        const deleteLabel = deleteBtn.querySelector('span');

        const exitBtn = document.createElement('button');
        exitBtn.type = 'button';
        exitBtn.className = 'hbm-btn hbm-primary hbm-hide';

        bar.append(manageBtn, spacer, countEl, selectAllBtn, deleteBtn, exitBtn);
        masonry.parentNode.insertBefore(bar, masonry);

        function cards(){
            return Array.from(masonry.querySelectorAll('[data-history-ts]'));
        }
        function entries(){
            return opts.entries ? opts.entries() : cards().map(card=>({timestamp:card.dataset.historyTs}));
        }
        function selectedEntries(){
            return entries().filter(row=>selected.has(String(row.timestamp)));
        }

        function refreshLabels(){
            manageLabel.textContent = tr('bulk.manage');
            const all = entries();
            const sel = selectedEntries();
            cards().forEach(card=>card.classList.toggle('hbm-selected',selected.has(card.dataset.historyTs)));
            countEl.textContent = fmt('bulk.selectedCount', { n: sel.length });
            const allSelected = all.length > 0 && sel.length === all.length;
            selectAllBtn.textContent = allSelected ? tr('bulk.deselectAll') : tr('bulk.selectAll');
            deleteLabel.textContent = tr(deleting ? 'bulk.deleting' : 'bulk.deleteSelected');
            deleteBtn.disabled = deleting || sel.length === 0;
            selectAllBtn.disabled = exitBtn.disabled = deleting;
            exitBtn.textContent = tr('bulk.exit');
            if(window.lucide && lucide.createIcons) lucide.createIcons();
        }

        function enter(){
            selecting = true;
            document.body.classList.add('history-bulk-selecting');
            manageBtn.classList.add('hbm-hide');
            [countEl, selectAllBtn, deleteBtn, exitBtn].forEach(el => el.classList.remove('hbm-hide'));
            refreshLabels();
        }
        function exit(){
            selecting = false;
            selected.clear();
            document.body.classList.remove('history-bulk-selecting');
            cards().forEach(c => c.classList.remove('hbm-selected'));
            manageBtn.classList.remove('hbm-hide');
            [countEl, selectAllBtn, deleteBtn, exitBtn].forEach(el => el.classList.add('hbm-hide'));
            refreshLabels();
        }

        manageBtn.addEventListener('click', enter);
        exitBtn.addEventListener('click', exit);

        selectAllBtn.addEventListener('click', () => {
            const all = entries();
            const allSelected = all.length > 0 && selectedEntries().length === all.length;
            selected.clear();
            if(!allSelected)all.forEach(row=>selected.add(String(row.timestamp)));
            refreshLabels();
        });

        /* 选择模式下点击卡片 = 切换选中（捕获阶段拦截，避免触发卡片自身逻辑） */
        masonry.addEventListener('click', (e) => {
            if(!selecting) return;
            const card = e.target.closest('[data-history-ts]');
            if(!card || !masonry.contains(card)) return;
            e.preventDefault();
            e.stopPropagation();
            if(deleting) return;
            const key=card.dataset.historyTs;
            selected.has(key)?selected.delete(key):selected.add(key);
            refreshLabels();
        }, true);

        async function doDelete(){
            if(deleting) return;
            const sel = selectedEntries();
            if(sel.length === 0) return;
            if(!confirm(fmt('bulk.deleteConfirm', { n: sel.length }))) return;

            deleting = true;
            refreshLabels();

            let failed = 0;
            // These writes share one history document. Avoid one simultaneous
            // full-file write per selected card; retry leaves failures selected.
            for(const row of sel){
                const ts = String(row.timestamp);
                try {
                    const response=await fetch('/api/history/delete', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ timestamp: ts })
                    });
                    const res=await response.json();
                    if(response.ok && res && res.success){
                        selected.delete(ts);
                        if(opts.remove)opts.remove(ts);
                        else cards().find(card=>card.dataset.historyTs===ts)?.remove();
                        continue;
                    }
                    throw new Error('delete failed');
                } catch(_){failed++;}
            }

            deleting = false;
            if(failed > 0) alert(failed + ' / ' + sel.length + ' ✗');

            refreshLabels();
            if(selectedEntries().length === 0 && entries().length === 0){ exit(); }
        }
        deleteBtn.addEventListener('click', doDelete);

        /* 语言切换时刷新文案 */
        window.addEventListener('studio-lang-change', refreshLabels);

        refreshLabels();

        const api = { enter, exit, refresh: refreshLabels, isSelecting: () => selecting,
            isSelected: ts=>selected.has(String(ts)) };
        masonry._hbm = api;
        return api;
    }

    window.HistoryBulkManager = { attach };
})();
