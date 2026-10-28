const assert=require('node:assert/strict');
const {clamp,alpha,resist,fling,ease}=require('../../static/js/character-carousel.js');
// Snapping and inertial movement must stay bounded, including a single result.
assert.equal(clamp(-2,4),0);assert.equal(clamp(10,4),3);
assert.equal(fling(1,-1,4),2);assert.equal(fling(0,5,4),0);assert.equal(fling(0,-5,1),0);
assert.equal(fling(1,.1,4),1);assert.ok(resist(-1,4)>-1);assert.ok(resist(5,4)<5);
// The recovered focus fade is continuous; neighbors stop fading at 20%.
assert.equal(alpha(0),1);assert.equal(alpha(1),.2);assert.equal(alpha(5),.2);assert.ok(alpha(.5)>.2&&alpha(.5)<1);
// The unusual original cubic curve must remain finite and monotonic.
let previous=0;
for(let i=0;i<=100;i++){const value=ease(i/100);assert.ok(Number.isFinite(value)&&value>=previous-1e-9&&value<=1);previous=value;}
assert.equal(ease(0),0);assert.equal(ease(1),1);
console.log('Recovered carousel bounds, fling direction, focus fade and easing passed.');
