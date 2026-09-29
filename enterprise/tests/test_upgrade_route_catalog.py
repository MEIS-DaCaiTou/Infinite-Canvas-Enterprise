import hashlib
import sqlite3
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from enterprise.migrations.versioned import schema_objects, schema_snapshot_sha256
from enterprise.ops.update.models import ReleaseMetadataV2
from enterprise.ops.update.route_catalog import inspect_installed_route_state, read_release_routes, verify_target_route_schema
from enterprise.ops.update.upgrade_routes import ReleaseState, UpgradeRouteError
from enterprise.release.release_manifest_v2 import canonical_json
from enterprise.tests.test_upgrade_routes import _document, _sha


def _metadata(route_raw: bytes):
    return ReleaseMetadataV2(
        provider_release_id="123", tag_name="2026.09.7", version="2026.09.7",
        published_at="2026-09-28T00:00:00Z", release_notes="test",
        manifest_url="manifest", manifest_size_bytes=8,
        inventory_url="inventory", inventory_size_bytes=1,
        archive_url="archive", archive_size_bytes=1, prerelease=True,
        upgrade_routes_url="routes", upgrade_routes_size_bytes=len(route_raw),
        upgrade_routes_sha256=hashlib.sha256(route_raw).hexdigest(),
    )


def test_route_asset_is_bound_to_manifest_and_github_digest(monkeypatch):
    from enterprise.ops.update import route_catalog

    raw, _ = _document(
        "ice-097", "2026.09.7", "2", "ice-096", "2026.09.6", "1",
        channel="development",
    )
    manifest = SimpleNamespace(
        raw_sha256=_sha("2"), release_id="ice-097",
        section=lambda _name: {"release_version": "2026.09.7"},
    )
    monkeypatch.setattr(route_catalog, "parse_release_manifest_v2_bytes", lambda _raw: manifest)

    class Client:
        def read_bytes(self, url, **_kwargs):
            return b"manifest" if url == "manifest" else raw

    provider = SimpleNamespace(
        http_client=Client(), release_v2_asset_request_headers=lambda _url: {},
    )
    declaration = read_release_routes(provider, _metadata(raw))
    assert declaration.target.release_id == "ice-097"
    bad = _metadata(raw)
    bad = bad.__class__(**{**bad.__dict__, "upgrade_routes_sha256": _sha("9")})
    with pytest.raises(UpgradeRouteError, match="UPGRADE_ROUTE_DIGEST_MISMATCH"):
        read_release_routes(provider, bad)


def test_installed_database_must_match_exact_source_schema(tmp_path: Path, monkeypatch):
    from enterprise.ops.update import route_catalog

    database = tmp_path / "enterprise.db"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE canvas (id TEXT PRIMARY KEY)")
        objects = schema_objects(conn)
        sha = schema_snapshot_sha256(conn)
    evidence_raw = canonical_json({"objects": objects})
    evidence_path = tmp_path / "database-schema.json"
    evidence_path.write_bytes(evidence_raw)
    manifest = SimpleNamespace(
        release_id="ice-096", raw_sha256=_sha("1"),
        section=lambda name: (
            {"release_version": "2026.09.6"} if name == "identity" else
            {"schema_snapshot_path": "database-schema.json", "schema_snapshot_sha256": hashlib.sha256(evidence_raw).hexdigest()}
        ),
    )
    monkeypatch.setattr(route_catalog, "_database_evidence", lambda *_args: {"objects": objects})
    state = inspect_installed_route_state(app_root=tmp_path, database_path=database, manifest=manifest)
    assert state.database_schema_sha256 == sha
    evidence_path.write_bytes(evidence_raw + b" ")
    with pytest.raises(UpgradeRouteError, match="UPGRADE_ROUTE_SOURCE_DATABASE_UNVERIFIED"):
        inspect_installed_route_state(app_root=tmp_path, database_path=database, manifest=manifest)
    evidence_path.write_bytes(evidence_raw)
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE unexpected (id INTEGER)")
    with pytest.raises(UpgradeRouteError, match="UPGRADE_ROUTE_SOURCE_DATABASE_UNVERIFIED"):
        inspect_installed_route_state(app_root=tmp_path, database_path=database, manifest=manifest)


def test_update_preview_labels_direct_missing_and_intermediate_paths(monkeypatch):
    from enterprise import update_api

    installed = ReleaseState("ice-096", "2026.09.6", _sha("1"), _sha("a"), 1, "stable")
    _, bridge = _document(
        "ice-097", "2026.09.7", "2", "ice-096", "2026.09.6", "1",
        target_updater_contract=2,
    )
    _, final = _document(
        "ice-098", "2026.09.8", "3", "ice-097", "2026.09.7", "2",
        target_schema="b", minimum_updater_contract=2,
        migration_mode="versioned-forward-migration",
    )
    releases = [
        SimpleNamespace(provider_release_id="bridge", version="2026.09.7", prerelease=False, upgrade_routes_url="bridge"),
        SimpleNamespace(provider_release_id="final", version="2026.09.8", prerelease=False, upgrade_routes_url="final"),
        SimpleNamespace(provider_release_id="old", version="2026.09.9", prerelease=False, upgrade_routes_url=None),
    ]
    monkeypatch.setattr(update_api, "inspect_installed_route_state", lambda **_kwargs: installed)
    monkeypatch.setattr(update_api, "read_release_routes", lambda _provider, release: {"bridge": bridge, "final": final}[release.provider_release_id])
    pointer = SimpleNamespace(release=SimpleNamespace(release_id="ice-096", manifest_sha256=_sha("1")))
    result = update_api._route_previews(object(), releases, SimpleNamespace(release_id="ice-096", raw_sha256=_sha("1")), pointer)
    assert result["bridge"]["route_status"] == "direct"
    assert result["final"]["route_status"] == "requires_intermediate"
    assert [step["release_id"] for step in result["final"]["upgrade_path"]] == ["ice-097", "ice-098"]
    assert result["old"]["route_status"] == "route_missing"


def test_preview_rejects_pointer_and_manifest_disagreement(monkeypatch):
    from enterprise import update_api

    release = SimpleNamespace(provider_release_id="bridge", upgrade_routes_url="route")
    monkeypatch.setattr(update_api, "read_release_routes", lambda *_args: pytest.fail("no route fetch expected"))
    pointer = SimpleNamespace(release=SimpleNamespace(release_id="ice-other", manifest_sha256=_sha("1")))
    result = update_api._route_previews(object(), [release], SimpleNamespace(release_id="ice-096", raw_sha256=_sha("1")), pointer)
    assert result["bridge"]["route_status"] == "source_unverified"


def test_target_archive_schema_must_match_route(tmp_path: Path):
    import zipfile

    _, routes = _document(
        "ice-097", "2026.09.7", "2", "ice-096", "2026.09.6", "1",
        target_schema="a", channel="development",
    )
    objects = [{"name": "canvas", "sql": "CREATE TABLE canvas (id TEXT PRIMARY KEY)", "type": "table"}]
    evidence = canonical_json({"objects": objects})
    archive_path = tmp_path / "release.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("release/database-schema.json", evidence)
    manifest = SimpleNamespace(section=lambda name: (
        {"root_prefix": "release"} if name == "archive" else
        {"schema_snapshot_path": "database-schema.json", "schema_snapshot_sha256": hashlib.sha256(evidence).hexdigest()}
    ))
    with pytest.raises(UpgradeRouteError, match="UPGRADE_ROUTE_TARGET_SCHEMA_MISMATCH"):
        verify_target_route_schema(archive_path=archive_path, manifest=manifest, routes=routes)
    actual_sha = hashlib.sha256(canonical_json(objects)).hexdigest()
    verified = replace(routes, target=replace(routes.target, database_schema_sha256=actual_sha))
    verify_target_route_schema(archive_path=archive_path, manifest=manifest, routes=verified)


def test_higher_version_without_route_is_not_offered_as_update(monkeypatch):
    from enterprise import update_api

    candidate = SimpleNamespace(
        provider_release_id="unrouted", tag_name="2026.09.8", version="2026.09.8",
        published_at="2026-09-28T00:00:00Z", release_notes="test", prerelease=False,
        upgrade_routes_url=None,
    )
    monkeypatch.setattr(update_api, "_provider", lambda: SimpleNamespace(list_release_v2_candidates=lambda **_kwargs: [candidate]))
    monkeypatch.setattr(update_api, "read_current_release_result_from_state_root", lambda _root: SimpleNamespace(release=SimpleNamespace(release_id="ice-096", manifest_sha256=_sha("1"))))
    monkeypatch.setattr(update_api, "read_release_manifest_v2", lambda _path: SimpleNamespace(release_id="ice-096", raw_sha256=_sha("1"), section=lambda _section: {"release_version": "2026.09.6"}))
    monkeypatch.setattr(update_api, "inspect_installed_route_state", lambda **_kwargs: ReleaseState("ice-096", "2026.09.6", _sha("1"), _sha("a"), 1, "stable"))
    result = update_api._check_update_sync()
    assert result["update_available"] is False
    assert result["latest"] is None
    assert result["releases"][0]["route_status"] == "route_missing"


def test_online_prepare_rejects_unrouted_release_before_any_asset_download(monkeypatch):
    from enterprise import update_api
    from enterprise.ops.update.mvp import UpdateMvpError

    class Store:
        def __init__(self, _roots):
            pass

        def assert_no_unresolved_recovery(self):
            pass

    monkeypatch.setattr(update_api, "UpdateJobStore", Store)
    monkeypatch.setattr(update_api, "_provider", lambda: object())
    monkeypatch.setattr(
        update_api, "_metadata_by_id",
        lambda _provider, _release_id: SimpleNamespace(upgrade_routes_url=None),
    )
    with pytest.raises(UpdateMvpError, match="SYSTEM_UPDATE_ROUTE_UNDECLARED"):
        update_api._prepare_update_sync("actor", "unrouted")


def test_online_prepare_rejects_pointer_manifest_mismatch_before_download(monkeypatch):
    from enterprise import update_api
    from enterprise.ops.update.mvp import UpdateMvpError

    class Store:
        def __init__(self, _roots):
            pass

        def assert_no_unresolved_recovery(self):
            pass

    monkeypatch.setattr(update_api, "UpdateJobStore", Store)
    monkeypatch.setattr(update_api, "_provider", lambda: object())
    monkeypatch.setattr(update_api, "_metadata_by_id", lambda *_args: SimpleNamespace(upgrade_routes_url="routes"))
    pointer = SimpleNamespace(release=SimpleNamespace(release_id="ice-096", manifest_sha256=_sha("1")))
    monkeypatch.setattr(update_api, "read_current_release_result_from_state_root", lambda _root: pointer)
    monkeypatch.setattr(update_api, "read_release_manifest_v2", lambda _path: SimpleNamespace(release_id="ice-096", raw_sha256=_sha("2")))
    monkeypatch.setattr(update_api, "read_release_routes", lambda *_args: pytest.fail("route fetch must not occur"))
    with pytest.raises(UpdateMvpError, match="SYSTEM_UPDATE_ROUTE_SOURCE_UNVERIFIED"):
        update_api._prepare_update_sync("actor", "candidate")
