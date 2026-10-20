"""Owned offline same-schema upgrade/reinstall through the shared update engine.

Application, native entry, retained Setup, and Windows registration have separate
checkpoints. Original native objects stay in the installation's recovery journal.
An interrupted operation never guesses a lock's age or restores a business DB.
"""
from __future__ import annotations

from configparser import ConfigParser
import hashlib
import io
import json
import os
from pathlib import Path
import uuid

from enterprise import install_cache as files, install_lifecycle as lifecycle
from enterprise import install_database_preparation as database_preparation
from enterprise.fresh_install import verify_release_assets
from enterprise.install_entry import ENTRY_NAME, _record, _snapshot, verify_entry_bundle, validate_installation_record
from enterprise.ops.update import mvp
from enterprise.ops.update.versions import compare_versions
from enterprise.paths import PortableRootInputs, derive_portable_path_roots, validate_path_roots_for_use
from enterprise.release.current_release import (
    read_current_release_result_from_state_root, sync_state_root_directory,
)
from enterprise.release.release_manifest_v2 import canonical_json, read_release_manifest_v2, verify_materialized_release
from enterprise.runtime.windows_owned_move import rename_owned, release_fence

PLAN_SCHEMA = "enterprise-offline-upgrade-plan-v1"
STATE_SCHEMA = "enterprise-offline-upgrade-state-v1"
ACTIVE_SCHEMA = "enterprise-offline-upgrade-active-v1"
ACTIVE_NAME = "install-upgrade-active.json"
SLOTS = {"entry": ENTRY_NAME, "record": "state/installation.json",
         "setup": "state/windows-maintenance/maintenance-setup.exe",
         "support": "state/windows-maintenance/support.ini"}
STATES = {"PREPARED", "SOURCE_RESTORED", "PREPARING_DATABASE", "READY", "EXECUTING", "AWAITING_REGISTRATION",
          "COMPLETE", "ROLLING_BACK", "ROLLED_BACK", "RECOVERY_REQUIRED"}
PLAN_KEYS = {"schema_version", "operation_id", "installation_id", "install_root", "root_identity",
             "local_app_data_base", "retained_source", "data_identity", "config_identity", "config",
             "source_release_id", "source_manifest_sha256", "source_pointer", "target_release_id",
             "target_manifest_sha256", "slots", "system_fence", "database_identity", "database_contract", "lease"}


class InstallUpgradeError(RuntimeError):
    def __init__(self, code="INSTALL_UPGRADE_RECOVERY_REQUIRED"):
        self.code = code
        super().__init__(code)


def _fail(code="INSTALL_UPGRADE_RECOVERY_REQUIRED"):
    raise InstallUpgradeError(code)


def _checkpoint(stage):
    """Owned tests may terminate their runner; no runtime injection setting."""


def _read(path):
    if files._io(files._safe(path)).stat().st_nlink == 2:
        value = lifecycle._read_fence(path)
        return value, hashlib.sha256(canonical_json(value)).hexdigest()
    value, digest = files._read(path)
    return value, digest


def _blob(path, data):
    files._safe(path, missing=True)
    with files._io(path).open("xb") as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    return files._file(path)


def _file_or_none(path):
    files._safe(path, missing=True)
    return files._file(path) if files._exists(path) else None


def _support(root, installation_id):
    setup, info = root / SLOTS["setup"], root / SLOTS["support"]
    left, right = _file_or_none(setup), _file_or_none(info)
    if left is None and right is None:
        return
    if left is None or right is None or right["size_bytes"] > 16384:
        _fail("INSTALL_UPGRADE_SUPPORT_UNPROVEN")
    raw = files._io(info).read_bytes()
    try:
        parser = ConfigParser(interpolation=None, strict=True)
        parser.read_string(raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"))
        values = dict(parser["Lifecycle"])
        if (parser.sections() != ["Lifecycle"] or set(values) not in (
                {"product", "installationid", "setupsha256", "setupsize"},
                {"product", "installationid", "setupsha256", "setupsize", "uninstaller", "uninstallersha256"})
                or values["product"] != "MEIS-DaCaiTou/Infinite-Canvas-Enterprise"
                or values["installationid"] != installation_id or values["setupsha256"] != left["sha256"]
                or values["setupsize"] != str(left["size_bytes"])):
            _fail("INSTALL_UPGRADE_SUPPORT_UNPROVEN")
    except (ValueError, KeyError, UnicodeError) as exc:
        raise InstallUpgradeError("INSTALL_UPGRADE_SUPPORT_UNPROVEN") from exc
    if files._file(info) != right or files._file(setup) != left:
        _fail("INSTALL_UPGRADE_SUPPORT_UNPROVEN")


def _eligible(roots, source, target):
    if compare_versions(str(source.section("identity")["release_version"]),
                        str(target.section("identity")["release_version"])) != "newer":
        _fail("INSTALL_UPGRADE_TARGET_NOT_NEWER")
    if (mvp._database_contract_mode(source, target) != "same-schema-no-migration"
            or source.section("database_contract")["schema_snapshot_sha256"]
            != target.section("database_contract")["schema_snapshot_sha256"]):
        _fail("INSTALL_UPGRADE_DATABASE_CONTRACT_UNSUPPORTED")
    metadata, preparation = database_preparation.inspect(roots)
    if metadata["schema_version"] not in {1, 2}:
        _fail("INSTALL_UPGRADE_DATABASE_CONTRACT_UNSUPPORTED")
    program = roots.APP_ROOT
    if not files._exists(program):
        directory, plan, _state = lifecycle._active(roots)
        program, _entry = lifecycle._placements(roots, directory, plan)
    evidence = mvp._database_evidence(program, source)
    if (evidence.get("schema_version") != metadata["schema_version"]
            or metadata["schema_sha256"] != evidence.get("schema_objects_sha256")):
        _fail("INSTALL_UPGRADE_DATABASE_CONTRACT_UNSUPPORTED")
    return metadata, preparation


def inspect_upgrade(*, install_root, release_dir, local_app_data_base):
    assets = verify_release_assets(Path(release_dir))
    if files._exists(Path(install_root) / "state" / ACTIVE_NAME):
        tx, state = _load(install_root, local_app_data_base, assets)
        # Read-only state is not proof that execution or registration completed.
        return tx.public("AWAITING_REGISTRATION" if state["state"] in {"AWAITING_REGISTRATION", "COMPLETE"}
                         else "RECOVERY_REQUIRED")
    roots, record, source = lifecycle.current_source(install_root=install_root, local_app_data_base=local_app_data_base)
    _metadata, preparation = _eligible(roots, source, assets.manifest)
    _support(roots.INSTALL_ROOT, record["installation_id"])
    return {"installation_id": record["installation_id"], "source_release_id": source.release_id,
            "target_release_id": assets.manifest.release_id, "upgrade_state": "ELIGIBLE",
            "database_update_mode": "same-schema-no-migration",
            "database_preparation_required": preparation is not None}


class _Transaction:
    def __init__(self, roots, directory, plan):
        self.roots, self.directory, self.plan = roots, directory, plan

    def state(self, name, **fields):
        if name not in STATES:
            _fail()
        files._state(self.directory / "state.json", {"schema_version": STATE_SCHEMA,
            "operation_id": self.plan["operation_id"], "state": name, **fields})

    def basics(self):
        p, r = self.plan, self.roots
        if (files._identity(r.INSTALL_ROOT) != p["root_identity"]
                or files._identity(r.DATA_ROOT) != p["data_identity"]
                or files._identity(r.CONFIG_ROOT) != p["config_identity"]
                or lifecycle._plain_file_identity(r.DATA_ROOT / "enterprise.db") != p["database_identity"]
                or files._file(r.CONFIG_ROOT / "enterprise.env") != p["config"]):
            _fail("INSTALL_UPGRADE_SOURCE_CHANGED")
        active, digest = _read(r.STATE_ROOT / ACTIVE_NAME)
        if (active != {"schema_version": ACTIVE_SCHEMA, "operation_id": p["operation_id"],
                       "installation_id": p["installation_id"], "plan_sha256": hashlib.sha256(canonical_json(p)).hexdigest()}
                or lifecycle._marker(r.STATE_ROOT / ACTIVE_NAME) != lifecycle._marker(self.directory / "active.json")):
            _fail()
        common = r.STATE_ROOT / "system-update-active.lock"
        if files._exists(common):
            marker = lifecycle._marker(common)
            if marker["identity"] != p["system_fence"]["identity"]:
                recovery = self.directory / "recovery-fence.json"
                if not files._exists(recovery) or marker != lifecycle._marker(recovery):
                    _fail("INSTALL_UPGRADE_FENCE_CHANGED")
            if marker != p["system_fence"]:
                status, _ = _read(self.directory / "state.json")
                payload, _ = _read(common)
                if (payload.get("schema_version") != mvp.LOCK_SCHEMA
                        or "job_id" not in status or payload.get("job_id") != status["job_id"]):
                    _fail("INSTALL_UPGRADE_FENCE_CHANGED")

    def slots(self):
        self.basics()
        result = {}
        for key, relative in SLOTS.items():
            spec = self.plan["slots"][key]
            if key == "support" and files._exists(self.directory / "registration.json"):
                registration, _ = _read(self.directory / "registration.json")
                if (set(registration) != {"schema_version", "operation_id", "support"}
                        or registration["schema_version"] != "enterprise-offline-registration-v1"
                        or registration["operation_id"] != self.plan["operation_id"]
                        or not _valid_file(registration["support"])
                        or registration["support"]["identity"] != spec["candidate"]["identity"]):
                    _fail()
                spec = {**spec, "candidate": registration["support"]}
            current = _file_or_none(self.roots.INSTALL_ROOT / relative)
            old = _file_or_none(self.directory / ("original-" + key))
            candidate = _file_or_none(self.directory / ("candidate-" + key))
            if (old not in (None, spec["before"]) or candidate not in (None, spec["candidate"])
                    or current not in (None, spec["before"], spec["candidate"])
                    or sum(value == spec["candidate"] for value in (current, candidate)) != 1
                    or (spec["before"] is not None and sum(value == spec["before"] for value in (current, old)) != 1)
                    or (spec["before"] is None and old is not None)):
                _fail("INSTALL_UPGRADE_TOOL_CHANGED")
            result[key] = (current, old, candidate)
        return result

    def publish(self):
        for key, relative in SLOTS.items():
            current, old, candidate = self.slots()[key]
            spec = self.plan["slots"][key]
            if current == spec["candidate"]:
                continue
            target = self.roots.INSTALL_ROOT / relative
            if spec["before"] is not None and current == spec["before"]:
                rename_owned(target, self.directory / ("original-" + key), spec["before"])
                sync_state_root_directory(target.parent)
                _checkpoint(key + "_retained")
            rename_owned(self.directory / ("candidate-" + key), target, spec["candidate"])
            sync_state_root_directory(target.parent)
            sync_state_root_directory(self.directory)
            _checkpoint(key + "_published")
        self.slots()

    def restore(self):
        for key, relative in reversed(tuple(SLOTS.items())):
            current, old, candidate = self.slots()[key]
            spec = self.plan["slots"][key]
            target = self.roots.INSTALL_ROOT / relative
            if current == spec["candidate"]:
                rename_owned(target, self.directory / ("candidate-" + key), spec["candidate"])
                _checkpoint(key + "_withdrawn")
            if spec["before"] is not None and old == spec["before"]:
                rename_owned(self.directory / ("original-" + key), target, spec["before"])
                _checkpoint(key + "_restored")
            sync_state_root_directory(target.parent)
        self.slots()

    def refresh(self, release_id):
        roots = derive_portable_path_roots(PortableRootInputs(self.roots.INSTALL_ROOT, Path(self.plan["local_app_data_base"])), release_id)
        manifest = read_release_manifest_v2(roots.APP_ROOT / "release-manifest.json")
        expected = self.plan["target_manifest_sha256"] if release_id == self.plan["target_release_id"] else self.plan["source_manifest_sha256"]
        if manifest.raw_sha256 != expected or manifest.release_id != release_id:
            _fail()
        lifecycle.refresh_installed_proof(roots, manifest)

    def inspect_database(self, database):
        """Supply shared-engine reads only from this proven stopped SQLite.

        Ordinary mode=ro opens of a stopped WAL-mode database can create empty
        WAL/SHM files. Keep the existing offline immutable inspection and its
        sidecar rejection; never delete or adopt such files after the fact.
        """
        if Path(database) != self.roots.DATA_ROOT / "enterprise.db":
            _fail("INSTALL_UPGRADE_DATABASE_CHANGED")
        self.basics()
        lifecycle._runtime_quiescent(self.roots)
        metadata = lifecycle._database_inspection(self.roots)
        if {key: metadata[key] for key in ("schema_version", "schema_sha256", "ledger_sha256")} != self.plan["database_contract"]:
            _fail("INSTALL_UPGRADE_DATABASE_CHANGED")
        return metadata

    def prepare_database(self):
        proof = self.plan.get("database_preparation")
        if proof is None:
            return
        self.basics()
        common = self.roots.STATE_ROOT / "system-update-active.lock"
        if not files._exists(common) or lifecycle._marker(common) != self.plan["system_fence"]:
            _fail("INSTALL_UPGRADE_FENCE_CHANGED")
        pointer = read_current_release_result_from_state_root(self.roots.STATE_ROOT)
        source = read_release_manifest_v2(self.roots.APP_ROOT / "release-manifest.json")
        if (pointer.raw_sha256 != self.plan["source_pointer"]
                or source.raw_sha256 != self.plan["source_manifest_sha256"]
                or files._file(self.roots.STATE_ROOT / "installation.json") != self.plan["slots"]["record"]["before"]
                or files._exists(self.roots.RUNTIME_ROOT / "runtime-reconcile.lock")):
            _fail("INSTALL_UPGRADE_SOURCE_CHANGED")
        lifecycle._runtime_quiescent(self.roots)
        self.state("PREPARING_DATABASE")
        _checkpoint("database_preparing")
        database_preparation.prepare(self.roots, proof, self.plan["database_contract"])
        _checkpoint("database_prepared")
        self.state("SOURCE_RESTORED")

    def published_tools(self):
        """Only Inno's proven support-object registration fields may change."""
        self.basics()
        _support(self.roots.INSTALL_ROOT, self.plan["installation_id"])
        for key, relative in SLOTS.items():
            spec = self.plan["slots"][key]
            current = files._file(self.roots.INSTALL_ROOT / relative)
            if (current["identity"] != spec["candidate"]["identity"]
                    or (key != "support" and current != spec["candidate"])
                    or _file_or_none(self.directory / ("candidate-" + key)) is not None
                    or _file_or_none(self.directory / ("original-" + key)) != spec["before"]):
                _fail("INSTALL_UPGRADE_TOOL_CHANGED")

    def launcher(self, app_root, command):
        if command == "start":
            if app_root.name == self.plan["target_release_id"]:
                self.publish()
            elif app_root.name == self.plan["source_release_id"]:
                self.restore()
            else:
                _fail()
            self.refresh(app_root.name)
        if command == "health" and app_root.name == self.plan["target_release_id"]:
            _checkpoint("target_health")
        return mvp._run_launcher(app_root, command)

    def release_active(self):
        self.basics()
        path = self.roots.STATE_ROOT / ACTIVE_NAME
        release_fence(path, lifecycle._marker(self.directory / "active.json"))
        sync_state_root_directory(self.roots.STATE_ROOT)

    def public(self, name):
        return {"operation_id": self.plan["operation_id"], "installation_id": self.plan["installation_id"],
                "source_release_id": self.plan["source_release_id"], "target_release_id": self.plan["target_release_id"],
                "upgrade_state": name, "database_update_mode": "same-schema-no-migration"}


def _transfer_lock(roots, token, job_id):
    """Rewrite the owned fence in place: there is never an unlocked startup gap."""
    path = roots.STATE_ROOT / "system-update-active.lock"
    if lifecycle._marker(path) != token:
        _fail()
    with files._io(path).open("r+b") as stream:
        if files._fd_identity(stream) != token["identity"]:
            _fail()
        raw = stream.read(16384)
        if hashlib.sha256(raw).hexdigest() != token["sha256"]:
            _fail()
        data = canonical_json({"schema_version": mvp.LOCK_SCHEMA, "job_id": job_id, "created_at": mvp.utc_now()})
        stream.seek(0); stream.write(data); stream.truncate(); stream.flush(); os.fsync(stream.fileno())
        if files._fd_identity(stream) != token["identity"]:
            _fail()
    sync_state_root_directory(roots.STATE_ROOT)


def upgrade_retained(*, install_root, release_dir, native_entry_dir, setup_executable,
                     local_app_data_base, confirm_no_active_tasks=False, notify_progress=None):
    if confirm_no_active_tasks is not True:
        _fail("INSTALL_UPGRADE_TASK_CONFIRMATION_REQUIRED")
    root = files._safe(Path(install_root))
    if files._exists(root / "state" / ACTIVE_NAME):
        _fail("INSTALL_UPGRADE_EXPLICIT_RECOVERY_REQUIRED")
    assets = verify_release_assets(Path(release_dir))
    roots, record, source = lifecycle.current_source(install_root=root, local_app_data_base=local_app_data_base)
    metadata, preparation = _eligible(roots, source, assets.manifest)
    _support(root, record["installation_id"])
    identity = assets.manifest.section("enterprise_source")
    entry = verify_entry_bundle(Path(native_entry_dir), commit=identity["commit"], tree=identity["tree"])
    setup = files._safe(Path(setup_executable))
    setup_token = files._file(setup)
    if not 1 <= setup_token["size_bytes"] <= 512 * 1024 * 1024:
        _fail("INSTALL_UPGRADE_SETUP_UNPROVEN")
    setup_bytes = files._io(setup).read_bytes()
    if (not setup_bytes.startswith(b"MZ") or hashlib.sha256(setup_bytes).hexdigest() != setup_token["sha256"]
            or files._file(setup) != setup_token):
        _fail("INSTALL_UPGRADE_SETUP_UNPROVEN")
    # Source restoration retains its existing startup fence for the parent
    # transaction; installed sources acquire a create-only equivalent fence.
    lock = roots.STATE_ROOT / "system-update-active.lock"
    retained_source = files._exists(lock)
    entry_source = root / ENTRY_NAME
    if retained_source:
        old_directory, previous, state = lifecycle._active(roots)
        _program, entry_source = lifecycle._placements(roots, old_directory, previous)
        fence = lifecycle._marker(lock)
    else:
        fence = None
    if files._file(entry_source)["sha256"] != record["native_entry"]["sha256"]:
        _fail("INSTALL_UPGRADE_SOURCE_ENTRY_UNPROVEN")
    operation = uuid.uuid4().hex
    directory = roots.STATE_ROOT / "install-upgrades" / operation
    files._safe(directory, missing=True)
    files._io(directory).mkdir(parents=True, exist_ok=False)
    with files._io(directory / "runner.lock").open("xb") as stream:
        stream.write(b"C"); stream.flush(); os.fsync(stream.fileno())
    support_directory = roots.STATE_ROOT / "windows-maintenance"
    files._safe(support_directory, missing=True)
    files._io(support_directory).mkdir(exist_ok=True)
    parser = ConfigParser(interpolation=None)
    parser.optionxform = str
    parser["Lifecycle"] = {"Product": "MEIS-DaCaiTou/Infinite-Canvas-Enterprise", "InstallationId": record["installation_id"],
        "SetupSha256": setup_token["sha256"], "SetupSize": str(setup_token["size_bytes"])}
    text = io.StringIO(); parser.write(text)
    payloads = {"entry": entry.data, "record": canonical_json(_record(root, entry, _snapshot(root / SLOTS["record"]))),
                "setup": setup_bytes, "support": text.getvalue().encode("ascii")}
    slots = {key: {"before": _file_or_none(entry_source if key == "entry" else root / relative),
                   "candidate": _blob(directory / ("candidate-" + key), payloads[key])}
             for key, relative in SLOTS.items()}
    if fence is None:
        files._new_json(directory / "system-fence.json", {"schema_version": ACTIVE_SCHEMA,
            "operation_id": operation, "installation_id": record["installation_id"]})
        fence = lifecycle._marker(directory / "system-fence.json")
    plan = {"schema_version": PLAN_SCHEMA, "operation_id": operation, "installation_id": record["installation_id"],
        "install_root": str(root), "root_identity": files._identity(root),
        "local_app_data_base": str(Path(local_app_data_base)), "retained_source": retained_source,
        "data_identity": files._identity(roots.DATA_ROOT), "config_identity": files._identity(roots.CONFIG_ROOT),
        "config": files._file(roots.CONFIG_ROOT / "enterprise.env"), "source_release_id": source.release_id,
        "source_manifest_sha256": source.raw_sha256, "source_pointer": read_current_release_result_from_state_root(roots.STATE_ROOT).raw_sha256,
        "target_release_id": assets.manifest.release_id, "target_manifest_sha256": assets.manifest.raw_sha256,
        "slots": slots, "system_fence": fence,
        "database_identity": lifecycle._plain_file_identity(roots.DATA_ROOT / "enterprise.db"),
        "database_contract": {key: metadata[key] for key in ("schema_version", "schema_sha256", "ledger_sha256")},
        "lease": files._file(directory / "runner.lock")["identity"]}
    if preparation is not None:
        plan["database_preparation"] = preparation
    files._new_json(directory / "plan.json", plan)
    files._new_json(directory / "active.json", {"schema_version": ACTIVE_SCHEMA, "operation_id": operation,
        "installation_id": record["installation_id"], "plan_sha256": hashlib.sha256(canonical_json(plan)).hexdigest()})
    tx = _Transaction(roots, directory, plan)
    with files._lease(directory / "runner.lock", plan["lease"]):
        # State and immutable proof are durable before publishing ownership.
        tx.state("PREPARED")
        sync_state_root_directory(directory)
        os.link(files._io(directory / "active.json"), files._io(roots.STATE_ROOT / ACTIVE_NAME))
        sync_state_root_directory(roots.STATE_ROOT)
        _checkpoint("active_published")
        if not retained_source:
            os.link(files._io(directory / "system-fence.json"), files._io(lock))
        sync_state_root_directory(roots.STATE_ROOT)
        _checkpoint("fence_published")
        if retained_source:
            lifecycle._reinstall(roots, record, keep_fence=True)
        tx.state("SOURCE_RESTORED")
        lifecycle._runtime_quiescent(roots)
        tx.prepare_database()
        _checkpoint("source_fenced")
        prepared = mvp.UpdateMvpService(roots, database_inspector=tx.inspect_database).prepare_from_artifacts(actor_user_id="local-installation-owner:" + record["installation_id"],
            manifest_path=assets.manifest_path, archive_path=assets.archive_path, inventory_path=assets.inventory_path)
        store = mvp.UpdateJobStore(roots)
        if prepared.database_update_mode != "same-schema-no-migration":
            _fail("INSTALL_UPGRADE_DATABASE_CONTRACT_UNSUPPORTED")
        files._new_json(directory / "job.json", {"schema_version": "enterprise-offline-upgrade-job-v1",
            "operation_id": operation, "plan_sha256": hashlib.sha256(canonical_json(plan)).hexdigest(),
            "job_id": prepared.job_id, "job_plan_sha256": hashlib.sha256(canonical_json(store.read_plan(prepared.job_id))).hexdigest()})
        _checkpoint("job_bound")
        tx.state("READY", job_id=prepared.job_id)
        _checkpoint("upgrade_ready")
        status = store.read_status(prepared.job_id)
        store.write_status(prepared.job_id, "UPDATING", actor_user_id=status["actor_user_id"], result_code="SYSTEM_UPDATE_STARTED",
            source_release_id=source.release_id, target_release_id=assets.manifest.release_id)
        _transfer_lock(roots, fence, prepared.job_id)
        tx.state("EXECUTING", job_id=prepared.job_id)
        if notify_progress is not None:
            notify_progress("UPGRADING", operation)
        mvp.execute_update_job(roots, prepared.job_id, launcher=tx.launcher, database_inspector=tx.inspect_database)
        result = store.read_status(prepared.job_id)
        if result["state"] == "SUCCEEDED":
            tx.state("AWAITING_REGISTRATION", job_id=prepared.job_id)
            _checkpoint("awaiting_registration")
            return tx.public("AWAITING_REGISTRATION")
        if result["state"] in {"FAILED", "ROLLED_BACK"}:
            tx.restore()
            tx.state("ROLLED_BACK", job_id=prepared.job_id)
            tx.release_active()
            return tx.public("ROLLED_BACK")
        tx.state("RECOVERY_REQUIRED", job_id=prepared.job_id)
        _fail()


def _valid_file(value):
    return (type(value) is dict and set(value) == {"identity", "size_bytes", "sha256"}
            and files._valid_identity(value["identity"]) and type(value["size_bytes"]) is int
            and 0 <= value["size_bytes"] <= files.MAX_FILE_BYTES
            and type(value["sha256"]) is str and files.SHA.fullmatch(value["sha256"]))


def _load(install_root, local_app_data_base, assets):
    root = files._safe(Path(install_root))
    active, _ = _read(root / "state" / ACTIVE_NAME)
    if (set(active) != {"schema_version", "operation_id", "installation_id", "plan_sha256"}
            or active["schema_version"] != ACTIVE_SCHEMA
            or type(active["operation_id"]) is not str or not files.ID.fullmatch(active["operation_id"])):
        _fail()
    directory = root / "state/install-upgrades" / active["operation_id"]
    plan, digest = _read(directory / "plan.json")
    if (set(plan) not in (PLAN_KEYS, PLAN_KEYS | {"database_preparation"}) or plan["schema_version"] != PLAN_SCHEMA
            or plan["operation_id"] != active["operation_id"] or plan["installation_id"] != active["installation_id"]
            or digest != active["plan_sha256"] or plan["install_root"] != str(root)
            or plan["local_app_data_base"] != str(Path(local_app_data_base))
            or plan["target_release_id"] != assets.manifest.release_id
            or plan["target_manifest_sha256"] != assets.manifest.raw_sha256
            or type(plan["retained_source"]) is not bool or not files.ID.fullmatch(str(plan["installation_id"]))
            or not all(files._valid_identity(plan[name]) for name in ("root_identity", "lease", "data_identity", "config_identity", "database_identity"))
            or not _valid_file(plan["config"]) or not _valid_file(plan["system_fence"])
            or type(plan["slots"]) is not dict or set(plan["slots"]) != set(SLOTS)
            or any(type(plan[name]) is not str or not files.SHA.fullmatch(plan[name])
                   for name in ("source_manifest_sha256", "source_pointer", "target_manifest_sha256"))
            or type(plan["database_contract"]) is not dict
            or set(plan["database_contract"]) != {"schema_version", "schema_sha256", "ledger_sha256"}
            or type(plan["database_contract"]["schema_version"]) is not int
            or plan["database_contract"]["schema_version"] not in {1, 2}
            or any(type(plan["database_contract"][name]) is not str or not files.SHA.fullmatch(plan["database_contract"][name])
                   for name in ("schema_sha256", "ledger_sha256"))):
        _fail()
    if "database_preparation" in plan:
        proof = plan["database_preparation"]
        if (plan["retained_source"] or type(proof) is not dict or set(proof) != {"database", "sidecars"}
                or not _valid_file(proof["database"]) or proof["database"]["identity"] != plan["database_identity"]
                or type(proof["sidecars"]) is not dict or set(proof["sidecars"]) != {"-wal", "-shm"}
                or not any(proof["sidecars"].values())
                or any(token is not None and (not _valid_file(token) or token["size_bytes"] != size)
                       for suffix, size in (("-wal", 0), ("-shm", 32768))
                       for token in (proof["sidecars"][suffix],))):
            _fail()
    for spec in plan["slots"].values():
        if (type(spec) is not dict or set(spec) != {"before", "candidate"}
                or not _valid_file(spec["candidate"]) or (spec["before"] is not None and not _valid_file(spec["before"]))):
            _fail()
    roots = derive_portable_path_roots(PortableRootInputs(root, Path(local_app_data_base)), plan["source_release_id"])
    validate_path_roots_for_use(roots)
    tx = _Transaction(roots, directory, plan)
    tx.basics()
    state, _ = _read(directory / "state.json")
    if (state.get("schema_version") != STATE_SCHEMA or state.get("operation_id") != plan["operation_id"]
            or state.get("state") not in STATES or set(state) - {"schema_version", "operation_id", "state", "job_id"}):
        _fail()
    if "job_id" in state:
        mvp.UpdateJobStore.validate_job_id(state["job_id"])
    bound = directory / "job.json"
    if files._exists(bound):
        receipt, _ = _read(bound)
        if (set(receipt) != {"schema_version", "operation_id", "plan_sha256", "job_id", "job_plan_sha256"}
                or receipt["schema_version"] != "enterprise-offline-upgrade-job-v1"
                or receipt["operation_id"] != plan["operation_id"] or receipt["plan_sha256"] != digest
                or ("job_id" in state and state["job_id"] != receipt["job_id"])):
            _fail("INSTALL_UPGRADE_JOB_CHANGED")
        mvp.UpdateJobStore.validate_job_id(receipt["job_id"])
        job_plan = mvp.UpdateJobStore(roots).read_plan(receipt["job_id"])
        if hashlib.sha256(canonical_json(job_plan)).hexdigest() != receipt["job_plan_sha256"]:
            _fail("INSTALL_UPGRADE_JOB_CHANGED")
        state = {**state, "job_id": receipt["job_id"]}
    elif "job_id" in state:
        _fail("INSTALL_UPGRADE_JOB_CHANGED")
    return tx, state


def recover_upgrade(*, install_root, release_dir, local_app_data_base, confirm_no_active_tasks=False):
    """Explicit interrupted-operation recovery; same-schema data is never restored.

    Stop a proven target before reverting its pointer/tools. A successful engine
    result is only finalized, never downgraded after it may have served data.
    """
    if confirm_no_active_tasks is not True:
        _fail("INSTALL_UPGRADE_TASK_CONFIRMATION_REQUIRED")
    assets = verify_release_assets(Path(release_dir))
    tx, state = _load(install_root, local_app_data_base, assets)
    with files._lease(tx.directory / "runner.lock", tx.plan["lease"]):
        job_id = state.get("job_id")
        if job_id is None:
            # The parent has not delegated its fence to the update engine.
            # Complete an interrupted old-source object restoration only.
            if tx.plan["retained_source"]:
                record = validate_installation_record(tx.roots.INSTALL_ROOT, _snapshot(tx.roots.STATE_ROOT / "installation.json"))
                lifecycle._reinstall(tx.roots, record, keep_fence=True)
            lifecycle._runtime_quiescent(tx.roots)
            if "database_preparation" in tx.plan:
                lock = tx.roots.STATE_ROOT / "system-update-active.lock"
                if not files._exists(lock):
                    # Explicit recovery of death between active and fence
                    # publication; create-only linking never adopts a foreign lock.
                    os.link(files._io(tx.directory / "system-fence.json"), files._io(lock))
                    sync_state_root_directory(tx.roots.STATE_ROOT)
                tx.prepare_database()
            tx.restore()
            pointer = read_current_release_result_from_state_root(tx.roots.STATE_ROOT)
            source = read_release_manifest_v2(tx.roots.APP_ROOT / "release-manifest.json")
            verify_materialized_release(tx.roots.APP_ROOT, inventory_path=tx.roots.APP_ROOT / "release-payload-inventory.json")
            if (pointer.raw_sha256 != tx.plan["source_pointer"] or source.raw_sha256 != tx.plan["source_manifest_sha256"]
                    or lifecycle._database_contract(tx.roots) != tx.plan["database_contract"]):
                _fail()
            lock = tx.roots.STATE_ROOT / "system-update-active.lock"
            if files._exists(lock):
                if lifecycle._marker(lock) != tx.plan["system_fence"]:
                    _fail()
                release_fence(lock, tx.plan["system_fence"])
            elif tx.plan["retained_source"] or lifecycle._marker(tx.directory / "system-fence.json") != tx.plan["system_fence"]:
                _fail()
            tx.state("ROLLED_BACK")
            tx.release_active()
            return tx.public("ROLLED_BACK")
        store = mvp.UpdateJobStore(tx.roots)
        job = store.read_status(job_id)
        plan = store.read_plan(job_id)
        if (plan.get("source_release_id") != tx.plan["source_release_id"]
                or plan.get("source_manifest_sha256") != tx.plan["source_manifest_sha256"]
                or plan.get("target_release_id") != tx.plan["target_release_id"]
                or plan.get("target_manifest_sha256") != tx.plan["target_manifest_sha256"]
                or job.get("actor_user_id") != plan.get("actor_user_id")
                or plan.get("database_update", {}).get("mode") != "same-schema-no-migration"):
            _fail()
        if job["state"] == "SUCCEEDED":
            tx.published_tools()
            pointer = read_current_release_result_from_state_root(tx.roots.STATE_ROOT)
            if pointer.release.manifest_sha256 != tx.plan["target_manifest_sha256"]:
                _fail()
            tx.state("AWAITING_REGISTRATION", job_id=job_id)
            return tx.public("AWAITING_REGISTRATION")
        lock = store.lock_path
        if files._exists(lock):
            marker = lifecycle._marker(lock)
            payload, _ = _read(lock)
            if marker == tx.plan["system_fence"] and state["state"] in {"SOURCE_RESTORED", "READY"}:
                _transfer_lock(tx.roots, marker, job_id)
                marker = lifecycle._marker(lock)
            elif (marker["identity"] != tx.plan["system_fence"]["identity"] or payload.get("job_id") != job_id
                  or payload.get("schema_version") != mvp.LOCK_SCHEMA):
                if (not files._exists(tx.directory / "recovery-fence.json")
                        or marker != lifecycle._marker(tx.directory / "recovery-fence.json")
                        or payload.get("job_id") != job_id or payload.get("schema_version") != mvp.LOCK_SCHEMA):
                    _fail()
        else:
            # Exception unwind can release the MVP handle before its terminal
            # status is written. The separate active marker and kernel runner
            # lease still prove this exact offline operation; never use age/PID.
            if job["state"] not in {"READY", "UPDATING", "RESTARTING", "VERIFYING", "ROLLING_BACK", "FAILED", "ROLLED_BACK", "RECOVERY_REQUIRED"}:
                _fail()
            recovery = tx.directory / "recovery-fence.json"
            if files._exists(recovery):
                payload, _ = _read(recovery)
                if set(payload) != {"schema_version", "job_id", "created_at"} or payload.get("schema_version") != mvp.LOCK_SCHEMA or payload.get("job_id") != job_id:
                    _fail()
            else:
                files._new_json(recovery, {"schema_version": mvp.LOCK_SCHEMA,
                    "job_id": job_id, "created_at": mvp.utc_now()})
            os.link(files._io(tx.directory / "recovery-fence.json"), files._io(lock))
            marker = lifecycle._marker(lock)
        tx.state("ROLLING_BACK", job_id=job_id)
        target = tx.roots.RELEASE_ROOT / tx.plan["target_release_id"]
        if target.exists():
            manifest = read_release_manifest_v2(target / "release-manifest.json")
            if manifest.raw_sha256 != tx.plan["target_manifest_sha256"]:
                _fail()
            verify_materialized_release(target, inventory_path=target / "release-payload-inventory.json")
            code, details = mvp._run_launcher(target, "stop")
            if code != 0 or not details:
                _fail("INSTALL_UPGRADE_TARGET_STOP_UNCONFIRMED")
        lifecycle._runtime_quiescent(tx.roots)
        if lifecycle._database_contract(tx.roots) != tx.plan["database_contract"]:
            _fail("INSTALL_UPGRADE_DATABASE_CHANGED")
        source = read_release_manifest_v2(tx.roots.APP_ROOT / "release-manifest.json")
        if source.raw_sha256 != tx.plan["source_manifest_sha256"]:
            _fail()
        verify_materialized_release(tx.roots.APP_ROOT, inventory_path=tx.roots.APP_ROOT / "release-payload-inventory.json")
        pointer = read_current_release_result_from_state_root(tx.roots.STATE_ROOT)
        if pointer.release.release_id == tx.plan["target_release_id"]:
            mvp.restore_source_pointer(tx.roots, source, tx.plan["target_release_id"],
                expected_current_raw_sha256=pointer.raw_sha256)
        elif pointer.release.manifest_sha256 != tx.plan["source_manifest_sha256"]:
            _fail()
        tx.restore()
        tx.refresh(source.release_id)
        store.write_status(job_id, "ROLLED_BACK", actor_user_id=job["actor_user_id"], result_code="SYSTEM_UPDATE_ROLLED_BACK",
            source_release_id=source.release_id, target_release_id=tx.plan["target_release_id"])
        release_fence(lock, marker)
        tx.state("ROLLED_BACK", job_id=job_id)
        tx.release_active()
        return tx.public("ROLLED_BACK")


def finish_upgrade(*, install_root, release_dir, local_app_data_base, verify_registration):
    """Finalize only after the target Setup/uninstaller registration is proven."""
    assets = verify_release_assets(Path(release_dir))
    tx, state = _load(install_root, local_app_data_base, assets)
    with files._lease(tx.directory / "runner.lock", tx.plan["lease"]):
        if state["state"] not in {"AWAITING_REGISTRATION", "COMPLETE"} or "job_id" not in state:
            _fail()
        job = mvp.UpdateJobStore(tx.roots).read_status(state["job_id"])
        pointer = read_current_release_result_from_state_root(tx.roots.STATE_ROOT)
        if job["state"] != "SUCCEEDED" or pointer.release.manifest_sha256 != tx.plan["target_manifest_sha256"]:
            _fail()
        tx.published_tools()
        target = tx.roots.RELEASE_ROOT / tx.plan["target_release_id"]
        verify_materialized_release(target, inventory_path=target / "release-payload-inventory.json")
        _support(tx.roots.INSTALL_ROOT, tx.plan["installation_id"])
        verify_registration(tx.roots.INSTALL_ROOT, tx.plan["installation_id"])
        support = files._file(tx.roots.INSTALL_ROOT / SLOTS["support"])
        if support["identity"] != tx.plan["slots"]["support"]["candidate"]["identity"]:
            _fail("INSTALL_UPGRADE_SUPPORT_CHANGED")
        registration_path = tx.directory / "registration.json"
        registration = {"schema_version": "enterprise-offline-registration-v1", "operation_id": tx.plan["operation_id"], "support": support}
        if files._exists(registration_path):
            if _read(registration_path)[0] != registration:
                _fail()
        else:
            files._new_json(registration_path, registration)
        current_slots = tx.slots()
        if any(current != tx.plan["slots"][key]["candidate"] for key, (current, _old, _candidate) in current_slots.items() if key != "support"):
            _fail()
        tx.state("COMPLETE", job_id=state["job_id"])
        tx.release_active()
        return tx.public("COMPLETE")
