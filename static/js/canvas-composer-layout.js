/* Screen-space node anchoring follows the inspected Jimeng node-toolbar geometry. */
(function(root){
    function position(rect,viewport,availableWidth){
        return {
            x:viewport.x+(rect.x+rect.width/2)*viewport.scale,
            y:viewport.y+(rect.y+rect.height)*viewport.scale+20,
            width:Math.min(680,availableWidth-48),
        };
    }
    const api={position};
    root.CanvasComposerLayout=api;
    if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
