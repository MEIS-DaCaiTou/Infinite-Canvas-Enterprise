"""ENV-1B1C-B1 writable-root probe primitive tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from enterprise.runtime.error_contract import RuntimeContractError
from enterprise.runtime.writable_probe import probe_writable_root


VALID_SUFFIX = "a" * 8


class _HandleProxy:
    def __init__(self, handle, *, write_fails: bool = False, flush_fails: bool = False) -> None:
        self._handle = handle
        self._write_fails = write_fails
        self._flush_fails = flush_fails

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        self._handle.close()

    def write(self, value: bytes) -> int:
        if self._write_fails:
            raise OSError("write failure")
        return self._handle.write(value)

    def flush(self) -> None:
        if self._flush_fails:
            raise OSError("flush failure")
        self._handle.flush()

    def fileno(self) -> int:
        return self._handle.fileno()


def test_writable_probe_success_creates_and_removes_only_own_file(tmp_path: Path) -> None:
    result = probe_writable_root(tmp_path, "DATA_ROOT", name_factory=lambda: VALID_SUFFIX)
    assert result.created is True
    assert result.cleaned_up is True
    assert list(tmp_path.iterdir()) == []


def test_r4_writable_probe_default_name_is_random_and_cleanup_safe(tmp_path: Path) -> None:
    result = probe_writable_root(tmp_path, "TEMP_ROOT")
    assert result.created is True
    assert result.cleaned_up is True
    assert list(tmp_path.iterdir()) == []


def test_writable_probe_existing_name_fails_without_overwrite(tmp_path: Path) -> None:
    existing = tmp_path / f".ice-probe-data_root-{VALID_SUFFIX}.tmp"
    existing.write_text("foreign", encoding="utf-8")
    with pytest.raises(RuntimeContractError) as exc:
        probe_writable_root(tmp_path, "DATA_ROOT", name_factory=lambda: VALID_SUFFIX)
    assert exc.value.code == "WRITABLE_PROBE_EXISTS"
    assert existing.read_text(encoding="utf-8") == "foreign"


def test_writable_probe_does_not_delete_foreign_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / f".ice-probe-log_root-{VALID_SUFFIX}.tmp"

    def replace_after_create(path: Path) -> bool:
        target.unlink()
        target.write_text("foreign replacement", encoding="utf-8")
        return False

    monkeypatch.setattr("enterprise.runtime.writable_probe.has_reparse_point", replace_after_create)
    with pytest.raises(RuntimeContractError) as exc:
        probe_writable_root(tmp_path, "LOG_ROOT", name_factory=lambda: VALID_SUFFIX)
    assert exc.value.code == "WRITABLE_PROBE_OWNERSHIP_LOST"
    assert target.read_text(encoding="utf-8") == "foreign replacement"


def test_r4_writable_probe_rejects_identity_reused_foreign_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A reusable file id is not ownership: the nonce bytes are also bound."""
    import enterprise.runtime.writable_probe as subject

    target = tmp_path / f".ice-probe-log_root-{VALID_SUFFIX}.tmp"
    original_identity = subject._identity

    def replace_after_create(path: Path) -> bool:
        target.unlink()
        target.write_bytes(b"ice-probe-v1:foreign-token\\n")
        return False

    monkeypatch.setattr(subject, "has_reparse_point", replace_after_create)
    monkeypatch.setattr(subject, "_identity", lambda path: (1, 1))
    with pytest.raises(RuntimeContractError) as exc:
        probe_writable_root(tmp_path, "LOG_ROOT", name_factory=lambda: VALID_SUFFIX)
    assert exc.value.code == "WRITABLE_PROBE_OWNERSHIP_LOST"
    assert target.read_bytes() == b"ice-probe-v1:foreign-token\\n"


def test_writable_probe_fsync_failure_cleans_own_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("enterprise.runtime.writable_probe.os.fsync", lambda _: (_ for _ in ()).throw(OSError("fsync")))
    with pytest.raises(RuntimeContractError) as exc:
        probe_writable_root(tmp_path, "RUNTIME_ROOT", name_factory=lambda: VALID_SUFFIX)
    assert exc.value.code == "WRITABLE_PROBE_FSYNC_FAILED"
    assert list(tmp_path.iterdir()) == []


def test_writable_probe_rejects_app_root_label(tmp_path: Path) -> None:
    with pytest.raises(RuntimeContractError) as exc:
        probe_writable_root(tmp_path, "APP_ROOT")
    assert exc.value.code == "WRITABLE_PROBE_LABEL_INVALID"


def test_r3_writable_probe_missing_root_is_a_stable_contract_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeContractError) as exc:
        probe_writable_root(tmp_path / "missing", "DATA_ROOT", name_factory=lambda: "a" * 8)
    assert exc.value.code == "WRITABLE_PROBE_CREATE_FAILED"


def test_r3_writable_probe_create_permission_error_is_sanitized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*_: object, **__: object):
        raise PermissionError("host detail must not leak")

    monkeypatch.setattr(Path, "open", denied)
    with pytest.raises(RuntimeContractError) as exc:
        probe_writable_root(tmp_path, "DATA_ROOT", name_factory=lambda: VALID_SUFFIX)
    assert exc.value.code == "WRITABLE_PROBE_CREATE_FAILED"
    assert "host detail" not in exc.value.payload.canonical_json().decode("utf-8")


@pytest.mark.parametrize(("failure", "expected"), [("write", "WRITABLE_PROBE_WRITE_FAILED"), ("flush", "WRITABLE_PROBE_WRITE_FAILED")])
def test_r3_writable_probe_write_stages_are_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str, expected: str
) -> None:
    original_open = Path.open

    def controlled_open(path: Path, *args: object, **kwargs: object):
        return _HandleProxy(
            original_open(path, *args, **kwargs),
            write_fails=failure == "write",
            flush_fails=failure == "flush",
        )

    monkeypatch.setattr(Path, "open", controlled_open)
    with pytest.raises(RuntimeContractError) as exc:
        probe_writable_root(tmp_path, "DATA_ROOT", name_factory=lambda: VALID_SUFFIX)
    assert exc.value.code == expected
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("suffix", ["short", "a" * 65, "a" * 7, "a" * 8 + "\n"])
def test_r3_writable_probe_suffix_is_strictly_bounded(tmp_path: Path, suffix: str) -> None:
    with pytest.raises(RuntimeContractError) as exc:
        probe_writable_root(tmp_path, "DATA_ROOT", name_factory=lambda: suffix)
    assert exc.value.code == "WRITABLE_PROBE_LABEL_INVALID"
