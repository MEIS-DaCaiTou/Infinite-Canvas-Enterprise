"""ENV-1B1C-B1 startup preflight result contract tests."""

from __future__ import annotations

import hashlib
import json

import pytest

from enterprise.runtime.error_contract import RuntimeContractError
from enterprise.runtime.mode import parse_runtime_mode
from enterprise.runtime.preflight import StartupPreflightResult, build_startup_preflight_result, decide_release_mismatch
from enterprise.runtime.python_identity import PythonIdentity
from enterprise.runtime.runtime_manifest import STARTUP_CORE_FILES, RuntimeManifestStartupView, StartupCoreFile
from enterprise.runtime.writable_probe import WritableProbeResult
from enterprise.tests.release_manifest_v2_fixture import preflight_v2_fields, release_manifest


SHA = "a" * 64


def _manifest(**overrides: object) -> RuntimeManifestStartupView:
    records = tuple(StartupCoreFile(name, "e" * 64, 1) for name in STARTUP_CORE_FILES)
    digest = hashlib.sha256()
    for record in records:
        encoded = record.relative_path.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(record.size_bytes.to_bytes(8, "big"))
        digest.update(bytes.fromhex(record.sha256))
    values: dict[str, object] = {
        "schema_version": "env-1b1c-runtime-manifest-startup-view-v1",
        "manifest_sha256": "c" * 64,
        "python_version": "3.14.6",
        "python_implementation": "CPython",
        "python_abi": "cp314",
        "architecture": "x64",
        "architecture_supported": True,
        "startup_core_files": records,
        "startup_core_digest": digest.hexdigest(),
        "candidate_id": None,
        "manifest_self_declared_enterprise_commit": None,
    }
    values.update(overrides)
    return RuntimeManifestStartupView(**values)  # type: ignore[arg-type]


def _identity(**overrides: object) -> PythonIdentity:
    values: dict[str, object] = {
        "implementation": "CPython",
        "version": "3.14.6",
        "abi": "cp314",
        "architecture": "x64",
        "architecture_supported": True,
        "pointer_bits": 64,
        "executable_basename": "python.exe",
        "executable_sha256": "e" * 64,
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
        "release_manifest": release_manifest(runtime_manifest_sha256="c" * 64),
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
    assert decoded["schema_version"] == "env-1b1c-startup-preflight-v2"
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
        ({"runtime_manifest": _manifest(python_version="3.13.12")}, "STARTUP_PREFLIGHT_INVALID"),
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


@pytest.mark.parametrize("warning", ["RUNTIME_MODE_INVALID", "PYTHON_IDENTITY_EXECUTABLE_MISSING"])
def test_r4_preflight_rejects_error_codes_as_warnings(warning: str) -> None:
    with pytest.raises(RuntimeContractError) as exc:
        _build(warnings=(warning,))
    assert exc.value.code == "STARTUP_PREFLIGHT_INVALID"


@pytest.mark.parametrize(
    "override",
    [
        {"mode": __import__("enterprise.runtime.mode", fromlist=["RuntimeMode"]).RuntimeMode("portable-release", True, False, True, False)},
        {"runtime_manifest": _manifest(schema_version="wrong")},
        {"python_identity": _identity(schema_version="wrong")},
        {"writable_probe_results": tuple(WritableProbeResult(label, True, True, schema_version="wrong") for label in ("DATA_ROOT", "LOG_ROOT", "RUNTIME_ROOT", "CACHE_ROOT", "TEMP_ROOT"))},
    ],
)
def test_r4_preflight_rejects_forged_typed_models(override: dict[str, object]) -> None:
    with pytest.raises(RuntimeContractError) as exc:
        _build(**override)
    assert exc.value.code == "STARTUP_PREFLIGHT_INVALID"


def test_r5_preflight_binds_python_executable_to_manifest_record() -> None:
    with pytest.raises(RuntimeContractError) as exc:
        _build(python_identity=_identity(executable_sha256="d" * 64))
    assert exc.value.code == "STARTUP_PREFLIGHT_PYTHON_MANIFEST_MISMATCH"
    assert _build().result == "pass"


@pytest.mark.parametrize("patch", ["00001", "01", "1000"])
def test_r5_preflight_rejects_noncanonical_python_patch_version(patch: str) -> None:
    with pytest.raises(RuntimeContractError) as exc:
        StartupPreflightResult(
            result="pass", mode="portable-release", release_id="release-A",
            app_root_relative="releases/release-A", path_roots_identity=SHA,
            current_release_sha256="b" * 64, runtime_manifest_sha256="c" * 64,
            **preflight_v2_fields(),
            python_executable_sha256="d" * 64, python_implementation="CPython",
            python_version=f"3.14.{patch}", python_abi="cp314", architecture="x64",
            bytecode_policy="disabled-no-user-site",
            writable_roots_verified=("DATA_ROOT", "LOG_ROOT", "RUNTIME_ROOT", "CACHE_ROOT", "TEMP_ROOT"),
        )
    assert exc.value.code == "STARTUP_PREFLIGHT_INVALID"


def test_r5_release_gate_is_not_final_health_readiness() -> None:
    decision = decide_release_mismatch(
        launcher_release_id="release-A", current_release_id="release-A",
        running_release_id=None, owned_instance_valid=False, command="health",
    )
    assert decision.allowed is True and decision.status_code == "RELEASE_MATCH"
    assert decision.decision_scope == "release_gate_only"


def test_r6_preflight_schema_is_an_invariant() -> None:
    with pytest.raises(RuntimeContractError) as exc:
        StartupPreflightResult(
            result="pass", mode="portable-release", release_id="release-A",
            app_root_relative="releases/release-A", path_roots_identity=SHA,
            current_release_sha256="b" * 64, runtime_manifest_sha256="c" * 64,
            **preflight_v2_fields(),
            python_executable_sha256="d" * 64, python_implementation="CPython",
            python_version="3.14.6", python_abi="cp314", architecture="x64",
            bytecode_policy="disabled-no-user-site",
            writable_roots_verified=("DATA_ROOT", "LOG_ROOT", "RUNTIME_ROOT", "CACHE_ROOT", "TEMP_ROOT"),
            schema_version="WRONG",
        )
    assert exc.value.code == "STARTUP_PREFLIGHT_INVALID"


@pytest.mark.parametrize("release_id", ["CON", "NUL", "COM1", "LPT9.txt", "release.", "release ", ".", "..", "a/b", "a\\b", "a:b"])
def test_r5_preflight_reuses_windows_safe_release_component(release_id: str) -> None:
    with pytest.raises(RuntimeContractError) as exc:
        _build(release_id=release_id)
    assert exc.value.code == "STARTUP_PREFLIGHT_INVALID"
