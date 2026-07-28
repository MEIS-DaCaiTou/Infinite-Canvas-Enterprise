"""Real bundled-Python portable lifecycle harness used only by ENV-1B2A."""

from __future__ import annotations

import argparse
import json
import socket
from pathlib import Path

from enterprise.runtime.control import RuntimeController, inspect_runtime
from enterprise.runtime.portable import build_portable_preflight
from enterprise.runtime.supervisor import SupervisorConfig


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def _process_snapshot(status: dict[str, object], role: str) -> dict[str, object]:
    state = status.get("runtime_state")
    value = state.get(role) if type(state) is dict else None
    return {
        "executable_basename": Path(str(value.get("executable", ""))).name if type(value) is dict else "",
        "pid_present": type(value) is dict and type(value.get("pid")) is int,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-root", required=True, type=Path)
    parser.add_argument("--local-base", required=True, type=Path)
    args = parser.parse_args()
    evidence = build_portable_preflight(
        args.app_root,
        local_app_data_resolver=lambda: args.local_base,
    )
    upstream_port = _free_port()
    gateway_port = _free_port()
    while gateway_port == upstream_port:
        gateway_port = _free_port()
    config = SupervisorConfig(
        app_root=evidence.roots.APP_ROOT,
        runtime_root=evidence.roots.RUNTIME_ROOT,
        log_root=evidence.roots.LOG_ROOT / "runtime-fixture",
        mode="service-host",
        runtime_mode="portable-release",
        release_id=evidence.result.release_id,
        runtime_manifest_sha256=evidence.result.runtime_manifest_sha256,
        startup_preflight_sha256=evidence.result.identity,
        python_executable=str(evidence.roots.PYTHON_RUNTIME / "python.exe"),
        upstream_port=upstream_port,
        gateway_port=gateway_port,
        startup_timeout_seconds=30,
        health_interval_seconds=1,
        fixture_child_wrapper=True,
    )
    controller = RuntimeController(config)
    started: dict[str, object] | None = None
    stopped: dict[str, object] | None = None
    try:
        started = controller.start(preflight=evidence.result, wait_seconds=45)
        status = inspect_runtime(controller.config)
        stopped = controller.send_command("stop", wait_seconds=45)
        final = inspect_runtime(controller.config)
        payload = {
            "fixed_python_basename": Path(str(controller.config.python_executable)).name,
            "gateway": _process_snapshot(status, "gateway"),
            "health_ready": type(status.get("readiness")) is dict and status["readiness"].get("ready") is True,
            "launch_context_identity_present": isinstance(status.get("launch_context_identity"), str),
            "portable_ownership_valid": status.get("portable_ownership_valid") is True,
            "ports_released": final.get("upstream_tcp", {}).get("ok") is False and final.get("gateway_tcp", {}).get("ok") is False,
            "result": "pass",
            "schema_version": "env-1b2a-real-bundled-python-lifecycle-v1",
            "start_result": started.get("result") if type(started) is dict else None,
            "stop_result": stopped.get("result") if type(stopped) is dict else None,
            "supervisor_executable_basename": Path(str(status.get("runtime_state", {}).get("supervisor_executable", ""))).name,
            "upstream": _process_snapshot(status, "upstream"),
        }
        if not all(
            (
                payload["start_result"] == "started",
                payload["stop_result"] == "stopped",
                payload["portable_ownership_valid"] is True,
                payload["health_ready"] is True,
                payload["ports_released"] is True,
                payload["fixed_python_basename"].casefold() == "python.exe",
                payload["supervisor_executable_basename"].casefold() == "python.exe",
                payload["upstream"]["executable_basename"].casefold() == "python.exe",
                payload["gateway"]["executable_basename"].casefold() == "python.exe",
            )
        ):
            payload["result"] = "fail"
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return 0 if payload["result"] == "pass" else 2
    finally:
        if started is not None and stopped is None:
            try:
                controller.send_command("stop", wait_seconds=30)
            except Exception:
                pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:
        print(
            json.dumps(
                {
                    "error_code": str(getattr(exc, "code", type(exc).__name__))[:64],
                    "result": "fail",
                    "schema_version": "env-1b2a-real-bundled-python-lifecycle-v1",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        raise SystemExit(2)
