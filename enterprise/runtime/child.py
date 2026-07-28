"""Fixed internal Uvicorn wrapper with an instance-local shutdown file."""

from __future__ import annotations

import sys
from pathlib import Path


def _remove_runtime_script_directory() -> None:
    """Prevent the sibling runtime ``logging.py`` from shadowing stdlib logging."""
    runtime_directory = Path(__file__).resolve().parent
    filtered: list[str] = []
    for entry in sys.path:
        if not entry:
            filtered.append(entry)
            continue
        try:
            if Path(entry).resolve() == runtime_directory:
                continue
        except OSError:
            pass
        filtered.append(entry)
    sys.path[:] = filtered


_remove_runtime_script_directory()

import argparse
import asyncio
import importlib


def _load_application(role: str, app_root: Path):
    root = str(app_root.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    module_name = "main" if role == "upstream" else "enterprise.gateway"
    module = importlib.import_module(module_name)
    application = getattr(module, "app", None)
    if application is None:
        raise RuntimeError("runtime application is unavailable")
    return application


async def _serve(args: argparse.Namespace) -> int:
    if args.runtime_mode == "portable-release":
        app_root = Path(args.app_root).absolute()
        expected_entry = app_root / "enterprise" / "runtime" / "child.py"
        try:
            if expected_entry.resolve() != Path(__file__).resolve():
                return 2
        except OSError:
            return 2
        if str(app_root) not in sys.path:
            sys.path.insert(0, str(app_root))
        from enterprise.runtime.portable import validate_portable_process_binding

        validate_portable_process_binding(
            app_root=app_root,
            runtime_root=Path(args.runtime_root),
            instance_id=args.instance_id,
            expected_context_identity=args.launch_context_identity,
        )
    import uvicorn

    application = _load_application(args.role, Path(args.app_root))
    config = uvicorn.Config(application, host=args.host, port=args.port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    stop_file = Path(args.runtime_stop_file)
    marker = Path(args.shutdown_marker)

    async def watch_stop_file() -> None:
        while not server.should_exit:
            if stop_file.is_file():
                server.should_exit = True
                return
            await asyncio.sleep(0.1)

    watcher = asyncio.create_task(watch_stop_file())
    try:
        await server.serve()
        if stop_file.is_file():
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("graceful_shutdown\n", encoding="utf-8")
        return 0
    finally:
        watcher.cancel()
        try:
            await watcher
        except asyncio.CancelledError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=("upstream", "gateway"), required=True)
    parser.add_argument("--app-root", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--runtime-stop-file", required=True)
    parser.add_argument("--shutdown-marker", required=True)
    parser.add_argument("--runtime-mode", choices=("development", "portable-release"), default="development")
    parser.add_argument("--runtime-root")
    parser.add_argument("--instance-id")
    parser.add_argument("--launch-context-identity")
    args = parser.parse_args(argv)
    if args.runtime_mode == "portable-release" and not all(
        (args.runtime_root, args.instance_id, args.launch_context_identity)
    ):
        return 2
    return asyncio.run(_serve(args))


if __name__ == "__main__":
    raise SystemExit(main())
