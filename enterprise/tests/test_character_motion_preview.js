const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const warnings = [];
let observing = 0;
class Element {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {};
    const classes = new Set();
    this.classList = { add: (...names) => names.forEach(n => classes.add(n)),
      remove: (...names) => names.forEach(n => classes.delete(n)), contains: name => classes.has(name) };
  }
  append(node) { this.children.push(node); }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener() {}
  remove() { this.removed = true; }
}
const documentElement = { matches: () => true };
const context = { window: { addEventListener() {} }, AbortController,
  document: { documentElement, createElement: tag => new Element(tag) },
  matchMedia: () => ({ matches: false }), console: { warn: (...args) => warnings.push(args) },
  MutationObserver: class {
    observe(node) { assert.equal(node, documentElement); observing++; }
    disconnect() { observing--; }
  },
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../static/js/character-motion-preview.js'), 'utf8'), context);
const Preview = context.window.CharacterMotionPreview;
const flush = () => new Promise(resolve => setImmediate(resolve));
const renderer = () => ({ phases: [], themes: [], disposed: 0,
  setPhase(value) { this.phases.push(value); }, setTheme(value) { this.themes.push(value); },
  dispose() { this.disposed++; },
});
(async () => {
  // Dev-only files and the old catalog flag must not select a different body.
  for (const referenceAssets of [true, false]) {
    Preview.referenceAssets = referenceAssets;
    const host = new Element('div'), result = renderer();
    let options;
    const preview = new Preview(host, 'library', async () => ({
      createCharacterGenerationRenderer: async (_, value) => { options = value; return result; },
    }));
    assert.equal(host.children[0].children[0].tagName, 'span');
    assert.equal(host.children[0].children[0].textContent, '正在加载人体预览…');
    await flush();
    assert(host.classList.contains('has-motion-preview'));
    assert.deepEqual(result.phases, ['library']);
    assert.deepEqual(result.themes, ['dark']);
    preview.setPhase('loading');
    assert.deepEqual(result.phases, ['library', 'loading']);
    options.onUnavailable();
    assert(!host.classList.contains('has-motion-preview'));
    assert.equal(host.children[0].children[0].textContent, '人体预览暂不可用');
    preview.destroy(); preview.destroy();
    assert.equal(result.disposed, 1);
    assert.equal(options.signal.aborted, true);
    assert(host.children.every(node => node.removed));
    assert(!host.classList.contains('has-static-preview'));
  }
  // Close during model loading: a late renderer must be disposed, never mounted.
  let resolve;
  const late = renderer(), host = new Element('div');
  const preview = new Preview(host, 'pending', async () => ({
    createCharacterGenerationRenderer: () => new Promise(done => { resolve = done; }),
  }));
  await flush(); preview.destroy(); resolve(late); await flush();
  assert.equal(late.disposed, 1);
  assert(!host.classList.contains('has-motion-preview'));
  // A missing/disabled GPU reports failure instead of substituting a different human.
  const failedHost = new Element('div');
  const failed = new Preview(failedHost, 'library', async () => { throw new Error('GPU disabled'); });
  await flush();
  assert(failedHost.classList.contains('has-static-preview'));
  assert(failedHost.classList.contains('motion-preview-unavailable'));
  assert.equal(failedHost.children[0].children[0].textContent, '人体预览暂不可用');
  assert.equal(warnings.length, 1);
  failed.destroy();
  assert.equal(observing, 0, 'all theme observers released');
  console.log('Bundled original preview, explicit failure, theme/phase, late-load and repeated disposal passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
