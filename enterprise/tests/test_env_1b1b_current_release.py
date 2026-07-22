from __future__ import annotations

from pathlib import Path

import pytest

from enterprise.paths import (
    PortableRootInputs,
    derive_portable_path_roots,
    derive_portable_root_layout,
    prepare_install_state_directories,
)
from enterprise.release.current_release import (
    CurrentRelease,
    CurrentReleaseError,
    atomic_write_current_release,
    canonical_json,
    read_current_release,
    resolve_current_app_root,
    resolve_portable_path_roots,
)


def roots(tmp_path: Path):
    value = derive_portable_path_roots(PortableRootInputs(tmp_path / "install", tmp_path / "local"), "release-A")
    prepare_install_state_directories(value)
    value.APP_ROOT.mkdir(parents=True)
    return value


def release() -> CurrentRelease:
    return CurrentRelease(
        "env-1b1b-current-release-v1", "release-A", "releases/release-A",
        "a" * 64, "2026-07-22T12:00:00Z", None,
    )


def test_round_trip_is_canonical_and_resolves_app_root(tmp_path: Path):
    value = roots(tmp_path)
    atomic_write_current_release(value, release())
    raw = (value.STATE_ROOT / "current-release.json").read_bytes()
    assert raw == canonical_json(release()) and raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    assert read_current_release(value) == release()
    assert resolve_current_app_root(value) == value.APP_ROOT


def test_two_stage_portable_resolution_reads_only_state_before_deriving_app_root(tmp_path: Path):
    inputs = PortableRootInputs(tmp_path / "install", tmp_path / "local", "a" * 64)
    layout = derive_portable_root_layout(inputs)
    assert not layout.RELEASE_ROOT.exists()
    value = derive_portable_path_roots(inputs, "release-A")
    prepare_install_state_directories(value)
    value.APP_ROOT.mkdir(parents=True)
    (value.APP_ROOT / "main.py").write_text("# fixture\n", encoding="utf-8")
    (value.APP_ROOT / "static").mkdir()
    atomic_write_current_release(value, release(), expected_manifest_sha256="a" * 64)
    resolved = resolve_portable_path_roots(inputs)
    assert resolved.APP_ROOT == value.APP_ROOT
    assert resolved.PYTHON_RUNTIME == value.APP_ROOT / "python"


@pytest.mark.parametrize("release_id", ["CON", "CON.txt", "COM1.json", "bad/name", "bad\\name", "bad..name", "trail.", " trail"])
def test_release_id_fails_closed(tmp_path: Path, release_id: str):
    value = roots(tmp_path)
    bad = CurrentRelease(release().schema_version, release_id, f"releases/{release_id}", "a" * 64, release().activated_at, None)
    with pytest.raises(CurrentReleaseError):
        atomic_write_current_release(value, bad)


def test_reader_rejects_duplicate_unknown_bom_and_invalid_manifest(tmp_path: Path):
    value = roots(tmp_path)
    path = value.STATE_ROOT / "current-release.json"
    cases = [
        b'{"schema_version":"env-1b1b-current-release-v1","schema_version":"env-1b1b-current-release-v1"}',
        b'\xef\xbb\xbf{}',
        b'{"unknown":true}',
        b'\xff',
    ]
    for raw in cases:
        path.write_bytes(raw)
        with pytest.raises(CurrentReleaseError):
            read_current_release(value)


def test_residual_temp_fails_closed_without_deletion(tmp_path: Path):
    value = roots(tmp_path)
    temporary = value.STATE_ROOT / "current-release.json.new"
    temporary.write_text("foreign", encoding="utf-8")
    with pytest.raises(CurrentReleaseError, match="CURRENT_RELEASE_TEMP_EXISTS"):
        atomic_write_current_release(value, release())
    assert temporary.read_text(encoding="utf-8") == "foreign"


def test_expected_manifest_is_format_only_and_optional_equality(tmp_path: Path):
    value = roots(tmp_path)
    atomic_write_current_release(value, release(), expected_manifest_sha256="a" * 64)
    assert read_current_release(value, expected_manifest_sha256="a" * 64).manifest_sha256 == "a" * 64
    with pytest.raises(CurrentReleaseError, match="CURRENT_RELEASE_MANIFEST_SHA_MISMATCH"):
        read_current_release(value, expected_manifest_sha256="b" * 64)
