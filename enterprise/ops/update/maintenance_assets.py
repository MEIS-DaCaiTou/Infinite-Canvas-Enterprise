"""Release-bound native maintenance assets; no customer data or publication."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from enterprise.install_entry import verify_entry_bundle
from enterprise.ops.update.download import atomic_download
from enterprise.ops.update.mvp import UpdateMvpError
from enterprise.release.release_manifest_v2 import canonical_json

ASSET_NAME = "maintenance-tools-v1.json"
SCHEMA = "enterprise-maintenance-tools-v1"
FILENAMES = ("InfiniteCanvas.exe", "native-entry-build-record.json",
             "InfiniteCanvasSetup.exe", "unsigned-installer-build-record.json")
LIMITS = (4 * 1024 * 1024, 16384, 1024 * 1024 * 1024, 16384)


def verify_tools(directory: Path, manifest, *, expected_digest: str | None = None) -> dict:
    from enterprise import install_cache as files
    raw = files._io(files._safe(directory / ASSET_NAME)).read_bytes()
    try:
        document = json.loads(raw)
        identity = manifest.section("enterprise_source")
        if (len(raw) > 16384 or raw != canonical_json(document)
                or (expected_digest is not None and hashlib.sha256(raw).hexdigest() != expected_digest)
                or set(document) != {"schema_version", "release_id", "manifest_sha256", "source_commit",
                                      "source_tree", "uninstaller_contract", "files"}
                or document["schema_version"] != SCHEMA or document["release_id"] != manifest.release_id
                or document["manifest_sha256"] != manifest.raw_sha256
                or document["source_commit"] != identity["commit"] or document["source_tree"] != identity["tree"]
                or type(document["uninstaller_contract"]) is not int or document["uninstaller_contract"] != 1
                or type(document["files"]) is not dict or set(document["files"]) != set(FILENAMES)):
            raise ValueError()
        for name, limit in zip(FILENAMES, LIMITS):
            specification = document["files"][name]
            token = files._file(directory / name)
            if (type(specification) is not dict or set(specification) != {"sha256", "size_bytes"}
                    or type(specification["size_bytes"]) is not int or not 1 <= specification["size_bytes"] <= limit
                    or {key: token[key] for key in specification} != specification):
                raise ValueError()
        verify_entry_bundle(directory, commit=identity["commit"], tree=identity["tree"])
        build = json.loads(files._io(directory / FILENAMES[3]).read_bytes())
        setup = document["files"][FILENAMES[2]]
        if (build.get("schema_version") != "install-ux-1-unsigned-build-record-v1"
                or build.get("enterprise_commit") != identity["commit"] or build.get("enterprise_tree") != identity["tree"]
                or build.get("release_id") != manifest.release_id
                or build.get("unsigned_setup_sha256") != setup["sha256"]
                or build.get("unsigned_setup_size_bytes") != setup["size_bytes"]
                or build.get("unsigned_builds_identical") is not True
                or not files._io(directory / FILENAMES[2]).read_bytes()[:2] == b"MZ"):
            raise ValueError()
        return document
    except (ValueError, KeyError, TypeError) as exc:
        raise UpdateMvpError("SYSTEM_UPDATE_MAINTENANCE_TOOLS_UNVERIFIED") from exc


def download_tools(provider, metadata, directory: Path, manifest) -> str | None:
    if metadata.maintenance_tools_url is None:
        return None  # Immutable historical releases keep their original native tools.
    directory.mkdir(exist_ok=False)
    atomic_download(provider.http_client, url=metadata.maintenance_tools_url,
                    destination=directory / ASSET_NAME, maximum_bytes=16384,
                    expected_size_bytes=metadata.maintenance_tools_size_bytes,
                    expected_sha256=metadata.maintenance_tools_sha256,
                    headers=provider.release_v2_asset_request_headers(metadata.maintenance_tools_url))
    raw = (directory / ASSET_NAME).read_bytes()
    try:
        records = json.loads(raw)["files"]
        assets = {name: (url, size) for name, url, size in metadata.maintenance_assets}
        if set(records) != set(FILENAMES) or set(assets) != set(FILENAMES):
            raise ValueError()
        for name, limit in zip(FILENAMES, LIMITS):
            url, size = assets[name]
            if size != records[name]["size_bytes"]:
                raise ValueError()
            atomic_download(provider.http_client, url=url, destination=directory / name, maximum_bytes=limit,
                            expected_size_bytes=size, expected_sha256=records[name]["sha256"],
                            headers=provider.release_v2_asset_request_headers(url))
    except (ValueError, KeyError, TypeError) as exc:
        raise UpdateMvpError("SYSTEM_UPDATE_MAINTENANCE_TOOLS_UNVERIFIED") from exc
    verify_tools(directory, manifest, expected_digest=metadata.maintenance_tools_sha256)
    return metadata.maintenance_tools_sha256
