/* Drag-first reference collection. Storage, ownership and canvas saves remain
 * in the existing asset-library and editor APIs. No provider is called here. */
(function(root){
    'use strict';
    const DEFAULTS=[['inbox','待整理','inbox'],['face','人脸参考','user'],['pose','姿势参考','person-standing'],['clothes','服装库','shirt'],['scene','场景参考','mountain']];
    function mediaKind(row){
        const value=String(row?.url || '').split(/[?#]/)[0];
        if(/\.(mp4|webm|mov|m4v|avi|mkv)$/i.test(value))return 'video';
        if(/\.(mp3|wav|m4a|aac|ogg|flac)$/i.test(value))return 'audio';
        return row?.kind || row?.mediaKind || 'image';
    }
    function previewUrl(value,size=240){
        const preview=root.canvasMediaPreviewUrl || root.smartMediaPreviewUrl;
        if(typeof preview!=='function')return value;
        try{const url=new URL(value,location.origin);return url.origin===location.origin?preview(url.pathname+url.search,size):value;}catch(_){return value;}
    }
    function mediaFromNodes(nodes){
        const found=new Map();
        function add(value,node){
            const row=typeof value==='string'?{url:value}:value;
            if(!row?.url || !['image','video','audio'].includes(mediaKind(row)))return;
            if(!found.has(row.url))found.set(row.url,{url:row.url,name:row.name || node.name || node.title || '画布素材',nodeId:node.id,kind:mediaKind(row),
                width:row.width || row.w,height:row.height || row.h});
        }
        for(const node of nodes || []){
            if(['image','video','audio'].includes(node.type) && node.url)add(node,node);
            for(const key of ['images','generatedOutputs','outputs','videos','audios'])for(const row of Array.isArray(node[key])?node[key]:[])add(row,node);
        }
        return [...found.values()];
    }
    class ReferenceShelf{
        constructor(fetcher){this.fetcher=fetcher;this.actor='';this.library=null;this.libraries=[];this.selectedId='';this.pending=new Map();this.itemVersion=0;this.page={rows:[],cursor:null,total:0,loading:false,error:''};}
        async request(path,method='GET',body){
            if(method!=='GET' && path.startsWith('/api/asset-library/'))path+=(path.includes('?')?'&':'?')+'catalog=1';
            const response=await this.fetcher(path,{method,credentials:'same-origin',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
            const data=await response.json().catch(()=>({}));
            if(!response.ok)throw Object.assign(new Error(typeof data.detail==='string'?data.detail:(data.detail?.message || data.message || (response.status===409?'目录已变化，请刷新后再拖入':'整理未完成，请稍后重试'))),{status:response.status});
            return data;
        }
        async refresh({catalog=false}={}){
            const who=await this.request('/enterprise/api/me');
            if(this.actor && this.actor!==who.user_id){this.pending.clear();this.cancelItems();this.page={rows:[],cursor:null,total:0,loading:false,error:''};this.library=null;this.libraries=[];this.selectedId='';this.actor=who.user_id;throw new Error('账号已变化，请重新打开资产整理');}
            this.actor=who.user_id;
            const data=await this.request('/api/asset-library'+(catalog?'?catalog=1':''));
            this.libraries=data.library?.libraries || [];
            this.library=this.selectedId?this.libraries.find(row=>row.id===this.selectedId):this.libraries.find(row=>row.reference_shelf_owner===this.actor);
            if(this.selectedId && !this.library)throw new Error('资产库已删除或权限已变化，请重新选择');
            this.library ||= null;
            return this.library;
        }
        adopt(data){
            if(data.library?.libraries)this.libraries=data.library.libraries;
            const id=this.selectedId || this.library?.id;
            const row=data.asset_library || this.libraries.find(value=>value.id===id);
            if(!row)throw new Error('目录已变化，请重新打开资产整理');
            this.library=row;this.selectedId=row.id;
        }
        async selectLibrary(id,options){
            // A missing/revoked selection must not silently write into another library.
            this.selectedId=id;
            await this.refresh(options);
            return this.library;
        }
        cancelItems(){++this.itemVersion;this.page.loading=false;}
        async loadItems(folder,query='',append=false){
            const categoryId=folder?.category?.id,libraryId=this.library?.id;
            if(!libraryId || !categoryId){this.cancelItems();this.page={rows:[],cursor:null,total:0,loading:false,error:''};return;}
            const key=JSON.stringify([this.actor,libraryId,categoryId,query]);
            if(append && (this.page.loading || this.page.key!==key || !this.page.cursor))return;
            const version=++this.itemVersion,cursor=append?this.page.cursor:null;
            const keep=append || this.page.key===key;
            this.page={key,rows:keep?this.page.rows:[],cursor,total:keep?this.page.total:0,loading:true,error:'',refresh:false};
            const params=new URLSearchParams({page_size:'24',library_id:libraryId,category_id:categoryId,q:query});
            if(cursor)params.set('cursor',cursor);
            try{
                const data=await this.request('/api/asset-library?'+params);
                if(version!==this.itemVersion)return;
                let rows,total,next;
                if(Array.isArray(data.items)){
                    if(!Number.isFinite(data.total) || data.next_cursor!==null && typeof data.next_cursor!=='string')throw Error('素材列表返回格式异常，请重试');
                    rows=data.items;total=data.total;next=data.next_cursor;
                }else if(Array.isArray(data.library?.libraries)){
                    // Older deployments return the original full directory.
                    rows=(data.library.libraries.find(row=>row.id===libraryId)?.categories || []).find(row=>row.id===categoryId)?.items || [];
                    rows=rows.filter(row=>!query || String(row.name || '').toLocaleLowerCase().includes(query.toLocaleLowerCase()));total=rows.length;next=null;
                }else throw Error('素材列表返回格式异常，请重试');
                const unique=new Map((append?this.page.rows:[]).map(row=>[row.id,row]));
                for(const row of rows)unique.set(row.id,{...row,itemId:row.id});
                this.page={key,rows:[...unique.values()],cursor:next,total,loading:false,error:'',refresh:false};
            }catch(error){
                if(version!==this.itemVersion)return;
                this.page.loading=false;this.page.error=error.message || '素材加载失败，请重试';this.page.refresh=error.status===409;
                if([401,403].includes(error.status))Object.assign(this.page,{rows:[],cursor:null,total:0});
            }
        }
        async createLibrary(name){
            await this.refresh({catalog:true});
            const data=await this.request('/api/asset-library/libraries','POST',{name,reference_shelf:true});
            this.adopt(data);return this.library;
        }
        folders(){
            const cats=this.library?.categories || [];
            const result=DEFAULTS.map(([key,name,icon])=>({key,name,icon,category:cats.find(row=>row.name===name && row.type==='image')}));
            for(const cat of cats)if(cat.type==='image' && !result.some(row=>row.category?.id===cat.id))result.push({key:cat.id,name:cat.name,icon:'folder',category:cat});
            return result;
        }
        async ensureFolder(folder){
            if(!this.library)await this.createLibrary('我的参考库');
            let category=this.library.categories.find(row=>row.type==='image' && (row.id===folder.key || row.name===folder.name));
            if(!category){
                const data=await this.request('/api/asset-library/categories','POST',{library_id:this.library.id,name:folder.name,type:'image'});
                this.adopt(data);category=this.library.categories.find(row=>row.id===data.category.id);
            }
            return category;
        }
        async collect(item,folder){
            await this.refresh({catalog:true});const cat=await this.ensureFolder(folder),libraryId=this.library.id;
            const existing=item.itemId && await this.lookup({item_id:item.itemId});
            if(existing){
                if(existing.category_id===cat.id)return{label:'已在这个文件夹中',item:existing};
                this.adopt(await this.request('/api/asset-library/items/move','POST',{library_id:libraryId,ids:[existing.id],target_library_id:libraryId,target_category_id:cat.id}));
                return{label:'已移入 '+folder.name,item:existing,undo:{kind:'move',libraryId,id:existing.id,from:existing.category_id,to:cat.id}};
            }
            const duplicate=await this.lookup({category_id:cat.id,match_url:item.url});
            if(duplicate)return{label:'已保存在 '+folder.name,item:duplicate};
            const key=cat.id+'\n'+item.url;
            if(!this.pending.has(key))this.pending.set(key,root.crypto.randomUUID());
            const data=await this.request('/api/asset-library/items','POST',{library_id:libraryId,category_id:cat.id,url:item.url,name:item.name,classify:false,collect_request_id:this.pending.get(key)});
            this.adopt(data);this.pending.delete(key);
            return{label:'已保存到 '+folder.name,item:data.item,undo:data.already_saved?null:{kind:'collect',libraryId,id:data.item.id,to:cat.id}};
        }
        async undo(action){
            await this.refresh({catalog:true});
            if(action.libraryId && action.libraryId!==this.library?.id)throw new Error('请回到原资产库撤销这次整理');
            const item=await this.lookup({item_id:action.id});
            if(!item || item.category_id!==action.to)throw new Error('素材已被再次整理，未覆盖后续修改');
            const data=action.kind==='move'
                ?await this.request('/api/asset-library/items/move','POST',{library_id:this.library.id,ids:[action.id],target_library_id:this.library.id,target_category_id:action.from})
                :await this.request('/api/asset-library/items/'+encodeURIComponent(action.id)+'?keep_file=true','DELETE');
            this.adopt(data);
        }
        async lookup(selectors){
            const params=new URLSearchParams({page_size:'1',library_id:this.library.id,...selectors});
            const data=await this.request('/api/asset-library?'+params);
            if(Array.isArray(data.items))return data.items[0] || null;
            // Legacy full responses remain readable without another full GET.
            const lib=data.library?.libraries?.find(row=>row.id===this.library.id);
            if(!lib)throw Error('素材查询返回格式异常，请刷新后重试');
            for(const category of lib.categories || [])for(const row of category.items || []){
                if(selectors.item_id && row.id!==selectors.item_id || selectors.category_id && category.id!==selectors.category_id)continue;
                if(selectors.match_url && ![row.url,row.collected_from].includes(selectors.match_url))continue;
                return {...row,category_id:category.id};
            }
            return null;
        }
    }
    // Canvas-origin gestures can only collect. Only saved-library gestures insert.
    function dropIntent(origin,target){
        if(target==='folder' || target==='gallery')return 'collect';
        return origin==='library' && target==='canvas'?'insert':'none';
    }
    const exports={ReferenceShelf,mediaFromNodes,mediaKind,dropIntent,previewUrl};
    if(typeof module!=='undefined' && module.exports)module.exports=exports;
    if(typeof document==='undefined')return;
    function element(tag,cls,text){const el=document.createElement(tag);if(cls)el.className=cls;if(text!==undefined)el.textContent=text;return el;}
    function icon(name){const el=element('i');el.dataset.lucide=name;return el;}
    function safeMedia(value){
        try{const u=new URL(value,location.origin);return u.origin===location.origin && /^\/(assets|output)\//.test(u.pathname)?u.href:'';}catch(_){return '';}
    }
    function install(adapter){
        let setting=new URLSearchParams(location.search).get('assetShelf');
        try{setting ??=new URLSearchParams(parent.location.search).get('assetShelf');}catch(_){}
        if(setting==='0')return;
        const shell=document.getElementById('shell');
        if(!shell || document.getElementById('referenceShelf'))return;
        const controller=new AbortController();
        const listen=(el,type,fn,options={})=>el.addEventListener(type,fn,{...options,signal:controller.signal});
        let viewController=new AbortController();
        const listenView=(el,type,fn,options={})=>el.addEventListener(type,fn,{...options,signal:viewController.signal});
        const model=new ReferenceShelf(root.fetch.bind(root));
        let open=false,view='canvas',active='inbox',queue=Promise.resolve(),pointerDrag=null,ghost=null;
        let lastActions=[],statusTimer=null,searchTimer=null,suppressClickUntil=0,selectionLoaded=false,displayLimit=24;
        const trigger=element('button','reference-shelf-toggle');
        trigger.type='button';trigger.setAttribute('aria-label','资产整理');trigger.setAttribute('aria-expanded','false');
        trigger.append(icon('folder-open'),element('span','','资产整理'));
        const panel=element('aside','reference-shelf');
        panel.id='referenceShelf';panel.hidden=true;panel.setAttribute('aria-label','资产整理');
        const header=element('header','reference-shelf-head'),heading=element('div');
        const privacy=element('span','reference-shelf-private','个人资产');
        heading.append(element('strong','','资产整理'),privacy);
        const close=element('button','reference-shelf-icon');close.type='button';close.setAttribute('aria-label','关闭资产整理');close.append(icon('x'));
        header.append(heading,close);
        const libraryBar=element('div','reference-shelf-library-bar');
        const librarySelect=element('select','reference-shelf-library-select');librarySelect.setAttribute('aria-label','选择资产库');
        const addLibrary=element('button','reference-shelf-icon');addLibrary.type='button';addLibrary.setAttribute('aria-label','新建资产库');addLibrary.title='新建产品或用途资产库';addLibrary.append(icon('folder-plus'));
        libraryBar.append(librarySelect,addLibrary);
        const hint=element('p','reference-shelf-hint','直接拖动画布素材到文件夹或下方区域保存');
        const folderGrid=element('div','reference-shelf-folders');folderGrid.setAttribute('aria-label','参考文件夹');
        const tabs=element('div','reference-shelf-tabs');tabs.setAttribute('role','tablist');
        const canvasTab=element('button','','当前画布'),savedTab=element('button','','库内素材');
        for(const tab of [canvasTab,savedTab]){tab.type='button';tab.setAttribute('role','tab');tabs.append(tab);}
        const search=element('input','reference-shelf-search');search.placeholder='搜索素材名称';search.setAttribute('aria-label','搜索参考');
        const summary=element('div','reference-shelf-summary');
        const gallery=element('div','reference-shelf-gallery');gallery.setAttribute('aria-label','素材区');
        const footer=element('div','reference-shelf-foot');
        const status=element('span','reference-shelf-status');status.setAttribute('role','status');
        const undo=element('button','reference-shelf-undo','撤销本次整理');undo.type='button';undo.hidden=true;
        footer.append(status,undo);
        panel.append(header,libraryBar,hint,folderGrid,tabs,search,summary,gallery,footer);
        shell.append(trigger,panel);
        function icons(container=panel){root.lucide?.createIcons({root:container});if(container===panel)root.lucide?.createIcons({root:trigger});}
        function resetStatus(){status.textContent='画布拖入保存 · 库内素材拖回画布复用';status.removeAttribute('role');status.setAttribute('role','status');footer.classList.remove('is-error');}
        function notify(text,error=false){
            clearTimeout(statusTimer);status.textContent=text;status.setAttribute('role',error?'alert':'status');footer.classList.toggle('is-error',error);
            if(!error)statusTimer=setTimeout(resetStatus,2500);
        }
        function setUndo(actions){lastActions=actions;undo.hidden=!lastActions.length;}
        function run(operation){
            queue=queue.catch(()=>{}).then(async()=>{
                panel.setAttribute('aria-busy','true');
                try{await operation();}catch(error){notify(error.message || '整理未完成，原素材已保留',true);}
                finally{panel.removeAttribute('aria-busy');render();if(open && view==='saved')await loadSaved();}
            });return queue;
        }
        function remember(){try{sessionStorage.setItem('canvasAssetShelfLibrary:'+model.actor,model.library?.id || '');}catch(_){};}
        async function refresh(){
            await model.refresh({catalog:true});
            if(!selectionLoaded){
                selectionLoaded=true;
                try{
                    const id=sessionStorage.getItem('canvasAssetShelfLibrary:'+model.actor);
                    const found=model.libraries.find(row=>row.id===id);
                    if(found){model.selectedId=id;model.library=found;}
                }catch(_){}
            }
        }
        function folders(){return model.folders();}
        function selectedFolder(){return folders().find(row=>row.key===active) || folders()[0];}
        function galleryFolder(){return view==='saved'?selectedFolder():folders()[0];}
        function items(){return view==='canvas'?adapter.items():model.page.rows;}
        async function loadSaved(append=false){
            if(!append)displayLimit=24;
            const pending=model.loadItems(selectedFolder(),search.value.trim(),append);
            render();await pending;if(open && view==='saved')render();
        }
        function payload(item,origin){return{url:item.url,name:item.name,width:item.width,height:item.height,kind:mediaKind(item),itemId:item.itemId || '',origin};}
        function thumbnail(item,preview=false,listenMedia=listenView){
            const kind=mediaKind(item),url=safeMedia(item.url);
            if(kind==='image'){
                const img=element('img'),src=previewUrl(url,preview?96:240);img.src=src;img.alt=preview?'':item.name || '图片';img.loading='lazy';img.decoding='async';img.draggable=false;
                if(src!==url)listenMedia(img,'error',()=>{if(img.isConnected)img.src=url;},{once:true});
                return img;
            }
            if(preview){const badge=element('span','reference-shelf-cover-media');badge.append(icon(kind==='video'?'film':'music-2'));return badge;}
            const wrap=element('div','reference-shelf-media');
            if(kind==='video'){
                const video=element('video');video.src=url;video.preload='metadata';video.controls=true;video.playsInline=true;
                listenMedia(video,'loadedmetadata',()=>{if(video.videoWidth && video.videoHeight){item.width=video.videoWidth;item.height=video.videoHeight;}});wrap.append(video);
            }else{
                wrap.append(icon('music-2'));const audio=element('audio');audio.src=url;audio.controls=true;audio.preload='none';wrap.append(audio);
            }
            wrap.append(element('span','reference-shelf-media-kind',kind==='video'?'视频':'音频'));return wrap;
        }
        async function insert(item,point){
            // Thumbnail dimensions must never become the original canvas size.
            const probe=root.loadCanvasOriginalImageDimensions || root.loadSmartOriginalImageDimensions;
            if(mediaKind(item)==='image' && (!item.width || !item.height) && typeof probe==='function'){
                const size=await probe(item.url);if(size)item={...item,width:size.w,height:size.h};
            }
            adapter.insert(item,point);
        }
        function saveItems(media,folder){return run(async()=>{
            const actions=[];setUndo([]);let label='';
            try{
                for(const item of media){const result=await model.collect(item,folder);label=result.label;if(result.undo)actions.push(result.undo);}
            }finally{setUndo(actions);}
            active=folder.key;view='saved';remember();
            notify(media.length>1?'本次整理完成：'+media.length+' 项':label);
        });}
        function releaseMedia(container=gallery){
            for(const media of container.querySelectorAll('video,audio')){media.pause();media.removeAttribute('src');media.load();}
            for(const image of container.querySelectorAll('img'))image.removeAttribute('src');
        }
        let gridContext='';
        const gridWindow=new root.MediaGridWindow(gallery,{
            columns:2,height:142,
            key:item=>JSON.stringify([view,item.id || item.itemId || item.url,item.url,item.name,mediaKind(item)]),
            create:item=>{
                const card=element('article','reference-shelf-card');card.dataset.shelfCard='1';card.title=view==='canvas'?'拖到文件夹保存':'拖到文件夹整理，拖回画布复用';
                card.append(thumbnail(item,false,(el,type,fn,options)=>el.addEventListener(type,fn,options)),element('span','reference-shelf-card-name',item.name || '未命名素材'));
                if(view==='saved'){
                    const plus=element('button','reference-shelf-insert');plus.type='button';plus.setAttribute('aria-label','放入画布：'+(item.name || '素材'));plus.append(icon('plus'));card.append(plus);
                }
                icons(card);return card;
            },
            update:(card,item)=>{card._shelfItem=item;card._shelfOrigin=view==='saved'?'library':'canvas';},
            release:releaseMedia,
        });
        function render(){
            viewController.abort();viewController=new AbortController();
            const options=model.libraries.slice();
            if(!model.library && !options.some(row=>row.id===''))options.unshift({id:'',name:'我的参考库（首次保存时创建）'});
            librarySelect.replaceChildren();
            for(const row of options){const option=element('option','',row.name || '未命名资产库');option.value=row.id;librarySelect.append(option);}
            librarySelect.value=model.library?.id || '';
            privacy.textContent=!model.library || model.library.reference_shelf_owner===model.actor?'个人资产':'按权限访问';
            folderGrid.replaceChildren();
            for(const folder of folders()){
                const target=element('button','reference-shelf-folder'+(active===folder.key && view==='saved'?' is-selected':''));
                target.type='button';target.dataset.folder=folder.key;target.setAttribute('aria-label',folder.name+'文件夹');
                const preview=element('span','reference-shelf-folder-preview');preview.append(icon(folder.icon));
                const covers=(folder.category?.preview_items || folder.category?.items || []).filter(row=>safeMedia(row.url)).slice(-2);
                for(const row of covers)preview.append(thumbnail(row,true));
                target.append(preview,element('span','reference-shelf-folder-name',folder.name),element('span','reference-shelf-folder-count',String(folder.category?.item_count ?? folder.category?.items?.length ?? 0)));
                listenView(target,'click',()=>{if(Date.now()<suppressClickUntil)return;active=folder.key;view='saved';loadSaved();});folderGrid.append(target);
            }
            const create=element('button','reference-shelf-new');create.type='button';create.append(icon('folder-plus'),element('span','','新建文件夹'));listenView(create,'click',()=>newName('folder'));folderGrid.append(create);
            canvasTab.setAttribute('aria-selected',String(view==='canvas'));savedTab.setAttribute('aria-selected',String(view==='saved'));
            const query=search.value.trim().toLocaleLowerCase();
            const available=items().filter(row=>safeMedia(row.url) && ['image','video','audio'].includes(mediaKind(row)) && (view==='saved' || !query || String(row.name || '').toLocaleLowerCase().includes(query)));
            const list=available.slice(0,displayLimit),page=view==='saved'?model.page:null;
            summary.textContent=(view==='canvas'?'当前画布':selectedFolder().name)+' · 已显示 '+list.length+' / '+(page?page.total:available.length)+' 项';
            let empty=null,more=null;
            if(!list.length && !page?.loading && !page?.error){
                empty=element('div','reference-shelf-empty');
                empty.append(icon('image-plus'),element('strong','',query?'没有找到匹配的素材':'把画布素材拖到这里'),element('span','',query?'换个名称试试，已有素材仍会保留':'支持图片、视频和音频；松开保存至「'+galleryFolder().name+'」'));icons(empty);
            }
            if(page?.loading || page?.error || available.length>list.length || page?.cursor){
                more=element('button','reference-shelf-more',page?.loading?'正在加载…':page?.refresh?'列表已更新，刷新':page?.error?'加载失败，重试':'加载更多');
                more.type='button';more.disabled=!!page?.loading;more.title=page?.error || '';
                listenView(more,'click',()=>{
                    if(page?.error){loadSaved(!!page.cursor && !page.refresh);return;}
                    if(available.length>displayLimit){displayLimit+=24;render();}
                    else {displayLimit+=24;loadSaved(true);}
                });
            }
            const context=JSON.stringify([view,model.library?.id,active,query]);
            gridWindow.setItems(list,{reset:context!==gridContext,footer:more,empty});gridContext=context;
            icons(folderGrid);
        }
        listen(gallery,'pointerdown',event=>{
            const card=event.target.closest('[data-shelf-card]');
            if(card && !event.target.closest('button,video,audio'))beginPointer(event,payload(card._shelfItem,card._shelfOrigin));
        });
        listen(gallery,'click',event=>{
            const card=event.target.closest('[data-shelf-card]');
            if(card && event.target.closest('.reference-shelf-insert') && Date.now()>=suppressClickUntil)insert(card._shelfItem);
        });
        listen(gallery,'dblclick',event=>{
            const card=event.target.closest('[data-shelf-card]');
            if(card?._shelfOrigin==='library' && !event.target.closest('video,audio') && Date.now()>=suppressClickUntil)insert(card._shelfItem);
        });
        function newName(type){
            panel.querySelector('.reference-shelf-create-form')?.remove();
            panel.classList.add('is-naming');
            const isLibrary=type==='library',input=element('input','reference-shelf-new-name');
            input.placeholder=isLibrary?'资产库名称，例如：女装春夏':'文件夹名称，例如：衬衫／款式A';input.setAttribute('aria-label',isLibrary?'新资产库名称':'新文件夹名称');input.maxLength=40;
            const form=element('div','reference-shelf-create-form');
            const cancel=element('button','reference-shelf-create-cancel','取消');cancel.type='button';cancel.setAttribute('aria-label',isLibrary?'取消新建资产库':'取消新建文件夹');
            const cancelForm=()=>{form.remove();panel.classList.remove('is-naming');(isLibrary?addLibrary:folderGrid.querySelector('.reference-shelf-new'))?.focus();};
            listen(cancel,'click',cancelForm);form.append(input,cancel);
            (isLibrary?libraryBar:folderGrid).append(form);form.scrollIntoView({block:'nearest'});input.focus();
            listen(input,'keydown',event=>{
                if(event.key==='Escape'){event.stopPropagation();cancelForm();}
                if(event.key==='Enter' && input.value.trim()){
                    const name=input.value.trim();form.remove();panel.classList.remove('is-naming');
                    run(async()=>{
                        if(isLibrary){await model.createLibrary(name);active='inbox';setUndo([]);remember();}
                        else{await model.refresh({catalog:true});const category=await model.ensureFolder({key:'new',name});active=category.id;}
                        view='saved';notify(isLibrary?'已切换资产库，可拖入素材':'文件夹已就绪，可拖入素材');
                    });
                }
            });
        }
        async function show(value){
            open=value;panel.hidden=!open;trigger.setAttribute('aria-expanded',String(open));
            if(!open){model.cancelItems();clearTimeout(searchTimer);viewController.abort();gridWindow.clear();return;}
            placeEntry();render();try{await refresh();if(open){if(view==='saved')await loadSaved();else render();}}catch(error){notify(error.message,true);}
        }
        function dropTarget(event){
            if(!open)return null;
            const hit=document.elementFromPoint(event.clientX,event.clientY);
            if(!hit || !panel.contains(hit))return null;
            const folder=hit.closest('[data-folder]');
            if(folder)return{type:'folder',el:folder,folder:folders().find(row=>row.key===folder.dataset.folder)};
            if(gallery.contains(hit))return{type:'gallery',el:gallery,folder:galleryFolder()};
            return null;
        }
        function clearDrop(){panel.classList.remove('is-dragging');panel.querySelectorAll('.is-drop').forEach(el=>el.classList.remove('is-drop'));hint.textContent='直接拖动画布素材到文件夹或下方区域保存';}
        function previewNodeDrag(event,media){
            const hit=document.elementFromPoint(event.clientX,event.clientY);
            if(media.length && trigger.contains(hit) && !open)show(true);
            clearDrop();const target=dropTarget(event);
            if(!media.length || !target)return false;
            panel.classList.add('is-dragging');target.el.classList.add('is-drop');hint.textContent='松开保存到「'+target.folder.name+'」';return true;
        }
        function dropNodeDrag(event,media){
            const target=dropTarget(event);clearDrop();
            if(!target || !media.length)return false;
            suppressClickUntil=Date.now()+250;saveItems(media,target.folder);return true;
        }
        function accept(event){return [...(event.dataTransfer?.types || [])].some(type=>['application/x-canvas-asset','application/x-canvas-output-image'].includes(type));}
        function read(event){
            try{const raw=event.dataTransfer.getData('application/x-canvas-asset');const item=raw?JSON.parse(raw):{url:event.dataTransfer.getData('application/x-canvas-output-image'),name:'画布素材'};return safeMedia(item.url) && ['image','video','audio'].includes(mediaKind(item))?item:null;}catch(_){return null;}
        }
        function canvasTarget(target){return shell.contains(target) && !panel.contains(target) && !target.closest('button,input,textarea,dialog,.topbar,.canvas-dock');}
        function beginPointer(event,item){
            if(event.button!==0 || !safeMedia(item.url))return;
            event.preventDefault();event.stopPropagation();pointerDrag={item,x:event.clientX,y:event.clientY,id:event.pointerId,active:false};
        }
        function clearPointer(){pointerDrag=null;ghost?.remove();ghost=null;clearDrop();}
        listen(window,'pointermove',event=>{
            if(!pointerDrag || event.pointerId!==pointerDrag.id)return;
            if(!pointerDrag.active && Math.hypot(event.clientX-pointerDrag.x,event.clientY-pointerDrag.y)<6)return;
            event.preventDefault();event.stopPropagation();
            if(!pointerDrag.active){
                pointerDrag.active=true;ghost=element('div','reference-shelf-ghost');ghost.append(thumbnail(pointerDrag.item,true),element('span','',pointerDrag.item.name || '素材'));shell.append(ghost);
            }
            ghost.style.left=(event.clientX+14)+'px';ghost.style.top=(event.clientY+14)+'px';previewNodeDrag(event,[pointerDrag.item]);
        },{capture:true});
        listen(window,'pointerup',event=>{
            if(!pointerDrag || event.pointerId!==pointerDrag.id)return;
            const current=pointerDrag,target=dropTarget(event),hit=document.elementFromPoint(event.clientX,event.clientY);
            clearPointer();if(!current.active)return;event.preventDefault();event.stopPropagation();suppressClickUntil=Date.now()+250;
            const intent=dropIntent(current.item.origin,target?.type || (hit && canvasTarget(hit)?'canvas':''));
            if(intent==='collect')saveItems([current.item],target.folder);
            else if(intent==='insert')insert(current.item,{x:event.clientX,y:event.clientY});
        },{capture:true});
        listen(window,'pointercancel',clearPointer);listen(window,'blur',clearPointer);
        listen(panel,'dragover',event=>{if(!accept(event))return;event.preventDefault();event.stopPropagation();event.dataTransfer.dropEffect='copy';const item=read(event);previewNodeDrag(event,[item || {}]);});
        listen(panel,'dragleave',event=>{if(!panel.contains(event.relatedTarget))clearDrop();});
        listen(panel,'drop',event=>{if(!accept(event))return;event.preventDefault();event.stopPropagation();const item=read(event);if(item)dropNodeDrag(event,[item]);});
        listen(document,'dragend',clearDrop);
        listen(librarySelect,'change',()=>{const id=librarySelect.value;panel.querySelector('.reference-shelf-create-form')?.remove();panel.classList.remove('is-naming');run(async()=>{await model.selectLibrary(id,{catalog:true});active='inbox';view='saved';setUndo([]);remember();resetStatus();});});
        listen(addLibrary,'click',()=>newName('library'));
        listen(undo,'click',()=>run(async()=>{for(const action of lastActions.slice().reverse())await model.undo(action);setUndo([]);notify('已撤销整理，原素材仍保留');}));
        listen(trigger,'click',()=>show(!open));listen(close,'click',()=>show(false));
        listen(canvasTab,'click',()=>{view='canvas';displayLimit=24;model.cancelItems();render();});listen(savedTab,'click',()=>{view='saved';loadSaved();});
        listen(search,'input',()=>{clearTimeout(searchTimer);displayLimit=24;if(view==='saved')searchTimer=setTimeout(()=>loadSaved(),200);else render();});
        for(const type of ['pointerdown','mousedown','wheel','dblclick','keydown'])listen(panel,type,event=>{if(event.key!=='Escape')event.stopPropagation();});
        listen(document,'keydown',event=>{if(event.key==='Escape' && pointerDrag){event.preventDefault();event.stopPropagation();clearPointer();}else if(open && event.key==='Escape' && !document.querySelector('dialog[open]')){event.preventDefault();event.stopPropagation();show(false);}});
        function placeEntry(){
            const dock=document.getElementById('canvasDock'),box=shell.getBoundingClientRect();let bottom=14,panelBottom=68;
            if(dock){
                const rect=dock.getBoundingClientRect(),height=trigger.offsetHeight || 38,width=trigger.offsetWidth || 105;
                const left=box.left+14,top=box.bottom-bottom-height;
                if(left<rect.right+8 && left+width>rect.left-8 && top<rect.bottom+8 && top+height>rect.top-8)bottom=Math.max(bottom,box.bottom-rect.top+10);
                const panelLeft=box.left+12,panelWidth=panel.offsetWidth || 326;
                if(panelLeft<rect.right+8 && panelLeft+panelWidth>rect.left-8)panelBottom=Math.max(panelBottom,box.bottom-rect.top+10);
            }
            trigger.style.bottom=bottom+'px';panel.style.bottom=Math.max(panelBottom,bottom+(trigger.offsetHeight || 38)+10)+'px';
        }
        listen(window,'resize',placeEntry);
        const dock=document.getElementById('canvasDock'),observer=dock?new MutationObserver(placeEntry):null;
        observer?.observe(dock,{attributes:true,attributeFilter:['style']});placeEntry();resetStatus();icons();
        return{open:()=>show(true),previewNodeDrag,dropNodeDrag,clearDrop,dispose(){model.cancelItems();viewController.abort();gridWindow.dispose();clearPointer();clearTimeout(statusTimer);clearTimeout(searchTimer);observer?.disconnect();controller.abort();for(const el of [trigger,panel])el.remove();}};
    }
    root.CanvasAssetShelf={...exports,install};
})(typeof window==='undefined'?globalThis:window);
