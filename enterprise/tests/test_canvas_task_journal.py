"""Durability tests use temporary roots and fake providers only."""
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock

import pytest

from enterprise.canvas_task_journal import CanvasTaskJournal, create_task_receipt


ROOT = Path(__file__).resolve().parents[2]


def record(task_id="canvas_img_fixture"):
    return {"id": task_id, "type": "online-image", "status": "queued", "result": None, "error": ""}


def test_task_survives_abrupt_process_exit_and_never_replays(tmp_path):
    script = """
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from enterprise.canvas_task_journal import CanvasTaskJournal
journal = CanvasTaskJournal(Path(sys.argv[2]))
for name in ('queued', 'running', 'succeeded', 'jimeng_pending'):
    journal.create({'id': name, 'type': 'online-image', 'status': 'queued'})
    if name != 'queued':
        assert journal.mark_running(name)
    if name in ('succeeded', 'jimeng_pending'):
        journal.finish(name, {'status': name, 'result': {'images': ['/output/fixture.png']}, 'submit_id': 'external-fixture'})
os._exit(17)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(ROOT), str(tmp_path / "tasks")],
        timeout=20,
    )
    assert completed.returncode == 17
    journal = CanvasTaskJournal(tmp_path / "tasks")
    assert journal.recover() == {"interrupted": 2, "corrupt": 0}
    assert journal.recover() == {"interrupted": 0, "corrupt": 0}
    for name in ("queued", "running"):
        task = journal.get(name)
        assert task["status"] == "failed"
        assert task["recovery_required"] is True
        assert task["interrupted_status"] == name
        assert journal.mark_running(name) is False
    assert journal.get("succeeded")["result"] == {"images": ["/output/fixture.png"]}
    assert journal.get("jimeng_pending")["submit_id"] == "external-fixture"
    assert journal.get("jimeng_pending")["status"] == "jimeng_pending"


def test_atomic_write_failure_preserves_previous_record(tmp_path, monkeypatch):
    journal = CanvasTaskJournal(tmp_path)
    journal.create(record())
    def fail(*args):
        raise OSError("injected replace failure")
    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        journal.mark_running("canvas_img_fixture")
    assert journal.get("canvas_img_fixture")["status"] == "queued"
    assert not list(tmp_path.glob("*.tmp"))


def test_task_claim_is_single_use_and_completed_result_cannot_be_overwritten(tmp_path):
    journal = CanvasTaskJournal(tmp_path)
    journal.create(record())
    assert journal.mark_running("canvas_img_fixture")
    assert not journal.mark_running("canvas_img_fixture")
    journal.finish("canvas_img_fixture", {"status": "succeeded", "result": {"image": "/output/a.png"}})
    with pytest.raises(ValueError):
        journal.finish("canvas_img_fixture", {"status": "failed"})
    with pytest.raises(ValueError):
        journal.create(record())


def test_corrupt_record_is_preserved_and_reported_not_silently_dropped(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{"id":', encoding="utf-8")
    journal = CanvasTaskJournal(tmp_path)
    assert journal.recover()["corrupt"] == 1
    assert path.read_text(encoding="utf-8") == '{"id":'
    with pytest.raises(ValueError):
        journal.get("broken")


@pytest.mark.parametrize("task_id", ["../outside", "x/y", "x\\y", "", "x" * 161])
def test_record_path_cannot_escape_root(tmp_path, task_id):
    with pytest.raises(ValueError):
        CanvasTaskJournal(tmp_path).create(record(task_id))


def test_receipt_and_owner_are_written_before_gateway_response(tmp_path, monkeypatch):
    from enterprise import db
    journal = CanvasTaskJournal(tmp_path)
    monkeypatch.setattr(db, "get_user_by_id", lambda _: {"id": "alice"})
    def assign(user_id, task_id):
        assert journal.get(task_id)["enterprise_user_id"] == user_id
    mapping = MagicMock(side_effect=assign)
    monkeypatch.setattr(db, "record_canvas_image_task_owner", mapping)
    generic = MagicMock()
    monkeypatch.setattr(db, "record_task_owner", generic)
    monkeypatch.setattr(db, "get_canvas_image_task_owner", lambda _: "alice")
    create_task_receipt(journal, record(), "alice")
    mapping.assert_called_once_with("alice", "canvas_img_fixture")
    assert generic.call_count == 1


def test_invalid_owner_cannot_create_receipt(tmp_path, monkeypatch):
    from enterprise import db
    monkeypatch.setattr(db, "get_user_by_id", lambda _: None)
    journal = CanvasTaskJournal(tmp_path)
    with pytest.raises(ValueError):
        create_task_receipt(journal, record(), "unknown")
    assert not list(tmp_path.iterdir())


def test_main_hooks_persist_before_dispatch_and_return_result_after_memory_loss(tmp_path):
    install = tmp_path / "install"
    app = install / "releases" / "fixture"
    (app / "static").mkdir(parents=True)
    (app / "main.py").write_text("# fixture", encoding="utf-8")
    script = """
import asyncio, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from enterprise.paths import PortableRootInputs, derive_portable_path_roots, install_path_roots_for_process, prepare_application_directories
from enterprise.canvas_task_journal import CanvasTaskJournal
roots = derive_portable_path_roots(PortableRootInputs(Path(sys.argv[2]), Path(sys.argv[3])), 'fixture')
install_path_roots_for_process(roots)
prepare_application_directories(roots)
import main
calls = []
async def fake_provider(payload):
    calls.append('image')
    return {'images': ['/output/fake.png']}
def fake_comfy(payload):
    calls.append('comfy')
    return {'images': ['/output/comfy.png']}
main.build_online_image_result = fake_provider
main.generate = fake_comfy
async def run():
    request = main.OnlineImageRequest(prompt='private fixture prompt')
    reply = await main.create_canvas_image_task(request)
    task_id = reply['task_id']
    assert main.CANVAS_TASK_JOURNAL.get(task_id) is not None
    await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
    await main.run_canvas_image_task(task_id, request)
    assert calls == ['image']
    main.CANVAS_TASK_JOURNAL = CanvasTaskJournal(roots.DATA_ROOT / 'canvas-tasks')
    assert (await main.get_canvas_image_task(task_id))['result']['images'] == ['/output/fake.png']
    assert 'private fixture prompt' not in (roots.DATA_ROOT / 'canvas-tasks' / (task_id + '.json')).read_text(encoding='utf-8')
    comfy = await main.create_canvas_comfy_task(main.GenerateRequest())
    await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
    assert (await main.get_canvas_comfy_task(comfy['task_id']))['status'] == 'succeeded'
    assert (await main.get_canvas_comfy_task(comfy['task_id']))['workflow_json'] == 'Z-Image.json'
    def fail_receipt(*args):
        raise OSError('injected disk write failure')
    main.create_task_receipt = fail_receipt
    try:
        await main.create_canvas_image_task(request)
        raise AssertionError('acknowledged unpersisted task')
    except OSError:
        pass
    assert calls == ['image', 'comfy']
asyncio.run(run())
print('durable main hooks passed')
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(ROOT), str(install), str(tmp_path / "local")],
        cwd=ROOT, capture_output=True, text=True,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "durable main hooks passed" in completed.stdout
    assert sorted(p.relative_to(app).as_posix() for p in app.rglob("*") if p.is_file()) == ["main.py"]
