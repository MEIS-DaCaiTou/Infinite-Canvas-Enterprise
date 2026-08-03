from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from enterprise.path_safety import PathSafetyError
from enterprise.release import release_manifest_v2
from enterprise.release.current_release import (
    CurrentRelease,
    canonical_json,
    read_current_release_result_from_state_root,
)
from enterprise.runtime.error_contract import RuntimeContractError
from enterprise.runtime.portable import build_portable_preflight, execute_portable_command, validate_portable_process_binding
from enterprise.runtime.runtime_manifest import STARTUP_CORE_FILES
from enterprise.release.release_manifest_v2 import build_inventory, canonical_json as release_canonical_json, sha256_bytes
from enterprise.tests.release_manifest_v2_fixture import release_manifest


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    install = tmp_path / "install"
    release_id = "ice-2026.07.6-bbbbbbbbbbbb"
    app = install / "releases" / release_id
    runtime = app / "python"
    runtime.mkdir(parents=True)
    (app / "main.py").write_text("# fixture\n", encoding="utf-8")
    (app / "static").mkdir()
    core: dict[str, bytes] = {}
    for name in STARTUP_CORE_FILES:
        content = f"core:{name}".encode()
        (runtime / name).write_bytes(content)
        core[name] = content
    manifest = {
        "architecture": "x64",
        "core_files": [
            {"filename": name, "sha256": _sha(content), "size_bytes": len(content)}
            for name, content in core.items()
        ],
        "python_abi": "cp314",
        "python_implementation": "CPython",
        "python_version": "3.14.6",
        "schema_version": "enterprise-windows-runtime-manifest-v1",
        "source": {"enterprise_commit": "a" * 40},
    }
    (app / "runtime-manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    runtime_manifest_sha = _sha((app / "runtime-manifest.json").read_bytes())
    inventory = build_inventory(app)
    (app / "release-payload-inventory.json").write_bytes(inventory.canonical_bytes)
    release_payload = release_manifest(release_id=release_id, runtime_manifest_sha256=runtime_manifest_sha).data
    release_payload["release_payload"].update({"inventory_sha256": inventory.sha256, "tree_sha256": inventory.tree_sha256, "file_count": len(inventory.entries), "total_size_bytes": inventory.total_size_bytes})
    release_payload["archive"].update({"inventory_sha256": inventory.sha256, "payload_tree_sha256": inventory.tree_sha256, "file_count": len(inventory.entries) + 1, "total_uncompressed_bytes": inventory.total_size_bytes + len(inventory.canonical_bytes)})
    release_bytes = release_canonical_json(release_payload)
    (app / "release-manifest.json").write_bytes(release_bytes)
    for directory in (
        install / "data",
        install / "logs",
        install / "state",
        tmp_path / "local" / "InfiniteCanvasEnterprise" / "runtime",
        tmp_path / "local" / "Infinite-Canvas-Enterprise" / "cache",
        tmp_path / "local" / "Infinite-Canvas-Enterprise" / "temp",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    pointer = CurrentRelease(
        "env-1b1b-current-release-v1",
        release_id,
        f"releases/{release_id}",
        sha256_bytes(release_bytes),
        "2026-07-27T00:00:00Z",
        None,
    )
    raw = canonical_json(pointer)
    (install / "state" / "current-release.json").write_bytes(raw)
    probe = {
        "implementation": "cpython",
        "version": "3.14.6",
        "cache_tag": "cpython-314",
        "machine": "AMD64",
        "pointer_bits": 64,
        "executable": str(runtime / "python.exe"),
        "prefix": str(runtime),
        "base_prefix": str(runtime),
        "soabi": None,
        "dont_write_bytecode": True,
        "no_user_site": True,
    }
    return app, tmp_path / "local", probe


def test_pointer_read_result_binds_exact_accepted_bytes(tmp_path: Path) -> None:
    app, _local, _probe = _fixture(tmp_path)
    raw = (app.parents[1] / "state" / "current-release.json").read_bytes()
    result = read_current_release_result_from_state_root(app.parents[1] / "state")
    assert result.release.release_id == "ice-2026.07.6-bbbbbbbbbbbb"
    assert result.raw_sha256 == _sha(raw)


def test_portable_preflight_cross_binds_pointer_manifest_python_and_roots(tmp_path: Path) -> None:
    app, local, probe = _fixture(tmp_path)
    evidence = build_portable_preflight(
        app,
        local_app_data_resolver=lambda: local,
        executable=app / "python" / "python.exe",
        python_probe=probe,
    )
    assert evidence.result.result == "pass"
    assert evidence.result.release_id == "ice-2026.07.6-bbbbbbbbbbbb"
    assert evidence.result.path_roots_identity == evidence.roots.root_identity
    assert evidence.result.runtime_manifest_sha256 == evidence.runtime_manifest.manifest_sha256
    assert evidence.result.python_executable_sha256 == evidence.python_identity.executable_sha256
    assert tuple(item.root_label for item in evidence.writable_probes) == (
        "DATA_ROOT", "LOG_ROOT", "RUNTIME_ROOT", "CACHE_ROOT", "TEMP_ROOT"
    )


def test_portable_preflight_prepares_missing_writable_roots_before_probe(tmp_path: Path) -> None:
    app, local, probe = _fixture(tmp_path)
    writable_roots = (
        app.parents[1] / "data",
        app.parents[1] / "logs",
        local / "InfiniteCanvasEnterprise" / "runtime",
        local / "Infinite-Canvas-Enterprise" / "cache",
        local / "Infinite-Canvas-Enterprise" / "temp",
    )
    for root in writable_roots:
        shutil.rmtree(root)

    evidence = build_portable_preflight(
        app,
        local_app_data_resolver=lambda: local,
        executable=app / "python" / "python.exe",
        python_probe=probe,
    )

    assert evidence.result.result == "pass"
    assert all(root.is_dir() for root in writable_roots)


def test_pointer_must_identify_launcher_release(tmp_path: Path) -> None:
    app, local, probe = _fixture(tmp_path)
    payload = json.loads((app.parents[1] / "state" / "current-release.json").read_text(encoding="utf-8"))
    payload["release_id"] = "release-B"
    payload["app_root_relative"] = "releases/release-B"
    (app.parents[1] / "state" / "current-release.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeContractError) as exc:
        build_portable_preflight(
            app,
            local_app_data_resolver=lambda: local,
            executable=app / "python" / "python.exe",
            python_probe=probe,
        )
    assert exc.value.code == "PORTABLE_RELEASE_POINTER_MISMATCH"


def test_pointer_must_bind_exact_release_manifest_bytes(tmp_path: Path) -> None:
    app, local, probe = _fixture(tmp_path)
    pointer_path = app.parents[1] / "state" / "current-release.json"
    payload = json.loads(pointer_path.read_text(encoding="utf-8"))
    payload["manifest_sha256"] = "f" * 64
    pointer_path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeContractError) as exc:
        build_portable_preflight(
            app,
            local_app_data_resolver=lambda: local,
            executable=app / "python" / "python.exe",
            python_probe=probe,
        )
    assert exc.value.code == "PORTABLE_RELEASE_MANIFEST_INVALID"


@pytest.mark.parametrize("field", ["minimum_launcher_contract", "minimum_runtime_contract"])
def test_portable_preflight_rejects_future_release_contract(tmp_path: Path, field: str) -> None:
    app, local, probe = _fixture(tmp_path)
    manifest_path = app / "release-manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["compatibility"][field] = 999
    raw = release_canonical_json(payload)
    manifest_path.write_bytes(raw)
    pointer_path = app.parents[1] / "state" / "current-release.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["manifest_sha256"] = _sha(raw)
    pointer_path.write_bytes(canonical_json(CurrentRelease(**pointer)))
    with pytest.raises(RuntimeContractError) as exc:
        build_portable_preflight(
            app,
            local_app_data_resolver=lambda: local,
            executable=app / "python" / "python.exe",
            python_probe=probe,
        )
    assert exc.value.code == "PORTABLE_RELEASE_CONTRACT_UNSUPPORTED"


def test_process_binding_uses_retained_context_not_current_pointer(tmp_path: Path) -> None:
    from enterprise.runtime.launch_context import build_launch_context, publish_launch_context

    app, local, probe = _fixture(tmp_path)
    evidence = build_portable_preflight(
        app,
        local_app_data_resolver=lambda: local,
        executable=app / "python" / "python.exe",
        python_probe=probe,
    )
    context = build_launch_context(evidence.result, instance_id="a" * 32)
    publish_launch_context(
        evidence.roots.RUNTIME_ROOT / "launch-context.json",
        context,
        expected_existing_identity=None,
    )
    # A later activation may change the pointer; an owned running process is
    # still bound to its retained immutable context.
    (app.parents[1] / "state" / "current-release.json").write_text("{}", encoding="utf-8")
    binding = validate_portable_process_binding(
        app_root=app,
        runtime_root=evidence.roots.RUNTIME_ROOT,
        instance_id=context.instance_id,
        expected_context_identity=context.identity,
        local_app_data_resolver=lambda: local,
        executable=app / "python" / "python.exe",
        python_probe=probe,
        install_roots=False,
    )
    assert binding.context.identity == context.identity
    assert binding.roots.root_identity == evidence.roots.root_identity


def test_process_binding_rejects_launch_context_manifest_mismatch(tmp_path: Path) -> None:
    from enterprise.runtime.launch_context import build_launch_context, publish_launch_context

    app, local, probe = _fixture(tmp_path)
    evidence = build_portable_preflight(
        app,
        local_app_data_resolver=lambda: local,
        executable=app / "python" / "python.exe",
        python_probe=probe,
    )
    context = replace(build_launch_context(evidence.result, instance_id="a" * 32), release_manifest_sha256="f" * 64)
    publish_launch_context(evidence.roots.RUNTIME_ROOT / "launch-context.json", context, expected_existing_identity=None)
    with pytest.raises(RuntimeContractError) as exc:
        validate_portable_process_binding(
            app_root=app,
            runtime_root=evidence.roots.RUNTIME_ROOT,
            instance_id=context.instance_id,
            expected_context_identity=context.identity,
            local_app_data_resolver=lambda: local,
            executable=app / "python" / "python.exe",
            python_probe=probe,
            install_roots=False,
        )
    assert exc.value.code == "PORTABLE_CONTEXT_UNTRUSTED"


def test_process_binding_rechecks_manifest_path_safety_from_retained_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from enterprise.runtime.launch_context import build_launch_context, publish_launch_context

    app, local, probe = _fixture(tmp_path)
    evidence = build_portable_preflight(
        app,
        local_app_data_resolver=lambda: local,
        executable=app / "python" / "python.exe",
        python_probe=probe,
    )
    context = build_launch_context(evidence.result, instance_id="a" * 32)
    publish_launch_context(
        evidence.roots.RUNTIME_ROOT / "launch-context.json",
        context,
        expected_existing_identity=None,
    )

    def reject(_path: Path, *, allow_missing: bool = False) -> None:
        raise PathSafetyError("fixture-reparse")

    monkeypatch.setattr(release_manifest_v2, "assert_no_reparse_ancestors", reject)
    with pytest.raises(RuntimeContractError) as exc:
        validate_portable_process_binding(
            app_root=app,
            runtime_root=evidence.roots.RUNTIME_ROOT,
            instance_id=context.instance_id,
            expected_context_identity=context.identity,
            local_app_data_resolver=lambda: local,
            executable=app / "python" / "python.exe",
            python_probe=probe,
            install_roots=False,
        )
    assert exc.value.code == "PORTABLE_CONTEXT_UNTRUSTED"


@pytest.mark.parametrize("error_code", ["PORTABLE_RELEASE_MANIFEST_INVALID", "PORTABLE_RELEASE_CONTRACT_UNSUPPORTED"])
def test_status_reports_damaged_manifest_without_context_as_read_only_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error_code: str
) -> None:
    monkeypatch.setattr(
        "enterprise.runtime.portable.build_portable_preflight",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeContractError(error_code)),
    )
    monkeypatch.setattr("enterprise.runtime.portable._derive_install_root", lambda _app: tmp_path / "install")
    monkeypatch.setattr("enterprise.runtime.portable.windows_local_app_data_known_folder", lambda: tmp_path / "local")
    monkeypatch.setattr(
        "enterprise.runtime.portable.read_launch_context",
        lambda _path: (_ for _ in ()).throw(RuntimeContractError("LAUNCH_CONTEXT_INVALID")),
    )
    payload, exit_code = execute_portable_command(app_root=tmp_path / "install/releases/release-A", command="status")
    assert exit_code == 0
    assert payload == {
        "release_manifest_error_code": error_code,
        "release_manifest_v2_valid": False,
        "status": "invalid",
    }
