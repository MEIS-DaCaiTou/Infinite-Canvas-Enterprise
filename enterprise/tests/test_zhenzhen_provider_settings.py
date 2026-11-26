"""Supplier setup and identity use existing storage; no real provider calls."""
import json
import os
import subprocess
import sys

from enterprise.providers.zhenzhen import (
    DEFAULT_IMAGE_MODELS, IMAGE_MODELS, configure_provider, image_profile, is_zhenzhen, provider_preset,
)
from enterprise.providers.zhenzhen_video import video_profile
from enterprise.tests.test_canvas_image_recovery_main import BOOTSTRAP, ROOT


def test_preset_lists_maintained_models_and_returns_independent_values():
    preset=provider_preset()
    assert preset['supplier']=='zhenzhen' and preset['base_url']=='https://ai.t8star.org/v1'
    assert len(DEFAULT_IMAGE_MODELS)==17 and set(DEFAULT_IMAGE_MODELS)<=set(IMAGE_MODELS)
    preset['image_models'].clear()
    assert provider_preset()['image_models']==DEFAULT_IMAGE_MODELS


def test_explicit_supplier_save_uses_native_protocol_without_replacing_business_identity():
    original={'id':'department-images','supplier':'zhenzhen','name':'Department A',
        'base_url':'https://proxy.invalid/v1','protocol':'gemini','image_request_mode':'openai-responses',
        'model_protocols':{'gpt-image-2':'gemini'},'image_models':['gpt-image-2'],
        'chat_models':['owned-chat-model'],'video_models':['MiniMax-H3'],'enabled':False}
    configured=configure_provider(original)
    assert configured['protocol']=='openai' and configured['image_request_mode']=='openai'
    assert configured['model_protocols']=={}
    for field in ('id','name','base_url','image_models','chat_models','video_models','enabled'):
        assert configured[field]==original[field]
    assert original['protocol']=='gemini'
    assert configure_provider({'supplier':'zhenzhen'})['base_url']==provider_preset()['base_url']


def test_supplier_identity_recognizes_explicit_proxies_and_legacy_configs():
    for provider in ({'supplier':'zhenzhen','id':'department-images','base_url':'https://proxy.invalid/v1'},
                     {'id':'zhenzhen','base_url':'https://proxy.invalid/v1'},
                     {'id':'old-company','base_url':'https://ai.t8star.org/v1'}):
        assert is_zhenzhen(provider)
        assert image_profile(provider,'nano-banana-pro-2k')['fixed_resolution']=='2K'
        assert video_profile(provider,'MiniMax-H3')
    assert not is_zhenzhen({'id':'other','base_url':'https://not-ai.t8star.org.invalid/v1'})


def test_old_configs_are_not_rewritten_by_supplier_save_helper():
    legacy={'id':'old-company','base_url':'https://ai.t8star.org/v1','protocol':'openai',
            'image_request_mode':'openai-json'}
    assert configure_provider(legacy) is legacy


def test_actual_main_roundtrip_preserves_supplier_for_older_settings_clients(tmp_path):
    app=tmp_path/'install/releases/fixture'
    for name in ('static','workflows'):(app/name).mkdir(parents=True,exist_ok=True)
    script=BOOTSTRAP+r'''
async def run():
    catalog=await main.api_providers()
    assert catalog['provider_presets']['zhenzhen']['image_models']==main.zhenzhen_provider_preset()['image_models']
    legacy=main.normalize_provider({'id':'legacy-t8','base_url':'https://ai.t8star.org/v1',
        'protocol':'openai','image_request_mode':'openai-json','image_models':['seedream-v5.5']})
    assert legacy['supplier']=='zhenzhen' and legacy['image_request_mode']=='openai-json'
    value=main.ApiProviderPayload(id='department-images',supplier='zhenzhen',name='Department A',
        base_url='https://proxy.invalid/v1',protocol='gemini',image_request_mode='openai-responses',
        model_protocols={'gpt-image-2':'gemini'},image_models=['gpt-image-2','seedream-v5.5'],
        chat_models=['owned-chat-model'],video_models=['MiniMax-H3'])
    saved=(await main.save_providers([value]))['providers'][0]
    assert saved['supplier']=='zhenzhen' and saved['protocol']=='openai' and saved['model_protocols']=={}
    assert saved['image_request_mode']=='openai' and saved['managed_source_supported']
    assert set(saved['builtin_model_image_profiles'])=={'gpt-image-2','seedream-v5.5'}
    assert 'MiniMax-H3' in saved['builtin_model_video_profiles']
    # An older client omits supplier and capability fields; save must retain them.
    old=main.ApiProviderPayload(id='department-images',name='Renamed Department A',
        base_url='https://proxy.invalid/v1',image_models=['gpt-image-2','seedream-v5.5'])
    saved=(await main.save_providers([old]))['providers'][0]
    assert saved['id']=='department-images' and saved['supplier']=='zhenzhen'
    assert saved['managed_source_supported'] and saved['protocol']=='openai'
    assert main.load_api_providers()[0]['supplier']=='zhenzhen'
asyncio.run(run())
print('actual main supplier settings roundtrip passed')
'''
    env={**os.environ,'ICE_ENTERPRISE_ENABLED':'0','ICE_PORTABLE_ROOT':'','PYTHONIOENCODING':'utf-8'}
    result=subprocess.run([sys.executable,'-B','-c',script,str(ROOT),str(tmp_path/'install'),str(tmp_path/'local')],
        cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf8',timeout=45)
    assert result.returncode==0,result.stdout+result.stderr
