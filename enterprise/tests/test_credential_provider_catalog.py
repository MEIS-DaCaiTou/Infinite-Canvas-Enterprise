"""The catalog reports the same capability used by task credential binding."""
import ast
from pathlib import Path

import pytest
from enterprise.providers.zhenzhen import is_zhenzhen


@pytest.mark.parametrize('provider,supported', [
    ({'id':'zhenzhen','base_url':'https://company-proxy.invalid/v1'}, True),
    ({'id':'company-ai','base_url':'https://ai.t8star.org/v1'}, True),
    ({'id':'modelscope','base_url':'https://api-inference.modelscope.cn/v1'}, False),
    ({'id':'custom','base_url':'https://other.invalid/v1'}, False),
])
def test_public_provider_reports_real_source_capability(provider, supported):
    tree = ast.parse((Path(__file__).resolve().parents[2] / 'main.py').read_text(encoding='utf8'))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'public_provider')
    namespace = {'is_zhenzhen':is_zhenzhen,
        'provider_env_key_value':lambda _: '', 'mask_secret':lambda _: '',
        'provider_key_env':lambda _: 'TEST_ENV',
        'zhenzhen_public_image_profiles':lambda _: {}, 'zhenzhen_public_video_profiles':lambda _: {}}
    exec(compile(ast.Module(body=[function],type_ignores=[]), 'main.py', 'exec'),namespace)
    result = namespace['public_provider'](provider)
    assert result['managed_source_supported'] is supported
    assert result['id'] == provider['id']
    assert result['has_key'] is False  # A department can supply its own key without a company key.
