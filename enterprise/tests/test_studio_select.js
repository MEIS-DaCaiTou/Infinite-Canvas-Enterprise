const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {placeMenu} = require('../../static/js/studio-select.js');

const viewport = {width:909,height:704};
for (const scale of [.68,.8,1,1.4]) {
  const rect = {left:200*scale,top:180*scale,bottom:214*scale};
  const result = placeMenu(rect,{width:220,height:260},viewport);
  assert.equal(result.left,rect.left);
  assert.equal(result.top,rect.bottom+6,`scaled control ${scale} stays anchored`);
  assert.equal(result.height,260);
}
const edge = placeMenu({left:845,top:650,bottom:684},{width:320,height:260},viewport);
assert.equal(edge.left+edge.width,viewport.width-8);
assert.equal(edge.top+edge.height,650-6);
assert(edge.top>=8);
const long = placeMenu({left:260,top:100,bottom:134},{width:1200,height:900},{width:390,height:844});
assert.equal(long.width,374);
assert.equal(long.left,8);
assert.equal(long.top+long.height,836);

const root=path.resolve(__dirname,'../..');
for (const directory of ['static','enterprise-static']) {
  for (const file of fs.readdirSync(path.join(root,directory)).filter(name=>name.endsWith('.html'))) {
    const html=fs.readFileSync(path.join(root,directory,file),'utf8');
    assert(html.includes('/static/js/studio-select.js'),`${directory}/${file} must support runtime-created selects`);
    assert(html.includes('/static/css/studio-select.css'),`${directory}/${file} must share menu presentation`);
  }
}
console.log('Scaled anchors, viewport edges, long menus and all HTML entry points passed');
