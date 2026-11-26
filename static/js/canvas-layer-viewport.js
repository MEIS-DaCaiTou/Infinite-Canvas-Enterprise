/* Fullscreen viewport math follows the inspected layer-board viewport commands. */
(function(root){
    const limit=(zoom,minimum=.25)=>Math.min(4,Math.max(minimum,zoom));
    function fit(stage,rect,margin=20){
        const zoom=Math.min(4,Math.max(1,stage.width-104)/Math.max(1,rect.width),Math.max(1,stage.height-margin*2)/Math.max(1,rect.height));
        return {x:stage.width/2-(rect.x+rect.width/2)*zoom,y:stage.height/2-(rect.y+rect.height/2)*zoom,zoom};
    }
    function zoomAt(view,zoom,point,minimum=.25){
        zoom=limit(zoom,minimum);const ratio=zoom/view.zoom;
        return {x:point.x-(point.x-view.x)*ratio,y:point.y-(point.y-view.y)*ratio,zoom};
    }
    function wheel(view,event,point,minimum=.25){
        return event.ctrlKey||event.metaKey?zoomAt(view,view.zoom*Math.exp(-event.deltaY*.01),point,minimum):
            {...view,x:view.x-event.deltaX,y:view.y-event.deltaY};
    }
    function keyAction(event){
        if(event.altKey)return '';
        const mod=event.ctrlKey||event.metaKey,key=event.key;
        if(mod&&['=','+'].includes(key))return 'zoom-in';
        if(mod&&!event.shiftKey&&key==='-')return 'zoom-out';
        if(mod&&!event.shiftKey&&key==='0'||!mod&&event.shiftKey&&event.code==='Digit1')return 'zoom-fit';
        if(mod&&!event.shiftKey&&key==='1')return 'zoom-100';
        if(!mod&&event.shiftKey&&event.code==='Digit2')return 'zoom-selection';
        return '';
    }
    const api={limit,fit,zoomAt,wheel,keyAction};root.CanvasLayerViewport=api;
    if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
