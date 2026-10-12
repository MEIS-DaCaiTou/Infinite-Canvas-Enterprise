"""Read-only, current-user registration attestation for the offline installer."""
from __future__ import annotations

from configparser import ConfigParser
import os
from pathlib import Path
import re

from enterprise import install_cache as files


def verify_registration(root: Path, installation_id: str):
    if os.name != "nt":
        raise files.CacheError("INSTALL_WINDOWS_REQUIRED")
    import winreg
    root = files._safe(root)
    parser = ConfigParser(interpolation=None, strict=True)
    raw = files._io(root / "state/windows-maintenance/support.ini").read_bytes()
    parser.read_string(raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"))
    section = parser["Lifecycle"]
    name, digest = section.get("uninstaller", ""), section.get("uninstallersha256", "")
    if not re.fullmatch(r"unins[0-9]{3}\.exe", name) or not files.SHA.fullmatch(digest):
        raise files.CacheError("INSTALL_UPGRADE_REGISTRATION_UNPROVEN")
    uninstaller = root / "state/windows-uninstaller" / name
    if files._file(uninstaller)["sha256"] != digest:
        raise files.CacheError("INSTALL_UPGRADE_REGISTRATION_UNPROVEN")
    def query(key, field):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_READ) as handle:
                value, kind = winreg.QueryValueEx(handle, field)
                if kind != winreg.REG_SZ or not isinstance(value, str):
                    raise ValueError()
                return value
        except (OSError, ValueError) as exc:
            raise files.CacheError("INSTALL_UPGRADE_REGISTRATION_UNPROVEN") from exc
    def same(left, right):
        return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))
    key = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\InfiniteCanvasEnterprise-" + installation_id + "_is1"
    command = query(key, "UninstallString")
    if not command.startswith('"') or '"' not in command[1:]:
        raise files.CacheError("INSTALL_UPGRADE_REGISTRATION_UNPROVEN")
    executable, remainder = command[1:].split('"', 1)
    if remainder.strip() or not same(executable, uninstaller) or not same(query(key, "InstallLocation"), root):
        raise files.CacheError("INSTALL_UPGRADE_REGISTRATION_UNPROVEN")
    locator = "Software\\Infinite-Canvas-Enterprise\\Installations\\" + installation_id
    if not same(query(locator, "InstallLocation"), root) or not same(query(locator, "Launcher"), root / "InfiniteCanvas.exe"):
        raise files.CacheError("INSTALL_UPGRADE_REGISTRATION_UNPROVEN")
