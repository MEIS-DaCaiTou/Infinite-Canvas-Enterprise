"""Assemble verified build outputs for online updates. Does not publish."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from enterprise.ops.update.maintenance_assets import ASSET_NAME, FILENAMES, SCHEMA, verify_tools
from enterprise.release.release_manifest_v2 import canonical_json, read_release_manifest_v2


def build(*, release_dir: Path, native_dir: Path, setup_dir: Path, output: Path):
    manifest = read_release_manifest_v2(release_dir / "ops-release-manifest-v2.json")
    identity = manifest.section("enterprise_source")
    record = json.loads((setup_dir / FILENAMES[3]).read_bytes())
    name = record["unsigned_setup_filename"]
    if Path(name).name != name or "/" in name or "\\" in name:
        raise ValueError("invalid Setup filename")
    output.mkdir(parents=True, exist_ok=False)
    sources = (native_dir / FILENAMES[0], native_dir / FILENAMES[1], setup_dir / name, setup_dir / FILENAMES[3])
    records = {}
    for name, source in zip(FILENAMES, sources):
        shutil.copyfile(source, output / name)
        raw = (output / name).read_bytes()
        records[name] = {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
    document = {"schema_version": SCHEMA, "release_id": manifest.release_id,
                "manifest_sha256": manifest.raw_sha256, "source_commit": identity["commit"],
                "source_tree": identity["tree"], "uninstaller_contract": 1, "files": records}
    (output / ASSET_NAME).write_bytes(canonical_json(document))
    verify_tools(output, manifest)
    return document


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("release-dir", "native-dir", "setup-dir", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(build(release_dir=arguments.release_dir, native_dir=arguments.native_dir,
                           setup_dir=arguments.setup_dir, output=arguments.output), sort_keys=True))
