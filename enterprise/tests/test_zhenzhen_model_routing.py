"""Supplier contract and original-task recovery; synthetic media, no paid calls."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from enterprise.providers import zhenzhen_video as adapter
from enterprise.providers.model_catalog import classify_model, correct_known_groups
from enterprise.providers.video_generation import generate_json_video, video_error_detail
from enterprise.tests.test_canvas_image_recovery_main import BOOTSTRAP, ROOT


def payload(**changes):
    values = dict(prompt="owned fixture", duration=5, aspect_ratio="16:9", resolution="",
        enhance_prompt=False, enable_upsample=False, watermark=False, seed=None,
        camerafixed=False, return_last_frame=False, generate_audio=False, multimodal=False)
    return SimpleNamespace(**(values | changes))


@pytest.mark.parametrize("model,expected", [("MiniMax-H3", "video"), ("kling-image-v3", "image"),
    ("kling-image-v1", "image"), ("kling-multi-image2image", "image"), ("grok-imagine-video", "video"),
    ("veo3-fast", "video"), ("gpt-image-2", "image"), ("custom-chat", "chat")])
def test_model_classification(model, expected):
    assert classify_model(model) == expected


def test_repair_known_groups_preserves_manual_choices_and_source_ids():
    groups = {"chat": ["custom", "MiniMax-H3"], "image": ["custom-image"], "video": ["kling-image-v3", "veo3-fast"]}
    assert correct_known_groups(groups) == {"chat": ["custom"], "image": ["custom-image", "kling-image-v3"], "video": ["MiniMax-H3", "veo3-fast"]}
    assert groups["chat"][-1] == "MiniMax-H3" and groups["video"][0] == "kling-image-v3"


@pytest.mark.parametrize("model,extra", [
    ("grok-imagine-video-1.5", {"seconds": "5", "images": ["https://media.invalid/one.png"], "resolution": "480p"}),
    ("MiniMax-H3", {"seconds": "5", "imageUrls": ["https://media.invalid/one.png"], "resolution": "768P"}),
    ("wan3.0-video", {"duration": 5, "image_urls": ["https://media.invalid/one.png"], "resolution": "480P", "prompt_extend": False, "audio": False, "watermark": False}),
    ("grok-imagine-video", {"duration": 5, "image": {"url": "https://media.invalid/one.png"}, "resolution": "480p"}),
])
def test_model_contract_uses_its_own_media_duration_and_resolution(model, extra):
    assert adapter.video_body(payload(), model, ["https://media.invalid/one.png"], [], []) == {
        "model": model, "prompt": "owned fixture", "aspect_ratio": "16:9", **extra}
    paths = adapter.submit_endpoints("https://supplier.invalid/proxy", model)
    assert paths == ["https://supplier.invalid/proxy/" + ("xai/v1/videos/generations" if model == "grok-imagine-video" else "v1/videos")]
    query = adapter.query_endpoints("https://supplier.invalid/proxy", "opaque%2Fid", submit_url=paths[0])
    assert query == ["https://supplier.invalid/proxy/" + ("xai/v1/videos/" if model == "grok-imagine-video" else "v1/videos/") + "opaque%2Fid"]


def test_legacy_contract_and_native_request_identity_are_kept():
    assert adapter.submit_endpoints("https://supplier.invalid", "veo3-fast") == [
        "https://supplier.invalid/v2/videos/generations", "https://supplier.invalid/v1/videos/generations"]
    assert adapter.request_id({"request_id": "original"}) == "original"
    assert adapter.request_id({"data": {"id": "opaque"}}) == "opaque"
    assert adapter.request_id({"id": True}) is None


@pytest.mark.parametrize("change,model,images,videos,audios", [
    ({"duration": 4}, "MiniMax-H3", [], [], []),
    ({"resolution": "480p"}, "MiniMax-H3", [], [], []),
    ({"aspect_ratio": "21:9"}, "wan3.0-video", [], [], []),
    ({"generate_audio": True}, "grok-imagine-video-1.5", [], [], []),
    ({}, "grok-imagine-video-1.5", [], ["https://media.invalid/ref.mp4"], []),
    ({}, "MiniMax-H3", ["https://media.invalid/ref.png"] * 10, [], []),
    ({}, "MiniMax-H3", [], [], ["/assets/local.wav"]),
    ({"duration": 31}, "wan3.0-video", [], [], []),
    ({"resolution": "1080p"}, "grok-imagine-video-1.5", ["https://m.invalid/ref.png"] * 2, [], []),
])
def test_invalid_capabilities_fail_before_submission(change, model, images, videos, audios):
    p = payload(); p.__dict__.update(change)
    with pytest.raises(HTTPException) as exc:
        adapter.video_body(p, model, images, videos, audios)
    assert exc.value.status_code == 400


def test_native_reference_and_multimodal_fields_are_not_silently_dropped():
    p = payload(); p.multimodal = True
    body = adapter.video_body(p, "MiniMax-H3", ["https://m.invalid/image"], ["https://m.invalid/video"], ["https://m.invalid/audio"])
    assert body["audioUrls"] and body["videoUrls"] and body["mode"] == "multimodal-to-video"
    body = adapter.video_body(p, "grok-imagine-video", ["https://m.invalid/a", "https://m.invalid/b"], [], [])
    assert body["reference_images"] == [{"url": "https://m.invalid/a"}, {"url": "https://m.invalid/b"}]
    p.duration = 11
    with pytest.raises(HTTPException, match="10 秒"):
        adapter.video_body(p, "grok-imagine-video", ["https://m.invalid/a"], [], [])


@pytest.mark.parametrize("reply", [404, 405, 503, "timeout", {}])
def test_selected_new_protocol_never_falls_back_to_another_paid_endpoint(reply):
    async def run():
        calls = []
        def handler(request):
            calls.append(request)
            if reply == "timeout":
                raise httpx.ReadTimeout("owned response loss", request=request)
            return httpx.Response(reply) if isinstance(reply, int) else httpx.Response(200, json=reply)
        async def accepted(*_): pass
        async def poll(*_): pytest.fail("no accepted identity")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises((HTTPException, httpx.HTTPError)):
                await generate_json_video(client, adapter.submit_endpoints("https://supplier.invalid", "MiniMax-H3"), {}, {},
                    extract_task_id=adapter.request_id, output_urls=lambda _: [], accepted=accepted, poll=poll)
        assert len(calls) == 1 and calls[0].url.path == "/v1/videos"
    asyncio.run(run())


@pytest.mark.parametrize("model,path,mode", [("grok-imagine-video-1.5", "/v1/videos", adapter.V1),
    ("MiniMax-H3", "/v1/videos", adapter.V1), ("wan3.0-video", "/v1/videos", adapter.V1),
    ("grok-imagine-video", "/xai/v1/videos/generations", adapter.XAI)])
def test_actual_main_acceptance_survives_exit_and_only_queries_original_protocol(tmp_path, model, path, mode):
    install = tmp_path / "install"; app = install / "releases/fixture"
    (app / "static").mkdir(parents=True); (app / "main.py").write_text("# owned fixture", encoding="utf8")
    args = [str(ROOT), str(install), str(tmp_path / "local")]
    setup = f"\nmodel={model!r}; path={path!r}; mode={mode!r}\n" + r'''
from enterprise import db
main.provider_env_key_value=lambda _: 'fixture-only-key'
db.record_canvas_image_task_owner=lambda *_:None
db.record_task_owner=lambda *a,**kw:None
provider['video_models']=[model]
'''
    writer = BOOTSTRAP + setup + r'''
def reply(request):
    calls.append((request.method, request.url.path))
    assert request.method=='POST' and request.url.path==path
    body=json.loads(request.content)
    assert body['model']==model and request.headers['authorization']=='Bearer fixture-only-key'
    return httpx.Response(200,json={'request_id':'original-video'} if mode.endswith('xai-v1') else {'id':'original-video','status':'queued'})
main.httpx.AsyncClient=lambda **kw:original_client(transport=httpx.MockTransport(reply),**kw)
async def exit_before_poll(*_):
    record=main.CANVAS_TASK_JOURNAL.get(id_path.read_text())
    receipt=record['provider_receipts'][0]
    assert receipt['upstream_task_id']=='original-video' and receipt['video_query_mode']==mode,receipt
    assert 'fixture-only-key' not in json.dumps(record)
    os._exit(27)
main.wait_for_video_task=exit_before_poll
async def run():
    result=await main.create_canvas_video_task(main.CanvasVideoRequest(provider_id='zhenzhen',model=model,prompt='owned fixture'),None)
    id_path.write_text(result['task_id'])
    await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
asyncio.run(run())
'''
    env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    first = subprocess.run([sys.executable, "-c", writer, *args], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf8", timeout=45)
    assert first.returncode == 27, first.stdout + first.stderr
    reader = BOOTSTRAP + setup + r'''
def reply(request):
    calls.append((request.method,request.url.path))
    expected='/xai/v1/videos/original-video' if mode.endswith('xai-v1') else '/v1/videos/original-video'
    assert request.method=='GET' and request.url.path==expected
    return httpx.Response(200,json={'status':'done','video':{'url':'https://supplier.example/result.mp4'}})
main.httpx.AsyncClient=lambda **kw:original_client(transport=httpx.MockTransport(reply),**kw)
async def archive(url):
    (Path(main.OUTPUT_DIR)/'recovered.mp4').write_bytes(b'owned result')
    return '/output/recovered.mp4'
main.save_remote_video_to_output=archive
main.CANVAS_VIDEO_TASKS.archive=archive
assert main.CANVAS_TASK_JOURNAL.recover()['interrupted']==1
async def run():
    task_id=id_path.read_text()
    result=await main.reconcile_canvas_video_task(task_id)
    assert result['status']=='succeeded',result
    assert result['videos']==['/output/recovered.mp4']
    assert await main.reconcile_canvas_video_task(task_id)==result
    assert len(calls)==1
asyncio.run(run())
'''
    second = subprocess.run([sys.executable, "-c", reader, *args], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf8", timeout=45)
    assert second.returncode == 0, second.stdout + second.stderr


def test_error_text_does_not_confuse_route_catalog_or_claim_recharging_fixes_access():
    provider = {"id": "zhenzhen"}
    assert "不是整个平台" in video_error_detail("not in [old-model]", provider, "new-model")
    assert "不能证明充值" in video_error_detail("model_not_found", provider, "new-model")
