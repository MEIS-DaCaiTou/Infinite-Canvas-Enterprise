/* Test-canvas links follow rendered ports, independently of workflow execution. */
(function(root){
    function curve(a,b){
        const bend = Math.max(45, Math.abs(b.x-a.x)*.5);
        return `M ${a.x} ${a.y} C ${a.x+bend} ${a.y}, ${b.x-bend} ${b.y}, ${b.x} ${b.y}`;
    }
    function mount(world){
        const cards = new Map([...world.querySelectorAll('.mini-card[data-node]')].map(card=>[card.dataset.node,card]));
        function update(){
            const bounds=world.getBoundingClientRect(), scale=bounds.width/world.offsetWidth;
            const point=port=>{const r=port.getBoundingClientRect();return {x:(r.left+r.width/2-bounds.left)/scale,y:(r.top+r.height/2-bounds.top)/scale};};
            for(const path of world.querySelectorAll('[data-mini-from]')){
                const from=cards.get(path.dataset.miniFrom)?.querySelector('.mini-port.out');
                const to=cards.get(path.dataset.miniTo)?.querySelector('.mini-port.in');
                if(from && to && scale>0) path.setAttribute('d',curve(point(from),point(to)));
            }
        }
        const observer=new ResizeObserver(update);
        cards.forEach(card=>observer.observe(card));
        update();
        return {update,dispose:()=>observer.disconnect()};
    }
    root.ComfyPreviewLinks={curve,mount};
})(typeof window==='undefined'?globalThis:window);
