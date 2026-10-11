"""Opt-in complete Windows lifecycle and actual process-death drills.

Only fresh owned installations are touched. Bundled Python runs frozen code;
Runtime, files, database and verifier APIs are real. The sole fault injection
terminates the exact test-owned runner at an explicit checkpoint.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import uuid

import pytest

from enterprise import install_cache as files
from enterprise.tests.test_install_cache_windows import full_inputs, _prepare

RUNNER = r'''
import json, os, sys
sys.path.insert(0, sys.argv[1])
from enterprise import install_lifecycle as lifecycle
def checkpoint(stage):
    if stage == sys.argv[6]: os._exit(93)
lifecycle._checkpoint = checkpoint
arguments = dict(install_root=sys.argv[2], release_dir=sys.argv[3],
                 local_app_data_base=sys.argv[4], confirm_no_active_tasks=True)
try:
    if sys.argv[5] == 'reinstall': result = lifecycle.reinstall_retained(**arguments)
    else: result = lifecycle.uninstall_retaining_data(**arguments, recover=sys.argv[5] == 'recover')
except Exception as exc:
    print(json.dumps({'error': getattr(exc, 'code', type(exc).__name__)}), flush=True)
    raise SystemExit(2)
print(json.dumps(result, separators=(',', ':')), flush=True)
'''


def _run(inputs, app, operation, checkpoint=""):
    return subprocess.run([str(app / "python/python.exe"), "-I", "-B", "-c", RUNNER,
        str(app), str(inputs["target"]), str(inputs["assets"]), str(inputs["local"]),
        operation, checkpoint], cwd=app, capture_output=True, timeout=300,
        creationflags=subprocess.CREATE_NO_WINDOW)


def _result(process):
    assert process.returncode == 0, (process.returncode, process.stdout[-500:], process.stderr[-500:])
    return json.loads(process.stdout)


def _business(inputs):
    root = inputs["target"]
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*") if p.is_file() and
        (p.relative_to(root).parts[0] in {"data", "config", "backups"}
         or p.name in {"installation.json", "current-release.json"})}


def _entry(inputs, mode):
    output = inputs["base"] / ("native-" + mode + "-" + uuid.uuid4().hex[:8] + ".json")
    process = subprocess.run([str(inputs["target"] / "InfiniteCanvas.exe"), "--" + mode,
        "--result-file", str(output)], cwd=inputs["base"], capture_output=True,
        timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
    assert process.returncode == 0, (process.returncode, process.stdout[-500:], process.stderr[-500:])
    result = json.loads(output.read_bytes())
    if mode == "identity":
        assert result["release_id"] == inputs["verified"].manifest.release_id
    return result


@pytest.mark.parametrize("checkpoint", ["", "program_retained", "program_reinstated"])
def test_complete_payload_retains_business_and_recovers_actual_runner_death(full_inputs, checkpoint):
    inputs = full_inputs
    _container, app = _prepare(inputs)  # External Setup preparation, not the moving program.
    root = inputs["target"]
    program = root / "releases" / inputs["verified"].manifest.release_id
    before, original_program, original_entry = _business(inputs), files._tree(program), files._file(root / "InfiniteCanvas.exe")
    _entry(inputs, "identity")
    installation_id = json.loads((root / "state/installation.json").read_bytes())["installation_id"]
    operation = "uninstall"
    if checkpoint == "program_retained":
        interrupted = _run(inputs, app, operation, checkpoint)
        assert interrupted.returncode == 93 and not interrupted.stdout
        assert not program.exists() and (root / "InfiniteCanvas.exe").exists()
        assert _business(inputs) == before
        operation = "recover"
    result = _result(_run(inputs, app, operation))
    assert result["lifecycle_state"] == "UNINSTALLED"
    assert result["installation_id"] == installation_id
    assert not program.exists() and not (root / "InfiniteCanvas.exe").exists()
    assert (root / "state/system-update-active.lock").exists() and _business(inputs) == before
    if checkpoint == "program_reinstated":
        interrupted = _run(inputs, app, "reinstall", checkpoint)
        assert interrupted.returncode == 93 and not interrupted.stdout
        assert program.exists() and not (root / "InfiniteCanvas.exe").exists()
        assert (root / "state/system-update-active.lock").exists() and _business(inputs) == before
    restored = _result(_run(inputs, app, "reinstall"))
    assert restored["lifecycle_state"] == "INSTALLED" and restored["installation_id"] == result["installation_id"]
    assert not (root / "state/system-update-active.lock").exists()
    assert files._tree(program) == original_program and files._file(root / "InfiniteCanvas.exe") == original_entry
    assert _business(inputs) == before
    assert _entry(inputs, "status")["worker_exit_code"] == 0
