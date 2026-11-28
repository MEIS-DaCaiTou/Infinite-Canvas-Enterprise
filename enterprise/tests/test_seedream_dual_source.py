"""Real request encoders and receipts on local transports; no paid calls."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

from enterprise.creation_settings import native_background_parameters
from enterprise.provider_image_profiles import image_profile_for, validate_image_size, ImageProfileError
from enterprise.providers import suppliers, volcengine_images as ark, zhenzhen
from enterprise.seedream_capabilities import NATIVE_MODEL
from enterprise.tests.test_task_credentials import bound
from enterprise.tests.test_department_governance import business

ARK = {"id": "official-images", "supplier": "volcengine", "protocol": "volcengine",
       "base_url": "https://ark.example/api/v3", "image_models": [NATIVE_MODEL]}
ZZ = {"id": "department-images", "supplier": "zhenzhen", "protocol": "openai",
      "base_url": "https://t8.example/v1", "image_models": ["seedream-v5.5", "seedream-v5.5/layer-decomposition"]}


def test_reference_limits_are_separate_from_output_sizes_and_supplier_contracts():
    profile=image_profile_for(ARK,NATIVE_MODEL)
    assert profile['reference_input']=={'formats':['PNG','JPEG','WEBP'],'max_file_bytes':30000000,
        'max_pixels':36000000,'min_edge':15,'max_aspect':16}
    assert profile['layer_profile']['reference_input']['min_pixels']==262144
    assert profile['layer_profile']['reference_input']['formats']==['PNG','JPEG']
    # Workshop pages do not state the native Ark input limits; don't silently
    # borrow either those limits or the much smaller generated-image limits.
    assert 'reference_input' not in image_profile_for(ZZ,'seedream-v5.5')
    assert 'reference_input' not in image_profile_for(ZZ,'gpt-image-2')


@pytest.mark.parametrize("size", ["1K", "1.5K", "2K", "1024x1024", "2880x1440"])
@pytest.mark.parametrize("count", [0, 1, 10])
def test_equivalent_generation_keeps_model_rules_and_exact_dimensions(size, count):
    refs = ["data:image/png;base64,fixture"] * count
    native = ark.image_body(NATIVE_MODEL, "sample", size, refs)
    reseller = zhenzhen.image_body("seedream-v5.5", "sample", size, "high", refs, None)
    assert native == {**reseller, "model": NATIVE_MODEL}
    assert native["size"] == size and "quality" not in native
    assert len(native.get("image", [])) == count
    for provider, model in ((ARK, NATIVE_MODEL), (ZZ, "seedream-v5.5")):
        profile = image_profile_for(provider, model)
        assert profile["model_family"] == "seedream-5.5"
        validate_image_size(size, profile)


@pytest.mark.parametrize("size", ["auto", "4K", "512x512", "100x10000", "4608x1024"])
def test_invalid_generation_sizes_are_rejected_by_both_adapters(size):
    for operation in (lambda: ark.image_body(NATIVE_MODEL, "sample", size, []),
                      lambda: zhenzhen.image_body("seedream-v5.5", "sample", size, "", [], None)):
        with pytest.raises(HTTPException) as error:
            operation()
        assert error.value.status_code == 400
    with pytest.raises(ImageProfileError):
        validate_image_size(size, image_profile_for(ARK, NATIVE_MODEL))


@pytest.mark.parametrize("size", ["auto", "1K", "1.5K", "2K"])
def test_layer_mode_has_its_own_wire_encoding_and_no_background(size):
    options = {"max_images": 100, "text_recognition": True}
    native = ark.image_body(NATIVE_MODEL, "split", size, ["source"], layer_options=options)
    reseller = zhenzhen.image_body("seedream-v5.5/layer-decomposition", "split", size, "", ["source"], None, layer_options={})
    assert native["layer_decomposition"] is True and "layer_decomposition" not in reseller
    for body in (native, reseller):
        assert body["image"] == "source" and body["size"] == size
        assert body["output_format"] == "png" and "background" not in body
        assert "n" not in body and "sequential_image_generation" not in body
    validate_image_size(size, image_profile_for(ARK, NATIVE_MODEL), {"layer_options": options})
    assert native['layer_decomposition_options']==options
    assert 'layer_decomposition_options' not in reseller


@pytest.mark.parametrize("mode", ["opaque", "transparent"])
def test_background_is_available_for_generation_and_rejected_for_layers(mode):
    options = native_background_parameters(ARK, NATIVE_MODEL, mode)
    assert ark.image_body(NATIVE_MODEL, "sample", "2K", [], background_options=options)["background"] == mode
    assert zhenzhen.image_body("seedream-v5.5", "sample", "2K", "", [], None, background_options=options)["background"] == mode
    with pytest.raises(HTTPException):
        ark.image_body(NATIVE_MODEL, "split", "auto", ["source"], layer_options={}, background_options=options)
    with pytest.raises(HTTPException):
        native_background_parameters(ZZ, "seedream-v5.5/layer-decomposition", mode)


@pytest.mark.parametrize("layers,count", [(False, 11), (True, 0), (True, 2)])
def test_reference_limits_do_not_silently_trim_inputs(layers, count):
    references = ["source"] * count
    with pytest.raises(HTTPException):
        ark.image_body(NATIVE_MODEL, "sample", "auto" if layers else "2K", references,
                       layer_options={} if layers else None)
    with pytest.raises(HTTPException):
        zhenzhen.image_body("seedream-v5.5/layer-decomposition" if layers else "seedream-v5.5",
                            "sample", "auto" if layers else "2K", "", references, None)


def test_catalog_keeps_business_identity_and_isolates_capability_values():
    original = {**ARK, "protocol": "openai", "image_request_mode": "openai-responses",
                "model_protocols": {NATIVE_MODEL: "gemini"}}
    configured = suppliers.configure_provider(original)
    assert configured["id"] == original["id"] and configured["base_url"] == original["base_url"]
    assert configured["protocol"] == "volcengine" and configured["model_protocols"] == {}
    assert original["protocol"] == "openai"
    assert suppliers.supplier_id({"id": "volcengine", "protocol": "volcengine"}) == "volcengine"
    assert not zhenzhen.is_zhenzhen({**ARK, "base_url": "https://ai.t8star.org/v1"})
    first = suppliers.public_image_profiles(ARK)
    first[NATIVE_MODEL]["layer_profile"]["resolutions"].clear()
    assert suppliers.public_image_profiles(ARK)[NATIVE_MODEL]["layer_profile"]["resolutions"] == ["1K", "1.5K", "2K"]
    assert suppliers.provider_presets()["volcengine"]["image_models"] == [NATIVE_MODEL]


@pytest.mark.parametrize("payload", [{"request_id": "diagnostic-only"},
    {"request_id": "diagnostic-only", "data": [{"url": "https://media.example/result.png"}]}])
def test_native_request_id_never_becomes_an_async_query_or_second_submission(payload):
    calls = []
    class Sink:
        def identify(self, *args, **kwargs):
            pass
        async def accepted(self, *args):
            raise AssertionError("native request_id is not a pollable task")
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=payload, headers={"x-request-id": "diagnostic-header"})
    def extract(raw):
        if not raw.get("data"):
            raise HTTPException(502, "No image")
        return raw["data"][0]["url"]
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await ark.execute_image(client, ARK["base_url"] + "/images/generations", {"Authorization": "Bearer test-only"},
                provider=ARK, model=NATIVE_MODEL, prompt="sample", size="2K", references=[], extract_image=extract, receipt_sink=Sink())
    if payload.get("data"):
        assert asyncio.run(run())[1] == payload
    else:
        with pytest.raises(HTTPException) as error:
            asyncio.run(run())
        assert getattr(error.value, "submission_unknown", False)
    assert len(calls) == 1 and calls[0].method == "POST"
    assert calls[0].url.path == "/api/v3/images/generations"


def test_legacy_native_size_migration_matches_frozen_function():
    """Actual pre-extraction results, independent of HEAD and shallow Git history."""
    # Captured from main.py at d8210980d5c773ff91798cac20e8cfb5c14ee92b.
    # HEAD already contains the extraction after the owner's backup commit.
    sizes=("auto","1K","2K","4K","512x512","1024x1536","1200X1600","1200*800","2880x1440")
    expected={
        "doubao-seedream-4-5-251128": ("2048x2048","2048x2048","2048x2048","4096x4096","1920x1920","1584x2336","1680x2208","2336x1584","2720x1536"),
        "legacy-image-model": ("auto","1K","2048x2048","4096x4096","512x512","1024x1536","1200x1600","1200x800","2880x1440"),
    }
    for model,results in expected.items():
        for size,result in zip(sizes,results):
            assert ark.normalize_legacy_size(size,model)==result


@pytest.mark.parametrize("code,status,message", [("SetLimitExceeded",429,"Account model paused"),
    ("AccountQuotaExceeded",429,"Account model paused"), ("",403,"The request failed because your account has an overdue balance.")])
def test_native_account_limits_are_not_reported_as_temporary_traffic_limits(code,status,message):
    calls, identified = [], []
    class Sink:
        def identify(self, headers, raw=None):
            identified.append((headers.get('x-request-id'), raw))
    def reply(request):
        calls.append(request.method)
        return httpx.Response(status, json={'error':{'code':code,'message':message}},
                              headers={'x-request-id':'original-denied-call'})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            await ark.execute_image(client, ARK['base_url']+'/images/generations', {}, provider=ARK,
                model=NATIVE_MODEL, prompt='sample', size='1K', references=[],
                extract_image=lambda raw:None, receipt_sink=Sink())
    with pytest.raises(HTTPException) as error:
        asyncio.run(run())
    assert error.value.status_code == status and code in error.value.detail
    if status==403:assert '欠费' in error.value.detail
    assert '稍后重试' not in error.value.detail
    assert 'original-denied-call' in error.value.detail
    assert calls == ['POST'] and identified[0][0] == 'original-denied-call'


def test_native_department_source_keeps_credentials_bound_to_original_protocol(bound):
    import enterprise.task_credentials as binding
    service, people, design, ops, journal, *_ = bound
    source = service.create_source(people['admin'], provider_id=ARK['id'], name='Ark source',
        scope='department', department_id=design, procurement='company', account_ref='fixture-ark', secret='fixture-ark-secret')
    service.grant_source(people['admin'], source['id'], 'employee', True)
    record = {'id':'native-source-task', 'enterprise_user_id':'employee', 'model':NATIVE_MODEL, 'expected_attempts':1}
    record['billing_context'] = binding.prepare_task_binding(service, record, {'call_source_id':source['id']}, 'employee', ARK)
    assert 'fixture-ark-secret' not in json.dumps(record)
    with binding.credential_scope(record, service=service):
        assert binding.scoped_api_key(ARK) == 'fixture-ark-secret'
        with pytest.raises(HTTPException) as error:
            binding.scoped_api_key({**ARK, 'protocol':'openai', 'base_url':'https://t8.example/v1'})
        assert error.value.status_code == 409
    assert binding.scoped_api_key(ARK) is None


def test_native_source_rejects_an_ordinary_user_from_another_department(bound):
    import enterprise.task_credentials as binding
    service, people, design, ops, *_ = bound
    source = service.create_source(people['admin'], provider_id=ARK['id'], name='Other department Ark',
        scope='department', department_id=ops, procurement='company', account_ref='fixture-ark-other', secret='fixture-other-secret')
    record = {'id':'native-denied-task', 'enterprise_user_id':'employee', 'model':NATIVE_MODEL, 'expected_attempts':1}
    with pytest.raises(HTTPException) as error:
        binding.prepare_task_binding(service, record, {'call_source_id':source['id']}, 'employee', ARK)
    assert error.value.status_code == 403


def test_original_page_helpers_consume_the_backend_profiles_without_supplier_rules():
    import subprocess
    root = Path(__file__).resolve().parents[2]
    providers = [ARK, ZZ, {'id':'volcengine','protocol':'volcengine','image_models':[]}]
    providers = [{**p, 'builtin_model_image_profiles': suppliers.public_image_profiles(p)} for p in providers]
    result = subprocess.run(['node', str(root/'enterprise/tests/test_seedream_dual_source_ui.js')],
        input=json.dumps({'providers':providers,'model':NATIVE_MODEL}), capture_output=True, text=True,
        encoding='utf8', cwd=root, timeout=15)
    assert result.returncode == 0, result.stdout+result.stderr


def test_reseller_layer_submission_keeps_the_full_synchronous_metadata_response():
    endpoint='https://t8.example/v1/images/generations'
    query='https://t8.example/v1/images/tasks/{task_id}'
    assert zhenzhen.async_image_submit_url(endpoint,query,model='seedream-v5.5/layer-decomposition') is None
    assert zhenzhen.async_image_submit_url(endpoint,query,model='seedream-v5.5') == endpoint+'?async=true'


@pytest.mark.parametrize('options',[{'max_images':3},{'text_recognition':True}])
def test_reseller_unimplemented_options_are_rejected_before_paid_submission(options):
    profile=image_profile_for(ZZ,'seedream-v5.5/layer-decomposition')
    assert profile['supports_layer_limit'] is False and profile['supports_layer_text_recognition'] is False
    with pytest.raises(HTTPException) as error:
        zhenzhen.image_body('seedream-v5.5/layer-decomposition','split','auto','',['source'],None,layer_options=options)
    assert error.value.status_code==400 and '贞贞' in error.value.detail
