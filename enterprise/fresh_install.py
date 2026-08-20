"""Minimal local-only Greenfield installation orchestration.

This module deliberately does not migrate, repair, adopt, or overwrite an
existing installation.  It consumes the already-closed three-asset Release
contract and publishes the current-release pointer only after configuration
and the canonical first database are durable.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from enterprise import db
from enterprise.migrations.sec_1b1_role_auth import ROLE_AUTH_READY, inspect_role_auth_schema
from enterprise.migrations.sec_1b2_activation import (
    BOOTSTRAP_READY,
    ensure_bootstrap_lifecycle_schema_in_transaction,
    inspect_bootstrap_lifecycle_connection,
    inspect_bootstrap_lifecycle_schema,
)
from enterprise.migrations.sec_1f0_security_audit import (
    inspect_security_audit_schema,
)
from enterprise.path_safety import PathSafetyError, assert_no_reparse_ancestors, lexical_path_state
from enterprise.paths import (
    PathRoots,
    PathRootsError,
    PortableRootInputs,
    derive_portable_path_roots,
    resolve_database_path,
    validate_path_roots_for_use,
)
from enterprise.release.current_release import (
    CurrentRelease,
    SCHEMA_VERSION as CURRENT_RELEASE_SCHEMA,
    atomic_write_current_release,
)
from enterprise.release.release_manifest_v2 import (
    ReleaseManifestV2,
    ReleaseVerificationResult,
    enforce_portable_contract_compatibility,
    materialize_release_fixture,
    read_release_manifest_v2,
    verify_release_manifest_v2,
)
from enterprise.roles import ROLE_SUPER_ADMIN
from enterprise.security_audit import (
    SECURITY_AUDIT_READY,
    append_security_audit_event,
    ensure_security_audit_schema_in_transaction,
)


MANIFEST_NAME = "ops-release-manifest-v2.json"
INVENTORY_NAME = "release-payload-inventory.json"
CONFIG_NAME = "enterprise.env"
DATABASE_NAME = "enterprise.db"
INSTALL_LOCK_NAME = "install-mvp-active.lock"
MAX_RELEASE_DIRECTORY_ENTRIES = 1024
DEFAULT_PASSWORDS = frozenset({"admin123", "change-me-before-production"})
REQUIRED_BUSINESS_TABLES = frozenset(
    {
        "users",
        "user_canvas_map",
        "user_project_map",
        "user_conversation_map",
        "user_resource_map",
        "user_canvas_task_map",
        "user_task_map",
        "user_history_map",
        "user_asset_object_map",
        "usage_logs",
        "enterprise_feature_flags",
        "enterprise_user_feature_overrides",
    }
)


class FreshInstallError(RuntimeError):
    """Stable, path-free Greenfield installation failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class VerifiedReleaseAssets:
    manifest_path: Path
    inventory_path: Path
    archive_path: Path
    manifest: ReleaseManifestV2
    verification: ReleaseVerificationResult


@dataclass(frozen=True)
class FreshInstallResult:
    release_id: str
    manifest_sha256: str
    payload_tree_sha256: str
    root_identity: str
    first_user_id: str
    first_username: str
    user_count: int
    active_super_admin_count: int
    bootstrap_marker_count: int
    bootstrap_audit_event: bool
    sqlite_integrity_check: str
    pointer_published: bool

    def public_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


def _fail(code: str, cause: BaseException | None = None) -> None:
    error = FreshInstallError(code)
    if cause is None:
        raise error
    raise error from cause


def _identity(path: Path) -> tuple[int, int]:
    value = os.stat(path, follow_symlinks=False)
    return value.st_dev, value.st_ino


def _remove_owned_file(path: Path, identity: tuple[int, int] | None) -> None:
    if identity is None:
        return
    try:
        if _identity(path) == identity:
            path.unlink()
    except OSError:
        pass


def _remove_owned_directory(path: Path, identity: tuple[int, int] | None) -> None:
    if identity is None:
        return
    try:
        if _identity(path) == identity:
            shutil.rmtree(path)
    except OSError:
        pass


def _remove_owned_empty_directory(path: Path, identity: tuple[int, int] | None) -> None:
    """Remove only the same operation-created directory when it is empty."""

    if identity is None:
        return
    try:
        if _identity(path) == identity:
            path.rmdir()
    except OSError:
        pass


def _ensure_operation_directory(
    path: Path,
    created: dict[Path, tuple[int, int]],
    *,
    parents: bool = False,
) -> None:
    """Create and identity-bind missing directories for rollback cleanup."""

    candidates = [path]
    if parents:
        candidates = []
        current = path
        while lexical_path_state(current) == "missing":
            candidates.append(current)
            if current == current.parent:
                break
            current = current.parent
        candidates.reverse()
    try:
        for candidate in candidates:
            try:
                candidate.mkdir()
            except FileExistsError:
                pass
            else:
                created[candidate] = _identity(candidate)
            assert_no_reparse_ancestors(candidate)
            if lexical_path_state(candidate) != "regular" or not candidate.is_dir():
                _fail("INSTALL_TARGET_UNSAFE")
        assert_no_reparse_ancestors(path)
        if lexical_path_state(path) != "regular" or not path.is_dir():
            _fail("INSTALL_TARGET_UNSAFE")
    except FreshInstallError:
        raise
    except (OSError, PathSafetyError) as exc:
        _fail("INSTALL_TARGET_UNSAFE", exc)


def _normalized_username(value: object) -> str:
    if not isinstance(value, str):
        _fail("INSTALL_USERNAME_INVALID")
    normalized = value.strip()
    if not normalized or len(normalized) > 128 or any(ord(char) < 32 for char in normalized):
        _fail("INSTALL_USERNAME_INVALID")
    return normalized


def validate_first_password(password: object, confirmation: object) -> str:
    if not isinstance(password, str) or not password or password.isspace():
        _fail("INSTALL_PASSWORD_INVALID")
    if password != confirmation:
        _fail("INSTALL_PASSWORD_CONFIRMATION_MISMATCH")
    if password.casefold() in {item.casefold() for item in DEFAULT_PASSWORDS}:
        _fail("INSTALL_PASSWORD_DEFAULT_FORBIDDEN")
    return password


def verify_release_assets(release_dir: Path) -> VerifiedReleaseAssets:
    release_dir = Path(release_dir)
    try:
        assert_no_reparse_ancestors(release_dir)
        if not release_dir.is_dir():
            _fail("INSTALL_RELEASE_ASSET_SET_INVALID")
        files: list[Path] = []
        for index, item in enumerate(release_dir.iterdir()):
            if index >= MAX_RELEASE_DIRECTORY_ENTRIES:
                _fail("INSTALL_RELEASE_ASSET_SET_INVALID")
            state = lexical_path_state(item)
            if state != "regular" or item.is_symlink():
                _fail("INSTALL_RELEASE_ASSET_SET_INVALID")
            if item.is_file():
                files.append(item)
            elif not item.is_dir():
                _fail("INSTALL_RELEASE_ASSET_SET_INVALID")
        file_names = {item.name for item in files}
        if MANIFEST_NAME not in file_names or INVENTORY_NAME not in file_names:
            _fail("INSTALL_RELEASE_ASSET_SET_INVALID")
        manifest_path = release_dir / MANIFEST_NAME
        inventory_path = release_dir / INVENTORY_NAME
        manifest = read_release_manifest_v2(manifest_path)
        archive_path = release_dir / str(manifest.section("archive")["filename"])
        expected = {MANIFEST_NAME, INVENTORY_NAME, archive_path.name}
        if file_names != expected or len(files) != len(expected):
            _fail("INSTALL_RELEASE_ASSET_SET_INVALID")
        verification = verify_release_manifest_v2(manifest_path, archive_path, inventory_path)
        enforce_portable_contract_compatibility(manifest)
        return VerifiedReleaseAssets(
            manifest_path, inventory_path, archive_path, manifest, verification
        )
    except FreshInstallError:
        raise
    except (OSError, PathSafetyError) as exc:
        _fail("INSTALL_RELEASE_ASSET_SET_INVALID", exc)
    except Exception as exc:
        _fail("INSTALL_RELEASE_VERIFICATION_FAILED", exc)


def _require_greenfield_install_root(install_root: Path) -> None:
    install_root = Path(os.path.abspath(os.fspath(install_root)))
    try:
        assert_no_reparse_ancestors(install_root, allow_missing=True)
        state = lexical_path_state(install_root)
        if state == "reparse" or state == "inspection_failed":
            _fail("INSTALL_TARGET_UNSAFE")
        if state == "regular":
            if not install_root.is_dir() or any(install_root.iterdir()):
                _fail("INSTALL_TARGET_NOT_GREENFIELD")
    except FreshInstallError:
        raise
    except (OSError, PathSafetyError) as exc:
        _fail("INSTALL_TARGET_UNSAFE", exc)


def require_gateway_database_ready(roots: PathRoots, configured_db_path: str | Path | None) -> Path:
    """Read-only pre-start gate; it never creates a path or SQLite file."""
    try:
        database_path = resolve_database_path(roots, configured_db_path)
        state = lexical_path_state(database_path)
        if state == "missing":
            _fail("INSTALL_BOOTSTRAP_REQUIRED")
        if state in {"reparse", "inspection_failed"}:
            _fail("INSTALL_DATABASE_INVALID")
        assert_no_reparse_ancestors(database_path)
    except FreshInstallError:
        raise
    except (OSError, PathSafetyError, PathRootsError) as exc:
        _fail("INSTALL_DATABASE_INVALID", exc)
    if not database_path.is_file():
        _fail("INSTALL_BOOTSTRAP_REQUIRED")
    try:
        if database_path.stat().st_size <= 0:
            _fail("INSTALL_BOOTSTRAP_REQUIRED")
        inspection = inspect_role_auth_schema(database_path)
        if inspection.get("current_state") not in {"SCHEMA_LEGACY", ROLE_AUTH_READY}:
            _fail("INSTALL_DATABASE_INVALID")
        if int(inspection.get("user_count") or 0) < 1:
            _fail("INSTALL_BOOTSTRAP_REQUIRED")
    except FreshInstallError:
        raise
    except Exception as exc:
        _fail("INSTALL_DATABASE_INVALID", exc)
    return database_path


def _validate_release_database_contract(manifest: ReleaseManifestV2) -> None:
    contract = manifest.section("database_contract")
    required_migrations = {
        "sec_1b1_role_auth",
        "sec_1b2_activation",
        "sec_1f0_security_audit",
    }
    migrations = set(contract.get("migration_ids") or [])
    if (
        contract.get("schema_id") != "enterprise-database-contract-v1"
        or contract.get("migration_compatibility") != "same-schema-no-migration"
        or contract.get("rollback_classification") != "code-release-pointer"
        or contract.get("ops3b_activation_eligible") is not True
        or not required_migrations.issubset(migrations)
    ):
        _fail("INSTALL_DATABASE_CONTRACT_UNSUPPORTED")


def _create_greenfield_database(
    database_path: Path,
    *,
    expected_identity: tuple[int, int],
    username: str,
    password: str,
    manifest: ReleaseManifestV2,
    operation_id: str,
) -> dict[str, object]:
    _validate_release_database_contract(manifest)
    try:
        if (
            _identity(database_path) != expected_identity
            or lexical_path_state(database_path) != "regular"
            or not database_path.is_file()
            or database_path.stat().st_size != 0
        ):
            _fail("INSTALL_TARGET_NOT_GREENFIELD")
    except FreshInstallError:
        raise
    except OSError as exc:
        _fail("INSTALL_DATABASE_WRITE_FAILED", exc)
    user_id = uuid.uuid4().hex
    password_hash = db._hash_password(password)
    now = int(time.time() * 1000)
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=DELETE")
        db.ensure_db_schema_in_connection(conn)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            INSERT INTO main.users (
                id, username, password_hash, display_name, is_admin, role,
                auth_version, role_updated_at, role_updated_by, is_active, created_at
            ) VALUES (?, ?, ?, ?, 1, ?, 1, ?, ?, 1, ?)
            """,
            (user_id, username, password_hash, username, ROLE_SUPER_ADMIN, now, user_id, now),
        )
        if cursor.rowcount != 1:
            _fail("INSTALL_FIRST_USER_WRITE_FAILED")
        conn.execute(
            """
            INSERT INTO main.enterprise_feature_flags (
                feature_key, enabled, description, updated_by, updated_at
            ) VALUES ('system_update', 1, ?, ?, ?)
            """,
            ("Greenfield first-install update capability", user_id, now),
        )
        ensure_security_audit_schema_in_transaction(conn)
        ensure_bootstrap_lifecycle_schema_in_transaction(conn)
        marker = (
            1,
            now,
            user_id,
            user_id,
            operation_id,
            "local-first-install",
            now,
        )
        inserted = conn.execute(
            """
            INSERT INTO main.security_governance_bootstrap (
                singleton_id, bootstrap_completed_at, bootstrap_completed_by,
                bootstrap_target_user_id, bootstrap_operation_id,
                bootstrap_actor_label, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            marker,
        )
        if inserted.rowcount != 1:
            _fail("INSTALL_BOOTSTRAP_MARKER_WRITE_FAILED")
        event = append_security_audit_event(
            action="security.super_admin.bootstrap",
            risk_level="L3",
            result="success",
            actor_type="local_operator",
            operation_id=operation_id,
            actor_user_id=user_id,
            actor_role=ROLE_SUPER_ADMIN,
            actor_label="local-first-install",
            target_type="user",
            target_id=user_id,
            reason="Create the first Greenfield super administrator",
            context={
                "bootstrap_kind": "greenfield",
                "role_after": ROLE_SUPER_ADMIN,
                "user_count": 1,
            },
            connection=conn,
        )
        conn.commit()
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM main.sqlite_master WHERE type='table'"
            ).fetchall()
        }
        users = conn.execute(
            "SELECT id, username, password_hash, is_admin, role, auth_version, is_active FROM main.users"
        ).fetchall()
        marker_inspection = inspect_bootstrap_lifecycle_connection(conn)
        if integrity != "ok" or not REQUIRED_BUSINESS_TABLES.issubset(tables):
            _fail("INSTALL_DATABASE_INTEGRITY_FAILED")
        if len(users) != 1:
            _fail("INSTALL_FIRST_USER_INVARIANT_FAILED")
        first = users[0]
        if (
            first[0] != user_id
            or first[1] != username
            or first[3] != 1
            or first[4] != ROLE_SUPER_ADMIN
            or first[5] != 1
            or first[6] != 1
            or not db.verify_password(password, first[2])
        ):
            _fail("INSTALL_FIRST_USER_INVARIANT_FAILED")
        if (
            marker_inspection.get("current_state") != BOOTSTRAP_READY
            or marker_inspection.get("marker_count") != 1
            or marker_inspection.get("marker", {}).get("bootstrap_target_user_id") != user_id
        ):
            _fail("INSTALL_BOOTSTRAP_MARKER_INVALID")
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()

    try:
        role = inspect_role_auth_schema(database_path)
        audit = inspect_security_audit_schema(database_path)
        lifecycle = inspect_bootstrap_lifecycle_schema(database_path)
        if role.get("current_state") != ROLE_AUTH_READY:
            _fail("INSTALL_ROLE_AUTH_SCHEMA_INVALID")
        if audit.get("current_state") != SECURITY_AUDIT_READY:
            _fail("INSTALL_SECURITY_AUDIT_INVALID")
        if lifecycle.get("current_state") != BOOTSTRAP_READY:
            _fail("INSTALL_BOOTSTRAP_MARKER_INVALID")
        with database_path.open("r+b") as handle:
            os.fsync(handle.fileno())
    except FreshInstallError:
        raise
    except Exception as exc:
        _fail("INSTALL_DATABASE_VERIFICATION_FAILED", exc)
    return {
        "user_id": user_id,
        "username": username,
        "bootstrap_event_id": event["event_id"],
        "integrity": integrity,
    }


def _write_config_temp(path: Path) -> tuple[str, tuple[int, int]]:
    jwt_secret = secrets.token_urlsafe(48)
    encoded = f"ENTERPRISE_ENV=production\nJWT_SECRET={jwt_secret}\n".encode("utf-8")
    identity: tuple[int, int] | None = None
    try:
        with path.open("xb") as handle:
            identity = _identity(path)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        return jwt_secret, identity
    except OSError as exc:
        _remove_owned_file(path, identity)
        _fail("INSTALL_CONFIG_WRITE_FAILED", exc)


def _create_database_temp(path: Path) -> tuple[int, int]:
    identity: tuple[int, int] | None = None
    try:
        with path.open("xb") as handle:
            identity = _identity(path)
            handle.flush()
            os.fsync(handle.fileno())
        return identity
    except OSError as exc:
        _remove_owned_file(path, identity)
        _fail("INSTALL_DATABASE_WRITE_FAILED", exc)


def _validate_config(path: Path, expected_secret: str) -> None:
    try:
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf") or len(raw) > 4096:
            _fail("INSTALL_CONFIG_VERIFICATION_FAILED")
        records: dict[str, str] = {}
        for line in raw.decode("utf-8").splitlines():
            key, separator, value = line.partition("=")
            if not separator or key in records:
                _fail("INSTALL_CONFIG_VERIFICATION_FAILED")
            records[key] = value
        if (
            records != {"ENTERPRISE_ENV": "production", "JWT_SECRET": expected_secret}
            or len(expected_secret) < 48
            or expected_secret.startswith("PLEASE_CHANGE")
        ):
            _fail("INSTALL_CONFIG_VERIFICATION_FAILED")
    except FreshInstallError:
        raise
    except (OSError, UnicodeError) as exc:
        _fail("INSTALL_CONFIG_VERIFICATION_FAILED", exc)


def _publish_new_file(source: Path, target: Path, code: str) -> tuple[int, int]:
    if target.exists() or target.is_symlink():
        _fail("INSTALL_TARGET_NOT_GREENFIELD")
    target_identity: tuple[int, int] | None = None
    try:
        os.link(source, target)
        target_identity = _identity(target)
        source.unlink()
        return target_identity
    except FileExistsError as exc:
        _fail("INSTALL_TARGET_NOT_GREENFIELD", exc)
    except OSError as exc:
        _remove_owned_file(target, target_identity)
        _fail(code, exc)


def install_greenfield(
    *,
    release_dir: Path,
    install_root: Path,
    username: str,
    password: str,
    password_confirmation: str,
    local_app_data_base: Path,
) -> FreshInstallResult:
    """Install one verified Release into a genuinely empty target."""
    normalized_username = _normalized_username(username)
    accepted_password = validate_first_password(password, password_confirmation)
    assets = verify_release_assets(Path(release_dir))
    _require_greenfield_install_root(Path(install_root))

    inputs = PortableRootInputs(
        install_root=Path(install_root),
        local_app_data_base=Path(local_app_data_base),
        expected_manifest_sha256=assets.manifest.raw_sha256,
    )
    roots = derive_portable_path_roots(inputs, assets.manifest.release_id)
    validate_path_roots_for_use(roots)

    release_identity: tuple[int, int] | None = None
    config_temp_identity: tuple[int, int] | None = None
    database_temp_identity: tuple[int, int] | None = None
    config_identity: tuple[int, int] | None = None
    database_identity: tuple[int, int] | None = None
    lock_identity: tuple[int, int] | None = None
    config_temp = roots.CONFIG_ROOT / f"{CONFIG_NAME}.{uuid.uuid4().hex}.new"
    database_temp = roots.DATA_ROOT / f"{DATABASE_NAME}.{uuid.uuid4().hex}.new"
    config_final = roots.CONFIG_ROOT / CONFIG_NAME
    database_final = roots.DATA_ROOT / DATABASE_NAME
    lock_path = roots.STATE_ROOT / INSTALL_LOCK_NAME
    pointer_path = roots.STATE_ROOT / "current-release.json"
    operation_id = f"install-{uuid.uuid4().hex}"
    committed = False
    created_directories: dict[Path, tuple[int, int]] = {}
    try:
        _ensure_operation_directory(roots.INSTALL_ROOT, created_directories, parents=True)
        if any(roots.INSTALL_ROOT.iterdir()):
            _fail("INSTALL_TARGET_NOT_GREENFIELD")
        for directory in (
            roots.RELEASE_ROOT,
            roots.DATA_ROOT,
            roots.CONFIG_ROOT,
            roots.STATE_ROOT,
        ):
            _ensure_operation_directory(directory, created_directories)
        for candidate in (config_final, database_final, pointer_path):
            if candidate.exists() or candidate.is_symlink():
                _fail("INSTALL_TARGET_NOT_GREENFIELD")
        with lock_path.open("xb") as lock:
            lock.write((json.dumps({"operation_id": operation_id}, sort_keys=True) + "\n").encode("utf-8"))
            lock.flush()
            os.fsync(lock.fileno())
        lock_identity = _identity(lock_path)

        materialize_release_fixture(
            assets.manifest_path,
            assets.archive_path,
            assets.inventory_path,
            roots.APP_ROOT,
        )
        release_identity = _identity(roots.APP_ROOT)
        jwt_secret, config_temp_identity = _write_config_temp(config_temp)
        _validate_config(config_temp, jwt_secret)
        database_temp_identity = _create_database_temp(database_temp)
        database = _create_greenfield_database(
            database_temp,
            expected_identity=database_temp_identity,
            username=normalized_username,
            password=accepted_password,
            manifest=assets.manifest,
            operation_id=operation_id,
        )
        config_identity = _publish_new_file(config_temp, config_final, "INSTALL_CONFIG_PUBLISH_FAILED")
        database_identity = _publish_new_file(database_temp, database_final, "INSTALL_DATABASE_PUBLISH_FAILED")

        pointer = CurrentRelease(
            schema_version=CURRENT_RELEASE_SCHEMA,
            release_id=assets.manifest.release_id,
            app_root_relative=f"releases/{assets.manifest.release_id}",
            manifest_sha256=assets.manifest.raw_sha256,
            activated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            previous_release_id=None,
        )
        atomic_write_current_release(
            roots,
            pointer,
            expected_manifest_sha256=assets.manifest.raw_sha256,
        )
        committed = True
        _remove_owned_file(lock_path, lock_identity)
        lock_identity = None
        return FreshInstallResult(
            release_id=assets.manifest.release_id,
            manifest_sha256=assets.manifest.raw_sha256,
            payload_tree_sha256=assets.verification.payload_tree_sha256,
            root_identity=roots.root_identity,
            first_user_id=str(database["user_id"]),
            first_username=normalized_username,
            user_count=1,
            active_super_admin_count=1,
            bootstrap_marker_count=1,
            bootstrap_audit_event=bool(database["bootstrap_event_id"]),
            sqlite_integrity_check=str(database["integrity"]),
            pointer_published=True,
        )
    except FreshInstallError:
        raise
    except Exception as exc:
        _fail("INSTALL_FAILED", exc)
    finally:
        accepted_password = ""
        _remove_owned_file(config_temp, config_temp_identity)
        _remove_owned_file(database_temp, database_temp_identity)
        _remove_owned_file(lock_path, lock_identity)
        if not committed and not pointer_path.exists():
            _remove_owned_file(config_final, config_identity)
            _remove_owned_file(database_final, database_identity)
            _remove_owned_directory(roots.APP_ROOT, release_identity)
            for directory in sorted(
                created_directories,
                key=lambda item: len(item.parts),
                reverse=True,
            ):
                _remove_owned_empty_directory(directory, created_directories[directory])
