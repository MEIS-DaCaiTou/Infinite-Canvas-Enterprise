"""Minimal authenticated API for the fail-closed online Update Center."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from enterprise import db as edb
from enterprise.config import (
    ADMIN_PASSWORD,
    ENTERPRISE_UPDATE_ENABLED,
    JWT_SECRET,
    PATH_ROOTS,
)
from enterprise.ops.update.diagnostics import diagnostics_zip, recent_diagnostics
from enterprise.ops.update.download import atomic_download
from enterprise.ops.update.mvp import (
    MAX_ARCHIVE_BYTES,
    UpdateJobStore,
    UpdateMvpError,
    UpdateMvpService,
)
from enterprise.ops.update.providers import GitHubReleasesProvider
from enterprise.release.current_release import read_current_release_result_from_state_root
from enterprise.release.release_manifest_v2 import (
    INVENTORY_MAX_BYTES,
    MANIFEST_MAX_BYTES,
    ReleaseManifestV2Error,
    read_release_manifest_v2,
)
from enterprise.roles import ROLE_ADMIN, ROLE_SUPER_ADMIN
from enterprise.runtime.portable import request_portable_update_handoff


router = APIRouter()


def _error(exc: Exception) -> None:
    code = str(getattr(exc, "code", getattr(exc, "detail_code", "SYSTEM_UPDATE_FAILED")))
    status = int(getattr(exc, "status_code", 400))
    message = (
        "此版本包含数据库结构升级，当前在线升级版本暂不支持，请使用后续升级引擎。"
        if code == "SYSTEM_UPDATE_DATABASE_CONTRACT_UNSUPPORTED"
        else "The update operation could not be completed"
    )
    raise HTTPException(status_code=status, detail={"code": code, "message": message}) from exc


def _current_user(request: Request) -> dict:
    principal = getattr(request.state, "user", None)
    if not isinstance(principal, dict) or not isinstance(principal.get("user_id"), str):
        raise HTTPException(status_code=401, detail={"code": "STALE_AUTHENTICATION", "message": "Authentication is no longer current"})
    current = edb.get_user_by_id(principal["user_id"])
    if (
        not isinstance(current, dict)
        or current.get("is_active") is not True
        or current.get("auth_version") != principal.get("auth_version")
    ):
        raise HTTPException(status_code=401, detail={"code": "STALE_AUTHENTICATION", "message": "Authentication is no longer current"})
    return current


def _require_admin_view(request: Request) -> dict:
    current = _current_user(request)
    if current.get("role") not in {ROLE_ADMIN, ROLE_SUPER_ADMIN}:
        raise HTTPException(status_code=403, detail={"code": "SYSTEM_UPDATE_ACCESS_DENIED", "message": "Update Center access is denied"})
    return current


def _require_update_operator(request: Request) -> dict:
    current = _require_admin_view(request)
    if current.get("role") != ROLE_SUPER_ADMIN:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "SYSTEM_UPDATE_SUPER_ADMIN_REQUIRED",
                "message": "System update requires the current super administrator role",
            },
        )
    if not ENTERPRISE_UPDATE_ENABLED:
        raise HTTPException(status_code=403, detail={"code": "SYSTEM_UPDATE_EMERGENCY_SWITCH_DISABLED", "message": "System update is disabled"})
    if not edb.can_use_feature(current, "system_update"):
        raise HTTPException(status_code=403, detail={"code": "SYSTEM_UPDATE_PERMISSION_DENIED", "message": "System update permission is denied"})
    return current


def _provider() -> GitHubReleasesProvider:
    return GitHubReleasesProvider()


def _metadata_by_id(provider: GitHubReleasesProvider, release_id: str):
    matches = [item for item in provider.list_release_v2_candidates() if item.provider_release_id == release_id]
    if len(matches) != 1:
        raise UpdateMvpError("SYSTEM_UPDATE_RELEASE_NOT_FOUND", status_code=404)
    return matches[0]


@router.get("/api/update-mvp/access")
async def update_access(request: Request):
    current = _require_admin_view(request)
    effective = edb.get_effective_feature_value(current, "system_update")
    return {
        "role": current.get("role"),
        "can_operate": bool(ENTERPRISE_UPDATE_ENABLED and effective.get("allowed")),
        "global_update_enabled": bool(ENTERPRISE_UPDATE_ENABLED and effective.get("global_enabled")),
        "permission_source": effective.get("source"),
    }


@router.get("/api/update-mvp/check")
async def check_update(request: Request):
    _require_update_operator(request)
    try:
        current = read_current_release_result_from_state_root(PATH_ROOTS.STATE_ROOT)
        source_manifest = read_release_manifest_v2(PATH_ROOTS.APP_ROOT / "release-manifest.json")
        releases = _provider().list_release_v2_candidates()
        latest = releases[0] if releases else None
        return {
            "current_release_id": current.release.release_id,
            "current_version": source_manifest.section("identity")["release_version"],
            "latest": None if latest is None else {
                "provider_release_id": latest.provider_release_id,
                "tag_name": latest.tag_name,
                "version": latest.version,
                "published_at": latest.published_at,
                "release_notes": latest.release_notes,
            },
        }
    except Exception as exc:
        _error(exc)


@router.post("/api/update-mvp/prepare")
async def prepare_update(request: Request):
    actor = _require_update_operator(request)
    try:
        body = await request.json()
        provider_release_id = str(body.get("provider_release_id") or "").strip() if isinstance(body, dict) else ""
        if not provider_release_id or len(provider_release_id) > 64:
            raise UpdateMvpError("SYSTEM_UPDATE_RELEASE_ID_INVALID")
        return await run_in_threadpool(_prepare_update_sync, actor["id"], provider_release_id)
    except Exception as exc:
        _error(exc)


def _prepare_update_sync(actor_user_id: str, provider_release_id: str) -> dict[str, object]:
    """Complete one prepare workflow outside the Gateway asyncio event loop."""
    provider = _provider()
    metadata = _metadata_by_id(provider, provider_release_id)
    incoming = PATH_ROOTS.STAGING_ROOT / "update-mvp" / "incoming" / uuid.uuid4().hex
    incoming.mkdir(parents=True, exist_ok=False)
    try:
        manifest_path = incoming / "ops-release-manifest-v2.json"
        inventory_path = incoming / "release-payload-inventory.json"
        archive_path = incoming / "release.zip"
        headers = provider.release_v2_asset_request_headers(metadata.manifest_url)
        atomic_download(provider.http_client, url=metadata.manifest_url, destination=manifest_path, maximum_bytes=MANIFEST_MAX_BYTES, expected_size_bytes=metadata.manifest_size_bytes, headers=headers)
        manifest = read_release_manifest_v2(manifest_path)
        if manifest.section("identity")["release_version"] != metadata.version:
            raise UpdateMvpError("SYSTEM_UPDATE_PROVIDER_MANIFEST_IDENTITY_MISMATCH")
        archive = manifest.section("archive")
        payload = manifest.section("release_payload")
        if archive["size_bytes"] != metadata.archive_size_bytes:
            raise UpdateMvpError("SYSTEM_UPDATE_PROVIDER_MANIFEST_SIZE_MISMATCH")
        atomic_download(
            provider.http_client,
            url=metadata.inventory_url,
            destination=inventory_path,
            maximum_bytes=INVENTORY_MAX_BYTES,
            expected_size_bytes=metadata.inventory_size_bytes,
            expected_sha256=str(payload["inventory_sha256"]),
            headers=provider.release_v2_asset_request_headers(metadata.inventory_url),
        )
        atomic_download(
            provider.http_client,
            url=metadata.archive_url,
            destination=archive_path,
            maximum_bytes=MAX_ARCHIVE_BYTES,
            expected_size_bytes=int(archive["size_bytes"]),
            expected_sha256=str(archive["sha256"]),
            headers=provider.release_v2_asset_request_headers(metadata.archive_url),
        )
        prepared = UpdateMvpService(PATH_ROOTS).prepare_from_artifacts(
            actor_user_id=actor_user_id, manifest_path=manifest_path, archive_path=archive_path, inventory_path=inventory_path
        )
        return {"state": "READY", **prepared.public(), "release_notes": metadata.release_notes}
    finally:
        shutil.rmtree(incoming, ignore_errors=True)


def _launch_handoff(job_id: str, actor_user_id: str) -> None:
    store = UpdateJobStore(PATH_ROOTS)
    try:
        result = request_portable_update_handoff(app_root=PATH_ROOTS.APP_ROOT, job_id=job_id)
        if result.get("result") != "update_handoff_started":
            store.write_status(job_id, "FAILED", actor_user_id=actor_user_id, result_code="SYSTEM_UPDATE_HANDOFF_FAILED")
            store.append_event(job_id, "FAILED", "SYSTEM_UPDATE_HANDOFF_FAILED")
            edb.log_action(actor_user_id, "system_update_failed", json.dumps({"job_id": job_id, "result_code": "SYSTEM_UPDATE_HANDOFF_FAILED"}, ensure_ascii=False))
            try:
                lock = store.acquire_execution_lock(job_id)
                store.release_execution_lock(lock, job_id)
            except UpdateMvpError:
                pass
    except Exception:
        try:
            store.write_status(job_id, "FAILED", actor_user_id=actor_user_id, result_code="SYSTEM_UPDATE_HANDOFF_FAILED")
            store.append_event(job_id, "FAILED", "SYSTEM_UPDATE_HANDOFF_FAILED")
            edb.log_action(actor_user_id, "system_update_failed", json.dumps({"job_id": job_id, "result_code": "SYSTEM_UPDATE_HANDOFF_FAILED"}, ensure_ascii=False))
            lock = store.acquire_execution_lock(job_id)
            store.release_execution_lock(lock, job_id)
        except Exception:
            pass


@router.post("/api/update-mvp/jobs/{job_id}/execute", status_code=202)
async def execute_update(job_id: str, request: Request, background_tasks: BackgroundTasks):
    actor = _require_update_operator(request)
    reservation_created = False
    try:
        body = await request.json()
        password = body.get("password") if isinstance(body, dict) else None
        if not isinstance(password, str) or not password or len(password) > 1024:
            raise UpdateMvpError("SYSTEM_UPDATE_PASSWORD_REQUIRED")
        # Re-read the actor immediately before confirmation.  The password is
        # used only in this call and is never written to plan, state or audit.
        current = edb.get_user_by_id(actor["id"])
        if not current or current.get("auth_version") != actor.get("auth_version") or not edb.verify_password(password, str(current.get("password_hash") or "")):
            raise UpdateMvpError("SYSTEM_UPDATE_PASSWORD_INVALID", status_code=403)
        if not ENTERPRISE_UPDATE_ENABLED or not edb.can_use_feature(current, "system_update"):
            raise UpdateMvpError("SYSTEM_UPDATE_PERMISSION_DENIED", status_code=403)
        store = UpdateJobStore(PATH_ROOTS)
        status = store.read_status(job_id)
        plan = store.read_plan(job_id)
        if status.get("state") != "READY" or plan.get("actor_user_id") != actor["id"]:
            raise UpdateMvpError("SYSTEM_UPDATE_JOB_NOT_EXECUTABLE", status_code=409)
        current_pointer = read_current_release_result_from_state_root(PATH_ROOTS.STATE_ROOT)
        if current_pointer.raw_sha256 != plan.get("source_pointer_sha256"):
            raise UpdateMvpError("SYSTEM_UPDATE_EXPECTED_CURRENT_MISMATCH", status_code=409)
        store.reserve_execution(job_id)
        reservation_created = True
        store.write_status(
            job_id, "UPDATING", actor_user_id=actor["id"], result_code="SYSTEM_UPDATE_STARTED",
            source_release_id=plan.get("source_release_id"), target_release_id=plan.get("target_release_id"),
        )
        store.append_event(job_id, "UPDATING", "SYSTEM_UPDATE_STARTED")
        edb.log_action(actor["id"], "system_update_started", json.dumps({"job_id": job_id, "source_release_id": plan.get("source_release_id"), "target_release_id": plan.get("target_release_id")}, ensure_ascii=False))
        background_tasks.add_task(_launch_handoff, job_id, actor["id"])
        return {"job_id": job_id, "state": "UPDATING", "result_code": "SYSTEM_UPDATE_STARTED"}
    except Exception as exc:
        if reservation_created:
            try:
                lock = UpdateJobStore(PATH_ROOTS).acquire_execution_lock(job_id)
                UpdateJobStore(PATH_ROOTS).release_execution_lock(lock, job_id)
            except Exception:
                pass
        _error(exc)


@router.get("/api/update-mvp/jobs/{job_id}")
async def update_job(job_id: str, request: Request):
    _require_update_operator(request)
    try:
        return UpdateJobStore(PATH_ROOTS).read_status(job_id)
    except Exception as exc:
        _error(exc)


@router.get("/api/update-mvp/diagnostics")
async def update_diagnostics(request: Request):
    _require_update_operator(request)
    try:
        job_id = str(request.query_params.get("job_id") or "").strip() or None
        if job_id is not None:
            UpdateJobStore.validate_job_id(job_id)
        limit = int(request.query_params.get("limit") or 100)
        payload = recent_diagnostics(
            PATH_ROOTS,
            job_id=job_id,
            limit=limit,
            level=str(request.query_params.get("level") or ""),
            keyword=str(request.query_params.get("keyword") or ""),
            secret_values=(JWT_SECRET, ADMIN_PASSWORD),
        )
    except Exception as exc:
        _error(exc)
    if request.query_params.get("download") == "1":
        return Response(
            diagnostics_zip(payload), media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="update-diagnostics.zip"'},
        )
    return payload
