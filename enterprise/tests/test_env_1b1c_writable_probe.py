"""ENV-1B1C-B1 writable-root probe primitive tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from enterprise.runtime.error_contract import RuntimeContractError
from enterprise.runtime.writable_probe import probe_writable_root


def test_writable_probe_success_creates_and_removes_only_own_file(tmp_path: Path) -> None:
    result = probe_writable_root(tmp_path, "DATA_ROOT", name_factory=lambda: "fixed")
    assert result.created is True
    assert result.cleaned_up is True
    assert list(tmp_path.iterdir()) == []


def test_writable_probe_existing_name_fails_without_overwrite(tmp_path: Path) -> None:
    existing = tmp_path / ".ice-probe-data_root-fixed.tmp"
    existing.write_text("foreign", encoding="utf-8")
    with pytest.raises(RuntimeContractError) as exc:
        probe_writable_root(tmp_path, "DATA_ROOT", name_factory=lambda: "fixed")
    assert exc.value.code == "WRITABLE_PROBE_EXISTS"
    assert existing.read_text(encoding="utf-8") == "foreign"


def test_writable_probe_does_not_delete_foreign_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / ".ice-probe-log_root-fixed.tmp"

    def replace_after_create(path: Path) -> bool:
        target.unlink()
        target.write_text("foreign replacement", encoding="utf-8")
        return False

    monkeypatch.setattr("enterprise.runtime.writable_probe.has_reparse_point", replace_after_create)
    with pytest.raises(RuntimeContractError) as exc:
        probe_writable_root(tmp_path, "LOG_ROOT", name_factory=lambda: "fixed")
    assert exc.value.code == "WRITABLE_PROBE_OWNERSHIP_LOST"
    assert target.read_text(encoding="utf-8") == "foreign replacement"


def test_writable_probe_fsync_failure_cleans_own_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("enterprise.runtime.writable_probe.os.fsync", lambda _: (_ for _ in ()).throw(OSError("fsync")))
    with pytest.raises(RuntimeContractError) as exc:
        probe_writable_root(tmp_path, "RUNTIME_ROOT", name_factory=lambda: "fixed")
    assert exc.value.code == "WRITABLE_PROBE_FSYNC_FAILED"
    assert list(tmp_path.iterdir()) == []


def test_writable_probe_rejects_app_root_label(tmp_path: Path) -> None:
    with pytest.raises(RuntimeContractError) as exc:
        probe_writable_root(tmp_path, "APP_ROOT")
    assert exc.value.code == "WRITABLE_PROBE_LABEL_INVALID"
