"""Build a small, exact-source upgrade-route asset beside a verified Release v2.

The input JSON contains an array of source Release roots and audited updater
contract numbers. It must be reviewed with the release; the tool does not
invent compatibility from a higher display version.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from enterprise.ops.update.upgrade_routes import (  # noqa: E402
    AllowedSource, ROUTE_ASSET_NAME, ReleaseState, build_upgrade_routes,
)
from enterprise.release.release_manifest_v2 import (  # noqa: E402
    canonical_json, read_release_manifest_v2, verify_materialized_release,
    verify_release_manifest_v2,
)


def _schema_sha(evidence: bytes, expected_sha: str) -> str:
    if hashlib.sha256(evidence).hexdigest() != expected_sha or len(evidence) > 1024 * 1024:
        raise ValueError("database evidence does not match the Release manifest")
    payload = json.loads(evidence)
    if type(payload) is not dict or type(payload.get("objects")) is not list:
        raise ValueError("database evidence is incomplete")
    schema_sha = hashlib.sha256(canonical_json(payload["objects"])).hexdigest()
    if payload.get("schema_objects_sha256", schema_sha) != schema_sha:
        raise ValueError("database schema object hash is inconsistent")
    return schema_sha


def _schema_from_materialized(root: Path, manifest) -> str:
    contract = manifest.section("database_contract")
    relative = contract["schema_snapshot_path"]
    return _schema_sha(
        (root / Path(*relative.split("/"))).read_bytes(),
        contract["schema_snapshot_sha256"],
    )


def _schema_from_archive(archive: Path, manifest) -> str:
    name = manifest.section("archive")["root_prefix"] + "/" + manifest.section("database_contract")["schema_snapshot_path"]
    with zipfile.ZipFile(archive) as zipped:
        info = zipped.getinfo(name)
        if info.file_size > 1024 * 1024:
            raise ValueError("database evidence is oversized")
        return _schema_sha(zipped.read(info), manifest.section("database_contract")["schema_snapshot_sha256"])


def build(*, target_manifest: Path, target_archive: Path, target_inventory: Path,
          sources_json: Path, target_updater_contract: int, channel: str, output: Path) -> dict[str, object]:
    verify_release_manifest_v2(target_manifest, target_archive, target_inventory)
    manifest = read_release_manifest_v2(target_manifest)
    target_schema_sha = _schema_from_archive(target_archive, manifest)
    sources = json.loads(sources_json.read_text(encoding="utf-8"))
    if type(sources) is not list or not sources:
        raise ValueError("at least one exact source Release is required")
    expected_mode = manifest.section("database_contract")["migration_compatibility"]
    allowed = []
    for item in sources:
        if type(item) is not dict or set(item) != {"app_root", "minimum_updater_contract", "migration_mode"}:
            raise ValueError("source route declaration is invalid")
        root = Path(item["app_root"])
        source_manifest = read_release_manifest_v2(root / "release-manifest.json")
        inventory = root / source_manifest.section("release_payload")["inventory_path"]
        verify_materialized_release(root, inventory_path=inventory)
        if item["migration_mode"] != expected_mode:
            raise ValueError("route mode does not match target database contract")
        allowed.append(AllowedSource(
            source_manifest.release_id,
            source_manifest.section("identity")["release_version"],
            source_manifest.raw_sha256,
            _schema_from_materialized(root, source_manifest),
            item["minimum_updater_contract"],
            item["migration_mode"],
        ))
    target = ReleaseState(
        manifest.release_id, manifest.section("identity")["release_version"],
        manifest.raw_sha256, target_schema_sha, target_updater_contract, channel,
    )
    content = build_upgrade_routes(target, allowed)
    if output.exists() or output.name != ROUTE_ASSET_NAME:
        raise ValueError("output must be a new upgrade-routes-v1.json file")
    output.write_bytes(content)
    return {
        "result": "pass", "asset": str(output), "sha256": hashlib.sha256(content).hexdigest(),
        "target_release_id": target.release_id,
        "source_release_ids": [item.release_id for item in allowed],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-manifest", type=Path, required=True)
    parser.add_argument("--target-archive", type=Path, required=True)
    parser.add_argument("--target-inventory", type=Path, required=True)
    parser.add_argument("--sources-json", type=Path, required=True)
    parser.add_argument("--target-updater-contract", type=int, required=True)
    parser.add_argument("--channel", choices=("stable", "development"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(**vars(args)), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
