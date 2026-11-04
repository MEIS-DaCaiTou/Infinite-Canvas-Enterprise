"""Mutable HTML entry documents must revalidate without disabling media caching."""
import ast
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient


def static_class():
    root = Path(__file__).parents[2]
    node = next(node for node in ast.parse((root/'main.py').read_text('utf-8')).body
                if isinstance(node, ast.ClassDef) and node.name == 'RevalidatedHtmlStaticFiles')
    namespace = {'StaticFiles': StaticFiles}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'actual_static_policy', 'exec'), namespace)
    return namespace[node.name]


@pytest.mark.parametrize('entry', ['canvas.html', 'smart-canvas.html', 'canvas-list.html'])
def test_entry_html_revalidates_200_and_304(tmp_path, entry):
    page = tmp_path/entry
    page.write_text('<p>before</p>', encoding='utf-8')
    app = FastAPI()
    app.mount('/static', static_class()(directory=str(tmp_path)))
    with TestClient(app) as client:
        first = client.get('/static/'+entry+'?v=old')
        assert first.status_code == 200 and first.headers['cache-control'] == 'no-cache'
        unchanged = client.get('/static/'+entry+'?v=old', headers={'If-None-Match': first.headers['etag']})
        assert unchanged.status_code == 304 and unchanged.headers['cache-control'] == 'no-cache'
        page.write_text('<p>updated HTML with new script references</p>', encoding='utf-8')
        changed = client.get('/static/'+entry+'?v=old', headers={'If-None-Match': first.headers['etag']})
        assert changed.status_code == 200 and 'updated HTML' in changed.text
        assert changed.headers['cache-control'] == 'no-cache'


def test_script_and_video_keep_static_caching_and_range(tmp_path):
    (tmp_path/'app.js').write_text('window.fixture = true;', encoding='utf-8')
    (tmp_path/'clip.mp4').write_bytes(bytes(range(256)))
    app = FastAPI()
    app.mount('/static', static_class()(directory=str(tmp_path)))
    with TestClient(app) as client:
        script = client.get('/static/app.js?v=fixture')
        assert script.status_code == 200 and 'cache-control' not in script.headers
        assert client.get('/static/app.js', headers={'If-None-Match':script.headers['etag']}).status_code == 304
        media = client.get('/static/clip.mp4', headers={'Range':'bytes=0-9'})
        assert media.status_code == 206 and media.content == bytes(range(10))
        assert 'cache-control' not in media.headers
