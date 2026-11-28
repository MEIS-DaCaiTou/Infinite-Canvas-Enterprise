import asyncio
from pathlib import Path
import shutil
import subprocess

import httpx

from enterprise.canvas_image_recovery import CanvasImageRecovery, ImageReceiptSink, image_task_timing, public_receipt
from enterprise.providers.submission import httpx_request_with_transient_retries, reported_usage
from enterprise.providers.zhenzhen import image_headers, image_task_endpoint, query_image, image_query_status
from enterprise.tests.test_canvas_image_recovery import PROVIDER, new_journal


def test_canvas_image_recovery_elapsed_time_scripts():
    if not shutil.which('node'):
        import pytest
        pytest.skip('Node is required for canvas timing checks')
    root = Path(__file__).resolve().parents[2]
    for script in ('test_canvas_image_timing.js', 'test_smart_canvas_logs.js'):
        subprocess.run(['node', str(root / 'enterprise/tests' / script)], cwd=root, check=True)


def test_completed_image_timing_ignores_next_day_view_and_reconciliation():
    record = {"id":"original", "type":"online-image", "status":"succeeded", "created_at":1000,
              "updated_at":1000 + 921*60 + 42, "result":{"timestamp":1106, "images":["/output/original.png"]},
              "provider_receipts":[{"state":"succeeded", "finished_at":1106}]}
    assert public_receipt(record)["timing"] == {"started_at":1000, "finished_at":1106, "elapsed_ms":106000}
    record["updated_at"] += 86400
    assert image_task_timing(record)["elapsed_ms"] == 106000
    assert record["result"] == {"timestamp":1106, "images":["/output/original.png"]}


def test_image_timing_preserves_running_and_unknown_legacy_end():
    assert image_task_timing({"created_at":1000, "status":"running", "result":{"timestamp":1005}}) == {"started_at":1000}
    assert image_task_timing({"created_at":1000, "status":"succeeded", "updated_at":90000}) == {"started_at":1000}
    assert image_task_timing({"created_at":1000, "status":"succeeded", "result":{"timestamp":999}}) == {"started_at":1000}
    assert image_task_timing({"status":"succeeded"}) == {}


def test_image_timing_uses_last_saved_child_finish_for_legacy_batch():
    assert image_task_timing({"created_at":1000, "status":"succeeded", "provider_receipts":[
        {"finished_at":1050}, {"finished_at":1106}]}) == {"started_at":1000, "finished_at":1106, "elapsed_ms":106000}


def test_sync_image_retains_oneapi_trace_without_inventing_async_id(tmp_path):
    async def scenario():
        journal = new_journal(tmp_path)
        sink = ImageReceiptSink(journal, 'canvas_img_a', 0)
        sink.identify(httpx.Headers({'X-Oneapi-Request-Id':'EMaster-trace-only'}))
        await sink.generated({'data':[{'url':'https://supplier.example/original.png'}]})
        await sink.completed(['/output/original.png'], [])
        receipt = journal.get('canvas_img_a')['provider_receipts'][0]
        assert receipt['provider_request_id'] == 'EMaster-trace-only'
        assert not receipt.get('upstream_task_id')
        assert receipt['state'] == 'succeeded'
    asyncio.run(scenario())


def test_usage_is_reported_fact_not_estimated_settlement():
    assert reported_usage({'usage':{'total_tokens':17,'api_key':'hidden'},'cost':'0.025'}) == {'total_tokens':17,'reported_cost':'0.025','currency':None}
    assert reported_usage({'data':{'usage':{'input_tokens':3},'cost':0,'currency':'CNY'}})['currency']=='CNY'
    assert reported_usage({'usage':{'input_tokens':-1,'output_tokens':float('nan')},'cost':'NaN'}) == {}
    assert reported_usage({'data':{'status':'SUCCESS','data':{'usage':{'total_tokens':27}}}}) == {'total_tokens':27}


def test_zhenzhen_query_state_does_not_turn_unknown_payload_into_running_or_success():
    assert image_query_status({'data':{'status':'IN_PROGRESS'}},has_images=False)=='running'
    assert image_query_status({'data':{'status':'FAILURE'}},has_images=True)=='failed'
    assert image_query_status({'data':{'status':'SUCCESS'}},has_images=True)=='succeeded'
    assert image_query_status({'data':{'status':'SUCCESS'}},has_images=False)=='manual'
    assert image_query_status({'unexpected':'reply'},has_images=False)=='manual'


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
        async def query(provider,key, *, plan_archive):
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
