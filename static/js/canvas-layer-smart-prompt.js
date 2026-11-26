/* Inline smart-edit references. Public reference: Jimeng 1225 / 6680 marker
 * node views. The prompt keeps its existing plain-text image API contract. */
(function(root){
    const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const t=key=>root.StudioI18n.t('layers.'+key),clamp=(v,min,max)=>Math.max(min,Math.min(max,v));
    const reference=mark=>'【'+mark.number+'】';
    function parts(text,marks){
        const result=[];let at=0;
        for(const hit of text.matchAll(/【(\d+)】/g)){
            const mark=marks.find(m=>m.kind==='marker'&&m.number===Number(hit[1]));if(!mark)continue;
            if(hit.index>at)result.push({text:text.slice(at,hit.index)});
            result.push({mark});at=hit.index+hit[0].length;
        }
        if(at<text.length)result.push({text:text.slice(at)});return result;
    }
    function pin(number,size=16){
        return `<svg class="layer-smart-pin" aria-hidden="true" width="${size}" height="${size}" viewBox="0 0 16 16"><path d="M8 0C4.465 0 1.6 2.864 1.6 6.4C1.6 10.08 6.183 14.198 7.53 15.315C7.805 15.543 8.195 15.543 8.47 15.315C9.817 14.198 14.4 10.08 14.4 6.4C14.4 2.864 11.535 0 8 0Z"/><text x="8" y="6.4" dominant-baseline="central" text-anchor="middle" font-size="${number<10?10:8}">${number}</text></svg>`;
    }
    function thumbnailCrop(mark,source){
        const w=source.width,h=source.height,r=mark.rect,p=mark.points[0];
        const side=Math.min(r?Math.max(r.width*w,r.height*h)+48:180,w,h);
        const x=(r?r.x+r.width/2:p.x)*w,y=(r?r.y+r.height/2:p.y)*h;
        return {x:clamp(x-side/2,0,w-side),y:clamp(y-side/2,0,h-side),width:side,height:side};
    }
    function previewFrame(mark,source,zoomed){
        const w=source.width,h=source.height,r=mark.rect,p=mark.points[0];
        let crop={x:0,y:0,width:w,height:h};
        if(zoomed){
            let width,height;
            if(r){const scale=Math.min(272/Math.max(1,r.width*w),132/Math.max(1,r.height*h));width=Math.min(w,320/scale);height=Math.min(h,180/scale);}
            else{width=Math.min(320,w);height=Math.min(180,h);if(width/height>320/180)width=height*320/180;else height=width*180/320;}
            const x=(r?r.x+r.width/2:p.x)*w,y=(r?r.y+r.height/2:p.y)*h;
            crop={x:clamp(x-width/2,0,w-width),y:clamp(y-height/2,0,h-height),width,height};
        }
        const scale=Math.min(320/crop.width,180/crop.height);
        return {source:crop,target:{x:(320-crop.width*scale)/2,y:(180-crop.height*scale)/2,width:crop.width*scale,height:crop.height*scale},scale};
    }
    function serialize(node){
        if(node.nodeType===3)return node.textContent.replace(/\u200b/g,'');
        if(node.getAttribute?.('data-edit-tail')==='true')return '';
        if(node.getAttribute?.('data-edit-reference'))return node.getAttribute('data-reference-text')||'';
        if(node.nodeName==='BR')return '\n';
        let text='';
        for(const child of node.childNodes||[]){
            if(['DIV','P'].includes(child.nodeName)&&text&&!text.endsWith('\n'))text+='\n';
            text+=serialize(child);
        }
        return text;
    }
    const needsMultiline=(text,width,available)=>text.includes('\n')||available<=0||width>available;
    function contentWidth(host){
        let width=0;
        for(const node of host.childNodes){
            if(node.nodeType===1&&node.getAttribute('data-edit-reference')){
                const style=getComputedStyle(node);width+=node.getBoundingClientRect().width+parseFloat(style.marginLeft)+parseFloat(style.marginRight);
            }else if(node.nodeName!=='BR'){
                const range=document.createRange();range.selectNodeContents(node);width+=[...range.getClientRects()].reduce((sum,r)=>sum+r.width,0);
            }
        }
        return width;
    }
    class Prompt{
        constructor(options){this.o=options;this.caret={start:0,end:0};}
        mount(host,preview,text,marks,source){
            this.resizeObserver?.disconnect();cancelAnimationFrame(this.layoutFrame);this.layoutFrame=0;
            this.host=host;this.preview=preview;this.marks=marks;this.source=source;
            host.innerHTML=parts(text,marks).map(part=>part.mark?this.token(part.mark):esc(part.text).replace(/\n/g,'<br>')).join('')+(text.endsWith('\n')?'<br data-edit-tail="true">':'');
            if(!host.lastChild||host.lastChild.nodeType!==3)host.append(document.createTextNode(''));
            host.oninput=e=>{if(e.inputType?.startsWith('delete')&&host.innerHTML==='<br>')host.replaceChildren();this.capture();this.changed();this.hidePreview();};
            host.onbeforeinput=e=>{if(!e.isComposing)this.o.remember();if(['insertParagraph','insertLineBreak'].includes(e.inputType)){e.preventDefault();this.insert('\n');}};
            host.oncompositionstart=()=>this.o.remember();
            host.onkeyup=host.onmouseup=()=>this.capture();
            host.onfocusout=()=>{this.capture();this.hidePreview();};
            host.onpointerdown=e=>{
                const side=e.target.closest('[data-reference-side]');if(!side)return;
                e.preventDefault();const token=side.closest('[data-edit-reference]');this.placeByToken(token,side.dataset.referenceSide==='after');
            };
            host.onclick=e=>{const token=e.target.closest('[data-edit-reference]');if(token){this.o.select(token.dataset.editReference);token.focus({preventScroll:true});this.showPreview(token);}};
            host.onfocusin=e=>{const token=e.target.closest('[data-edit-reference]');if(token)this.showPreview(token);};
            host.onpointerover=e=>{const token=e.target.closest('[data-edit-reference]');if(token&&!token.contains(e.relatedTarget))this.showPreview(token);};
            host.onpointerout=e=>{const token=e.target.closest('[data-edit-reference]');if(token&&!token.contains(e.relatedTarget)&&document.activeElement!==token)this.hidePreview();};
            host.oncopy=e=>this.copy(e,false);host.oncut=e=>this.copy(e,true);
            host.onpaste=e=>{e.preventDefault();if(host.contentEditable==='false')return;this.o.remember();this.insert(e.clipboardData.getData('text/plain'));};
            host.ondragstart=e=>{
                const token=e.target.closest('[data-edit-reference]');if(!token)return;if(host.contentEditable==='false'){e.preventDefault();return;}
                this.dragged=token;e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',token.dataset.referenceText);this.o.remember();this.hidePreview();
            };
            host.ondragover=e=>{if(this.dragged){e.preventDefault();e.dataTransfer.dropEffect='move';}};
            host.ondrop=e=>{
                if(!this.dragged)return;e.preventDefault();
                let range;
                const token=e.target.closest('[data-edit-reference]');
                if(token){if(token===this.dragged)return;range=document.createRange();range.setStartBefore(token);range.collapse(true);if(e.clientX>token.getBoundingClientRect().left+token.offsetWidth/2)range.setStartAfter(token);}
                else range=document.caretRangeFromPoint(e.clientX,e.clientY);
                if(!range||!host.contains(range.startContainer))return;
                range.insertNode(this.dragged);range.setStartAfter(this.dragged);range.collapse(true);this.selectRange(range);this.dragged=null;
                this.capture();this.changed();
            };
            host.ondragend=()=>{this.dragged=null;};
            this.refreshThumbnails();
            const surface=host.closest('.layer-smart-prompt');this.resizeObserver=new ResizeObserver(()=>this.scheduleLayout());
            this.resizeObserver.observe(surface);this.resizeObserver.observe(surface.querySelector('footer'));this.updateLayout();
        }
        changed(){this.o.change(serialize(this.host));this.updateLayout();}
        scheduleLayout(){if(!this.layoutFrame)this.layoutFrame=requestAnimationFrame(()=>{this.layoutFrame=0;this.updateLayout();});}
        updateLayout(){
            if(!this.host?.isConnected)return;
            const surface=this.host.closest('.layer-smart-prompt'),actions=surface.querySelector('footer'),style=getComputedStyle(surface),width=actions.offsetWidth;
            const available=surface.clientWidth-parseFloat(style.paddingLeft)-12-width-8;
            const layout=needsMultiline(serialize(this.host),contentWidth(this.host),available)?'multiline':'single-line';
            if(surface.dataset.layout!==layout)surface.dataset.layout=layout;
            if(surface.style.getPropertyValue('--smart-prompt-actions-width')!==width+'px')surface.style.setProperty('--smart-prompt-actions-width',width+'px');
        }
        token(mark){return `<span class="layer-smart-reference" data-edit-reference="${esc(mark.id)}" data-reference-text="${reference(mark)}" contenteditable="false" draggable="true" tabindex="0" role="img" aria-label="${esc(t('editMarker')+' '+mark.number)}"><span class="layer-smart-reference-gap before" data-reference-side="before" aria-hidden="true"></span><span class="layer-smart-reference-image" aria-hidden="true"><img alt="" draggable="false"></span>${pin(mark.number)}<span class="layer-smart-reference-gap after" data-reference-side="after" aria-hidden="true"></span></span>`;}
        refreshThumbnails(){
            if(!this.source)return;
            for(const token of this.host.querySelectorAll('[data-edit-reference]')){
                const mark=this.marks.find(m=>m.id===token.dataset.editReference);if(!mark)continue;
                const crop=thumbnailCrop(mark,this.source),canvas=document.createElement('canvas');canvas.width=canvas.height=32;
                canvas.getContext('2d').drawImage(this.source,crop.x,crop.y,crop.width,crop.height,0,0,32,32);token.querySelector('img').src=canvas.toDataURL('image/png');
            }
        }
        range(){const selection=document.getSelection();if(!selection.rangeCount)return;const range=selection.getRangeAt(0);return this.host.contains(range.commonAncestorContainer)?range:undefined;}
        capture(){
            if(!this.host?.isConnected)return false;
            const range=this.range();if(!range)return false;
            const start=range.cloneRange();start.selectNodeContents(this.host);start.setEnd(range.startContainer,range.startOffset);
            this.caret={start:serialize(start.cloneContents()).length,end:serialize(start.cloneContents()).length+serialize(range.cloneContents()).length};
            return this.host.contains(document.activeElement);
        }
        point(offset){
            let left=offset,found;
            const visit=node=>{
                if(found)return;
                if(node.nodeType===3){const length=node.textContent.length;if(left<=length)found={node,offset:left};else left-=length;return;}
                if(node.nodeName==='BR'){
                    if(node.getAttribute('data-edit-tail')==='true')return;
                    if(left<=1)found={node:node.parentNode,offset:[...node.parentNode.childNodes].indexOf(node)+(left?1:0)};else left--;return;
                }
                if(node.getAttribute?.('data-edit-reference')){
                    const length=serialize(node).length;if(left<length){const parent=node.parentNode,index=[...parent.childNodes].indexOf(node);found={node:parent,offset:index+(left?1:0)};}else left-=length;return;
                }
                for(const child of node.childNodes)visit(child);
            };
            visit(this.host);return found||{node:this.host,offset:this.host.childNodes.length};
        }
        selectRange(range){const selection=document.getSelection();selection.removeAllRanges();selection.addRange(range);}
        restore(focus=false){
            const range=document.createRange(),a=this.point(this.caret.start),b=this.point(this.caret.end);range.setStart(a.node,a.offset);range.setEnd(b.node,b.offset);
            if(focus)this.host.focus({preventScroll:true});this.selectRange(range);
        }
        insert(text){
            const range=this.range();if(range)this.capture();const value=serialize(this.host),{start,end}=this.caret;
            text=text.slice(0,Math.max(0,2000-value.length+end-start));
            const next=value.slice(0,start)+text+value.slice(end),caret=start+text.length;
            this.mount(this.host,this.preview,next,this.marks,this.source);this.caret={start:caret,end:caret};this.restore(true);this.o.change(next);
        }
        insertMarker(mark){this.insert(reference(mark));}
        focusMarker(id){
            const token=[...this.host.querySelectorAll('[data-edit-reference]')].find(el=>el.dataset.editReference===id);
            if(token){token.focus({preventScroll:true});this.showPreview(token);}else{const mark=this.marks.find(m=>m.id===id);if(mark){this.o.remember();this.insertMarker(mark);}}
        }
        placeByToken(token,after){const range=document.createRange();after?range.setStartAfter(token):range.setStartBefore(token);range.collapse(true);this.host.focus({preventScroll:true});this.selectRange(range);this.capture();this.hidePreview();}
        copy(e,cut){
            const range=this.range();if(!range||range.collapsed)return;e.preventDefault();e.clipboardData.setData('text/plain',serialize(range.cloneContents()));
            if(cut&&this.host.contentEditable!=='false'){this.o.remember();range.deleteContents();this.capture();this.changed();this.hidePreview();}
        }
        keydown(e){
            if(this.host.contentEditable==='false')return false;
            const token=e.target.closest('[data-edit-reference]');
            if(token){
                if(['Backspace','Delete'].includes(e.key)){e.preventDefault();e.stopImmediatePropagation();this.o.remember();this.placeByToken(token,false);token.remove();this.capture();this.changed();return true;}
                if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();this.placeByToken(token,e.key==='ArrowRight');return true;}
            }
            if(e.key==='Escape'&&!this.preview.hidden){e.preventDefault();e.stopImmediatePropagation();this.hidePreview();return true;}
            return false;
        }
        showPreview(token){
            const mark=this.marks.find(m=>m.id===token.dataset.editReference);if(!mark||!this.source)return;
            if(this.previewToken===token&&!this.preview.hidden)return;
            clearTimeout(this.zoomTimer);this.preview.classList.add('is-initial');this.preview.hidden=false;this.previewToken=token;this.previewMark=mark;this.zoomed=false;
            const canvas=this.preview.querySelector('canvas');canvas.width=this.source.width;canvas.height=this.source.height;canvas.getContext('2d').drawImage(this.source,0,0);
            this.preview.querySelector('.layer-smart-reference-preview-pin').innerHTML=pin(mark.number,24);this.drawPreview();
            void this.preview.offsetWidth;this.preview.classList.remove('is-initial');
            this.zoomTimer=setTimeout(()=>{if(this.previewToken===token){this.zoomed=true;this.drawPreview();}},500);
        }
        drawPreview(){
            const frame=previewFrame(this.previewMark,this.source,this.zoomed),a=frame.source,b=frame.target;
            const rect=(selector,value)=>Object.assign(this.preview.querySelector(selector).style,Object.fromEntries(Object.entries(value).map(([key,n])=>[key,n+'px'])));
            rect('.layer-smart-reference-preview-window',{left:b.x,top:b.y,width:b.width,height:b.height});
            rect('canvas',{left:-a.x*frame.scale,top:-a.y*frame.scale,width:this.source.width*frame.scale,height:this.source.height*frame.scale});
            const mark=this.previewMark,r=mark.rect,p=r?{x:r.x+r.width,y:r.y+r.height}:mark.points[0],x=b.x+(p.x*this.source.width-a.x)*frame.scale,y=b.y+(p.y*this.source.height-a.y)*frame.scale;
            this.preview.querySelector('.layer-smart-reference-preview-box').hidden=!r;
            if(r)rect('.layer-smart-reference-preview-box',{left:b.x+(r.x*this.source.width-a.x)*frame.scale,top:b.y+(r.y*this.source.height-a.y)*frame.scale,width:r.width*this.source.width*frame.scale,height:r.height*this.source.height*frame.scale});
            Object.assign(this.preview.querySelector('.layer-smart-reference-preview-pin').style,{left:x+'px',top:y+'px'});this.layoutPreview();
        }
        layoutPreview(){if(this.preview?.hidden||!this.previewToken?.isConnected)return;const r=this.previewToken.getBoundingClientRect();Object.assign(this.preview.style,{left:clamp(r.left+r.width/2-160,8,innerWidth-328)+'px',top:Math.max(8,r.top-188)+'px'});}
        hidePreview(){clearTimeout(this.zoomTimer);if(this.preview)this.preview.hidden=true;this.previewToken=null;}
        close(){this.hidePreview();this.resizeObserver?.disconnect();cancelAnimationFrame(this.layoutFrame);this.layoutFrame=0;this.host=null;this.dragged=null;this.caret={start:0,end:0};}
    }
    const api={parts,pin,thumbnailCrop,previewFrame,serialize,needsMultiline,Prompt};root.CanvasLayerSmartPrompt=api;
    if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
