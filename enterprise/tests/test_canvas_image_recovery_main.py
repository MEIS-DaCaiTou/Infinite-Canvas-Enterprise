"""Actual main hooks survive a hard exit immediately after supplier acceptance."""
import json
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


def test_responses_hard_exit_keeps_original_endpoint_and_archives_all_outputs(tmp_path):
    for directory in ('static','workflows'):
        (tmp_path/'install/releases/fixture'/directory).mkdir(parents=True,exist_ok=True)
    setup = BOOTSTRAP + r'''
provider.update(id='responses-fixture',image_request_mode='openai-responses',
    image_generation_endpoint='https://supplier.example/custom/responses',image_models=['responses-fixture-image'])
main.save_api_providers([provider])
main.RESPONSES_POLL_INTERVAL=0
'''
    writer = setup + r'''
def interrupted(request):
    calls.append((request.method,str(request.url)))
    if request.method=='POST':
        assert str(request.url)=='https://supplier.example/custom/responses'
        assert json.loads(request.content)['background'] is True
        return httpx.Response(200,json={'status':'queued','id':'resp-original'},headers={'x-request-id':'request-original'})
    receipt=main.CANVAS_TASK_JOURNAL.get(id_path.read_text())['provider_receipts'][0]
    assert receipt['state']=='accepted' and receipt['upstream_task_id']=='resp-original'
    assert receipt['query_endpoint']=='https://supplier.example/custom/responses/resp-original'
    assert receipt['provider_request_id']=='request-original'
    assert [method for method,_ in calls]==['POST','GET']
    os._exit(37)
main.httpx.AsyncClient=lambda **kw:original_client(transport=httpx.MockTransport(interrupted),**kw)
async def exercise():
    result=await main.create_canvas_image_task(main.OnlineImageRequest(prompt='own synthetic fixture',provider_id=provider['id'],model='responses-fixture-image'))
    id_path.write_text(result['task_id'])
    await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
asyncio.run(exercise())
'''
    args=[str(ROOT),str(tmp_path/'install'),str(tmp_path/'local')]
    environment=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1')
    crashed=subprocess.run([sys.executable,'-c',writer,*args],cwd=ROOT,env=environment,capture_output=True,text=True,timeout=40)
    assert crashed.returncode==37,crashed.stdout+crashed.stderr
    reader = setup + r'''
import base64
from io import BytesIO
from PIL import Image
provider['image_generation_endpoint']='https://supplier.example/changed/responses'
main.save_api_providers([provider])
assert main.CANVAS_TASK_JOURNAL.recover()['interrupted']==1
encoded=[]
for color in ['red','blue']:
    content=BytesIO();Image.new('RGBA',(20,16),color).save(content,'PNG');encoded.append(base64.b64encode(content.getvalue()).decode())
finished=False
def original_query(request):
    assert request.method=='GET' and str(request.url)=='https://supplier.example/custom/responses/resp-original'
    calls.append((request.method,str(request.url)))
    return httpx.Response(200,json={'id':'resp-original','status':'completed' if finished else 'in_progress',
        'output':[{'type':'image_generation_call','result':value} for value in encoded]})
main.httpx.AsyncClient=lambda **kw:original_client(transport=httpx.MockTransport(original_query),**kw)
async def exercise():
    global finished
    key=id_path.read_text()
    assert (await main.reconcile_canvas_image_task(key))['status']=='running'
    record=main.CANVAS_TASK_JOURNAL.get(key)
    assert not (record.get('result') or {}).get('images') and record['provider_receipts'][0]['state']=='accepted'
    finished=True
    result=await main.reconcile_canvas_image_task(key)
    assert result['status']=='succeeded' and len(result['images'])==2
    for url in result['images']:
        with Image.open(main.output_file_from_url(url)) as image:assert image.size==(20,16)
    assert (await main.reconcile_canvas_image_task(key))==result
    assert len(calls)==2 and all(method=='GET' for method,_ in calls)
asyncio.run(exercise())
'''
    recovered=subprocess.run([sys.executable,'-c',reader,*args],cwd=ROOT,env=environment,capture_output=True,text=True,timeout=40)
    assert recovered.returncode==0,recovered.stdout+recovered.stderr


@pytest.mark.parametrize("mode", ["first-write", "until-finish", "finish-retry", "finish-after-save", "path-probe", "unwritable"])
def test_accepted_image_id_survives_receipt_write_failure(tmp_path, mode):
    install = tmp_path / "install"
    app = install / "releases/fixture"
    (app / "static").mkdir(parents=True)
    (app / "main.py").write_text("# fixture", encoding="utf-8")
    script = BOOTSTRAP + r'''
from enterprise.generation_tasks import describe_task
from io import BytesIO
from PIL import Image
mode = sys.argv[4]
task_id = 'canvas_img_' + 'f'*32
journal = main.CANVAS_TASK_JOURNAL
write = journal._write
failed = 0
failures_before_recovery = {'first-write': 1, 'until-finish': 2, 'finish-retry': 3, 'path-probe': 1}
image = BytesIO()
Image.new('RGB', (32,32), 'white').save(image, 'PNG')

def fail_write(record):
    global failed
    if mode == 'finish-after-save':
        state = record['provider_receipts'][0]['state']
        fail = (failed == 0 and state == 'accepted') or (failed == 1 and record['status'] == 'failed')
    else:
        fail = mode == 'unwritable' or failed < failures_before_recovery[mode]
    if record.get('upstream_task_id') and fail:
        failed += 1
        if mode=='path-probe':
            from unittest.mock import patch
            with patch('enterprise.paths.os.lstat', side_effect=PermissionError('fixture storage path inaccessible')):
                write(record)
            raise AssertionError('fixture path probe did not fail')
        raise PermissionError('fixture journal write blocked')
    write(record)
journal._write = fail_write

def reply(request):
    path = request.url.path
    if path == '/result.png':
        calls.append((request.method,path))
        return httpx.Response(200,content=image.getvalue(),headers={'content-type':'image/png'})
    if request.method == 'GET':
        saved = journal.get(task_id)['provider_receipts'][0]
        assert saved['upstream_task_id']=='accepted-before-process-exit'
        assert saved['provider_base_url']==provider['base_url']
    return handler(request)
main.httpx.AsyncClient = lambda **kw: original_client(transport=httpx.MockTransport(reply), **kw)

async def exercise():
    request = main.OnlineImageRequest(request_id='f'*32, provider_id='zhenzhen',model='gpt-image-2-all',prompt='fixture')
    await main.create_canvas_image_task(request,None)
    await asyncio.gather(*main.CANVAS_TASK_RUNNERS, return_exceptions=(mode=='unwritable'))
    assert calls==[('POST','/v1/images/generations')]
    public = await main.get_canvas_image_task(task_id)
    assert public['recovery_required'] and public['error_code']=='PROVIDER_SUBMISSION_UNKNOWN'
    assert '已受理' in public['error']
    if mode=='finish-after-save':
        assert failed==2
    if mode=='unwritable':
        assert not public['can_reconcile'] and not journal.get(task_id).get('upstream_task_id')
        from enterprise.generation_tasks import GenerationTaskRepository
        from enterprise import db
        db.get_task_owner = lambda *_: 'owner'
        db.list_owned_canvas_tasks = lambda *_args, **_kw: [
            {'task_id':task_id, 'task_type':'canvas_image', 'created_at':1}]
        repository = GenerationTaskRepository(journal.root,journal=journal)
        for item in (repository.detail('owner',task_id),repository.page('owner',status='unknown')['items'][0]):
            assert item['status']=='unknown' and '本地回执' in item['error'] and not item['can_query']
        assert repository.detail('another-user',task_id) is None
        return
    assert public['can_reconcile']
    detail = describe_task(journal.get(task_id),detail=True)
    assert detail['status']=='unknown' and detail['attempts'][0]['status']=='unknown'
    assert detail['attempts'][0]['upstream_task_id']=='accepted-before-process-exit'
    recovered = await main.reconcile_canvas_image_task(task_id)
    assert recovered['status']=='succeeded' and len(recovered['images'])==1
    assert calls==[('POST','/v1/images/generations'),('GET','/v1/images/tasks/accepted-before-process-exit'),('GET','/result.png')]
asyncio.run(exercise())
'''
    result = subprocess.run([sys.executable, "-c", script, str(ROOT), str(install), str(tmp_path / "local"), mode],
                            cwd=ROOT, env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"),
                            capture_output=True, text=True, encoding="utf-8", timeout=35)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("crash_point", ["accepted", "before_reply"])
def test_hard_exit_preserves_accepted_id_and_recovery_only_issues_get(tmp_path, crash_point):
    install = tmp_path / "install"
    app = install / "releases/fixture"
    (app / "static").mkdir(parents=True)
    (app / "main.py").write_text("# fixture", encoding="utf-8")
    writer = BOOTSTRAP + r'''
crash_point = sys.argv[4]
def crash_handler(request):
    if request.method == 'POST':
        assert request.url.path == '/v1/images/generations' and request.url.params['async'] == 'true'
        calls.append(('POST', request.url.path))
        if crash_point == 'before_reply':
            assert main.CANVAS_TASK_JOURNAL.get(id_path.read_text())['provider_receipts'][0]['state'] == 'submitting'
            os._exit(18)
        return httpx.Response(200, json={'task_id':'accepted-before-process-exit'})
    record = main.CANVAS_TASK_JOURNAL.get(id_path.read_text())
    assert request.method == 'GET' and request.url.path == '/v1/images/tasks/accepted-before-process-exit'
    assert record['upstream_task_id'] == 'accepted-before-process-exit'
    assert record['provider_receipts'][0]['provider_base_url'] == provider['base_url']
    assert calls == [('POST', '/v1/images/generations')]
    assert 'fixture-only-key' not in json.dumps(record)
    os._exit(17)
main.httpx.AsyncClient = lambda **kwargs: original_client(transport=httpx.MockTransport(crash_handler), **kwargs)
async def create():
    response = await main.create_canvas_image_task(main.OnlineImageRequest(prompt='private-fixture', provider_id='zhenzhen', model='nano-banana-2'))
    id_path.write_text(response['task_id'])
    await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
asyncio.run(create())
'''
    arguments = [str(ROOT), str(install), str(tmp_path / "local"), crash_point]
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    first = subprocess.run([sys.executable, "-c", writer, *arguments], cwd=ROOT, env=environment,
                           capture_output=True, text=True, timeout=40)
    assert first.returncode == (17 if crash_point == "accepted" else 18), first.stdout + first.stderr
    reader = BOOTSTRAP + r'''
async def save_image(image, prefix='', *, plan_archive=None):
    assert image['value'] == 'https://supplier.example/result.png'
    from PIL import Image
    Image.new('RGB', (1, 1), 'white').save(Path(main.OUTPUT_DIR) / 'recovered-original.png')
    return '/output/recovered-original.png'
main.save_ai_image_to_output = save_image
assert main.CANVAS_TASK_JOURNAL.recover()['interrupted'] == 1
async def recover():
    task_id = id_path.read_text()
    record = await main.get_canvas_image_task(task_id)
    if sys.argv[4] == 'before_reply':
        from enterprise.generation_tasks import describe_task
        from fastapi import HTTPException
        assert describe_task(main.CANVAS_TASK_JOURNAL.get(task_id))['status'] == 'unknown'
        assert not record.get('upstream_task_id') and not record['can_reconcile']
        assert not main.CANVAS_TASK_JOURNAL.recovery_candidates()
        try:
            await main.reconcile_canvas_image_task(task_id)
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError('No original supplier ID to query')
        assert calls == []
        return
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


@pytest.mark.parametrize("stage", ["before_publish", "before_result_receipt", "before_history"])
def test_sync_image_archive_recovery_requires_durable_task_association(tmp_path, stage):
    install = tmp_path / "install"
    app = install / "releases/fixture"
    (app / "static").mkdir(parents=True)
    (app / "main.py").write_text("# fixture", encoding="utf-8")
    writer = BOOTSTRAP + r'''
from base64 import b64encode
from io import BytesIO
from PIL import Image
from enterprise.canvas_image_recovery import ImageReceiptSink

# A synchronous OpenAI-compatible route returns bytes with no supplier task ID.
provider.update(id='fixture-sync', base_url='https://supplier.example/v1')
encoded = BytesIO()
Image.new('RGB', (8, 8), 'orange').save(encoded, format='PNG')
def complete(request):
    assert request.method == 'POST' and request.url.path == '/v1/images/generations'
    assert 'async' not in request.url.params
    assert not calls
    assert json.loads(request.content).get('n', 1) == 1
    calls.append((request.method, request.url.path))
    return httpx.Response(200, json={'data': [{'b64_json': b64encode(encoded.getvalue()).decode('ascii')}]})
main.httpx.AsyncClient = lambda **kwargs: original_client(transport=httpx.MockTransport(complete), **kwargs)

def interrupt(urls):
    assert calls == [('POST', '/v1/images/generations')]
    assert Path(main.output_file_from_url(urls[0])).read_bytes() == encoded.getvalue()
    os._exit(19)

if sys.argv[4] == 'before_publish':
    operation = 'rename' if os.name == 'nt' else 'link'
    publish = getattr(os, operation)
    def before_publish(source, target, *args, **kwargs):
        if str(source).endswith('.part') and 'online_' in str(target):
            assert Path(source).read_bytes() == encoded.getvalue()
            receipt = main.CANVAS_TASK_JOURNAL.get(id_path.read_text())['provider_receipts'][0]
            assert receipt['state'] == 'generated' and receipt['archive']['url'].endswith(Path(target).name)
            assert not Path(target).exists()
            assert calls == [('POST', '/v1/images/generations')]
            os._exit(19)
        return publish(source, target, *args, **kwargs)
    setattr(os, operation, before_publish)
elif sys.argv[4] == 'before_result_receipt':
    async def before_result_receipt(self, urls, items):
        interrupt(urls)
    ImageReceiptSink.completed = before_result_receipt
else:
    def before_history(record):
        receipt = main.CANVAS_TASK_JOURNAL.get(id_path.read_text())['provider_receipts'][0]
        assert receipt['state'] == 'succeeded' and not receipt.get('upstream_task_id')
        interrupt(record['images'])
    main.save_to_history = before_history

async def create():
    response = await main.create_canvas_image_task(main.OnlineImageRequest(
        prompt='synchronous image fixture', provider_id=provider['id'], model='fixture-model'), None)
    id_path.write_text(response['task_id'])
    await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
asyncio.run(create())
'''
    reader = BOOTSTRAP + r'''
from enterprise.generation_tasks import describe_task
from enterprise.history_records import read_records
from fastapi import HTTPException

def no_supplier_request(request):
    calls.append((request.method, request.url.path))
    raise AssertionError('Local recovery must not call the supplier')
main.httpx.AsyncClient = lambda **kwargs: original_client(transport=httpx.MockTransport(no_supplier_request), **kwargs)
assert main.CANVAS_TASK_JOURNAL.recover()['interrupted'] == 1
task_id = id_path.read_text()
from PIL import Image
archive_dir = roots.UPLOAD_ROOT / 'assets/output'
files = list(archive_dir.glob('online_*.png'))
stage = sys.argv[4]
assert len(files) == (0 if stage == 'before_publish' else 1)
Image.new('RGB', (4, 4), 'blue').save(archive_dir / ('online_' + 'a' * 32 + '.png'))
assert read_records(main.HISTORY_FILE) == []
async def recover():
    detail = describe_task(main.CANVAS_TASK_JOURNAL.get(task_id), detail=True)
    assert not detail['attempts'][0]['upstream_task_id'] and detail['can_query']
    if stage == 'before_publish':
        assert detail['status'] == 'unknown' and not detail['output_count']
        assert len(list(archive_dir.glob('*.part'))) == 1
        try:
            await main.reconcile_canvas_image_task(task_id)
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError('Neither a temporary file nor an unassociated file can be assigned')
        assert read_records(main.HISTORY_FILE) == []
    else:
        if stage == 'before_history':
            assert detail['output_count'] == 1
            assert (await main.get_canvas_image_task(task_id))['result']['images'] == [detail['items'][0]['url']]
        else:
            assert detail['status'] == 'unknown' and not detail['output_count']
        recovered = await main.reconcile_canvas_image_task(task_id)
        assert recovered['status'] == 'succeeded'
        assert [Path(main.output_file_from_url(url)) for url in recovered['images']] == files
        assert recovered['image_items'][0]['natural_w'] == 8
        assert await main.reconcile_canvas_image_task(task_id) == recovered
        assert (await main.get_canvas_image_task(task_id))['status'] == 'succeeded'
        rows = read_records(main.HISTORY_FILE)
        assert len(rows) == 1 and rows[0]['images'] == recovered['images']
    assert not calls
asyncio.run(recover())
'''
    args = [str(ROOT), str(install), str(tmp_path / "local"), stage]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    first = subprocess.run([sys.executable, "-c", writer, *args], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=40)
    assert first.returncode == 19, first.stdout + first.stderr
    second = subprocess.run([sys.executable, "-c", reader, *args], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=40)
    assert second.returncode == 0, second.stdout + second.stderr


@pytest.mark.parametrize("stage", ["before_publish", "before_receipt"])
def test_background_single_image_archive_recovers_after_process_exit(tmp_path, stage):
    install = tmp_path / "install"
    app = install / "releases/fixture"
    (app / "static").mkdir(parents=True)
    (app / "main.py").write_text("# fixture", encoding="utf-8")
    script = BOOTSTRAP + r'''
from io import BytesIO
from PIL import Image
from enterprise import db

stage, process = sys.argv[4:]
task_id = 'canvas_img_' + 'a' * 32
archive_path = roots.DATA_ROOT / 'fixture-archive-url'
journal = main.CANVAS_TASK_JOURNAL
main.CANVAS_ACCEPTED_RECOVERY.poll_delay = .02
posts = 0
background = process == 'restart'
images = []
for index in range(3):
    buffer = BytesIO()
    Image.new('RGB', (8, 8), (index * 60, 20, 100)).save(buffer, format='PNG')
    images.append(buffer.getvalue())

def supplier(request):
    global posts
    path = request.url.path
    calls.append((request.method, path))
    if request.method == 'POST':
        assert process == 'initial' and not background
        assert path == '/v1/images/generations' and request.url.params['async'] == 'true'
        assert json.loads(request.content).get('n', 1) == 1
        posts += 1
        if posts == 4:
            return httpx.Response(429, json={'error': {'message': 'fixture rate limit'}})
        return httpx.Response(200, json={'task_id': f'original-{posts - 1}'})
    assert request.method == 'GET'
    if process == 'restart' and stage == 'before_receipt':
        return httpx.Response(410, json={'message': 'fixture result expired'})
    if path.startswith('/v1/images/tasks/'):
        index = int(path.rsplit('-', 1)[1])
        if index == 2 and not background:
            return httpx.Response(503, json={'message': 'fixture initial query unavailable'})
        return httpx.Response(200, json={'status': 'SUCCESS',
            'data': [{'url': f'https://supplier.example/result-{index}.png'}],
            'usage': {'total_tokens': index + 10}})
    index = int(path.removeprefix('/result-').removesuffix('.png'))
    return httpx.Response(200, content=images[index], headers={'content-type': 'image/png'})

main.httpx.AsyncClient = lambda **kwargs: original_client(transport=httpx.MockTransport(supplier), **kwargs)

def target_receipt():
    return next(item for item in journal.get(task_id)['provider_receipts']
                if item.get('upstream_task_id') == 'original-2')

async def submit_and_interrupt():
    global background
    db.ensure_db_schema()
    connection = db.get_db()
    try:
        with connection:
            connection.executemany(
                "INSERT INTO users (id, username, password_hash, display_name, role, is_admin, auth_version, is_active, created_at) "
                "VALUES (?, ?, 'fixture', ?, 'user', 0, 1, 1, 1)",
                [(name, name, name) for name in ('fixture-alice', 'fixture-bob')],
            )
    finally:
        connection.close()
    request = main.OnlineImageRequest(request_id='a' * 32, provider_id='zhenzhen',
        model='gpt-image-2-all', prompt='fixture', n=4)
    assert (await main.create_canvas_image_task(request, 'fixture-alice'))['task_id'] == task_id
    await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
    assert posts == 4
    assert sorted(item['state'] for item in journal.get(task_id)['provider_receipts']) == [
        'failed', 'succeeded', 'succeeded', 'unknown']
    background = True

    if stage == 'before_publish':
        operation = 'rename' if os.name == 'nt' else 'link'
        publish = getattr(os, operation)
        def interrupt_publish(source, target, *args, **kwargs):
            if Path(source).suffix == '.part' and Path(target).name.startswith('online_'):
                receipt = target_receipt()
                assert receipt['state'] == 'generated'
                assert Path(source).read_bytes() == images[2] and not Path(target).exists()
                assert receipt['archive']['url'].endswith(Path(target).name)
                archive_path.write_text(receipt['archive']['url'], encoding='utf-8')
                os._exit(19)
            return publish(source, target, *args, **kwargs)
        setattr(os, operation, interrupt_publish)
    else:
        write = journal.record_image_request
        def interrupt_receipt(key, index, changes, *, recovering=False):
            if recovering and changes.get('state') == 'succeeded':
                url, = changes['result']['images']
                assert Path(main.output_file_from_url(url)).read_bytes() == images[2]
                archive_path.write_text(url, encoding='utf-8')
                os._exit(19)
            return write(key, index, changes, recovering=recovering)
        journal.record_image_request = interrupt_receipt

    await main.startup_event()
    try:
        async with asyncio.timeout(8):
            while (journal.get(task_id).get('auto_recovery') or {}).get('status') != 'complete':
                await asyncio.sleep(.02)
        raise AssertionError('Background recovery missed the archive interruption point')
    finally:
        await main.shutdown_task_recovery()

async def check_recovery():
    from enterprise import gateway
    from enterprise.auth import create_token
    url = archive_path.read_text(encoding='utf-8')
    record = journal.get(task_id)
    assert record['auto_recovery']['status'] == 'querying'
    path = main.output_file_from_url(url)
    assert bool(path and Path(path).is_file()) == (stage == 'before_receipt')
    await main.startup_event()
    try:
        async with asyncio.timeout(8):
            while journal.get(task_id)['auto_recovery']['status'] not in {'complete', 'manual'}:
                await asyncio.sleep(.02)
        owner = db.get_user_by_username('fixture-alice')
        other = db.get_user_by_username('fixture-bob')
        token = lambda user: {'Cookie': 'enterprise_token=' + create_token(user['id'])}
        async with (
            original_client(transport=httpx.ASGITransport(app=main.app), base_url='http://upstream') as upstream,
            original_client(transport=httpx.ASGITransport(app=gateway.app), base_url='http://testserver') as client,
        ):
            gateway._http_client = gateway.app.state.upstream_client = upstream
            task_path = '/enterprise/api/me/generation-tasks/' + task_id
            detail = await client.get(task_path, headers=token(owner))
            assert detail.status_code == 200, detail.text
            data = detail.json()
            assert data['status'] == 'partial' and data['output_count'] == 3, data
            assert sorted(item['status'] for item in data['attempts']) == ['failed', 'succeeded', 'succeeded', 'succeeded']
            recovered = target_receipt()
            assert recovered['reported_usage']['total_tokens'] == 12
            recovered_url, = recovered['result']['images']
            if stage == 'before_receipt':
                assert recovered_url == url
                assert calls == []
            else:
                assert calls == [('GET', '/v1/images/tasks/original-2'), ('GET', '/result-2.png')]
            public = await client.get('/api/canvas-image-tasks/' + task_id, headers=token(owner))
            assert set(public.json()['result']['images']) == {item['url'] for item in data['items']}
            assert (await client.get(task_path, headers=token(other))).status_code == 404
            result_bytes = set()
            for item in data['items']:
                response = await client.get(item['url'], headers=token(owner))
                assert response.status_code == 200
                result_bytes.add(response.content)
                assert (await client.get(item['url'], headers=token(other))).status_code == 404
            assert result_bytes == set(images)
            assert (await client.get(recovered_url, headers=token(owner))).content == images[2]
    finally:
        await main.shutdown_task_recovery()

asyncio.run(submit_and_interrupt() if process == 'initial' else check_recovery())
'''
    environment = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1",
                       JWT_SECRET="fixture-authentication-key-for-isolated-tests")
    for process, expected in (("initial", 19), ("restart", 0)):
        run = subprocess.run(
            [sys.executable, "-c", script, str(ROOT), str(install), str(tmp_path / "local"), stage, process],
            cwd=ROOT, env=environment, capture_output=True, text=True, timeout=40,
        )
        assert run.returncode == expected, run.stdout + run.stderr


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


def test_async_edit_uploads_local_asset_upload_and_history_as_files(tmp_path):
    install = tmp_path / "install"
    app = install / "releases/fixture"
    (app / "static").mkdir(parents=True)
    (app / "main.py").write_text("# fixture", encoding="utf-8")
    script = BOOTSTRAP + r'''
from email import policy
from email.parser import BytesParser
from io import BytesIO
from starlette.datastructures import Headers, UploadFile
from PIL import Image

colors = {'asset':(80,30,180), 'upload':(20,130,80), 'history':(190,40,35)}
def image_bytes(label, size):
    out = BytesIO()
    Image.new('RGB', size, colors[label]).save(out, format='PNG')
    return out.getvalue()

posts = []
def reply(request):
    path = request.url.path
    if request.method == 'POST':
        assert path == '/v1/images/edits' and request.url.params['async'] == 'true'
        header = ('Content-Type: ' + request.headers['content-type'] + '\r\n\r\n').encode()
        parts = list(BytesParser(policy=policy.default).parsebytes(header + request.content).iter_parts())
        fields = {part.get_param('name', header='content-disposition'):part.get_content()
                  for part in parts if not part.get_filename()}
        files = [part for part in parts if part.get_filename()]
        label = fields['prompt']
        assert fields['model'] == 'gpt-image-2-all' and len(files) == 1
        assert files[0].get_param('name', header='content-disposition') == 'image'
        with Image.open(BytesIO(files[0].get_payload(decode=True))) as image:
            assert image.size == (1536, 1024) and image.format == 'JPEG'
            assert all(abs(a-b) <= 3 for a,b in zip(image.getpixel((500,500)), colors[label]))
        posts.append(label)
        return httpx.Response(200, json={'task_id':label})
    if path.startswith('/v1/images/tasks/'):
        label = path.rsplit('/',1)[-1]
        return httpx.Response(200,json={'data':{'task_id':label,'status':'SUCCESS','data':{
            'data':[{'url':f'https://supplier.example/{label}.png'}]}}})
    label = path.removeprefix('/').removesuffix('.png')
    return httpx.Response(200,content=image_bytes(label,(32,32)),headers={'content-type':'image/png'})

main.httpx.AsyncClient = lambda **kwargs: original_client(transport=httpx.MockTransport(reply), **kwargs)

async def exercise():
    asset_path = Path(main.ASSETS_DIR)/'library'/'reference.png'
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_bytes(image_bytes('asset',(3072,2048)))
    uploaded = await main.upload_ai_reference([UploadFile(BytesIO(image_bytes('upload',(3072,2048))),
        filename='portrait.png',headers=Headers({'content-type':'image/png'}))])
    assert uploaded['files'][0]['url'].startswith('/assets/input/')
    archived = await main.save_ai_image_to_output({'type':'url','value':'https://supplier.example/history.png'}, prefix='history_')
    assert archived.startswith('/assets/')
    Path(main.output_file_from_url(archived)).write_bytes(image_bytes('history',(3840,2560)))
    refs = {'asset':'/assets/library/reference.png','upload':uploaded['files'][0]['url'],'history':archived}
    for index,(label,url) in enumerate(refs.items()):
        body = main.OnlineImageRequest(request_id=f'{index+1:032x}',provider_id='zhenzhen',
            model='gpt-image-2-all', prompt=label,reference_images=[{'url':url,'kind':'image'}])
        task = await main.create_canvas_image_task(body, None)
        await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
        record = await main.get_canvas_image_task(task['task_id'])
        assert record['status']=='succeeded' and record['upstream_task_id']==label,record
        assert Path(main.output_file_from_url(record['result']['images'][0])).is_file()
    for index,url in enumerate(['/assets/input/missing.png','https://unconfigured.example/missing.png'], start=4):
        body = main.OnlineImageRequest(request_id=f'{index:032x}',provider_id='zhenzhen',
            model='gpt-image-2-all', prompt='invalid',reference_images=[{'url':url,'kind':'image'}])
        task = await main.create_canvas_image_task(body,None)
        await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
        assert (await main.get_canvas_image_task(task['task_id']))['status']=='failed'
    assert posts == ['asset','upload','history']
asyncio.run(exercise())
'''
    result = subprocess.run(
        [sys.executable, "-c", script, str(ROOT), str(install), str(tmp_path / "local")],
        cwd=ROOT, env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"),
        capture_output=True, text=True, timeout=40,
    )
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

@pytest.mark.parametrize("failure", [None, 429, 502, "disconnect", "request-id-only"])
def test_independent_batch_receipts_and_supplier_status(tmp_path, failure):
    install = tmp_path / "install"
    app = install / "releases/fixture"
    (app / "static").mkdir(parents=True)
    (app / "main.py").write_text("# fixture", encoding="utf-8")
    script = BOOTSTRAP + r"""
from PIL import Image
from enterprise.generation_tasks import describe_task

failure = json.loads(sys.argv[4])
posts = []
queries = {}
main.IMAGE_POLL_INTERVAL = 0.001
def handler(request):
    if request.method == 'GET':
        upstream_id = request.url.path.removeprefix('/v1/images/tasks/')
        index = int(upstream_id.removeprefix('fixture-job-'))
        record = main.CANVAS_TASK_JOURNAL.get(f'canvas_img_{index + 1:032x}')
        assert record['provider_receipts'][0]['upstream_task_id'] == upstream_id
        assert record['provider_receipts'][0]['state'] == 'accepted'
        queries[index] = queries.get(index, 0) + 1
        result = {'task_id':upstream_id, 'status':'IN_PROGRESS'}
        if queries[index] > 1:
            result.update(status='SUCCESS', data={'data':[{'url':f'https://supplier.example/{upstream_id}.png'}]})
        return httpx.Response(200, json={'code':'success','data':result})
    assert request.method == 'POST' and request.url.path == '/v1/images/generations'
    assert request.url.params['async'] == 'true'
    payload = json.loads(request.content)
    index = int(payload['prompt'])
    posts.append(index)
    headers = {'x-request-id': f'fixture-request-{index}'}
    if index == 3 and failure == 'disconnect':
        raise httpx.ReadTimeout('fixture supplier reply interrupted', request=request)
    if index == 3 and failure == 'request-id-only':
        return httpx.Response(200, json={'request_id':'task-diagnostic-only'})
    if index == 3 and failure:
        return httpx.Response(failure, headers=headers, json={'error': {'message': 'fixture supplier rejected request', 'code': 'invalid_value'}})
    if index == 1:
        return httpx.Response(200, headers=headers, json={'data':[{'url':'https://supplier.example/sync.png'}]})
    if index == 2:
        return httpx.Response(200, headers=headers, json={'task_id':'fixture-job-2',
            'data':[{'url':'https://supplier.example/preview.png'}]})
    return httpx.Response(200, headers=headers, json={'task_id':f'fixture-job-{index}'})
main.httpx.AsyncClient = lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs)

async def save_image(image, prefix='', *, plan_archive=None):
    name = image['value'].rsplit('/', 1)[1]
    Image.new('RGB', (16, 16), 'white').save(Path(main.OUTPUT_DIR) / name)
    return f'/output/{name}'
main.save_ai_image_to_output = save_image

async def exercise():
    requests = [main.OnlineImageRequest(prompt=str(index), provider_id='zhenzhen', model='gpt-image-2-all',
        size='3840x2160', request_id=f'{index + 1:032x}') for index in range(4)]
    receipts = await asyncio.gather(*(main.create_canvas_image_task(body) for body in requests))
    duplicate = await main.create_canvas_image_task(requests[0])
    assert duplicate['task_id'] == receipts[0]['task_id']
    await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
    tasks = [await main.get_canvas_image_task(receipt['task_id']) for receipt in receipts]
    assert sorted(posts) == [0, 1, 2, 3]
    assert queries == ({0:2, 2:2} if failure else {0:2, 2:2, 3:2})
    assert [task['status'] for task in tasks] == ['succeeded'] * 3 + (['failed'] if failure else ['succeeded'])
    assert tasks[0]['upstream_task_id'] == 'fixture-job-0'
    assert not tasks[1].get('upstream_task_id') and tasks[1]['provider_request_id'] == 'fixture-request-1'
    assert tasks[2]['upstream_task_id'] == 'fixture-job-2'
    assert tasks[2]['result']['images'] == ['/output/fixture-job-2.png']
    attempt = describe_task(main.CANVAS_TASK_JOURNAL.get(tasks[1]['id']), detail=True)['attempts'][0]
    assert not attempt['upstream_task_id'] and attempt['provider_request_id'] == 'fixture-request-1'
    if failure:
        assert tasks[3]['submission_status'] == ('failed' if failure == 429 else 'unknown')
        assert '当前尺寸' not in tasks[3]['error']
    if failure == 429:
        assert '限流' in tasks[3]['error'] and 'fixture supplier rejected request' in tasks[3]['error']
    if failure == 502:
        assert 'HTTP 502' in tasks[3]['error'] and tasks[3]['provider_request_id'] == 'fixture-request-3'
    if failure == 'request-id-only':
        assert tasks[3]['provider_request_id'] == 'task-diagnostic-only' and not tasks[3].get('upstream_task_id')
    if failure in ('disconnect', 'request-id-only', 502):
        task = describe_task(main.CANVAS_TASK_JOURNAL.get(tasks[3]['id']), detail=True)
        assert task['status'] == 'unknown' and not task['can_query']
    for code in (401, 403, 429):
        assert '尺寸' not in main.friendly_image_error_detail('invalid size', '4096x4096', 'gpt-image-2', code)
    assert main.friendly_image_error_detail('invalid_value for quality', '4096x4096', 'gpt-image-2', 400) == ''
    assert '尺寸' in main.friendly_image_error_detail('invalid size', '4096x4096', 'gpt-image-2', 400)
asyncio.run(exercise())
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(ROOT), str(install), str(tmp_path / "local"), json.dumps(failure)],
        cwd=ROOT, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1"),
        capture_output=True, encoding="utf-8", timeout=40,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("last_attempt", ["rejected", "reply_lost"])
def test_single_platform_task_keeps_partial_images_and_recovers_one_original_id(tmp_path, last_attempt):
    app = tmp_path / "install/releases/fixture"
    (app / "static").mkdir(parents=True)
    (app / "main.py").write_text("# fixture", encoding="utf-8")
    script = BOOTSTRAP + r'''
from io import BytesIO
from PIL import Image
from enterprise.canvas_task_journal import CanvasTaskJournal
from enterprise.generation_tasks import describe_task

last_attempt=sys.argv[4]
post_count=0
recovering=False
task_id='canvas_img_'+'a'*32
source_images={}
for index in range(3):
    image=BytesIO()
    Image.new('RGB',(32,32),(50*index,100,200)).save(image,format='PNG')
    source_images[index]=image.getvalue()

def reply(request):
    global post_count
    calls.append((request.method,request.url.path))
    if request.method=='POST':
        assert request.url.path=='/v1/images/generations' and request.url.params['async']=='true'
        body=json.loads(request.content)
        assert body.get('n',1)==1 and body['model']=='gpt-image-2-all'
        post_count+=1
        if post_count<=3:
            return httpx.Response(200,json={'task_id':f'upstream-{post_count-1}'})
        if last_attempt=='rejected':
            return httpx.Response(429,json={'error':{'message':'fixture rate limit'}})
        raise httpx.ReadTimeout('fixture missing fourth reply',request=request)
    assert request.method=='GET'
    if request.url.path.startswith('/v1/images/tasks/'):
        upstream_id=request.url.path.rsplit('/',1)[-1]
        index=int(upstream_id.removeprefix('upstream-'))
        record=main.CANVAS_TASK_JOURNAL.get(task_id)
        assert any(item.get('upstream_task_id')==upstream_id for item in record['provider_receipts'])
        if index==2 and not recovering:
            return httpx.Response(503,json={'message':'fixture temporary query failure'})
        return httpx.Response(200,json={'data':{'task_id':upstream_id,'status':'SUCCESS',
            'data':{'data':[{'url':f'https://supplier.example/result-{index}.png'}]}}})
    index=int(request.url.path.removeprefix('/result-').removesuffix('.png'))
    return httpx.Response(200,content=source_images[index],headers={'content-type':'image/png'})
main.httpx.AsyncClient=lambda **kw:original_client(transport=httpx.MockTransport(reply),**kw)

async def exercise():
    global recovering
    request=main.OnlineImageRequest(request_id='a'*32,provider_id='zhenzhen',model='gpt-image-2-all',
        prompt='four outputs in one local task',n=4)
    initial=await main.create_canvas_image_task(request,None)
    assert initial['task_id']==task_id
    await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
    reopened=CanvasTaskJournal(main.CANVAS_TASK_JOURNAL.root)
    detail=describe_task(reopened.get(task_id),detail=True)
    assert detail['status']=='partial' and detail['output_count']==2 and detail['can_query'],detail
    assert len(detail['attempts'])==4
    unknown=[item for item in detail['attempts'] if not item['upstream_task_id']]
    assert len(unknown)==1 and unknown[0]['status']==('failed' if last_attempt=='rejected' else 'unknown')
    archived={item['url'] for item in detail['items']}
    assert {Path(main.output_file_from_url(url)).read_bytes() for url in archived}=={source_images[0],source_images[1]}
    for auto_state in (None,'waiting','querying'):
        if auto_state:
            reopened.record_auto_recovery(task_id, {'status':auto_state})
        projected=await main.get_canvas_image_task(task_id)
        assert projected['status']=='running'
        assert projected['result']['status']=='partial' and set(projected['result']['images'])==archived
        assert '仍在跟踪' in projected['result']['message']
    reopened.record_auto_recovery(task_id, {'status':'manual'})
    projected=await main.get_canvas_image_task(task_id)
    assert projected['status']=='partial' and set(projected['result']['images'])==archived
    assert projected['result']['message'] and 'provider_receipts' not in projected

    recovering=True
    count=len(calls)
    result=await main.reconcile_canvas_image_task(task_id)
    assert result['status']=='partial' and len(result['images'])==3
    assert archived.issubset(result['images'])
    assert calls[count:]==[('GET','/v1/images/tasks/upstream-2'),('GET','/result-2.png')]
    detail=describe_task(reopened.get(task_id),detail=True)
    assert detail['status']=='partial' and detail['output_count']==3
    projected=await main.get_canvas_image_task(task_id)
    assert projected['status']=='partial' and projected['result']==result
    assert sorted(attempt['upstream_task_id'] for attempt in detail['attempts'])==['','upstream-0','upstream-1','upstream-2']
    duplicate=await main.create_canvas_image_task(request,None)
    assert duplicate['task_id']==task_id and post_count==4
    count=len(calls)
    assert await main.reconcile_canvas_image_task(task_id)==result
    assert len(calls)==count
asyncio.run(exercise())
'''
    result = subprocess.run([sys.executable, "-c", script, str(ROOT), str(tmp_path / "install"),
                             str(tmp_path / "local"), last_attempt], cwd=ROOT,
                            env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"),
                            capture_output=True, encoding="utf-8", timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr


def test_normal_image_requests_have_no_shared_or_per_user_admission_limit(tmp_path):
    app = tmp_path / 'install/releases/fixture'
    (app / 'static').mkdir(parents=True)
    (app / 'main.py').write_text('# fixture', encoding='utf-8')
    script = BOOTSTRAP + r'''
import base64
from io import BytesIO
from PIL import Image
from enterprise.generation_tasks import describe_task
buffer=BytesIO();Image.new('RGBA',(16,16),(20,140,80,160)).save(buffer,'PNG')
encoded=base64.b64encode(buffer.getvalue()).decode()
posts=[]
all_sent=asyncio.Event()
release=asyncio.Event()
async def concurrent(request):
    if request.method=='POST':
        posts.append(request)
        index=len(posts)
        if index==16:all_sent.set()
        await release.wait()
        return httpx.Response(200,json={'task_id':f'parallel-{index}'})
    assert request.method=='GET' and '/v1/images/tasks/parallel-' in request.url.path
    return httpx.Response(200,json={'status':'SUCCESS','data':[{'b64_json':encoded}]})
main.httpx.AsyncClient=lambda **kw:original_client(transport=httpx.MockTransport(concurrent),**kw)
async def run():
    requests=[main.OnlineImageRequest(request_id=character*32,provider_id='zhenzhen',model='gpt-image-2-all',
        prompt='parallel API production fixture',n=8) for character in ['a','b']]
    receipts=[await main.create_canvas_image_task(payload,None) for payload in requests]
    # All sixteen POSTs must reach the supplier before any receives a reply.
    # A shared cap of two or a per-user cap of one would deadlock this barrier.
    await asyncio.wait_for(all_sent.wait(),timeout=8)
    assert len(posts)==16 and not hasattr(main,'CANVAS_IMAGE_QUEUE')
    release.set()
    await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
    for receipt,payload in zip(receipts,requests):
        row=main.CANVAS_TASK_JOURNAL.get(receipt['task_id'])
        assert row['status']=='succeeded' and 'image_queue' not in row
        assert describe_task(row,detail=True)['output_count']==8
        assert (await main.create_canvas_image_task(payload,None))['task_id']==receipt['task_id']
    assert len(posts)==16
asyncio.run(run())
'''
    result=subprocess.run([sys.executable,'-c',script,str(ROOT),str(tmp_path/'install'),str(tmp_path/'local')],
        cwd=ROOT,env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1'),
        capture_output=True,encoding='utf-8',timeout=40)
    assert result.returncode==0,result.stdout+result.stderr


def test_expired_reference_url_keeps_supplier_error_without_automatic_resubmission(tmp_path):
    app = tmp_path / 'install/releases/fixture'
    (app / 'static').mkdir(parents=True)
    (app / 'main.py').write_text('# fixture', encoding='utf-8')
    script = BOOTSTRAP + r'''
from enterprise.generation_tasks import describe_task
provider['image_models']=['seedream-v5.5']
main.save_api_providers([provider])
url='https://media.example/temporary-image.png?expires=fixture'
def expired(request):
    calls.append((request.method,request.url.path))
    assert request.method=='POST' and json.loads(request.content)['image']==[url]
    return httpx.Response(400,json={'error':{'message':'reference image URL has expired'}})
main.httpx.AsyncClient=lambda **kw:original_client(transport=httpx.MockTransport(expired),**kw)
async def run():
    payload=main.OnlineImageRequest(request_id='c'*32,provider_id='zhenzhen',model='seedream-v5.5',
        prompt='expired reference fixture',size='1024x1024',n=1,reference_images=[{'url':url}])
    created=await main.create_canvas_image_task(payload,None)
    await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
    detail=describe_task(main.CANVAS_TASK_JOURNAL.get(created['task_id']),detail=True)
    assert len(calls)==1 and detail['status']=='failed' and 'URL has expired' in detail['error']
    assert not detail['items']
    assert (await main.create_canvas_image_task(payload,None))['task_id']==created['task_id']
    assert len(calls)==1
asyncio.run(run())
'''
    result=subprocess.run([sys.executable,'-c',script,str(ROOT),str(tmp_path/'install'),str(tmp_path/'local')],
        cwd=ROOT,env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1'),
        capture_output=True,encoding='utf-8',timeout=40)
    assert result.returncode==0,result.stdout+result.stderr
