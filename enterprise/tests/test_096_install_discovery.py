"""Native, read-only tests of the Inno discovery implementation, not a rewrite.

Set ICE_INNO_ISCC to the pinned compiler to run the native checks. Fixtures
contain a non-executable Python sentinel; the harness cannot invoke the bridge.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest

from tools.build_install_ux_1 import _compile


SOURCE_ID = "ice-2026.09.6-8f65c5cd328f"
MANIFEST_BYTES = b"pinned manifest fixture\n"
PYTHON_BYTES = b"pinned non-executable python fixture\n"
MANIFEST_HASH = hashlib.sha256(MANIFEST_BYTES).hexdigest()


@pytest.fixture(scope="module")
def discovery_harness(tmp_path_factory):
    compiler_text = os.environ.get("ICE_INNO_ISCC")
    if os.name != "nt" or not compiler_text:
        pytest.skip("Set ICE_INNO_ISCC for native Windows discovery checks")
    root = Path(__file__).resolve().parents[2]
    output = tmp_path_factory.mktemp("discovery-compiler")
    _compile(
        iscc=Path(compiler_text),
        script=root / "enterprise/tests/fixtures/install_discovery_harness.iss",
        definitions={
            "OutputDir": str(output),
            "SourceReleaseId": SOURCE_ID,
            "SourceManifestSha256": MANIFEST_HASH,
            "SourcePythonSha256": hashlib.sha256(PYTHON_BYTES).hexdigest(),
            "DiagnosticsRelative": "staging\\operator-diagnostics",
            "MaximumMaterializedSuffixLength": "189",
        },
    )
    return output / "discovery-test.exe"


def _source(tmp_path: Path) -> Path:
    # Keep the fixture inside pytest's owned root and below legacy MAX_PATH.
    install = tmp_path.parent / ("i-" + uuid.uuid4().hex[:6])
    source = install / "releases" / SOURCE_ID
    (source / "python").mkdir(parents=True)
    (install / "data").mkdir()
    (install / "state").mkdir()
    (source / "python/python.exe").write_bytes(PYTHON_BYTES)
    (source / "release-manifest.json").write_bytes(MANIFEST_BYTES)
    (install / "data/enterprise.db").write_bytes(b"database-must-not-change")
    (install / "state/current-release.json").write_text(
        json.dumps({"release_id": SOURCE_ID, "manifest_sha256": MANIFEST_HASH}, separators=(",", ":")),
        encoding="utf-8",
    )
    return install


def _run(harness: Path, tmp_path: Path, **parameters: str) -> str:
    log = tmp_path / "discovery.log"
    result = subprocess.run(
        [str(harness), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/LOG={log}",
         *(f"/{name}={value}" for name, value in parameters.items())],
        capture_output=True, timeout=30,
    )
    assert result.returncode == 7
    output = log.read_text(encoding="utf-8-sig")
    assert "TEST_READ_ONLY_COMPLETE" in output
    return output


def test_no_match_stays_empty_and_does_not_create_install(discovery_harness, tmp_path):
    missing = tmp_path / "not-an-install"
    output = _run(discovery_harness, tmp_path, ROOT1=str(missing))
    assert "TEST_COUNT=0" in output
    assert "TEST_CHOSEN=\n" in output
    assert not missing.exists()


def test_one_pinned_match_is_selected_and_case_deduplicated(discovery_harness, tmp_path):
    install = _source(tmp_path)
    output = _run(discovery_harness, tmp_path, ROOT1=str(install), ROOT2=str(install).upper() + "\\")
    assert "TEST_COUNT=1" in output
    assert "TEST_CHOSEN=" + str(install) in output
    assert not (install / "staging").exists()
    assert (install / "data/enterprise.db").read_bytes() == b"database-must-not-change"


def test_multiple_matches_require_an_explicit_choice(discovery_harness, tmp_path):
    first, second = _source(tmp_path), _source(tmp_path)
    output = _run(discovery_harness, tmp_path, ROOT1=str(first), ROOT2=str(second))
    assert "TEST_COUNT=2" in output
    assert "TEST_CHOSEN=\n" in output
    assert not (first / "staging").exists()
    assert not (second / "staging").exists()


def test_explicit_invalid_root_never_falls_back(discovery_harness, tmp_path):
    install = _source(tmp_path)
    invalid = install.parent / "other-project"
    output = _run(discovery_harness, tmp_path, ROOT1=str(install), INSTALLROOT=str(invalid))
    assert "TEST_COUNT=1" in output
    assert "TEST_CHOSEN=" + str(invalid) in output
    assert "TEST_VALIDATION=SECURITY_BRIDGE_INSTALL_ROOT_INVALID" in output
    assert not invalid.exists()


@pytest.mark.parametrize("changed", ["pointer", "pointer-manifest", "manifest", "python", "missing-db", "oversized-pointer"])
def test_stale_or_untrusted_location_is_not_selected(discovery_harness, tmp_path, changed):
    install = _source(tmp_path)
    source = install / "releases" / SOURCE_ID
    if changed == "pointer":
        (install / "state/current-release.json").write_text(
            json.dumps({"release_id": "ice-2026.09.9-other", "manifest_sha256": MANIFEST_HASH}, separators=(",", ":")),
            encoding="utf-8",
        )
    elif changed == "pointer-manifest":
        (install / "state/current-release.json").write_text(
            json.dumps({"release_id": SOURCE_ID, "manifest_sha256": "0" * 64}, separators=(",", ":")),
            encoding="utf-8",
        )
    elif changed == "manifest":
        (source / "release-manifest.json").write_bytes(b"untrusted")
    elif changed == "python":
        (source / "python/python.exe").write_bytes(b"untrusted")
    elif changed == "missing-db":
        (install / "data/enterprise.db").unlink()
    else:
        (install / "state/current-release.json").write_bytes(b"x" * 16385)
    output = _run(discovery_harness, tmp_path, ROOT1=str(install))
    assert "TEST_COUNT=0" in output
    assert "TEST_CHOSEN=\n" in output
    assert not (install / "staging").exists()


def test_bounded_ancestor_hints_find_the_actual_root(discovery_harness, tmp_path):
    install = _source(tmp_path)
    output = _run(discovery_harness, tmp_path, NEARBY=str(install / "releases" / SOURCE_ID / "python/python.exe"))
    assert "TEST_COUNT=1" in output
    assert "TEST_CHOSEN=" + str(install) in output


def test_incomplete_discovery_never_chooses_a_single_visible_match(discovery_harness, tmp_path):
    install = _source(tmp_path)
    output = _run(discovery_harness, tmp_path, ROOT1=str(install), INCOMPLETE="1")
    assert "TEST_COUNT=1" in output
    assert "TEST_CHOSEN=\n" in output


def test_shortcut_is_read_without_execution_or_modification(discovery_harness, tmp_path):
    install = _source(tmp_path)
    shortcut = tmp_path / "project.lnk"
    target = install / "releases" / SOURCE_ID / "python/python.exe"
    # Fixture generation only: the production helper never saves a shortcut.
    command = (
        "$shell = New-Object -ComObject WScript.Shell; "
        f"$shortcut = $shell.CreateShortcut('{shortcut}'); "
        f"$shortcut.TargetPath = '{target}'; $shortcut.Save()"
    )
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                   check=True, capture_output=True, timeout=30)
    original = shortcut.read_bytes()
    output = _run(discovery_harness, tmp_path, SHORTCUT=str(shortcut))
    assert "TEST_COUNT=1" in output
    assert "TEST_CHOSEN=" + str(install) in output
    assert shortcut.read_bytes() == original
    assert (install / "data/enterprise.db").read_bytes() == b"database-must-not-change"


def test_reparse_location_is_rejected_without_touching_target(discovery_harness, tmp_path):
    install = _source(tmp_path)
    junction = install.parent / ("j-" + uuid.uuid4().hex[:6])
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         f"New-Item -ItemType Junction -Path '{junction}' -Target '{install}' -ErrorAction Stop | Out-Null"],
        check=True, capture_output=True, timeout=30,
    )
    try:
        output = _run(discovery_harness, tmp_path, ROOT1=str(junction), INSTALLROOT=str(junction))
        assert "TEST_COUNT=0" in output
        assert "TEST_VALIDATION=SECURITY_BRIDGE_INSTALL_ROOT_UNSAFE" in output
        assert (install / "data/enterprise.db").read_bytes() == b"database-must-not-change"
        assert not (install / "staging").exists()
    finally:
        # Only remove the exact link created above, never recurse into its target.
        assert junction.parent == install.parent
        os.rmdir(junction)


def test_too_long_install_is_not_auto_selected(discovery_harness, tmp_path):
    install = _source(tmp_path)
    long_root = install.parent / ("long-" + "x" * 60)
    install.rename(long_root)
    output = _run(discovery_harness, tmp_path, ROOT1=str(long_root), INSTALLROOT=str(long_root))
    assert "TEST_COUNT=0" in output
    assert "TEST_VALIDATION=SECURITY_BRIDGE_INSTALL_ROOT_TOO_LONG" in output
    assert (long_root / "data/enterprise.db").read_bytes() == b"database-must-not-change"


@pytest.mark.parametrize("invalid", ["C:\\", "\\\\example.invalid\\project"])
def test_broad_or_network_root_is_rejected(discovery_harness, tmp_path, invalid):
    install = _source(tmp_path)
    output = _run(discovery_harness, tmp_path, ROOT1=str(install), INSTALLROOT=invalid)
    assert "TEST_CHOSEN=" + invalid in output
    assert "TEST_VALIDATION=SECURITY_BRIDGE_INSTALL_ROOT_INVALID" in output
    assert (install / "data/enterprise.db").read_bytes() == b"database-must-not-change"


def test_registered_hints_are_read_only_and_revalidated(discovery_harness, tmp_path):
    import winreg

    install = _source(tmp_path)
    base = "Software\\Infinite-Canvas-Enterprise-Discovery-Tests\\" + uuid.uuid4().hex
    entries = {"valid": str(install), "stale": str(tmp_path / "not-installed")}
    try:
        for name, value in entries.items():
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + "\\" + name) as key:
                winreg.SetValueEx(key, "InstallRoot", 0, winreg.REG_SZ, value)
        output = _run(discovery_harness, tmp_path, REGISTRYKEY=base)
        assert "TEST_COUNT=1" in output
        assert "TEST_CHOSEN=" + str(install) in output
        for name, value in entries.items():
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base + "\\" + name) as key:
                assert winreg.QueryValueEx(key, "InstallRoot")[0] == value
    finally:
        for name in entries:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base + "\\" + name)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base)


def test_discovery_registry_limit_requires_manual_choice(discovery_harness, tmp_path):
    import winreg

    install = _source(tmp_path)
    base = "Software\\Infinite-Canvas-Enterprise-Discovery-Tests\\" + uuid.uuid4().hex
    try:
        for number in range(33):
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + f"\\{number:02}") as key:
                winreg.SetValueEx(key, "InstallRoot", 0, winreg.REG_SZ, str(install))
        output = _run(discovery_harness, tmp_path, REGISTRYKEY=base)
        assert "TEST_COUNT=1" in output
        assert "TEST_CHOSEN=\n" in output
    finally:
        for number in range(33):
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base + f"\\{number:02}")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base)


def test_discovery_has_no_shell_execution_or_disk_scan() -> None:
    root = Path(__file__).resolve().parents[2]
    code = (root / "installer/windows/096-install-discovery.issinc").read_text(encoding="utf-8")
    assert "SELECT ExecutablePath FROM Win32_Process" in code
    for forbidden in ("CommandLine", "FindFirst(", "FindNext(", "Exec(", "ShellExec(", ".Save"):
        assert forbidden not in code
    assert "not ValidateInstallRoot(Root, Code)" in code
    assert "PointerSize > 16384" in code
