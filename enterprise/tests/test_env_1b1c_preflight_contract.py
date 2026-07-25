"""ENV-1B1C-B1 startup preflight result contract tests."""

from __future__ import annotations

import json

import pytest

from enterprise.runtime.error_contract import RuntimeContractError
from enterprise.runtime.preflight import build_startup_preflight_result


SHA = "a" * 64


def test_startup_preflight_result_is_immutable_and_canonical() -> None:
    result = build_startup_preflight_result(
        mode_value="portable-release",
        release_id="release-A",
        path_roots_identity=SHA,
        current_release_sha256="b" * 64,
        runtime_manifest_sha256="c" * 64,
        python_executable_sha256="d" * 64,
        python_version="3.10.11",
    )
    assert result.identity == result.identity
    decoded = json.loads(result.canonical_json().decode("utf-8"))
    assert decoded["schema_version"] == "env-1b1c-startup-preflight-v1"
    assert decoded["app_root_relative"] == "releases/release-A"
    assert set(decoded["writable_roots_verified"]) == {"DATA_ROOT", "LOG_ROOT", "RUNTIME_ROOT", "CACHE_ROOT", "TEMP_ROOT"}


def test_preflight_does_not_accept_development_mode() -> None:
    with pytest.raises(RuntimeContractError) as exc:
        build_startup_preflight_result(
            mode_value="development",
            release_id="release-A",
            path_roots_identity=SHA,
            current_release_sha256=SHA,
            runtime_manifest_sha256=SHA,
            python_executable_sha256=SHA,
            python_version="3.10.11",
        )
    assert exc.value.code == "STARTUP_PREFLIGHT_INVALID"


def test_preflight_rejects_bad_hash() -> None:
    with pytest.raises(RuntimeContractError):
        build_startup_preflight_result(
            mode_value="portable-release",
            release_id="release-A",
            path_roots_identity="not-sha",
            current_release_sha256=SHA,
            runtime_manifest_sha256=SHA,
            python_executable_sha256=SHA,
            python_version="3.10.11",
        )
