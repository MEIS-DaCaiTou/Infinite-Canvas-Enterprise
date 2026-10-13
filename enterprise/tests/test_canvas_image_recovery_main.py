"""Actual main hooks survive a hard exit immediately after supplier acceptance."""
import os
from pathlib import Path
import subprocess
import sys


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
