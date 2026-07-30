from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "tools" / "validation" / "windows" / "env_1b3"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")
TASK_ID = "ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE"


def _run_powershell(script: str) -> subprocess.CompletedProcess[str]:
    assert POWERSHELL is not None
    return subprocess.run(
        [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_fixture(
    root: Path,
    *,
    enterprise_commit: str = "a" * 40,
    enterprise_tree: str = "b" * 40,
) -> tuple[Path, Path, Path]:
    root.mkdir()
    payloads = {"empty.txt": b"", "payload.txt": b"candidate\n"}
    entries = [
        {"path": relative, "sha256": _sha256(payload), "size_bytes": len(payload)}
        for relative, payload in payloads.items()
    ]
    tree_lines = b"".join(
        f"{entry['path']}\0{entry['size_bytes']}\0{entry['sha256']}\n".encode()
        for entry in entries
    )
    inventory = {
        "schema_version": "ops-release-payload-inventory-v1",
        "entries": entries,
        "file_count": len(entries),
        "total_size_bytes": sum(len(payload) for payload in payloads.values()),
        "tree_sha256": _sha256(tree_lines),
    }
    inventory_path = root / "release-payload-inventory.json"
    inventory_bytes = (json.dumps(inventory, sort_keys=True, separators=(",", ":")) + "\n").encode()
    inventory_path.write_bytes(inventory_bytes)

    archive_path = root / "fixture.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for relative, payload in payloads.items():
            archive.writestr(f"fixture/{relative}", payload)
        archive.writestr("fixture/release-payload-inventory.json", inventory_bytes)
    archive_bytes = archive_path.read_bytes()
    inventory_hash = _sha256(inventory_bytes)
    manifest = {
        "schema_version": "ops-release-manifest-v2",
        "enterprise_source": {"commit": enterprise_commit, "tree": enterprise_tree},
        "identity": {"release_id": "fixture-release"},
        "archive": {
            "filename": archive_path.name,
            "inventory_sha256": inventory_hash,
            "root_prefix": "fixture",
            "sha256": _sha256(archive_bytes),
            "size_bytes": len(archive_bytes),
        },
        "release_payload": {
            "file_count": len(entries),
            "inventory_path": inventory_path.name,
            "inventory_sha256": inventory_hash,
            "static_tree_sha256": "0" * 64,
            "total_size_bytes": inventory["total_size_bytes"],
            "tree_sha256": inventory["tree_sha256"],
        },
        "runtime": {"runtime_tree_sha256": "1" * 64},
    }
    manifest_path = root / "ops-release-manifest-v2.json"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest_path, archive_path, inventory_path


def _generate_handoff(tmp_path: Path, *, sequence: str = "04", kit: Path = KIT) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", repository], check=True)
    subprocess.run(["git", "-C", repository, "config", "user.name", "ENV-1B3 fixture"], check=True)
    subprocess.run(["git", "-C", repository, "config", "user.email", "fixture@example.invalid"], check=True)
    (repository / "tracked.txt").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "-C", repository, "add", "tracked.txt"], check=True)
    subprocess.run(["git", "-C", repository, "commit", "-q", "-m", "fixture"], check=True)
    commit = subprocess.check_output(["git", "-C", repository, "rev-parse", "HEAD"], text=True).strip()
    tree = subprocess.check_output(["git", "-C", repository, "rev-parse", "HEAD^{tree}"], text=True).strip()

    candidate = tmp_path / f"candidate-{sequence}"
    candidate.mkdir()
    build = candidate / "release-build"
    _write_fixture(build, enterprise_commit=commit, enterprise_tree=tree)
    taskbook = tmp_path / "taskbook.md"
    taskbook.write_text("# Independent test-host taskbook\n", encoding="utf-8", newline="\n")
    script = kit / "New-CandidateHandoff.ps1"
    completed = subprocess.run(
        [
            POWERSHELL,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-Repository",
            str(repository),
            "-BuildRoot",
            str(build),
            "-CandidateRoot",
            str(candidate),
            "-CandidateSequence",
            sequence,
            "-TestHostTaskbook",
            str(taskbook),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return candidate / "handoff"


def _generate_w01_probe_fixture(tmp_path: Path) -> tuple[Path, Path, str, str]:
    repository = tmp_path / "probe-repository"
    kit = repository / "tools" / "validation" / "windows" / "env_1b3"
    kit.mkdir(parents=True)
    for name in (
        "ENV1B3.Validation.psm1",
        "Invoke-EnvironmentBaseline.ps1",
        "Invoke-W01StabilizationProbe.ps1",
        "New-W01StabilizationProbe.ps1",
    ):
        shutil.copyfile(KIT / name, kit / name)
    subprocess.run(["git", "init", "-q", repository], check=True)
    subprocess.run(["git", "-C", repository, "config", "user.name", "ENV-1B3 fixture"], check=True)
    subprocess.run(["git", "-C", repository, "config", "user.email", "fixture@example.invalid"], check=True)
    subprocess.run(["git", "-C", repository, "add", "tools"], check=True)
    subprocess.run(["git", "-C", repository, "commit", "-q", "-m", "fixture"], check=True)
    head = subprocess.check_output(["git", "-C", repository, "rev-parse", "HEAD"], text=True).strip()
    tree = subprocess.check_output(["git", "-C", repository, "rev-parse", "HEAD^{tree}"], text=True).strip()
    output = tmp_path / "probe-output"
    completed = subprocess.run(
        [
            POWERSHELL,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(kit / "New-W01StabilizationProbe.ps1"),
            "-Repository",
            str(repository),
            "-OutputRoot",
            str(output),
            "-ExpectedCandidateId",
            "ice-2026.07.6-c14cd8341a25-candidate-04",
            "-ExpectedCandidateHead",
            "c14cd8341a25de08fdfec1d83f3b1581a10c2723",
            "-ExpectedCandidateTree",
            "b852d18e38f4615fb4bc9a8c0e26f24a2fbf194b",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return output / f"ENV-1B3-W01-STABILIZATION-PROBE-{head}.zip", output, head, tree


def _run_validation_entrypoint(
    entrypoint: Path,
    handoff: Path,
    test_root: Path,
    evidence_root: Path,
    *,
    prelude: str,
) -> subprocess.CompletedProcess[str]:
    def escaped(path: Path) -> str:
        return str(path).replace("'", "''")

    command = (
        "Set-StrictMode -Version 2.0;"
        + prelude
        + f";& '{escaped(entrypoint)}' -Mode Verify -HandoffRoot '{escaped(handoff)}'"
        + f" -TestRoot '{escaped(test_root)}' -EvidenceRoot '{escaped(evidence_root)}';"
        + "$entrypointSucceeded=$?;"
        + "if($entrypointSucceeded){exit 0};"
        + "$exitVariable=Get-Variable -Name LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue;"
        + "if($null -ne $exitVariable){exit [int]$exitVariable.Value};exit 2"
    )
    return _run_powershell(command)


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
def test_all_windows_validation_scripts_parse() -> None:
    escaped_kit = str(KIT).replace("'", "''")
    command = (
        "$errors=@();Get-ChildItem -LiteralPath '"
        + escaped_kit
        + "'"
        + " -File | Where-Object Extension -in '.ps1','.psm1' | ForEach-Object {$parse=$null;"
        + "[void][Management.Automation.Language.Parser]::ParseFile($_.FullName,[ref]$null,[ref]$parse);"
        + "$errors+=@($parse)};if($errors.Count){$errors|ForEach-Object ToString;exit 2}"
    )
    result = _run_powershell(command)
    assert result.returncode == 0, result.stdout + result.stderr


def test_matrix_and_single_entrypoint_are_closed() -> None:
    expected_files = {
        "ENV1B3.Validation.psm1",
        "Export-ValidationEvidence.ps1",
        "Invoke-ArtifactVerification.ps1",
        "Invoke-ENV1B3Validation.ps1",
        "Invoke-EnvironmentBaseline.ps1",
        "Invoke-LifecycleMatrix.ps1",
        "Invoke-Materialization.ps1",
        "Invoke-PermissionMatrix.ps1",
        "Invoke-RebootResume.ps1",
        "Invoke-ResourceInterferenceMatrix.ps1",
        "Invoke-TamperMatrix.ps1",
        "Invoke-W01StabilizationProbe.ps1",
        "New-CandidateHandoff.ps1",
        "New-W01StabilizationProbe.ps1",
        "README.md",
        "matrix.json",
    }
    assert {path.name for path in KIT.iterdir() if path.is_file()} == expected_files
    matrix = json.loads((KIT / "matrix.json").read_text(encoding="utf-8"))
    assert matrix["overall_task_id"] == TASK_ID
    assert matrix["matrix_version"] == "env-1b3-windows-validation-matrix-v1"
    assert [record["case_id"] for record in matrix["cases"]] == [f"W{i:02d}" for i in range(1, 15)]
    assert len({record["script"] for record in matrix["cases"]}) < len(matrix["cases"])


def test_test_host_kit_has_no_repository_mutation_or_python_fallback() -> None:
    forbidden = (
        "git add",
        "git commit",
        "git push",
        "git checkout",
        "git reset",
        "git clean",
        "pip install",
        "invoke-webrequest",
        "start-bitstransfer",
    )
    for path in KIT.glob("*.ps1"):
        if path.name == "New-CandidateHandoff.ps1":
            continue
        text = path.read_text(encoding="utf-8").lower()
        assert not any(token in text for token in forbidden), (path, text)
        if path.name != "Invoke-EnvironmentBaseline.ps1":
            assert "windowsapps" not in text
    lifecycle = (KIT / "Invoke-LifecycleMatrix.ps1").read_text(encoding="utf-8")
    materialize = (KIT / "Invoke-Materialization.ps1").read_text(encoding="utf-8")
    assert "$env:ComSpec" in lifecycle
    assert "python\\python.exe" in materialize
    assert "Get-Command python" not in lifecycle + materialize


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
@pytest.mark.parametrize(
    ("candidate", "allowed"),
    [
        ("folder/file with space.txt", True),
        ("Unicode/测试.txt", True),
        ("../escape.txt", False),
        ("folder\\file.txt", False),
        ("C:/absolute.txt", False),
        ("file.txt:stream", False),
        ("CON.txt", False),
    ],
)
def test_safe_relative_path_contract(candidate: str, allowed: bool) -> None:
    escaped_module = str(KIT / "ENV1B3.Validation.psm1").replace("'", "''")
    escaped_candidate = candidate.replace("'", "''")
    result = _run_powershell(
        f"Import-Module '{escaped_module}' -Force; if(Test-ENV1B3SafeRelativePath '{escaped_candidate}'){{exit 0}}else{{exit 2}}"
    )
    assert (result.returncode == 0) is allowed


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
def test_install_date_normalization_is_nullable_invariant_and_locale_independent() -> None:
    module = str(KIT / "ENV1B3.Validation.psm1").replace("'", "''")
    command = (
        f"Import-Module '{module}' -Force;"
        "$date=[DateTime]::SpecifyKind([DateTime]::new(2026,2,4,10,48,36),[DateTimeKind]::Utc);"
        "$dmtf=[Management.ManagementDateTimeConverter]::ToDmtfDateTime($date);"
        "$oldCulture=[Threading.Thread]::CurrentThread.CurrentCulture;"
        "$oldUi=[Threading.Thread]::CurrentThread.CurrentUICulture;"
        "try {"
        "$items=[ordered]@{};"
        "$items.datetime=ConvertTo-ENV1B3UtcIso8601 $date;"
        "$items.dmtf=ConvertTo-ENV1B3UtcIso8601 $dmtf;"
        "$items.missing=ConvertTo-ENV1B3UtcIso8601 $null;"
        "$items.invalid=ConvertTo-ENV1B3UtcIso8601 'not-a-dmtf-date';"
        "[Threading.Thread]::CurrentThread.CurrentCulture=[Globalization.CultureInfo]::GetCultureInfo('zh-CN');"
        "[Threading.Thread]::CurrentThread.CurrentUICulture=[Globalization.CultureInfo]::GetCultureInfo('zh-CN');"
        "$items.zh=ConvertTo-ENV1B3UtcIso8601 $date;"
        "[Threading.Thread]::CurrentThread.CurrentCulture=[Globalization.CultureInfo]::GetCultureInfo('en-US');"
        "[Threading.Thread]::CurrentThread.CurrentUICulture=[Globalization.CultureInfo]::GetCultureInfo('en-US');"
        "$items.en=ConvertTo-ENV1B3UtcIso8601 $date;"
        "$items|ConvertTo-Json -Depth 5 -Compress"
        "} finally {"
        "[Threading.Thread]::CurrentThread.CurrentCulture=$oldCulture;"
        "[Threading.Thread]::CurrentThread.CurrentUICulture=$oldUi"
        "}"
    )
    result = _run_powershell(command)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["datetime"] == {"value": "2026-02-04T10:48:36.0000000Z", "diagnostic": "datetime"}
    assert payload["dmtf"] == {"value": "2026-02-04T10:48:36.0000000Z", "diagnostic": "dmtf"}
    assert payload["missing"] == {"value": None, "diagnostic": "missing"}
    assert payload["invalid"] == {"value": None, "diagnostic": "invalid_format"}
    assert payload["zh"] == payload["en"] == payload["datetime"]


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
@pytest.mark.parametrize("previous_exit", [0, 7])
def test_where_lookup_treats_real_absence_as_normal_under_strict_stop(previous_exit: int) -> None:
    module = str(KIT / "ENV1B3.Validation.psm1").replace("'", "''")
    missing = f"env1b3-certainly-absent-{previous_exit}-f3b19.exe"
    command = (
        "Set-StrictMode -Version Latest;$ErrorActionPreference='Stop';"
        f"Import-Module '{module}' -Force;"
        f"& $env:ComSpec /d /c exit {previous_exit} | Out-Null;"
        f"$missing=Invoke-ENV1B3WhereLookup '{missing}';"
        "$found=Invoke-ENV1B3WhereLookup 'cmd.exe';"
        "$failed=$null;try{ConvertTo-ENV1B3WhereDiscoveryResult -ExitCode 7 -Stdout '' -Stderr 'fixture'}catch{$failed=$_.Exception.Message};"
        "[ordered]@{script_continues=$true;usable_external_python_present=$missing.found;baseline_collection_failed=$false;missing=$missing;found=$found;unexpected=$failed}|ConvertTo-Json -Depth 6 -Compress"
    )
    result = _run_powershell(command)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["script_continues"] is True
    assert payload["usable_external_python_present"] is False
    assert payload["baseline_collection_failed"] is False
    assert payload["missing"]["exit_code"] == 1
    assert payload["missing"]["found"] is False
    assert payload["missing"]["diagnostic_failed"] is False
    assert payload["found"]["exit_code"] == 0
    assert payload["found"]["found"] is True
    assert payload["unexpected"].startswith("ENV1B3_WHERE_DIAGNOSTIC_FAILED|")


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
def test_display_name_filter_is_strict_mode_safe_for_mixed_registry_objects() -> None:
    module = str(KIT / "ENV1B3.Validation.psm1").replace("'", "''")
    command = (
        "Set-StrictMode -Version Latest;$ErrorActionPreference='Stop';"
        f"Import-Module '{module}' -Force;"
        "$items=@("
        "[pscustomobject]@{DisplayName='English App'},"
        "[pscustomobject]@{Other='missing'},"
        "[pscustomobject]@{DisplayName=$null},"
        "[pscustomobject]@{DisplayName=''},"
        "[pscustomobject]@{DisplayName=42},"
        "[pscustomobject]@{DisplayName='中文应用'});"
        "$json=@(Get-ENV1B3DisplayNames $items)|ConvertTo-Json -Compress;"
        "[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))"
    )
    result = _run_powershell(command)
    assert result.returncode == 0, result.stdout + result.stderr
    encoded = result.stdout.strip().splitlines()[-1]
    assert json.loads(base64.b64decode(encoded).decode("utf-8")) == ["English App", "42", "中文应用"]


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
def test_w01_clean_guest_fixture_passes_with_alias_and_recorded_bypassnro() -> None:
    module = str(KIT / "ENV1B3.Validation.psm1").replace("'", "''")
    command = (
        "Set-StrictMode -Version Latest;$ErrorActionPreference='Stop';"
        f"Import-Module '{module}' -Force;"
        "$commands=@([ordered]@{name='python';found=$true;alias_stub=$true;usable=$false},"
        "[pscustomobject]@{name='python3';found=$false;alias_stub=$false;usable=$false},"
        "[pscustomobject]@{name='py';found=$false;alias_stub=$false;usable=$false});"
        "$result=Test-ENV1B3CleanRuntimeBaseline -Classification fresh_vm_snapshot -ApplicationUserIsAdmin $false "
        "-InstallTimePresent $true -PythonCommands $commands -PythonRegistryPresent $false "
        "-MicrosoftStorePythonPresent $false -ProjectStatePreexisting $false -BypassNroRecorded $true;"
        "$external=Test-ENV1B3CleanRuntimeBaseline -Classification fresh_vm_snapshot -ApplicationUserIsAdmin $false "
        "-InstallTimePresent $true -PythonCommands @([ordered]@{usable=$true;alias_stub=$false}) -PythonRegistryPresent $false "
        "-MicrosoftStorePythonPresent $false -ProjectStatePreexisting $false -BypassNroRecorded $false;"
        "[ordered]@{clean=$result;external=$external}|ConvertTo-Json -Depth 6 -Compress"
    )
    result = _run_powershell(command)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    clean = payload["clean"]
    assert clean["result"] == "PASS"
    assert clean["usable_external_python_present"] is False
    assert clean["no_system_python_runtime"] is True
    assert clean["recorded_oobe_deviation"] is True
    assert clean["pristine_oobe_baseline"] is False
    assert clean["clean_windows_runtime_baseline"] is True
    assert payload["external"]["result"] == "FAIL"
    assert payload["external"]["usable_external_python_present"] is True


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
def test_offline_release_artifact_verification_and_tamper(tmp_path: Path) -> None:
    manifest, archive, inventory = _write_fixture(tmp_path / "fixture")
    module = str(KIT / "ENV1B3.Validation.psm1").replace("'", "''")
    command = (
        f"Import-Module '{module}' -Force;"
        f"$r=Test-ENV1B3ReleaseArtifacts -ManifestPath '{manifest}' -ArchivePath '{archive}' -InventoryPath '{inventory}';"
        "$r|ConvertTo-Json -Compress"
    )
    result = _run_powershell(command)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1])["result"] == "pass"

    with archive.open("ab") as stream:
        stream.write(b"tamper")
    failed = _run_powershell(command)
    assert failed.returncode != 0


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
def test_candidate_handoff_readme_is_safe_and_bound(tmp_path: Path) -> None:
    handoff = _generate_handoff(tmp_path, sequence="04")
    readme_bytes = (handoff / "README-FIRST.md").read_bytes()
    assert not readme_bytes.startswith(b"\xef\xbb\xbf")
    assert all(value >= 0x20 or value in (0x09, 0x0A, 0x0D) for value in readme_bytes)
    readme = readme_bytes.decode("utf-8")
    assert "fixture-release-candidate-04" in readme
    assert "$candidateId" not in readme
    assert ".\\validation-kit\\Invoke-ENV1B3Validation.ps1" in readme
    assert "ENV-1B3-INDEPENDENT-WINDOWS-TEST-HOST-CODEX-TASK.md" in readme
    assert "validation-kit/README.md" in readme
    for parameter in ("-HandoffRoot", "-TestRoot", "-EvidenceRoot", "-CleanHostClassification"):
        assert parameter in readme

    sums = {}
    for line in (handoff / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        sums[relative] = digest
    assert sums["README-FIRST.md"] == _sha256(readme_bytes)
    handoff_json = json.loads((handoff / "CANDIDATE-HANDOFF.json").read_text(encoding="utf-8"))
    copied_taskbook = handoff / "ENV-1B3-INDEPENDENT-WINDOWS-TEST-HOST-CODEX-TASK.md"
    assert handoff_json["expected_test_host_taskbook_sha256"] == _sha256(copied_taskbook.read_bytes())


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
def test_w01_probe_bundle_is_diagnostic_closed_and_fixture_passes(tmp_path: Path) -> None:
    probe_zip, _, head, tree = _generate_w01_probe_fixture(tmp_path)
    assert probe_zip.is_file()
    extracted = tmp_path / "extracted-probe"
    with zipfile.ZipFile(probe_zip) as archive:
        assert set(archive.namelist()) == {
            "ENV1B3.Validation.psm1",
            "Invoke-EnvironmentBaseline.ps1",
            "Invoke-W01StabilizationProbe.ps1",
            "PROBE-MANIFEST.json",
            "SHA256SUMS",
        }
        archive.extractall(extracted)
    manifest = json.loads((extracted / "PROBE-MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["developer_head"] == head
    assert manifest["developer_tree"] == tree
    assert manifest["expected_candidate_04_id"] == "ice-2026.07.6-c14cd8341a25-candidate-04"
    assert manifest["diagnostic_only"] is True
    assert manifest["not_a_release_candidate"] is True
    assert manifest["cannot_support_final_acceptance"] is True
    assert manifest["production_approved"] is False
    sums = {}
    for line in (extracted / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        sums[name] = digest
    payload_files = {path.name for path in extracted.iterdir() if path.is_file() and path.name != "SHA256SUMS"}
    assert set(sums) == payload_files
    assert all(_sha256((extracted / name).read_bytes()) == digest for name, digest in sums.items())

    fixture = tmp_path / "clean-guest-fixture.json"
    fixture.write_text(
        json.dumps(
            {
                "schema_version": "env-1b3-w01-probe-fixture-v1",
                "application_user_is_admin": False,
                "install_time_present": True,
                "python_commands": [
                    {"name": "python", "found": True, "alias_stub": True, "usable": False},
                    {"name": "python3", "found": False, "alias_stub": False, "usable": False},
                    {"name": "py", "found": False, "alias_stub": False, "usable": False},
                ],
                "python_registry_present": False,
                "microsoft_store_python_present": False,
                "project_state_preexisting": False,
                "bypass_nro_recorded": True,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    evidence = tmp_path / "probe-evidence"
    completed = subprocess.run(
        [
            POWERSHELL,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(extracted / "Invoke-W01StabilizationProbe.ps1"),
            "-TestRoot",
            str(tmp_path / "test-root"),
            "-EvidenceRoot",
            str(evidence),
            "-Classification",
            "fresh_vm_snapshot",
            "-FixturePath",
            str(fixture),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads((evidence / "W01.json").read_text(encoding="utf-8"))
    assert result["result"] == "PASS"
    assert result["evidence"]["usable_external_python_present"] is False
    assert result["evidence"]["no_system_python_runtime"] is True
    assert result["evidence"]["recorded_oobe_deviation"] is True
    assert result["evidence"]["pristine_oobe_baseline"] is False
    assert result["evidence"]["clean_windows_runtime_baseline"] is True


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
@pytest.mark.parametrize(
    "prelude",
    [
        "Remove-Variable -Name LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue",
        "& $env:ComSpec /d /c exit 0 | Out-Null",
        "& $env:ComSpec /d /c exit 7 | Out-Null",
    ],
)
def test_entrypoint_ignores_unset_or_stale_native_exit_for_successful_powershell_step(
    tmp_path: Path, prelude: str
) -> None:
    handoff = _generate_handoff(tmp_path / "fixture", sequence="04")
    result = _run_validation_entrypoint(
        KIT / "Invoke-ENV1B3Validation.ps1",
        handoff,
        tmp_path / "test-root",
        tmp_path / "evidence",
        prelude=prelude,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1])["code"] == "ENV1B3_ARTIFACT_VERIFY_PASS"


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
@pytest.mark.parametrize(("native_exit", "expected_exit"), [(0, 0), (7, 2)])
def test_entrypoint_current_native_verifier_exit_is_fail_closed(
    tmp_path: Path, native_exit: int, expected_exit: int
) -> None:
    handoff = _generate_handoff(tmp_path / "fixture", sequence="04")
    test_kit = tmp_path / "validation-kit"
    shutil.copytree(KIT, test_kit)
    verifier = test_kit / "Invoke-ArtifactVerification.ps1"
    verifier.write_text(
        "Set-StrictMode -Version 2.0\n"
        "$ErrorActionPreference='Stop'\n"
        f"& $env:ComSpec /d /c exit {native_exit}\n"
        "$code=$LASTEXITCODE\n"
        "if($code -ne 0){throw [InvalidOperationException]::new('NATIVE_VERIFIER_FAILED')}\n"
        "[ordered]@{code='FIXTURE_NATIVE_PASS';status='pass'}|ConvertTo-Json -Compress\n",
        encoding="utf-8",
        newline="\n",
    )
    result = _run_validation_entrypoint(
        test_kit / "Invoke-ENV1B3Validation.ps1",
        handoff,
        tmp_path / "test-root",
        tmp_path / "evidence",
        prelude="Remove-Variable -Name LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue",
    )
    assert result.returncode == expected_exit, result.stdout + result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["code"] == ("FIXTURE_NATIVE_PASS" if expected_exit == 0 else "ENV1B3_ENTRYPOINT_POWERSHELL_STEP_FAILED")


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
def test_entrypoint_powershell_step_exception_has_stable_failure(tmp_path: Path) -> None:
    handoff = _generate_handoff(tmp_path / "fixture", sequence="04")
    test_kit = tmp_path / "validation-kit"
    shutil.copytree(KIT, test_kit)
    (test_kit / "Invoke-ArtifactVerification.ps1").write_text(
        "throw [InvalidOperationException]::new('fixture failure')\n",
        encoding="utf-8",
        newline="\n",
    )
    result = _run_validation_entrypoint(
        test_kit / "Invoke-ENV1B3Validation.ps1",
        handoff,
        tmp_path / "test-root",
        tmp_path / "evidence",
        prelude="Remove-Variable -Name LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue",
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1])["code"] == "ENV1B3_ENTRYPOINT_POWERSHELL_STEP_FAILED"
