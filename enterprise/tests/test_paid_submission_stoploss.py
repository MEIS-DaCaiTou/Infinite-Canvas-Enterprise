"""Paid-submit stop-loss contracts use an isolated runtime and fake upstream."""

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def test_paid_submissions_are_not_replayed_after_ambiguous_responses(tmp_path):
    install = tmp_path / "install"
    app = install / "releases" / "fixture"
    (app / "static").mkdir(parents=True)
    (app / "main.py").write_text("# fixture", encoding="utf-8")
    script = r'''
import asyncio, sys
from pathlib import Path
import httpx
from PIL import Image
sys.path.insert(0, sys.argv[1])
from enterprise.paths import PortableRootInputs, derive_portable_path_roots, install_path_roots_for_process, prepare_application_directories
roots = derive_portable_path_roots(PortableRootInputs(Path(sys.argv[2]), Path(sys.argv[3])), 'fixture')
install_path_roots_for_process(roots)
prepare_application_directories(roots)
import main
from enterprise.canvas_task_journal import CanvasTaskJournal

provider = {'id': 'fixture', 'name': 'Fixture', 'base_url': 'https://example.test/v1',
            'image_request_mode': 'openai', 'image_models': ['test-model']}
main.get_api_provider = lambda _id='fixture': provider
main.api_headers = lambda **kwargs: {}
main.provider_env_key_value = lambda _id: 'fixture-key'
reference = Path(main.OUTPUT_DIR) / 'ref.png'
Image.new('RGB', (1, 1), 'white').save(reference)
main.output_file_from_url = lambda _url: str(reference)
real_client = httpx.AsyncClient
calls = []

def use_handler(handler):
    calls.clear()
    def tracked(request):
        calls.append((request.method, request.url.path))
        return handler(request)
    main.httpx.AsyncClient = lambda **kwargs: real_client(transport=httpx.MockTransport(tracked))

async def check():
    class RetryClient:
        def __init__(self): self.count = 0
        async def request(self, method, url, **kwargs):
            self.count += 1
            return httpx.Response(503 if self.count == 1 else 200,
                                  request=httpx.Request(method, url))
    client = RetryClient()
    try:
        await main.httpx_request_with_transient_retries(client, 'POST', 'https://example.test/images', attempts=2)
        raise AssertionError('POST retry was accepted')
    except ValueError:
        assert client.count == 0
    response = await main.httpx_request_with_transient_retries(client, 'GET', 'https://example.test/task', attempts=2, retry_delay=0)
    assert response.status_code == 200 and client.count == 2

    def lost_reply(request):
        raise httpx.ReadTimeout('lost response', request=request)
    use_handler(lost_reply)
    try:
        await main.generate_ai_image('fixture', '1024x1024', '', 'test-model', [{'url': '/output/ref.png'}], 'fixture')
        raise AssertionError('ambiguous edit was treated as success')
    except main.HTTPException as error:
        assert getattr(error, 'submission_unknown', False)
    assert len(calls) == 1 and calls[0][1].endswith('/images/edits')

    use_handler(lambda request: httpx.Response(503, request=request, text='unavailable'))
    try:
        await main.build_online_image_result(main.OnlineImageRequest(
            prompt='fixture', provider_id='fixture', model='test-model',
            reference_images=[{'url': '/output/ref.png'}]))
        raise AssertionError('HTTP 503 must not trigger another paid submission')
    except main.HTTPException as error:
        assert getattr(error, 'submission_unknown', False)
    assert len(calls) == 1 and calls[0][1].endswith('/images/edits')

    def rejected_then_accepted(request):
        if request.url.path.endswith('/images/edits'):
            return httpx.Response(404, request=request, text='images api is not supported')
        return httpx.Response(200, request=request, json={'data': [{'url': 'https://example.test/result.png'}]})
    use_handler(rejected_then_accepted)
    result, _raw = await main.generate_ai_image('fixture', '1024x1024', '', 'test-model',
                                                [{'url': '/output/ref.png'}], 'fixture')
    assert result == {'type': 'url', 'value': 'https://example.test/result.png'}, repr((result, calls))
    assert [path for _method, path in calls] == ['/v1/images/edits', '/v1/images/generations'], repr(calls)

    provider['image_request_mode'] = 'openai-video-proxy'
    use_handler(lambda request: httpx.Response(503, request=request, text='unavailable'))
    try:
        await main.build_online_image_result(main.OnlineImageRequest(prompt='fixture', provider_id='fixture', model='test-model'))
        raise AssertionError('video-proxy submit was retried')
    except main.HTTPException as error:
        assert getattr(error, 'submission_unknown', False)
    assert len(calls) == 1 and calls[0][1].endswith('/videos')

    provider['image_request_mode'] = 'openai'
    use_handler(lambda request: httpx.Response(200, request=request, text='<html>gateway</html>', headers={'content-type': 'text/html'}))
    try:
        await main.canvas_video(main.CanvasVideoRequest(prompt='fixture', provider_id='fixture', model='test-model'))
        raise AssertionError('HTML success must not trigger a second video submission')
    except main.HTTPException as error:
        assert getattr(error, 'submission_unknown', False)
    assert len(calls) == 1

    use_handler(lambda request: httpx.Response(503, request=request, text='unavailable'))
    try:
        await main.canvas_video(main.CanvasVideoRequest(prompt='fixture', provider_id='fixture', model='test-model'))
        raise AssertionError('video HTTP 503 must not trigger another submission')
    except main.HTTPException as error:
        assert getattr(error, 'submission_unknown', False)
    assert len(calls) == 1

    journal = CanvasTaskJournal(roots.DATA_ROOT / 'stoploss-tasks')
    journal.create({'id': 'unknown', 'type': 'online-image', 'status': 'queued'})
    main.CANVAS_TASK_JOURNAL = journal
    async def unknown_result(_payload):
        raise main.provider_submission_unknown('fixture unknown')
    main.build_online_image_result = unknown_result
    await main.run_canvas_image_task('unknown', main.OnlineImageRequest(prompt='fixture'))
    record = journal.get('unknown')
    assert record['status'] == 'failed'
    assert record['recovery_required'] is True
    assert record['error_code'] == 'PROVIDER_SUBMISSION_UNKNOWN'
    assert journal.mark_running('unknown') is False

asyncio.run(check())
print('paid submit stop-loss passed')
'''
    completed = subprocess.run(
        [sys.executable, "-c", script, str(ROOT), str(install), str(tmp_path / "local")],
        cwd=ROOT, capture_output=True, text=True,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), timeout=40,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "paid submit stop-loss passed" in completed.stdout
