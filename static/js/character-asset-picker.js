/* Read-only image selection over existing, permission-filtered asset services.
 * This view owns temporary selection only; the caller owns import/save actions. */
(function () {
  const node = (tag, cls, text) => {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text !== undefined) el.textContent = text;
    return el;
  };
  function urlKey(value) {
    if (typeof value !== 'string' || !value.trim()) return '';
    try {
      const url = new URL(value, location.origin);
      if (!['http:', 'https:'].includes(url.protocol)) return '';
      return url.origin === location.origin ? url.pathname : url.href;
    } catch { return ''; }
  }
  function previewUrl(value) {
    const preview=window.canvasMediaPreviewUrl || window.smartMediaPreviewUrl;
    if(typeof preview!=='function')return value;
    try{const url=new URL(value,location.origin);return url.origin===location.origin?preview(url.pathname+url.search,320):value;}catch{return value;}
  }
  function context(index = {}) {
    const canvases = new Map((index.canvases || []).map(row => [row.id, row.project]));
    const urls = new Map();
    for (const item of index.items || []) {
      const key = urlKey(item.url), project = canvases.get(item.canvas_id);
      if (!key || !project) continue;
      if (!urls.has(key)) urls.set(key, new Set());
      urls.get(key).add(project);
    }
    return {canvases, urls, items: index.items || []};
  }
  function images(source, data, ctx) {
    const values = [];
    const add = (item, parent = {}) => {
      if (typeof item === 'string') item = {url: item};
      if (!item || typeof item.url !== 'string') return;
      const key = urlKey(item.url);
      if (!key || !(item.kind === 'image' || /\.(png|jpe?g|webp|gif|avif)(?:[?#]|$)/i.test(item.url))) return;
      const projects = new Set(ctx.urls.get(key) || []);
      for (const row of [parent, item]) {
        const project = row.project_id || row.project || ctx.canvases.get(row.canvas_id || row.source?.canvas_id);
        if (typeof project === 'string' && project) projects.add(project);
      }
      const rawTime = item.created_at || parent.timestamp || parent.created_at || 0;
      let created = Number(rawTime);
      if (!Number.isFinite(created)) created = Date.parse(rawTime) || 0;
      if (created && created < 1e11) created *= 1000;
      values.push({url: item.url, key, projects, created,
        name: String(item.name || parent.prompt || parent.node_title || '图片').slice(0, 120)});
    };
    if (source === 'generated') {
      for (const row of Array.isArray(data) ? data : [])
        for (const item of row.images || []) add(item, row);
      // Canvas results also include workflow outputs absent from online history.
      for (const item of ctx.items)
        if (/^\/(assets\/output|output)\//.test(urlKey(item.url))) add(item);
    } else if (source === 'saved') {
      const root = data?.library || data || {};
      const libraries = root.libraries || [{categories: root.categories || []}];
      for (const library of libraries)
        for (const category of library.categories || [])
          for (const item of category.items || []) add(item);
    } else {
      for (const item of data?.items || []) add(item);
      for (const item of ctx.items)
        if (/^\/assets\/(input|uploads)\//.test(urlKey(item.url))) add(item);
    }
    const unique = new Map();
    for (const item of values) {
      const previous = unique.get(item.key);
      if (previous) for (const project of item.projects) previous.projects.add(project);
      else unique.set(item.key, item);
    }
    return [...unique.values()];
  }
  class CharacterAssetPicker {
    constructor({request, projectId, canvasId, cancelLabel = '返回角色库', onCancel, onConfirm}) {
      Object.assign(this, {request, projectId, canvasId, cancelLabel, onCancel, onConfirm});
      this.root = node('section', 'character-asset-picker');
      this.root.setAttribute('aria-label', '资产库');
      this.source = 'generated';
      this.scope = projectId ? 'project' : 'all';
      this.rows = [];
      this.newest = true;
      this.version = 0;
      this.limit = 24;
      this.cursor = null;
      this.render();
    }
    async load(append = false) {
      if (append && (this.loading || !this.cursor)) return;
      const version = ++this.version;
      this.loading = true;
      this.error = '';
      this.needsRefresh = false;
      if (!append) { this.resetGridScroll = true; this.selected = null; this.rows = []; this.cursor = null; this.limit = 24; }
      this.render();
      try {
        const source = this.source;
        const params = new URLSearchParams({page_size:'24',sort:this.newest?'newest':'oldest'});
        if (source !== 'generated') params.set('kind','image');
        if (append) params.set('cursor',this.cursor);
        const endpoint = {generated:'/api/history',saved:'/api/asset-library',uploaded:'/api/local-assets'}[source];
        const data = await this.request(endpoint+'?'+params);
        if (this.destroyed || version !== this.version) return;
        let normalized = data;
        let nextCursor = null;
        if (Array.isArray(data.items) && Number.isFinite(data.total)) {
          if (!Number.isFinite(data.total) || data.next_cursor!==null && typeof data.next_cursor!=='string') throw Error('资产返回格式异常，请重试');
          nextCursor = data.next_cursor;
          normalized = source==='generated'?data.items:source==='saved'?{library:{categories:[{items:data.items}]}}:data;
        } else {
          const valid = source==='generated'?Array.isArray(data):source==='saved'?
            Array.isArray(data.library?.libraries) || Array.isArray(data.library?.categories):Array.isArray(data.items);
          if (!valid) throw Error('资产返回格式异常，请重试');
        }
        const candidates = images(source, normalized, context());
        const ctx = await this.readContext(candidates.map(row=>row.url));
        if (this.destroyed || version !== this.version) return;
        if (!this.projectId && ctx.canvases.get(this.canvasId)) {
          this.projectId = ctx.canvases.get(this.canvasId);
          if (!this.scopeTouched) this.scope = 'project';
        }
        const next = images(source, normalized, ctx);
        const merged = new Map((append?this.rows:[]).map(row=>[row.key,row]));
        for (const row of next) merged.set(row.key,row);
        this.rows = [...merged.values()];
        this.cursor = nextCursor;
        if (append) this.limit += 24;
      } catch (error) {
        if (this.destroyed || version !== this.version) return;
        this.error = error.message || '资产加载失败，请重试';
        this.needsRefresh = error.status===409;
        if ([401,403].includes(error.status)) { this.rows=[]; this.selected=null; this.cursor=null; }
      }
      if (this.destroyed || version !== this.version) return;
      this.loading = false;
      this.render();
    }
    async readContext(urls) {
      const combined = {canvases:[],items:[]};
      try {
        for (let offset=0;offset<Math.max(1,urls.length);offset+=100) {
          const data = await this.request('/api/canvas-assets/context', {method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({urls:urls.slice(offset,offset+100),canvas_id:this.canvasId || ''})});
          if (!Array.isArray(data.canvases) || !Array.isArray(data.items)) throw Error('画布关联返回格式异常，请重试');
          combined.canvases.push(...data.canvases);combined.items.push(...data.items);
        }
        return context(combined);
      } catch (error) {
        if (![404,405].includes(error.status)) throw error;
        // Compatibility with an older server; no fallback on permission/network errors.
        this.indexPromise ||= this.request('/api/canvas-assets').then(context).catch(failure=>{this.indexPromise=null;throw failure;});
        return this.indexPromise;
      }
    }
    loadMore() {
      if (this.loading) return;
      if (this.error) return this.load(!!this.cursor && !this.needsRefresh);
      if (this.visibleRows().length > this.limit) { this.limit += 24; this.render(); return; }
      if (this.cursor) return this.load(true);
    }
    visibleRows() {
      return this.rows.filter(row => this.scope === 'all' || row.projects.has(this.projectId))
        .sort((a, b) => this.newest ? b.created - a.created : a.created - b.created);
    }
    setScope(scope) {
      this.scopeTouched = true;
      this.scope = scope;
      this.resetGridScroll = true;
      this.limit = 24;
      this.selected = null;
      this.render();
    }
    choose(item) {
      this.selected = item;
      for (const card of this.root.querySelectorAll('[data-asset-key]'))
        card.setAttribute('aria-checked', String(card.dataset.assetKey === item.key));
      this.root.querySelector('[data-confirm]').disabled = false;
      this.root.querySelector('[data-selection]').textContent = `已选择：${item.name}`;
    }
    render() {
      const scrollTop = this.grid?.scrollTop || 0;
      this.root.replaceChildren();
      const sidebar = node('aside', 'character-asset-sidebar');
      const back = node('button', 'character-asset-back', '‹');
      back.type = 'button';
      back.setAttribute('aria-label', this.cancelLabel);
      back.onclick = this.onCancel;
      const heading = node('div', 'character-asset-heading');
      heading.append(back, node('h2', '', '资产库'));
      sidebar.append(heading);
      const nav = node('nav', 'character-asset-sources');
      nav.setAttribute('aria-label', '资产来源');
      for (const [value, label, icon] of [
        ['generated', '生成历史', 'history'], ['saved', '我保存的', 'folder'], ['uploaded', '我上传的', 'upload'],
      ]) {
        const button = node('button', '', label);
        button.type = 'button';
        button.setAttribute('aria-pressed', String(this.source === value));
        const image = node('i'); image.dataset.lucide = icon;
        button.prepend(image);
        button.onclick = () => { this.source = value; this.load(); };
        nav.append(button);
      }
      sidebar.append(nav);
      const main = node('div', 'character-asset-main');
      const tabs = node('nav', 'character-asset-scopes');
      tabs.setAttribute('aria-label', '项目范围');
      for (const [value, label] of [['project', '本项目'], ['all', '全部项目']]) {
        const button = node('button', '', label);
        button.type = 'button';
        button.disabled = value === 'project' && !this.projectId;
        button.setAttribute('aria-pressed', String(this.scope === value));
        button.onclick = () => this.setScope(value);
        tabs.append(button);
      }
      const available = this.visibleRows(), rows = available.slice(0,this.limit || 24);
      const tools = node('div', 'character-asset-tools');
      tools.append(node('span', 'character-asset-kind', `图片 · 已显示 ${rows.length}${this.cursor?'，可继续加载':''}`));
      const sort = node('button', '', '');
      sort.type = 'button';
      sort.innerHTML = '<i data-lucide="arrow-down-up"></i>';
      sort.setAttribute('aria-label', this.newest ? '排序：最新优先' : '排序：最早优先');
      sort.title = this.newest ? '最新优先' : '最早优先';
      sort.onclick = () => { this.newest = !this.newest; this.load(); };
      tools.append(sort);
      const grid = this.grid ||= node('div', 'character-pick-assets');
      this.gridRows = rows;
      grid.classList.toggle('is-empty', !rows.length);
      grid.setAttribute('role', 'radiogroup');
      grid.setAttribute('aria-label', '可选图片');
      grid.setAttribute('aria-busy', String(!!this.loading));
      grid.onclick = event => {
        const card = event.target.closest('[data-asset-index]');
        if (card) this.choose(this.gridRows[Number(card.dataset.assetIndex)]);
      };
      grid.onkeydown = event => {
        const card = event.target.closest('[data-asset-index]');
        if (!card || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const current = Number(card.dataset.assetIndex), columns = this.windowGrid.columns;
        const movement = {ArrowLeft: -1, ArrowRight: 1, ArrowUp: -columns, ArrowDown: columns};
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? rows.length - 1 :
          Math.max(0, Math.min(rows.length - 1, current + movement[event.key]));
        this.windowGrid.reveal(next).focus({preventScroll:true});
        this.choose(rows[next]);
      };
      let empty = null, more = null;
      if (!rows.length) {
        grid.classList.add('is-empty');
        empty = node('div', 'character-asset-empty');
        const icon = node('i'); icon.dataset.lucide = this.error ? 'circle-alert' : 'file-x-2';
        const label = this.loading ? '正在加载图片…' : this.error || (this.cursor?'已加载范围暂无匹配图片，可继续加载':({generated: '暂无历史记录', saved: '暂无保存的资产', uploaded: '暂无上传的资产'}[this.source]));
        empty.append(icon, node('p', '', label));
        if (!this.error && !this.loading && this.scope === 'project')
          empty.append(node('small', '', '可切换“全部项目”查看未关联本项目的图片'));
        if (this.error && !this.cursor) {
          const retry = node('button', '', '重新加载');
          retry.type = 'button'; retry.onclick = () => this.load(); empty.append(retry);
        }
      }
      if (this.cursor || available.length>rows.length || this.loading || this.error && rows.length) {
        more = node('button','character-asset-more',this.loading?'正在加载…':this.needsRefresh?'列表已更新，刷新':this.error?'加载失败，重试':'加载更多');
        more.type='button';more.disabled=!!this.loading;more.title=this.error || '';
        more.onclick=()=>this.loadMore();
      }
      const footer = node('footer', 'character-asset-footer');
      const selection = node('span', 'character-asset-selection', this.selected ? `已选择：${this.selected.name}` : '');
      selection.dataset.selection = ''; selection.setAttribute('role', 'status');
      const cancel = node('button', '', '取消');
      cancel.type = 'button'; cancel.onclick = this.onCancel;
      const confirm = node('button', 'character-primary', '确认选择');
      confirm.type = 'button'; confirm.dataset.confirm = '';
      confirm.disabled = !this.selected;
      confirm.onclick = () => { if (this.selected) this.onConfirm(this.selected); };
      footer.append(selection, cancel, confirm);
      main.append(tabs, tools, grid, footer);
      this.root.append(sidebar, main);
      this.windowGrid ||= new window.MediaGridWindow(grid, {
        columns:5, height:194, key:item=>item.key,
        create:item=>{
          const button=node('button');button.type='button';button.setAttribute('role','radio');
          const image=node('img'),preview=previewUrl(item.url);
          image.src=preview;image.alt='';image.loading='lazy';image.decoding='async';
          if(preview!==item.url)image.addEventListener('error',()=>{if(image.isConnected)image.src=item.url;},{once:true});
          button.append(image,node('span','',item.name));return button;
        },
        update:(button,item,index)=>{
          button.dataset.assetKey=item.key;button.dataset.assetIndex=String(index);
          button.setAttribute('aria-label',item.name);button.title=item.name;
          button.setAttribute('aria-checked',String(this.selected?.key===item.key));
          button.setAttribute('aria-posinset',String(index+1));button.setAttribute('aria-setsize',String(this.gridRows.length));
          button.querySelector('span').textContent=item.name;
        },
        release:button=>button.querySelector('img').removeAttribute('src'),
      });
      if(!this.resetGridScroll)grid.scrollTop=scrollTop;
      this.windowGrid.setItems(rows,{reset:!!this.resetGridScroll,footer:more,empty});
      this.resetGridScroll=false;
      window.lucide?.createIcons({root:this.root});
    }
    destroy() {
      this.destroyed = true;
      ++this.version;
      this.windowGrid?.dispose();
      this.root.remove();
    }
  }
  window.CharacterAssetSources = {urlKey, context, images, previewUrl};
  window.CharacterAssetPicker = CharacterAssetPicker;
})();
