/* Viewport-only media cards. No fetching, permissions, selection or persistence. */
(function(root){
    'use strict';
    function range(count,columns,height,gap,top,viewport,overscan=2){
        columns=Math.max(1,Math.floor(columns));
        const rows=Math.ceil(count/columns),stride=height+gap;
        if(!rows)return{start:0,end:0,before:0,after:0};
        const first=Math.min(rows-1,Math.max(0,Math.floor(Math.max(0,top)/stride)-overscan));
        const last=Math.max(first+1,Math.min(rows,Math.ceil((Math.max(0,top)+Math.max(1,viewport))/stride)+overscan));
        return{start:first*columns,end:Math.min(count,last*columns),
            before:first?first*stride-gap:0,after:last<rows?(rows-last)*stride-gap:0};
    }
    class MediaGridWindow{
        constructor(element,options){
            this.element=element;this.options=options;this.items=[];this.cards=new Map();
            element.style.overflowAnchor='none';
            this.height=options.height;this.columns=options.columns;this.footer=null;this.empty=null;
            this.before=this.spacer();this.after=this.spacer();
            element.append(this.before,this.after);
            this.scroller=options.scrollElement||element;
            this.scroll=()=>this.schedule();this.scroller.addEventListener('scroll',this.scroll,{passive:true});
            this.resize=new ResizeObserver(()=>this.schedule());this.resize.observe(element);
        }
        spacer(){
            const node=document.createElement('div');node.className='media-grid-spacer';
            node.setAttribute('aria-hidden','true');node.style.gridColumn='1 / -1';node.hidden=true;return node;
        }
        schedule(){
            if(!this.frame && !this.destroyed)this.frame=requestAnimationFrame(()=>{this.frame=null;this.paint();});
        }
        setItems(items,{reset=false,footer=null,empty=null}={}){
            if(this.footer!==footer)this.footer?.remove();
            if(this.empty!==empty)this.empty?.remove();
            this.items=items;this.footer=footer;this.empty=empty;
            if(reset)this.element.scrollTop=0;
            this.paint();
        }
        paint(){
            if(this.destroyed)return;
            const element=this.element,style=getComputedStyle(element);
            const tracks=style.gridTemplateColumns.trim().split(/\s+/);
            this.columns=tracks.every(track=>/^\d+(?:\.\d+)?px$/.test(track))?tracks.length:this.options.columns;
            this.gap=parseFloat(style.rowGap)||0;
            const rect=this.scroller===element?null:element.getBoundingClientRect();
            const scale=rect?rect.width/Math.max(1,element.clientWidth):1;
            const top=rect?Math.max(0,-rect.top/scale):element.scrollTop;
            const viewport=rect?this.scroller.innerHeight/scale:element.clientHeight;
            const window=range(this.items.length,this.columns,this.height,this.gap,top,viewport);
            this.before.hidden=!window.before;this.before.style.height=window.before+'px';
            this.after.hidden=!window.after;this.after.style.height=window.after+'px';
            const retained=new Map();let position=this.before.nextSibling;
            for(let i=window.start;i<window.end;i++){
                const item=this.items[i],key=this.options.key(item,i);
                const card=this.cards.get(key)||this.options.create(item,i);
                this.options.update?.(card,item,i);
                if(card!==position)element.insertBefore(card,position);
                position=card.nextSibling;retained.set(key,card);
            }
            for(const [key,card] of this.cards)if(!retained.has(key)){
                this.options.release?.(card);card.remove();
            }
            this.cards=retained;
            // Spacers preserve the loaded list's scroll extent; controls remain
            // after that extent instead of fetching pages on scroll.
            element.append(this.after);
            if(this.empty && !this.items.length)element.append(this.empty);
            if(this.footer)element.append(this.footer);
            const first=retained.values().next().value;
            if(first?.offsetHeight && this.height!==first.offsetHeight){
                this.height=first.offsetHeight;this.schedule();
            }
        }
        reveal(index){
            const top=Math.floor(index/this.columns)*(this.height+this.gap);
            if(top<this.element.scrollTop)this.element.scrollTop=top;
            else if(top+this.height>this.element.scrollTop+this.element.clientHeight)
                this.element.scrollTop=top+this.height-this.element.clientHeight;
            this.paint();return this.cards.get(this.options.key(this.items[index],index));
        }
        clear(){this.setItems([],{reset:true});}
        dispose(){
            this.clear();this.destroyed=true;cancelAnimationFrame(this.frame);
            this.resize.disconnect();this.scroller.removeEventListener('scroll',this.scroll);
            this.before.remove();this.after.remove();
        }
    }
    root.MediaGridWindow=MediaGridWindow;
    if(typeof module!=='undefined')module.exports={range};
})(typeof window==='undefined'?globalThis:window);
