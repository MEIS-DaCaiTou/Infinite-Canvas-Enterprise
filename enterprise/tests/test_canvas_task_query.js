const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const calls = [];
let reply = {status: 'succeeded', images: ['/output/original.png']};
const context = {window: {}, fetch: async (url, options) => {
    calls.push({url, options});
    return {ok: true, json: async () => reply};
}};
vm.runInNewContext(fs.readFileSync('static/js/canvas-task-query.js', 'utf8'), context);
(async () => {
    const result = await context.window.CanvasTaskQuery.query({canvasTaskId:'canvas_img_original', canReconcile:true,
        providerId:'ignored-provider', upstreamTaskId:'ignored-body-id'});
    assert.equal(result.status, 'succeeded');
    assert.equal(calls[0].url, '/api/canvas-image-tasks/canvas_img_original/reconcile');
    assert.equal(calls[0].options.body, '{}');
    reply = {status:'partial', images:['/output/retained.png'], message:'remaining request unknown'};
    assert.equal((await context.window.CanvasTaskQuery.query({canvasTaskId:'old', providerId:'legacy', upstreamTaskId:'original'})).status, 'partial');
    assert.equal(calls[1].url, '/api/image-task-query');
    assert.deepEqual(JSON.parse(calls[1].options.body), {provider_id:'legacy', task_id:'original'});
    context.fetch = async () => ({ok:false, text:async () => '{"detail":"provider binding changed"}'});
    await assert.rejects(context.window.CanvasTaskQuery.query({canvasTaskId:'original', canReconcile:true}), /provider binding changed/);
    assert(calls.every(call => !/generat|submit/.test(call.url)));
    console.log('shared canvas original-task query passed');
})();
