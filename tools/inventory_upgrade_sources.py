#!/usr/bin/env python3
"""Verify immutable historical assets and generate the native upgrade catalog.

This tool reads release archives, not an installed customer's database.  It
does not infer compatibility from a version number or silently trust an old
download.  Its output must be reviewed and tested before shipping a tool.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(ROOT))

from enterprise.release.release_manifest_v2 import canonical_json, read_release_manifest_v2, verify_release_manifest_v2
from enterprise.path_safety import assert_no_reparse_ancestors

CATALOG_SCHEMA = "enterprise-native-upgrade-catalog-v1"


def inventory(asset_root: Path) -> dict[str, object]:
    records = json.loads(subprocess.run(
        ["gh", "api", "repos/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/releases?per_page=100"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout)
    public = {item["tag_name"]: item for item in records if not item["draft"]}
    sources = []
    for folder in sorted(asset_root.iterdir()):
        if not folder.is_dir():
            continue
        tag = folder.name
        record = public.get(tag)
        if record is None:
            raise ValueError("INVENTORY_PUBLIC_RELEASE_MISSING")
        assets = {item["name"]: item for item in record["assets"]}
        manifest_path = folder / "ops-release-manifest-v2.json"
        inventory_path = folder / "release-payload-inventory.json"
        manifest = read_release_manifest_v2(manifest_path)
        archive_path = folder / manifest.section("archive")["filename"]
        for path in (manifest_path, inventory_path, archive_path):
            expected = assets[path.name]
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if expected.get("digest") != "sha256:" + digest or path.stat().st_size != expected["size"]:
                raise ValueError("INVENTORY_PUBLIC_ASSET_MISMATCH")
        verification = verify_release_manifest_v2(manifest_path, archive_path, inventory_path)
        prefix = manifest.section("archive")["root_prefix"] + "/"
        with zipfile.ZipFile(archive_path) as archive:
            evidence = json.loads(archive.read(prefix + manifest.section("database_contract")["schema_snapshot_path"]))
            runtime = json.loads(archive.read(prefix + manifest.section("runtime")["runtime_manifest_path"]))
        python_file = next(item for item in runtime["files"] if item["path"] == "python.exe")
        sources.append({
            "release_id": manifest.release_id,
            "version": tag,
            "channel": "development" if record["prerelease"] else "stable",
            "manifest_sha256": manifest.raw_sha256,
            "python_sha256": python_file["sha256"],
            "archive_filename": archive_path.name,
            "archive_sha256": manifest.section("archive")["sha256"],
            "payload_tree_sha256": verification.payload_tree_sha256,
            "database_evidence_sha256": manifest.section("database_contract")["schema_snapshot_sha256"],
            "database_objects_sha256": hashlib.sha256(canonical_json(evidence["objects"])).hexdigest(),
            "object_count": len(evidence["objects"]),
            "schema_version": evidence.get("schema_version"),
        })
    return {"schema_version": CATALOG_SCHEMA, "sources": sources}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-catalog", type=Path)
    args = parser.parse_args()
    args.asset_root = args.asset_root.resolve()
    args.output = args.output.resolve()
    assert_no_reparse_ancestors(args.asset_root)
    assert_no_reparse_ancestors(args.output, allow_missing=True)
    if args.output.is_relative_to(args.asset_root) or args.output.is_relative_to(ROOT):
        raise ValueError('INVENTORY_OUTPUT_OVERLAPS_INPUT')
    document = inventory(args.asset_root)
    if args.expected_catalog is not None:
        assert_no_reparse_ancestors(args.expected_catalog)
        if canonical_json(json.loads(args.expected_catalog.read_bytes())) != canonical_json(document):
            raise ValueError('INVENTORY_REVIEWED_CATALOG_MISMATCH')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as target:
        target.write(canonical_json(document))
    print(json.dumps({"catalog": str(args.output), "sources": document["sources"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
