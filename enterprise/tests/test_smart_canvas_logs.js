const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const sourcePath = path.resolve(__dirname, '..', '..', 'static', 'js', 'smart-canvas.js');
const source = fs.readFileSync(sourcePath, 'utf8');

function extractFunction(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `missing ${name}`);
  const paramsStart = source.indexOf('(', start);
  let paramsDepth = 0;
  let bodyStart = -1;
  for (let index = paramsStart; index < source.length; index += 1) {
    if (source[index] === '(') paramsDepth += 1;
    if (source[index] === ')' && --paramsDepth === 0) {
      bodyStart = source.indexOf('{', index + 1);
      break;
    }
  }
  assert.notEqual(bodyStart, -1, `missing ${name} body`);
  let depth = 0;
  for (let index = bodyStart; index < source.length; index += 1) {
    if (source[index] === '{') depth += 1;
    if (source[index] === '}' && --depth === 0) return source.slice(start, index + 1);
  }
  throw new Error(`unterminated ${name}`);
}

const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(`${extractFunction('smartGenerationLogKey')}\n${extractFunction('normalizeSmartGenerationLogs')}\n${extractFunction('mergeSmartGenerationLogs')}`, sandbox);

assert.deepEqual(
  JSON.parse(JSON.stringify(sandbox.normalizeSmartGenerationLogs({ createdAt: 1, outputs: ['/assets/output/old.png'] }))),
  [{ createdAt: 1, outputs: ['/assets/output/old.png'] }],
  'a legacy single-object log must become one list entry',
);
assert.deepEqual(JSON.parse(JSON.stringify(sandbox.normalizeSmartGenerationLogs(null))), [], 'null logs must become an empty list');
assert.equal(sandbox.normalizeSmartGenerationLogs({ items: [{ id: 'legacy' }] }).length, 1, 'legacy items list must be preserved');
assert.deepEqual(
  JSON.parse(JSON.stringify(sandbox.mergeSmartGenerationLogs([{ id: 'local', createdAt: 2 }], [{ id: 'remote', createdAt: 1 }, { id: 'local', createdAt: 2 }]))).map(entry => entry.id),
  ['local', 'remote'],
  'conflict merge must preserve both distinct log entries without duplicates',
);
assert.equal(
  sandbox.normalizeSmartGenerationLogs([
    { id: 'normal-path', status: 'success', nodeId: 'node-1', prompt: 'same', outputs: ['/assets/output/same.png'] },
    { id: 'recovery-path', status: 'success', nodeId: 'node-1', prompt: 'same', outputs: ['/assets/output/same.png'] },
  ]).length,
  1,
  'normal and recovery completion paths must not duplicate the same successful output log',
);

const pendingSandbox = {
  Set,
  Math,
  nowMs: () => 2000,
  settings: {},
  cloneSmartSettings: value => ({ ...(value || {}) }),
  smartPendingTasks: node => Array.isArray(node?.pendingTasks) ? node.pendingTasks.filter(task => task?.taskId) : [],
  resultMediaUrls: value => Array.isArray(value) ? value : (value ? [value] : []),
  nonPreviewOutputImages: value => Array.isArray(value) ? value : [],
  stripImageGenerationMeta: item => item,
  copyMediaSizeFields: (item, target) => ({ ...target, ...(item || {}) }),
  mediaNodeDefaultScale: () => 1,
  MEDIA_NODE_DEFAULT_SCALE: 1,
  MEDIA_GROUP_PREVIOUS_DEFAULT_SCALE: 1,
  MEDIA_GROUP_DEFAULT_SCALE: 1,
  logged: [],
  addSmartGenerationLog: entry => pendingSandbox.logged.push(entry),
};
vm.createContext(pendingSandbox);
vm.runInContext([
  extractFunction('startSmartPendingGenerationLog'),
  extractFunction('pendingSmartGenerationLog'),
  extractFunction('clearSmartPendingGenerationLog'),
  extractFunction('recordSmartPendingGenerationLog'),
  extractFunction('finalizeSmartPendingTask'),
].join('\n'), pendingSandbox);

const pendingNode = {
  id: 'legacy-node',
  type: 'smart-image',
  images: [],
  pending: 2,
  pendingTasks: [{ taskId: 'task-1' }, { taskId: 'task-2' }],
  runSettings: {},
  runStartedAt: 1000,
};
pendingSandbox.startSmartPendingGenerationLog(pendingNode, { nodeId: 'legacy-node', kind: 'image' }, 1000);
pendingSandbox.finalizeSmartPendingTask(pendingNode, 'task-1', [{ url: '/assets/output/one.png' }]);
pendingSandbox.finalizeSmartPendingTask(pendingNode, 'task-2', [{ url: '/assets/output/two.png' }]);
assert.equal(pendingSandbox.logged.length, 1, 'completed multi-task recovery must write one log entry');
assert.deepEqual(
  JSON.parse(JSON.stringify(pendingSandbox.logged[0].outputs)),
  ['/assets/output/one.png', '/assets/output/two.png'],
  'completed multi-task recovery must retain every output URL',
);
assert.equal(pendingNode.pendingGenerationLog, undefined, 'completed recovery must clear its transient log state');

for (const expected of [
  'canvas.logs = normalizeSmartGenerationLogs(canvas.logs);',
  'logs:normalizeSmartGenerationLogs(storageCanvas.logs)',
  'canvas.logs = mergeSmartGenerationLogs(canvas.logs, serverCanvas.logs);',
  'startSmartPendingGenerationLog(outputSlot, runLog, runLogStart);',
  'startSmartPendingGenerationLog(pendingNode, runLog, runLogStart);',
  'recordSmartPendingGenerationLog(node, additions, kind);',
  'const logState = pendingSmartGenerationLog(node, kind);',
  'await resumeSmartPendingNode(pendingNode, {recordLog:false});',
]) {
  assert.ok(source.includes(expected), `missing regression hook: ${expected}`);
}

console.log('smart canvas log compatibility checks passed');
