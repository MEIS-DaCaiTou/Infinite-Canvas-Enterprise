"""Trusted maintenance control for immutable historical portable releases.

The installed supervisor and Job remain the sole process owner. This module
only sends its existing, generation/context-bound STOP protocol; it never
starts a second host, signals an arbitrary PID or rewrites installed code.
"""
from __future__ import annotations

from pathlib import Path
import json
import os
import subprocess
import sys

from .control import RuntimeController, inspect_runtime
from .launch_context import LAUNCH_CONTEXT_FILENAME, read_launch_context
from .portable import build_portable_preflight, windows_local_app_data_known_folder
from .supervisor import SupervisorConfig


def portable_controller(app_root: Path, *, local_app_data_base: Path | None = None) -> RuntimeController:
    resolver = (lambda: local_app_data_base) if local_app_data_base is not None else windows_local_app_data_known_folder
    preflight = build_portable_preflight(app_root, local_app_data_resolver=resolver)
    # Full source/interpreter/pointer trust is checked BEFORE reading runtime
    # authority. Ports come from this installation's configuration, not logs.
    from enterprise.paths import install_path_roots_for_process
    install_path_roots_for_process(preflight.roots)
    from enterprise import config
    identity = preflight.result
    controller = RuntimeController(SupervisorConfig(
        app_root=preflight.roots.APP_ROOT, runtime_root=preflight.roots.RUNTIME_ROOT,
        log_root=preflight.roots.LOG_ROOT / "runtime", mode="service-host",
        runtime_mode="portable-release", release_id=identity.release_id,
        release_manifest_sha256=identity.release_manifest_sha256,
        release_payload_tree_sha256=identity.release_payload_tree_sha256,
        enterprise_commit=identity.enterprise_commit, enterprise_tree=identity.enterprise_tree,
        runtime_manifest_sha256=identity.runtime_manifest_sha256,
        startup_preflight_sha256=identity.identity,
        python_executable=str(preflight.roots.PYTHON_RUNTIME / "python.exe"),
        upstream_port=int(config.UPSTREAM_PORT), gateway_port=int(config.GATEWAY_PORT),
    ))
    snapshot = inspect_runtime(controller.config)
    if snapshot.get("supervisor_identity_current") or snapshot.get("owned_child_current") or snapshot.get("lock"):
        context = read_launch_context(preflight.roots.RUNTIME_ROOT / LAUNCH_CONTEXT_FILENAME)
        if (context.path_roots_identity != preflight.roots.root_identity
                or context.current_release_sha256 != preflight.current_release.raw_sha256
                or context.release_id != identity.release_id
                or context.release_manifest_sha256 != identity.release_manifest_sha256
                or context.release_payload_tree_sha256 != identity.release_payload_tree_sha256
                or context.enterprise_commit != identity.enterprise_commit
                or context.enterprise_tree != identity.enterprise_tree
                or context.runtime_manifest_sha256 != identity.runtime_manifest_sha256
                or context.python_executable_sha256 != identity.python_executable_sha256
                or context.startup_preflight_sha256 != identity.identity):
            raise ValueError("NATIVE_RUNTIME_CONTEXT_MISMATCH")
    return controller


def stop_portable_service(app_root: Path, *, local_app_data_base: Path | None = None) -> tuple[int, dict]:
    executable = Path(app_root) / "python/python.exe"
    if os.path.normcase(os.path.abspath(sys.executable)) != os.path.normcase(os.path.abspath(executable)):
        # Rollback may have to stop a failed TARGET while the update worker
        # still uses source Python. Verify its complete closure BEFORE running
        # the same trusted controller bundle with target's pinned interpreter.
        from enterprise.paths import PortableRootInputs, derive_portable_path_roots
        from enterprise.release.current_release import read_current_release_result_from_state_root
        from enterprise.release.release_manifest_v2 import read_release_manifest_v2, verify_materialized_release
        install = Path(app_root).parents[1]
        current = read_current_release_result_from_state_root(install / "state")
        local = local_app_data_base if local_app_data_base is not None else windows_local_app_data_known_folder()
        roots = derive_portable_path_roots(PortableRootInputs(install, local), current.release.release_id)
        manifest = read_release_manifest_v2(app_root / "release-manifest.json")
        if roots.APP_ROOT != Path(app_root).absolute() or manifest.raw_sha256 != current.release.manifest_sha256:
            raise ValueError("NATIVE_RUNTIME_CONTEXT_MISMATCH")
        verify_materialized_release(app_root, inventory_path=app_root / "release-payload-inventory.json")
        code = "import json,sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from enterprise.runtime.recovery_control import stop_portable_service;c,p=stop_portable_service(Path(sys.argv[2]),local_app_data_base=Path(sys.argv[3]));print(json.dumps(p));sys.exit(c)"
        environment = dict(os.environ)
        for key in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONINSPECT"):
            environment.pop(key, None)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        done = subprocess.run([str(executable), "-I", "-B", "-c", code,
            str(Path(__file__).resolve().parents[2]), str(app_root), str(local)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=environment, timeout=150, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if len(done.stdout) > 65536:
            return 2, {"code": "NATIVE_RUNTIME_CONTROL_OUTPUT_INVALID"}
        try:
            payload = json.loads(done.stdout)
        except (ValueError, UnicodeError):
            return 2, {"code": "NATIVE_RUNTIME_CONTROL_OUTPUT_INVALID"}
        return int(done.returncode), payload if type(payload) is dict else {"code": "NATIVE_RUNTIME_CONTROL_OUTPUT_INVALID"}
    controller = portable_controller(app_root, local_app_data_base=local_app_data_base)
    payload = controller.send_command("stop", wait_seconds=90)
    return (0 if payload.get("result") in {"stopped", "already_stopped"} else 2), payload


def lifecycle_summary(phase: str, exit_code: int, payload: dict) -> dict[str, object]:
    """Fixed, bounded diagnostic fields: no command, environment or exception text."""
    def category(value):
        return value if isinstance(value, str) and len(value) <= 100 and all(
            c.isascii() and (c.isalnum() or c == "_") for c in value) else None
    status = payload.get("status")
    status = status if type(status) is dict else payload
    result = {"phase": phase, "exit_code": exit_code}
    for key in ("result", "code"):
        result[key] = category(payload.get(key))
    for key in ("state", "start_disposition"):
        result[key] = category(status.get(key))
    for key in ("portable_control_valid", "portable_ownership_valid", "supervisor_identity_current", "owned_child_current"):
        if type(status.get(key)) is bool:
            result[key] = status[key]
    for role in ("upstream", "gateway"):
        item = status.get(role + "_listener")
        if type(item) is dict:
            result[role + "_inspection_failed"] = item.get("inspection_failed") is True
            result[role + "_failure_category"] = category(item.get("failure_category"))
    ack = payload.get("ack")
    if type(ack) is dict:
        result["quiescence_confirmed"] = ack.get("quiescence_confirmed") is True
        result["reconciled_stop_result"] = category(ack.get("reconciled_stop_result"))
    return result
