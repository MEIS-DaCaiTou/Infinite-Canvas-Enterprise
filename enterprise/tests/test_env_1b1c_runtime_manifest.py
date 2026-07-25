"""ENV-1B1C-B1 bounded Runtime Manifest startup parser tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from enterprise.runtime.error_contract import RuntimeContractError
from enterprise.runtime.runtime_manifest import (
    RuntimeManifestStartupView,
    STARTUP_CORE_FILES,
    StartupCoreFile,
    assert_no_reparse_ancestors,
    parse_runtime_manifest_startup_view,
    sha256_file,
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


def test_r3_reparse_inspection_error_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import enterprise.path_safety as path_safety

    def denied(_path: object) -> object:
        raise PermissionError("denied")

    monkeypatch.setattr(path_safety.os, "lstat", denied)
    with pytest.raises(RuntimeContractError) as exc:
        assert_no_reparse_ancestors(tmp_path / "runtime")
    assert exc.value.code == "RUNTIME_MANIFEST_REPARSE_FORBIDDEN"


def test_r3_hard_core_record_limit_is_enforced(tmp_path: Path) -> None:
    runtime, manifest = _runtime_fixture(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    for index in range(4):
        payload["core_files"].append({"filename": f"extra-{index}.dll", "sha256": "0" * 64, "size_bytes": 0})
    manifest.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    with pytest.raises(RuntimeContractError) as exc:
        parse_runtime_manifest_startup_view(manifest, runtime)
    assert exc.value.code == "RUNTIME_MANIFEST_CORE_LIMIT_EXCEEDED"


@pytest.mark.parametrize("candidate_id", ["", "contains space", "../escape", "x" * 129])
def test_r3_invalid_optional_candidate_id_fails_closed(tmp_path: Path, candidate_id: str) -> None:
    runtime, manifest = _runtime_fixture(tmp_path, candidate_id=candidate_id)
    with pytest.raises(RuntimeContractError) as exc:
        parse_runtime_manifest_startup_view(manifest, runtime)
    assert exc.value.code == "RUNTIME_MANIFEST_METADATA_INVALID"


@pytest.mark.parametrize("source", [None, "bad", {"enterprise_commit": 1}, {"enterprise_commit": "a" * 39}, {"enterprise_commit": "a" * 39 + "\\n"}, {"enterprise_commit": "C:/escape"}])
def test_r4_source_metadata_is_strict_when_present(tmp_path: Path, source: object) -> None:
    runtime, manifest = _runtime_fixture(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["source"] = source
    manifest.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    with pytest.raises(RuntimeContractError) as exc:
        parse_runtime_manifest_startup_view(manifest, runtime)
    assert exc.value.code == "RUNTIME_MANIFEST_METADATA_INVALID"


def _typed_view(records: tuple[StartupCoreFile, ...]) -> RuntimeManifestStartupView:
    digest = hashlib.sha256()
    for record in records:
        encoded = record.relative_path.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(record.size_bytes.to_bytes(8, "big"))
        digest.update(bytes.fromhex(record.sha256))
    return RuntimeManifestStartupView(
        schema_version="env-1b1c-runtime-manifest-startup-view-v1", manifest_sha256="a" * 64,
        python_version="3.10.11", python_implementation="CPython", python_abi="cp310",
        architecture="x64", architecture_supported=True, startup_core_files=records,
        startup_core_digest=digest.hexdigest(), candidate_id=None, manifest_self_declared_enterprise_commit=None,
    )


@pytest.mark.parametrize("size", [64 * 1024 * 1024 + 1, 70 * 1024 * 1024])
def test_r5_typed_manifest_reapplies_single_file_hash_limit(size: int) -> None:
    records = tuple(StartupCoreFile(name, "e" * 64, size if name == "python.exe" else 1) for name in STARTUP_CORE_FILES)
    with pytest.raises(RuntimeContractError) as exc:
        _typed_view(records).validated()
    assert exc.value.code == "RUNTIME_MANIFEST_HASH_LIMIT_EXCEEDED"


def test_r5_typed_manifest_reapplies_total_hash_limit() -> None:
    records = tuple(StartupCoreFile(name, "e" * 64, 30 * 1024 * 1024) for name in STARTUP_CORE_FILES)
    with pytest.raises(RuntimeContractError) as exc:
        _typed_view(records).validated()
    assert exc.value.code == "RUNTIME_MANIFEST_HASH_LIMIT_EXCEEDED"


@pytest.mark.parametrize("stage", ["open", "read", "close"])
def test_r5_core_hash_os_errors_are_mapped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str) -> None:
    target = tmp_path / "python.exe"
    target.write_bytes(b"core")
    if stage == "open":
        monkeypatch.setattr(Path, "open", lambda *_a, **_k: (_ for _ in ()).throw(PermissionError("host detail")))
    elif stage == "read":
        class BrokenRead:
            def __enter__(self): return self
            def __exit__(self, *_a): return None
            def read(self, _n): raise PermissionError("host detail")
        monkeypatch.setattr(Path, "open", lambda *_a, **_k: BrokenRead())
    else:
        original = Path.open
        class BrokenClose:
            def __enter__(self): self.handle = original(target, "rb"); return self.handle
            def __exit__(self, *_a): self.handle.close(); raise PermissionError("host detail")
        monkeypatch.setattr(Path, "open", lambda *_a, **_k: BrokenClose())
    with pytest.raises(RuntimeContractError) as exc:
        sha256_file(target)
    assert exc.value.code == "RUNTIME_MANIFEST_CORE_READ_FAILED"
    assert "host detail" not in exc.value.payload.canonical_json().decode("utf-8")
