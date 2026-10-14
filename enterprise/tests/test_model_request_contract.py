"""Execute real request builders with a MockTransport; no provider key or paid request."""
import ast
import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from enterprise.provider_image_profiles import (
    IMAGE_PROFILE_TEMPLATES, ImageProfileError, build_aspect_parameters,
    normalize_image_profile, image_profile_for,
)
from enterprise.providers.zhenzhen import (
    IMAGE_MODELS, image_profile as zhenzhen_image_profile,
    public_image_profiles as zhenzhen_public_image_profiles,
    submit_image as submit_zhenzhen_image,
)
from enterprise.providers.submission import (
    submission_json, image_api_explicitly_rejected, provider_submission_unknown,
)


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def builders():
    names = {
        'parse_size_pair', 'apimart_size_resolution', 'aspect_image_parameters',
        'gemini_image_config', 'gemini_model_name', 'generate_ai_image',
        'api_headers',
    }
    tree = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8'))
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
             or isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'IMAGE_PROFILE_TEMPLATES' for t in node.targets)]
    provider = {'id':'fixture', 'base_url':'https://provider.invalid', 'protocol':'openai'}
    calls = []
    response_status = [200]

    def transport(request):
        calls.append(request)
        return httpx.Response(response_status[0], json={'data':[{'url':'https://media.invalid/result.png'}]}, request=request)

    client_type = httpx.AsyncClient
    env = {
        're':re, 'HTTPException':HTTPException,
        'IMAGE_PROFILE_TEMPLATES':IMAGE_PROFILE_TEMPLATES, 'ImageProfileError':ImageProfileError,
        'build_aspect_parameters':build_aspect_parameters, 'normalize_image_profile':normalize_image_profile, 'image_profile_for':image_profile_for,
        'zhenzhen_image_profile':zhenzhen_image_profile, 'submit_zhenzhen_image':submit_zhenzhen_image,
        'submission_json':submission_json, 'image_api_explicitly_rejected':image_api_explicitly_rejected,
        'provider_submission_unknown':provider_submission_unknown,
        'httpx':SimpleNamespace(AsyncClient=lambda **kw: client_type(transport=httpx.MockTransport(transport), **kw), Timeout=httpx.Timeout, HTTPError=httpx.HTTPError),
        'get_api_provider':lambda _:provider,
        'selected_model':lambda model, fallback:model or fallback,
        'effective_protocol':lambda p, m:'openai',
        'effective_image_request_mode':lambda p, m:'openai',
        'is_gpt_image_2_model':lambda m:False,
        'is_apimart_provider':lambda p:False,
        'AI_BASE_URL':'', 'AI_REQUEST_TIMEOUT':30,
        'ONLINE_IMAGE_REFERENCE_MAX':16,
        'provider_endpoint_url':lambda p, key, default:p['base_url'] + default,
        'api_headers':lambda **kw:{'Content-Type':'application/json'} if kw.get('json_body',True) else {},
        'provider_env_key_value':lambda _: 'fake-contract-key',
        'bearer_auth_value':lambda key:'Bearer ' + key,
        'extract_image':lambda raw:{'type':'url', 'value':raw['data'][0]['url']},
        'reference_to_data_url':lambda ref, **kwargs:ref['url'],
    }
    for name in ('codex', 'gemini_cli', 'jimeng', 'runninghub', 'volcengine'):
        env[f'is_{name}_provider'] = lambda p:False
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'main.py', 'exec'), env)
    provider['image_profile'] = dict(env['IMAGE_PROFILE_TEMPLATES']['aspect-size'])
    env['fixture_provider'] = provider
    return env, calls, response_status


@pytest.mark.parametrize('ratio', ['auto','16:9','1:1','1:4','1:8','21:9','2:3','3:2','3:4','4:1','4:3','4:5','5:4','8:1','9:16'])
def test_nb21_ratios(builders, ratio):
    env, _, _ = builders
    assert env['aspect_image_parameters'](ratio, env['fixture_provider']['image_profile'])['aspect_ratio'] == ratio


def test_pixel_size_maps_to_supported_aspect_and_resolution(builders):
    env, _, _ = builders
    assert env['aspect_image_parameters']('3648x2048', env['fixture_provider']['image_profile']) == {'aspect_ratio':'16:9', 'image_size':'4K'}
    assert env['gemini_image_config']('auto', 'gemini-nano-banana-2.1', env['fixture_provider']) == {'imageSize':'1K'}
    assert env['gemini_image_config']('2K', 'another-model') == {'aspectRatio':'1:1', 'imageSize':'2K'}


def test_nb21_generation_uses_named_parameters(builders):
    import json
    env, calls, _ = builders
    asyncio.run(env['generate_ai_image']('fixture prompt', '3648x2048', 'high', 'gemini-nano-banana-2.1', provider_id='fixture'))
    assert len(calls) == 1
    body = json.loads(calls[0].content)
    assert body == {'model':'gemini-nano-banana-2.1', 'prompt':'fixture prompt', 'response_format':'url', 'aspect_ratio':'16:9', 'image_size':'4K'}
    assert calls[0].url.path == '/v1/images/generations'
    assert 'Authorization' in calls[0].headers and 'x-goog-api-key' not in calls[0].headers


def test_invalid_aspect_stops_before_provider_request(builders):
    env, calls, _ = builders
    with pytest.raises(HTTPException, match='9:21') as failure:
        asyncio.run(env['generate_ai_image']('fixture prompt', '9:21', '', 'gemini-nano-banana-2.1', provider_id='fixture'))
    assert failure.value.status_code == 400
    assert not calls


def test_edit_uses_multipart_contract_and_never_resubmits_on_failure(builders, tmp_path):
    env, calls, status = builders
    image = tmp_path / 'fixture.png'
    image.write_bytes(b'fixture-image-bytes')
    env.update({'output_file_from_url':lambda url:str(image), 'content_type_for_path':lambda path:'image/png', '__builtins__':__builtins__})
    import os
    env['os'] = os
    status[0] = 400
    with pytest.raises(httpx.HTTPStatusError) as failure:
        asyncio.run(env['generate_ai_image']('fixture edit', '4:5', 'high', 'gemini-nano-banana-2.1', [{'url':'/assets/fixture.png'}], 'fixture'))
    assert failure.value.response.status_code == 400
    assert len(calls) == 1
    assert calls[0].url.path == '/v1/images/edits'
    body = calls[0].content
    assert b'name="aspect_ratio"' in body and b'4:5' in body
    assert b'name="image_size"' in body and b'name="image"' in body
    assert b'name="quality"' not in body and b'name="size"' not in body


def test_other_image_model_keeps_existing_request(builders):
    import json
    env, calls, _ = builders
    env['fixture_provider']['model_image_profiles'] = {'another-model':{'mode':'pixel'}}
    asyncio.run(env['generate_ai_image']('fixture prompt', '1024x1024', 'high', 'another-model', provider_id='fixture'))
    body = json.loads(calls[0].content)
    assert body['size'] == '1024x1024' and body['quality'] == 'high'
    assert 'aspect_ratio' not in body


def test_new_model_inherits_template_without_source_change(builders):
    import json
    env, calls, _ = builders
    asyncio.run(env['generate_ai_image']('fixture prompt', '16:9', '', 'future-model-not-in-source', provider_id='fixture'))
    assert json.loads(calls[0].content)['aspect_ratio'] == '16:9'
    env['fixture_provider']['model_image_profiles'] = {'future-model-not-in-source':{'mode':'aspect-size','ratios':['3:1'],'resolutions':['1K']}}
    asyncio.run(env['generate_ai_image']('fixture prompt', '3:1', '', 'future-model-not-in-source', provider_id='fixture'))
    assert json.loads(calls[1].content)['aspect_ratio'] == '3:1'


def test_explicit_ratio_and_resolution_are_not_guessed_from_pixels(builders):
    import json
    env, calls, _ = builders
    asyncio.run(env['generate_ai_image']('fixture prompt', '1024x8192', '', 'future-model-not-in-source', provider_id='fixture', image_parameters={'aspect_ratio':'1:8','resolution':'1K'}))
    body = json.loads(calls[0].content)
    assert body['aspect_ratio'] == '1:8' and body['image_size'] == '1K'


@pytest.mark.parametrize('explicit_clear', [False, True])
def test_older_provider_settings_do_not_erase_capability_profiles(explicit_clear):
    tree = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8'))
    node = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'save_providers')
    node.decorator_list = []
    node.returns = None
    for argument in node.args.args:
        argument.annotation = None
    existing = {'id':'fixture', 'image_profile':{'mode':'aspect-size'}, 'model_image_profiles':{'exception':{'mode':'pixel'}}}
    body = {'id':' FIXTURE ', 'image_profile':{}, 'model_image_profiles':{}}
    submitted = body if explicit_clear else {'id':body['id']}
    item = SimpleNamespace(id=body['id'], primary=False, clear_key=False, api_key=None,
                           dict=lambda **kwargs: dict(submitted if kwargs.get('exclude_unset') else body))
    saved = []
    env = {
        'load_api_providers':lambda:[existing],
        'normalize_provider':lambda value:{**value,'id':value['id'].strip().lower()},
        'save_api_providers':lambda values:saved.extend(values),
        'provider_key_env':lambda value:'FIXTURE_KEY', 'public_provider':lambda value:value,
        'HTTPException':HTTPException,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'main.py', 'exec'), env)
    asyncio.run(env['save_providers']([item]))
    for field in ('image_profile','model_image_profiles'):
        assert saved[0][field] == ({} if explicit_clear else existing[field])


@pytest.mark.parametrize('model', list(IMAGE_MODELS))
def test_zhenzhen_builtin_text_and_reference_requests_need_no_template(builders, model):
    import json
    env, calls, _ = builders
    provider = env['fixture_provider']
    provider.update(base_url='https://ai.t8star.org', image_profile={}, model_image_profiles={})
    for references in ([], [{'url':'data:image/png;base64,ZmFrZQ=='}]):
        asyncio.run(env['generate_ai_image']('fixture prompt', '1024x1024', 'high', model, references, 'fixture', {'aspect_ratio':'1:1', 'resolution':'2K'}))
    assert len(calls) == 2
    for request in calls:
        body = json.loads(request.content)
        assert request.url.path == '/v1/images/generations'
        profile = IMAGE_MODELS[model]
        if profile['mode'] == 'aspect-size':
            assert body['aspect_ratio'] == '1:1' and 'size' not in body
            assert ('image_size' in body) == profile['supports_image_size']
            if profile['supports_image_size']:
                assert body['image_size'] == '2K'
        else:
            assert body['size'] == '1024x1024' and 'image_size' not in body
        assert ('quality' in body) == profile['supports_quality']
    assert json.loads(calls[1].content)['image'] == ['data:image/png;base64,ZmFrZQ==']


def test_builtin_contract_overrides_stale_templates_only_on_verified_supplier(builders):
    env, calls, _ = builders
    provider = env['fixture_provider']
    provider.update(base_url='https://ai.t8star.org', image_profile={'mode':'pixel'}, model_image_profiles={'gemini-nano-banana-2.1':{'mode':'pixel'}})
    assert image_profile_for(provider, 'gemini-nano-banana-2.1')['mode'] == 'aspect-size'
    with pytest.raises(HTTPException, match='9:21'):
        asyncio.run(env['generate_ai_image']('fixture prompt', '9:21', '', 'gemini-nano-banana-2.1', provider_id='fixture'))
    assert not calls
    provider['base_url'] = 'https://ai.t8star.org.example.invalid'
    assert image_profile_for(provider, 'gemini-nano-banana-2.1') == {'mode':'pixel'}
    provider['id'] = 'zhenzhen'
    assert image_profile_for(provider, 'gemini-nano-banana-2.1')['mode'] == 'aspect-size'


def test_zhenzhen_reference_error_never_retries_paid_submission(builders):
    env, calls, status = builders
    env['fixture_provider'].update(base_url='https://ai.t8star.org', image_profile={})
    status[0] = 400
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(env['generate_ai_image']('fixture prompt', '16:9', '', 'gemini-nano-banana-2.1', [{'url':'https://media.invalid/input.png'}], 'fixture'))
    assert len(calls) == 1 and calls[0].url.path == '/v1/images/generations'


def test_builtin_projection_contains_only_selected_models_and_no_keys():
    provider = {'id':'zhenzhen', 'image_models':['nano-banana','gemini-3.1-flash-image','new-model'], 'api_key':'fake-key'}
    projected = zhenzhen_public_image_profiles(provider)
    assert set(projected) == {'nano-banana', 'gemini-3.1-flash-image'}
    assert projected['nano-banana']['supports_image_size'] is False
    assert '512' in projected['gemini-3.1-flash-image']['resolutions']
    assert 'fake-key' not in str(projected)


def test_builtin_generation_contract_is_independent_of_old_platform_protocol(builders):
    env, calls, _ = builders
    env['fixture_provider'].update(base_url='https://ai.t8star.org', image_profile={})
    env['effective_protocol'] = lambda provider, model:'gemini'
    asyncio.run(env['generate_ai_image']('fixture prompt', '16:9', '', 'nano-banana', provider_id='fixture'))
    assert calls[0].url.path == '/v1/images/generations'
    assert 'Authorization' in calls[0].headers and 'x-goog-api-key' not in calls[0].headers
