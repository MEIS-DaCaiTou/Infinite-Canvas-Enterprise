"""One authorized path, durable hop receipts, and the existing single-hop engine.

The verified final Release runs the coordinator. Intermediate business access
stays paused. A failed hop restores only that hop; completed hops are never
undone by restoring an older database snapshot.
"""
from __future__ import annotations

from configparser import ConfigParser
import hashlib
import io
import json
import os
from pathlib import Path

from enterprise import install_cache as files, install_lifecycle as lifecycle
from enterprise.install_entry import ENTRY_NAME, _record, _snapshot, validate_installation_record, verify_entry_bundle
from enterprise.install_upgrade import _Transaction, _blob, _file_or_none, _support, SLOTS
from enterprise.ops.update import mvp
from enterprise.ops.update.maintenance_assets import verify_tools
from enterprise.ops.update.updater import plan_sha256, select_verified_updater
from enterprise.paths import PortableRootInputs, derive_portable_path_roots, validate_release_component
from enterprise.release.current_release import read_current_release_result_from_state_root, sync_state_root_directory
from enterprise.release.release_manifest_v2 import canonical_json, read_release_manifest_v2, verify_release_manifest_v2
from enterprise.runtime.windows_owned_move import release_fence

ACTIVE_NAME = "upgrade-sequence-active.json"
SCHEMA = "enterprise-upgrade-sequence-v1"
DESCRIPTOR = "enterprise/ops/update/sequence-controller-v1.json"


def require_sequence_controller(app_root):
    path = Path(app_root) / DESCRIPTOR
    token = files._file(path)
    if token["size_bytes"] > 4096:
        raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_INCOMPATIBLE")
    try:
        payload = json.loads(files._io(path).read_bytes())
    except (ValueError, UnicodeError) as exc:
        raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_INCOMPATIBLE") from exc
    if files._file(path) != token:
        raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_UNVERIFIED")
    if (payload != {"schema_version": "enterprise-upgrade-sequence-controller-v1",
                   "controller_contract": 1, "maximum_hops": 8, "maintenance_tools_contract": 1}
            or any(type(payload[key]) is not int for key in ("controller_contract", "maximum_hops", "maintenance_tools_contract"))):
        raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_INCOMPATIBLE")


def input_root(roots, sequence_id):
    return roots.STAGING_ROOT / "update-mvp" / "sequences" / mvp.UpdateJobStore.validate_job_id(sequence_id)


def _root_plan(roots, root_job_id):
    store = mvp.UpdateJobStore(roots)
    plan, status = store.read_plan(root_job_id), store.read_status(root_job_id)
    sequence = plan.get("upgrade_sequence")
    if (type(sequence) is not dict or set(sequence) != {"schema_version", "sequence_id", "operator_revision", "hops"}
            or sequence["schema_version"] != SCHEMA or status.get("plan_sha256") != plan_sha256(plan)
            or type(sequence["hops"]) is not list or not 1 <= len(sequence["hops"]) <= 8
            or type(sequence["operator_revision"]) is not int):
        raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_UNVERIFIED")
    directory = input_root(roots, sequence["sequence_id"])
    proof, _ = files._read(directory / "ownership.json")
    if (proof.get("schema_version") != SCHEMA or proof.get("sequence_id") != sequence["sequence_id"]
            or proof.get("install_root_identity") != files._identity(roots.INSTALL_ROOT)):
        raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_UNVERIFIED")
    return plan, sequence, directory, proof


def check_authorization(plan, sequence):
    from enterprise import db as edb
    from enterprise.config import ENTERPRISE_UPDATE_ENABLED
    from enterprise.roles import ROLE_SUPER_ADMIN
    actor = edb.get_user_by_id(plan["actor_user_id"])
    if (not actor or actor.get("is_active") is not True or actor.get("role") != ROLE_SUPER_ADMIN
            or actor.get("auth_version") != sequence["operator_revision"]
            or not ENTERPRISE_UPDATE_ENABLED or not edb.can_use_feature(actor, "system_update")):
        raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_AUTHORIZATION_REVOKED", status_code=403)


def _state(directory, **payload):
    files._state(directory / "state.json", {"schema_version": SCHEMA, "updated_at": mvp.utc_now(), **payload})


def activate_sequence(roots, root_job_id):
    plan, sequence, directory, proof = _root_plan(roots, root_job_id)
    check_authorization(plan, sequence)
    if any(hop["tools_sha256"] is not None for hop in sequence["hops"]):
        record = validate_installation_record(roots.INSTALL_ROOT, _snapshot(roots.STATE_ROOT / "installation.json"))
        _support(roots.INSTALL_ROOT, record["installation_id"])
        if files._file(roots.INSTALL_ROOT / ENTRY_NAME)["sha256"] != record["native_entry"]["sha256"]:
            raise mvp.UpdateMvpError("SYSTEM_UPDATE_MAINTENANCE_SOURCE_UNVERIFIED")
        from enterprise.runtime.windows_install_registration import verify_registration
        verify_registration(roots.INSTALL_ROOT, record["installation_id"],
                            expected_version=read_release_manifest_v2(roots.APP_ROOT / "release-manifest.json").section("identity")["release_version"])
    with files._lease(directory / "runner.lock", proof["lease"]):
        marker = roots.STATE_ROOT / ACTIVE_NAME
        if files._exists(marker):
            raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_ACTIVE", status_code=409)
        # A create-only, linked marker keeps exact ownership for completion.
        files._new_json(directory / "active.json", {"schema_version": SCHEMA, "job_id": root_job_id,
            "sequence_id": sequence["sequence_id"], "plan_sha256": plan_sha256(plan)})
        _state(directory, job_id=root_job_id, state="UPDATING", completed_hops=0,
               current_job_id=root_job_id, result_code="SYSTEM_UPDATE_SEQUENCE_STARTED")
        os.link(files._io(directory / "active.json"), files._io(marker))
        sync_state_root_directory(roots.STATE_ROOT)


def _assert_active(roots, root_job_id, plan, directory):
    marker = roots.STATE_ROOT / ACTIVE_NAME
    token = lifecycle._marker(directory / "active.json")
    if (lifecycle._marker(marker) != token or lifecycle._read_fence(marker) != {
            "schema_version": SCHEMA, "job_id": root_job_id,
            "sequence_id": plan["upgrade_sequence"]["sequence_id"], "plan_sha256": plan_sha256(plan)}):
        raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_UNVERIFIED")
    return token


def _checkpoints(roots, root_job_id, plan, sequence, directory):
    """Progress JSON cannot authorize skipping a hop or completing an upgrade."""
    result = []
    store = mvp.UpdateJobStore(roots)
    for index, hop in enumerate(sequence["hops"]):
        path = directory / ("checkpoint-" + str(index) + ".json")
        if not files._exists(path):
            if any(files._exists(directory / ("checkpoint-" + str(later) + ".json"))
                   for later in range(index + 1, len(sequence["hops"]))):
                raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_CHECKPOINT_UNVERIFIED")
            break
        receipt, _ = files._read(path)
        job_id = receipt.get("job_id")
        job_plan, status = store.read_plan(job_id), store.read_status(job_id)
        source_id = plan["source_release_id"] if index == 0 else sequence["hops"][index - 1]["release_id"]
        source_manifest = plan["source_manifest_sha256"] if index == 0 else sequence["hops"][index - 1]["manifest_sha256"]
        if (receipt != {"schema_version": SCHEMA, "root_job_id": root_job_id, "index": index,
                "job_id": job_id, "plan_sha256": plan_sha256(job_plan), "root_plan_sha256": plan_sha256(plan),
                "pointer_sha256": receipt.get("pointer_sha256")}
                or type(receipt["pointer_sha256"]) is not str or len(receipt["pointer_sha256"]) != 64
                or status["state"] != "SUCCEEDED" or job_plan["actor_user_id"] != plan["actor_user_id"]
                or job_plan["source_release_id"] != source_id or job_plan["source_manifest_sha256"] != source_manifest
                or job_plan["target_release_id"] != hop["release_id"] or job_plan["target_manifest_sha256"] != hop["manifest_sha256"]
                or (index == 0 and job_id != root_job_id)
                or (index > 0 and (job_plan.get("sequence_parent") != root_job_id
                    or job_plan["source_pointer_sha256"] != result[-1]["pointer_sha256"]))):
            raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_CHECKPOINT_UNVERIFIED")
        result.append(receipt)
    return result


def _commit_checkpoint(roots, root_job_id, root_plan, directory, index, job_id):
    job_plan = mvp.UpdateJobStore(roots).read_plan(job_id)
    value = {"schema_version": SCHEMA, "root_job_id": root_job_id, "index": index,
             "job_id": job_id, "plan_sha256": plan_sha256(job_plan), "root_plan_sha256": plan_sha256(root_plan),
             "pointer_sha256": read_current_release_result_from_state_root(roots.STATE_ROOT).raw_sha256}
    files._new_json(directory / ("checkpoint-" + str(index) + ".json"), value)
    sync_state_root_directory(directory)


def public_sequence(roots, root_job_id):
    plan, sequence, directory, _ = _root_plan(roots, root_job_id)
    if not files._exists(directory / "state.json"):
        return None
    state, _ = files._read(directory / "state.json")
    if state.get("schema_version") != SCHEMA or state.get("job_id") != root_job_id:
        raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_UNVERIFIED")
    completed = len(_checkpoints(roots, root_job_id, plan, sequence, directory))
    hop_status = mvp.UpdateJobStore(roots).read_status(state["current_job_id"])
    effective = state["state"]
    if files._exists(directory / "completion.json") and not files._exists(roots.STATE_ROOT / ACTIVE_NAME):
        completion, _ = files._read(directory / "completion.json")
        checkpoints = _checkpoints(roots, root_job_id, plan, sequence, directory)
        if (len(checkpoints) != len(sequence["hops"]) or completion != {
                "schema_version": SCHEMA, "job_id": root_job_id, "final_job_id": checkpoints[-1]["job_id"],
                "plan_sha256": plan_sha256(plan), "completed_hops": len(checkpoints),
                "pointer_sha256": checkpoints[-1]["pointer_sha256"]}):
            raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_CHECKPOINT_UNVERIFIED")
        effective = "SUCCEEDED"
    if effective == "UPDATING" and hop_status["state"] not in mvp.TERMINAL_STATES:
        effective = hop_status["state"]
    elif effective == "UPDATING" and hop_status["state"] in {"FAILED", "ROLLED_BACK", "RECOVERY_REQUIRED"}:
        effective = hop_status["state"]
    available = False
    if files._exists(roots.STATE_ROOT / ACTIVE_NAME):
        _assert_active(roots, root_job_id, plan, directory)
        try:
            _, _, _, proof = _root_plan(roots, root_job_id)
            with files._lease(directory / "runner.lock", proof["lease"]):
                available = not mvp.UpdateJobStore(roots).lock_path.exists()
        except files.CacheError:
            pass  # The active worker owns continuation until it exits.
    return {"job_id": root_job_id, "state": effective,
            "result_code": "SYSTEM_UPDATE_SUCCEEDED" if effective == "SUCCEEDED" else state["result_code"],
            "updated_at": state.get("updated_at", hop_status["updated_at"]),
            "current_job_id": state["current_job_id"], "completed_hops": completed,
            "total_hops": len(sequence["hops"]), "source_release_id": plan["source_release_id"],
            "target_release_id": sequence["hops"][-1]["release_id"],
            "updater_execution": plan["updater_execution"],
            "can_resume": available and hop_status["state"] == "SUCCEEDED"
                          and completed <= len(sequence["hops"]),
            "can_stop": available and hop_status["state"] in {"SUCCEEDED", "ROLLED_BACK", "FAILED", "RECOVERY_CLEARED"},
            "upgrade_path": [{"release_id": hop["release_id"], "version": hop["version"]} for hop in sequence["hops"]]}


def active_sequence_id(roots):
    if not files._exists(roots.STATE_ROOT / ACTIVE_NAME):
        return None
    marker = lifecycle._read_fence(roots.STATE_ROOT / ACTIVE_NAME)
    root_job_id = marker.get("job_id")
    plan, _, directory, _ = _root_plan(roots, root_job_id)
    _assert_active(roots, root_job_id, plan, directory)
    return root_job_id


class OnlineTools(_Transaction):
    """Reuse the object-bound C6 slots; Windows registration stays an adapter."""
    def __init__(self, roots, directory, plan, assert_active):
        super().__init__(roots, directory, plan)
        self.assert_active = assert_active

    def basics(self):
        self.assert_active()
        if (files._identity(self.roots.INSTALL_ROOT) != self.plan["root_identity"]
                or files._identity(self.roots.DATA_ROOT) != self.plan["data_identity"]
                or files._identity(self.roots.CONFIG_ROOT) != self.plan["config_identity"]):
            raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_INSTALLATION_CHANGED")

    def refresh(self, release_id):
        roots = derive_portable_path_roots(PortableRootInputs(self.roots.INSTALL_ROOT,
            Path(self.plan["local_app_data_base"])), release_id)
        lifecycle.refresh_installed_proof(roots, read_release_manifest_v2(roots.APP_ROOT / "release-manifest.json"))

    def register(self):
        from enterprise.runtime.windows_install_registration import update_registration_version
        update_registration_version(self.roots.INSTALL_ROOT, self.plan["installation_id"],
                                    source_version=self.plan["source_version"], target_version=self.plan["target_version"])


def _tools_transaction(roots, job_id, tools, digest, guard):
    manifest = read_release_manifest_v2(roots.RELEASE_ROOT / mvp.UpdateJobStore(roots).read_plan(job_id)["target_release_id"] / "release-manifest.json")
    verify_tools(tools, manifest, expected_digest=digest)
    entry = verify_entry_bundle(tools, commit=manifest.section("enterprise_source")["commit"], tree=manifest.section("enterprise_source")["tree"])
    directory = mvp.UpdateJobStore(roots).job_root(job_id) / "native-tools"
    if files._exists(directory / "plan.json"):
        plan, _ = files._read(directory / "plan.json")
        receipt, _ = files._read(directory / "proof.json")
        if (plan.get("operation_id") != job_id or plan.get("target_manifest_sha256") != manifest.raw_sha256
                or receipt != {"schema_version": "enterprise-online-native-proof-v1", "job_id": job_id,
                    "plan_sha256": hashlib.sha256(canonical_json(plan)).hexdigest(), "tools_sha256": digest,
                    "job_plan_sha256": plan_sha256(mvp.UpdateJobStore(roots).read_plan(job_id))}):
            raise mvp.UpdateMvpError("SYSTEM_UPDATE_MAINTENANCE_TOOLS_UNVERIFIED")
        return OnlineTools(roots, directory, plan, guard)
    snapshot = _snapshot(roots.STATE_ROOT / "installation.json")
    record = validate_installation_record(roots.INSTALL_ROOT, snapshot)
    _support(roots.INSTALL_ROOT, record["installation_id"])
    if files._file(roots.INSTALL_ROOT / ENTRY_NAME)["sha256"] != record["native_entry"]["sha256"]:
        raise mvp.UpdateMvpError("SYSTEM_UPDATE_MAINTENANCE_SOURCE_UNVERIFIED")
    files._io(files._safe(directory, missing=True)).mkdir(exist_ok=False)
    parser = ConfigParser(interpolation=None)
    raw = files._io(roots.INSTALL_ROOT / SLOTS["support"]).read_bytes()
    parser.read_string(raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"))
    parser["Lifecycle"]["SetupSha256"] = files._file(tools / "InfiniteCanvasSetup.exe")["sha256"]
    parser["Lifecycle"]["SetupSize"] = str(files._file(tools / "InfiniteCanvasSetup.exe")["size_bytes"])
    support = io.StringIO(); parser.write(support)
    payloads = {"entry": entry.data, "record": canonical_json(_record(roots.INSTALL_ROOT, entry, snapshot)),
                "setup": files._io(tools / "InfiniteCanvasSetup.exe").read_bytes(),
                "support": support.getvalue().encode("utf-8")}
    slots = {key: {"before": _file_or_none(roots.INSTALL_ROOT / relative),
                   "candidate": _blob(directory / ("candidate-" + key), payloads[key])} for key, relative in SLOTS.items()}
    source = read_release_manifest_v2(roots.APP_ROOT / "release-manifest.json")
    from enterprise.runtime.portable import windows_local_app_data_known_folder
    plan = {"operation_id": job_id, "installation_id": record["installation_id"],
            "root_identity": files._identity(roots.INSTALL_ROOT), "data_identity": files._identity(roots.DATA_ROOT),
            "config_identity": files._identity(roots.CONFIG_ROOT), "local_app_data_base": str(windows_local_app_data_known_folder()),
            "source_release_id": source.release_id, "source_manifest_sha256": source.raw_sha256,
            "target_release_id": manifest.release_id, "target_manifest_sha256": manifest.raw_sha256,
            "source_version": source.section("identity")["release_version"],
            "target_version": manifest.section("identity")["release_version"], "slots": slots}
    files._new_json(directory / "plan.json", plan)
    files._new_json(directory / "proof.json", {"schema_version": "enterprise-online-native-proof-v1", "job_id": job_id,
        "plan_sha256": hashlib.sha256(canonical_json(plan)).hexdigest(), "tools_sha256": digest,
        "job_plan_sha256": plan_sha256(mvp.UpdateJobStore(roots).read_plan(job_id))})
    return OnlineTools(roots, directory, plan, guard)


def _hop_artifacts(roots, directory, hop):
    if type(hop) is not dict or set(hop) != {"release_id", "version", "manifest_sha256", "tools_sha256", "route"}:
        raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_UNVERIFIED")
    root = directory / validate_release_component(hop["release_id"])
    manifest_path, archive, inventory = (root / name for name in ("ops-release-manifest-v2.json", "release.zip", "release-payload-inventory.json"))
    verification = verify_release_manifest_v2(manifest_path, archive, inventory)
    manifest = read_release_manifest_v2(manifest_path)
    if (manifest.release_id != hop["release_id"] or verification.manifest_sha256 != hop["manifest_sha256"]
            or manifest.section("identity")["release_version"] != hop["version"]):
        raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_UNVERIFIED")
    return root, manifest_path, archive, inventory


def verify_prepared_sequence(roots, plan):
    """Called by the source supervisor before accepting any service shutdown."""
    from enterprise.release.release_manifest_v2 import verify_materialized_release
    from enterprise.ops.update.updater import read_updater_descriptor
    sequence = plan["upgrade_sequence"]
    directory = input_root(roots, sequence["sequence_id"])
    for hop in sequence["hops"]:
        artifacts, manifest_path, _, _ = _hop_artifacts(roots, directory, hop)
        target = roots.RELEASE_ROOT / validate_release_component(hop["release_id"])
        manifest = read_release_manifest_v2(manifest_path)
        verification = verify_materialized_release(target, inventory_path=target / manifest.section("release_payload")["inventory_path"])
        if verification.manifest_sha256 != hop["manifest_sha256"] or read_updater_descriptor(target) is None:
            raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_UNVERIFIED")
        require_sequence_controller(target)
        if hop["tools_sha256"] is not None:
            verify_tools(artifacts / "tools", manifest, expected_digest=hop["tools_sha256"])


def _verify_edge(current_roots, database_path, hop):
    from enterprise.migrations.versioned import STATE_READY
    from enterprise.ops.update.upgrade_routes import ReleaseState, parse_upgrade_routes, plan_upgrade_path
    source = read_release_manifest_v2(current_roots.APP_ROOT / "release-manifest.json")
    metadata = lifecycle._database_inspection(current_roots)
    evidence = mvp._database_evidence(current_roots.APP_ROOT, source)
    if (metadata["current_state"] != STATE_READY or metadata["schema_sha256"] != evidence["schema_objects_sha256"]
            or metadata["schema_version"] != evidence["schema_version"]):
        raise mvp.UpdateMvpError("SYSTEM_UPDATE_ROUTE_SOURCE_UNVERIFIED")
    document = {"schema_version": "enterprise-upgrade-routes-v1", **hop["route"]}
    raw = json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    route = parse_upgrade_routes(raw, expected_manifest_sha256=hop["manifest_sha256"],
        expected_release_id=hop["release_id"], expected_version=hop["version"], expected_channel=document["target"]["channel"])
    # The final verified engine supplies the capability for every known migration.
    from enterprise.ops.update.updater import read_updater_descriptor
    controller = read_updater_descriptor(Path(__file__).resolve().parents[3])
    contract = controller[0]["updater_contract"] if controller is not None else 4
    state = ReleaseState(source.release_id, source.section("identity")["release_version"], source.raw_sha256,
                         metadata["schema_sha256"], contract, "stable")
    if plan_upgrade_path(state, hop["release_id"], [route], allow_development=route.target.channel == "development") is None:
        raise mvp.UpdateMvpError("SYSTEM_UPDATE_ROUTE_INVALID")


def execute_sequence(roots, root_job_id, *, database_path=None, launcher=mvp._run_launcher):
    plan, sequence, directory, proof = _root_plan(roots, root_job_id)
    select_verified_updater(roots, plan, mvp.UpdateJobStore(roots).read_status(root_job_id))
    with files._lease(directory / "runner.lock", proof["lease"]):
        token = _assert_active(roots, root_job_id, plan, directory)
        guard = lambda: _assert_active(roots, root_job_id, plan, directory)
        state, _ = files._read(directory / "state.json")
        completed = len(_checkpoints(roots, root_job_id, plan, sequence, directory))
        job_id = state["current_job_id"]
        database_path = database_path or roots.DATA_ROOT / "enterprise.db"
        try:
            for index in range(completed, len(sequence["hops"])):
                check_authorization(plan, sequence)
                guard()
                hop = sequence["hops"][index]
                artifacts, manifest_path, archive, inventory = _hop_artifacts(roots, directory, hop)
                current = read_current_release_result_from_state_root(roots.STATE_ROOT)
                current_roots = derive_portable_path_roots(PortableRootInputs(roots.INSTALL_ROOT,
                    Path(proof["local_app_data_base"])), current.release.release_id)
                receipt = directory / ("hop-" + str(index) + ".json")
                if index > 0:
                    if files._exists(receipt):
                        bound, _ = files._read(receipt)
                        job_id = bound["job_id"]
                        job_plan = mvp.UpdateJobStore(roots).read_plan(job_id)
                        if bound != {"schema_version": SCHEMA, "root_job_id": root_job_id, "index": index,
                                     "job_id": job_id, "plan_sha256": plan_sha256(job_plan)}:
                            raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_UNVERIFIED")
                    else:
                        # The previous successful runtime is still paused by the linked marker.
                        stop_code, _ = launcher(current_roots.APP_ROOT, "stop")
                        if stop_code != 0:
                            raise mvp.UpdateMvpError("SYSTEM_UPDATE_TARGET_STOP_UNCONFIRMED")
                        _verify_edge(current_roots, database_path, hop)
                        prepared = mvp.UpdateMvpService(current_roots, database_path=database_path,
                            database_inspector=lambda path: lifecycle._database_inspection(current_roots)).prepare_from_artifacts(
                                actor_user_id=plan["actor_user_id"], manifest_path=manifest_path, archive_path=archive,
                                inventory_path=inventory, execution_context={"sequence_parent": root_job_id,
                                    "sequence_controller": plan["sequence_controller"]})
                        job_id = prepared.job_id
                        job_plan = mvp.UpdateJobStore(roots).read_plan(job_id)
                        files._new_json(receipt, {"schema_version": SCHEMA, "root_job_id": root_job_id,
                            "index": index, "job_id": job_id, "plan_sha256": plan_sha256(job_plan)})
                    status = mvp.UpdateJobStore(roots).read_status(job_id)
                    if status["state"] == "READY":
                        mvp.UpdateJobStore(roots).reserve_execution(job_id)
                        mvp.UpdateJobStore(roots).write_status(job_id, "UPDATING", actor_user_id=plan["actor_user_id"],
                            result_code="SYSTEM_UPDATE_STARTED", source_release_id=job_plan["source_release_id"], target_release_id=hop["release_id"])
                _state(directory, job_id=root_job_id, state="UPDATING", completed_hops=index,
                       current_job_id=job_id, result_code="SYSTEM_UPDATE_SEQUENCE_HOP_STARTED")
                tx = None
                if hop["tools_sha256"] is not None:
                    tx = _tools_transaction(current_roots, job_id, artifacts / "tools", hop["tools_sha256"], guard)
                def launch(app_root, command):
                    guard()
                    if command == "start" and tx is not None:
                        if app_root.name == hop["release_id"]:
                            tx.publish()
                        else:
                            tx.restore()
                        tx.refresh(app_root.name)
                    elif command == "start" and files._exists(roots.STATE_ROOT / "installation.json"):
                        baseline_roots = derive_portable_path_roots(PortableRootInputs(roots.INSTALL_ROOT,
                            Path(proof["local_app_data_base"])), app_root.name)
                        lifecycle.refresh_installed_proof(baseline_roots, read_release_manifest_v2(app_root / "release-manifest.json"))
                    return launcher(app_root, command)
                store = mvp.UpdateJobStore(roots)
                hop_status = store.read_status(job_id)
                if hop_status["state"] == "UPDATING":
                    _verify_edge(current_roots, database_path, hop)
                    mvp.execute_update_job(current_roots, job_id, launcher=launch, database_path=database_path,
                                           database_inspector=lambda path: lifecycle._database_inspection(current_roots))
                hop_status = store.read_status(job_id)
                if hop_status["state"] != "SUCCEEDED":
                    _state(directory, job_id=root_job_id, state=hop_status["state"], completed_hops=index,
                           current_job_id=job_id, result_code=hop_status["result_code"])
                    if hop_status["state"] in {"FAILED", "ROLLED_BACK"}:
                        if tx is not None:
                            tx.restore()
                        if hop_status["state"] == "FAILED":
                            source = read_release_manifest_v2(current_roots.APP_ROOT / "release-manifest.json")
                            pointer = read_current_release_result_from_state_root(roots.STATE_ROOT)
                            schema = lifecycle._database_inspection(current_roots)
                            evidence = mvp._database_evidence(current_roots.APP_ROOT, source)
                            if (pointer.release.release_id != source.release_id or pointer.release.manifest_sha256 != source.raw_sha256
                                    or schema["schema_sha256"] != evidence["schema_objects_sha256"]
                                    or schema["schema_version"] != evidence["schema_version"]):
                                raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_CHECKPOINT_UNVERIFIED")
                            launch(current_roots.APP_ROOT, "start")
                        health_code, _ = launcher(current_roots.APP_ROOT, "health")
                        if health_code == 0:
                            release_fence(roots.STATE_ROOT / ACTIVE_NAME, token)
                    return 2
                if tx is not None:
                    tx.published_tools()
                    tx.register()
                _commit_checkpoint(roots, root_job_id, plan, directory, index, job_id)
                _state(directory, job_id=root_job_id, state="UPDATING", completed_hops=index + 1,
                       current_job_id=job_id, result_code="SYSTEM_UPDATE_SEQUENCE_CHECKPOINT")
                completed = index + 1
                _checkpoint("hop_committed", completed)
            files._new_json(directory / "completion.json", {"schema_version": SCHEMA, "job_id": root_job_id,
                "final_job_id": job_id, "plan_sha256": plan_sha256(plan), "completed_hops": completed,
                "pointer_sha256": read_current_release_result_from_state_root(roots.STATE_ROOT).raw_sha256})
            release_fence(roots.STATE_ROOT / ACTIVE_NAME, token)
            sync_state_root_directory(roots.STATE_ROOT)
            _state(directory, job_id=root_job_id, state="SUCCEEDED", completed_hops=len(sequence["hops"]),
                   current_job_id=job_id, result_code="SYSTEM_UPDATE_SUCCEEDED")
            return 0
        except Exception as exc:
            _state(directory, job_id=root_job_id, state="RECOVERY_REQUIRED", completed_hops=completed,
                   current_job_id=job_id, result_code=getattr(exc, "code", "SYSTEM_UPDATE_SEQUENCE_RECOVERY_REQUIRED"))
            return 2


def _checkpoint(stage, completed_hops):
    """Opt-in development harness hook; no external fault injection setting."""


def resume_sequence(roots, root_job_id, *, launcher=mvp._run_launcher):
    """Resume only a durable, fully successful boundary; never rerun a mutation."""
    plan, sequence, directory, proof = _root_plan(roots, root_job_id)
    with files._lease(directory / "runner.lock", proof["lease"]):
        _assert_active(roots, root_job_id, plan, directory)
        check_authorization(plan, sequence)
        state, _ = files._read(directory / "state.json")
        index = len(_checkpoints(roots, root_job_id, plan, sequence, directory))
        store = mvp.UpdateJobStore(roots)
        previous = store.read_status(state["current_job_id"])
        if previous["state"] != "SUCCEEDED":
            raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_CHECKPOINT_UNVERIFIED", status_code=409)
        current = read_current_release_result_from_state_root(roots.STATE_ROOT)
        if index == len(sequence["hops"]):
            checkpoints = _checkpoints(roots, root_job_id, plan, sequence, directory)
            if current.raw_sha256 != checkpoints[-1]["pointer_sha256"]:
                raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_CHECKPOINT_UNVERIFIED")
            health, _ = launcher(roots.RELEASE_ROOT / current.release.release_id, "health")
            if health != 0:
                raise mvp.UpdateMvpError("SYSTEM_UPDATE_RECOVERY_HEALTH_UNVERIFIED")
            completion = {"schema_version": SCHEMA, "job_id": root_job_id, "final_job_id": checkpoints[-1]["job_id"],
                "plan_sha256": plan_sha256(plan), "completed_hops": index, "pointer_sha256": current.raw_sha256}
            if files._exists(directory / "completion.json"):
                if files._read(directory / "completion.json")[0] != completion:
                    raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_CHECKPOINT_UNVERIFIED")
            else:
                files._new_json(directory / "completion.json", completion)
            release_fence(roots.STATE_ROOT / ACTIVE_NAME, _assert_active(roots, root_job_id, plan, directory))
            _state(directory, job_id=root_job_id, state="SUCCEEDED", completed_hops=index,
                   current_job_id=checkpoints[-1]["job_id"], result_code="SYSTEM_UPDATE_SUCCEEDED")
            return None
        previous_plan = store.read_plan(state["current_job_id"])
        # A healthy hop may have committed before its native registration or
        # sequence receipt returned. Complete that work; never execute it twice.
        if previous_plan["target_release_id"] == sequence["hops"][index]["release_id"]:
            hop = sequence["hops"][index]
            if current.release.release_id != hop["release_id"] or current.release.manifest_sha256 != hop["manifest_sha256"]:
                raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_CHECKPOINT_UNVERIFIED")
            health, _ = launcher(roots.RELEASE_ROOT / current.release.release_id, "health")
            if health != 0:
                raise mvp.UpdateMvpError("SYSTEM_UPDATE_RECOVERY_HEALTH_UNVERIFIED")
            if hop["tools_sha256"] is not None:
                original_roots = derive_portable_path_roots(PortableRootInputs(roots.INSTALL_ROOT,
                    Path(proof["local_app_data_base"])), previous_plan["source_release_id"])
                tx = _tools_transaction(original_roots, previous_plan["job_id"],
                    directory / hop["release_id"] / "tools", hop["tools_sha256"],
                    lambda: _assert_active(roots, root_job_id, plan, directory))
                tx.published_tools(); tx.register()
            _commit_checkpoint(roots, root_job_id, plan, directory, index, state["current_job_id"])
            index += 1
            _state(directory, job_id=root_job_id, state="UPDATING", completed_hops=index,
                   current_job_id=state["current_job_id"], result_code="SYSTEM_UPDATE_SEQUENCE_CHECKPOINT")
            if index == len(sequence["hops"]):
                token = _assert_active(roots, root_job_id, plan, directory)
                files._new_json(directory / "completion.json", {"schema_version": SCHEMA, "job_id": root_job_id,
                    "final_job_id": state["current_job_id"], "plan_sha256": plan_sha256(plan),
                    "completed_hops": index, "pointer_sha256": current.raw_sha256})
                release_fence(roots.STATE_ROOT / ACTIVE_NAME, token)
                _state(directory, job_id=root_job_id, state="SUCCEEDED", completed_hops=index,
                       current_job_id=state["current_job_id"], result_code="SYSTEM_UPDATE_SUCCEEDED")
                return None
        if current.release.release_id != sequence["hops"][index - 1]["release_id"]:
            raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_CHECKPOINT_UNVERIFIED", status_code=409)
        current_roots = derive_portable_path_roots(PortableRootInputs(roots.INSTALL_ROOT,
            Path(proof["local_app_data_base"])), current.release.release_id)
        # Prepare while the current source stays healthy; the accepted worker
        # takes the original source process lease and proves shutdown as usual.
        artifacts, manifest_path, archive, inventory = _hop_artifacts(roots, directory, sequence["hops"][index])
        prepared = mvp.UpdateMvpService(current_roots).prepare_from_artifacts(actor_user_id=plan["actor_user_id"],
            manifest_path=manifest_path, archive_path=archive, inventory_path=inventory,
            execution_context={"sequence_parent": root_job_id, "sequence_controller": plan["sequence_controller"]})
        job_id = prepared.job_id
        job_plan = store.read_plan(job_id)
        files._new_json(directory / ("hop-" + str(index) + ".json"), {"schema_version": SCHEMA,
            "root_job_id": root_job_id, "index": index, "job_id": job_id, "plan_sha256": plan_sha256(job_plan)})
        store.reserve_execution(job_id)
        store.write_status(job_id, "UPDATING", actor_user_id=plan["actor_user_id"], result_code="SYSTEM_UPDATE_STARTED",
                           source_release_id=job_plan["source_release_id"], target_release_id=job_plan["target_release_id"])
        _state(directory, job_id=root_job_id, state="UPDATING", completed_hops=index,
               current_job_id=job_id, result_code="SYSTEM_UPDATE_SEQUENCE_RESUMING")
        return job_id


def stop_sequence(roots, root_job_id, *, launcher=mvp._run_launcher):
    """Keep the attested current version/data and cancel the unexecuted suffix."""
    plan, sequence, directory, proof = _root_plan(roots, root_job_id)
    with files._lease(directory / "runner.lock", proof["lease"]):
        token = _assert_active(roots, root_job_id, plan, directory)
        state, _ = files._read(directory / "state.json")
        completed = len(_checkpoints(roots, root_job_id, plan, sequence, directory))
        store = mvp.UpdateJobStore(roots)
        status = store.read_status(state["current_job_id"])
        if status["state"] not in {"SUCCEEDED", "ROLLED_BACK", "FAILED", "RECOVERY_CLEARED"} or store.lock_path.exists():
            raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_CHECKPOINT_UNVERIFIED", status_code=409)
        if status["state"] == "RECOVERY_CLEARED":
            store.assert_no_unresolved_recovery()
            job_plan = store.read_plan(state["current_job_id"])
            if (completed >= len(sequence["hops"]) or job_plan["target_release_id"] != sequence["hops"][completed]["release_id"]
                    or job_plan["target_manifest_sha256"] != sequence["hops"][completed]["manifest_sha256"]
                    or (completed == 0 and job_plan["job_id"] != root_job_id)
                    or (completed > 0 and job_plan.get("sequence_parent") != root_job_id)):
                raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_CHECKPOINT_UNVERIFIED")
        current = read_current_release_result_from_state_root(roots.STATE_ROOT)
        allowed_hops = completed + (1 if status["state"] == "RECOVERY_CLEARED" else 0)
        valid = {plan["source_release_id"]: plan["source_manifest_sha256"],
                 **{hop["release_id"]: hop["manifest_sha256"] for hop in sequence["hops"][:allowed_hops]}}
        if valid.get(current.release.release_id) != current.release.manifest_sha256:
            raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_CHECKPOINT_UNVERIFIED", status_code=409)
        current_roots = derive_portable_path_roots(PortableRootInputs(roots.INSTALL_ROOT,
            Path(proof["local_app_data_base"])), current.release.release_id)
        if status["state"] == "RECOVERY_CLEARED" and completed < len(sequence["hops"]):
            hop = sequence["hops"][completed]
            if hop["tools_sha256"] is not None:
                original_roots = derive_portable_path_roots(PortableRootInputs(roots.INSTALL_ROOT,
                    Path(proof["local_app_data_base"])), job_plan["source_release_id"])
                tx = _tools_transaction(original_roots, job_plan["job_id"],
                    directory / hop["release_id"] / "tools", hop["tools_sha256"],
                    lambda: _assert_active(roots, root_job_id, plan, directory))
                stop, _ = launcher(current_roots.APP_ROOT, "stop")
                if stop != 0:
                    raise mvp.UpdateMvpError("SYSTEM_UPDATE_TARGET_STOP_UNCONFIRMED")
                if current.release.release_id == job_plan["target_release_id"]:
                    tx.publish()
                else:
                    tx.restore()
                tx.refresh(current.release.release_id)
                start, _ = launcher(current_roots.APP_ROOT, "start")
                if start != 0:
                    raise mvp.UpdateMvpError("SYSTEM_UPDATE_SOURCE_RECOVERY_FAILED")
                if current.release.release_id == job_plan["target_release_id"]:
                    tx.published_tools(); tx.register()
        health, _ = launcher(current_roots.APP_ROOT, "health")
        if health != 0:
            raise mvp.UpdateMvpError("SYSTEM_UPDATE_RECOVERY_HEALTH_UNVERIFIED")
        from enterprise.migrations.versioned import STATE_READY, inspect_schema_metadata
        from enterprise.release.release_manifest_v2 import verify_materialized_release
        manifest = read_release_manifest_v2(current_roots.APP_ROOT / "release-manifest.json")
        verification = verify_materialized_release(current_roots.APP_ROOT,
            inventory_path=current_roots.APP_ROOT / manifest.section("release_payload")["inventory_path"])
        database = inspect_schema_metadata(current_roots.DATA_ROOT / "enterprise.db")
        evidence = mvp._database_evidence(current_roots.APP_ROOT, manifest)
        from enterprise.migrations.sqlite_existing import open_existing_sqlite
        import sqlite3
        with open_existing_sqlite(current_roots.DATA_ROOT / "enterprise.db", mode="ro", error_type=sqlite3.OperationalError) as connection:
            if (connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]
                    or connection.execute("PRAGMA foreign_key_check").fetchone() is not None):
                raise mvp.UpdateMvpError("SYSTEM_UPDATE_RECOVERY_DATABASE_UNVERIFIED")
        if (verification.manifest_sha256 != current.release.manifest_sha256 or database.get("current_state") != STATE_READY
                or database.get("schema_sha256") != evidence.get("schema_objects_sha256")
                or database.get("schema_version") != evidence.get("schema_version")):
            raise mvp.UpdateMvpError("SYSTEM_UPDATE_SEQUENCE_CHECKPOINT_UNVERIFIED")
        release_fence(roots.STATE_ROOT / ACTIVE_NAME, token)
        _state(directory, job_id=root_job_id, state="FAILED", completed_hops=completed,
               current_job_id=state["current_job_id"], result_code="SYSTEM_UPDATE_SEQUENCE_STOPPED")
        return public_sequence(roots, root_job_id)
