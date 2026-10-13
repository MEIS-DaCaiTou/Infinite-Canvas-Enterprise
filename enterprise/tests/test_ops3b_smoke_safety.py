"""The isolated Windows drill must never move or erase existing user data."""

from pathlib import Path

import pytest

from enterprise.tests.update_mvp_1_windows_smoke import (
    _assert_unused_local_roots,
    _create_owned_local_roots,
    _safe_generated_remove,
)


NAMES = ("InfiniteCanvasEnterprise", "Infinite-Canvas-Enterprise")


def test_preexisting_local_root_blocks_before_any_move_or_delete(tmp_path: Path):
    existing = tmp_path / NAMES[0]
    existing.mkdir()
    important = existing / "customer-data.txt"
    important.write_text("retain", encoding="utf-8")
    with pytest.raises(RuntimeError, match="UPDATE_MVP_R1_LOCAL_ROOTS_IN_USE"):
        _assert_unused_local_roots(tmp_path, NAMES)
    assert important.read_text(encoding="utf-8") == "retain"


def test_cleanup_requires_this_drills_exact_marker(tmp_path: Path):
    owned = tmp_path / NAMES[0]
    owned.mkdir()
    important = owned / "customer-data.txt"
    important.write_text("retain", encoding="utf-8")
    with pytest.raises(RuntimeError, match="UPDATE_MVP_R1_LOCAL_ROOT_NOT_OWNED"):
        _safe_generated_remove(owned, tmp_path, "current-drill")
    assert important.read_text(encoding="utf-8") == "retain"
    (owned / ".ops3b-drill-owned").write_text("another-drill", encoding="ascii")
    with pytest.raises(RuntimeError, match="UPDATE_MVP_R1_LOCAL_ROOT_NOT_OWNED"):
        _safe_generated_remove(owned, tmp_path, "current-drill")
    assert important.read_text(encoding="utf-8") == "retain"


def test_owned_fixture_root_can_be_cleaned(tmp_path: Path):
    owned = tmp_path / NAMES[0]
    owned.mkdir()
    (owned / ".ops3b-drill-owned").write_text("current-drill", encoding="ascii")
    (owned / "runtime").mkdir()
    _safe_generated_remove(owned, tmp_path, "current-drill")
    assert not owned.exists()


def test_each_scenario_recreates_owned_roots_after_cleanup(tmp_path: Path):
    for _ in ("success", "rollback"):
        _create_owned_local_roots(tmp_path, NAMES, "current-drill")
        for name in NAMES:
            owned = tmp_path / name
            assert (owned / ".ops3b-drill-owned").read_text(encoding="ascii") == "current-drill"
            _safe_generated_remove(owned, tmp_path, "current-drill")
        assert all(not (tmp_path / name).exists() for name in NAMES)
