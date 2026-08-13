"""Focused Gate A tests for the first real upgradeable Release."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from enterprise.release.release_mvp_preflight import (
    ReleaseMvpPreflightError,
    _assert_no_leak,
    validate_asset_set,
    validate_database_contract,
    validate_versions,
)


class _Manifest:
    def __init__(self, version: str, *, archive: str = "release.zip", database: dict[str, object] | None = None):
        self._sections = {
            "identity": {"release_version": version},
            "archive": {"filename": archive},
            "database_contract": database or _database_contract(),
        }

    def section(self, name: str) -> dict[str, object]:
        return self._sections[name]


def _database_contract(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_id": "enterprise-database-contract-v1",
        "schema_snapshot_sha256": "a" * 64,
        "migration_ids": ["m1"],
        "migration_compatibility": "same-schema-no-migration",
        "rollback_classification": "code-release-pointer",
        "ops3b_activation_eligible": True,
    }
    value.update(updates)
    return value


@pytest.mark.parametrize(
    ("source", "target", "tag", "code"),
    [
        ("2026.07.6", "2026.07.6", "2026.07.6", "RELEASE_MVP_VERSION_NOT_NEWER"),
        ("2026.07.6", "2026.08.1", "2026.08.2", "RELEASE_MVP_TAG_VERSION_MISMATCH"),
        ("2026.07.6", "v2026.08.1", "v2026.08.1", "RELEASE_MVP_VERSION_INVALID"),
    ],
)
def test_version_gate_is_strict(source: str, target: str, tag: str, code: str) -> None:
    with pytest.raises(ReleaseMvpPreflightError, match=code):
        validate_versions(_Manifest("2026.07.6"), _Manifest("2026.08.1"), source_version=source, target_version=target, target_tag=tag)


def test_version_gate_accepts_exact_newer_manifest_and_tag() -> None:
    validate_versions(
        _Manifest("2026.07.6"),
        _Manifest("2026.08.1"),
        source_version="2026.07.6",
        target_version="2026.08.1",
        target_tag="2026.08.1",
    )


def test_asset_set_requires_exact_three_files(tmp_path: Path) -> None:
    manifest = tmp_path / "ops-release-manifest-v2.json"
    inventory = tmp_path / "release-payload-inventory.json"
    archive = tmp_path / "release.zip"
    for path in (manifest, inventory, archive):
        path.write_bytes(b"x")
    validate_asset_set(manifest, inventory, archive, _Manifest("2026.08.1"))
    (tmp_path / "unexpected.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ReleaseMvpPreflightError, match="RELEASE_MVP_ASSET_SET_INVALID"):
        validate_asset_set(manifest, inventory, archive, _Manifest("2026.08.1"))


@pytest.mark.parametrize(
    "updates",
    [
        {"schema_id": "other"},
        {"schema_snapshot_sha256": "b" * 64},
        {"migration_ids": ["m2"]},
        {"migration_compatibility": "migration-required"},
        {"rollback_classification": "database-restore"},
        {"ops3b_activation_eligible": False},
    ],
)
def test_database_gate_rejects_any_contract_drift(updates: dict[str, object]) -> None:
    source = _Manifest("2026.07.6")
    target = _Manifest("2026.08.1", database=_database_contract(**updates))
    with pytest.raises(ReleaseMvpPreflightError, match="RELEASE_MVP_DATABASE_CONTRACT_UNSUPPORTED"):
        validate_database_contract(source, target)


def test_database_gate_accepts_same_schema_no_migration() -> None:
    validate_database_contract(_Manifest("2026.07.6"), _Manifest("2026.08.1"))


@pytest.mark.parametrize(
    "leak",
    [
        b"Authorization: Bearer secret-token-value",
        b"token=secret-token-value",
        b"GITHUB_TOKEN",
        b"D:\\CodeProject\\private\\artifact",
        b"review-artifacts/build-A",
    ],
)
def test_metadata_leak_scan_fails_closed(leak: bytes) -> None:
    with pytest.raises(ReleaseMvpPreflightError, match="RELEASE_MVP_SECRET_OR_LOCAL_PATH_LEAKAGE"):
        _assert_no_leak([leak])


def test_cli_failure_is_one_line_json_without_traceback(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "tools/release_mvp_preflight.py",
            "--source-manifest", "relative-source.json",
            "--manifest", "relative-manifest.json",
            "--inventory", "relative-inventory.json",
            "--archive", "relative.zip",
            "--source-version", "2026.07.6",
            "--target-version", "2026.08.1",
            "--target-tag", "2026.08.1",
        ],
        cwd=Path(__file__).parents[2],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 2
    assert completed.stderr == ""
    assert len(completed.stdout.splitlines()) == 1
    payload = json.loads(completed.stdout)
    assert payload == {
        "code": "RELEASE_MVP_INPUT_INVALID",
        "ready": False,
        "ready_for_github_release": False,
        "schema_version": "release-mvp-1-gate-a-preflight-v1",
        "status": "blocked",
    }
    assert "Traceback" not in completed.stdout


def test_cli_argument_error_is_json() -> None:
    completed = subprocess.run(
        [sys.executable, "tools/release_mvp_preflight.py"],
        cwd=Path(__file__).parents[2],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 2
    assert completed.stderr == ""
    assert json.loads(completed.stdout)["code"] == "RELEASE_MVP_ARGUMENT_INVALID"
