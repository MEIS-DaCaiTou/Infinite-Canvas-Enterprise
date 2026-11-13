const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const calls = [];
let reply = {status: 'succeeded', images: ['/output/original.png']};
const context = {window: {}, crypto:require('node:crypto').webcrypto, fetch: async (url, options) => {
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

    const image = context.window.CanvasTaskQuery;
    const requests = Array.from({length:4}, () => image.imageRequest({prompt:'fixture', n:4}));
    const ids = requests.map(request => request.taskId);
    assert.equal(new Set(ids).size, 4);
    const imageCalls = [];
    const fake = async (url, init={}) => {
        imageCalls.push({url, init});
        const answer = (status, body) => ({ok:status===200, status, json:async()=>body});
        if(init.method === 'POST'){
            const sent = JSON.parse(init.body);
            assert.equal(sent.n, 1);
            const task_id = 'canvas_img_' + sent.request_id;
            if(task_id === ids[3]) throw new Error('reply lost after platform receipt was committed');
            return answer(200, {task_id, status:'queued'});
        }
        assert.equal(url, '/api/canvas-image-tasks/' + ids[3]);
        return answer(200, {status:'running', submission_status:'accepted'});
    };
    const receipts = await Promise.all(requests.map(request => image.submitImage(request, {fetcher:fake})));
    assert.equal(image.imageStatus(receipts[0]), '平台任务已创建');
    assert.equal(image.imageStatus(receipts[3]), '供应商已受理');
    assert.equal(imageCalls.filter(call => call.init.method === 'POST').length, 4);
    assert.equal(imageCalls.length, 5);

    let rejectedReads = 0;
    await assert.rejects(image.submitImage(requests[0], {fetcher:async (_, init) => {
        if(init.method !== 'POST') rejectedReads++;
        return {ok:false, status:429, json:async()=>({detail:'fixture rate limit'})};
    }}), error => error.definiteRejection && error.message === 'fixture rate limit');
    assert.equal(rejectedReads, 0);

    const unknownCalls = [];
    await assert.rejects(image.submitImage(requests[1], {wait:async()=>{}, fetcher:async (url, init) => {
        unknownCalls.push([url, init.method]);
        return {ok:false, status:init.method === 'POST' ? 503 : 404, json:async()=>({})};
    }}), error => error.imageTrackingUnknown);
    assert.equal(unknownCalls.filter(([, method]) => method === 'POST').length, 1);
    assert(unknownCalls.slice(1).every(([url]) => url.endsWith(ids[1])));
    assert.equal(image.imageStatus({status:'failed', submission_status:'unknown'}), '供应商受理结果待核对');
    assert.equal(image.imageStatus({status:'failed', submission_status:'failed'}), '明确失败');
    const partial = {status:'partial', submission_status:'unknown', result:{images:['/output/retained.png']}};
    const states = [{status:'running'}, partial];
    const final = await image.waitImage(ids[0], {wait:async()=>{}, fetcher:async (url, init={}) => {
        assert.equal(url, '/api/canvas-image-tasks/' + ids[0]);
        assert.notEqual(init.method, 'POST');
        return {ok:true, json:async()=>states.shift()};
    }});
    assert.equal(image.imageStatus(final), '部分完成');
    assert.deepEqual(final.result.images, ['/output/retained.png']);
    console.log('shared canvas original-task query passed');
})();
