// Flush existing editor persistence before its explicit return-to-directory action.
// Storage format, conflict handling and user-facing feedback remain in each editor.
(function(root){
    let leaving = false;
    async function leave(options){
        if(leaving) return false;
        leaving = true;
        try {
            options.cancelDebounce();
            while(options.isSaving()) await new Promise(resolve => setTimeout(resolve, 20));
            if(await options.save() !== true || options.hasPending()){
                options.failed();
                return false;
            }
            options.navigate();
            return true;
        } finally {
            leaving = false;
        }
    }
    root.CanvasSaveNavigation = {leave};
})(window);
