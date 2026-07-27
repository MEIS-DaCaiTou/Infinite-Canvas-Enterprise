"""ENV-1B1C-B1 launch context primitive tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from enterprise.runtime.error_contract import RuntimeContractError
from enterprise.runtime.launch_context import (
    LAUNCH_CONTEXT_FILENAME,
    RuntimeLaunchContext,
    build_launch_context,
    publish_launch_context,
    read_launch_context,
)
from enterprise.runtime.preflight import StartupPreflightResult


SHA = "a" * 64


def _context(instance_id: str = "1" * 32):
    preflight = StartupPreflightResult(
        result="pass",
        mode="portable-release",
        release_id="release-A",
        app_root_relative="releases/release-A",
        path_roots_identity=SHA,
        current_release_sha256="b" * 64,
        runtime_manifest_sha256="c" * 64,
        python_executable_sha256="d" * 64,
        python_implementation="CPython",
        python_version="3.10.11",
        python_abi="cp310",
        architecture="x64",
        bytecode_policy="disabled-no-user-site",
        writable_roots_verified=("DATA_ROOT", "LOG_ROOT", "RUNTIME_ROOT", "CACHE_ROOT", "TEMP_ROOT"),
    )
    return build_launch_context(preflight, instance_id=instance_id)


def test_launch_context_build_read_publish_and_replace(tmp_path: Path) -> None:
    target = tmp_path / LAUNCH_CONTEXT_FILENAME
    first = _context("1" * 32)
    result = publish_launch_context(target, first, expected_existing_identity=None)
    assert result.pointer_replaced is True
    assert read_launch_context(target).identity == first.identity

    second = _context("2" * 32)
    with pytest.raises(RuntimeContractError) as exc:
        publish_launch_context(target, second, expected_existing_identity=None)
    assert exc.value.code == "LAUNCH_CONTEXT_EXISTING_REQUIRED"

    publish_launch_context(target, second, expected_existing_identity=first.identity)
    assert read_launch_context(target).identity == second.identity


def test_launch_context_expected_existing_identity_is_enforced(tmp_path: Path) -> None:
    target = tmp_path / LAUNCH_CONTEXT_FILENAME
    publish_launch_context(target, _context("1" * 32), expected_existing_identity=None)
    with pytest.raises(RuntimeContractError) as exc:
        publish_launch_context(target, _context("2" * 32), expected_existing_identity="f" * 64)
    assert exc.value.code == "LAUNCH_CONTEXT_EXISTING_MISMATCH"


def test_launch_context_foreign_temp_is_preserved(tmp_path: Path) -> None:
    target = tmp_path / LAUNCH_CONTEXT_FILENAME
    foreign = tmp_path / "launch-context.json.new"
    foreign.write_text("foreign", encoding="utf-8")
    with pytest.raises(RuntimeContractError) as exc:
        publish_launch_context(target, _context(), expected_existing_identity=None)
    assert exc.value.code == "LAUNCH_CONTEXT_TEMP_EXISTS"
    assert foreign.read_text(encoding="utf-8") == "foreign"


def test_launch_context_duplicate_key_fails(tmp_path: Path) -> None:
    target = tmp_path / LAUNCH_CONTEXT_FILENAME
    target.write_text('{"schema_version":"x","schema_version":"x"}', encoding="utf-8")
    with pytest.raises(RuntimeContractError) as exc:
        read_launch_context(target)
    assert exc.value.code == "LAUNCH_CONTEXT_DUPLICATE_KEY"


def test_launch_context_unknown_field_fails(tmp_path: Path) -> None:
    target = tmp_path / LAUNCH_CONTEXT_FILENAME
    payload = _context().as_dict()
    payload["extra"] = True
    target.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    with pytest.raises(RuntimeContractError) as exc:
        read_launch_context(target)
    assert exc.value.code == "LAUNCH_CONTEXT_INVALID"


def test_launch_context_write_failure_cleans_owned_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / LAUNCH_CONTEXT_FILENAME

    def fail_replace(*_: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr("enterprise.runtime.launch_context.os.replace", fail_replace)
    with pytest.raises(RuntimeContractError) as exc:
        publish_launch_context(target, _context(), expected_existing_identity=None)
    assert exc.value.code == "LAUNCH_CONTEXT_WRITE_FAILED"
    assert not (tmp_path / "launch-context.json.new").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mode", "development"),
        ("release_id", "../evil"),
        ("app_root_relative", "C:/absolute"),
        ("python_implementation", "PyPy"),
        ("python_version", "garbage"),
        ("python_abi", "cp999"),
        ("architecture", "arm64"),
        ("bytecode_policy", "enabled"),
    ],
)
def test_r3_launch_context_reader_rejects_each_invalid_contract_field(
    tmp_path: Path, field: str, value: str
) -> None:
    target = tmp_path / LAUNCH_CONTEXT_FILENAME
    payload = _context().as_dict()
    payload[field] = value
    target.write_bytes(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    )
    with pytest.raises(RuntimeContractError) as exc:
        read_launch_context(target)
    assert exc.value.code == "LAUNCH_CONTEXT_INVALID"


def test_r3_launch_context_direct_construction_and_publish_revalidate_contract(tmp_path: Path) -> None:
    payload = _context().as_dict()
    payload["mode"] = "development"
    with pytest.raises(RuntimeContractError) as exc:
        RuntimeLaunchContext(**payload)  # type: ignore[arg-type]
    assert exc.value.code == "LAUNCH_CONTEXT_INVALID"


@pytest.mark.parametrize(
    "raw_suffix",
    [b"", b"\n\n", b" ", b"\n "],
)
def test_r3_launch_context_reader_requires_exact_canonical_bytes(tmp_path: Path, raw_suffix: bytes) -> None:
    target = tmp_path / LAUNCH_CONTEXT_FILENAME
    raw = _context().canonical_json()
    target.write_bytes(raw[:-1] + raw_suffix)
    with pytest.raises(RuntimeContractError) as exc:
        read_launch_context(target)
    assert exc.value.code == "LAUNCH_CONTEXT_INVALID"


def test_r3_publish_does_not_overwrite_foreign_target_created_before_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import enterprise.runtime.launch_context as subject

    target = tmp_path / LAUNCH_CONTEXT_FILENAME
    original_verify = subject._verify_target_state
    calls = 0

    def foreign_appears(destination: Path, expected: str | None) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            destination.write_bytes(_context("f" * 32).canonical_json())
        original_verify(destination, expected)

    monkeypatch.setattr(subject, "_verify_target_state", foreign_appears)
    with pytest.raises(RuntimeContractError) as exc:
        publish_launch_context(target, _context(), expected_existing_identity=None)
    assert exc.value.code == "LAUNCH_CONTEXT_EXISTING_FORBIDDEN"
    assert read_launch_context(target).instance_id == "f" * 32


def test_r4_temp_identity_reuse_does_not_publish_foreign_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import enterprise.runtime.launch_context as subject

    target = tmp_path / LAUNCH_CONTEXT_FILENAME
    temporary = tmp_path / "launch-context.json.new"
    original_verify = subject._verify_target_state
    calls = 0

    def replace_temp_after_target_verify(destination: Path, expected: str | None) -> None:
        nonlocal calls
        calls += 1
        original_verify(destination, expected)
        if calls == 2:
            temporary.unlink()
            temporary.write_bytes(b"foreign")

    monkeypatch.setattr(subject, "_verify_target_state", replace_temp_after_target_verify)
    monkeypatch.setattr(subject, "_file_identity", lambda path: (7, 7))
    with pytest.raises(RuntimeContractError) as exc:
        publish_launch_context(target, _context(), expected_existing_identity=None)
    assert exc.value.code == "LAUNCH_CONTEXT_TEMP_OWNERSHIP_LOST"
    assert temporary.read_bytes() == b"foreign"
    assert not target.exists()


@pytest.mark.parametrize("name", [LAUNCH_CONTEXT_FILENAME, "launch-context.json.new"])
def test_r4_broken_symlink_is_lexically_present_and_preserved(tmp_path: Path, name: str) -> None:
    target = tmp_path / LAUNCH_CONTEXT_FILENAME
    link = tmp_path / name
    try:
        link.symlink_to(tmp_path / "missing")
    except OSError:
        # Keep the policy covered when this Windows fixture cannot create a
        # real symlink: lstat success is lexical existence even when normal
        # path resolution would fail for a broken link.
        import enterprise.runtime.launch_context as subject

        original_lstat = subject.os.lstat

        def synthetic_lstat(path: object):
            if Path(path) == link:
                return original_lstat(tmp_path)
            return original_lstat(path)

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(subject.os, "lstat", synthetic_lstat)
        try:
            with pytest.raises(RuntimeContractError):
                publish_launch_context(target, _context(), expected_existing_identity=None)
        finally:
            monkeypatch.undo()
        assert not link.exists()
        return
    with pytest.raises(RuntimeContractError):
        publish_launch_context(target, _context(), expected_existing_identity=None)
    assert link.is_symlink()


@pytest.mark.parametrize("release_id", ["CON", "NUL", "COM1", "LPT9.txt", "release.", "release ", ".", "..", "a/b", "a\\b", "a:b"])
def test_r5_launch_context_reuses_windows_safe_release_component(tmp_path: Path, release_id: str) -> None:
    payload = _context().as_dict()
    payload["release_id"] = release_id
    payload["app_root_relative"] = f"releases/{release_id}"
    with pytest.raises(RuntimeContractError) as exc:
        RuntimeLaunchContext(**payload)  # type: ignore[arg-type]
    assert exc.value.code == "LAUNCH_CONTEXT_INVALID"


def test_r6_launch_context_ownership_read_is_bounded_and_preserves_large_foreign_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import enterprise.runtime.launch_context as subject
    target = tmp_path / LAUNCH_CONTEXT_FILENAME
    temporary = tmp_path / "launch-context.json.new"
    original_verify = subject._verify_target_state
    original_read = subject.os.read
    calls = 0
    read_sizes: list[int] = []

    def replace_temp_after_target_verify(destination: Path, expected: str | None) -> None:
        nonlocal calls
        calls += 1
        original_verify(destination, expected)
        if calls == 2:
            temporary.unlink(); temporary.write_bytes(b"foreign" * 4096)

    def bounded_read(fd: int, size: int) -> bytes:
        read_sizes.append(size)
        return original_read(fd, size)

    monkeypatch.setattr(subject, "_verify_target_state", replace_temp_after_target_verify)
    monkeypatch.setattr(subject, "_file_identity", lambda _path: (7, 7))
    monkeypatch.setattr(subject.os, "read", bounded_read)
    context = _context()
    with pytest.raises(RuntimeContractError) as exc:
        publish_launch_context(target, context, expected_existing_identity=None)
    assert exc.value.code == "LAUNCH_CONTEXT_TEMP_OWNERSHIP_LOST"
    assert read_sizes and max(read_sizes) <= len(context.canonical_json()) + 1
    assert temporary.read_bytes().startswith(b"foreign")
