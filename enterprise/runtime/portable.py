"""Portable-release trust orchestration layered over the accepted B1 primitives.

This module establishes identity and then delegates lifecycle ownership to the
existing STAB-1 controller/supervisor.  It intentionally contains no second
lock, process supervisor, state store, or activation protocol.
"""

from __future__ import annotations

import ctypes
import os
import platform
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from enterprise.path_safety import PathSafetyError, assert_no_reparse_ancestors, has_reparse_point
from enterprise.paths import (
    PathRoots,
    PathRootsError,
    PortableRootInputs,
    derive_portable_path_roots,
    derive_portable_root_layout,
    install_path_roots_for_process,
    validate_portable_release_layout,
)
from enterprise.release.current_release import (
    CurrentReleaseError,
    CurrentReleaseReadResult,
    read_current_release_result_from_state_root,
)
from enterprise.release.release_manifest_v2 import (
    ReleaseManifestV2,
    ReleaseManifestV2Error,
    enforce_portable_contract_compatibility,
    read_release_manifest_v2,
    verify_materialized_release,
)

from .error_contract import RuntimeContractError, error_payload
from .launch_context import LAUNCH_CONTEXT_FILENAME, RuntimeLaunchContext, read_launch_context
from .mode import parse_runtime_mode
from .preflight import StartupPreflightResult, build_startup_preflight_result
from .python_identity import PythonIdentity, build_python_identity
from .runtime_manifest import RuntimeManifestStartupView, parse_runtime_manifest_startup_view
from .writable_probe import WritableProbeResult, probe_writable_root


PORTABLE_COMMANDS = frozenset({"start", "stop", "restart", "status", "health"})
_PROBE_ROOTS = (
    ("DATA_ROOT", "DATA_ROOT"),
    ("LOG_ROOT", "LOG_ROOT"),
    ("RUNTIME_ROOT", "RUNTIME_ROOT"),
    ("CACHE_ROOT", "CACHE_ROOT"),
    ("TEMP_ROOT", "TEMP_ROOT"),
)


def _prepare_writable_probe_roots(roots: PathRoots) -> None:
    """Create the bounded portable writable roots before probing them.

    A clean Windows profile has no per-user runtime/cache/temp directories yet.
    Creation therefore uses the existing pre-use/post-create reparse checks;
    the subsequent writable probes remain the authoritative preflight check.
    """

    for attribute, label in _PROBE_ROOTS:
        root = Path(getattr(roots, attribute))
        try:
            assert_no_reparse_ancestors(root, allow_missing=True)
            root.mkdir(parents=True, exist_ok=True)
            assert_no_reparse_ancestors(root)
            if not root.is_dir() or has_reparse_point(root):
                raise PathSafetyError("path-invalid")
        except (OSError, PathSafetyError) as exc:
            raise RuntimeContractError("WRITABLE_PROBE_CREATE_FAILED", details={"label": label}) from exc


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(os.path.normpath(os.fspath(left)))) == os.path.normcase(
        os.path.abspath(os.path.normpath(os.fspath(right)))
    )


def _assert_regular_no_reparse(path: Path, *, code: str) -> None:
    try:
        assert_no_reparse_ancestors(path)
        if not path.is_file() or has_reparse_point(path):
            raise PathSafetyError("path-invalid")
    except (OSError, PathSafetyError) as exc:
        raise RuntimeContractError(code) from exc


def _derive_install_root(app_root: Path) -> Path:
    app_root = Path(app_root).absolute()
    try:
        assert_no_reparse_ancestors(app_root)
        if not app_root.is_dir() or has_reparse_point(app_root):
            raise PathSafetyError("path-invalid")
    except (OSError, PathSafetyError) as exc:
        raise RuntimeContractError("PORTABLE_RELEASE_LAYOUT_INVALID") from exc
    release_root = app_root.parent
    if release_root.name.casefold() != "releases" or release_root.parent == release_root:
        raise RuntimeContractError("PORTABLE_RELEASE_LAYOUT_INVALID")
    return release_root.parent


def windows_local_app_data_known_folder() -> Path:
    """Read FOLDERID_LocalAppData without trusting an environment override."""

    if os.name != "nt":
        raise RuntimeContractError("PORTABLE_PLATFORM_UNSUPPORTED")
    # FOLDERID_LocalAppData = F1B32785-6FBA-4FCF-9D55-7B8E7F157091
    from ctypes import wintypes
    import uuid

    class GUID(ctypes.Structure):
        _fields_ = (
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        )

    raw = uuid.UUID("f1b32785-6fba-4fcf-9d55-7b8e7f157091").bytes_le
    folder_id = GUID.from_buffer_copy(raw)
    target = ctypes.c_wchar_p()
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    result = shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(target))
    if result != 0 or not target.value:
        raise RuntimeContractError("PORTABLE_LOCALAPPDATA_UNAVAILABLE")
    try:
        return Path(target.value).absolute()
    finally:
        ole32.CoTaskMemFree(target)


def in_process_python_probe() -> dict[str, object]:
    return {
        "implementation": sys.implementation.name,
        "version": platform.python_version(),
        "cache_tag": sys.implementation.cache_tag,
        "machine": platform.machine(),
        "pointer_bits": ctypes.sizeof(ctypes.c_void_p) * 8,
        "executable": sys.executable,
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
        "soabi": sysconfig.get_config_var("SOABI"),
        "dont_write_bytecode": sys.dont_write_bytecode,
        "no_user_site": bool(sys.flags.no_user_site),
    }


@dataclass(frozen=True)
class PortablePreflight:
    roots: PathRoots
    current_release: CurrentReleaseReadResult
    release_manifest: ReleaseManifestV2
    runtime_manifest: RuntimeManifestStartupView
    python_identity: PythonIdentity
    writable_probes: tuple[WritableProbeResult, ...]
    result: StartupPreflightResult


def build_portable_preflight(
    app_root: Path,
    *,
    local_app_data_resolver: Callable[[], Path] = windows_local_app_data_known_folder,
    executable: Path | None = None,
    python_probe: dict[str, object] | None = None,
    probe: Callable[[Path, str], WritableProbeResult] = probe_writable_root,
    verify_full_payload: bool = True,
) -> PortablePreflight:
    """Run the full read-only trust chain plus self-cleaning writable probes."""

    app_root = Path(app_root).absolute()
    install_root = _derive_install_root(app_root)
    inputs = PortableRootInputs(install_root=install_root, local_app_data_base=local_app_data_resolver())
    layout = derive_portable_root_layout(inputs)
    pointer = read_current_release_result_from_state_root(layout.STATE_ROOT)
    roots = derive_portable_path_roots(inputs, pointer.release.release_id)
    pointer_app = roots.INSTALL_ROOT.joinpath(*pointer.release.app_root_relative.split("/"))
    if not _same_path(pointer_app, app_root) or not _same_path(roots.APP_ROOT, app_root):
        raise RuntimeContractError("PORTABLE_RELEASE_POINTER_MISMATCH")
    try:
        validate_portable_release_layout(roots)
    except PathRootsError as exc:
        raise RuntimeContractError("PORTABLE_RELEASE_LAYOUT_INVALID") from exc
    try:
        release_manifest = read_release_manifest_v2(app_root / "release-manifest.json")
        if release_manifest.raw_sha256 != pointer.release.manifest_sha256 or release_manifest.release_id != pointer.release.release_id:
            raise ReleaseManifestV2Error("RELEASE_POINTER_MANIFEST_MISMATCH")
        enforce_portable_contract_compatibility(release_manifest)
        inventory_path = app_root / str(release_manifest.section("release_payload")["inventory_path"])
        if verify_full_payload:
            verify_materialized_release(app_root, inventory_path=inventory_path)
    except ReleaseManifestV2Error as exc:
        if exc.code == "RELEASE_COMPATIBILITY_UNSUPPORTED":
            raise RuntimeContractError("PORTABLE_RELEASE_CONTRACT_UNSUPPORTED") from exc
        raise RuntimeContractError("PORTABLE_RELEASE_MANIFEST_INVALID") from exc
    runtime_manifest_relative = str(release_manifest.section("runtime")["runtime_manifest_path"])
    manifest = parse_runtime_manifest_startup_view(app_root / runtime_manifest_relative, roots.PYTHON_RUNTIME)
    if manifest.manifest_sha256 != release_manifest.section("runtime")["runtime_manifest_sha256"]:
        raise RuntimeContractError("PORTABLE_RELEASE_MANIFEST_INVALID")
    fixed_executable = roots.PYTHON_RUNTIME / "python.exe"
    actual_executable = Path(sys.executable if executable is None else executable)
    identity = build_python_identity(
        actual_executable,
        in_process_python_probe() if python_probe is None else python_probe,
        expected_executable=fixed_executable,
        expected_runtime_root=roots.PYTHON_RUNTIME,
    )
    _prepare_writable_probe_roots(roots)
    probes = tuple(probe(Path(getattr(roots, attribute)), label) for attribute, label in _PROBE_ROOTS)
    result = build_startup_preflight_result(
        mode=parse_runtime_mode("portable-release"),
        release_id=pointer.release.release_id,
        path_roots_identity=roots.root_identity,
        current_release_sha256=pointer.raw_sha256,
        release_manifest=release_manifest,
        runtime_manifest=manifest,
        python_identity=identity,
        writable_probe_results=probes,
    )
    return PortablePreflight(roots, pointer, release_manifest, manifest, identity, probes, result)


@dataclass(frozen=True)
class PortableProcessBinding:
    roots: PathRoots
    context: RuntimeLaunchContext


def validate_portable_process_binding(
    *,
    app_root: Path,
    runtime_root: Path,
    instance_id: str,
    expected_context_identity: str,
    local_app_data_resolver: Callable[[], Path] = windows_local_app_data_known_folder,
    executable: Path | None = None,
    python_probe: dict[str, object] | None = None,
    install_roots: bool = True,
) -> PortableProcessBinding:
    """Validate host/child identity without rereading a possibly changed pointer."""

    app_root = Path(app_root).absolute()
    install_root = _derive_install_root(app_root)
    inputs = PortableRootInputs(install_root, local_app_data_resolver())
    context = read_launch_context(Path(runtime_root) / LAUNCH_CONTEXT_FILENAME)
    if context.identity != expected_context_identity or context.instance_id != instance_id:
        raise RuntimeContractError("PORTABLE_CONTEXT_UNTRUSTED")
    roots = derive_portable_path_roots(inputs, context.release_id)
    if (
        not _same_path(roots.APP_ROOT, app_root)
        or not _same_path(roots.RUNTIME_ROOT, Path(runtime_root))
        or roots.root_identity != context.path_roots_identity
    ):
        raise RuntimeContractError("PORTABLE_CONTEXT_UNTRUSTED")
    try:
        validate_portable_release_layout(roots)
    except PathRootsError as exc:
        raise RuntimeContractError("PORTABLE_CONTEXT_UNTRUSTED") from exc
    try:
        release_manifest = read_release_manifest_v2(app_root / "release-manifest.json")
    except ReleaseManifestV2Error as exc:
        raise RuntimeContractError("PORTABLE_CONTEXT_UNTRUSTED") from exc
    if (
        release_manifest.raw_sha256 != context.release_manifest_sha256
        or release_manifest.release_id != context.release_id
        or release_manifest.section("release_payload")["tree_sha256"] != context.release_payload_tree_sha256
        or release_manifest.section("enterprise_source")["commit"] != context.enterprise_commit
        or release_manifest.section("enterprise_source")["tree"] != context.enterprise_tree
    ):
        raise RuntimeContractError("PORTABLE_CONTEXT_UNTRUSTED")
    manifest = parse_runtime_manifest_startup_view(
        app_root / str(release_manifest.section("runtime")["runtime_manifest_path"]),
        roots.PYTHON_RUNTIME,
    )
    identity = build_python_identity(
        Path(sys.executable if executable is None else executable),
        in_process_python_probe() if python_probe is None else python_probe,
        expected_executable=roots.PYTHON_RUNTIME / "python.exe",
        expected_runtime_root=roots.PYTHON_RUNTIME,
    )
    if (
        manifest.manifest_sha256 != context.runtime_manifest_sha256
        or manifest.manifest_sha256 != release_manifest.section("runtime")["runtime_manifest_sha256"]
        or identity.executable_sha256 != context.python_executable_sha256
        or identity.version != context.python_version
        or identity.abi != context.python_abi
        or identity.architecture != context.architecture
    ):
        raise RuntimeContractError("PORTABLE_CONTEXT_UNTRUSTED")
    if install_roots:
        install_path_roots_for_process(roots)
    return PortableProcessBinding(roots, context)


def stable_error_document(error: BaseException) -> dict[str, object]:
    """Return one path-free public error document for the formal launcher."""

    if isinstance(error, RuntimeContractError):
        return error.payload.as_public_dict()
    code = getattr(error, "code", None)
    if not isinstance(code, str) or not code or len(code) > 64:
        code = "PORTABLE_BOOTSTRAP_INVALID"
    return {"code": code, "status": "blocked"}


def stable_error_json(error: BaseException) -> bytes:
    import json

    return (json.dumps(stable_error_document(error), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def expected_release_python(app_root: Path) -> Path:
    candidate = Path(app_root) / "python" / "python.exe"
    _assert_regular_no_reparse(candidate, code="PORTABLE_PYTHON_MISSING")
    return candidate


def _public_runtime_snapshot(value: object, *, key: str = "") -> object:
    """Remove host paths while retaining bounded lifecycle evidence."""

    if isinstance(value, dict):
        return {name: _public_runtime_snapshot(item, key=name) for name, item in value.items()}
    if isinstance(value, list):
        return [_public_runtime_snapshot(item, key=key) for item in value]
    if isinstance(value, tuple):
        return [_public_runtime_snapshot(item, key=key) for item in value]
    if isinstance(value, str) and (key == "executable" or key.endswith("_executable")):
        return Path(value).name
    return value


def execute_portable_command(*, app_root: Path, command: str) -> tuple[dict[str, object], int]:
    """Run one formal command through the existing STAB-1 lifecycle."""

    if command not in PORTABLE_COMMANDS:
        raise RuntimeContractError("RELEASE_MISMATCH_COMMAND_INVALID")
    preflight: PortablePreflight | None = None
    manifest_error: BaseException | None = None
    try:
        preflight = build_portable_preflight(app_root, verify_full_payload=command in {"start", "restart", "health"})
        roots = install_path_roots_for_process(preflight.roots)
        portable_identity: StartupPreflightResult | RuntimeLaunchContext = preflight.result
    except (RuntimeContractError, CurrentReleaseError) as exc:
        if command not in {"status", "stop"}:
            raise
        manifest_error = exc
        # Safe-stop/status recovery is authorized only by the retained context
        # plus the existing adopted lock/state/process identity. It never turns
        # damaged current Release files back into start/restart/health trust.
        install_root = _derive_install_root(Path(app_root).absolute())
        inputs = PortableRootInputs(install_root, windows_local_app_data_known_folder())
        provisional = derive_portable_path_roots(inputs, Path(app_root).name)
        try:
            context = read_launch_context(provisional.RUNTIME_ROOT / LAUNCH_CONTEXT_FILENAME)
        except RuntimeContractError:
            if command == "status":
                return {
                    "release_manifest_error_code": str(getattr(manifest_error, "code", "CURRENT_RELEASE_INVALID")),
                    "release_manifest_v2_valid": False,
                    "status": "invalid",
                }, 0
            raise
        roots = derive_portable_path_roots(inputs, context.release_id)
        if not _same_path(roots.APP_ROOT, Path(app_root).absolute()) or roots.root_identity != context.path_roots_identity:
            raise RuntimeContractError("PORTABLE_CONTEXT_UNTRUSTED")
        roots = install_path_roots_for_process(roots)
        portable_identity = context

    # Imports below this point are intentionally after portable root install.
    from enterprise import config as enterprise_config
    from enterprise.paths import prepare_application_directories, prepare_runtime_directories
    from enterprise.runtime.control import RuntimeController, inspect_runtime
    from enterprise.runtime.preflight import decide_release_mismatch
    from enterprise.runtime.supervisor import SupervisorConfig

    prepare_application_directories(roots)
    prepare_runtime_directories(roots)
    secrets_to_redact = tuple(
        value
        for value in (
            getattr(enterprise_config, "JWT_SECRET", None),
            getattr(enterprise_config, "ADMIN_PASSWORD", None),
        )
        if isinstance(value, str) and len(value.strip()) >= 8
    )
    config = SupervisorConfig(
        app_root=roots.APP_ROOT,
        runtime_root=roots.RUNTIME_ROOT,
        log_root=roots.LOG_ROOT / "runtime",
        mode="service-host",
        runtime_mode="portable-release",
        release_id=portable_identity.release_id,
        runtime_manifest_sha256=portable_identity.runtime_manifest_sha256,
        release_manifest_sha256=portable_identity.release_manifest_sha256,
        release_payload_tree_sha256=portable_identity.release_payload_tree_sha256,
        enterprise_commit=portable_identity.enterprise_commit,
        enterprise_tree=portable_identity.enterprise_tree,
        startup_preflight_sha256=(portable_identity.identity if isinstance(portable_identity, StartupPreflightResult) else portable_identity.startup_preflight_sha256),
        python_executable=str(roots.PYTHON_RUNTIME / "python.exe"),
        upstream_port=int(getattr(enterprise_config, "UPSTREAM_PORT", 3001)),
        gateway_port=int(getattr(enterprise_config, "GATEWAY_PORT", 8000)),
        secret_values=secrets_to_redact,
    )
    controller = RuntimeController(config)
    snapshot = inspect_runtime(config)
    if command == "start" and snapshot.get("start_disposition") in {"startup_in_progress", "stale_runtime_state"}:
        if controller.reconcile_reboot_stale_runtime(snapshot):
            snapshot = inspect_runtime(config)
    if manifest_error is not None:
        snapshot["release_manifest_v2_valid"] = False
        snapshot["release_manifest_error_code"] = str(getattr(manifest_error, "code", "CURRENT_RELEASE_INVALID"))
        public = _public_runtime_snapshot(snapshot)
        if command == "status":
            return public, 0
        if snapshot.get("portable_ownership_valid") is not True:
            return {"code": "PORTABLE_RUNTIME_OWNERSHIP_UNTRUSTED", "status": "blocked"}, 2
        payload = controller.send_command("stop")
        result = str(payload.get("result"))
        return _public_runtime_snapshot(payload), 0 if result in {"stopped", "already_stopped"} else 2
    decision = decide_release_mismatch(
        launcher_release_id=preflight.result.release_id,
        current_release_id=preflight.result.release_id,
        running_release_id=snapshot.get("running_release_id"),
        owned_instance_valid=snapshot.get("portable_ownership_valid") is True,
        command=command,
    )
    unsafe_dispositions = {
        "foreign_port_occupant",
        "unresolved_port_occupant",
        "port_inspection_failed",
        "owned_orphan_process",
        "upstream_only",
        "gateway_only",
    }
    if command != "status" and snapshot.get("start_disposition") in unsafe_dispositions:
        return {
            "code": "PORTABLE_RUNTIME_OWNERSHIP_UNTRUSTED",
            "status": "blocked",
        }, 2
    if (
        command != "status"
        and snapshot.get("start_disposition") not in {"stopped", "stale_runtime_state"}
        and snapshot.get("portable_ownership_valid") is not True
    ):
        return {"code": "PORTABLE_RUNTIME_OWNERSHIP_UNTRUSTED", "status": "blocked"}, 2
    if not decision.allowed:
        return {
            "code": decision.status_code,
            "release_gate": decision.as_dict(),
            "status": "blocked",
        }, 2
    if command == "start":
        assert preflight is not None
        payload = controller.start(preflight=preflight.result)
        result = str(payload.get("result"))
        return _public_runtime_snapshot(payload), 0 if result in {"started", "already_running"} else 2
    if command == "stop":
        payload = controller.send_command("stop")
        result = str(payload.get("result"))
        return _public_runtime_snapshot(payload), 0 if result in {"stopped", "already_stopped"} else 2
    if command == "restart":
        payload = controller.send_command("restart", wait_seconds=90)
        return _public_runtime_snapshot(payload), 0 if payload.get("result") == "restarted" else 2
    snapshot = inspect_runtime(config)
    snapshot["release_gate"] = decision.as_dict()
    public = _public_runtime_snapshot(snapshot)
    if command == "status":
        return public, 0
    readiness = snapshot.get("readiness")
    if type(readiness) is dict and readiness.get("ready") is True:
        return public, 0
    return {
        "code": "PORTABLE_STARTUP_NOT_READY",
        "readiness": _public_runtime_snapshot(readiness),
        "release_gate": decision.as_dict(),
        "status": "blocked",
    }, 2
