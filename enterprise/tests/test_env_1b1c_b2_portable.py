from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from enterprise.release.current_release import (
    CurrentRelease,
    canonical_json,
    read_current_release_result_from_state_root,
)
from enterprise.runtime.error_contract import RuntimeContractError
from enterprise.runtime.portable import build_portable_preflight, validate_portable_process_binding
from enterprise.runtime.runtime_manifest import STARTUP_CORE_FILES


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    install = tmp_path / "install"
    app = install / "releases" / "release-A"
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
        "python_abi": "cp310",
        "python_implementation": "CPython",
        "python_version": "3.10.11",
        "schema_version": "enterprise-windows-runtime-manifest-v1",
        "source": {"enterprise_commit": "a" * 40},
    }
    (app / "runtime-manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
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
        "release-A",
        "releases/release-A",
        "b" * 64,
        "2026-07-27T00:00:00Z",
        None,
    )
    raw = canonical_json(pointer)
    (install / "state" / "current-release.json").write_bytes(raw)
    probe = {
        "implementation": "cpython",
        "version": "3.10.11",
        "cache_tag": "cpython-310",
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
    assert result.release.release_id == "release-A"
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
    assert evidence.result.release_id == "release-A"
    assert evidence.result.path_roots_identity == evidence.roots.root_identity
    assert evidence.result.runtime_manifest_sha256 == evidence.runtime_manifest.manifest_sha256
    assert evidence.result.python_executable_sha256 == evidence.python_identity.executable_sha256
    assert tuple(item.root_label for item in evidence.writable_probes) == (
        "DATA_ROOT", "LOG_ROOT", "RUNTIME_ROOT", "CACHE_ROOT", "TEMP_ROOT"
    )


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
