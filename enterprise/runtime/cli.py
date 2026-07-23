"""Local CLI for fixed runtime lifecycle commands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .control import RuntimeControlError, RuntimeController, default_runtime_root, inspect_runtime, validate_runtime_root
from .supervisor import RuntimeStartBlocked, RuntimeSupervisor, SupervisorConfig


ROOT = Path(__file__).resolve().parents[2]

_COMMAND_SUCCESS_RESULTS = {
    "start": frozenset({"started", "already_running"}),
    "stop": frozenset({"stopped", "already_stopped"}),
    "restart": frozenset({"restarted"}),
}


def _configured_secret_values() -> tuple[str, ...]:
    """Return only explicit configuration secrets for in-memory log redaction."""
    try:
        from enterprise import config as enterprise_config
    except Exception:
        return ()
    values: list[str] = []
    for name in ("JWT_SECRET", "ADMIN_PASSWORD"):
        value = getattr(enterprise_config, name, None)
        if isinstance(value, str) and len(value.strip()) >= 8 and value not in values:
            values.append(value)
    return tuple(values)


def _paths(args: argparse.Namespace) -> tuple[Path, Path]:
    app_root = Path(args.app_root).resolve()
    runtime_root = validate_runtime_root(app_root, Path(args.runtime_root))
    return app_root, runtime_root


def _config(args: argparse.Namespace, *, mode: str) -> SupervisorConfig:
    app_root, runtime_root = _paths(args)
    try:
        from enterprise.config import GATEWAY_PORT, UPSTREAM_PORT, PATH_ROOTS
    except Exception:
        GATEWAY_PORT, UPSTREAM_PORT, PATH_ROOTS = 8000, 3001, None
    upstream_port = args.upstream_port if args.upstream_port is not None else UPSTREAM_PORT
    gateway_port = args.gateway_port if args.gateway_port is not None else GATEWAY_PORT
    return SupervisorConfig(
        app_root=app_root,
        runtime_root=runtime_root,
        # Do not regress development logs into APP_ROOT.  Portable injection
        # is explicit in a future B1C entrypoint, not inferred by this CLI.
        log_root=None,
        mode=mode,
        upstream_port=upstream_port,
        gateway_port=gateway_port,
        secret_values=_configured_secret_values(),
        fixture_child_wrapper=bool(args.fixture_child_wrapper),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Infinite Canvas Enterprise local runtime control")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "stop", "restart", "status", "health", "foreground", "service-host"):
        item = subparsers.add_parser(name)
        item.add_argument("--app-root", default=str(ROOT))
        item.add_argument("--runtime-root", default=str(default_runtime_root()))
        item.add_argument("--upstream-port", type=int)
        item.add_argument("--gateway-port", type=int)
        item.add_argument("--fixture-child-wrapper", action="store_true", help=argparse.SUPPRESS)
        if name == "service-host":
            item.add_argument("--instance-id", required=True)
    return parser


def _write(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _command_exit_code(command: str, payload: dict[str, object]) -> int:
    result = payload.get("result")
    return 0 if result in _COMMAND_SUCCESS_RESULTS[command] else 2


def _health_exit_code(snapshot: dict[str, object]) -> int:
    if snapshot.get("state") != "healthy":
        return 2
    upstream = snapshot.get("upstream_health")
    gateway = snapshot.get("gateway_health")
    return 0 if type(upstream) is dict and type(gateway) is dict and upstream.get("ok") is True and gateway.get("ok") is True else 2


def run(args: argparse.Namespace) -> int:
    if args.command == "service-host":
        return RuntimeSupervisor(_config(args, mode="service-host"), instance_id=args.instance_id).run()
    if args.command == "foreground":
        return RuntimeSupervisor(_config(args, mode="foreground")).run()
    config = _config(args, mode="service-host")
    controller = RuntimeController(config)
    if args.command == "start":
        payload = controller.start()
        _write(payload)
        return _command_exit_code("start", payload)
    if args.command == "stop":
        payload = controller.send_command("stop")
        _write(payload)
        return _command_exit_code("stop", payload)
    if args.command == "restart":
        payload = controller.send_command("restart", wait_seconds=90)
        _write(payload)
        return _command_exit_code("restart", payload)
    snapshot = inspect_runtime(config)
    if args.command == "status":
        _write(snapshot)
        return 0
    _write(snapshot)
    return _health_exit_code(snapshot)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except (RuntimeControlError, RuntimeStartBlocked) as exc:
        payload: dict[str, object] = {"status": "blocked", "code": getattr(exc, "code", "RUNTIME_CONTROL_ERROR")}
        if isinstance(exc, RuntimeControlError):
            payload.update(exc.public_details)
        _write(payload)
        return 2
    except ValueError:
        _write({"status": "blocked", "code": "RUNTIME_INPUT_INVALID"})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
