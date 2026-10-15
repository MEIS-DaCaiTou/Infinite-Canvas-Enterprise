import asyncio

import httpx

from enterprise.canvas_image_recovery import CanvasImageRecovery, ImageReceiptSink
from enterprise.providers.submission import httpx_request_with_transient_retries, reported_usage
from enterprise.providers.zhenzhen import image_headers, image_task_endpoint, query_image
from enterprise.tests.test_canvas_image_recovery import PROVIDER, new_journal


def test_usage_is_reported_fact_not_estimated_settlement():
    assert reported_usage({'usage':{'total_tokens':17,'api_key':'hidden'},'cost':'0.025'}) == {'total_tokens':17,'reported_cost':'0.025','currency':None}
    assert reported_usage({'data':{'usage':{'input_tokens':3},'cost':0,'currency':'CNY'}})['currency']=='CNY'
    assert reported_usage({'usage':{'input_tokens':-1,'output_tokens':float('nan')},'cost':'NaN'}) == {}


def test_submission_fact_and_local_archive_error_stay_unknown(tmp_path):
    async def scenario():
        journal=new_journal(tmp_path)
        sink=ImageReceiptSink(journal,'canvas_img_a',0)
        await sink.started(PROVIDER,'fixture-model')
        assert journal.get('canvas_img_a')['provider_receipts'][0]['state']=='submitting'
        await sink.accepted('original-paid-id',PROVIDER)
        await sink.generated({'usage':{'total_tokens':17},'cost':'0.025'})
        await sink.interrupted(OSError('local disk unavailable'))
        receipt=journal.get('canvas_img_a')['provider_receipts'][0]
        assert receipt['state']=='unknown' and receipt['upstream_task_id']=='original-paid-id'
        assert receipt['reported_usage']['total_tokens']==17
        journal.recover()
        queries=[]
        async def query(provider,key):
            queries.append(key)
            return {'status':'succeeded','images':['/output/restored.png'],'raw':{}}
        result=await CanvasImageRecovery(journal,lambda _:PROVIDER,query,lambda _:None).reconcile('canvas_img_a')
        assert result['status']=='succeeded' and queries==['original-paid-id']
        record=journal.get('canvas_img_a')
        assert record['provider_receipts'][0]['reported_usage']['total_tokens']==17
        assert record['reconciliation']['count']==1 and record['reconciliation']['status']=='succeeded'
    asyncio.run(scenario())


def test_zhenzhen_original_query_retries_get_only_and_preserves_protocol():
    calls=[]
    def handler(request):
        calls.append((request.method,request.url.path))
        assert request.headers['authorization']=='Bearer fixture-only'
        return httpx.Response(503 if len(calls)==1 else 200,json={'status':'SUCCESS','task_id':'original'})
    async def request(client,method,url,**kwargs):
        return await httpx_request_with_transient_retries(client,method,url,retry_delay=0,**kwargs)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            raw=await query_image(client,image_task_endpoint('https://supplier.invalid/v1','original'),image_headers('Bearer fixture-only'),request)
            assert raw['task_id']=='original'
    asyncio.run(scenario())
    assert calls==[('GET','/v1/images/tasks/original')]*2
    assert image_task_endpoint('https://supplier.invalid/prefix/','a/b').endswith('/prefix/v1/images/tasks/a%2Fb')
