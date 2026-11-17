/* Studio keeps inactive same-origin frames mounted. The browser's visibility
   state alone cannot tell whether the canvas is the selected module. */
(function(root){
    function isVisible(){
        return !root.document.hidden && !root.frameElement?.matches('#frame-canvas:not(.active)');
    }
    root.CanvasViewActivity = {isVisible};
})(window);
