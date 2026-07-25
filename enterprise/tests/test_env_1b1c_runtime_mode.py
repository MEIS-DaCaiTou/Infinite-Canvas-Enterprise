"""ENV-1B1C-B1 runtime mode and stable error contract tests."""

from __future__ import annotations

import json

import pytest

from enterprise.runtime.error_contract import ERROR_REGISTRY, RuntimeContractError, error_payload
from enterprise.runtime.mode import DEVELOPMENT, PORTABLE_RELEASE, parse_runtime_mode


def test_runtime_mode_portable_is_fail_closed() -> None:
    mode = parse_runtime_mode(PORTABLE_RELEASE)
    assert mode.mode == PORTABLE_RELEASE
    assert mode.allow_system_python is False
    assert mode.allows_path_fallback is False
    assert mode.release_validation_eligible is True
    assert mode.development_only is False


def test_runtime_mode_development_is_not_release_evidence() -> None:
    mode = parse_runtime_mode(DEVELOPMENT)
    assert mode.allow_system_python is True
    assert mode.allows_path_fallback is True
    assert mode.release_validation_eligible is False
    assert mode.development_only is True


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (None, "RUNTIME_MODE_REQUIRED"),
        ("", "RUNTIME_MODE_REQUIRED"),
        ("Portable-Release", "RUNTIME_MODE_INVALID"),
        ("portable-release ", "RUNTIME_MODE_INVALID"),
        ("unknown", "RUNTIME_MODE_INVALID"),
        ("server", "RUNTIME_MODE_NOT_IMPLEMENTED"),
    ],
)
def test_runtime_mode_failures_are_stable(value: object, code: str) -> None:
    with pytest.raises(RuntimeContractError) as exc:
        parse_runtime_mode(value)
    assert exc.value.code == code


def test_error_payload_is_canonical_and_redacted() -> None:
    payload = error_payload("PORTABLE_RELEASE_NOT_CURRENT", details={"label": "APP_ROOT"})
    decoded = json.loads(payload.canonical_json().decode("utf-8"))
    assert decoded["schema_version"] == "env-1b1c-runtime-error-v1"
    assert decoded["exit_code"] == 2
    assert decoded["details"] == {"label": "APP_ROOT"}
    assert "D:\\" not in payload.canonical_json().decode("utf-8")


def test_unknown_error_code_is_rejected() -> None:
    assert "RUNTIME_MODE_REQUIRED" in ERROR_REGISTRY
    with pytest.raises(ValueError):
        error_payload("NOT_A_REAL_CODE")


def test_error_details_reject_host_paths() -> None:
    with pytest.raises(RuntimeContractError):
        error_payload("RUNTIME_MODE_INVALID", details={"label": "C:" + "\\redacted"})


def test_r3_error_payload_details_are_immutable_and_not_leaked() -> None:
    payload = error_payload("RUNTIME_MODE_INVALID", details={"labels": ["DATA_ROOT"]})
    with pytest.raises((AttributeError, TypeError)):
        payload.details["labels"] = "changed"  # type: ignore[index]
    public = payload.as_public_dict()
    public["details"]["labels"].append("LOG_ROOT")
    assert json.loads(payload.canonical_json())["details"] == {"labels": ["DATA_ROOT"]}


@pytest.mark.parametrize("correlation_id", ["bad\nvalue", r"C:\secret", "x" * 65])
def test_r3_error_payload_rejects_unsafe_correlation_id(correlation_id: str) -> None:
    with pytest.raises(ValueError):
        error_payload("RUNTIME_MODE_INVALID", correlation_id=correlation_id)


@pytest.mark.parametrize("value", ["/home/alice/token", r"\Users\alice\secret", "../secret", "a/b", r"a\b"])
def test_r5_error_details_reject_pathlike_values_recursively(value: str) -> None:
    with pytest.raises(RuntimeContractError):
        error_payload("RUNTIME_MODE_INVALID", details={"label": ("APP_ROOT", [value])})


@pytest.mark.parametrize("value", ["APP_ROOT", "python.exe", "runtime_manifest"])
def test_r5_error_details_allow_symbolic_labels(value: str) -> None:
    assert error_payload("RUNTIME_MODE_INVALID", details={"label": value}).as_public_dict()["details"] == {"label": value}
