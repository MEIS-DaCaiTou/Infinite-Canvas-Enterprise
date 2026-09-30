from __future__ import annotations

import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from tools.apply_096_security_bridge import (
    DIAGNOSTICS_SCHEMA,
    RESULT_SCHEMA,
    _bounded_result,
    _new_output_path,
    _result_bytes,
    _write_diagnostics,
    _write_new,
)
from tools.build_096_bridge_updater import _maximum_materialized_suffix_length


def test_gui_result_is_bounded_and_secret_free(tmp_path: Path) -> None:
    result = _bounded_result(
        {
            "result": "succeeded",
            "job_id": "a" * 32,
            "result_code": "SYSTEM_UPDATE_SUCCEEDED",
            "source_release_id": "ice-2026.09.6-8f65c5cd328f",
            "target_release_id": "ice-2026.09.9-54f9e67d1643",
            "terminal_state": "SUCCEEDED",
            "password": "must-not-leak",
            "token": "must-not-leak",
        }
    )
    assert result["schema_version"] == RESULT_SCHEMA
    encoded = _result_bytes(result)
    assert b"must-not-leak" not in encoded
    assert json.loads(encoded)["result"] == "succeeded"
    target = tmp_path / "result.json"
    _write_new(_new_output_path(str(target)), encoded)
    assert json.loads(target.read_text(encoding="utf-8"))["job_id"] == "a" * 32
    with pytest.raises(ValueError, match="SECURITY_BRIDGE_OUTPUT_PATH_INVALID"):
        _new_output_path(str(target))


def test_gui_diagnostics_are_created_without_requiring_runtime_logs(tmp_path: Path) -> None:
    target = _new_output_path(str(tmp_path / "update-diagnostics.zip"))
    _write_diagnostics(
        target,
        payload={"result": "blocked", "code": "SECURITY_BRIDGE_SOURCE_DATABASE_MISMATCH"},
        roots=None,
    )
    assert target is not None
    with zipfile.ZipFile(target) as archive:
        assert archive.namelist() == ["update-diagnostics.json"]
        payload = json.loads(archive.read("update-diagnostics.json"))
    assert payload["schema_version"] == DIAGNOSTICS_SCHEMA
    assert payload["bridge_result"]["code"] == "SECURITY_BRIDGE_SOURCE_DATABASE_MISMATCH"
    assert payload["update_diagnostics"] is None


def test_archive_path_budget_covers_atomic_publication(tmp_path: Path) -> None:
    archive = tmp_path / "release.zip"
    relative = "python/Lib/site-packages/fastapi/references/dependencies.md"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("payload/" + relative, b"fixture")
    suffix = _maximum_materialized_suffix_length(archive, "payload", "ice-test")
    partial = "releases\\.ice-test." + "0" * 32 + ".partial\\"
    bootstrap = "staging\\workspace\\security-bridge-ice-test-" + "0" * 32 + "\\"
    assert suffix == max(len(partial), len(bootstrap)) + len(relative)


@pytest.mark.parametrize("confirmed", [False, True], ids=["confirmation-required", "source-python-rejected"])
def test_compiled_updater_blocks_before_executing_untrusted_python(
    tmp_path: Path, confirmed: bool,
) -> None:
    executable_text = os.environ.get("ICE_096_UPDATER_EXE")
    manifest_text = os.environ.get("ICE_096_SOURCE_MANIFEST")
    if not executable_text or not manifest_text:
        pytest.skip("Set compiled updater and exact 09.6 source manifest for binary checks")
    install = tmp_path.parent / ("i-" + tmp_path.name[-2:])
    source = install / "releases" / "ice-2026.09.6-8f65c5cd328f"
    (source / "python").mkdir(parents=True)
    (install / "data").mkdir()
    (source / "python" / "python.exe").write_bytes(b"must-never-execute")
    (source / "release-manifest.json").write_bytes(Path(manifest_text).read_bytes())
    database = install / "data" / "enterprise.db"
    database.write_bytes(b"must-never-change")
    log = tmp_path / "setup.log"
    arguments = [str(Path(executable_text)), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                 f"/INSTALLROOT={install}", f"/LOG={log}"]
    if confirmed:
        arguments.append("/CONFIRMNOACTIVETASKS=1")
    completed = subprocess.run(arguments, capture_output=True, timeout=120)
    assert completed.returncode == 7
    expected = ("SECURITY_BRIDGE_PYTHON_IDENTITY_MISMATCH" if confirmed
                else "SECURITY_BRIDGE_ACTIVE_TASK_CONFIRMATION_REQUIRED")
    assert expected in log.read_text(encoding="utf-8-sig")
    assert database.read_bytes() == b"must-never-change"
    assert not (install / "staging" / "operator-diagnostics").exists()


def test_compiled_updater_exports_bootstrap_failure_with_bundled_python(tmp_path: Path) -> None:
    executable_text = os.environ.get("ICE_096_UPDATER_EXE")
    source_text = os.environ.get("ICE_096_RELEASE_ROOT")
    if not executable_text or not source_text:
        pytest.skip("Set compiled updater and materialized 09.6 source for bootstrap check")
    install = tmp_path.parent / ("i-" + tmp_path.name[-2:])
    source = install / "releases" / "ice-2026.09.6-8f65c5cd328f"
    shutil.copytree(Path(source_text), source)
    (install / "data").mkdir()
    database = install / "data" / "enterprise.db"
    database.write_bytes(b"must-never-change")
    # A missing current-release pointer must be rejected before Runtime control.
    log = tmp_path / "setup.log"
    completed = subprocess.run(
        [str(Path(executable_text)), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
         f"/INSTALLROOT={install}", f"/LOG={log}", "/CONFIRMNOACTIVETASKS=1"],
        capture_output=True, timeout=180,
    )
    assert completed.returncode == 7
    archives = list((install / "staging" / "operator-diagnostics").glob("*.zip"))
    assert len(archives) == 1
    with zipfile.ZipFile(archives[0]) as archive:
        result = json.loads(archive.read("update-diagnostics.json"))["bridge_result"]
    assert result["result"] == "blocked"
    assert result["code"] == "CURRENT_RELEASE_MISSING"
    assert result["code"] in log.read_text(encoding="utf-8-sig")
    assert database.read_bytes() == b"must-never-change"
    assert not (install / "state").exists()


def test_one_click_updater_is_gui_only_and_uses_the_reviewed_bridge() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "installer" / "windows" / "InfiniteCanvasEnterprise096Bridge.iss").read_text(
        encoding="utf-8"
    )
    lowered = source.casefold()
    assert "privilegesrequired=lowest" in lowered
    assert "uninstallable=no" in lowered
    assert "powershell" not in lowered
    assert "cmd.exe" not in lowered
    assert "sw_hide" in lowered
    assert "ewwaituntilterminated" in lowered
    assert "-i -b" in lowered
    assert "apply_096_security_bridge.py" not in source  # injected as a pinned filename definition
    assert "{#BridgeBootstrapFilename}" in source
    assert "--confirm-no-active-tasks" in source
    assert "--result-file" in source
    assert "--diagnostics-file" in source
    assert "GetSHA256OfFile" in source
    assert "SECURITY_BRIDGE_EMBEDDED_ASSET_HASH_MISMATCH" in source
    assert "ConfirmationPage.Values[0]" in source
    assert "WizardSilent" in source
    assert "{param:CONFIRMNOACTIVETASKS|}" in source
    assert "SECURITY_BRIDGE_ACTIVE_TASK_CONFIRMATION_REQUIRED" in source
    assert "SelectedInstallRoot := InstallRootPage.Values[0]" in source
    assert "ValidateInstallRoot(SelectedInstallRoot" in source
    assert "{#MaximumMaterializedSuffixLength}" in source
    assert "SECURITY_BRIDGE_INSTALL_ROOT_TOO_LONG" in source
    assert "InstallRootPage.Values[0] := DetectInstallRoot" in source
    assert "HasUnsafeAncestor(DiagnosticsRoot)" in source
    assert "SourcePythonSha256" in source
    assert "TerminalState = 'RECOVERY_REQUIRED'" in source
    assert "data\\enterprise.db" in source
    assert "2026.09.9" in source


def test_bridge_updater_policy_binds_one_exact_source_and_target() -> None:
    root = Path(__file__).resolve().parents[2]
    policy = json.loads(
        (root / "installer" / "windows" / "096-bridge-updater-build-policy.json").read_text(
            encoding="utf-8"
        )
    )
    assert policy == {
        "bootstrap_asset": "tools/apply_096_security_bridge.py",
        "diagnostics_relative": "staging/operator-diagnostics",
        "installer_architecture": "x64",
        "installer_filename": "Infinite-Canvas-Enterprise-096-to-099-Updater-x64.exe",
        "installer_source": "installer/windows/InfiniteCanvasEnterprise096Bridge.iss",
        "privileges": "current-user-lowest",
        "schema_version": "security-bridge-updater-build-policy-v1",
        "source_manifest_sha256": "e183631d52bbd0955477dfc6f6540aea99a0e173bb11821544a1db926a2cb85d",
        "source_python_sha256": "03168c01b7b7491423350e82c26fee71f35b43694d1319d3c668bda6903a0c38",
        "source_release_id": "ice-2026.09.6-8f65c5cd328f",
        "target_version": "2026.09.9",
        "uninstaller_created": False,
    }
