'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const html=fs.readFileSync(path.join(__dirname,'../../static/online.html'),'utf8');
const cards=new Map();
let opened;
const context=vm.createContext({URL,URLSearchParams,location:{href:'http://localhost/static/online.html',origin:'http://localhost'},
 document:{body:{classList:{contains:()=>false}},createElement(){
  const img={},caption={};return {dataset:{},querySelector:selector=>selector==='img'?img:caption};
 }},tr:key=>key,openLightbox:data=>{opened=data;},lucide:{createIcons(){throw Error('per-card icon scan');}}});
vm.runInContext(html.slice(html.indexOf('function historyPreviewUrl('),html.indexOf('const historyRows=[];')),context);
for(let i=0;i<48;i++){
 const row={timestamp:i,images:['/output/large-'+i+'.png','/output/second.png'],prompt:'<img src=x onerror=alert(1)>'};
 const card=context.createHistoryCard(row);cards.set(`history-${row.timestamp}`,card);assert.equal(row.images[0],'/output/large-'+i+'.png');
 const url=new URL(card.querySelector('img').src,'http://localhost');
 assert.equal(url.pathname,'/api/media-preview');assert.equal(url.searchParams.get('w'),'512');
 assert.equal(url.searchParams.get('url'),row.images[0]);assert.equal(card.querySelector('p').textContent,row.prompt);
 assert(!card.innerHTML.includes(row.prompt));card.onclick();assert.equal(opened,row);
}
assert.equal(cards.size,48);
assert.equal(context.historyPreviewUrl('http://localhost/assets/input/a.png?x=1'),'/api/media-preview?w=512&url=%2Fassets%2Finput%2Fa.png%3Fx%3D1');
assert.equal(context.historyPreviewUrl('https://external.invalid/photo.png'),'https://external.invalid/photo.png');
assert.equal(context.historyPreviewUrl('data:image/png;base64,AAAA'),'data:image/png;base64,AAAA');
assert.equal(context.historyPreviewUrl('/output/legacy.svg'),'/output/legacy.svg');
console.log('History thumbnails, original lightbox data, safe captions and no per-card icon scan passed');
