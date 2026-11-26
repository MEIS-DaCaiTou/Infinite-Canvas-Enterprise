"""Exercise actual Responses helpers with HTTP entirely confined to MockTransport."""
import asyncio
from functools import partial
import json

import httpx
import pytest


def helpers():
    from enterprise.providers.responses_images import submit
    return {'post_openai_responses': partial(submit, poll_interval=0, poll_max_seconds=1)}


@pytest.mark.parametrize('explicit_rejections', [0, 1])
def test_lost_generation_reply_does_not_trigger_another_post(explicit_rejections):
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) <= explicit_rejections:
            return httpx.Response(400, json={'error': 'unsupported background'}, request=request)
        raise httpx.ReadTimeout('fixture lost generation reply', request=request)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(httpx.ReadTimeout):
                await helpers()['post_openai_responses'](client, 'https://fixture.test/v1/responses', {}, {'model': 'fixture'})
    asyncio.run(run())
    assert len(calls) == explicit_rejections + 1
    assert all(request.method == 'POST' for request in calls)


def test_only_explicit_rejections_allow_protocol_negotiation():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response([400, 415, 200][len(calls)-1], json={'output': []}, request=request)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert (await helpers()['post_openai_responses'](client, 'https://fixture.test/v1/responses', {}, {})).status_code == 200
    asyncio.run(run())
    assert len(calls) == 3
    assert json.loads(calls[0].content)['background'] is True
    assert json.loads(calls[1].content)['stream'] is True
    assert json.loads(calls[2].content) == {}


def test_server_error_does_not_trigger_protocol_fallback():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(503, request=request)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert (await helpers()['post_openai_responses'](client, 'https://fixture.test/v1/responses', {}, {})).status_code == 503
    asyncio.run(run())
    assert len(calls) == 1
