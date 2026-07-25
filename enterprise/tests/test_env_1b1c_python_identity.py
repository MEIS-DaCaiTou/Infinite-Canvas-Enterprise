"""ENV-1B1C-B1 Python identity normalization tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from enterprise.runtime.error_contract import RuntimeContractError
from enterprise.runtime.python_identity import _hash_file, build_python_identity


def _probe(executable: Path, **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "architecture": "64bit",
        "base_prefix": str(executable.parent),
        "cache_tag": "cpython-310",
        "dont_write_bytecode": True,
        "implementation": "cpython",
        "machine": "AMD64",
        "no_user_site": True,
        "pointer_bits": 64,
        "executable": str(executable),
        "prefix": str(executable.parent),
        "version": "3.10.11",
    }
    data.update(overrides)
    return data


def test_python_identity_is_redacted_and_bound_to_python_exe(tmp_path: Path) -> None:
    exe = tmp_path / "python.exe"
    exe.write_bytes(b"fake executable")
    identity = build_python_identity(exe, _probe(exe), expected_executable=exe, expected_runtime_root=exe.parent)
    snapshot = identity.public_snapshot()
    assert snapshot["implementation"] == "CPython"
    assert snapshot["abi"] == "cp310"
    assert snapshot["architecture"] == "x64"
    assert snapshot["executable_basename"] == "python.exe"
    assert str(tmp_path) not in str(snapshot)


def test_pythonw_is_rejected(tmp_path: Path) -> None:
    exe = tmp_path / "pythonw.exe"
    exe.write_bytes(b"fake")
    with pytest.raises(RuntimeContractError) as exc:
        build_python_identity(exe, _probe(exe), expected_executable=exe, expected_runtime_root=exe.parent)
    assert exc.value.code == "PYTHON_IDENTITY_EXECUTABLE_INVALID"


def test_executable_mismatch_fails_closed(tmp_path: Path) -> None:
    exe = tmp_path / "python.exe"
    other = tmp_path / "other" / "python.exe"
    other.parent.mkdir()
    exe.write_bytes(b"fake")
    other.write_bytes(b"fake")
    with pytest.raises(RuntimeContractError) as exc:
        build_python_identity(exe, _probe(exe), expected_executable=other, expected_runtime_root=other.parent)
    assert exc.value.code == "PYTHON_IDENTITY_EXECUTABLE_MISMATCH"


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"implementation": "pypy"}, "PYTHON_IDENTITY_IMPLEMENTATION_INVALID"),
        ({"version": "3.11.0"}, "PYTHON_IDENTITY_VERSION_INVALID"),
        ({"version": "3.10.not-a-patch"}, "PYTHON_IDENTITY_VERSION_INVALID"),
        ({"cache_tag": "cpython-311"}, "PYTHON_IDENTITY_ABI_INVALID"),
        ({"pointer_bits": 32}, "PYTHON_IDENTITY_ARCHITECTURE_INVALID"),
        ({"dont_write_bytecode": False}, "PYTHON_IDENTITY_BYTECODE_POLICY_INVALID"),
        ({"no_user_site": False}, "PYTHON_IDENTITY_BYTECODE_POLICY_INVALID"),
    ],
)
def test_python_identity_negative_probe_fields(tmp_path: Path, override: dict[str, object], code: str) -> None:
    exe = tmp_path / "python.exe"
    exe.write_bytes(b"fake")
    with pytest.raises(RuntimeContractError) as exc:
        build_python_identity(exe, _probe(exe, **override), expected_executable=exe, expected_runtime_root=exe.parent)
    assert exc.value.code == code


def test_arm64_identity_parses_but_is_not_supported(tmp_path: Path) -> None:
    exe = tmp_path / "python.exe"
    exe.write_bytes(b"fake")
    identity = build_python_identity(exe, _probe(exe, machine="arm64"), expected_executable=exe, expected_runtime_root=exe.parent)
    assert identity.architecture == "arm64"
    assert identity.architecture_supported is False


def test_r3_prefix_identity_binds_the_runtime_root_not_only_basename(tmp_path: Path) -> None:
    first = tmp_path / "first" / "runtime"
    second = tmp_path / "second" / "runtime"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    first_exe = first / "python.exe"
    second_exe = second / "python.exe"
    first_exe.write_bytes(b"same")
    second_exe.write_bytes(b"same")
    first_identity = build_python_identity(first_exe, _probe(first_exe), expected_executable=first_exe, expected_runtime_root=first)
    second_identity = build_python_identity(second_exe, _probe(second_exe), expected_executable=second_exe, expected_runtime_root=second)
    assert first_identity.prefix_identity != second_identity.prefix_identity
    assert first_identity.base_prefix_identity != second_identity.base_prefix_identity


def test_r3_prefix_escape_from_expected_runtime_is_rejected(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    exe = runtime / "python.exe"
    exe.write_bytes(b"fake")
    with pytest.raises(RuntimeContractError) as exc:
        build_python_identity(exe, _probe(exe, prefix=str(tmp_path), base_prefix=str(tmp_path)), expected_executable=exe, expected_runtime_root=runtime)
    assert exc.value.code == "PYTHON_IDENTITY_PREFIX_MISMATCH"


@pytest.mark.parametrize("kind", ["subdir", "file"])
def test_r4_prefix_and_base_prefix_must_equal_runtime_root(tmp_path: Path, kind: str) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    exe = runtime / "python.exe"
    exe.write_bytes(b"fake")
    candidate = runtime / kind
    if kind == "subdir":
        candidate.mkdir()
    else:
        candidate.write_bytes(b"not a directory")
    with pytest.raises(RuntimeContractError) as exc:
        build_python_identity(exe, _probe(exe, prefix=str(candidate), base_prefix=str(candidate)), expected_executable=exe, expected_runtime_root=runtime)
    assert exc.value.code == "PYTHON_IDENTITY_PREFIX_MISMATCH"


def test_r5_portable_identity_requires_explicit_expected_roots(tmp_path: Path) -> None:
    exe = tmp_path / "python.exe"
    exe.write_bytes(b"fake")
    with pytest.raises(RuntimeContractError) as exc:
        build_python_identity(exe, _probe(exe))
    assert exc.value.code == "PYTHON_IDENTITY_EXECUTABLE_MISMATCH"


@pytest.mark.parametrize("soabi", [None, "cpython-310-win_amd64"])
def test_r5_portable_identity_allows_absent_or_exact_soabi(tmp_path: Path, soabi: str | None) -> None:
    runtime = tmp_path / "runtime"; runtime.mkdir()
    exe = runtime / "python.exe"; exe.write_bytes(b"fake")
    identity = build_python_identity(exe, _probe(exe, soabi=soabi), expected_executable=exe, expected_runtime_root=runtime)
    assert identity.abi == "cp310"


def test_r5_portable_identity_rejects_incompatible_soabi(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"; runtime.mkdir()
    exe = runtime / "python.exe"; exe.write_bytes(b"fake")
    with pytest.raises(RuntimeContractError) as exc:
        build_python_identity(exe, _probe(exe, soabi="cp999-win_amd64"), expected_executable=exe, expected_runtime_root=runtime)
    assert exc.value.code == "PYTHON_IDENTITY_ABI_INVALID"


@pytest.mark.parametrize("stage", ["open", "read", "close"])
def test_r5_executable_hash_os_errors_are_mapped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str) -> None:
    target = tmp_path / "python.exe"; target.write_bytes(b"core")
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
        _hash_file(target)
    assert exc.value.code == "PYTHON_IDENTITY_EXECUTABLE_READ_FAILED"
    assert "host detail" not in exc.value.payload.canonical_json().decode("utf-8")
