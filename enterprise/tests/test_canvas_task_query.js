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
    const videoCalls = [];
    let state = ['queued','running','succeeded'];
    const fetcher = async (url, options={}) => {
        videoCalls.push({url,options});
        return {ok:true, json:async () => options.method === 'POST' ? {task_id:'local-video'} :
            {status:state.shift(),result:{videos:['/output/recovered.mp4']}}};
    };
    const video = await context.window.CanvasTaskQuery.runVideo({request_id:'fixture-nonce',prompt:'fixture'},
        {fetcher,wait:async () => {},maxPolls:4});
    assert.equal(video.videos[0],'/output/recovered.mp4');
    assert.equal(videoCalls.filter(call=>call.options.method==='POST').length,1);
    assert.equal(JSON.parse(videoCalls[0].options.body).request_id,'fixture-nonce');
    assert(videoCalls.slice(1).every(call=>call.url==='/api/canvas-video-tasks/local-video'));
    state=['failed'];
    await assert.rejects(context.window.CanvasTaskQuery.runVideo({request_id:'fixture-nonce'},
        {fetcher,wait:async()=>{},maxPolls:2}), /生成任务.*local-video/);
    console.log('shared canvas original-task query passed');
})();
