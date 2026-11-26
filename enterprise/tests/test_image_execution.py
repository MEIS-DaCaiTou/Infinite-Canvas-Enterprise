"""The extracted executor can run without main, the business DB or DPAPI."""
import asyncio
import httpx
import pytest
from fastapi import HTTPException

from enterprise.providers.image_execution import poll_image_task
from enterprise.providers.zhenzhen import execute_image as execute_zhenzhen_image


def image(raw):
    values = raw.get('data')
    if isinstance(values, list) and values:
        return values[0]
    raise HTTPException(502, 'No image')


@pytest.mark.parametrize('async_mode', [False, True])
def test_one_submit_and_persist_before_original_query_keep_all_outputs(async_mode):
    events = []
    results = [{'url': 'https://media.invalid/one.png'}, {'b64_json': 'alpha-png-fixture', 'x': 10}]
    class Sink:
        def identify(self, *args, **kwargs): pass
        async def accepted(self, key, provider): events.append(('persist', key))
    def handler(request):
        events.append((request.method, request.url.path))
        return httpx.Response(200, json={'task_id': 'original', 'data': results} if async_mode else {'data': results})
    async def wait(client, key, provider):
        assert events[-1] == ('persist', 'original')
        events.append(('query', key))
        return {'status': 'SUCCESS', 'data': results}
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await execute_zhenzhen_image(client, 'https://supplier.invalid/v1/images/generations', {},
                provider={'id':'fixture'}, model='seedream-v5.5', prompt='owned fixture', size='1024x1024',
                quality='', references=[], aspect_parameters=None, extract_image=image,
                extract_task_id=lambda raw:raw.get('task_id'), wait_for_task=wait,
                receipt_sink=Sink(), async_endpoints=['https://supplier.invalid/v1/images/generations'] if async_mode else ['https://supplier.invalid/v1/images/edits?async=true'])
    first, raw = asyncio.run(run())
    assert first == results[0] and raw['data'] == results
    assert len([event for event in events if event[0] == 'POST']) == 1
    assert ('query', 'original') in events if async_mode else len(events) == 1


@pytest.mark.parametrize('mode', ['lost-submit', 'lost-query', 'request-id-only'])
def test_unknown_response_never_submits_again(mode):
    posts = []
    def handler(request):
        posts.append(request)
        if mode == 'lost-submit': raise httpx.ReadError('fixture disconnected')
        return httpx.Response(200, json={'task_id':'original'} if mode == 'lost-query' else {'id':'request-id-only'})
    async def wait(*args): raise httpx.ReadError('fixture query disconnected')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await execute_zhenzhen_image(client, 'https://supplier.invalid/v1/images/generations?async=true', {},
                provider={'id':'fixture'}, model='seedream-v5.5', prompt='owned fixture', size='1024x1024',
                quality='', references=[], aspect_parameters=None, extract_image=image,
                extract_task_id=lambda raw:raw.get('id'), wait_for_task=wait,
                async_endpoints=['https://supplier.invalid/v1/images/generations?async=true'])
    with pytest.raises(HTTPException) as error: asyncio.run(run())
    assert error.value.submission_unknown and len(posts) == 1
    if mode == 'lost-query': assert error.value.upstream_task_id == 'original'


def test_poll_original_task_states_and_explicit_failure():
    replies = iter([{'status':'IN_PROGRESS'}, {'status':'FAILURE', 'fail_reason':'fixture upstream rejected'}])
    async def fetch(client, key, provider):
        assert key == 'original'
        return next(replies)
    with pytest.raises(HTTPException) as error:
        asyncio.run(poll_image_task(None, 'original', {}, timeout=1, interval=0, initial_delay=0,
                                   fetch_payload=fetch, extract_image=image))
    assert error.value.provider_task_failed and 'fixture upstream rejected' in error.value.detail
