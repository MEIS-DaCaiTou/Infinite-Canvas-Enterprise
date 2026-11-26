/* Result placement uses its final display dimensions, before image loading. */
(function(root){
    function freeRect(candidate,occupied,gap=160){
        const result={...candidate}, {width,height}=result;
        let collision;
        do{
            collision=occupied.find(r=>result.x<r.x+r.width+gap/2 && result.x+width+gap/2>r.x && result.y<r.y+r.height+100 && result.y+height+100>r.y);
            if(collision)result.y=collision.y+collision.height+100;
        }while(collision);
        return result;
    }
    function resultRect(source,document,occupied,gap=160){
        const width=source.width,height=Math.round(width*document.height/document.width);
        return freeRect({x:source.x+source.width+gap,y:source.y,width,height},occupied,gap);
    }
    function frame(source,result,viewport){
        const left=Math.min(source.x,result.x),right=Math.max(source.x+source.width,result.x+result.width),top=Math.min(source.y,result.y),bottom=Math.max(source.y+source.height,result.y+result.height);
        return {x:(left+right)/2,y:(top+bottom)/2,scale:Math.min(viewport.scale,(viewport.width-100)/(right-left+80),(viewport.height-220)/(bottom-top+80))};
    }
    const api={freeRect,resultRect,frame};root.CanvasLayerLayout=api;if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
