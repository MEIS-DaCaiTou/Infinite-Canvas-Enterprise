"""ComfyUI contract tests, real HTTP on loopback; no GPU, customer files or paid APIs."""
import json
import ast
import os
import random
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from enterprise.canvas_task_journal import CanvasTaskJournal
from enterprise.providers.comfyui import ComfyClient, ComfyExecutionError, base_url, endpoint


@pytest.fixture
def backend():
    state = {"posts": [], "phase": "queued"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def reply(self, data):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            state["posts"].append((self.path, body))
            if self.path == "/prefix/upload/image":
                self.reply({"name": "renamed.png", "subfolder": "task-inputs"})
            elif state["phase"] == "redirect":
                self.send_response(307)
                self.send_header("Location", "/prefix/redirected-prompt")
                self.end_headers()
            else:
                self.reply({"prompt_id": "accepted-id", "number": 42})

        def do_GET(self):
            if self.path == "/prefix/queue":
                self.reply({"queue_pending": [[42, "accepted-id"]] if state["phase"] == "queued" else [],
                            "queue_running": [[42, "accepted-id"]] if state["phase"] == "running" else []})
            elif state["phase"] == "done":
                self.reply({"accepted-id": {"status": {"completed": True, "status_str": "success"},
                    "outputs": {"save": {"images": [{"filename": "layer.png", "type": "output"}]}}}})
            elif state["phase"] == "error":
                self.reply({"accepted-id": {"status": {"status_str": "error", "messages": [
                    ["execution_error", {"exception_message": "missing model"}]]}}})
            else:
                self.reply({})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield ComfyClient(f"http://127.0.0.1:{server.server_port}/prefix"), state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_full_url_upload_reference_and_exact_task_queue(backend):
    client, state = backend
    name = client.upload("same-name.png", b"selected-subject", "image/png")
    assert name == "task-inputs/renamed.png"
    prompt = {"input": {"class_type": "LoadImage", "inputs": {"image": name}}}
    assert client.submit(prompt, "user-test") == "accepted-id"
    assert json.loads(state["posts"][-1][1])["prompt"] == prompt
    assert client.inspect("accepted-id") == ("queued", None)
    state["phase"] = "running"
    assert client.inspect("accepted-id") == ("running", None)
    state["phase"] = "done"
    assert client.inspect("accepted-id")[1]["outputs"]["save"]["images"][0]["filename"] == "layer.png"
    assert len(state["posts"]) == 2
    state["phase"] = "error"
    with pytest.raises(ComfyExecutionError, match="missing model"):
        client.inspect("accepted-id")
    state["phase"] = "redirect"
    with pytest.raises(RuntimeError, match="重定向"):
        client.submit(prompt, "do-not-replay")
    assert len(state["posts"]) == 3


def test_no_retry_on_lost_submit_response(monkeypatch):
    posts = []
    def lost(*args, **kwargs):
        posts.append(args)
        raise requests.Timeout("accepted but response lost")
    monkeypatch.setattr(requests, "post", lost)
    with pytest.raises(requests.Timeout):
        ComfyClient("localhost:8188").submit({}, "test")
    assert len(posts) == 1
    assert endpoint("https://example.test/comfy/", "/prompt") == "https://example.test/comfy/prompt"
    assert base_url("127.0.0.1:8188") == "http://127.0.0.1:8188"
    for value in ["https://user:secret@example.test", "https://example.test/?token=x", "file:///tmp"]:
        with pytest.raises(ValueError): base_url(value)


def test_accepted_task_survives_restart_without_replay_or_identity_change(tmp_path):
    journal = CanvasTaskJournal(tmp_path)
    journal.create({"id": "accepted", "type": "comfy", "status": "queued"})
    journal.mark_running("accepted")
    journal.record_comfy("accepted", {"backend": "https://example.test/comfy", "phase": "submitting"})
    journal.record_comfy("accepted", {"prompt_id": "original", "phase": "queued"})
    with pytest.raises(ValueError): journal.record_comfy("accepted", {"backend": "other:8188"})
    journal = CanvasTaskJournal(tmp_path)
    assert journal.recover()["interrupted"] == 1
    assert journal.claim_comfy_query("accepted")["prompt_id"] == "original"
    assert journal.get("accepted")["error_code"] == ""
    assert journal.claim_comfy_query("accepted") is None
    journal.create({"id": "uncertain", "type": "comfy", "status": "queued"})
    journal.mark_running("uncertain")
    journal.record_comfy("uncertain", {"backend": "localhost:8188", "phase": "submitting"})
    journal.recover()
    assert journal.claim_comfy_query("uncertain") is None


def test_shared_browser_session_contract():
    subprocess.run(["node", str(Path(__file__).with_name("test_comfy_session.js"))], check=True)


def test_imported_graph_keeps_original_nodes_and_rejects_obsolete_field_mapping(tmp_path):
    source = Path(__file__).resolve().parents[2] / "main.py"
    prepare = next(node for node in ast.parse(source.read_text(encoding="utf-8")).body
                   if isinstance(node, ast.FunctionDef) and node.name == "prepare_comfy_workflow")
    path = tmp_path / "workflow.json"
    path.write_text(json.dumps({
        "14": {"class_type": "LoadImage", "inputs": {"image": "original.png"}},
        "23": {"class_type": "Text", "inputs": {"text": "original prompt"}},
        "144": {"class_type": "SaveImage", "inputs": {"filename_prefix": "output"}},
    }), encoding="utf-8")
    scope = {"os": os, "json": json, "random": random, "BUILTIN_WORKFLOWS": set(),
             "workflow_path_from_name": lambda _: str(path), "ComfyExecutionError": ComfyExecutionError}
    exec(compile(ast.Module(body=[prepare], type_ignores=[]), str(source), "exec"), scope)
    request = SimpleNamespace(workflow_json="custom/tool.json", prompt="do not overwrite unrelated node",
                              width=1024, height=1024, params={"14": {"image": "bound/selected.png"}})
    graph, _ = scope["prepare_comfy_workflow"](request)
    assert graph["14"]["inputs"]["image"] == "bound/selected.png"
    assert graph["23"]["inputs"]["text"] == "original prompt"
    assert "width" not in graph["144"]["inputs"]
    for params in [{"old-node": {"image": "bound/selected.png"}}, {"14": {"obsolete_input": "bound/selected.png"}}]:
        request.params = params
        with pytest.raises(ComfyExecutionError, match="映射已失效"):
            scope["prepare_comfy_workflow"](request)
