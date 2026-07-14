"""Local CLI for fixed runtime lifecycle commands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .control import RuntimeControlError, RuntimeController, default_runtime_root, inspect_runtime, validate_runtime_root
from .supervisor import RuntimeStartBlocked, RuntimeSupervisor, SupervisorConfig


ROOT = Path(__file__).resolve().parents[2]


def _paths(args: argparse.Namespace) -> tuple[Path, Path]:
    app_root = Path(args.app_root).resolve()
    runtime_root = validate_runtime_root(app_root, Path(args.runtime_root))
    return app_root, runtime_root


def _config(args: argparse.Namespace, *, mode: str) -> SupervisorConfig:
    app_root, runtime_root = _paths(args)
    try:
        from enterprise.config import GATEWAY_PORT, UPSTREAM_PORT
    except Exception:
        GATEWAY_PORT, UPSTREAM_PORT = 8000, 3001
    upstream_port = args.upstream_port if args.upstream_port is not None else UPSTREAM_PORT
    gateway_port = args.gateway_port if args.gateway_port is not None else GATEWAY_PORT
    return SupervisorConfig(
        app_root=app_root,
        runtime_root=runtime_root,
        mode=mode,
        upstream_port=upstream_port,
        gateway_port=gateway_port,
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


def run(args: argparse.Namespace) -> int:
    if args.command == "service-host":
        return RuntimeSupervisor(_config(args, mode="service-host"), instance_id=args.instance_id).run()
    if args.command == "foreground":
        return RuntimeSupervisor(_config(args, mode="foreground")).run()
    config = _config(args, mode="service-host")
    controller = RuntimeController(config)
    if args.command == "start":
        _write(controller.start())
        return 0
    if args.command == "stop":
        _write(controller.send_command("stop"))
        return 0
    if args.command == "restart":
        _write(controller.send_command("restart", wait_seconds=90))
        return 0
    snapshot = inspect_runtime(config)
    if args.command == "status":
        _write(snapshot)
        return 0
    _write(snapshot)
    return 0 if snapshot["state"] == "healthy" else 2


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except (RuntimeControlError, RuntimeStartBlocked):
        _write({"status": "blocked", "code": getattr(sys.exc_info()[1], "code", "RUNTIME_CONTROL_ERROR")})
        return 2
    except ValueError:
        _write({"status": "blocked", "code": "RUNTIME_INPUT_INVALID"})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
