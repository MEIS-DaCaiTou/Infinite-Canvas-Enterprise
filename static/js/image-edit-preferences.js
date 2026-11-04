/* Browser-local brush sizes shared by the two image editors; no canvas data is stored here. */
(function(root){
    'use strict';
    function bindBrushSizes(doc=root.document){
        ['paintBrushSize','maskBrushSize'].forEach(id=>{
            const control=doc.getElementById(id);
            if(!control)return;
            const key=`canvas_${id}`;
            try{
                const stored=root.localStorage.getItem(key),value=Number(stored);
                if(stored!==null && Number.isFinite(value))control.value=String(Math.max(Number(control.min),Math.min(Number(control.max),value)));
            }catch(_){} // Storage restrictions must not block drawing.
            control.addEventListener('input',()=>{
                try{root.localStorage.setItem(key,control.value);}catch(_){}
            });
        });
    }
    root.ImageEditPreferences={bindBrushSizes};
})(window);
