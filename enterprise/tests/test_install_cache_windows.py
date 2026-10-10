"""Opt-in complete-payload Windows cache drills; no GUI/customer/production claim.

The authenticated pipe client and bundled worker really exit. No substituted PID
observations, verifier or file/lease APIs. Runtime/cache fixture identities are new;
only their selected closed preparation tree may be deleted.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from enterprise import fresh_install as fresh, install_cache as cache
from enterprise.install_setup_bridge import CACHE_MAINTENANCE_REQUEST_SCHEMA
from enterprise.release.release_manifest_v2 import materialize_release_fixture
from enterprise.runtime.portable import windows_local_app_data_known_folder

CLIENT = r'''
import json, subprocess, sys, uuid
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from enterprise.tests.test_install_ux_1 import _client_exchange
app=Path(sys.argv[2]); request=json.loads(sys.argv[3]); suffix=uuid.uuid4().hex
p=subprocess.Popen([str(app/'python/python.exe'),'-I','-B',str(app/'enterprise/install_setup_bridge.py'),
                    '--pipe-name',suffix],stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
try:
    result=_client_exchange(suffix,request)
    out,err=p.communicate(timeout=180)
    assert p.returncode==0 and not out and not err, (p.returncode,len(out),len(err))
    print(json.dumps(result,separators=(',',':')),flush=True)
    if sys.argv[4]=='hold': sys.stdin.readline()
finally:
    if p.poll() is None:
        p.terminate(); p.wait(timeout=10)
'''

CLEANER = r'''
import json, os, sys
sys.path.insert(0,sys.argv[1])
from enterprise import install_cache as cache
def checkpoint(stage):
    if stage==sys.argv[5]: os._exit(93)
cache._checkpoint=checkpoint
cache.clean_cache(local_app_data_base=sys.argv[2],cache_id=sys.argv[3],token=sys.argv[4],confirmed=True)
raise AssertionError('hard exit checkpoint not reached')
'''


@pytest.fixture(scope="module")
def full_inputs(tmp_path_factory):
    if os.name != "nt" or not all(os.environ.get(k) for k in ("ICE_CACHE_RELEASE_ASSETS", "ICE_NATIVE_ENTRY")):
        pytest.skip("opt-in requires clean same-source complete Release assets and compiled native entry")
    assets = Path(os.environ["ICE_CACHE_RELEASE_ASSETS"]).absolute()
    native = Path(os.environ["ICE_NATIVE_ENTRY"]).absolute().parent
    verified = fresh.verify_release_assets(assets)
    source = verified.manifest.section("enterprise_source")
    from enterprise.install_entry import verify_entry_bundle
    verify_entry_bundle(native, commit=source["commit"], tree=source["tree"])
    base = tmp_path_factory.getbasetemp()
    local = windows_local_app_data_known_folder()
    target = base / ("i-" + uuid.uuid4().hex[:8])
    password = "Fixture-only-Cache-Strong-Password-2026!"
    fresh.install_greenfield(release_dir=assets, install_root=target, username="cache-fixture-maintainer",
                             password=password, password_confirmation=password,
                             local_app_data_base=local, native_entry_dir=native)
    (target / "data/cache-gate-only-media.bin").write_bytes(b"owned synthetic media, never customer")
    return dict(base=base, assets=assets, native=native, verified=verified, target=target, local=local)


def _prepare(inputs):
    container = cache.cache_root(inputs["local"]) / uuid.uuid4().hex
    assets = container / "install-ux-bundle"
    cache._io(assets).mkdir(parents=True)
    verified = inputs["verified"]
    for source in (verified.manifest_path, verified.archive_path, verified.inventory_path):
        shutil.copyfile(source, cache._io(assets / source.name))
    shutil.copytree(inputs["native"], cache._io(assets / "native-entry"))
    app = assets / "raw" / verified.manifest.section("archive")["root_prefix"]
    materialize_release_fixture(verified.manifest_path, verified.archive_path, verified.inventory_path, cache._io(app))
    return container, app


def _preview(inputs, container):
    return next(v for v in cache.inspect_cache(local_app_data_base=inputs["local"])["candidates"]
                if v["cache_id"] == container.name)


def _client(inputs, app, *, hold=False, operation="inspect-cache", selected=None):
    request = {"schema_version": CACHE_MAINTENANCE_REQUEST_SCHEMA, "operation": operation,
               "install_mode": "custom", "install_root": str(inputs["target"]),
               "username": "", "password": "", "password_confirmation": "",
               "cache_id": selected["cache_id"] if selected else "",
               "cache_token": selected["token"] if selected else "", "confirm_cache_cleanup": bool(selected)}
    repo = Path(__file__).resolve().parents[2]
    process = subprocess.Popen([sys.executable, "-B", "-c", CLIENT, str(repo), str(app),
                                json.dumps(request), "hold" if hold else "exit"],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    return process


def _end(process):
    try:
        out, err = process.communicate(input="\n", timeout=180)
    except BaseException:
        process.terminate()  # Only this exact test-owned client; not a PID search.
        process.wait(timeout=10)
        raise
    assert process.returncode == 0 and not err, (process.returncode, err[:1000])
    return json.loads(out)


def _preserved(inputs):
    root = inputs["target"]
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def test_actual_pipe_client_remains_busy_after_bundled_worker_exits(full_inputs):
    container, app = _prepare(full_inputs)
    before = _preserved(full_inputs)
    process = _client(full_inputs, app, hold=True)
    try:
        line = process.stdout.readline()
        assert json.loads(line)["code"] == "INSTALL_CACHE_PREVIEW"
        assert process.poll() is None
        assert _preview(full_inputs, container)["status"] == "INSTALL_CACHE_BUSY"
    finally:
        out, err = process.communicate(input="\n", timeout=30)
        assert process.returncode == 0 and not err and not out
    view = _preview(full_inputs, container)
    assert view["status"] == "CLEANABLE"
    result = cache.clean_cache(local_app_data_base=full_inputs["local"], cache_id=container.name,
                               token=view["token"], confirmed=True)
    assert result["deleted_bytes"] == view["size_bytes"] and not container.exists()
    assert before == _preserved(full_inputs)


def test_authenticated_v5_cleanup_preserves_current_full_installation(full_inputs):
    old, old_app = _prepare(full_inputs)
    assert _end(_client(full_inputs, old_app))["code"] == "INSTALL_CACHE_PREVIEW"
    selected = _preview(full_inputs, old)
    assert selected["status"] == "CLEANABLE"
    container, app = _prepare(full_inputs)
    before = _preserved(full_inputs)
    result = _end(_client(full_inputs, app, operation="clean-cache", selected=selected))
    assert result["code"] == "INSTALL_CACHE_REMOVED" and result["status"] == "succeeded"
    assert result["deleted_bytes"] == selected["size_bytes"] and not old.exists()
    assert before == _preserved(full_inputs)
    view = _preview(full_inputs, container)
    assert view["status"] == "CLEANABLE"
    cache.clean_cache(local_app_data_base=full_inputs["local"], cache_id=container.name,
                      token=view["token"], confirmed=True)


@pytest.mark.parametrize("stage", ["quarantined", "member_removed"])
def test_real_process_death_retains_quarantine_and_requires_new_explicit_confirmation(full_inputs, stage):
    container, app = _prepare(full_inputs)
    assert _end(_client(full_inputs, app))["code"] == "INSTALL_CACHE_PREVIEW"
    before = _preserved(full_inputs)
    old = _preview(full_inputs, container)
    repo = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, "-B", "-c", CLEANER, str(repo), str(full_inputs["local"]),
                             container.name, old["token"], stage], capture_output=True,
                            timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 93 and not result.stdout and not result.stderr
    view = _preview(full_inputs, container)
    assert view["status"] == "CLEANABLE" and view["token"] != old["token"]
    with pytest.raises(cache.CacheError, match="INSTALL_CACHE_PREVIEW_CHANGED"):
        cache.clean_cache(local_app_data_base=full_inputs["local"], cache_id=container.name,
                          token=old["token"], confirmed=True)
    assert before == _preserved(full_inputs)
    cache.clean_cache(local_app_data_base=full_inputs["local"], cache_id=container.name,
                      token=view["token"], confirmed=True)
    assert not container.exists() and not (container.parent / ".quarantine" / container.name).exists()
    assert before == _preserved(full_inputs)
