"""One-shot, stdlib-only credential bridge for the INSTALL-UX-1 Setup.

The bridge is launched only by the Release's fixed CPython with ``-I -B``.
Credentials cross one current-user Windows named pipe and are never accepted
through command line arguments, environment variables, or files.
"""

from __future__ import annotations

import argparse
import ctypes
from contextvars import ContextVar
import json
import os
import re
import stat
import sys
import time
from pathlib import Path
from typing import Callable

from ctypes import wintypes


REQUEST_SCHEMA = "install-ux-1-request-v1"
MAINTENANCE_REQUEST_SCHEMA = "enterprise-install-maintenance-request-v2"
PROGRAM_MAINTENANCE_REQUEST_SCHEMA = "enterprise-install-maintenance-request-v3"
GRAPHICAL_MAINTENANCE_REQUEST_SCHEMA = "enterprise-install-maintenance-request-v4"
CACHE_MAINTENANCE_REQUEST_SCHEMA = "enterprise-install-maintenance-request-v5"
LIFECYCLE_REQUEST_SCHEMA = "enterprise-install-maintenance-request-v6"
UPGRADE_REQUEST_SCHEMA = "enterprise-install-maintenance-request-v7"
_AUTHENTICATED_CLIENT = ContextVar("setup_pipe_client_identity", default=None)
RESULT_SCHEMA = "install-ux-1-result-v1"
MAX_FRAME_BYTES = 16 * 1024
CONNECT_TIMEOUT_SECONDS = 45.0
PIPE_PREFIX = "InfiniteCanvasEnterprise-InstallUX1-"
PIPE_SUFFIX_PATTERN = re.compile(r"^[0-9a-f]{32}$")
DEFAULT_INSTALL_RELATIVE = Path("Infinite-Canvas-Enterprise") / "install"


class SetupBridgeError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise SetupBridgeError("INSTALL_SETUP_BRIDGE_ARGUMENT_INVALID")


def _blocked(code: str) -> dict[str, object]:
    return {
        "schema_version": RESULT_SCHEMA,
        "status": "blocked",
        "code": code if code.startswith("INSTALL_") else "INSTALL_SETUP_BRIDGE_FAILED",
    }


def _stable_code(error: BaseException) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and code.startswith("INSTALL_") and len(code) <= 96:
        return code
    return "INSTALL_INTERNAL_ERROR"


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


def _succeeded(result: object) -> dict[str, object]:
    public = result.public_dict()  # type: ignore[attr-defined]
    return {
        "schema_version": RESULT_SCHEMA,
        "status": "succeeded",
        "code": "INSTALL_SUCCEEDED",
        "release_id": str(public["release_id"]),
        "manifest_sha256": str(public["manifest_sha256"]),
        "payload_tree_sha256": str(public["payload_tree_sha256"]),
        "pointer_published": bool(public["pointer_published"]),
        "installation_id": public.get("installation_id"),
        "launcher_installed": bool(public.get("launcher_installed")),
    }


def _encode_frame(payload: dict[str, object]) -> bytes:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    if not 1 <= len(raw) <= MAX_FRAME_BYTES:
        raise SetupBridgeError("INSTALL_SETUP_BRIDGE_RESPONSE_INVALID")
    return f"{len(raw):08x}".encode("ascii") + raw


def _decode_request(raw: bytes) -> dict[str, object]:
    if not 1 <= len(raw) <= MAX_FRAME_BYTES:
        raise SetupBridgeError("INSTALL_SETUP_BRIDGE_REQUEST_TOO_LARGE")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SetupBridgeError("INSTALL_SETUP_BRIDGE_REQUEST_INVALID") from exc
    if not isinstance(payload, dict):
        raise SetupBridgeError("INSTALL_SETUP_BRIDGE_REQUEST_INVALID")
    expected = {
        "schema_version",
        "username",
        "password",
        "password_confirmation",
        "install_mode",
        "install_root",
    }
    schema = payload.get("schema_version")
    if schema == UPGRADE_REQUEST_SCHEMA:
        expected.update({"operation", "confirm_no_active_tasks"})
        operation = payload.get("operation")
        if (operation not in {"inspect-upgrade", "upgrade-retained", "recover-upgrade", "finish-upgrade"}
                or payload.get("confirm_no_active_tasks") is not (operation in {"upgrade-retained", "recover-upgrade"})):
            raise SetupBridgeError("INSTALL_SETUP_BRIDGE_REQUEST_INVALID")
    elif schema == LIFECYCLE_REQUEST_SCHEMA:
        expected.update({"operation", "confirm_no_active_tasks"})
        operation = payload.get("operation")
        if (operation not in {"inspect-lifecycle", "uninstall-retain", "recover-uninstall", "reinstall-retained"}
                or payload.get("confirm_no_active_tasks") is not (operation != "inspect-lifecycle")):
            raise SetupBridgeError("INSTALL_SETUP_BRIDGE_REQUEST_INVALID")
    elif schema == CACHE_MAINTENANCE_REQUEST_SCHEMA:
        expected.update({"operation", "cache_id", "cache_token", "confirm_cache_cleanup"})
        operation = payload.get("operation")
        if (operation not in {"inspect-cache", "clean-cache"}
                or payload.get("confirm_cache_cleanup") is not (operation == "clean-cache")):
            raise SetupBridgeError("INSTALL_SETUP_BRIDGE_REQUEST_INVALID")
        if operation == "inspect-cache":
            if payload.get("cache_id") != "" or payload.get("cache_token") != "":
                raise SetupBridgeError("INSTALL_SETUP_BRIDGE_REQUEST_INVALID")
        elif (not isinstance(payload.get("cache_id"), str) or not PIPE_SUFFIX_PATTERN.fullmatch(payload["cache_id"])
              or not isinstance(payload.get("cache_token"), str) or not re.fullmatch(r"[0-9a-f]{64}", payload["cache_token"])):
            raise SetupBridgeError("INSTALL_SETUP_BRIDGE_REQUEST_INVALID")
    elif schema == GRAPHICAL_MAINTENANCE_REQUEST_SCHEMA:
        expected.update({"operation", "confirm_no_active_tasks"})
        operation = payload.get("operation")
        if (operation not in {"repair-program", "recover-program", "inspect-program"}
                or payload.get("confirm_no_active_tasks") is not (operation != "inspect-program")):
            raise SetupBridgeError("INSTALL_SETUP_BRIDGE_REQUEST_INVALID")
    elif schema == PROGRAM_MAINTENANCE_REQUEST_SCHEMA:
        expected.update({"operation", "confirm_no_active_tasks"})
        if (payload.get("operation") not in {"repair-program", "recover-program"}
                or payload.get("confirm_no_active_tasks") is not True):
            raise SetupBridgeError("INSTALL_SETUP_BRIDGE_REQUEST_INVALID")
    elif schema == MAINTENANCE_REQUEST_SCHEMA:
        expected.add("operation")
        if payload.get("operation") not in {"install", "repair-entry", "recover-entry"}:
            raise SetupBridgeError("INSTALL_SETUP_BRIDGE_REQUEST_INVALID")
    elif schema != REQUEST_SCHEMA:
        raise SetupBridgeError("INSTALL_SETUP_BRIDGE_REQUEST_INVALID")
    if set(payload) != expected:
        raise SetupBridgeError("INSTALL_SETUP_BRIDGE_REQUEST_INVALID")
    if payload.get("install_mode") not in {"quick", "custom"}:
        raise SetupBridgeError("INSTALL_SETUP_BRIDGE_REQUEST_INVALID")
    for field in ("username", "password", "password_confirmation"):
        if not isinstance(payload.get(field), str):
            raise SetupBridgeError("INSTALL_SETUP_BRIDGE_REQUEST_INVALID")
    install_root = payload.get("install_root")
    if install_root is not None and not isinstance(install_root, str):
        raise SetupBridgeError("INSTALL_SETUP_BRIDGE_REQUEST_INVALID")
    if payload["install_mode"] == "quick" and install_root is not None:
        raise SetupBridgeError("INSTALL_SETUP_BRIDGE_REQUEST_INVALID")
    if payload["install_mode"] == "custom" and not install_root:
        raise SetupBridgeError("INSTALL_SETUP_BRIDGE_REQUEST_INVALID")
    if payload.get("operation") in {"repair-entry", "recover-entry", "repair-program", "recover-program", "inspect-program", "inspect-cache", "clean-cache", "inspect-lifecycle", "uninstall-retain", "recover-uninstall", "reinstall-retained", "inspect-upgrade", "upgrade-retained", "recover-upgrade", "finish-upgrade"} and any(payload[field] for field in ("username", "password", "password_confirmation")):
        raise SetupBridgeError("INSTALL_SETUP_BRIDGE_REQUEST_INVALID")
    return payload


def _is_reparse(path: Path) -> bool:
    info = os.lstat(path)
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & flag)


def _safe_existing_path(path: Path, *, directory: bool) -> bool:
    absolute = Path(os.path.abspath(os.fspath(path)))
    current = Path(absolute.anchor)
    try:
        if _is_reparse(current):
            return False
        for part in absolute.parts[1:]:
            current /= part
            if _is_reparse(current):
                return False
        return absolute.is_dir() if directory else absolute.is_file()
    except OSError:
        return False


def _same_path(left: Path, right: Path) -> bool:
    normalize = lambda value: os.path.normcase(os.path.abspath(os.path.normpath(os.fspath(value))))
    return normalize(left) == normalize(right)


def _prebootstrap_app_root(script_path: Path) -> Path:
    """Establish enough fixed identity to import the shared formal gate."""

    script = script_path.absolute()
    if not _safe_existing_path(script, directory=False) or script.name != "install_setup_bridge.py":
        raise SetupBridgeError("INSTALL_BOOTSTRAP_INVALID")
    app_root = script.parent.parent
    expected_python = app_root / "python" / "python.exe"
    if not _safe_existing_path(app_root, directory=True):
        raise SetupBridgeError("INSTALL_BOOTSTRAP_INVALID")
    if not _safe_existing_path(expected_python, directory=False):
        raise SetupBridgeError("INSTALL_PYTHON_MISSING")
    if not _same_path(Path(sys.executable), expected_python):
        raise SetupBridgeError("INSTALL_PYTHON_IDENTITY_INVALID")
    for path, directory in (
        (app_root / "enterprise", True),
        (app_root / "python", True),
        (app_root / "enterprise" / "install_cli.py", False),
        (app_root / "runtime-manifest.json", False),
        (app_root / "VERSION", False),
        (app_root / "首次安装企业版.bat", False),
    ):
        if not _safe_existing_path(path, directory=directory):
            raise SetupBridgeError("INSTALL_BOOTSTRAP_INVALID")
    return app_root


def _reject_reparse_ancestors(path: Path) -> None:
    absolute = Path(os.path.abspath(os.fspath(path)))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            if _is_reparse(current):
                raise SetupBridgeError("INSTALL_TARGET_UNSAFE")
        except FileNotFoundError:
            return
        except OSError as exc:
            raise SetupBridgeError("INSTALL_TARGET_UNSAFE") from exc


def _paths_overlap(left: Path, right: Path) -> bool:
    left_value = os.path.normcase(os.path.abspath(os.fspath(left)))
    right_value = os.path.normcase(os.path.abspath(os.fspath(right)))
    try:
        return os.path.commonpath((left_value, right_value)) in {left_value, right_value}
    except ValueError:
        return False


def _drive_type(path: Path) -> int:
    if os.name != "nt":
        raise SetupBridgeError("INSTALL_WINDOWS_REQUIRED")
    root = Path(os.path.abspath(os.fspath(path))).anchor
    if not root:
        raise SetupBridgeError("INSTALL_TARGET_UNSAFE")
    return int(ctypes.windll.kernel32.GetDriveTypeW(root))


def _validated_install_root(
    request: dict[str, object],
    *,
    raw_app_root: Path,
    release_dir: Path,
    known_folder: Path,
) -> Path:
    if request["install_mode"] == "quick":
        target = known_folder / DEFAULT_INSTALL_RELATIVE
    else:
        value = str(request["install_root"])
        candidate = Path(value)
        if not candidate.is_absolute() or value.startswith(("\\\\", "//")):
            raise SetupBridgeError("INSTALL_TARGET_UNSAFE")
        target = candidate
    target = Path(os.path.abspath(os.fspath(target)))
    if target == Path(target.anchor):
        raise SetupBridgeError("INSTALL_TARGET_UNSAFE")
    _reject_reparse_ancestors(target)
    if _drive_type(target) != 3:  # DRIVE_FIXED
        raise SetupBridgeError("INSTALL_TARGET_NOT_LOCAL_FIXED_DISK")
    if (_paths_overlap(target, raw_app_root) or _paths_overlap(target, release_dir)
            or _paths_overlap(target, known_folder / "Infinite-Canvas-Enterprise" / "maintenance-payloads")):
        raise SetupBridgeError("INSTALL_TARGET_OVERLAP")
    try:
        if request.get("operation", "install") in {"repair-entry", "recover-entry", "repair-program", "recover-program", "inspect-program", "inspect-cache", "clean-cache", "inspect-lifecycle", "uninstall-retain", "recover-uninstall", "reinstall-retained", "inspect-upgrade", "upgrade-retained", "recover-upgrade", "finish-upgrade"}:
            if not target.is_dir():
                raise SetupBridgeError("INSTALL_ENTRY_SOURCE_INVALID")
        elif target.exists() and (not target.is_dir() or any(target.iterdir())):
            raise SetupBridgeError("INSTALL_TARGET_NOT_GREENFIELD")
    except SetupBridgeError:
        raise
    except OSError as exc:
        raise SetupBridgeError("INSTALL_TARGET_UNSAFE") from exc
    return target


def _release_asset_directory(raw_app_root: Path) -> Path:
    """Resolve the Setup-owned three-asset directory without user discovery."""

    raw_root = raw_app_root.parent
    asset_root = raw_root.parent
    if raw_root.name != "raw" or asset_root.name != "install-ux-bundle":
        raise SetupBridgeError("INSTALL_RELEASE_ASSETS_REQUIRED")
    if not _safe_existing_path(asset_root, directory=True):
        raise SetupBridgeError("INSTALL_RELEASE_ASSETS_REQUIRED")
    return asset_root


def _run_install_request(
    request: dict[str, object],
    *,
    raw_app_root: Path,
    notify_progress=None,
) -> dict[str, object]:
    from enterprise.fresh_install import verify_release_assets
    from enterprise.runtime.portable import windows_local_app_data_known_folder

    known_folder = windows_local_app_data_known_folder()
    assets = _release_asset_directory(raw_app_root)
    verified = verify_release_assets(assets)
    target = _validated_install_root(
        request,
        raw_app_root=raw_app_root,
        release_dir=assets,
        known_folder=known_folder,
    )
    from enterprise.install_cache import CacheError, setup_cache_session, finish_setup_cache
    response = None
    try:
        with setup_cache_session(local_app_data_base=known_folder, assets=assets,
                                 raw_app_root=raw_app_root, verified=verified, target=target,
                                 client=_AUTHENTICATED_CLIENT.get()) as session:
            response = _execute_install_request(request, assets=assets, verified=verified, target=target,
                                                known_folder=known_folder, notify_progress=notify_progress)
            finish_setup_cache(session, response)
    except (CacheError, OSError):
        if response is None:
            raise  # Pre-operation/operation failures cannot be disguised as success.
        response["cache_warning"] = "INSTALL_CACHE_RETAINED"
    return response


def _execute_install_request(request, *, assets, verified, target, known_folder, notify_progress=None):
    from enterprise.fresh_install import install_greenfield
    from enterprise.install_entry import repair_fixed_entry, recover_fixed_entry, verify_entry_bundle
    if request.get("schema_version") == UPGRADE_REQUEST_SCHEMA:
        from enterprise.install_upgrade import inspect_upgrade, upgrade_retained, recover_upgrade, finish_upgrade
        arguments = dict(install_root=target, release_dir=assets, local_app_data_base=known_folder)
        operation = request["operation"]
        if operation == "inspect-upgrade":
            result = inspect_upgrade(**arguments)
        elif operation == "finish-upgrade":
            from enterprise.runtime.windows_install_registration import verify_registration
            result = finish_upgrade(**arguments, verify_registration=lambda root, installation_id:
                verify_registration(root, installation_id, expected_version=str(verified.manifest.section("identity")["release_version"])))
        else:
            arguments["confirm_no_active_tasks"] = request["confirm_no_active_tasks"]
            if operation == "recover-upgrade":
                result = recover_upgrade(**arguments)
            else:
                client = _AUTHENTICATED_CLIENT.get()
                if client is None:
                    raise SetupBridgeError("INSTALL_SETUP_BRIDGE_CLIENT_IDENTITY_FAILED")
                from enterprise.runtime.windows_setup_source import authenticated_setup_executable
                result = upgrade_retained(**arguments, native_entry_dir=assets / "native-entry",
                    setup_executable=authenticated_setup_executable(client), notify_progress=notify_progress)
        return {"schema_version": RESULT_SCHEMA, "status": "succeeded", "code": "INSTALL_UPGRADE_RESULT", **result}
    if request.get("operation") in {"inspect-lifecycle", "uninstall-retain", "recover-uninstall", "reinstall-retained"}:
        from enterprise.install_lifecycle import inspect_lifecycle, uninstall_retaining_data, reinstall_retained
        arguments = dict(install_root=target, release_dir=assets, local_app_data_base=known_folder)
        operation = request["operation"]
        if operation == "inspect-lifecycle":
            result = inspect_lifecycle(**arguments)
        else:
            arguments["confirm_no_active_tasks"] = request["confirm_no_active_tasks"]
            if operation == "reinstall-retained":
                result = reinstall_retained(**arguments)
            else:
                result = uninstall_retaining_data(**arguments, recover=operation == "recover-uninstall")
        return {"schema_version": RESULT_SCHEMA, "status": "succeeded", "code": "INSTALL_LIFECYCLE_RESULT", **result}
    if request.get("operation") in {"inspect-cache", "clean-cache"}:
        from enterprise.install_cache import inspect_cache, clean_cache
        if request["operation"] == "inspect-cache":
            result = inspect_cache(local_app_data_base=known_folder)
            # Fixed, bounded display protocol: no paths, secrets or arbitrary text.
            rows = [f'{item["cache_id"]},{item["size_bytes"]},{item["token"]},{item["status"]}' for item in result["candidates"]]
            return {"schema_version": RESULT_SCHEMA, "status": "succeeded", "code": "INSTALL_CACHE_PREVIEW",
                    "cache_rows": ";".join(rows), "retained_unknown": result["retained_unknown"]}
        result = clean_cache(local_app_data_base=known_folder, cache_id=request["cache_id"],
                             token=request["cache_token"], confirmed=request["confirm_cache_cleanup"])
        return {"schema_version": RESULT_SCHEMA, "status": "succeeded", "code": "INSTALL_CACHE_REMOVED",
                "cache_id": result["cache_id"], "deleted_bytes": result["deleted_bytes"], "cache_state": result["status"]}
    if request.get("operation") == "inspect-program":
        from enterprise.install_repair_status import inspect_program_repair
        result = inspect_program_repair(install_root=target, release_dir=assets, local_app_data_base=known_folder)
        return {"schema_version": RESULT_SCHEMA, "status": "succeeded", "code": "INSTALL_PROGRAM_STATUS", **result}
    if request.get("operation") in {"repair-program", "recover-program"}:
        from enterprise.install_repair import repair_program, recover_program
        handler = recover_program if request["operation"] == "recover-program" else repair_program
        result = handler(install_root=target, release_dir=assets, local_app_data_base=known_folder,
                         confirm_no_active_tasks=request["confirm_no_active_tasks"], notify_progress=notify_progress)
        return {"schema_version": RESULT_SCHEMA, "status": "succeeded",
                "code": "INSTALL_PROGRAM_RECOVERED" if request["operation"] == "recover-program" else "INSTALL_PROGRAM_REPAIRED",
                **result}
    if request.get("operation") in {"repair-entry", "recover-entry"}:
        source = verified.manifest.section("enterprise_source")
        entry = verify_entry_bundle(assets / "native-entry", commit=str(source["commit"]), tree=str(source["tree"]))
        handler = recover_fixed_entry if request["operation"] == "recover-entry" else repair_fixed_entry
        result = handler(install_root=target, entry=entry, local_app_data_base=known_folder)
        return {"schema_version": RESULT_SCHEMA, "status": "succeeded",
                "code": "INSTALL_ENTRY_RECOVERED" if request["operation"] == "recover-entry" else "INSTALL_ENTRY_REPAIRED",
                **result}
    result = install_greenfield(
        release_dir=assets,
        install_root=target,
        username=str(request["username"]),
        password=str(request["password"]),
        password_confirmation=str(request["password_confirmation"]),
        local_app_data_base=known_folder,
        native_entry_dir=assets / "native-entry" if request.get("schema_version") == MAINTENANCE_REQUEST_SCHEMA else None,
    )
    return _succeeded(result)


if os.name == "nt":
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    class _SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", wintypes.LPVOID), ("Attributes", wintypes.DWORD)]

    class _TOKEN_USER(ctypes.Structure):
        _fields_ = [("User", _SID_AND_ATTRIBUTES)]

    class _SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("nLength", wintypes.DWORD),
            ("lpSecurityDescriptor", wintypes.LPVOID),
            ("bInheritHandle", wintypes.BOOL),
        ]

    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CreateNamedPipeW.restype = wintypes.HANDLE
    kernel32.CreateNamedPipeW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_SECURITY_ATTRIBUTES),
    ]
    kernel32.ConnectNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
    kernel32.ReadFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.WriteFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
    kernel32.DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
    kernel32.GetNamedPipeClientProcessId.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
    kernel32.SetNamedPipeHandleState.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
        wintypes.LPVOID,
    ]
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.ConvertSidToStringSidW.argtypes = [
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.LocalFree.argtypes = [wintypes.LPVOID]
    kernel32.LocalFree.restype = wintypes.LPVOID


def _token_user_sid(process_handle: int) -> str:
    if os.name != "nt":
        raise SetupBridgeError("INSTALL_WINDOWS_REQUIRED")
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(process_handle, 0x0008, ctypes.byref(token)):
        raise SetupBridgeError("INSTALL_SETUP_BRIDGE_CLIENT_IDENTITY_FAILED")
    try:
        size = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        if size.value <= 0 or size.value > 64 * 1024:
            raise SetupBridgeError("INSTALL_SETUP_BRIDGE_CLIENT_IDENTITY_FAILED")
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            raise SetupBridgeError("INSTALL_SETUP_BRIDGE_CLIENT_IDENTITY_FAILED")
        user = ctypes.cast(buffer, ctypes.POINTER(_TOKEN_USER)).contents
        sid_string = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(user.User.Sid, ctypes.byref(sid_string)):
            raise SetupBridgeError("INSTALL_SETUP_BRIDGE_CLIENT_IDENTITY_FAILED")
        try:
            return str(sid_string.value)
        finally:
            kernel32.LocalFree(sid_string)
    finally:
        kernel32.CloseHandle(token)


def _current_user_security_attributes() -> tuple[_SECURITY_ATTRIBUTES, int, str]:
    sid = _token_user_sid(kernel32.GetCurrentProcess())
    descriptor = wintypes.LPVOID()
    sddl = f"D:P(A;;GA;;;{sid})"
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, 1, ctypes.byref(descriptor), None
    ):
        raise SetupBridgeError("INSTALL_SETUP_BRIDGE_SECURITY_FAILED")
    attributes = _SECURITY_ATTRIBUTES(ctypes.sizeof(_SECURITY_ATTRIBUTES), descriptor, False)
    return attributes, int(descriptor.value), sid


def _read_exact(handle: int, size: int) -> bytes:
    output = bytearray()
    while len(output) < size:
        chunk_size = min(size - len(output), 4096)
        chunk = ctypes.create_string_buffer(chunk_size)
        read = wintypes.DWORD()
        if not kernel32.ReadFile(handle, chunk, chunk_size, ctypes.byref(read), None) or read.value == 0:
            raise SetupBridgeError("INSTALL_SETUP_BRIDGE_READ_FAILED")
        output.extend(chunk.raw[: read.value])
    return bytes(output)


def _write_all(handle: int, raw: bytes) -> None:
    offset = 0
    while offset < len(raw):
        chunk = raw[offset : offset + 4096]
        written = wintypes.DWORD()
        if not kernel32.WriteFile(handle, chunk, len(chunk), ctypes.byref(written), None):
            raise SetupBridgeError("INSTALL_SETUP_BRIDGE_WRITE_FAILED")
        if written.value <= 0:
            raise SetupBridgeError("INSTALL_SETUP_BRIDGE_WRITE_FAILED")
        offset += written.value


def _validate_client_sid(pipe_handle: int, expected_sid: str):
    client_pid = wintypes.ULONG()
    if not kernel32.GetNamedPipeClientProcessId(pipe_handle, ctypes.byref(client_pid)):
        raise SetupBridgeError("INSTALL_SETUP_BRIDGE_CLIENT_IDENTITY_FAILED")
    process = kernel32.OpenProcess(0x1000, False, client_pid.value)
    if not process:
        raise SetupBridgeError("INSTALL_SETUP_BRIDGE_CLIENT_IDENTITY_FAILED")
    try:
        if _token_user_sid(process) != expected_sid:
            raise SetupBridgeError("INSTALL_SETUP_BRIDGE_CLIENT_IDENTITY_MISMATCH")
    finally:
        kernel32.CloseHandle(process)
    from enterprise.runtime.ownership import process_identity
    identity = process_identity(int(client_pid.value))
    if identity is None:
        raise SetupBridgeError("INSTALL_SETUP_BRIDGE_CLIENT_IDENTITY_FAILED")
    return identity


def _serve_once(
    pipe_suffix: str,
    handler: Callable[[dict[str, object]], dict[str, object]],
) -> int:
    if os.name != "nt":
        raise SetupBridgeError("INSTALL_WINDOWS_REQUIRED")
    if not PIPE_SUFFIX_PATTERN.fullmatch(pipe_suffix):
        raise SetupBridgeError("INSTALL_SETUP_BRIDGE_ARGUMENT_INVALID")
    attributes, descriptor, expected_sid = _current_user_security_attributes()
    pipe_name = rf"\\.\pipe\{PIPE_PREFIX}{pipe_suffix}"
    invalid_handle = ctypes.c_void_p(-1).value
    handle = kernel32.CreateNamedPipeW(
        pipe_name,
        0x00000003 | 0x00080000,  # PIPE_ACCESS_DUPLEX | FILE_FLAG_FIRST_PIPE_INSTANCE
        0x00000000 | 0x00000001 | 0x00000008,  # BYTE | NOWAIT | REJECT_REMOTE_CLIENTS
        1,
        MAX_FRAME_BYTES + 8,
        MAX_FRAME_BYTES + 8,
        0,
        ctypes.byref(attributes),
    )
    kernel32.LocalFree(descriptor)
    if handle == invalid_handle:
        raise SetupBridgeError("INSTALL_SETUP_BRIDGE_CREATE_FAILED")
    connected = False
    try:
        deadline = time.monotonic() + CONNECT_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if kernel32.ConnectNamedPipe(handle, None):
                connected = True
                break
            error = ctypes.get_last_error()
            if error == 535:  # ERROR_PIPE_CONNECTED
                connected = True
                break
            if error != 536:  # ERROR_PIPE_LISTENING
                raise SetupBridgeError("INSTALL_SETUP_BRIDGE_CONNECT_FAILED")
            time.sleep(0.02)
        if not connected:
            raise SetupBridgeError("INSTALL_SETUP_BRIDGE_TIMEOUT")
        wait_mode = wintypes.DWORD(0)
        if not kernel32.SetNamedPipeHandleState(handle, ctypes.byref(wait_mode), None, None):
            raise SetupBridgeError("INSTALL_SETUP_BRIDGE_CONNECT_FAILED")
        client = _validate_client_sid(handle, expected_sid)
        client_context = _AUTHENTICATED_CLIENT.set(client)
        graphical = False
        try:
            header = _read_exact(handle, 8)
            try:
                size = int(header.decode("ascii"), 16)
            except (UnicodeError, ValueError) as exc:
                raise SetupBridgeError("INSTALL_SETUP_BRIDGE_REQUEST_INVALID") from exc
            if not 1 <= size <= MAX_FRAME_BYTES:
                raise SetupBridgeError("INSTALL_SETUP_BRIDGE_REQUEST_TOO_LARGE")
            request = _decode_request(_read_exact(handle, size))
            graphical = request["schema_version"] in {GRAPHICAL_MAINTENANCE_REQUEST_SCHEMA, CACHE_MAINTENANCE_REQUEST_SCHEMA, LIFECYCLE_REQUEST_SCHEMA, UPGRADE_REQUEST_SCHEMA}
            if graphical:
                def notify(phase, operation_id):
                    # The pipe is presentation only. Closing a Setup window
                    # must not cancel the shared transaction or trigger rollback.
                    try:
                        _write_all(handle, _encode_frame({"schema_version": RESULT_SCHEMA, "event": "progress",
                            "status": "running", "code": "INSTALL_PROGRAM_PROGRESS",
                            "phase": phase, "operation_id": operation_id}))
                    except SetupBridgeError:
                        pass
                response = handler(request, notify_progress=notify)
                response = {**response, "event": "result"}
            else:
                response = handler(request)
        except BaseException as exc:
            response = _blocked(_stable_code(exc))
        finally:
            _AUTHENTICATED_CLIENT.reset(client_context)
            if "request" in locals():
                request.clear()
        try:
            _write_all(handle, _encode_frame(response))
            kernel32.FlushFileBuffers(handle)
        except SetupBridgeError:
            if not graphical:
                raise
        return 0 if response["status"] == "succeeded" else 2
    finally:
        if connected:
            kernel32.DisconnectNamedPipe(handle)
        kernel32.CloseHandle(handle)


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(add_help=False)
    parser.add_argument("--pipe-name", required=True)
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
        if not _python_isolation_ready():
            raise SetupBridgeError("INSTALL_PYTHON_ISOLATION_REQUIRED")
        _sanitize_python_environment()
        raw_app_root = _prebootstrap_app_root(Path(__file__))
        sys.path.insert(0, str(raw_app_root))
        from enterprise.install_cli import _bootstrap_fixed_install_entry

        checked_root = _bootstrap_fixed_install_entry(
            Path(__file__),
            expected_name="install_setup_bridge.py",
            additional_required_files=("enterprise/install_cli.py",),
        )
        if not _same_path(checked_root, raw_app_root):
            raise SetupBridgeError("INSTALL_BOOTSTRAP_INVALID")
        return _serve_once(
            args.pipe_name,
            lambda request, **kwargs: _run_install_request(request, raw_app_root=raw_app_root, **kwargs),
        )
    except SetupBridgeError:
        return 2
    except BaseException:
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
