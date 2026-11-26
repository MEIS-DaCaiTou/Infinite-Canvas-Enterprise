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
    normalize_image_profile, image_profile_for, validate_image_size,
)
from enterprise.providers.zhenzhen import (
    configure_provider as configure_zhenzhen_provider,
    IMAGE_MODELS, image_profile as zhenzhen_image_profile,
    public_image_profiles as zhenzhen_public_image_profiles,
    submit_image as submit_zhenzhen_image,
    image_headers as zhenzhen_image_headers,
    execute_image as execute_zhenzhen_image,
    image_submission_task_id as zhenzhen_image_submission_task_id,
    async_image_submit_url as zhenzhen_async_image_submit_url, is_zhenzhen,
)
from enterprise.providers.submission import (
    submission_json, image_api_explicitly_rejected, provider_submission_unknown,
)
from enterprise.providers.image_execution import complete_image_submission
from enterprise.providers.suppliers import configure_provider as configure_builtin_supplier
from enterprise.providers.openai_images import submit_image as submit_openai_image, submit_json_image
from enterprise.image_reference_preparation import edit_reference_files


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
        'validate_image_size':validate_image_size,
        'zhenzhen_image_profile':zhenzhen_image_profile, 'submit_zhenzhen_image':submit_zhenzhen_image,
        'zhenzhen_image_headers':zhenzhen_image_headers,
        'submission_json':submission_json, 'image_api_explicitly_rejected':image_api_explicitly_rejected,
        'provider_submission_unknown':provider_submission_unknown,
        'complete_image_submission':complete_image_submission, 'execute_zhenzhen_image':execute_zhenzhen_image,
        'submit_openai_image':submit_openai_image, 'submit_json_image':submit_json_image,
        'edit_reference_files':edit_reference_files,
        'zhenzhen_image_submission_task_id':zhenzhen_image_submission_task_id,
        'extract_task_id':lambda raw:None, 'wait_for_image_task':None,
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
    env.update({'image_reference_file':lambda url:str(image), 'content_type_for_path':lambda path:'image/png', '__builtins__':__builtins__})
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
        'configure_zhenzhen_provider':configure_zhenzhen_provider,
        'configure_builtin_supplier':configure_builtin_supplier,
        'save_api_providers':lambda values:saved.extend(values),
        'provider_key_env':lambda value:'FIXTURE_KEY', 'public_provider':lambda value:value,
        'HTTPException':HTTPException,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'main.py', 'exec'), env)
    asyncio.run(env['save_providers']([item]))
    for field in ('image_profile','model_image_profiles'):
        assert saved[0][field] == ({} if explicit_clear else existing[field])


@pytest.mark.parametrize('model', [name for name, profile in IMAGE_MODELS.items() if not profile.get('min_references')])
def test_zhenzhen_builtin_text_and_reference_requests_need_no_template(builders, model):
    import json
    env, calls, _ = builders
    provider = env['fixture_provider']
    provider.update(base_url='https://ai.t8star.org', image_profile={}, model_image_profiles={})
    for references in ([], [{'url':'data:image/png;base64,ZmFrZQ=='}]):
        asyncio.run(env['generate_ai_image']('fixture prompt', '1024x1024', 'high', model, references, 'fixture', {'aspect_ratio':'1:1', 'resolution':'2K'}))
    assert len(calls) == 2
    for index, request in enumerate(calls):
        profile = IMAGE_MODELS[model]
        edit = index == 1 and profile.get('reference_endpoint') == 'edits'
        assert request.url.path == ('/v1/images/edits' if edit else '/v1/images/generations')
        if edit and profile.get('reference_encoding') == 'multipart':
            assert request.headers['content-type'].startswith('multipart/form-data; boundary=')
            assert b'name="model"' in request.content and model.encode() in request.content
            assert b'name="image"; filename=' in request.content and b'fake' in request.content
            continue
        body = json.loads(request.content)
        if profile['mode'] == 'aspect-size':
            assert body['aspect_ratio'] == '1:1' and 'size' not in body
            assert ('image_size' in body) == profile['supports_image_size']
            if profile['supports_image_size']:
                assert body['image_size'] == '2K'
        else:
            assert body['size'] == '1024x1024' and 'image_size' not in body
        assert ('quality' in body) == profile['supports_quality']
    if IMAGE_MODELS[model].get('reference_encoding') != 'multipart':
        assert json.loads(calls[1].content)['image'] == ['data:image/png;base64,ZmFrZQ==']


@pytest.mark.parametrize('model', [
    'gemini-nano-banana-2.1', 'gemini-nano-banana-2.1-2k', 'gemini-nano-banana-2.1-4k',
    'gpt-image-2', 'gpt-image-2-all', 'gpt-image-2.5-flare', 'gpt-image-2.5-sunburst',
    'gpt-image-2.6-flare', 'gpt-image-2.6-sunburst', 'nano-banana-2-2k', 'nano-banana-2-4k',
    'nano-banana-pro', 'nano-banana-pro-2k', 'nano-banana-pro-4k', 'seedream-v5-pro', 'seedream-v5.5',
])
def test_production_model_has_authoritative_public_contract(model):
    provider = {'id':'zhenzhen', 'image_models':[model], 'image_profile':{'mode':'pixel'}}
    assert zhenzhen_public_image_profiles(provider)[model] == image_profile_for(provider,model)
    assert IMAGE_MODELS[model]


@pytest.mark.parametrize('model,size,parameters', [
    ('nano-banana-2-2k','768x2048',{}),
    ('gemini-nano-banana-2.1-4k','1024x1024',{'aspect_ratio':'6:17'}),
    ('gpt-image-2','4096x4096',{}),
    ('gpt-image-2.5-flare','1537x1024',{}),
    ('gpt-image-2.5-flare','auto',{}),
    ('gpt-image-2.5-sunburst','auto',{}),
    ('gpt-image-2.6-sunburst','512x512',{}),
    ('gpt-image-2-all','3840x512',{}),
    ('seedream-v5-pro','720x2040',{}),
    ('seedream-v5.5','1024x1024',{'resolution':'4K'}),
])
def test_illegal_production_parameters_make_zero_http_requests(builders,model,size,parameters):
    env,calls,_ = builders
    env['fixture_provider'].update(id='zhenzhen',image_profile={})
    with pytest.raises(HTTPException) as failure:
        asyncio.run(env['generate_ai_image']('fixture',size,'',model,provider_id='zhenzhen',image_parameters=parameters))
    assert failure.value.status_code == 400
    assert not calls


@pytest.mark.parametrize('size,requested,expected', [
    ('1280x544',{},'21:9'), # Legacy preset rounds to 16-pixel boundaries.
    ('1024x1024',{'aspect_ratio':'2000:3000'},'2:3'),
    ('1024x1024',{'aspect_ratio':'21:9'},'21:9'),
])
def test_old_preset_rounding_and_exact_source_ratio(builders,size,requested,expected):
    env,_,_ = builders
    assert env['aspect_image_parameters'](size,IMAGE_MODELS['nano-banana-pro'],requested)['aspect_ratio'] == expected


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


@pytest.mark.parametrize('background', ['auto', 'transparent'])
def test_composer_background_reaches_native_generation(builders, background):
    import json
    env, calls, _ = builders
    env['fixture_provider']['image_profile'] = {'mode':'pixel', 'supports_background':True}
    asyncio.run(env['generate_ai_image']('fixture', '1024x1024', '', 'fixture-image',
        provider_id='fixture', image_parameters={'background_mode':background}))
    body = json.loads(calls[0].content)
    assert len(calls) == 1
    if background == 'transparent':
        assert body['background'] == 'transparent' and body['output_format'] == 'png'
    else:
        assert 'background' not in body and 'output_format' not in body


def test_composer_transparency_is_sent_in_multipart_edits(builders, tmp_path):
    import os
    env, calls, _ = builders
    env['fixture_provider']['image_profile'] = {'mode':'pixel', 'supports_background':True}
    image = tmp_path / 'reference.png'
    image.write_bytes(b'fixture-image')
    env.update(os=os, image_reference_file=lambda _:str(image), content_type_for_path=lambda _:'image/png')
    asyncio.run(env['generate_ai_image']('fixture', '1024x1024', '', 'fixture-image',
        [{'url':'/assets/input/reference.png'}], 'fixture', {'background_mode':'transparent'}))
    assert len(calls) == 1 and calls[0].url.path == '/v1/images/edits'
    assert b'name="background"\r\n\r\ntransparent' in calls[0].content
    assert b'name="output_format"\r\n\r\npng' in calls[0].content


@pytest.mark.parametrize('model', ['seedream-v5.5', 'seedream-v5.5/layer-decomposition'])
@pytest.mark.parametrize('background', ['auto', 'opaque', 'transparent'])
def test_seedream55_native_background_uses_one_json_generation(builders, model, background):
    import json
    env, calls, _ = builders
    env['fixture_provider'].update(id='zhenzhen', image_profile={})
    layers = model.endswith('/layer-decomposition')
    if layers and background != 'auto':
        with pytest.raises(HTTPException):
            asyncio.run(env['generate_ai_image']('fixture', 'auto', '', model,
                [{'url':'data:image/png;base64,ZmFrZQ=='}], 'zhenzhen', {'background_mode':background}))
        assert not calls
        return
    size = 'auto' if layers else '1536x1536'
    asyncio.run(env['generate_ai_image']('fixture', size, 'high', model,
        [{'url':'data:image/png;base64,ZmFrZQ=='}], 'zhenzhen', {'background_mode':background}))
    assert len(calls) == 1 and calls[0].url.path == '/v1/images/generations'
    body = json.loads(calls[0].content)
    assert body['model'] == model and body['size'] == size
    assert body['output_format'] == 'png' and 'quality' not in body and 'n' not in body
    if layers:
        assert 'background' not in body
    else:
        assert body['background'] == background and body['watermark'] is False
    expected = 'data:image/png;base64,ZmFrZQ=='
    assert body['image'] == (expected if model.endswith('/layer-decomposition') else [expected])


@pytest.mark.parametrize('model', ['gpt-image-2.5-flare','gpt-image-2.5-sunburst'])
@pytest.mark.parametrize('with_references', [False,True])
def test_gpt25_uses_workshop_sync_contract_even_with_durable_receipt(builders, model, with_references):
    env,calls,_=builders
    provider=env['fixture_provider'];provider.update(id='zhenzhen',image_profile={})
    env.update(is_zhenzhen=is_zhenzhen,zhenzhen_async_image_submit_url=zhenzhen_async_image_submit_url,
               image_task_url_for_provider=lambda p,key:p['base_url']+'/v1/images/tasks/'+key)
    class Sink:
        def identify(self,*args,**kwargs):pass
        async def accepted(self,*args):raise AssertionError('inline result is not an async accepted task')
    references=[{'url':'data:image/png;base64,ZmFrZQ=='}]*14 if with_references else []
    asyncio.run(env['generate_ai_image']('fixture','1024x1024','high',model,references,'zhenzhen',receipt_sink=Sink()))
    assert len(calls)==1 and not calls[0].url.query
    assert calls[0].url.path.endswith('/edits' if with_references else '/generations')
    assert calls[0].headers['content-type'].startswith('multipart/form-data' if with_references else 'application/json')
    if with_references:assert calls[0].content.count(b'name="image"')==14
    assert zhenzhen_async_image_submit_url(provider['base_url']+'/v1/images/generations',
        provider['base_url']+'/v1/images/tasks/_',model='gpt-image-2.6-flare').endswith('?async=true')


@pytest.mark.parametrize('model', ['gpt-image-2.5-flare','gpt-image-2.5-sunburst'])
def test_gpt25_excess_references_stop_before_supplier(builders, model):
    env,calls,_=builders;env['fixture_provider'].update(id='zhenzhen',image_profile={})
    with pytest.raises(HTTPException) as error:
        asyncio.run(env['generate_ai_image']('fixture','1024x1024','',model,[{'url':'data:image/png;base64,ZmFrZQ=='}]*15,'zhenzhen'))
    assert error.value.status_code==400 and not calls


def test_seedream55_reference_limit_is_ten_before_submission(builders):
    env, calls, _ = builders
    env['fixture_provider'].update(id='zhenzhen', image_profile={})
    with pytest.raises(HTTPException, match='参考图'):
        asyncio.run(env['generate_ai_image']('fixture', '1024x1024', '', 'seedream-v5.5',
            [{'url':'data:image/png;base64,ZmFrZQ=='}] * 11, 'zhenzhen'))
    assert calls == []


def test_shared_image_choices_in_original_frontend_module():
    import subprocess
    result = subprocess.run(['node',str(ROOT / 'enterprise/tests/test_provider_image_choices.js')],
        capture_output=True,encoding='utf-8',timeout=15)
    assert result.returncode == 0,result.stdout + result.stderr


def test_seedream55_documented_resolution_tokens_and_unknown_provider_are_preserved():
    validate_image_size('1.5K',IMAGE_MODELS['seedream-v5.5'])
    validate_image_size('vendor-specific-size',{'mode':'pixel'})
