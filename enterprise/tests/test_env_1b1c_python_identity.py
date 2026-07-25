"""ENV-1B1C-B1 Python identity normalization tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from enterprise.runtime.error_contract import RuntimeContractError
from enterprise.runtime.python_identity import build_python_identity


def _probe(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "architecture": "64bit",
        "base_prefix": "python-runtime",
        "cache_tag": "cpython-310",
        "dont_write_bytecode": True,
        "implementation": "cpython",
        "machine": "AMD64",
        "no_user_site": True,
        "pointer_bits": 64,
        "prefix": "python-runtime",
        "version": "3.10.11",
    }
    data.update(overrides)
    return data


def test_python_identity_is_redacted_and_bound_to_python_exe(tmp_path: Path) -> None:
    exe = tmp_path / "python.exe"
    exe.write_bytes(b"fake executable")
    identity = build_python_identity(exe, _probe(), expected_executable=exe)
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
        build_python_identity(exe, _probe())
    assert exc.value.code == "PYTHON_IDENTITY_EXECUTABLE_INVALID"


def test_executable_mismatch_fails_closed(tmp_path: Path) -> None:
    exe = tmp_path / "python.exe"
    other = tmp_path / "other" / "python.exe"
    other.parent.mkdir()
    exe.write_bytes(b"fake")
    other.write_bytes(b"fake")
    with pytest.raises(RuntimeContractError) as exc:
        build_python_identity(exe, _probe(), expected_executable=other)
    assert exc.value.code == "PYTHON_IDENTITY_EXECUTABLE_MISMATCH"


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"implementation": "pypy"}, "PYTHON_IDENTITY_IMPLEMENTATION_INVALID"),
        ({"version": "3.11.0"}, "PYTHON_IDENTITY_VERSION_INVALID"),
        ({"cache_tag": "cpython-311"}, "RUNTIME_MANIFEST_ABI_INVALID"),
        ({"pointer_bits": 32}, "PYTHON_IDENTITY_ARCHITECTURE_INVALID"),
        ({"dont_write_bytecode": False}, "PYTHON_IDENTITY_BYTECODE_POLICY_INVALID"),
        ({"no_user_site": False}, "PYTHON_IDENTITY_BYTECODE_POLICY_INVALID"),
    ],
)
def test_python_identity_negative_probe_fields(tmp_path: Path, override: dict[str, object], code: str) -> None:
    exe = tmp_path / "python.exe"
    exe.write_bytes(b"fake")
    with pytest.raises(RuntimeContractError) as exc:
        build_python_identity(exe, _probe(**override))
    assert exc.value.code == code


def test_arm64_identity_parses_but_is_not_supported(tmp_path: Path) -> None:
    exe = tmp_path / "python.exe"
    exe.write_bytes(b"fake")
    identity = build_python_identity(exe, _probe(machine="arm64"))
    assert identity.architecture == "arm64"
    assert identity.architecture_supported is False
