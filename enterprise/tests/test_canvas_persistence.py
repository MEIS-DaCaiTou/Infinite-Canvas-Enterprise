"""Real canvas routes and frontend save/reopen functions, using disposable data only.

Node vm substitutes rendering and the HTTP boundary; ASGI executes the captured
request against main. A second Python process and a fresh vm reopen the saved
canvas, so neither server globals nor the text-result cache can hide data loss.
This is protocol coverage, not rendered-browser or Gateway authorization evidence.
"""
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = Path(__file__).with_suffix(".js")
SCENARIO = r'''
import asyncio, json, subprocess, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from enterprise.paths import (
    PortableRootInputs, derive_portable_path_roots,
    install_path_roots_for_process, prepare_application_directories,
)
root, mode, kind = Path(sys.argv[2]), sys.argv[3], sys.argv[4]
roots = derive_portable_path_roots(PortableRootInputs(root/'install', root/'local'), 'fixture')
install_path_roots_for_process(roots)
prepare_application_directories(roots)
import httpx
import main

def frontend(phase, source, destination):
    completed = subprocess.run(
        ['node', sys.argv[5], phase, kind, str(source), str(destination)],
        capture_output=True, text=True, encoding='utf-8', timeout=15,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

async def scenario():
    # Drive canvas-only ASGI routes without lifespan startup or TCP listeners.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://fixture') as client:
        if mode == 'write':
            created = await client.post('/api/canvases', json={'title':'隔离保存重开', 'kind':kind})
            assert created.status_code == 200, created.text
            original = created.json()
            (root/'canvas-id').write_text(original['canvas']['id'])
            (root/'created.json').write_text(json.dumps(original), encoding='utf-8')
            frontend('save', root/'created.json', root/'request.json')
            request = json.loads((root/'request.json').read_text(encoding='utf-8'))
            saved = await client.put('/api/canvases/'+original['canvas']['id'], json=request)
            assert saved.status_code == 200, saved.text
            saved_canvas = saved.json()['canvas']
            assert saved_canvas['nodes'] == request['nodes']
            assert saved_canvas['connections'] == request['connections']
            assert saved_canvas['logs'] == request['logs']
            assert saved_canvas['title'] == request['title']
            assert saved_canvas['icon'] == request['icon']
            assert saved_canvas['kind'] == kind
            disk = Path(main.canvas_path(saved_canvas['id']))
            assert disk.is_relative_to(roots.DATA_ROOT)
            assert json.loads(disk.read_text(encoding='utf-8')) == saved_canvas
            (root/'saved.json').write_text(json.dumps(saved_canvas), encoding='utf-8')
        else:
            canvas_id = (root/'canvas-id').read_text()
            reopened = await client.get('/api/canvases/'+canvas_id)
            assert reopened.status_code == 200, reopened.text
            assert reopened.json()['canvas'] == json.loads((root/'saved.json').read_text(encoding='utf-8'))
            (root/'reopened.json').write_text(reopened.text, encoding='utf-8')
            frontend('reopen', root/'reopened.json', root/'verified.json')
            assert json.loads((root/'verified.json').read_text()) == {'kind':kind, 'reopened':True}
asyncio.run(scenario())
'''


@pytest.mark.parametrize("kind", ["classic", "smart"])
def test_canvas_save_restart_reopen_keeps_typed_history_and_pinned_prompt(tmp_path, kind):
    app = tmp_path / "install/releases/fixture"
    (app / "static").mkdir(parents=True)
    (app / "main.py").write_text("# isolated path-layout marker\n", encoding="utf-8")
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    for mode in ("write", "read"):
        completed = subprocess.run(
            [sys.executable, "-B", "-c", SCENARIO, str(ROOT), str(tmp_path), mode, kind, str(FRONTEND)],
            cwd=ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=45,
        )
        assert completed.returncode == 0, f"{kind}/{mode}:\n" + completed.stdout + completed.stderr
