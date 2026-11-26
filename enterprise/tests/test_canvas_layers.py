import pytest
from pydantic import ValidationError
from enterprise.image_layers import LayerOptions, layer_parameters
from enterprise.providers.volcengine_images import image_body
from enterprise.seedream_capabilities import NATIVE_MODEL
from enterprise.providers.image_outputs import layer_metadata


@pytest.mark.parametrize('script', ['document', 'session', 'layout', 'interactions', 'smart_edit', 'edit_result', 'export', 'editor', 'viewport', 'annotations'])
def test_layer_frontend_interactions(script):
    import subprocess
    from pathlib import Path
    root = Path(__file__).parents[2]
    subprocess.run(['node', str(Path(__file__).with_name(f'test_canvas_layer_{script}.js'))],
                   cwd=root, check=True, timeout=30)


@pytest.mark.parametrize('total', [2, 17, 100])
def test_layer_limit_is_one_request_with_base_included(total):
    options = LayerOptions(max_images=total, text_recognition=True)
    body = image_body(NATIVE_MODEL, 'split', 'auto', ['source.png'], layer_options=options)
    assert body['image'] == 'source.png'
    assert body['size'] == 'auto'
    assert body['layer_decomposition_options'] == {'max_images': total, 'text_recognition': True}
    assert body['output_format'] == 'png' and 'n' not in body


@pytest.mark.parametrize('total', [1, 101])
def test_layer_limit_rejects_outside_native_contract(total):
    with pytest.raises(ValidationError):
        LayerOptions(max_images=total)


def test_automatic_limit_is_not_a_fabricated_exact_count():
    assert layer_parameters(LayerOptions()) == {'layer_decomposition_options': {'text_recognition': False}}
    assert layer_parameters(None) == {}


def test_ocr_survives_output_metadata_without_private_fields():
    value = {'z_index': 4, 'text_recognition': {'text': 'Sale\n129', 'private': 'omit', 'lines': [
        {'bounding_box': {'absolute': [10, 20, 200, 70]}, 'runs': [
            {'text': 'Sale', 'style': {'bold': True, 'foreground_color': '#123456', 'private': 'omit'}}]}]}}
    actual = layer_metadata(value)
    assert actual['text_recognition']['text'] == 'Sale\n129'
    assert actual['text_recognition']['lines'][0]['bounding_box']['absolute'] == [10, 20, 200, 70]
    assert actual['text_recognition']['lines'][0]['runs'][0]['style'] == {'bold': True, 'foreground_color': '#123456'}
    assert 'private' not in str(actual)


@pytest.mark.parametrize('size', ['auto', '1.5K'])
def test_native_seedream_keeps_layer_size_tier_and_options(size):
    import ast
    import asyncio
    import httpx
    from pathlib import Path
    from types import SimpleNamespace
    from fastapi import HTTPException
    from enterprise.providers.volcengine_images import image_profile, execute_image
    tree=ast.parse((Path(__file__).parents[2]/'main.py').read_text(encoding='utf-8'))
    function=next(node for node in tree.body if isinstance(node,ast.AsyncFunctionDef) and node.name=='generate_volcengine_provider_image')
    calls=[]
    def respond(request):
        import json
        body=json.loads(request.content);calls.append(body)
        assert body['layer_decomposition'] is True
        assert body['layer_decomposition_options']=={'max_images':17,'text_recognition':True}
        assert body['image']=='data:fixture' and body['size']==size
        return httpx.Response(200,json={'data':[{'url':'https://fixture.invalid/base.png'}]})
    namespace={'httpx':SimpleNamespace(Timeout=httpx.Timeout,AsyncClient=lambda **kw:httpx.AsyncClient(transport=httpx.MockTransport(respond),**kw)),
        'volcengine_endpoint_url':lambda _: 'https://fixture.invalid/api/v3/images/generations',
        'normalize_volcengine_size':lambda *_:'2048x2048', 'volcengine_image_payload':lambda _:'data:fixture',
        'ONLINE_IMAGE_REFERENCE_MAX':10,'api_headers':lambda **_: {},'extract_image':lambda raw:raw['data'][0],
        'layer_parameters':layer_parameters,'ark_image_profile':image_profile,
        'execute_ark_image':execute_image,'HTTPException':HTTPException}
    exec(compile(ast.Module(body=[function],type_ignores=[]),'main.py','exec'),namespace)
    asyncio.run(namespace['generate_volcengine_provider_image']('split',size,'doubao-seedream-5-5-261028',
        [{'url':'/assets/source.png'}],{'id':'volcengine','protocol':'volcengine'},
        {'layer_options':{'max_images':17,'text_recognition':True}}))
    assert len(calls)==1
