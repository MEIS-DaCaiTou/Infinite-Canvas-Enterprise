/* Shared text input and tool color controls. Documents and task hints keep their own data. */
(function(root){
    const colors=[['red','#ff3355'],['yellow','#ffc944'],['green','#66d675'],['blue','#3eadff'],['black','#111111'],['white','#ffffff']];
    const t=key=>root.StudioI18n.t('layers.'+key);
    function palette(color){return `<div class="layer-annotation-options" role="group" aria-label="${t('color')}">${colors.map(([name,value])=>`<button type="button" data-annotation-color="${value}" aria-label="${t('color'+name)}" aria-pressed="${value===color}"><span style="background:${value}"></span></button>`).join('')}</div>`;}
    function textBox(text,fontSize,measure,lineHeight=1.25){
        const lines=String(text||' ').split('\n');
        return {width:Math.max(fontSize,...lines.map(line=>measure(line||' ')))+2,height:Math.max(1,lines.length)*fontSize*lineHeight};
    }
    class TextInput{
        open(container,value,callbacks){
            this.cancel();this.callbacks=callbacks;this.value=value;this.container=container;
            const input=this.input=document.createElement('textarea');input.className='layer-annotation-text';input.dataset.layerAnnotationText='';input.setAttribute('aria-label',t('text'));input.setAttribute('wrap','off');input.maxLength=100;input.value=value.text;
            input.style.color=value.color;input.style.fontFamily=value.fontFamily||'sans-serif';input.style.fontWeight=String(value.fontWeight||600);input.style.lineHeight=String(value.lineHeight||1.25);container.append(input);this.layout();
            input.oninput=()=>{this.layout();callbacks.change?.(input.value,this.bounds);};
            input.onblur=()=>this.commit('blur');input.onpointerdown=input.ondblclick=e=>e.stopPropagation();
            input.onkeydown=e=>{e.stopPropagation();if(e.isComposing)return;if(e.key==='Escape'){e.preventDefault();this.cancel();}else if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();this.commit();}};
            input.focus();if(value.text)input.select();
        }
        layout(){
            if(!this.input)return;const {input,value,container}=this,width=container.clientWidth,font=value.fontSize*width;
            input.style.fontSize=font+'px';input.style.left=value.x*100+'%';input.style.top=value.y*100+'%';
            const ctx=document.createElement('canvas').getContext('2d');ctx.font=`${value.fontWeight||600} ${font}px ${value.fontFamily||'sans-serif'}`;
            const box=textBox(input.value,font,text=>ctx.measureText(text).width,value.lineHeight||1.25);this.bounds={width:box.width/width,height:box.height/container.clientHeight};
            input.style.width=box.width+'px';input.style.height=box.height+'px';
        }
        finish(cancel,reason){
            const input=this.input;if(!input)return;const callback=this.callbacks,box=this.bounds,text=input.value;
            this.input=null;input.onblur=null;input.remove();if(cancel)callback.cancel?.();else callback.commit(text,box,reason);
        }
        commit(reason='confirm'){this.finish(false,reason);}
        cancel(){this.finish(true);}
    }
    function markBox(mark){
        const font=mark.fontSize||.04,lines=String(mark.text).split('\n');
        return {x:mark.points[0].x,y:mark.points[0].y,width:mark.box?.width||Math.max(font,...lines.map(line=>line.length*font*.65)),height:mark.box?.height||lines.length*font*1.25};
    }
    function moveText(mark,start,dx,dy){mark.points=[{x:start.points[0].x+dx,y:start.points[0].y+dy}];}
    function resizeText(mark,start,corner,dx,dy){
        const box=markBox(start),ratio=Math.max(.1,1+(corner.includes('w')?-dx:dx)/Math.max(box.width,.001));
        const width=box.width*ratio,height=box.height*ratio;
        mark.fontSize=(start.fontSize||.04)*ratio;mark.box={width,height};mark.points=[{x:box.x+(corner.includes('w')?box.width-width:0),y:box.y+(corner.includes('n')?box.height-height:0)}];
    }
    const api={colors,palette,textBox,TextInput,markBox,moveText,resizeText};root.CanvasLayerAnnotations=api;
    if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
