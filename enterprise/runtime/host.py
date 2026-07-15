"""Fixed script entry for a detached service-host under bundled Python."""

from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_BOOTSTRAP_FAILURE_OPTION = "--bootstrap-failure-path"
_BOOTSTRAP_FAILURE_FILENAME = "service-host-bootstrap.failure"


def _option_value(arguments: list[str], option: str) -> str | None:
    values = [arguments[index + 1] for index, value in enumerate(arguments[:-1]) if value == option]
    return values[0] if len(values) == 1 else None


def _bootstrap_failure_path(arguments: list[str]) -> Path | None:
    """Accept only the controller's fixed marker directly inside runtime root."""
    runtime_root = _option_value(arguments, "--runtime-root")
    marker = _option_value(arguments, _BOOTSTRAP_FAILURE_OPTION)
    if runtime_root is None or marker is None:
        return None
    try:
        root = Path(runtime_root).resolve()
        path = Path(marker).resolve()
    except OSError:
        return None
    return path if path == root / _BOOTSTRAP_FAILURE_FILENAME else None


def _without_bootstrap_failure_option(arguments: list[str]) -> list[str]:
    """Keep the host-only marker option out of the public lifecycle parser."""
    filtered: list[str] = []
    index = 0
    while index < len(arguments):
        if arguments[index] == _BOOTSTRAP_FAILURE_OPTION:
            index += 2
            continue
        filtered.append(arguments[index])
        index += 1
    return filtered


def _write_bootstrap_failure(path: Path | None, category: str) -> None:
    if path is None:
        return
    try:
        with path.open("x", encoding="ascii", newline="") as handle:
            handle.write(f"{category}\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        pass


def _main(arguments: list[str]) -> int:
    marker = _bootstrap_failure_path(arguments)
    try:
        from enterprise.runtime.cli import main
    except Exception:
        _write_bootstrap_failure(marker, "host_import_failed")
        return 2
    try:
        result = main(_without_bootstrap_failure_option(arguments))
    except SystemExit as exc:
        result = exc.code if type(exc.code) is int else 2
    except Exception:
        _write_bootstrap_failure(marker, "host_entry_failed")
        return 2
    if result != 0:
        _write_bootstrap_failure(marker, "service_host_nonzero_exit")
    return result


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
