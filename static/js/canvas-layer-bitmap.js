/* Connected background selection preserves white details enclosed by a logo. */
(function(root){
    function region(data,width,height,x,y,tolerance=32){
        const start=Math.max(0,Math.min(height-1,Math.round(y)))*width+Math.max(0,Math.min(width-1,Math.round(x)));
        const result=new Uint8Array(width*height),seen=new Uint8Array(width*height),queue=new Int32Array(width*height);
        const color=[data[start*4],data[start*4+1],data[start*4+2]];let head=0,tail=1;queue[0]=start;seen[start]=1;
        while(head<tail){const p=queue[head++],i=p*4;
            if(Math.max(Math.abs(data[i]-color[0]),Math.abs(data[i+1]-color[1]),Math.abs(data[i+2]-color[2]))>tolerance)continue;
            result[p]=255;const px=p%width;
            for(const n of [px?p-1:-1,px<width-1?p+1:-1,p>=width?p-width:-1,p<width*(height-1)?p+width:-1])if(n>=0 && !seen[n]){seen[n]=1;queue[tail++]=n;}
        }
        return result;
    }
    function foreground(data,width,height,tolerance=32){
        const mask=new Uint8Array(width*height);mask.fill(255);
        for(const [x,y] of [[0,0],[width-1,0],[0,height-1],[width-1,height-1]]){
            const background=region(data,width,height,x,y,tolerance);for(let i=0;i<mask.length;i++)if(background[i])mask[i]=0;
        }
        return mask;
    }
    function apply(data,mask){const output=new Uint8ClampedArray(data);for(let i=0;i<mask.length;i++)output[i*4+3]=Math.round(output[i*4+3]*mask[i]/255);return output;}
    const api={region,foreground,apply};root.CanvasLayerBitmap=api;if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
