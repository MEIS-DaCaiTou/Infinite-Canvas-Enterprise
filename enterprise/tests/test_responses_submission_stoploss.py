"""Exercise actual Responses helpers with HTTP entirely confined to MockTransport."""
import ast
import asyncio
import json
from pathlib import Path
import time
import urllib.parse

import httpx
import pytest


def helpers():
    tree = ast.parse((Path(__file__).resolve().parents[2] / 'main.py').read_text(encoding='utf-8'))
    selected = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {
        '_responses_wrap', 'post_openai_responses', 'post_openai_responses_stream'
    }]
    scope = {'httpx': httpx, 'asyncio': asyncio, 'json': json, 'time': time, 'urllib': urllib,
             'RESPONSES_REJECT_STATUSES': {400, 404, 405, 415, 422},
             'RESPONSES_POLL_INTERVAL': 0, 'RESPONSES_POLL_MAX_SECONDS': 1}
    exec(compile(ast.Module(body=selected, type_ignores=[]), 'actual_responses_helpers', 'exec'), scope)
    return scope


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
