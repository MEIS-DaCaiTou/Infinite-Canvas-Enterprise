from __future__ import annotations

from pathlib import Path

import pytest

from enterprise.paths import (
    PATH_ROOTS_SCHEMA,
    PortableRootInputs,
    PathRootsError,
    _reset_path_roots_for_tests,
    derive_development_path_roots,
    derive_portable_path_roots,
    get_path_roots,
    install_path_roots_for_process,
    prepare_application_directories,
    prepare_install_state_directories,
    prepare_ops_directories,
    prepare_runtime_directories,
    validate_common_path_roots,
    validate_development_path_roots,
    validate_portable_release_layout,
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
