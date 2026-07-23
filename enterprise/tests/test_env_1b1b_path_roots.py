from __future__ import annotations

from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
import stat

import pytest

from enterprise.paths import (
    PATH_ROOTS_SCHEMA,
    PortableRootInputs,
    PathRoots,
    PathRootsError,
    _inside,
    _reset_path_roots_for_tests,
    derive_development_path_roots,
    derive_portable_path_roots,
    get_path_roots,
    install_path_roots_for_process,
    prepare_application_directories,
    prepare_install_state_directories,
    prepare_ops_directories,
    prepare_runtime_directories,
    resolve_database_path,
    validate_common_path_roots,
    validate_development_path_roots,
    validate_portable_release_layout,
    validate_release_component,
)


@pytest.fixture(autouse=True)
def reset_roots():
    _reset_path_roots_for_tests()
    yield
    _reset_path_roots_for_tests()


def portable(tmp_path: Path, release: str = "release-A"):
    return derive_portable_path_roots(PortableRootInputs(tmp_path / "安装 根", tmp_path / "本地 数据"), release)


def test_portable_contract_has_all_roots_and_deterministic_identity(tmp_path: Path):
    roots = portable(tmp_path)
    assert roots.schema_version == PATH_ROOTS_SCHEMA
    assert roots.APP_ROOT == roots.RELEASE_ROOT / "release-A"
    assert roots.PYTHON_RUNTIME == roots.APP_ROOT / "python"
    assert roots.UPLOAD_ROOT == roots.DATA_ROOT / "uploads"
    assert len(roots.inspect()["root_labels"]) == 14
    assert roots.inspect()["root_identity"] == portable(tmp_path).root_identity
    assert str(tmp_path) not in str(roots.inspect())


def test_derivation_and_common_validation_do_not_create_paths(tmp_path: Path):
    roots = portable(tmp_path)
    before = list(tmp_path.rglob("*"))
    validate_common_path_roots(roots)
    assert list(tmp_path.rglob("*")) == before


def test_development_is_code_anchored_and_needs_no_runtime_or_pointer(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code = tmp_path / "中文 空格" / "app"
    code.mkdir(parents=True)
    roots = derive_development_path_roots(code)
    validate_development_path_roots(roots)
    assert roots.APP_ROOT == code.resolve()
    assert roots.legacy_app_relative_layout is True
    assert roots.release_validation_eligible is False


def test_prepare_capabilities_are_scoped(tmp_path: Path):
    roots = portable(tmp_path)
    prepare_application_directories(roots)
    assert (roots.DATA_ROOT / "conversations").is_dir()
    assert (roots.UPLOAD_ROOT / "assets" / "uploads").is_dir()
    assert not roots.CONFIG_ROOT.exists() and not roots.STATE_ROOT.exists()
    prepare_runtime_directories(roots)
    assert (roots.RUNTIME_ROOT / "control").is_dir()
    assert (roots.LOG_ROOT / "runtime").is_dir()
    prepare_ops_directories(roots)
    assert roots.BACKUP_ROOT.is_dir() and (roots.STAGING_ROOT / "reports").is_dir()
    prepare_install_state_directories(roots)
    assert roots.CONFIG_ROOT.is_dir() and roots.STATE_ROOT.is_dir()
    assert not roots.APP_ROOT.exists()


def test_portable_layout_requires_source_structure_without_python_validation(tmp_path: Path):
    roots = portable(tmp_path)
    roots.APP_ROOT.mkdir(parents=True)
    (roots.APP_ROOT / "main.py").write_text("# fixture\n", encoding="utf-8")
    (roots.APP_ROOT / "static").mkdir()
    validate_portable_release_layout(roots)
    assert not roots.PYTHON_RUNTIME.exists()


@pytest.mark.parametrize("bad", ["C:relative", "\\\\server\\share", "\\\\?\\C:\\bad", "\\\\.\\C:\\bad"])
def test_special_windows_path_forms_fail_closed(tmp_path: Path, bad: str):
    with pytest.raises(PathRootsError):
        derive_portable_path_roots(PortableRootInputs(Path(bad), tmp_path / "local"), "release-A")


def test_process_install_is_idempotent_but_different_roots_fail(tmp_path: Path):
    first = portable(tmp_path, "release-A")
    assert install_path_roots_for_process(first) is first
    assert install_path_roots_for_process(first) is first
    with pytest.raises(PathRootsError, match="PATH_ROOTS_PROCESS_REINITIALIZATION"):
        install_path_roots_for_process(portable(tmp_path, "release-B"))
    assert get_path_roots() is first


@pytest.mark.parametrize("release_id", [
    "", "x" * 129, "非ASCII", "bad/name", "bad\\name", "..", "a..b",
    " lead", "trail ", "trail.", "/absolute", "C:relative", "\\\\server\\share",
    "\\\\?\\C:\\device", "CON", "con.txt", "PRN.json", "AUX.bin", "NUL.log",
    "COM1", "COM9.ext", "LPT1", "LPT9.log",
])
def test_release_component_validator_rejects_nonportable_identifiers(release_id: str):
    with pytest.raises(PathRootsError):
        validate_release_component(release_id)


def test_component_containment_is_not_string_prefix_based(tmp_path: Path):
    root = tmp_path / "app"
    assert _inside(root / "child", root)
    assert _inside(root / "子 目录", root)
    assert _inside(Path(root.anchor) / "root-child", Path(root.anchor))
    assert not _inside(tmp_path / "application", root)
    assert not _inside(tmp_path / "app2", root)
    assert not _inside(root, root)
    assert _inside(root, root, allow_equal=True)
    assert not _inside(root.parent, root)
    assert not _inside(root / "子 目录", tmp_path / "另一个")


def test_containment_handles_windows_volume_case_and_separator_boundaries():
    parent = Path(r"C:\App")
    assert _inside(Path(r"c:/app/child"), parent)
    assert not _inside(Path(r"C:\application"), parent)
    assert not _inside(Path(r"C:\app2"), parent)
    assert not _inside(Path(r"D:\app\child"), parent)


def test_portable_rejects_equal_and_unexpected_sibling_containment(tmp_path: Path):
    roots = portable(tmp_path)
    with pytest.raises(PathRootsError, match="PATH_ROOTS_EQUAL"):
        validate_common_path_roots(replace(roots, LOG_ROOT=roots.DATA_ROOT))
    with pytest.raises(PathRootsError, match="PATH_ROOTS_UNEXPECTED_CONTAINMENT"):
        validate_common_path_roots(replace(roots, LOG_ROOT=roots.DATA_ROOT / "logs"))


def _manually_forged(roots):
    values = {name: getattr(roots, name) for name in (
        "INSTALL_ROOT", "RELEASE_ROOT", "APP_ROOT", "CONFIG_ROOT", "DATA_ROOT", "UPLOAD_ROOT",
        "LOG_ROOT", "BACKUP_ROOT", "STATE_ROOT", "STAGING_ROOT", "RUNTIME_ROOT", "CACHE_ROOT",
        "TEMP_ROOT", "PYTHON_RUNTIME",
    )}
    return PathRoots(**values, profile=roots.profile)


@pytest.mark.parametrize("prepare", [
    prepare_application_directories,
    prepare_runtime_directories,
    prepare_ops_directories,
    prepare_install_state_directories,
])
def test_untrusted_manual_roots_cannot_install_or_prepare(tmp_path: Path, prepare):
    forged = _manually_forged(portable(tmp_path))
    with pytest.raises(PathRootsError, match="PATH_ROOTS_UNTRUSTED"):
        install_path_roots_for_process(forged)
    with pytest.raises(PathRootsError, match="PATH_ROOTS_UNTRUSTED"):
        prepare(forged)
    assert not forged.APP_ROOT.exists()
    assert not forged.DATA_ROOT.exists()
    assert not forged.LOG_ROOT.exists()


def test_untrusted_manual_development_roots_cannot_install_or_prepare(tmp_path: Path):
    code_root = tmp_path / "development-code"
    code_root.mkdir()
    forged = _manually_forged(derive_development_path_roots(code_root))
    with pytest.raises(PathRootsError, match="PATH_ROOTS_UNTRUSTED"):
        install_path_roots_for_process(forged)
    with pytest.raises(PathRootsError, match="PATH_ROOTS_UNTRUSTED"):
        prepare_application_directories(forged)
    assert not (code_root / "data").exists()


def test_dataclass_replace_cannot_inherit_the_private_trust_capability(tmp_path: Path):
    roots = portable(tmp_path)
    forged = replace(roots, DATA_ROOT=roots.APP_ROOT / "data")
    with pytest.raises(PathRootsError, match="PATH_ROOTS_UNTRUSTED"):
        install_path_roots_for_process(forged)
    with pytest.raises(PathRootsError, match="PATH_ROOTS_UNTRUSTED"):
        prepare_application_directories(forged)
    assert not (roots.APP_ROOT / "data").exists()


def test_reparse_metadata_is_rejected_by_validation(tmp_path: Path, monkeypatch):
    import enterprise.paths as paths_module

    roots = portable(tmp_path)
    roots.APP_ROOT.mkdir(parents=True)
    original_lstat = paths_module.os.lstat

    def marked_lstat(path):
        if Path(path) == roots.APP_ROOT:
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        return original_lstat(path)

    monkeypatch.setattr(paths_module.os, "lstat", marked_lstat)
    with pytest.raises(PathRootsError, match="PATH_REPARSE_FORBIDDEN"):
        validate_common_path_roots(roots)


def test_existing_symlink_component_is_rejected_when_platform_allows_it(tmp_path: Path):
    roots = portable(tmp_path)
    roots.RELEASE_ROOT.parent.mkdir(parents=True)
    target = tmp_path / "release-target"
    target.mkdir()
    try:
        roots.RELEASE_ROOT.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlink unavailable: {exc.__class__.__name__}")
    with pytest.raises(PathRootsError, match="PATH_REPARSE_FORBIDDEN"):
        validate_common_path_roots(roots)


def test_post_create_reparse_check_fails_closed(tmp_path: Path, monkeypatch):
    import enterprise.paths as paths_module

    roots = portable(tmp_path)
    target = roots.DATA_ROOT / "conversations"
    original = paths_module._assert_no_reparse
    target_checks = 0

    def reject_after_create(path: Path, label: str) -> None:
        nonlocal target_checks
        if path == target:
            target_checks += 1
            if target_checks == 2:
                raise PathRootsError("PATH_REPARSE_FORBIDDEN", label)
        original(path, label)

    monkeypatch.setattr(paths_module, "_assert_no_reparse", reject_after_create)
    with pytest.raises(PathRootsError, match="PATH_REPARSE_FORBIDDEN"):
        prepare_application_directories(roots)
    assert target.is_dir()
    assert target_checks == 2


def test_database_resolution_is_data_root_anchored_and_portable_fail_closed(tmp_path: Path):
    roots = portable(tmp_path)
    assert resolve_database_path(roots, None) == roots.DATA_ROOT / "enterprise.db"
    assert resolve_database_path(roots, "nested/database.db") == roots.DATA_ROOT / "nested" / "database.db"
    assert resolve_database_path(roots, roots.DATA_ROOT / "nested" / "absolute.db") == roots.DATA_ROOT / "nested" / "absolute.db"
    with pytest.raises(PathRootsError, match="DB_PATH_OUTSIDE_DATA_ROOT"):
        resolve_database_path(roots, roots.APP_ROOT / "enterprise.db")
    with pytest.raises(PathRootsError, match="DB_PATH_OUTSIDE_DATA_ROOT"):
        resolve_database_path(roots, tmp_path / "outside" / "enterprise.db")
    with pytest.raises(PathRootsError, match="DB_PATH_OUTSIDE_DATA_ROOT"):
        resolve_database_path(roots, "../escape.db")
    with pytest.raises(PathRootsError, match="DB_PATH_DIRECTORY_INVALID"):
        resolve_database_path(roots, roots.DATA_ROOT)
    with pytest.raises(PathRootsError):
        resolve_database_path(roots, "")
    with pytest.raises(PathRootsError):
        resolve_database_path(roots, "C:relative.db")
    with pytest.raises(PathRootsError):
        resolve_database_path(roots, "\\\\server\\share\\enterprise.db")
    with pytest.raises(PathRootsError):
        resolve_database_path(roots, "\\\\?\\C:\\device\\enterprise.db")


def test_development_relative_database_is_not_cwd_dependent(tmp_path: Path, monkeypatch):
    code_root = tmp_path / "code" / "应用"
    code_root.mkdir(parents=True)
    roots = derive_development_path_roots(code_root)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert resolve_database_path(roots, "relative.db") == roots.DATA_ROOT / "relative.db"


def test_database_reparse_ancestor_is_rejected_before_parent_creation(tmp_path: Path, monkeypatch):
    import enterprise.paths as paths_module

    roots = portable(tmp_path)
    original = paths_module._assert_no_reparse

    def reject(path: Path, label: str) -> None:
        if label == "DATA_ROOT":
            raise PathRootsError("PATH_REPARSE_FORBIDDEN", label)
        original(path, label)

    monkeypatch.setattr(paths_module, "_assert_no_reparse", reject)
    with pytest.raises(PathRootsError, match="PATH_REPARSE_FORBIDDEN"):
        resolve_database_path(roots, "nested/enterprise.db")
    assert not (roots.DATA_ROOT / "nested").exists()


def test_get_db_creates_only_a_data_root_parent_and_keeps_sqlite_sidecars_together(tmp_path: Path, monkeypatch):
    from enterprise import db

    roots = portable(tmp_path)
    database = roots.DATA_ROOT / "nested" / "enterprise.db"
    monkeypatch.setattr(db, "PATH_ROOTS", roots)
    monkeypatch.setattr(db, "DB_PATH", str(database))
    connection = db.get_db()
    try:
        connection.execute("CREATE TABLE fixture (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO fixture DEFAULT VALUES")
        connection.commit()
        assert database.is_file()
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        sidecars = [candidate for candidate in database.parent.iterdir() if candidate.name.startswith(database.name + "-")]
        assert sidecars
        assert all(candidate.parent == database.parent for candidate in sidecars)
        assert database.parent.is_relative_to(roots.DATA_ROOT)
        assert not roots.APP_ROOT.exists()
    finally:
        connection.close()


def test_runtime_cli_keeps_development_logs_external_and_portable_logs_require_explicit_injection(tmp_path: Path, monkeypatch):
    import argparse
    from enterprise import config as enterprise_config
    from enterprise.runtime import cli
    from enterprise.runtime.supervisor import RuntimeSupervisor

    args = argparse.Namespace(
        app_root=str(tmp_path / "app"), runtime_root=str(tmp_path / "runtime"),
        upstream_port=None, gateway_port=None, fixture_child_wrapper=False,
    )
    development = derive_development_path_roots(tmp_path / "development-app")
    monkeypatch.setattr(enterprise_config, "PATH_ROOTS", development)
    development_config = cli._config(args, mode="foreground")
    assert development_config.log_root is None
    assert RuntimeSupervisor(development_config).logs.root == development_config.runtime_root
    assert not str(RuntimeSupervisor(development_config).logs.root).startswith(str(development.APP_ROOT))

    release = portable(tmp_path)
    monkeypatch.setattr(enterprise_config, "PATH_ROOTS", release)
    portable_config = cli._config(args, mode="foreground")
    assert portable_config.log_root is None
    assert RuntimeSupervisor(portable_config).logs.root == portable_config.runtime_root

    explicit_portable = replace(portable_config, log_root=release.LOG_ROOT / "runtime")
    explicit_supervisor = RuntimeSupervisor(explicit_portable)
    assert explicit_supervisor.logs.root == release.LOG_ROOT / "runtime"
    assert explicit_supervisor.store.root == explicit_portable.runtime_root
