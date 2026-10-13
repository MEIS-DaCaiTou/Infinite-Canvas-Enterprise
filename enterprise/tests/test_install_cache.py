"""Small closed payloads + actual Windows deletion/leases; never customer data.

Unless a test explicitly uses a live owner, process-exit observations are replaced
for the parent-owned fixtures. These tests do not claim full Setup GUI acceptance.
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path

import pytest

from enterprise import install_cache as cache
from enterprise.fresh_install import verify_release_assets
from enterprise.install_setup_bridge import CACHE_MAINTENANCE_REQUEST_SCHEMA, _decode_request, SetupBridgeError
from enterprise.release.release_manifest_v2 import canonical_json, materialize_release_fixture
from enterprise.runtime.ownership import process_identity
from enterprise.tests.test_install_entry import bundle, qualified_program_fixture


class Interrupted(BaseException):
    pass


@pytest.fixture
def prepared(tmp_path):
    # Deep function names + the canonical cache prefix otherwise exceed MAX_PATH
    # in older test helpers. Keep this owned fixture under the same pytest root.
    tmp_path = tmp_path.parent / ("c-" + uuid.uuid4().hex[:8])
    tmp_path.mkdir()
    target, manifest, archive, inventory, document = qualified_program_fixture(tmp_path)
    local = tmp_path / "local"
    container = cache.cache_root(local) / uuid.uuid4().hex
    assets = container / "install-ux-bundle"
    cache._io(assets).mkdir(parents=True)
    for source in (manifest, archive, inventory):
        shutil.copyfile(cache._io(source), cache._io(assets / ("ops-release-manifest-v2.json" if source == manifest else source.name)))
    bundle(tmp_path / "native", commit=document["enterprise_source"]["commit"], tree=document["enterprise_source"]["tree"])
    shutil.copytree(cache._io(tmp_path / "native"), cache._io(assets / "native-entry"))
    app = assets / "raw" / document["archive"]["root_prefix"]
    materialize_release_fixture(manifest, archive, inventory, cache._io(app))
    args = dict(local_app_data_base=local, assets=assets, raw_app_root=app,
                verified=verify_release_assets(cache._io(assets)), target=target, client=process_identity(os.getpid()))
    return args, container


def seal(prepared, monkeypatch=None):
    args, container = prepared
    with cache.setup_cache_session(**args) as session:
        cache.finish_setup_cache(session, {"status": "succeeded", "repair_state": "NONE"})
    if monkeypatch:
        monkeypatch.setattr(cache, "_exited", lambda _value: True)
    return args, container


def candidate(prepared):
    args, container = prepared
    return next(v for v in cache.inspect_cache(local_app_data_base=args["local_app_data_base"])["candidates"]
                if v["cache_id"] == container.name)


def clean(prepared, token=None, confirmed=True):
    args, container = prepared
    return cache.clean_cache(local_app_data_base=args["local_app_data_base"], cache_id=container.name,
                             token=token or candidate(prepared)["token"], confirmed=confirmed)


def preserved(args):
    target = args["target"]
    return {str(p.relative_to(target)): p.read_bytes() for p in target.rglob("*") if p.is_file()}


def test_registration_proves_closed_program_tree_not_arbitrary_directory(prepared):
    args, container = prepared
    before = preserved(args)
    seal(prepared)
    receipt, _ = cache._read(container.parent / ".ledger" / container.name / "receipt.json")
    assert receipt["files"] == cache._tree(container)["files"]
    assert receipt["release_id"] == args["verified"].manifest.release_id
    assert before == preserved(args)


def test_actual_setup_archive_layout_without_detached_raw_manifest_is_supported(prepared):
    args, container = prepared
    cache._io(args["raw_app_root"] / "release-manifest.json").unlink()
    seal(prepared)
    receipt, _ = cache._read(container.parent / ".ledger" / container.name / "receipt.json")
    assert receipt["files"] == cache._tree(container)["files"]


def test_optional_detached_raw_manifest_must_match_verified_asset(prepared):
    args, container = prepared
    cache._io(args["raw_app_root"] / "release-manifest.json").write_bytes(b"unproven manifest")
    with pytest.raises(cache.CacheError, match="INSTALL_CACHE_CONTENT_UNPROVEN"):
        seal(prepared)
    assert not (container.parent / ".ledger" / container.name).exists()


@pytest.mark.parametrize("member", ["archive", "raw-program"])
def test_registration_rechecks_bytes_against_detached_verified_inventory(prepared, member):
    args, container = prepared
    path = args["verified"].archive_path if member == "archive" else args["raw_app_root"] / "main.py"
    cache._io(path).write_bytes(b"changed after three-asset verification")
    before = preserved(args)
    with pytest.raises(cache.CacheError, match="INSTALL_CACHE_CONTENT_UNPROVEN"):
        seal(prepared)
    assert before == preserved(args)
    assert not (container.parent / ".ledger" / container.name).exists()


@pytest.mark.parametrize("extra", ["customer.db", "enterprise.env", "unknown-empty-directory/"])
def test_unproven_extra_content_is_not_registered(prepared, extra):
    args, container = prepared
    path = container / extra
    if extra.endswith("/"):
        path.mkdir()
    else:
        path.write_bytes(b"never-delete")
    with pytest.raises(cache.CacheError, match="INSTALL_CACHE_CONTENT_UNPROVEN"):
        seal(prepared)
    assert path.exists()
    assert not (container.parent / ".ledger" / container.name).exists()


def test_unregistered_legacy_cache_is_retained(prepared):
    args, container = prepared
    assert candidate(prepared)["status"] == "INSTALL_CACHE_UNPROVEN"
    assert container.exists()
    assert not (container.parent / ".ledger").exists()


def test_current_authenticated_client_and_worker_block_cleanup(prepared):
    seal(prepared)
    assert candidate(prepared)["status"] == "INSTALL_CACHE_BUSY"


def test_unknown_process_identity_is_not_absence(prepared, monkeypatch):
    seal(prepared)
    monkeypatch.setattr(cache, "process_identity", lambda _pid: None)
    assert candidate(prepared)["status"] == "INSTALL_CACHE_PROCESS_UNCONFIRMED"


@pytest.mark.skipif(os.name != "nt", reason="Windows kernel leases")
def test_live_kernel_lease_blocks_even_if_pid_observation_claims_exited(prepared, monkeypatch):
    args, container = seal(prepared, monkeypatch)
    ledger = container.parent / ".ledger" / container.name
    receipt, _ = cache._read(ledger / "receipt.json")
    with cache._lease(ledger / "runner.lock", receipt["lease_identity"]):
        assert candidate(prepared)["status"] == "INSTALL_CACHE_BUSY"
    assert candidate(prepared)["status"] == "CLEANABLE"


@pytest.mark.skipif(os.name != "nt", reason="Windows handle-bound deletion")
def test_explicit_owned_cleanup_frees_only_selected_program_tree(prepared, monkeypatch):
    args, container = seal(prepared, monkeypatch)
    legacy = container.parent / uuid.uuid4().hex
    legacy.mkdir()
    (legacy / "unknown.db").write_bytes(b"legacy-never-delete")
    before = preserved(args)
    view = candidate(prepared)
    assert view["status"] == "CLEANABLE" and view["size_bytes"] > 0
    with pytest.raises(cache.CacheError, match="INSTALL_CACHE_CONFIRMATION_REQUIRED"):
        clean(prepared, view["token"], confirmed=False)
    result = clean(prepared, view["token"])
    assert result["deleted_bytes"] == view["size_bytes"]
    assert not container.exists()
    assert not (container.parent / ".quarantine" / container.name).exists()
    assert legacy.exists() and (legacy / "unknown.db").read_bytes() == b"legacy-never-delete"
    assert before == preserved(args)


@pytest.mark.parametrize("change", ["bytes", "replacement", "extra", "empty-directory", "hardlink"])
def test_preview_changes_fail_closed_without_any_deletion(prepared, monkeypatch, change):
    args, container = seal(prepared, monkeypatch)
    preview = candidate(prepared)
    path = args["assets"] / "native-entry" / "InfiniteCanvas.exe"
    if change == "bytes":
        path.write_bytes(b"changed")
    elif change == "replacement":
        replacement = path.with_suffix(".new")
        replacement.write_bytes(path.read_bytes())
        path.unlink()
        replacement.rename(path)
    elif change == "extra":
        (container / "business.db").write_bytes(b"preserve")
    elif change == "empty-directory":
        (container / "unexpected").mkdir()
    else:
        os.link(path, path.with_suffix(".external-hardlink"))
    assert candidate(prepared)["status"] in {"INSTALL_CACHE_CHANGED", "INSTALL_CACHE_PATH_UNSAFE"}
    with pytest.raises(cache.CacheError):
        clean(prepared, preview["token"])
    assert path.exists() and container.exists()


def test_installation_identity_replacement_blocks_cleanup(prepared, monkeypatch):
    args, container = seal(prepared, monkeypatch)
    original = args["target"]
    original.rename(original.with_name("retained-installation"))
    original.mkdir()
    assert candidate(prepared)["status"] == "INSTALL_CACHE_CHANGED"
    assert container.exists()


def test_recovery_lock_keeps_support_bundle(prepared, monkeypatch):
    args, container = seal(prepared, monkeypatch)
    (args["target"] / "state/system-update-active.lock").write_bytes(b"unproven-recovery")
    assert candidate(prepared)["status"] == "INSTALL_CACHE_RECOVERY_DEPENDENCY"
    assert container.exists()


@pytest.mark.parametrize("state", ["RUNNING", "RECOVERY_REQUIRED"])
def test_nonterminal_result_never_authorizes_cleanup(prepared, monkeypatch, state):
    args, container = prepared
    with cache.setup_cache_session(**args) as session:
        cache.finish_setup_cache(session, {"status": "succeeded", "repair_state": state})
    monkeypatch.setattr(cache, "_exited", lambda _value: True)
    assert candidate(prepared)["status"] == "INSTALL_CACHE_RETAIN"


def test_cache_bookkeeping_failure_does_not_falsify_committed_repair(prepared, monkeypatch):
    args, _ = prepared
    response = {"status": "succeeded", "repair_state": "SUCCEEDED"}
    with cache.setup_cache_session(**args) as session:
        def fail(_target, _local):
            raise OSError("fixture bookkeeping failure")
        monkeypatch.setattr(cache, "_no_recovery_dependency", fail)
        cache.finish_setup_cache(session, response)
    assert response == {"status": "succeeded", "repair_state": "SUCCEEDED", "cache_warning": "INSTALL_CACHE_RETAINED"}
    assert candidate(prepared)["status"] == "INSTALL_CACHE_RETAIN"


@pytest.mark.skipif(os.name != "nt", reason="Windows handle-bound cleanup recovery")
@pytest.mark.parametrize("stage", ["deleting_recorded", "quarantined", "member_removed", "tree_removed"])
def test_interrupted_cleanup_requires_new_preview_then_explicit_resume(prepared, monkeypatch, stage):
    args, container = seal(prepared, monkeypatch)
    before = preserved(args)
    old = candidate(prepared)["token"]
    def interrupt(point):
        if point == stage:
            raise Interrupted()
    monkeypatch.setattr(cache, "_checkpoint", interrupt)
    with pytest.raises(Interrupted):
        clean(prepared, old)
    monkeypatch.setattr(cache, "_checkpoint", lambda _stage: None)
    fresh = candidate(prepared)
    assert fresh["status"] == "CLEANABLE" and fresh["token"] != old
    with pytest.raises(cache.CacheError, match="INSTALL_CACHE_PREVIEW_CHANGED"):
        clean(prepared, old)
    assert before == preserved(args)
    clean(prepared, fresh["token"])
    assert not container.exists() and not (container.parent / ".quarantine" / container.name).exists()
    assert before == preserved(args)


@pytest.mark.skipif(os.name != "nt", reason="Windows pinned-file substitution")
def test_handle_bound_delete_rejects_same_byte_replacement(prepared, monkeypatch):
    args, _ = seal(prepared, monkeypatch)
    path = args["assets"] / "native-entry/InfiniteCanvas.exe"
    expected = cache._file(path)
    replacement = path.with_suffix(".substitute")
    replacement.write_bytes(path.read_bytes())
    path.unlink()
    replacement.rename(path)
    with pytest.raises(cache.CacheError, match="INSTALL_CACHE_CHANGED"):
        cache._remove_file(path, expected)
    assert path.exists()


def cache_request(**changes):
    result = {"schema_version": CACHE_MAINTENANCE_REQUEST_SCHEMA, "operation": "inspect-cache",
              "install_mode": "custom", "install_root": "D:\\owned-fixture",
              "username": "", "password": "", "password_confirmation": "",
              "cache_id": "", "cache_token": "", "confirm_cache_cleanup": False}
    result.update(changes)
    return canonical_json(result)


@pytest.mark.parametrize("changes", [dict(username="unexpected"), dict(password="never-transmit"),
    dict(cache_id="a" * 32), dict(confirm_cache_cleanup=True), dict(operation="delete-install"),
    dict(operation="clean-cache", confirm_cache_cleanup=True, cache_id="../other", cache_token="b" * 64),
    dict(operation="clean-cache", confirm_cache_cleanup=False, cache_id="a" * 32, cache_token="b" * 64)])
def test_cache_protocol_is_closed_and_never_accepts_credentials(changes):
    with pytest.raises(SetupBridgeError, match="INSTALL_SETUP_BRIDGE_REQUEST_INVALID"):
        _decode_request(cache_request(**changes))


def test_cache_protocol_requires_bound_preview_for_one_explicit_selection():
    assert _decode_request(cache_request())["operation"] == "inspect-cache"
    result = _decode_request(cache_request(operation="clean-cache", confirm_cache_cleanup=True,
                                          cache_id="a" * 32, cache_token="b" * 64))
    assert result["cache_id"] == "a" * 32


def test_gui_cache_branch_is_inspection_only_no_shortcut_or_automatic_cleanup():
    source = Path(__file__).resolve().parents[2] / "installer/windows/InfiniteCanvasEnterprise.iss"
    text = source.read_text(encoding="utf-8-sig")
    assert 'MB_YESNO or MB_DEFBUTTON2' in text
    assert "INSTALL_CACHE_INSPECTION_ONLY" in text
    assert "Result := False; { Never reach installation, registry, shortcuts, or auto-start. }" in text
    assert "CachePage.SelectedValueIndex := -1;" in text
    assert "enterprise-install-maintenance-request-v5" in text
