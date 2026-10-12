"""Read-only selection of a verified Release's fixed update executor.

The controller protocol is deliberately independent of the engine version.
Older, immutable Releases without a descriptor keep the source executor.
A present but incompatible or unverified descriptor never permits fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re

from enterprise.path_safety import assert_no_reparse_ancestors, has_reparse_point
from enterprise.paths import validate_release_component
from enterprise.release.release_manifest_v2 import read_release_manifest_v2, verify_materialized_release
from enterprise.runtime.logging import redact_value

CONTROLLER_CONTRACT = 1
WORKER_PROTOCOL = 2
UPDATER_CONTRACT = 4
DESCRIPTOR_PATH = "enterprise/ops/update/updater-worker-v1.json"
WORKER_PATH = "enterprise/ops/update/handoff.py"
DESCRIPTOR_SCHEMA = "enterprise-updater-worker-v1"
BINDING_SCHEMA = "enterprise-updater-binding-v1"
_DESCRIPTOR_KEYS = frozenset({
    "schema_version", "minimum_controller_contract", "worker_protocol", "updater_contract", "worker_entry",
})
_BINDING_KEYS = frozenset({
    "schema_version", "mode", "controller_contract", "worker_protocol", "updater_contract",
    "worker_release_id", "worker_manifest_sha256", "worker_payload_tree_sha256", "contract_sha256",
})
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class UpdaterExecutionError(RuntimeError):
    def __init__(self, code: str = "SYSTEM_UPDATE_UPDATER_UNVERIFIED") -> None:
        self.code = code
        self.status_code = 409
        super().__init__(code)


def plan_sha256(plan: dict) -> str:
    # Identical canonical encoding to the existing immutable plan writer.
    encoded = (json.dumps(redact_value(plan), ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")) + "\n").encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_updater_descriptor(app_root: Path) -> tuple[dict, str] | None:
    path = app_root / DESCRIPTOR_PATH
    try:
        assert_no_reparse_ancestors(path, allow_missing=True)
        # lexists distinguishes a missing legacy descriptor from a broken link.
        if not os.path.lexists(path):
            return None
        if not path.is_file() or has_reparse_point(path):
            raise UpdaterExecutionError()
        with path.open("rb") as handle:
            raw = handle.read(4097)
            opened = os.fstat(handle.fileno())
        current = path.stat(follow_symlinks=False)
        if len(raw) > 4096 or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise UpdaterExecutionError()
        payload = json.loads(raw)
        if (type(payload) is not dict or payload.keys() != _DESCRIPTOR_KEYS
                or payload.get("schema_version") != DESCRIPTOR_SCHEMA
                or payload.get("worker_entry") != WORKER_PATH):
            raise UpdaterExecutionError()
        if any(type(payload[key]) is not int or not 1 <= payload[key] <= 100
               for key in ("minimum_controller_contract", "worker_protocol", "updater_contract")):
            raise UpdaterExecutionError()
        if (payload["minimum_controller_contract"] > CONTROLLER_CONTRACT
                or payload["worker_protocol"] != WORKER_PROTOCOL
                or payload["updater_contract"] < UPDATER_CONTRACT):
            raise UpdaterExecutionError("SYSTEM_UPDATE_UPDATER_INCOMPATIBLE")
        return payload, hashlib.sha256(raw).hexdigest()
    except UpdaterExecutionError:
        raise
    except Exception as exc:
        raise UpdaterExecutionError() from exc


def prepared_updater_binding(app_root: Path, manifest_sha: str, payload_sha: str) -> dict | None:
    descriptor = read_updater_descriptor(app_root)
    if descriptor is None:
        return None
    contract, digest = descriptor
    return {
        "schema_version": BINDING_SCHEMA, "mode": "target-release",
        "controller_contract": CONTROLLER_CONTRACT, "worker_protocol": WORKER_PROTOCOL,
        "updater_contract": contract["updater_contract"], "worker_release_id": app_root.name,
        "worker_manifest_sha256": manifest_sha, "worker_payload_tree_sha256": payload_sha,
        "contract_sha256": digest,
    }


def sealed_updater_binding(plan: dict, status: dict) -> dict | None:
    """Verify plan/status agreement without running code or reading the payload."""
    if "updater_execution" not in plan and "updater_execution" not in status:
        return None
    binding = plan.get("updater_execution")
    if (type(binding) is not dict or binding.keys() != _BINDING_KEYS
            or type(status.get("updater_execution")) is not dict
            or json.dumps(binding, sort_keys=True) != json.dumps(status["updater_execution"], sort_keys=True)
            or status.get("plan_sha256") != plan_sha256(plan)
            or binding.get("schema_version") != BINDING_SCHEMA
            or binding.get("mode") != "target-release"):
        raise UpdaterExecutionError()
    for key, expected in (("controller_contract", CONTROLLER_CONTRACT), ("worker_protocol", WORKER_PROTOCOL)):
        if type(binding.get(key)) is not int or binding[key] != expected:
            raise UpdaterExecutionError()
    if type(binding.get("updater_contract")) is not int or not UPDATER_CONTRACT <= binding["updater_contract"] <= 100:
        raise UpdaterExecutionError()
    for key in ("worker_manifest_sha256", "worker_payload_tree_sha256", "contract_sha256"):
        if type(binding.get(key)) is not str or _SHA.fullmatch(binding[key]) is None:
            raise UpdaterExecutionError()
    controller = plan.get("sequence_controller", {})
    if type(controller) is not dict:
        raise UpdaterExecutionError()
    if (binding.get("worker_release_id") != controller.get("release_id", plan.get("target_release_id"))
            or binding["worker_manifest_sha256"] != controller.get("manifest_sha256", plan.get("target_manifest_sha256"))
            or binding["worker_payload_tree_sha256"] != controller.get("payload_tree_sha256", plan.get("target_payload_tree_sha256"))):
        raise UpdaterExecutionError()
    try:
        validate_release_component(binding["worker_release_id"])
    except Exception as exc:
        raise UpdaterExecutionError() from exc
    return {**binding, "plan_sha256": status["plan_sha256"]}


@dataclass(frozen=True)
class VerifiedUpdater:
    app_root: Path
    python: Path
    worker: Path
    readiness_binding: dict


def select_verified_updater(roots, plan: dict, status: dict) -> VerifiedUpdater | None:
    binding = sealed_updater_binding(plan, status)
    if binding is None:
        return None
    try:
        if "upgrade_sequence" in plan:
            from enterprise.ops.update.sequence import verify_prepared_sequence
            verify_prepared_sequence(roots, plan)
        app_root = roots.RELEASE_ROOT / validate_release_component(binding["worker_release_id"])
        manifest = read_release_manifest_v2(app_root / "release-manifest.json")
        verification = verify_materialized_release(
            app_root, inventory_path=app_root / manifest.section("release_payload")["inventory_path"])
        if (manifest.release_id != app_root.name or verification.manifest_sha256 != binding["worker_manifest_sha256"]
                or verification.payload_tree_sha256 != binding["worker_payload_tree_sha256"]
                or verification.inventory_sha256 != plan.get("sequence_controller", {}).get("inventory_sha256", plan.get("target_inventory_sha256"))):
            raise UpdaterExecutionError()
        actual = prepared_updater_binding(app_root, verification.manifest_sha256, verification.payload_tree_sha256)
        if actual != {key: value for key, value in binding.items() if key != "plan_sha256"}:
            raise UpdaterExecutionError()
        python, worker = app_root / "python/python.exe", app_root / WORKER_PATH
        for path in (python, worker):
            assert_no_reparse_ancestors(path)
            if not path.is_file() or has_reparse_point(path):
                raise UpdaterExecutionError()
        return VerifiedUpdater(app_root, python, worker, binding)
    except UpdaterExecutionError:
        raise
    except Exception as exc:
        raise UpdaterExecutionError() from exc
