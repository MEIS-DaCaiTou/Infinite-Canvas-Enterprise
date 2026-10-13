"""A UI target is not an upgrade path until every declared hop matches."""

import json

import pytest

from enterprise.ops.update.upgrade_routes import (
    ReleaseState,
    UpgradeRouteError,
    parse_upgrade_routes,
    plan_upgrade_path,
)


def _sha(char: str) -> str:
    return char * 64


def _document(
    target_id: str,
    target_version: str,
    target_sha: str,
    source_id: str,
    source_version: str,
    source_sha: str,
    *,
    target_schema: str = "a",
    source_schema: str = "a",
    channel: str = "stable",
    minimum_updater_contract: int = 1,
    target_updater_contract: int = 1,
    migration_mode: str = "same-schema-no-migration",
):
    payload = {
        "schema_version": "enterprise-upgrade-routes-v1",
        "target": {
            "release_id": target_id,
            "version": target_version,
            "manifest_sha256": _sha(target_sha),
            "database_schema_sha256": _sha(target_schema),
            "updater_contract": target_updater_contract,
            "channel": channel,
        },
        "allowed_sources": [{
            "release_id": source_id,
            "version": source_version,
            "manifest_sha256": _sha(source_sha),
            "database_schema_sha256": _sha(source_schema),
            "minimum_updater_contract": minimum_updater_contract,
            "migration_mode": migration_mode,
        }],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return raw, parse_upgrade_routes(
        raw, expected_manifest_sha256=_sha(target_sha),
        expected_release_id=target_id, expected_version=target_version,
        expected_channel=channel,
    )


def test_exact_release_graph_requires_intermediate_updater_and_schema_identity():
    installed = ReleaseState("ice-095", "2026.09.5", _sha("1"), _sha("a"), 1, "stable")
    _, bridge = _document("ice-096", "2026.09.6", "2", "ice-095", "2026.09.5", "1", target_updater_contract=2)
    _, target = _document(
        "ice-098", "2026.09.8", "3", "ice-096", "2026.09.6", "2",
        target_schema="b", minimum_updater_contract=2, target_updater_contract=2,
        migration_mode="versioned-forward-migration",
    )
    assert tuple(item.release_id for item in plan_upgrade_path(installed, "ice-098", [target, bridge])) == ("ice-096", "ice-098")
    assert plan_upgrade_path(installed, "ice-098", [target]) is None
    changed_database = ReleaseState("ice-095", "2026.09.5", _sha("1"), _sha("c"), 1, "stable")
    assert plan_upgrade_path(changed_database, "ice-098", [target, bridge]) is None


def test_stable_path_never_uses_development_intermediate():
    installed = ReleaseState("ice-096", "2026.09.6", _sha("1"), _sha("a"), 1, "stable")
    _, development = _document(
        "ice-097-dev", "2026.09.7", "2", "ice-096", "2026.09.6", "1",
        channel="development", target_updater_contract=2,
    )
    _, target = _document(
        "ice-098", "2026.09.8", "3", "ice-097-dev", "2026.09.7", "2",
        minimum_updater_contract=2,
    )
    assert plan_upgrade_path(installed, "ice-098", [development, target]) is None
    assert tuple(item.release_id for item in plan_upgrade_path(installed, "ice-098", [development, target], allow_development=True)) == ("ice-097-dev", "ice-098")


def test_shortest_direct_path_when_target_explicitly_supports_installed_release():
    installed = ReleaseState("ice-096", "2026.09.6", _sha("1"), _sha("a"), 2, "stable")
    _, bridge = _document("ice-097", "2026.09.7", "2", "ice-096", "2026.09.6", "1")
    _, direct = _document(
        "ice-098", "2026.09.8", "3", "ice-096", "2026.09.6", "1",
        target_schema="b", minimum_updater_contract=2,
        migration_mode="versioned-forward-migration",
    )
    assert tuple(item.release_id for item in plan_upgrade_path(installed, "ice-098", [bridge, direct])) == ("ice-098",)


@pytest.mark.parametrize("mutate", [
    lambda payload: payload["target"].update(channel="unexpected"),
    lambda payload: payload["allowed_sources"][0].update(migration_mode="invalid"),
    lambda payload: payload["allowed_sources"][0].update(minimum_updater_contract=True),
    lambda payload: payload["allowed_sources"][0].update(database_schema_sha256="wrong"),
    lambda payload: payload["target"].update(release_id="ice-wrong"),
])
def test_bad_declaration_fails_closed(mutate):
    raw, _ = _document("ice-097", "2026.09.7", "2", "ice-096", "2026.09.6", "1")
    payload = json.loads(raw)
    mutate(payload)
    changed = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(UpgradeRouteError):
        parse_upgrade_routes(changed, expected_manifest_sha256=_sha("2"), expected_release_id="ice-097", expected_version="2026.09.7", expected_channel="stable")


def test_noncanonical_or_wrong_manifest_is_rejected():
    raw, _ = _document("ice-097", "2026.09.7", "2", "ice-096", "2026.09.6", "1")
    with pytest.raises(UpgradeRouteError, match="UPGRADE_ROUTE_NONCANONICAL"):
        parse_upgrade_routes(raw + b"\n", expected_manifest_sha256=_sha("2"), expected_release_id="ice-097", expected_version="2026.09.7", expected_channel="stable")
    with pytest.raises(UpgradeRouteError, match="UPGRADE_ROUTE_TARGET_MISMATCH"):
        parse_upgrade_routes(raw, expected_manifest_sha256=_sha("9"), expected_release_id="ice-097", expected_version="2026.09.7", expected_channel="stable")
