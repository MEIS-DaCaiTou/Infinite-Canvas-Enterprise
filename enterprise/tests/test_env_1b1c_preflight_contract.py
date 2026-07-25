"""ENV-1B1C-B1 startup preflight result contract tests."""

from __future__ import annotations

import json

import pytest

from enterprise.runtime.error_contract import RuntimeContractError
from enterprise.runtime.mode import parse_runtime_mode
from enterprise.runtime.preflight import build_startup_preflight_result
from enterprise.runtime.python_identity import PythonIdentity
from enterprise.runtime.runtime_manifest import RuntimeManifestStartupView
from enterprise.runtime.writable_probe import WritableProbeResult


SHA = "a" * 64


def _manifest(**overrides: object) -> RuntimeManifestStartupView:
    values: dict[str, object] = {
        "schema_version": "env-1b1c-runtime-manifest-startup-view-v1",
        "manifest_sha256": "c" * 64,
        "python_version": "3.10.11",
        "python_implementation": "CPython",
        "python_abi": "cp310",
        "architecture": "x64",
        "architecture_supported": True,
        "startup_core_files": (),
        "startup_core_digest": "e" * 64,
        "candidate_id": None,
        "manifest_self_declared_enterprise_commit": None,
    }
    values.update(overrides)
    return RuntimeManifestStartupView(**values)  # type: ignore[arg-type]


def _identity(**overrides: object) -> PythonIdentity:
    values: dict[str, object] = {
        "implementation": "CPython",
        "version": "3.10.11",
        "abi": "cp310",
        "architecture": "x64",
        "architecture_supported": True,
        "pointer_bits": 64,
        "executable_basename": "python.exe",
        "executable_sha256": "d" * 64,
        "prefix_identity": "f" * 64,
        "base_prefix_identity": "f" * 64,
        "dont_write_bytecode": True,
        "no_user_site": True,
    }
    values.update(overrides)
    return PythonIdentity(**values)  # type: ignore[arg-type]


def _probes(labels: tuple[str, ...] = ("DATA_ROOT", "LOG_ROOT", "RUNTIME_ROOT", "CACHE_ROOT", "TEMP_ROOT")) -> tuple[WritableProbeResult, ...]:
    return tuple(WritableProbeResult(label, created=True, cleaned_up=True) for label in labels)


def _build(**overrides: object):
    values: dict[str, object] = {
        "mode": parse_runtime_mode("portable-release"),
        "release_id": "release-A",
        "path_roots_identity": SHA,
        "current_release_sha256": "b" * 64,
        "runtime_manifest": _manifest(),
        "python_identity": _identity(),
        "writable_probe_results": _probes(),
        "warnings": (),
    }
    values.update(overrides)
    return build_startup_preflight_result(**values)  # type: ignore[arg-type]


def test_startup_preflight_result_is_immutable_and_canonical() -> None:
    result = _build()
    assert result.identity == result.identity
    decoded = json.loads(result.canonical_json().decode("utf-8"))
    assert decoded["schema_version"] == "env-1b1c-startup-preflight-v1"
    assert decoded["app_root_relative"] == "releases/release-A"
    assert set(decoded["writable_roots_verified"]) == {"DATA_ROOT", "LOG_ROOT", "RUNTIME_ROOT", "CACHE_ROOT", "TEMP_ROOT"}


def test_preflight_does_not_accept_development_mode() -> None:
    with pytest.raises(RuntimeContractError) as exc:
        _build(mode=parse_runtime_mode("development"))
    assert exc.value.code == "STARTUP_PREFLIGHT_INVALID"


def test_preflight_rejects_bad_hash() -> None:
    with pytest.raises(RuntimeContractError):
        _build(path_roots_identity="not-sha")


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"runtime_manifest": _manifest(python_version="3.10.12")}, "STARTUP_PREFLIGHT_INVALID"),
        ({"runtime_manifest": _manifest(python_abi="cp311")}, "STARTUP_PREFLIGHT_INVALID"),
        ({"runtime_manifest": _manifest(architecture="arm64", architecture_supported=False), "python_identity": _identity(architecture="arm64", architecture_supported=False)}, "PORTABLE_ARCHITECTURE_UNSUPPORTED"),
        ({"python_identity": _identity(version="arbitrary")}, "STARTUP_PREFLIGHT_INVALID"),
        ({"writable_probe_results": _probes(("DATA_ROOT", "DATA_ROOT", "RUNTIME_ROOT", "CACHE_ROOT", "TEMP_ROOT"))}, "STARTUP_PREFLIGHT_INVALID"),
        ({"writable_probe_results": _probes(("LOG_ROOT", "DATA_ROOT", "RUNTIME_ROOT", "CACHE_ROOT", "TEMP_ROOT"))}, "STARTUP_PREFLIGHT_INVALID"),
        ({"warnings": ("unknown-warning",)}, "STARTUP_PREFLIGHT_INVALID"),
        ({"warnings": ("READINESS_RELEASE_MISMATCH\npath",)}, "STARTUP_PREFLIGHT_INVALID"),
    ],
)
def test_r3_preflight_cross_binds_verified_inputs(override: dict[str, object], code: str) -> None:
    with pytest.raises(RuntimeContractError) as exc:
        _build(**override)
    assert exc.value.code == code


def test_r3_preflight_rejects_legacy_raw_string_arguments() -> None:
    with pytest.raises(RuntimeContractError) as exc:
        _build(mode="portable-release")
    assert exc.value.code == "STARTUP_PREFLIGHT_INVALID"
