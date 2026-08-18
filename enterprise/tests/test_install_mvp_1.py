from __future__ import annotations

import json
import sqlite3
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


def test_failure_before_pointer_removes_only_operation_owned_state(monkeypatch, tmp_path: Path) -> None:
    import enterprise.fresh_install as fresh

    monkeypatch.setattr(fresh, "verify_release_assets", lambda _path: _assets())
    monkeypatch.setattr(fresh, "materialize_release_fixture", _fake_materialize)
    monkeypatch.setattr(
        fresh,
        "append_security_audit_event",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("fixture audit failure")),
    )
    install_root = tmp_path / "install"
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
    assert not (install_root / "data" / "enterprise.db").exists()
    assert not (install_root / "state" / "current-release.json").exists()
    assert not (install_root / "releases" / RELEASE_ID).exists()


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
    source = (Path(__file__).resolve().parents[2] / "tools" / "install_mvp.py").read_text(encoding="utf-8")
    assert "add_argument(\"--password" not in source
    assert "getpass.getpass" in source
    assert "os.environ" not in source
