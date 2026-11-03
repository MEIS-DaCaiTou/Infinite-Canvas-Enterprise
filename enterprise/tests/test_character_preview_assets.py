"""The originally previewed human must ship with its complete local decoder chain."""
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[2]
MOTION = ROOT / 'static/vendor/liblib-character-motion'


def test_original_human_is_embedded_and_decoder_dependencies_are_bundled():
    raw = (MOTION / 'midwam-human.glb').read_bytes()
    assert struct.unpack_from('<III', raw) == (0x46546C67, 2, len(raw))
    assert len(raw) == 179412
    size, kind = struct.unpack_from('<II', raw, 12)
    assert kind == 0x4E4F534A
    doc = json.loads(raw[20:20 + size])
    assert 'KHR_draco_mesh_compression' in doc['extensionsUsed']
    assert all('uri' not in item for item in doc['buffers'])
    assert (MOTION / 'draco/draco_decoder.wasm').read_bytes().startswith(b'\0asm')
    for relative in ('draco/draco_wasm_wrapper.js', 'draco/LICENSE', 'NOTICE', 'SOURCE.json'):
        assert (MOTION / relative).is_file(), relative


def test_renderer_uses_only_complete_packaged_original_resources():
    renderer = (MOTION / 'renderer.js').read_text(encoding='utf-8')
    assert '/static/vendor/liblib-character-motion/midwam-human.glb' in renderer
    assert '/static/vendor/liblib-character-motion/draco/' in renderer
    for name in ('loaders/GLTFLoader.js', 'loaders/DRACOLoader.js', 'utils/BufferGeometryUtils.js', 'LICENSE'):
        assert (ROOT / 'static/vendor/three-addons-r160' / name).is_file()
    wrapper = (ROOT / 'static/js/character-motion-preview.js').read_text(encoding='utf-8')
    assert '../vendor/liblib-character-motion/renderer.js' in wrapper
    assert 'referenceAssets' not in wrapper and 'character-mannequin' not in wrapper
