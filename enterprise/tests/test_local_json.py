import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from enterprise import local_json


@pytest.mark.parametrize("failure", ["serialization", "sync", "replace"])
def test_failed_save_preserves_previous_document_and_cleans_own_temp(tmp_path, monkeypatch, failure):
    path = tmp_path / "canvas.json"
    local_json.atomic_write_json(path, {"title": "原画布", "nodes": [1]})
    original = path.read_bytes()
    unrelated = tmp_path / ".canvas.other.tmp"
    unrelated.write_text("unrelated")
    payload = {"nodes": [object()]} if failure == "serialization" else {"nodes": [2]}
    def fail(*args):
        raise OSError("injected write failure")
    if failure != "serialization":
        monkeypatch.setattr(local_json.os, "fsync" if failure == "sync" else "replace", fail)
    with pytest.raises((TypeError, OSError)):
        local_json.atomic_write_json(path, payload)
    assert path.read_bytes() == original
    assert set(tmp_path.iterdir()) == {path, unrelated}


def test_concurrent_reads_never_observe_partial_json(tmp_path):
    path = tmp_path / "conversation.json"
    local_json.atomic_write_json(path, {"revision": 0, "text": "旧" * 5000})
    def save():
        for revision in range(1, 25):
            local_json.atomic_write_json(path, {"revision": revision, "text": "新" * 5000})
    with ThreadPoolExecutor() as pool:
        future = pool.submit(save)
        for _ in range(150):
            document = local_json.read_json(path)
            assert len(document["text"]) == 5000
        future.result()
    assert json.loads(path.read_text(encoding="utf-8"))["revision"] == 24
    assert list(tmp_path.iterdir()) == [path]


def test_read_retries_sharing_violation_but_not_invalid_data(tmp_path, monkeypatch):
    path = tmp_path / "canvas.json"
    local_json.atomic_write_json(path, {"nodes": [1]})
    real_open = local_json.Path.open
    attempts = []
    def busy_once(self, *args, **kwargs):
        attempts.append(self)
        if len(attempts) == 1:
            error = PermissionError("replacement in progress")
            error.winerror = 32
            raise error
        return real_open(self, *args, **kwargs)
    monkeypatch.setattr(local_json.Path, "open", busy_once)
    assert local_json.read_json(path) == {"nodes": [1]}
    assert len(attempts) == 2
    path.write_text("not json", encoding="utf-8")
    attempts.clear()
    with pytest.raises(json.JSONDecodeError):
        local_json.read_json(path)
    assert len(attempts) == 2  # one sharing failure, then the actual parse error
