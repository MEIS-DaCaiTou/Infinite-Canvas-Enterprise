"""Background choices must reach supported APIs without changing old requests."""
import pytest
from fastapi import HTTPException

from enterprise.creation_settings import (
    background_prompt, native_background_parameters, supports_transparent_background,
)


def test_preserve_background_is_an_explicit_edit_instruction():
    assert background_prompt("修改瓶子颜色", "auto") == "修改瓶子颜色"
    assert "保留参考图原有背景" in background_prompt("修改瓶子颜色", "preserve")


def test_transparent_output_requires_a_supported_native_contract():
    provider = {"base_url": "https://unverified.example/v1"}
    assert native_background_parameters(provider, "some-model", "auto") == {}
    with pytest.raises(HTTPException, match="透明背景能力"):
        native_background_parameters(provider, "some-model", "transparent")
    provider["image_profile"] = {"mode": "pixel", "supports_background": True}
    assert native_background_parameters(provider, "some-model", "transparent") == {
        "background": "transparent", "output_format": "png",
    }


@pytest.mark.parametrize("mode", ["openai-json", "openai-video-proxy"])
def test_incompatible_protocol_does_not_advertise_transparency(mode):
    provider = {"image_request_mode": mode, "image_profile": {"mode": "pixel", "supports_background": True}}
    assert not supports_transparent_background(provider, "gpt-image-1")


def test_official_openai_contract_and_explicit_opt_out():
    provider = {"base_url": "https://api.openai.com/v1"}
    assert supports_transparent_background(provider, "gpt-image-1")
    provider["image_profile"] = {"mode": "pixel", "supports_background": False}
    assert not supports_transparent_background(provider, "gpt-image-1")


@pytest.mark.parametrize('model', ['seedream-v5.5', 'seedream-v5.5/layer-decomposition'])
def test_seedream55_contract_takes_precedence_over_old_platform_mode(model):
    provider = {'id':'zhenzhen', 'protocol':'gemini', 'image_request_mode':'openai-json'}
    assert not supports_transparent_background(provider, model)
    if model.endswith('/layer-decomposition'):
        with pytest.raises(HTTPException):native_background_parameters(provider, model, 'opaque')
    else:
        assert native_background_parameters(provider, model, 'opaque') == {'background':'opaque','output_format':'png'}


def test_reseller_transparency_is_not_inherited_from_the_native_model():
    reseller={'id':'zhenzhen','protocol':'openai'}
    assert not supports_transparent_background(reseller,'seedream-v5.5')
    with pytest.raises(HTTPException,match='透明背景能力'):
        native_background_parameters(reseller,'seedream-v5.5','transparent')
    assert supports_transparent_background({'id':'volcengine','protocol':'volcengine'},'doubao-seedream-5-5-261028')
