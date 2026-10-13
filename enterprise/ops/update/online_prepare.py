"""Prepare every immutable hop before the single maintenance confirmation."""
from __future__ import annotations
from dataclasses import asdict
import hashlib
import os
from pathlib import Path
import uuid

from enterprise import install_cache as files
from enterprise.ops.update.download import atomic_download
from enterprise.ops.update.maintenance_assets import download_tools
from enterprise.ops.update.mvp import MAX_ARCHIVE_BYTES, UpdateMvpError, UpdateMvpService, stage_verified_release
from enterprise.ops.update.route_catalog import read_release_routes, verify_target_route_schema
from enterprise.ops.update.sequence import SCHEMA, input_root, require_sequence_controller
from enterprise.ops.update.upgrade_routes import plan_upgrade_path
from enterprise.release.release_manifest_v2 import MANIFEST_MAX_BYTES, INVENTORY_MAX_BYTES, read_release_manifest_v2


def download_step(provider, metadata, route, destination):
    destination.mkdir(exist_ok=False)
    manifest_path = destination / "ops-release-manifest-v2.json"
    archive = destination / "release.zip"
    inventory = destination / "release-payload-inventory.json"
    atomic_download(provider.http_client, url=metadata.manifest_url, destination=manifest_path,
        maximum_bytes=MANIFEST_MAX_BYTES, expected_size_bytes=metadata.manifest_size_bytes,
        expected_sha256=route.target.manifest_sha256,
        headers=provider.release_v2_asset_request_headers(metadata.manifest_url))
    manifest = read_release_manifest_v2(manifest_path)
    if manifest.section("identity")["release_version"] != metadata.version:
        raise UpdateMvpError("SYSTEM_UPDATE_PROVIDER_MANIFEST_IDENTITY_MISMATCH")
    declaration = manifest.section("archive")
    if declaration["size_bytes"] != metadata.archive_size_bytes:
        raise UpdateMvpError("SYSTEM_UPDATE_PROVIDER_MANIFEST_SIZE_MISMATCH")
    atomic_download(provider.http_client, url=metadata.inventory_url, destination=inventory,
        maximum_bytes=INVENTORY_MAX_BYTES, expected_size_bytes=metadata.inventory_size_bytes,
        expected_sha256=manifest.section("release_payload")["inventory_sha256"],
        headers=provider.release_v2_asset_request_headers(metadata.inventory_url))
    atomic_download(provider.http_client, url=metadata.archive_url, destination=archive,
        maximum_bytes=MAX_ARCHIVE_BYTES, expected_size_bytes=declaration["size_bytes"],
        expected_sha256=declaration["sha256"], headers=provider.release_v2_asset_request_headers(metadata.archive_url))
    verify_target_route_schema(archive_path=archive, manifest=manifest, routes=route)
    tools_digest = download_tools(provider, metadata, destination / "tools", manifest)
    return manifest_path, archive, inventory, tools_digest


def prepare_online_path(roots, database_path, provider, selected, installed, actor_user_id):
    from enterprise import db as edb
    from enterprise.runtime.portable import windows_local_app_data_known_folder
    if Path(database_path) != roots.DATA_ROOT / "enterprise.db":
        raise UpdateMvpError("SYSTEM_UPDATE_DATABASE_CONTRACT_UNSUPPORTED")
    documents, metadata_by_release = [], {}
    for item in provider.list_release_v2_candidates(include_prerelease=selected.prerelease):
        if item.upgrade_routes_url is None:
            continue
        try:
            route = read_release_routes(provider, item)
        except Exception:
            if item.provider_release_id == selected.provider_release_id:
                raise
            continue
        if route.target.release_id in metadata_by_release:
            raise UpdateMvpError("SYSTEM_UPDATE_ROUTE_INVALID")
        metadata_by_release[route.target.release_id] = item
        documents.append(route)
    target = next((doc for doc in documents if metadata_by_release[doc.target.release_id].provider_release_id == selected.provider_release_id), None)
    path = None if target is None else plan_upgrade_path(installed, target.target.release_id, documents,
                                                        allow_development=selected.prerelease)
    if not path:
        raise UpdateMvpError("SYSTEM_UPDATE_ROUTE_NOT_DIRECT")
    sequence_id = uuid.uuid4().hex
    directory = input_root(roots, sequence_id)
    directory.mkdir(parents=True, exist_ok=False)
    with (directory / "runner.lock").open("xb") as stream:
        stream.write(b"C"); stream.flush(); os.fsync(stream.fileno())
    files._new_json(directory / "ownership.json", {"schema_version": SCHEMA, "sequence_id": sequence_id,
        "install_root_identity": files._identity(roots.INSTALL_ROOT),
        "local_app_data_base": str(windows_local_app_data_known_folder()),
        "lease": files._file(directory / "runner.lock")["identity"]})
    hops, prepared_artifacts = [], []
    final_verification = None
    for step in path:
        metadata = metadata_by_release[step.release_id]
        route = next(doc for doc in documents if doc.target == step)
        artifacts = download_step(provider, metadata, route, directory / step.release_id)
        root, verification = stage_verified_release(roots, manifest_path=artifacts[0], archive_path=artifacts[1], inventory_path=artifacts[2])
        require_sequence_controller(root)  # Every intermediate must enforce the pause.
        from enterprise.ops.update.updater import read_updater_descriptor
        descriptor = read_updater_descriptor(root)
        if descriptor is None or descriptor[0]["updater_contract"] != step.updater_contract:
            raise UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_INCOMPATIBLE")
        hops.append({"release_id": step.release_id, "version": step.version, "manifest_sha256": step.manifest_sha256,
                     "tools_sha256": artifacts[3], "route": {"target": asdict(route.target),
                         "allowed_sources": [asdict(source) for source in route.allowed_sources]}})
        prepared_artifacts.append(artifacts)
        final_verification = verification
    final_contract = read_updater_descriptor(roots.RELEASE_ROOT / path[-1].release_id)[0]["updater_contract"]
    predecessor = installed
    for step, hop in zip(path, hops):
        source = next(item for item in hop["route"]["allowed_sources"]
                      if item["release_id"] == predecessor.release_id
                      and item["manifest_sha256"] == predecessor.manifest_sha256
                      and item["database_schema_sha256"] == predecessor.database_schema_sha256)
        if final_contract < source["minimum_updater_contract"]:
            raise UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_INCOMPATIBLE")
        predecessor = step
    actor = edb.get_user_by_id(actor_user_id)
    if not actor or type(actor.get("auth_version")) is not int:
        raise UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_AUTHORIZATION_REVOKED")
    context = {"upgrade_sequence": {"schema_version": SCHEMA, "sequence_id": sequence_id,
        "operator_revision": actor["auth_version"], "hops": hops},
        "sequence_controller": {"release_id": path[-1].release_id, "manifest_sha256": final_verification.manifest_sha256,
            "payload_tree_sha256": final_verification.payload_tree_sha256, "inventory_sha256": final_verification.inventory_sha256}}
    first = prepared_artifacts[0]
    prepared = UpdateMvpService(roots, database_path=Path(database_path)).prepare_from_artifacts(
        actor_user_id=actor_user_id, manifest_path=first[0], archive_path=first[1], inventory_path=first[2], execution_context=context)
    return {"state": "READY", **prepared.public(), "target_release_id": path[-1].release_id,
            "upgrade_path": [{"release_id": step.release_id, "version": step.version} for step in path],
            "total_hops": len(path), "requires_no_active_tasks_confirmation": True, "release_notes": selected.release_notes}
