from __future__ import annotations

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
        "New-CandidateHandoff.ps1",
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

    candidate = tmp_path / "candidate-03"
    candidate.mkdir()
    build = candidate / "release-build"
    _write_fixture(build, enterprise_commit=commit, enterprise_tree=tree)
    taskbook = tmp_path / "taskbook.md"
    taskbook.write_text("# Independent test-host taskbook\n", encoding="utf-8", newline="\n")
    script = KIT / "New-CandidateHandoff.ps1"
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
            "03",
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

    handoff = candidate / "handoff"
    readme_bytes = (handoff / "README-FIRST.md").read_bytes()
    assert not readme_bytes.startswith(b"\xef\xbb\xbf")
    assert all(value >= 0x20 or value in (0x09, 0x0A, 0x0D) for value in readme_bytes)
    readme = readme_bytes.decode("utf-8")
    assert "fixture-release-candidate-03" in readme
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
