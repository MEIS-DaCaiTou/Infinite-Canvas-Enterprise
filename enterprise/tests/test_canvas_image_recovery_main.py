"""Actual main hooks survive a hard exit immediately after supplier acceptance."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = r'''
import asyncio, json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from enterprise.paths import PortableRootInputs, derive_portable_path_roots, install_path_roots_for_process, prepare_application_directories
roots = derive_portable_path_roots(PortableRootInputs(Path(sys.argv[2]), Path(sys.argv[3])), 'fixture')
install_path_roots_for_process(roots)
prepare_application_directories(roots)
import httpx
import main
provider = {'id':'zhenzhen', 'name':'Fixture supplier', 'base_url':'https://supplier.example/v1',
            'protocol':'openai', 'image_request_mode':'openai', 'image_models':['nano-banana-2']}
roots.CONFIG_ROOT.mkdir(parents=True, exist_ok=True)
main.save_api_providers([provider])
main.get_api_provider = lambda _: provider
main.api_headers = lambda **kwargs: {'Authorization':'Bearer fixture-only-key'}
original_client = httpx.AsyncClient
calls = []
def handler(request):
    calls.append((request.method, request.url.path))
    if request.method == 'POST':
        return httpx.Response(200, json={'task_id':'accepted-before-process-exit'}, request=request)
    assert request.method == 'GET' and request.url.path == '/v1/images/tasks/accepted-before-process-exit'
    return httpx.Response(200, json={'status':'SUCCESS', 'data':[{'url':'https://supplier.example/result.png'}]}, request=request)
main.httpx.AsyncClient = lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs)
id_path = roots.DATA_ROOT / 'fixture-local-task-id'
'''


def test_hard_exit_preserves_accepted_id_and_recovery_only_issues_get(tmp_path):
    install = tmp_path / "install"
    app = install / "releases/fixture"
    (app / "static").mkdir(parents=True)
    (app / "main.py").write_text("# fixture", encoding="utf-8")
    writer = BOOTSTRAP + r'''
async def exit_before_poll(client, upstream_id, provider):
    record = main.CANVAS_TASK_JOURNAL.get(id_path.read_text())
    assert record['upstream_task_id'] == upstream_id == 'accepted-before-process-exit'
    assert record['provider_receipts'][0]['provider_base_url'] == provider['base_url']
    assert calls == [('POST', '/v1/images/generations')]
    assert 'fixture-only-key' not in json.dumps(record)
    os._exit(17)
main.wait_for_image_task = exit_before_poll
async def create():
    response = await main.create_canvas_image_task(main.OnlineImageRequest(prompt='private-fixture', provider_id='zhenzhen', model='nano-banana-2'))
    id_path.write_text(response['task_id'])
    await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
asyncio.run(create())
'''
    arguments = [str(ROOT), str(install), str(tmp_path / "local")]
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    first = subprocess.run([sys.executable, "-c", writer, *arguments], cwd=ROOT, env=environment,
                           capture_output=True, text=True, timeout=40)
    assert first.returncode == 17, first.stdout + first.stderr
    reader = BOOTSTRAP + r'''
async def save_image(image, prefix=''):
    assert image['value'] == 'https://supplier.example/result.png'
    from PIL import Image
    Image.new('RGB', (1, 1), 'white').save(Path(main.OUTPUT_DIR) / 'recovered-original.png')
    return '/output/recovered-original.png'
main.save_ai_image_to_output = save_image
assert main.CANVAS_TASK_JOURNAL.recover()['interrupted'] == 1
async def recover():
    task_id = id_path.read_text()
    record = await main.get_canvas_image_task(task_id)
    assert record['can_reconcile'] and record['upstream_task_id'] == 'accepted-before-process-exit'
    result = await main.reconcile_canvas_image_task(task_id)
    assert result['status'] == 'succeeded' and result['images'] == ['/output/recovered-original.png']
    cached = await main.reconcile_canvas_image_task(task_id)
    assert cached == result, (cached, result)
    assert calls == [('GET','/v1/images/tasks/accepted-before-process-exit')], calls
    assert (await main.get_canvas_image_task(task_id))['status'] == 'succeeded'
    assert not main.CANVAS_TASK_JOURNAL.mark_running(task_id)
asyncio.run(recover())
print('hard-exit original task reconciled without another POST')
'''
    second = subprocess.run([sys.executable, "-c", reader, *arguments], cwd=ROOT, env=environment,
                            capture_output=True, text=True, timeout=40)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "hard-exit original task reconciled without another POST" in second.stdout


def test_archive_failure_keeps_original_receipt_available_for_get_only_retry(tmp_path):
    install = tmp_path / 'install'
    app = install / 'releases/fixture'
    (app / 'static').mkdir(parents=True)
    (app / 'main.py').write_text('# fixture', encoding='utf-8')
    script = BOOTSTRAP + r'''
import io
from PIL import Image
from enterprise.canvas_image_recovery import ImageReceiptSink
buffer = io.BytesIO(); Image.new('RGB', (1, 1), 'white').save(buffer, format='PNG')
fail_download = True
def archive_handler(request):
    calls.append((request.method, request.url.path))
    assert request.method == 'GET'
    if request.url.path == '/v1/images/tasks/accepted-before-process-exit':
        return httpx.Response(200, json={'status':'SUCCESS', 'data':[{'url':'https://supplier.example/result.png'}]}, request=request)
    assert request.url.path == '/result.png'
    if fail_download:
        raise httpx.ReadTimeout('fixture result download lost', request=request)
    return httpx.Response(200, content=buffer.getvalue(), headers={'content-type':'image/png'}, request=request)
main.httpx.AsyncClient = lambda **kwargs: original_client(transport=httpx.MockTransport(archive_handler), **kwargs)
main.CANVAS_TASK_JOURNAL.create({'id':'canvas_img_archive_retry', 'type':'online-image', 'status':'queued',
    'provider_id':'zhenzhen','model':'nano-banana-2','provider_receipts':[{'index':0,'state':'started'}]})
assert main.CANVAS_TASK_JOURNAL.mark_running('canvas_img_archive_retry')
async def run():
    global fail_download
    await ImageReceiptSink(main.CANVAS_TASK_JOURNAL, 'canvas_img_archive_retry', 0).accepted('accepted-before-process-exit', provider)
    assert main.CANVAS_TASK_JOURNAL.recover()['interrupted'] == 1
    first = await main.reconcile_canvas_image_task('canvas_img_archive_retry')
    assert first['status'] == 'unknown'
    record = main.CANVAS_TASK_JOURNAL.get('canvas_img_archive_retry')
    assert record['status'] == 'failed' and record['provider_receipts'][0]['state'] == 'accepted'
    assert record['provider_receipts'][0]['upstream_task_id'] == 'accepted-before-process-exit'
    assert not list(Path(main.OUTPUT_DIR).glob('online_*.png'))
    fail_download = False
    second = await main.reconcile_canvas_image_task('canvas_img_archive_retry')
    assert second['status'] == 'succeeded'
    assert all(Path(main.output_file_from_url(url)).is_file() for url in second['images'])
    count = len(calls)
    assert await main.reconcile_canvas_image_task('canvas_img_archive_retry') == second
    assert len(calls) == count == 4
    assert all(method == 'GET' for method, _ in calls)
asyncio.run(run())
print('archive retry keeps original task and downloads locally before caching success')
'''
    result = subprocess.run([sys.executable, '-c', script, str(ROOT), str(install), str(tmp_path / 'local')],
                            cwd=ROOT, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1'),
                            capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('legacy_partial', [False, True])
def test_batch_archive_failure_and_legacy_partial_cache_query_original_id(tmp_path, legacy_partial):
    install = tmp_path / 'install'
    app = install / 'releases/fixture'
    (app / 'static').mkdir(parents=True)
    (app / 'main.py').write_text('# fixture', encoding='utf-8')
    script = BOOTSTRAP + r'''
import io
from PIL import Image
from fastapi import HTTPException
from enterprise.canvas_image_recovery import ImageReceiptSink
buffer = io.BytesIO(); Image.new('RGB', (1, 1), 'white').save(buffer, format='PNG')
fail_download = True
def batch_handler(request):
    calls.append((request.method, request.url.path))
    assert request.method == 'GET'
    if request.url.path == '/v1/images/tasks/accepted-before-process-exit':
        return httpx.Response(200, json={'status':'SUCCESS', 'data':[{'url':'https://supplier.example/result.png'}]}, request=request)
    assert request.url.path == '/result.png'
    if fail_download:
        raise httpx.ReadTimeout('fixture initial batch archive lost', request=request)
    return httpx.Response(200, content=buffer.getvalue(), headers={'content-type':'image/png'}, request=request)
main.httpx.AsyncClient = lambda **kwargs: original_client(transport=httpx.MockTransport(batch_handler), **kwargs)
main.CANVAS_TASK_JOURNAL.create({'id':'canvas_img_batch_archive', 'type':'online-image', 'status':'queued',
    'provider_id':'zhenzhen', 'model':'nano-banana-2',
    'provider_receipts':[{'index':i, 'state':'started'} for i in range(2)]})
async def generate(*args, receipt_sink, **kwargs):
    if receipt_sink.index == 1:
        raise HTTPException(400, 'fixture member explicitly rejected')
    await receipt_sink.accepted('accepted-before-process-exit', provider)
    image = {'type':'url', 'value':'https://supplier.example/result.png'}
    return image, {'data':[{'url':image['value']}]}
main.generate_ai_image = generate
async def run():
    global fail_download
    if sys.argv[4] == 'True':
        # A persisted partial from the old fallback path must not return early.
        assert main.CANVAS_TASK_JOURNAL.mark_running('canvas_img_batch_archive')
        sink = ImageReceiptSink(main.CANVAS_TASK_JOURNAL, 'canvas_img_batch_archive', 0)
        await sink.accepted('accepted-before-process-exit', provider)
        await sink.completed(['https://supplier.example/result.png'], [])
        await ImageReceiptSink(main.CANVAS_TASK_JOURNAL, 'canvas_img_batch_archive', 1).interrupted(HTTPException(400, 'rejected'))
        main.CANVAS_TASK_JOURNAL.finish('canvas_img_batch_archive', {'status':'failed',
            'result':{'status':'partial', 'images':['https://supplier.example/result.png']}})
    else:
        await main.run_canvas_image_task('canvas_img_batch_archive', main.OnlineImageRequest(
            prompt='fixture', provider_id='zhenzhen', model='nano-banana-2', n=2))
        record = main.CANVAS_TASK_JOURNAL.get('canvas_img_batch_archive')
        assert record['status'] == 'failed' and record['provider_receipts'][0]['state'] == 'unknown'
        assert record['provider_receipts'][0]['upstream_task_id'] == 'accepted-before-process-exit'
    first = await main.reconcile_canvas_image_task('canvas_img_batch_archive')
    assert first['status'] == 'unknown', first
    fail_download = False
    second = await main.reconcile_canvas_image_task('canvas_img_batch_archive')
    assert second['status'] == 'partial' and second['images'], second
    assert all(Path(main.output_file_from_url(url)).is_file() for url in second['images'])
    count = len(calls)
    assert await main.reconcile_canvas_image_task('canvas_img_batch_archive') == second
    assert len(calls) == count and all(method == 'GET' for method, _ in calls)
    assert calls.count(('GET', '/v1/images/tasks/accepted-before-process-exit')) == 2
asyncio.run(run())
print('batch archive failure and legacy partial retain GET-only recovery')
'''
    result = subprocess.run([sys.executable, '-c', script, str(ROOT), str(install), str(tmp_path / 'local'), str(legacy_partial)],
                            cwd=ROOT, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1'),
                            capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
