from __future__ import annotations

from pathlib import Path
import threading
import json
import os
import errno
from dataclasses import FrozenInstanceError, replace

import pytest

from enterprise.paths import (
    PortableRootInputs,
    derive_portable_path_roots,
    derive_portable_root_layout,
    prepare_install_state_directories,
)
from enterprise.release.current_release import (
    CROSS_PROCESS_LOCK,
    DIRECTORY_SYNC_UNSUPPORTED,
    DIRECTORY_SYNC_VERIFIED,
    MAX_BYTES,
    _directory_sync_is_unsupported,
    _file_identity,
    _owned_temp_still_present,
    CurrentRelease,
    CurrentReleaseError,
    CurrentReleaseWriteResult,
    atomic_write_current_release,
    canonical_json,
    read_current_release,
    read_current_release_from_state_root,
    resolve_current_app_root,
    resolve_portable_path_roots,
    sync_state_root_directory,
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
    result = atomic_write_current_release(value, release())
    assert isinstance(result, CurrentReleaseWriteResult)
    assert result.pointer_replaced is True
    assert result.directory_sync_status in {DIRECTORY_SYNC_VERIFIED, DIRECTORY_SYNC_UNSUPPORTED}
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


@pytest.mark.parametrize("foreign", [b"x", b"x" * len(canonical_json(release())), canonical_json(release())])
def test_foreign_temp_is_never_deleted_regardless_of_length_or_content(tmp_path: Path, foreign: bytes):
    value = roots(tmp_path)
    temporary = value.STATE_ROOT / "current-release.json.new"
    temporary.write_bytes(foreign)
    with pytest.raises(CurrentReleaseError, match="CURRENT_RELEASE_TEMP_EXISTS"):
        atomic_write_current_release(value, release())
    assert temporary.read_bytes() == foreign


def test_temp_cleanup_identity_does_not_accept_a_path_replaced_by_foreign_file(tmp_path: Path):
    temporary = tmp_path / "current-release.json.new"
    temporary.write_bytes(canonical_json(release()))
    original_identity = _file_identity(os.stat(temporary, follow_symlinks=False))
    temporary.unlink()
    temporary.write_bytes(canonical_json(release()))
    assert _owned_temp_still_present(temporary, original_identity) is False


def test_writer_never_activates_or_deletes_a_foreign_replacement_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from enterprise.release import current_release as current_release_module

    value = roots(tmp_path)
    old = release()
    atomic_write_current_release(value, old)
    replacement = CurrentRelease(old.schema_version, "release-B", "releases/release-B", "b" * 64, old.activated_at, "release-A")
    temporary = value.STATE_ROOT / "current-release.json.new"
    foreign = b"foreign replacement"
    original_check = current_release_module._assert_no_reparse
    replaced = False

    def replace_after_close(path: Path, label: str) -> None:
        nonlocal replaced
        original_check(path, label)
        if path == temporary and not replaced:
            replaced = True
            temporary.unlink()
            temporary.write_bytes(foreign)

    monkeypatch.setattr(current_release_module, "_assert_no_reparse", replace_after_close)
    with pytest.raises(CurrentReleaseError, match="CURRENT_RELEASE_TEMP_OWNERSHIP_LOST"):
        atomic_write_current_release(value, replacement)
    assert read_current_release(value) == old
    assert temporary.read_bytes() == foreign


def _failing_temp_open(monkeypatch: pytest.MonkeyPatch, temporary: Path, *, failure: str) -> None:
    original_open = Path.open

    def wrapped_open(path: Path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        if path != temporary:
            return handle

        class Handle:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                handle.close()

            def write(self, data):
                if failure == "write":
                    raise OSError("injected write failure")
                return handle.write(data)

            def flush(self):
                if failure == "flush":
                    raise OSError("injected flush failure")
                return handle.flush()

            def fileno(self):
                return handle.fileno()

        return Handle()

    monkeypatch.setattr(Path, "open", wrapped_open)


@pytest.mark.parametrize("failure", ["write", "flush"])
def test_writer_cleans_only_its_own_temp_after_write_or_flush_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str):
    value = roots(tmp_path)
    temporary = value.STATE_ROOT / "current-release.json.new"
    _failing_temp_open(monkeypatch, temporary, failure=failure)
    with pytest.raises(CurrentReleaseError, match="CURRENT_RELEASE_WRITE_FAILED"):
        atomic_write_current_release(value, release())
    assert not temporary.exists()


def test_writer_cleans_its_temp_after_fsync_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    value = roots(tmp_path)
    temporary = value.STATE_ROOT / "current-release.json.new"
    monkeypatch.setattr("enterprise.release.current_release.os.fsync", lambda _: (_ for _ in ()).throw(OSError("injected fsync")))
    with pytest.raises(CurrentReleaseError, match="CURRENT_RELEASE_WRITE_FAILED"):
        atomic_write_current_release(value, release())
    assert not temporary.exists()


def test_replace_failure_preserves_old_pointer_and_cleans_own_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    value = roots(tmp_path)
    old = release()
    atomic_write_current_release(value, old)
    replacement = CurrentRelease(old.schema_version, "release-B", "releases/release-B", old.manifest_sha256, old.activated_at, "release-A")
    monkeypatch.setattr("enterprise.release.current_release.os.replace", lambda *_: (_ for _ in ()).throw(OSError("injected replace")))
    with pytest.raises(CurrentReleaseError, match="CURRENT_RELEASE_WRITE_FAILED"):
        atomic_write_current_release(value, replacement)
    assert read_current_release(value) == old
    assert not (value.STATE_ROOT / "current-release.json.new").exists()


def test_writer_calls_directory_sync_after_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from enterprise.release import current_release as current_release_module

    value = roots(tmp_path)
    calls: list[Path] = []

    def record_sync(path: Path) -> str:
        calls.append(path)
        return DIRECTORY_SYNC_VERIFIED

    monkeypatch.setattr(current_release_module, "sync_state_root_directory", record_sync)
    result = atomic_write_current_release(value, release())
    assert calls == [value.STATE_ROOT]
    assert result == CurrentReleaseWriteResult(True, DIRECTORY_SYNC_VERIFIED)
    assert read_current_release(value) == release()


def test_writer_returns_unsupported_sync_result_without_path_or_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from enterprise.release import current_release as current_release_module

    value = roots(tmp_path)
    monkeypatch.setattr(
        current_release_module,
        "sync_state_root_directory",
        lambda _: DIRECTORY_SYNC_UNSUPPORTED,
    )
    result = atomic_write_current_release(value, release())
    assert result.pointer_replaced is True
    assert result.directory_sync_status == DIRECTORY_SYNC_UNSUPPORTED
    serialized = repr(result)
    assert str(value.STATE_ROOT) not in serialized
    assert "secret" not in serialized.lower()
    with pytest.raises(FrozenInstanceError):
        result.directory_sync_status = DIRECTORY_SYNC_VERIFIED  # type: ignore[misc]


def test_directory_sync_reports_unsupported_without_claiming_verified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import errno

    value = roots(tmp_path)
    monkeypatch.setattr("enterprise.release.current_release.os.open", lambda *_: (_ for _ in ()).throw(OSError(errno.EINVAL, "unsupported")))
    assert sync_state_root_directory(value.STATE_ROOT) == DIRECTORY_SYNC_UNSUPPORTED


@pytest.mark.parametrize("stage", ["open", "fsync"])
@pytest.mark.parametrize("errno_value", [errno.EACCES, errno.EPERM])
def test_posix_permission_errors_are_unexpected_directory_sync_failures(
    tmp_path: Path,
    stage: str,
    errno_value: int,
):
    assert _directory_sync_is_unsupported(OSError(errno_value, "denied"), stage=stage, platform_name="posix") is False


@pytest.mark.parametrize("errno_value", [errno.EACCES, errno.EPERM])
def test_windows_directory_open_permission_error_is_specific_unsupported_branch(errno_value: int):
    assert _directory_sync_is_unsupported(
        OSError(errno_value, "directory handle unsupported"),
        stage="open",
        platform_name="nt",
    ) is True


def test_windows_fsync_permission_error_is_not_silently_unsupported():
    assert _directory_sync_is_unsupported(
        OSError(errno.EACCES, "denied"),
        stage="fsync",
        platform_name="nt",
    ) is False


def test_directory_sync_permission_failure_uses_stable_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import errno
    from enterprise.release import current_release as current_release_module

    value = roots(tmp_path)
    monkeypatch.setattr(current_release_module.os, "open", lambda *_: 12345)
    monkeypatch.setattr(current_release_module.os, "fsync", lambda *_: (_ for _ in ()).throw(OSError(errno.EACCES, "permission denied")))
    monkeypatch.setattr(current_release_module.os, "close", lambda *_: None)
    with pytest.raises(CurrentReleaseError, match="CURRENT_RELEASE_DIRECTORY_SYNC_FAILED"):
        sync_state_root_directory(value.STATE_ROOT)


def test_directory_sync_failure_leaves_pointer_authoritative_for_reread(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    value = roots(tmp_path)
    old = release()
    atomic_write_current_release(value, old)
    replacement = CurrentRelease(old.schema_version, "release-B", "releases/release-B", "b" * 64, old.activated_at, "release-A")
    original_fsync = os.fsync
    monkeypatch.setattr("enterprise.release.current_release.os.open", lambda *_: 12345)
    monkeypatch.setattr(
        "enterprise.release.current_release.os.fsync",
        lambda fd: (_ for _ in ()).throw(OSError("unexpected sync failure")) if fd == 12345 else original_fsync(fd),
    )
    monkeypatch.setattr("enterprise.release.current_release.os.close", lambda *_: None)
    with pytest.raises(CurrentReleaseError, match="CURRENT_RELEASE_DIRECTORY_SYNC_FAILED"):
        atomic_write_current_release(value, replacement)
    assert read_current_release(value) == replacement
    assert not (value.STATE_ROOT / "current-release.json.new").exists()


def test_post_replace_state_root_reparse_failure_is_durability_error_and_requires_reread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from enterprise.release import current_release as current_release_module

    value = roots(tmp_path)
    old = release()
    atomic_write_current_release(value, old)
    replacement = CurrentRelease(old.schema_version, "release-B", "releases/release-B", "b" * 64, old.activated_at, "release-A")
    original_check = current_release_module._assert_no_reparse
    state_root_checks = 0

    def reject_post_replace(path: Path, label: str) -> None:
        nonlocal state_root_checks
        if Path(path) == value.STATE_ROOT:
            state_root_checks += 1
            if state_root_checks >= 2:
                raise current_release_module.PathRootsError("PATH_REPARSE_FORBIDDEN", label)
        original_check(path, label)

    monkeypatch.setattr(current_release_module, "_assert_no_reparse", reject_post_replace)
    with pytest.raises(CurrentReleaseError, match="CURRENT_RELEASE_DIRECTORY_SYNC_FAILED"):
        atomic_write_current_release(value, replacement)
    monkeypatch.setattr(current_release_module, "_assert_no_reparse", original_check)
    assert read_current_release(value) == replacement
    assert not (value.STATE_ROOT / "current-release.json.new").exists()


def test_in_process_writers_are_serialized_and_cross_process_lock_is_not_claimed(tmp_path: Path):
    value = roots(tmp_path)
    candidates = (
        release(),
        CurrentRelease(release().schema_version, "release-B", "releases/release-B", "b" * 64, release().activated_at, "release-A"),
    )
    failures: list[BaseException] = []
    gate = threading.Barrier(2)

    def write(candidate: CurrentRelease) -> None:
        try:
            gate.wait(timeout=5)
            atomic_write_current_release(value, candidate)
        except BaseException as exc:  # assertion reports any unexpected writer failure
            failures.append(exc)

    threads = [threading.Thread(target=write, args=(candidate,)) for candidate in candidates]
    [thread.start() for thread in threads]
    [thread.join(timeout=5) for thread in threads]
    assert not failures
    assert read_current_release(value) in candidates
    assert not (value.STATE_ROOT / "current-release.json.new").exists()
    assert CROSS_PROCESS_LOCK is False


def test_expected_manifest_is_format_only_and_optional_equality(tmp_path: Path):
    value = roots(tmp_path)
    atomic_write_current_release(value, release(), expected_manifest_sha256="a" * 64)
    assert read_current_release(value, expected_manifest_sha256="a" * 64).manifest_sha256 == "a" * 64
    with pytest.raises(CurrentReleaseError, match="CURRENT_RELEASE_MANIFEST_SHA_MISMATCH"):
        read_current_release(value, expected_manifest_sha256="b" * 64)


def test_current_release_size_boundary_is_exact_and_oversize_fails(tmp_path: Path):
    value = roots(tmp_path)
    path = value.STATE_ROOT / "current-release.json"
    raw = canonical_json(release())
    path.write_bytes(raw + b" " * (MAX_BYTES - len(raw)))
    assert read_current_release(value) == release()
    path.write_bytes(raw + b" " * (MAX_BYTES - len(raw) + 1))
    with pytest.raises(CurrentReleaseError, match="CURRENT_RELEASE_SIZE_INVALID"):
        read_current_release(value)


@pytest.mark.parametrize("field,value", [
    ("release_id", "x" * 129),
    ("release_id", "非ASCII"),
    ("release_id", "NUL.txt"),
    ("release_id", "trail."),
    ("app_root_relative", "/releases/release-A"),
    ("app_root_relative", "releases\\release-A"),
    ("app_root_relative", "C:releases/release-A"),
    ("app_root_relative", "releases/../release-A"),
    ("manifest_sha256", "A" * 64),
    ("manifest_sha256", "a" * 63),
    ("activated_at", "2026-07-22T12:00:00.1Z"),
    ("activated_at", "2026-07-22T12:00:00+08:00"),
    ("activated_at", "2026-02-30T12:00:00Z"),
])
def test_reader_rejects_all_pointer_field_escape_forms(tmp_path: Path, field: str, value: str):
    roots_value = roots(tmp_path)
    payload = release().as_dict()
    payload[field] = value
    (roots_value.STATE_ROOT / "current-release.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CurrentReleaseError):
        read_current_release(roots_value)


def test_reader_rejects_previous_equal_current_and_relative_state_root(tmp_path: Path):
    value = roots(tmp_path)
    payload = release().as_dict()
    payload["previous_release_id"] = "release-A"
    (value.STATE_ROOT / "current-release.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CurrentReleaseError, match="CURRENT_RELEASE_PREVIOUS_INVALID"):
        read_current_release(value)
    relative_state = tmp_path / "relative-state"
    relative_state.mkdir()
    (relative_state / "current-release.json").write_bytes(canonical_json(release()))
    original_cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        with pytest.raises(CurrentReleaseError, match="PATH_NOT_ABSOLUTE"):
            read_current_release_from_state_root(Path("relative-state"))
    finally:
        os.chdir(original_cwd)


def test_writer_rejects_untrusted_pathroots_and_has_no_runtime_activation_call_sites(tmp_path: Path):
    value = roots(tmp_path)
    forged = replace(value)
    with pytest.raises(CurrentReleaseError, match="PATH_ROOTS_UNTRUSTED"):
        atomic_write_current_release(forged, release())
    repository = Path(__file__).resolve().parents[2]
    production_sources = [
        source for source in (repository / "enterprise").rglob("*.py")
        if "tests" not in source.parts and source.name != "current_release.py"
    ]
    assert all("atomic_write_current_release(" not in source.read_text(encoding="utf-8") for source in production_sources)
