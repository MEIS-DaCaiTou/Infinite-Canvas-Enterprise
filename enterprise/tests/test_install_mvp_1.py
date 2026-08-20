from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from enterprise import db
from enterprise.fresh_install import (
    FreshInstallError,
    VerifiedReleaseAssets,
    install_greenfield,
    require_gateway_database_ready,
    validate_first_password,
)
from enterprise.migrations.sec_1b2_activation import BOOTSTRAP_READY, inspect_bootstrap_lifecycle_schema
from enterprise.migrations.sec_1f0_security_audit import inspect_security_audit_schema
from enterprise.paths import PortableRootInputs, derive_portable_path_roots
from enterprise.release.current_release import read_current_release
from enterprise.roles import ROLE_SUPER_ADMIN


FIXTURE_PASSWORD = "fixture-only-Strong-Password-924!"
RELEASE_ID = "ice-2026.08.4-" + "a" * 12
MANIFEST_SHA = "b" * 64
PAYLOAD_SHA = "c" * 64


class _Manifest:
    release_id = RELEASE_ID
    raw_sha256 = MANIFEST_SHA

    def section(self, name: str) -> dict[str, object]:
        if name == "database_contract":
            return {
                "schema_id": "enterprise-database-contract-v1",
                "migration_ids": [
                    "sec_1b1_role_auth",
                    "sec_1b2_activation",
                    "sec_1f0_security_audit",
                ],
                "migration_compatibility": "same-schema-no-migration",
                "rollback_classification": "code-release-pointer",
                "ops3b_activation_eligible": True,
            }
        if name == "archive":
            return {"filename": f"Infinite-Canvas-Enterprise-{RELEASE_ID}-win-x64.zip"}
        raise KeyError(name)


def _assets() -> VerifiedReleaseAssets:
    return VerifiedReleaseAssets(
        Path("manifest"),
        Path("inventory"),
        Path("archive"),
        _Manifest(),  # type: ignore[arg-type]
        SimpleNamespace(payload_tree_sha256=PAYLOAD_SHA),  # type: ignore[arg-type]
    )


def _fake_materialize(_manifest: Path, _archive: Path, _inventory: Path, destination: Path):
    destination.mkdir(parents=True)
    (destination / "main.py").write_text("# fixture\n", encoding="utf-8")
    (destination / "static").mkdir()
    (destination / "python").mkdir()
    (destination / "python" / "python.exe").write_bytes(b"fixture")
    return SimpleNamespace(result="pass")


def _install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, install_name: str = "install"):
    import enterprise.fresh_install as fresh

    monkeypatch.setattr(fresh, "verify_release_assets", lambda _path: _assets())
    monkeypatch.setattr(fresh, "materialize_release_fixture", _fake_materialize)
    install_root = tmp_path / install_name
    result = install_greenfield(
        release_dir=tmp_path / "assets",
        install_root=install_root,
        username=" first-admin ",
        password=FIXTURE_PASSWORD,
        password_confirmation=FIXTURE_PASSWORD,
        local_app_data_base=tmp_path / "local",
    )
    roots = derive_portable_path_roots(
        PortableRootInputs(install_root, tmp_path / "local", MANIFEST_SHA), RELEASE_ID
    )
    return result, roots


def test_schema_only_initializer_creates_zero_users_and_explicit_legacy_helper(monkeypatch, tmp_path: Path) -> None:
    roots = derive_portable_path_roots(
        PortableRootInputs(tmp_path / "install", tmp_path / "local"), RELEASE_ID
    )
    monkeypatch.setattr(db, "PATH_ROOTS", roots)
    monkeypatch.setattr(db, "DB_PATH", str(roots.DATA_ROOT / "enterprise.db"))
    monkeypatch.setattr(db, "ADMIN_USERNAME", "legacy-admin")
    monkeypatch.setattr(db, "ADMIN_PASSWORD", "legacy-fixture-password")
    db.init_db()
    with sqlite3.connect(db.DB_PATH) as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    created = db.create_legacy_default_admin_explicit()
    assert created["created"] is True
    assert db.get_user_by_username("legacy-admin")["role"] == "admin"


def test_empty_gateway_gate_fails_without_creating_database(tmp_path: Path) -> None:
    roots = derive_portable_path_roots(
        PortableRootInputs(tmp_path / "install", tmp_path / "local"), RELEASE_ID
    )
    database_path = roots.DATA_ROOT / "enterprise.db"
    with pytest.raises(FreshInstallError, match="INSTALL_BOOTSTRAP_REQUIRED") as caught:
        require_gateway_database_ready(roots, database_path)
    assert caught.value.code == "INSTALL_BOOTSTRAP_REQUIRED"
    assert not database_path.exists()


def test_greenfield_install_creates_one_super_admin_and_pointer_last(monkeypatch, tmp_path: Path) -> None:
    import enterprise.fresh_install as fresh

    pointer_calls: list[str] = []
    real_pointer_write = fresh.atomic_write_current_release

    def observed_pointer_write(roots, release, **kwargs):
        assert (roots.CONFIG_ROOT / "enterprise.env").is_file()
        assert (roots.DATA_ROOT / "enterprise.db").is_file()
        assert roots.APP_ROOT.is_dir()
        pointer_calls.append(release.release_id)
        return real_pointer_write(roots, release, **kwargs)

    monkeypatch.setattr(fresh, "atomic_write_current_release", observed_pointer_write)
    result, roots = _install(monkeypatch, tmp_path)
    database_path = roots.DATA_ROOT / "enterprise.db"
    config_path = roots.CONFIG_ROOT / "enterprise.env"
    assert result.user_count == 1
    assert result.active_super_admin_count == 1
    assert result.first_username == "first-admin"
    assert result.pointer_published is True
    assert pointer_calls == [RELEASE_ID]
    assert read_current_release(roots).release_id == RELEASE_ID
    config = config_path.read_text(encoding="utf-8")
    assert "ENTERPRISE_ENV=production" in config
    assert "JWT_SECRET=" in config
    assert "ADMIN_" not in config
    assert FIXTURE_PASSWORD not in config

    with sqlite3.connect(database_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM users").fetchall()
        assert len(rows) == 1
        first = dict(rows[0])
        assert first["role"] == ROLE_SUPER_ADMIN
        assert first["is_admin"] == 1
        assert first["auth_version"] == 1
        assert first["is_active"] == 1
        assert db.verify_password(FIXTURE_PASSWORD, first["password_hash"])
        assert conn.execute(
            "SELECT COUNT(*) FROM users WHERE role='admin'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM users WHERE role='user'"
        ).fetchone()[0] == 0
        audit_contexts = [row[0] for row in conn.execute("SELECT context_json FROM security_audit_events")]
        assert all(FIXTURE_PASSWORD not in value for value in audit_contexts)
        assert all(first["password_hash"] not in value for value in audit_contexts)
        assert conn.execute(
            "SELECT COUNT(*) FROM security_audit_events "
            "WHERE action='security.audit.foundation.activate'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM security_audit_events "
            "WHERE context_json LIKE '%sec_1f0_security_audit%'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM security_audit_events "
            "WHERE action='security.super_admin.bootstrap'"
        ).fetchone()[0] == 1
        password_hash = first["password_hash"]

    for path in roots.INSTALL_ROOT.rglob("*"):
        if not path.is_file() or path == database_path:
            continue
        content = path.read_bytes()
        assert FIXTURE_PASSWORD.encode() not in content
        assert password_hash.encode() not in content

    assert inspect_security_audit_schema(database_path)["is_ready"] is True
    marker = inspect_bootstrap_lifecycle_schema(database_path)
    assert marker["current_state"] == BOOTSTRAP_READY
    assert marker["marker_count"] == 1
    assert marker["marker"]["bootstrap_target_user_id"] == result.first_user_id

    monkeypatch.setattr(db, "PATH_ROOTS", roots)
    monkeypatch.setattr(db, "DB_PATH", str(database_path))
    user = db.get_user_by_username("first-admin")
    effective = db.get_effective_feature_value(user, "system_update")
    assert effective["allowed"] is True
    assert effective["source"] == "super_admin"
    assert require_gateway_database_ready(roots, database_path) == database_path


@pytest.mark.parametrize(
    ("password", "confirmation", "code"),
    [
        ("one", "two", "INSTALL_PASSWORD_CONFIRMATION_MISMATCH"),
        ("admin123", "admin123", "INSTALL_PASSWORD_DEFAULT_FORBIDDEN"),
        ("   ", "   ", "INSTALL_PASSWORD_INVALID"),
    ],
)
def test_password_gate(password: str, confirmation: str, code: str) -> None:
    with pytest.raises(FreshInstallError) as caught:
        validate_first_password(password, confirmation)
    assert caught.value.code == code


def test_confirmation_failure_creates_no_install_state(monkeypatch, tmp_path: Path) -> None:
    import enterprise.fresh_install as fresh

    monkeypatch.setattr(fresh, "verify_release_assets", lambda _path: _assets())
    install_root = tmp_path / "install"
    with pytest.raises(FreshInstallError) as caught:
        install_greenfield(
            release_dir=tmp_path / "assets",
            install_root=install_root,
            username="first-admin",
            password=FIXTURE_PASSWORD,
            password_confirmation="different",
            local_app_data_base=tmp_path / "local",
        )
    assert caught.value.code == "INSTALL_PASSWORD_CONFIRMATION_MISMATCH"
    assert not install_root.exists()


def test_existing_target_and_second_bootstrap_are_denied_without_changes(monkeypatch, tmp_path: Path) -> None:
    import enterprise.fresh_install as fresh

    monkeypatch.setattr(fresh, "verify_release_assets", lambda _path: _assets())
    monkeypatch.setattr(fresh, "materialize_release_fixture", _fake_materialize)
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    sentinel = occupied / "user-file.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(FreshInstallError) as caught:
        install_greenfield(
            release_dir=tmp_path / "assets",
            install_root=occupied,
            username="first-admin",
            password=FIXTURE_PASSWORD,
            password_confirmation=FIXTURE_PASSWORD,
            local_app_data_base=tmp_path / "local",
        )
    assert caught.value.code == "INSTALL_TARGET_NOT_GREENFIELD"
    assert sentinel.read_text(encoding="utf-8") == "keep"

    _result, roots = _install(monkeypatch, tmp_path, install_name="installed")
    before = (roots.DATA_ROOT / "enterprise.db").read_bytes()
    with pytest.raises(FreshInstallError) as caught:
        install_greenfield(
            release_dir=tmp_path / "assets",
            install_root=roots.INSTALL_ROOT,
            username="second-admin",
            password=FIXTURE_PASSWORD,
            password_confirmation=FIXTURE_PASSWORD,
            local_app_data_base=tmp_path / "local",
        )
    assert caught.value.code == "INSTALL_TARGET_NOT_GREENFIELD"
    assert (roots.DATA_ROOT / "enterprise.db").read_bytes() == before


def test_invalid_release_is_denied_before_target_creation(tmp_path: Path) -> None:
    release_dir = tmp_path / "bad-assets"
    release_dir.mkdir()
    install_root = tmp_path / "install"
    with pytest.raises(FreshInstallError) as caught:
        install_greenfield(
            release_dir=release_dir,
            install_root=install_root,
            username="first-admin",
            password=FIXTURE_PASSWORD,
            password_confirmation=FIXTURE_PASSWORD,
            local_app_data_base=tmp_path / "local",
        )
    assert caught.value.code.startswith("INSTALL_RELEASE_")
    assert not install_root.exists()


@pytest.mark.parametrize("preexisting_install_root", [False, True])
def test_failure_before_pointer_cleans_owned_directories_and_retry_succeeds(
    monkeypatch, tmp_path: Path, preexisting_install_root: bool
) -> None:
    import enterprise.fresh_install as fresh

    monkeypatch.setattr(fresh, "verify_release_assets", lambda _path: _assets())
    monkeypatch.setattr(fresh, "materialize_release_fixture", _fake_materialize)
    real_create_database = fresh._create_greenfield_database
    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("fixture pre-publication failure")
        return real_create_database(*args, **kwargs)

    monkeypatch.setattr(fresh, "_create_greenfield_database", fail_once)
    install_root = tmp_path / "install"
    if preexisting_install_root:
        install_root.mkdir()
    with pytest.raises(FreshInstallError) as caught:
        install_greenfield(
            release_dir=tmp_path / "assets",
            install_root=install_root,
            username="first-admin",
            password=FIXTURE_PASSWORD,
            password_confirmation=FIXTURE_PASSWORD,
            local_app_data_base=tmp_path / "local",
        )
    assert caught.value.code == "INSTALL_FAILED"
    assert not (install_root / "config" / "enterprise.env").exists()
    assert not (install_root / "data" / "enterprise.db").exists()
    assert not (install_root / "state" / "current-release.json").exists()
    assert not (install_root / "releases" / RELEASE_ID).exists()
    if preexisting_install_root:
        assert install_root.is_dir()
        assert list(install_root.iterdir()) == []
    else:
        assert not install_root.exists()

    result = install_greenfield(
        release_dir=tmp_path / "assets",
        install_root=install_root,
        username="first-admin",
        password=FIXTURE_PASSWORD,
        password_confirmation=FIXTURE_PASSWORD,
        local_app_data_base=tmp_path / "local",
    )
    assert result.pointer_published is True
    assert attempts == 2


def test_owned_empty_directory_cleanup_preserves_replacement_identity(tmp_path: Path) -> None:
    import enterprise.fresh_install as fresh

    owned = tmp_path / "owned"
    owned.mkdir()
    identity = fresh._identity(owned)
    displaced = tmp_path / "displaced"
    owned.rename(displaced)
    owned.mkdir()

    fresh._remove_owned_empty_directory(owned, identity)

    assert owned.is_dir()
    assert displaced.is_dir()


def test_existing_nonempty_database_schema_ensure_preserves_users(monkeypatch, tmp_path: Path) -> None:
    roots = derive_portable_path_roots(
        PortableRootInputs(tmp_path / "install", tmp_path / "local"), RELEASE_ID
    )
    monkeypatch.setattr(db, "PATH_ROOTS", roots)
    monkeypatch.setattr(db, "DB_PATH", str(roots.DATA_ROOT / "enterprise.db"))
    db.ensure_db_schema()
    with sqlite3.connect(db.DB_PATH) as conn:
        conn.execute(
            "INSERT INTO users (id,username,password_hash,display_name,is_admin,role,auth_version,is_active,created_at) VALUES ('u','existing','x','Existing',0,'user',1,1,1)"
        )
        conn.commit()
    db.ensure_db_schema()
    with sqlite3.connect(db.DB_PATH) as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM users WHERE username='admin'").fetchone()[0] == 0
    assert require_gateway_database_ready(roots, db.DB_PATH) == Path(db.DB_PATH)


def test_cli_has_no_password_argument_or_environment_input() -> None:
    root = Path(__file__).resolve().parents[2]
    tool_source = (root / "tools" / "install_mvp.py").read_text(encoding="utf-8")
    formal_source = (root / "enterprise" / "install_cli.py").read_text(encoding="utf-8")
    assert "add_argument(\"--password" not in tool_source + formal_source
    assert "getpass.getpass" in formal_source
    assert "os.environ" not in tool_source


def test_formal_install_entry_and_development_tool_share_one_cli() -> None:
    root = Path(__file__).resolve().parents[2]
    formal = root / "enterprise" / "install_cli.py"
    wrapper = root / "首次安装企业版.bat"
    assert formal.is_file()
    assert wrapper.is_file()
    formal_source = formal.read_text(encoding="utf-8")
    tool_source = (root / "tools" / "install_mvp.py").read_text(encoding="utf-8")
    assert "def development_main" in formal_source
    assert "from enterprise.install_cli import development_main" in tool_source
    assert "getpass.getpass" not in tool_source
    assert "install_greenfield" not in tool_source


def test_formal_install_wrapper_is_fixed_python_first_install_entry() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "首次安装企业版.bat").read_text(encoding="utf-8-sig").lower()
    assert "%~dp0python\\python.exe" in source
    assert "%~dp0enterprise\\runtime\\fixed_python_preflight.ps1" in source
    assert "%~dp0enterprise\\install_cli.py" in source
    assert source.index("fixed_python_preflight.ps1") < source.index('"%pyexe%" -i -b')
    assert "launcher.py" not in source
    assert "portable start" not in source
    assert "py.exe" not in source
    assert "pip" not in source
    assert "pause" in source


def test_release_asset_discovery_is_bounded_and_supports_extract_all_layout(tmp_path: Path) -> None:
    from enterprise.install_cli import discover_release_asset_directory

    raw_root = tmp_path / "downloads" / "outer" / "raw payload"
    raw_root.mkdir(parents=True)
    asset_root = raw_root.parent.parent
    calls: list[Path] = []

    def verify(candidate: Path) -> VerifiedReleaseAssets:
        calls.append(candidate)
        if candidate == asset_root:
            return _assets()
        raise FreshInstallError("INSTALL_RELEASE_ASSET_SET_INVALID")

    resolved = discover_release_asset_directory(
        raw_root,
        verify=verify,
        input_func=lambda _prompt: pytest.fail("fallback must not be used"),
        emit=lambda _payload: pytest.fail("input-required result must not be emitted"),
    )
    assert resolved == asset_root
    assert calls == [raw_root, raw_root.parent, raw_root.parent.parent]


def test_release_asset_discovery_has_one_interactive_directory_fallback(tmp_path: Path) -> None:
    from enterprise.install_cli import discover_release_asset_directory

    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    supplied = tmp_path / "three-assets"
    supplied.mkdir()
    emitted: list[dict[str, object]] = []
    prompts: list[str] = []

    def verify(candidate: Path) -> VerifiedReleaseAssets:
        if candidate == supplied:
            return _assets()
        raise FreshInstallError("INSTALL_RELEASE_ASSET_SET_INVALID")

    def input_path(prompt: str) -> str:
        prompts.append(prompt)
        return str(supplied)

    resolved = discover_release_asset_directory(
        raw_root,
        verify=verify,
        input_func=input_path,
        emit=emitted.append,
    )
    assert resolved == supplied.absolute()
    assert len(prompts) == 1
    assert emitted == [
        {
            "schema_version": "install-mvp-1-result-v1",
            "status": "input_required",
            "code": "INSTALL_RELEASE_ASSETS_REQUIRED",
        }
    ]
    assert all("PORTABLE_RELEASE_LAYOUT_INVALID" not in json.dumps(item) for item in emitted)


def test_release_asset_verifier_allows_only_a_sibling_extracted_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import enterprise.fresh_install as fresh

    asset_root = tmp_path / "downloads"
    asset_root.mkdir()
    archive_name = f"Infinite-Canvas-Enterprise-{RELEASE_ID}-win-x64.zip"
    (asset_root / fresh.MANIFEST_NAME).write_text("{}", encoding="utf-8")
    (asset_root / fresh.INVENTORY_NAME).write_text("{}", encoding="utf-8")
    (asset_root / archive_name).write_bytes(b"archive")
    (asset_root / "extracted payload").mkdir()
    monkeypatch.setattr(fresh, "read_release_manifest_v2", lambda _path: _Manifest())
    monkeypatch.setattr(
        fresh,
        "verify_release_manifest_v2",
        lambda *_args: SimpleNamespace(payload_tree_sha256=PAYLOAD_SHA),
    )
    monkeypatch.setattr(fresh, "enforce_portable_contract_compatibility", lambda _manifest: None)
    assert fresh.verify_release_assets(asset_root).archive_path.name == archive_name
    (asset_root / "unrelated.txt").write_text("reject", encoding="utf-8")
    with pytest.raises(FreshInstallError, match="INSTALL_RELEASE_ASSET_SET_INVALID"):
        fresh.verify_release_assets(asset_root)


def test_raw_bootstrap_identity_does_not_require_releases_parent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from enterprise import install_cli

    app_root = tmp_path / "raw extracted payload"
    script = app_root / "enterprise" / "install_cli.py"
    python_executable = app_root / "python" / "python.exe"
    script.parent.mkdir(parents=True)
    python_executable.parent.mkdir()
    script.write_text("# fixture", encoding="utf-8")
    python_executable.write_bytes(b"fixture")
    (app_root / "runtime-manifest.json").write_text("{}", encoding="utf-8")
    (app_root / "VERSION").write_text("2026.08.4\n", encoding="utf-8")
    (app_root / "首次安装企业版.bat").write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(python_executable))
    assert install_cli._bootstrap_identity(script) == app_root
    assert app_root.parent.name.casefold() != "releases"


def test_formal_install_uses_known_folder_default_and_returns_install_domain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from enterprise.install_cli import DEFAULT_INSTALL_RELATIVE, run_interactive_install

    forged = tmp_path / "forged-localappdata"
    trusted = tmp_path / "known-folder"
    monkeypatch.setenv("LOCALAPPDATA", str(forged))
    observed: dict[str, object] = {}

    class _Result:
        def public_dict(self) -> dict[str, object]:
            return {"release_id": RELEASE_ID}

    def installer(**kwargs: object) -> _Result:
        observed.update(kwargs)
        return _Result()

    payload = run_interactive_install(
        raw_app_root=tmp_path / "raw",
        release_dir=tmp_path / "assets",
        input_func=lambda _prompt: "first-admin",
        password_func=lambda _prompt: FIXTURE_PASSWORD,
        known_folder_resolver=lambda: trusted,
        verify=lambda _path: _assets(),
        installer=installer,
    )
    assert observed["install_root"] == trusted / DEFAULT_INSTALL_RELATIVE
    assert observed["local_app_data_base"] == trusted
    assert forged not in Path(observed["install_root"]).parents
    assert payload["status"] == "succeeded"
    assert payload["code"] == "INSTALL_SUCCEEDED"
    assert "PORTABLE_RELEASE_LAYOUT_INVALID" not in json.dumps(payload)


def test_formal_cli_checks_isolation_and_identity_before_enterprise_import() -> None:
    source = (Path(__file__).resolve().parents[1] / "install_cli.py").read_text(encoding="utf-8")
    main_body = source[source.index("def main(") :]
    isolation = main_body.index("if not _python_isolation_ready():")
    sanitize = main_body.index("_sanitize_python_environment()")
    bootstrap = main_body.index("_bootstrap_identity(Path(__file__))")
    execute = main_body.index("return _execute(raw_app_root=app_root)")
    assert isolation < sanitize < bootstrap < execute
    assert "from enterprise." not in source[: source.index("def run_interactive_install(")]
    assert "shell=True" not in source


@pytest.mark.parametrize(
    ("flags", "expected_code", "bundled_python_present"),
    [
        (("-s", "-B"), "INSTALL_PYTHON_ISOLATION_REQUIRED", False),
        (("-I", "-B"), "INSTALL_PYTHON_MISSING", False),
        (("-I", "-B"), "INSTALL_PYTHON_IDENTITY_INVALID", True),
    ],
)
def test_direct_formal_installer_fails_in_install_domain_before_business_import(
    tmp_path: Path,
    flags: tuple[str, ...],
    expected_code: str,
    bundled_python_present: bool,
) -> None:
    source = Path(__file__).resolve().parents[1] / "install_cli.py"
    script = tmp_path / "raw" / "enterprise" / "install_cli.py"
    script.parent.mkdir(parents=True)
    script.write_bytes(source.read_bytes())
    expected_python = script.parent.parent / "python" / "python.exe"
    if bundled_python_present:
        expected_python.parent.mkdir()
        expected_python.write_bytes(b"fixture identity only")

    # A bundled-looking Python outside the raw APP_ROOT models a contaminated
    # long-lived checkout without making the declared bootstrap precondition
    # depend on repository-local ignored files or the current working directory.
    ambient = tmp_path / "ambient checkout"
    (ambient / "python").mkdir(parents=True)
    (ambient / "python" / "python.exe").write_bytes(b"ambient fixture")
    completed = subprocess.run(
        [sys.executable, *flags, str(script)],
        cwd=ambient,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        timeout=20,
        shell=False,
        check=False,
    )
    assert completed.returncode == 2
    assert completed.stderr == ""
    assert json.loads(completed.stdout) == {
        "schema_version": "install-mvp-1-result-v1",
        "status": "blocked",
        "code": expected_code,
    }
    assert "PORTABLE_RELEASE_LAYOUT_INVALID" not in completed.stdout
