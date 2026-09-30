"""Read-only recognition of the exact security-activated legacy extension.

The immutable 09.6 release evidence describes the 18-object upgrade baseline.
Its first-install and security-activation flows can legitimately add the ten
SEC-1F0/SEC-1B2 objects without creating versioned migration metadata.  This
module recognizes *only* that exact extension; it never removes or rewrites an
audit object to make an upgrade appear compatible. The online default remains
bound to 09.6. An offline native tool may additionally supply a reviewed exact
source approval after independently verifying its immutable release catalog.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from enterprise.migrations.sec_1b2_activation import (
    BOOTSTRAP_READY,
    ensure_bootstrap_lifecycle_schema_in_transaction,
    inspect_bootstrap_lifecycle_connection,
)
from enterprise.migrations.versioned import (
    STATE_MISSING,
    inspect_schema_metadata_connection,
    schema_objects,
    schema_snapshot_sha256,
)
from enterprise.security_audit import (
    SECURITY_AUDIT_READY,
    ensure_security_audit_schema_in_transaction,
    inspect_security_audit_connection,
)


SOURCE_RELEASE_ID = "ice-2026.09.6-8f65c5cd328f"
SOURCE_MANIFEST_SHA256 = "e183631d52bbd0955477dfc6f6540aea99a0e173bb11821544a1db926a2cb85d"


class LegacySecurityVariantError(ValueError):
    """The installed database is not the exact supported 09.6 variant."""


def canonical_security_variant_objects(
    baseline_objects: Sequence[dict[str, str]],
) -> list[dict[str, str]]:
    """Build canonical DDL in memory, never against the installed database."""
    if len(baseline_objects) != 18:
        raise LegacySecurityVariantError("BASELINE_SCHEMA_INVALID")
    memory = sqlite3.connect(":memory:")
    try:
        for kind in ("table", "index", "trigger", "view"):
            for item in baseline_objects:
                if item.get("type") == kind:
                    memory.execute(item["sql"])
        if schema_objects(memory) != list(baseline_objects):
            raise LegacySecurityVariantError("BASELINE_SCHEMA_INVALID")
        memory.commit()
        memory.execute("BEGIN IMMEDIATE")
        ensure_security_audit_schema_in_transaction(memory)
        ensure_bootstrap_lifecycle_schema_in_transaction(memory)
        result = schema_objects(memory)
        memory.rollback()
        if len(result) != 28:
            raise LegacySecurityVariantError("SECURITY_VARIANT_SCHEMA_INVALID")
        return result
    except sqlite3.Error as exc:
        raise LegacySecurityVariantError("SECURITY_VARIANT_SCHEMA_INVALID") from exc
    finally:
        memory.close()


def inspect_096_security_variant(
    conn: sqlite3.Connection,
    *,
    baseline_objects: Sequence[dict[str, str]],
    source_release_id: str,
    source_manifest_sha256: str,
) -> dict[str, object]:
    """Return only non-sensitive evidence for an exact 28-object source.

    The caller must open the real database read-only.  Marker content and audit
    event rows are intentionally not returned.
    """
    return inspect_approved_security_variant(
        conn, baseline_objects=baseline_objects,
        source_release_id=source_release_id, source_manifest_sha256=source_manifest_sha256,
        approved_source=(SOURCE_RELEASE_ID, SOURCE_MANIFEST_SHA256),
    )


def inspect_approved_security_variant(
    conn: sqlite3.Connection,
    *,
    baseline_objects: Sequence[dict[str, str]],
    source_release_id: str,
    source_manifest_sha256: str,
    approved_source: tuple[str, str],
) -> dict[str, object]:
    """Recognize the shared security shape for an independently pinned source.

    Only the verified offline native tool supplies this approval.  Online
    callers still default to no exceptional source; the old 09.6 API retains
    its original exact identity.  Object counts alone never authorize a hop.
    """
    if (source_release_id, source_manifest_sha256) != approved_source:
        raise LegacySecurityVariantError("SOURCE_RELEASE_UNSUPPORTED")
    if inspect_schema_metadata_connection(conn).get("current_state") != STATE_MISSING:
        raise LegacySecurityVariantError("SOURCE_SCHEMA_METADATA_UNEXPECTED")
    if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise LegacySecurityVariantError("SOURCE_DATABASE_INTEGRITY_FAILED")
    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise LegacySecurityVariantError("SOURCE_DATABASE_FOREIGN_KEY_FAILED")
    expected = canonical_security_variant_objects(baseline_objects)
    if schema_objects(conn) != expected:
        raise LegacySecurityVariantError("SOURCE_SECURITY_SCHEMA_MISMATCH")
    audit = inspect_security_audit_connection(conn)
    bootstrap = inspect_bootstrap_lifecycle_connection(conn)
    if audit.get("current_state") != SECURITY_AUDIT_READY or not audit.get("event_count"):
        raise LegacySecurityVariantError("SOURCE_SECURITY_AUDIT_INVALID")
    if (
        bootstrap.get("current_state") != BOOTSTRAP_READY
        or bootstrap.get("marker_count") != 1
        or bootstrap.get("marker_data_valid") is not True
    ):
        raise LegacySecurityVariantError("SOURCE_SECURITY_BOOTSTRAP_INVALID")
    return {
        "variant": (
            "ice-2026.09.6-security-activated-v1"
            if approved_source == (SOURCE_RELEASE_ID, SOURCE_MANIFEST_SHA256)
            else "legacy-security-activated-v1"
        ),
        "schema_objects_sha256": schema_snapshot_sha256(conn),
        "object_count": 28,
        "audit_event_count": audit["event_count"],
        "bootstrap_marker_count": 1,
    }
