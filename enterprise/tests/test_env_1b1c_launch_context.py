"""ENV-1B1C-B1 launch context primitive tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from enterprise.runtime.error_contract import RuntimeContractError
from enterprise.runtime.launch_context import (
    LAUNCH_CONTEXT_FILENAME,
    build_launch_context,
    publish_launch_context,
    read_launch_context,
)
from enterprise.runtime.preflight import build_startup_preflight_result


SHA = "a" * 64


def _context(instance_id: str = "1" * 32):
    preflight = build_startup_preflight_result(
        mode_value="portable-release",
        release_id="release-A",
        path_roots_identity=SHA,
        current_release_sha256="b" * 64,
        runtime_manifest_sha256="c" * 64,
        python_executable_sha256="d" * 64,
        python_version="3.10.11",
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
