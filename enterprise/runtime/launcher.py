"""Fixed direct-script bootstrap for formal Windows portable commands."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path


_COMMANDS = frozenset({"start", "stop", "restart", "status", "health"})


def _blocked(code: str) -> int:
    print(json.dumps({"code": code, "status": "blocked"}, sort_keys=True, separators=(",", ":")))
    return 2


def _has_reparse(path: Path) -> bool:
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode):
        return True
    return bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _safe_existing_path(path: Path, *, directory: bool) -> bool:
    current = path
    checked: list[Path] = []
    while current != current.parent:
        checked.append(current)
        current = current.parent
    try:
        if any(_has_reparse(item) for item in reversed(checked)):
            return False
        return path.is_dir() if directory else path.is_file()
    except OSError:
        return False


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(os.path.normpath(os.fspath(left)))) == os.path.normcase(
        os.path.abspath(os.path.normpath(os.fspath(right)))
    )


def _python_isolation_ready() -> bool:
    return (
        sys.flags.isolated == 1
        and sys.flags.ignore_environment == 1
        and sys.flags.no_user_site == 1
        and sys.flags.dont_write_bytecode == 1
        and sys.dont_write_bytecode is True
    )


def _sanitize_python_environment() -> None:
    os.environ.pop("PYTHONHOME", None)
    os.environ.pop("PYTHONPATH", None)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["PYTHONNOUSERSITE"] = "1"
    sys.dont_write_bytecode = True


def _bootstrap_identity(script_path: Path) -> Path:
    script = script_path.absolute()
    if not _safe_existing_path(script, directory=False) or script.name != "launcher.py":
        raise RuntimeError("PORTABLE_BOOTSTRAP_INVALID")
    app_root = script.parents[2]
    if app_root.parent.name.casefold() != "releases" or not _safe_existing_path(app_root, directory=True):
        raise RuntimeError("PORTABLE_RELEASE_LAYOUT_INVALID")
    expected_python = app_root / "python" / "python.exe"
    if not _safe_existing_path(expected_python, directory=False):
        raise RuntimeError("PORTABLE_PYTHON_MISSING")
    if not _same_path(Path(sys.executable), expected_python):
        raise RuntimeError("PYTHON_IDENTITY_EXECUTABLE_MISMATCH")
    if not sys.dont_write_bytecode or not sys.flags.no_user_site:
        raise RuntimeError("PYTHON_IDENTITY_BYTECODE_POLICY_INVALID")
    # Cheap stdlib-only size/existence gates run before any enterprise import.
    for path, maximum, code in (
        (app_root / "runtime-manifest.json", 1024 * 1024, "RUNTIME_MANIFEST_MISSING"),
        (app_root.parent.parent / "state" / "current-release.json", 16 * 1024, "CURRENT_RELEASE_MISSING"),
    ):
        try:
            size = os.lstat(path).st_size
            if _has_reparse(path) or size < 1 or size > maximum:
                raise RuntimeError(code)
        except FileNotFoundError as exc:
            raise RuntimeError(code) from exc
        except OSError as exc:
            raise RuntimeError("PORTABLE_BOOTSTRAP_INVALID") from exc
    return app_root


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 2 or arguments[0] != "portable" or arguments[1] not in _COMMANDS:
        return _blocked("RUNTIME_MODE_INVALID")
    if not _python_isolation_ready():
        return _blocked("PORTABLE_PYTHON_ISOLATION_REQUIRED")
    _sanitize_python_environment()
    try:
        app_root = _bootstrap_identity(Path(__file__))
    except RuntimeError as exc:
        code = str(exc) if str(exc).isupper() and len(str(exc)) <= 64 else "PORTABLE_BOOTSTRAP_INVALID"
        return _blocked(code)
    sys.path.insert(0, str(app_root))
    try:
        from enterprise.runtime.portable import execute_portable_command, stable_error_document

        payload, exit_code = execute_portable_command(app_root=app_root, command=arguments[1])
    except BaseException as exc:
        try:
            payload = stable_error_document(exc)
        except BaseException:
            payload = {"code": "PORTABLE_BOOTSTRAP_INVALID", "status": "blocked"}
        exit_code = 2
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if exit_code == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
