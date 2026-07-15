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
    args = parser.parse_args(argv)
    return asyncio.run(_serve(args))


if __name__ == "__main__":
    raise SystemExit(main())
