"""ENV-1B1C-B1 bounded Runtime Manifest startup parser tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from enterprise.runtime.error_contract import RuntimeContractError
from enterprise.runtime.runtime_manifest import (
    STARTUP_CORE_FILES,
    parse_runtime_manifest_startup_view,
    validate_manifest_relative_path,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _runtime_fixture(tmp_path: Path, *, architecture: str = "x64", candidate_id: str | None = None) -> tuple[Path, Path]:
    runtime = tmp_path / "python-runtime"
    runtime.mkdir()
    core = {}
    for name in STARTUP_CORE_FILES:
        content = f"core:{name}".encode("utf-8")
        (runtime / name).write_bytes(content)
        core[name] = content
    payload = {
        "architecture": architecture,
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
    if candidate_id is not None:
        payload["candidate_id"] = candidate_id
    manifest = tmp_path / "runtime-manifest.json"
    manifest.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return runtime, manifest


def test_runtime_manifest_startup_view_uses_fixed_five_files(tmp_path: Path) -> None:
    runtime, manifest = _runtime_fixture(tmp_path)
    view = parse_runtime_manifest_startup_view(manifest, runtime)
    assert tuple(item.relative_path for item in view.startup_core_files) == STARTUP_CORE_FILES
    assert view.architecture == "x64"
    assert view.architecture_supported is True
    assert view.runtime_manifest_v1_self_consistency_checked is True
    assert view.runtime_provenance_promoted is False
    assert view.Manifest_v2_implemented is False
    assert view.candidate_id is None
    assert view.manifest_self_declared_enterprise_commit == "a" * 40


def test_candidate_id_is_optional_metadata(tmp_path: Path) -> None:
    runtime, manifest = _runtime_fixture(tmp_path, candidate_id="candidate-1")
    assert parse_runtime_manifest_startup_view(manifest, runtime).candidate_id == "candidate-1"


def test_arm64_parses_but_is_not_approved_for_current_portable_target(tmp_path: Path) -> None:
    runtime, manifest = _runtime_fixture(tmp_path, architecture="ARM64")
    view = parse_runtime_manifest_startup_view(manifest, runtime)
    assert view.architecture == "arm64"
    assert view.architecture_supported is False


def test_missing_core_file_fails_closed(tmp_path: Path) -> None:
    runtime, manifest = _runtime_fixture(tmp_path)
    (runtime / "pythonw.exe").unlink()
    with pytest.raises(RuntimeContractError) as exc:
        parse_runtime_manifest_startup_view(manifest, runtime)
    assert exc.value.code == "RUNTIME_MANIFEST_CORE_MISSING"


def test_core_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    runtime, manifest = _runtime_fixture(tmp_path)
    (runtime / "python.exe").write_bytes(b"tampered")
    with pytest.raises(RuntimeContractError) as exc:
        parse_runtime_manifest_startup_view(manifest, runtime)
    assert exc.value.code == "RUNTIME_MANIFEST_CORE_HASH_MISMATCH"


@pytest.mark.parametrize("value", ["../python.exe", r"folder\python.exe", "/python.exe", "C:python.exe", "CON", "file:name", "*.dll"])
def test_manifest_relative_paths_are_strict(value: str) -> None:
    with pytest.raises(RuntimeContractError):
        validate_manifest_relative_path(value)


def test_duplicate_manifest_key_fails_closed(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    manifest = tmp_path / "runtime-manifest.json"
    manifest.write_text('{"schema_version":"x","schema_version":"x"}', encoding="utf-8")
    with pytest.raises(RuntimeContractError) as exc:
        parse_runtime_manifest_startup_view(manifest, runtime)
    assert exc.value.code == "RUNTIME_MANIFEST_DUPLICATE_KEY"
