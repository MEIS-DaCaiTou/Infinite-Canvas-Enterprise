"""Comfy input contracts without starting the application or contacting a backend."""
import ast
from pathlib import Path
import re
import subprocess
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[2]


def test_shared_frontend_field_contract():
    subprocess.run(['node', str(Path(__file__).with_suffix('.js'))], check=True)


def test_output_prefix_is_not_synchronized_as_input_media():
    tree = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8'))
    selected = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in {
            'is_comfy_input_media_value', 'collect_required_comfy_media'
        }:
            selected.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in {'MEDIA_INPUT_KEYS', 'MEDIA_INPUT_EXT_RE'}
            for target in node.targets
        ):
            selected.append(node)
    scope = {'re': re, 'Any': Any, 'Dict': Dict, 'List': List}
    exec(compile(ast.Module(body=selected, type_ignores=[]), 'actual_comfy_media_functions', 'exec'), scope)
    collect = scope['collect_required_comfy_media']
    for prefix in ['ComfyUI', 'result.png', 'folder/video.mp4']:
        assert collect({'8': {'image': 'uploaded.png'}, '6': {'filename_prefix': prefix}}) == ['uploaded.png']
    assert collect({'1': {'filename': 'input.png', 'mask': 'mask.png', 'video': 'clip.mp4', 'audio': 'voice.wav'}}) == [
        'input.png', 'mask.png', 'clip.mp4', 'voice.wav'
    ]
