"""Formal local Windows entry for the INSTALL-MVP-1 Greenfield bootstrap.

Only stdlib modules are imported until the raw Release root, bundled Python,
and interpreter isolation flags have been checked.  The installation business
logic remains in :mod:`enterprise.fresh_install`.
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import io
import json
import os
import stat
import sys
import warnings
from pathlib import Path
from typing import Callable


RESULT_SCHEMA = "install-mvp-1-result-v1"
DEFAULT_INSTALL_RELATIVE = Path("Infinite-Canvas-Enterprise") / "install"


class InstallCliError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise InstallCliError("INSTALL_ARGUMENT_INVALID")


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")))


def _blocked(code: str) -> int:
    _emit({"schema_version": RESULT_SCHEMA, "status": "blocked", "code": code})
    return 2


def _stable_code(error: BaseException) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and code.startswith("INSTALL_") and len(code) <= 64:
        return code
    return "INSTALL_INTERNAL_ERROR"


def _has_reparse(path: Path) -> bool:
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode):
        return True
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(info, "st_file_attributes", 0) & flag)


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
    normalize = lambda value: os.path.normcase(os.path.abspath(os.path.normpath(os.fspath(value))))
    return normalize(left) == normalize(right)


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
    if not _safe_existing_path(script, directory=False) or script.name != "install_cli.py":
        raise InstallCliError("INSTALL_BOOTSTRAP_INVALID")
    app_root = script.parent.parent
    expected_python = app_root / "python" / "python.exe"
    if not _safe_existing_path(app_root, directory=True):
        raise InstallCliError("INSTALL_BOOTSTRAP_INVALID")
    if not _safe_existing_path(expected_python, directory=False):
        raise InstallCliError("INSTALL_PYTHON_MISSING")
    if not _same_path(Path(sys.executable), expected_python):
        raise InstallCliError("INSTALL_PYTHON_IDENTITY_INVALID")
    for path, directory in (
        (app_root / "enterprise", True),
        (app_root / "python", True),
        (app_root / "runtime-manifest.json", False),
        (app_root / "VERSION", False),
        (app_root / "首次安装企业版.bat", False),
    ):
        if not _safe_existing_path(path, directory=directory):
            raise InstallCliError("INSTALL_BOOTSTRAP_INVALID")
    try:
        manifest_size = os.lstat(app_root / "runtime-manifest.json").st_size
        version_size = os.lstat(app_root / "VERSION").st_size
    except OSError as exc:
        raise InstallCliError("INSTALL_BOOTSTRAP_INVALID") from exc
    if not 1 <= manifest_size <= 1024 * 1024 or not 1 <= version_size <= 128:
        raise InstallCliError("INSTALL_BOOTSTRAP_INVALID")
    return app_root


def discover_release_asset_directory(
    raw_app_root: Path,
    *,
    verify: Callable[[Path], object],
    input_func: Callable[[str], str],
    emit: Callable[[dict[str, object]], None],
) -> Path:
    """Try exactly the raw root and two parents, then one explicit directory."""

    root = Path(os.path.abspath(os.fspath(raw_app_root)))
    candidates: list[Path] = []
    current = root
    for _ in range(3):
        if current not in candidates:
            candidates.append(current)
        current = current.parent
    for candidate in candidates:
        try:
            verify(candidate)
            return candidate
        except BaseException as exc:
            if getattr(exc, "code", None) != "INSTALL_RELEASE_ASSET_SET_INVALID":
                raise
    emit(
        {
            "schema_version": RESULT_SCHEMA,
            "status": "input_required",
            "code": "INSTALL_RELEASE_ASSETS_REQUIRED",
        }
    )
    supplied = input_func("Directory containing the three Release assets: ").strip()
    if not supplied:
        raise InstallCliError("INSTALL_RELEASE_ASSETS_REQUIRED")
    supplied_path = Path(supplied)
    if not supplied_path.is_absolute():
        raise InstallCliError("INSTALL_RELEASE_ASSETS_REQUIRED")
    verify(supplied_path)
    return supplied_path.absolute()


def run_interactive_install(
    *,
    raw_app_root: Path,
    release_dir: Path | None = None,
    install_root: Path | None = None,
    input_func: Callable[[str], str] = input,
    password_func: Callable[[str], str] = getpass.getpass,
    known_folder_resolver: Callable[[], Path] | None = None,
    verify: Callable[[Path], object] | None = None,
    installer: Callable[..., object] | None = None,
) -> dict[str, object]:
    # Pre-install imports otherwise emit development-config and SyntaxWarning
    # messages containing the raw extraction path.  Failures still propagate
    # to the stable INSTALL_* result boundary below.
    with warnings.catch_warnings(), contextlib.redirect_stderr(io.StringIO()):
        warnings.simplefilter("ignore", SyntaxWarning)
        from enterprise.fresh_install import install_greenfield, verify_release_assets
        from enterprise.runtime.portable import windows_local_app_data_known_folder

    resolver = known_folder_resolver or windows_local_app_data_known_folder
    verify_assets = verify or verify_release_assets
    install = installer or install_greenfield
    known_folder = resolver()
    assets = release_dir or discover_release_asset_directory(
        raw_app_root,
        verify=verify_assets,
        input_func=input_func,
        emit=_emit,
    )
    target = install_root or (known_folder / DEFAULT_INSTALL_RELATIVE)
    username = input_func("First super_admin username: ")
    password = password_func("First super_admin password: ")
    confirmation = password_func("Confirm first super_admin password: ")
    result = install(
        release_dir=Path(assets),
        install_root=Path(target),
        username=username,
        password=password,
        password_confirmation=confirmation,
        local_app_data_base=known_folder,
    )
    return {"schema_version": RESULT_SCHEMA, "status": "succeeded", "code": "INSTALL_SUCCEEDED", **result.public_dict()}


def _execute(**kwargs: object) -> int:
    try:
        payload = run_interactive_install(**kwargs)  # type: ignore[arg-type]
    except (EOFError, KeyboardInterrupt):
        return _blocked("INSTALL_INTERACTIVE_INPUT_REQUIRED")
    except BaseException as exc:
        return _blocked(_stable_code(exc))
    _emit(payload)
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        return _blocked("INSTALL_ARGUMENT_INVALID")
    if not _python_isolation_ready():
        return _blocked("INSTALL_PYTHON_ISOLATION_REQUIRED")
    _sanitize_python_environment()
    try:
        app_root = _bootstrap_identity(Path(__file__))
    except BaseException as exc:
        return _blocked(_stable_code(exc))
    sys.path.insert(0, str(app_root))
    return _execute(raw_app_root=app_root)


def development_main(argv: list[str] | None = None) -> int:
    parser = _Parser(description="Install one verified Enterprise Release into a new local root")
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--install-root", type=Path, required=True)
    try:
        args = parser.parse_args(argv)
    except BaseException as exc:
        return _blocked(_stable_code(exc))
    return _execute(
        raw_app_root=Path(__file__).resolve().parents[1],
        release_dir=args.release_dir,
        install_root=args.install_root,
    )


if __name__ == "__main__":
    raise SystemExit(main())
