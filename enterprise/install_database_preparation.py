"""Empty WAL residue qualification for the owned offline upgrade transaction.

This is not database recovery. Nonempty WAL, rollback journals and unfamiliar
files remain blocked. The caller owns the existing upgrade lease/fence before
invoking prepare; only SQLite may remove its empty runtime files.
"""
import os
import sqlite3
from contextlib import contextmanager

from enterprise import install_cache as files, install_lifecycle as lifecycle
from enterprise.migrations.versioned import DataMigrationError, _checkpoint_quiescent_database


def _residue(database):
    journal = database.with_name(database.name + "-journal")
    files._safe(journal, missing=True)
    if files._exists(journal):
        lifecycle._fail("INSTALL_LIFECYCLE_DATABASE_RECOVERY_REQUIRED")
    result = {}
    for suffix, size in (("-wal", 0), ("-shm", 32768)):
        path = database.with_name(database.name + suffix)
        files._safe(path, missing=True)
        token = files._file(path) if files._exists(path) else None
        if token is not None and token["size_bytes"] != size:
            lifecycle._fail("INSTALL_LIFECYCLE_DATABASE_RECOVERY_REQUIRED")
        result[suffix] = token
    return result if any(result.values()) else None


def _proof(roots):
    database = roots.DATA_ROOT / "enterprise.db"
    residue = _residue(database)
    if residue is None:
        return None
    if not all(residue.values()):
        lifecycle._fail("INSTALL_LIFECYCLE_DATABASE_RECOVERY_REQUIRED")
    token = files._file(database)
    with files._io(database).open("rb") as stream:
        header = stream.read(100)
    if header[:16] != b"SQLite format 3\x00" or header[18:20] != b"\x02\x02":
        lifecycle._fail("INSTALL_LIFECYCLE_DATABASE_RECOVERY_REQUIRED")
    return {"database": token, "sidecars": residue}


def inspect(roots):
    """Read-only preflight; qualification never opens a mutable connection."""
    try:
        return _inspect(roots)
    except OSError as exc:
        raise lifecycle.LifecycleError("INSTALL_LIFECYCLE_DATABASE_UNPROVEN") from exc


def _inspect(roots):
    proof = _proof(roots)
    if proof is None:
        return lifecycle._database_inspection(roots), None
    if not hasattr(sqlite3.Connection, "setconfig") or not hasattr(sqlite3, "SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE"):
        lifecycle._fail("INSTALL_UPGRADE_DATABASE_PREPARATION_UNSUPPORTED")
    metadata = lifecycle._immutable_database_inspection(roots)
    if _proof(roots) != proof:
        lifecycle._fail("INSTALL_LIFECYCLE_CHANGED")
    return metadata, proof


def prepare(roots, proof, contract):
    """Called only under the durable offline upgrade's stopped-owner fence.

    The proof binds the main database bytes and exact sidecar objects. If a
    prior invocation finished before process death, only wholly absent logs and
    unchanged main bytes are accepted. Unknown intermediate states stay fenced.
    """
    try:
        _prepare(roots, proof, contract)
    except (OSError, DataMigrationError) as exc:
        raise lifecycle.LifecycleError("INSTALL_UPGRADE_DATABASE_PREPARATION_REQUIRED") from exc


def _prepare(roots, proof, contract):
    if not hasattr(sqlite3.Connection, "setconfig") or not hasattr(sqlite3, "SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE"):
        lifecycle._fail("INSTALL_UPGRADE_DATABASE_PREPARATION_UNSUPPORTED")
    database = roots.DATA_ROOT / "enterprise.db"
    if files._file(database) != proof["database"]:
        lifecycle._fail("INSTALL_UPGRADE_DATABASE_CHANGED")
    observed = _proof(roots)
    if observed is not None:
        if (observed["database"] != proof["database"] or any(
                observed["sidecars"][suffix][key] != proof["sidecars"][suffix][key]
                for suffix in ("-wal", "-shm") for key in ("identity", "size_bytes"))):
            lifecycle._fail("INSTALL_UPGRADE_DATABASE_CHANGED")
        _checkpoint_quiescent_database(database, checkpoint_guard=lambda conn: _sqlite_guard(conn, roots, proof))
    if (files._file(database) != proof["database"]
            or lifecycle._database_contract(roots) != contract):
        lifecycle._fail("INSTALL_UPGRADE_DATABASE_CHANGED")


def _checkpoint(stage):
    """Owned-copy tests only; no deployment fault-injection setting."""


@contextmanager
def _sqlite_guard(conn, roots, proof):
    # A failed guard must not checkpoint implicitly when this connection closes.
    # The fixed CP314 Runtime supplies this control; older tooling fails closed.
    conn.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE, True)
    conn.execute("PRAGMA wal_autocheckpoint=0")
    # Open normal WAL/SHM before exclusive mode; otherwise SQLite uses heap SHM
    # and would leave the original on-disk SHM behind when it closes.
    conn.execute("PRAGMA schema_version").fetchone()
    conn.execute("PRAGMA locking_mode=EXCLUSIVE")
    conn.execute("BEGIN EXCLUSIVE")
    conn.rollback()  # Exclusive locking mode retains the lock until close.
    database = roots.DATA_ROOT / "enterprise.db"
    for suffix in ("-wal", "-shm"):
        path = database.with_name(database.name + suffix)
        files._safe(path)
        # SHM lock bytes cannot be read through a second Windows handle while
        # SQLite owns them. Bind its file object and length, not mutable locks.
        with files._io(path).open("rb") as stream:
            info = os.fstat(stream.fileno())
            expected = proof["sidecars"][suffix]
            if (not files.stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or files._fd_identity(stream) != expected["identity"]
                    or info.st_size != expected["size_bytes"]):
                lifecycle._fail("INSTALL_LIFECYCLE_DATABASE_RECOVERY_REQUIRED")
    journal = database.with_name(database.name + "-journal")
    files._safe(journal, missing=True)
    if files._exists(journal) or files._file(database) != proof["database"]:
        lifecycle._fail("INSTALL_UPGRADE_DATABASE_CHANGED")
    _checkpoint("database_locked")
    yield
    if files._file(database) != proof["database"]:
        lifecycle._fail("INSTALL_UPGRADE_DATABASE_CHANGED")
    # Only a successful, unchanged, exclusively held empty checkpoint may enable
    # SQLite's normal close cleanup. Errors retain WAL/SHM and the parent fence.
    conn.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE, False)
