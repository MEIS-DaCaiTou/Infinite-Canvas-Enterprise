"""RunningHub video protocol: accepted identity, query-only POST, no paid traffic."""
import asyncio

import httpx
import pytest

from enterprise.providers import runninghub_video as rh


@pytest.mark.parametrize("reply,status", [
    ({"taskId":"original", "status":"QUEUED"}, "queued"),
    ({"taskId":"original", "status":"RUNNING", "results":[{"url":"https://cdn.invalid/preview.jpg"}]}, "running"),
    ({"taskId":"original", "status":"SUCCESS", "results":[{"url":"https://cdn.invalid/clip.mp4", "outputType":"mp4"}]}, "succeeded"),
    ({"taskId":"original", "status":"FAILED", "results":[{"url":"https://cdn.invalid/old.mp4"}], "errorMessage":"generation failed"}, "failed"),
    ({"taskId":"other", "status":"SUCCESS", "results":[{"url":"https://cdn.invalid/clip.mp4"}]}, "manual"),
    ({"status":"SUCCESS", "results":[{"url":"https://cdn.invalid/signed", "outputType":"jpg"}]}, "manual"),
    ({"errorCode":"INVALID_KEY", "results":[]}, "manual"),
    ({"status":"FUTURE_STATE", "results":[{"url":"https://cdn.invalid/clip.mp4"}]}, "manual"),
])
def test_query_status_requires_confirmed_video_result(reply, status):
    assert rh.video_result(reply, "original")["status"] == status


def test_video_results_exclude_thumbnails_audio_and_keep_original_order():
    raw={"status":"SUCCESS", "results":[
        {"url":"https://cdn.invalid/thumb.jpg", "outputType":"jpg"},
        {"url":"https://cdn.invalid/signed-video", "outputType":"mp4"},
        {"url":"https://cdn.invalid/audio.wav", "outputType":"wav"},
        {"url":"https://cdn.invalid/signed-unknown", "outputType":"zip"},
        {"url":"https://cdn.invalid/clip.mp4"},
        {"url":"https://cdn.invalid/clip.mp4"}]}
    assert rh.video_urls(raw)==["https://cdn.invalid/signed-video", "https://cdn.invalid/clip.mp4"]


@pytest.mark.parametrize("reply", ["html", {}, [], {"status":"UNKNOWN"}, "network", "http503"])
def test_unknown_submission_posts_once_without_protocol_fallback(reply):
    async def run():
        calls, accepted=[], []
        def handler(request):
            calls.append((request.method,request.url.path))
            if reply=="network": raise httpx.ReadTimeout("lost acceptance",request=request)
            if reply=="html": return httpx.Response(200,text='<html>gateway</html>')
            if reply=="http503": return httpx.Response(503)
            return httpx.Response(200,json=reply)
        async def save(identity): accepted.append(identity)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(Exception) as error:
                await rh.submit_video(client,"https://supplier.invalid/openapi/v2/video-fixture",{}, {"prompt":"fixture"},save)
        assert getattr(error.value,'submission_unknown',False)
        assert calls==[('POST','/openapi/v2/video-fixture')] and accepted==[]
    asyncio.run(run())


def test_submission_with_explicit_failed_task_is_terminal_without_polling():
    async def run():
        calls, accepted=[], []
        def handler(request):
            calls.append(request.url.path)
            return httpx.Response(200,json={"taskId":"original","status":"FAILED","errorMessage":"rejected"})
        async def save(identity): accepted.append(identity)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(Exception) as error:
                await rh.submit_video(client,"https://supplier.invalid/openapi/v2/video-fixture",{}, {},save)
        assert getattr(error.value,'provider_task_failed',False)
        assert accepted==['original'] and calls==['/openapi/v2/video-fixture']
    asyncio.run(run())


def test_acceptance_saved_before_query_and_read_post_uses_only_original_task_id():
    async def run():
        accepted, calls=[], []
        def handler(request):
            calls.append((request.method,request.url.path,request.content))
            if request.url.path.endswith('/query'):
                assert accepted==['original']
                assert request.content==b'{"taskId":"original"}'
                return httpx.Response(200,json={'taskId':'original','status':'SUCCESS',
                    'results':[{'url':'https://cdn.invalid/clip.mp4','outputType':'mp4'}]})
            assert not accepted
            return httpx.Response(200,json={'taskId':'original','status':'RUNNING'})
        async def save(identity): accepted.append(identity)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await rh.submit_video(client,'https://supplier.invalid/openapi/v2/video-fixture',{}, {'prompt':'fixture'},save)
            result=await rh.inspect_video(client,'https://supplier.invalid/openapi/v2/query',{},'original')
        assert result['status']=='succeeded'
        assert [(method,path) for method,path,_ in calls]==[
            ('POST','/openapi/v2/video-fixture'),('POST','/openapi/v2/query')]
    asyncio.run(run())
