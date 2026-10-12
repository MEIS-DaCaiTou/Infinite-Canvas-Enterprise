"""A stale/foreign uninstall registration must not release business access."""
from contextlib import nullcontext
import hashlib
import os
import sys
from types import SimpleNamespace

import pytest

from enterprise.runtime.windows_install_registration import verify_registration
from enterprise.install_cache import CacheError

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows registration adapter")


@pytest.mark.parametrize("bad", [None, "version", "path", "command", "kind", "locator", "bytes"])
def test_registration_binds_current_user_instance_target_version_and_uninstaller(tmp_path, monkeypatch, bad):
    identity = "a" * 32
    root = tmp_path / "install"; directory = root / "state/windows-maintenance"; directory.mkdir(parents=True)
    uninstaller = root / "state/windows-uninstaller/unins000.exe"; uninstaller.parent.mkdir(); uninstaller.write_bytes(b"MZ-owned-uninstaller")
    digest = hashlib.sha256(uninstaller.read_bytes()).hexdigest()
    (directory / "support.ini").write_text("[Lifecycle]\nUninstaller=unins000.exe\nUninstallerSha256=" + digest + "\n", encoding="ascii")
    uninstall_key = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\InfiniteCanvasEnterprise-" + identity + "_is1"
    locator_key = "Software\\Infinite-Canvas-Enterprise\\Installations\\" + identity
    values = {(uninstall_key, "DisplayVersion"): "2026.08.6", (uninstall_key, "Publisher"): "MEIS-DaCaiTou",
        (uninstall_key, "UninstallString"): '"' + str(uninstaller) + '"', (uninstall_key, "InstallLocation"): str(root),
        (locator_key, "InstallLocation"): str(root), (locator_key, "Launcher"): str(root / "InfiniteCanvas.exe")}
    if bad == "version": values[uninstall_key, "DisplayVersion"] = "2026.08.5"
    if bad == "path": values[uninstall_key, "InstallLocation"] = str(tmp_path / "other")
    if bad == "command": values[uninstall_key, "UninstallString"] += " /arbitrary"
    if bad == "locator": values[locator_key, "Launcher"] = str(tmp_path / "other.exe")
    if bad == "bytes": uninstaller.write_bytes(b"MZ-substituted")
    fake = SimpleNamespace(HKEY_CURRENT_USER="HKCU", KEY_READ=1, REG_SZ=1,
        OpenKey=lambda _hive, key, *_: nullcontext(key),
        QueryValueEx=lambda key, name: (values[key, name], 4 if bad == "kind" else 1))
    monkeypatch.setitem(sys.modules, "winreg", fake)
    if bad:
        with pytest.raises(CacheError, match="REGISTRATION_UNPROVEN"):
            verify_registration(root, identity, expected_version="2026.08.6")
    else:
        verify_registration(root, identity, expected_version="2026.08.6")
