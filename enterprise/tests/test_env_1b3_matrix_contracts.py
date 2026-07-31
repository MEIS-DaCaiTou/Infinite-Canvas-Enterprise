from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "tools" / "validation" / "windows" / "env_1b3"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")
EXPECTED_MODES = {
    "W02", "W03", "W04", "W05", "W06", "W07", "W08", "W09", "W10",
    "W11StoppedPrepare", "W11StoppedResume", "W11RunningPrepare", "W11RunningResume",
    "W12", "W13", "W14Prepare", "W14Validate", "M01",
}
EXPECTED_V3_MODES = {
    "W05", "W08", "W09", "W10",
    "W11StoppedPrepare", "W11StoppedResume", "W11RunningPrepare", "W11RunningResume",
    "W12EvidenceAudit", "W13", "ContractAudit",
}
EXPECTED_V3R1_MODES = {
    "W05", "W08Pointer", "W08ReleaseManifest", "W08RuntimeManifest", "W08Payload", "W08PythonDll",
    "W08Aggregate", "W09", "W10",
    "W11StoppedPrepare", "W11StoppedResume", "W11RunningPrepare", "W11RunningResume",
    "W12EvidenceAudit", "W13", "ContractAudit",
}
EXPECTED_V3R2_GUEST_MODES = {
    "W05", "W08Pointer", "W08ReleaseManifest", "W08RuntimeManifest", "W08Payload", "W08PythonDll",
    "W09", "W10", "W11StoppedPrepare", "W11StoppedResume", "W11RunningPrepare", "W11RunningResume", "W13",
}
EXPECTED_V3R2_HOST_MODES = {"W08HostAggregate", "W12EvidenceAudit", "ContractAudit"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hashes_sha256(values: dict[str, str]) -> str:
    canonical = "".join(f"{key}={values[key]}\n" for key in sorted(values))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _run_ps(command: str, *, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    assert POWERSHELL is not None
    return subprocess.run(
        [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=cwd,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=120,
        check=False,
    )


def test_matrix_contract_schema_closes_w01_through_w14() -> None:
    document = json.loads((KIT / "matrix-contracts.json").read_text(encoding="utf-8"))
    assert document["schema_version"] == "env-1b3-matrix-contracts-v2"
    assert document["matrix_version"] == "env-1b3-windows-validation-matrix-v1"
    cases = {case["case_id"]: case for case in document["cases"]}
    assert set(cases) == {f"W{number:02d}" for number in range(1, 15)}
    for case in cases.values():
        assert case["mandatory_subchecks"]
        assert len(case["mandatory_subchecks"]) == len(set(case["mandatory_subchecks"]))
        assert case["required_execution_context"] is not None
        assert case["required_fixtures"] is not None
        assert case["required_evidence_fields"]
        assert case["pass_aggregation_rule"] == "all_mandatory_subchecks_pass"
        assert case["subcheck_overwrite_allowed"] is False
        assert case["stable_error_codes"]

    assert cases["W06"]["mandatory_subchecks"] == ["readonly_app_root", "denied_writable_root"]
    assert cases["W09"]["mandatory_subchecks"] == [
        "owned_stop_after_tamper", "foreign_stop_rejected", "foreign_process_survived", "owned_cleanup_succeeded"
    ]
    assert cases["W12"]["mandatory_subchecks"] == [
        "archive_preflight_low_space", "materialization_low_space", "writable_root_low_space", "pointer_atomicity"
    ]
    assert cases["W13"]["mandatory_subchecks"] == [
        "archive_lock_failure", "recovery_after_lock_release", "defender_enabled", "controlled_scan_result",
        "permanent_exclusions_absent", "permanent_exclusions_unchanged",
    ]


def test_probe_v2_dispatcher_exposes_every_required_public_mode() -> None:
    source = (KIT / "Invoke-RemainingMatrixProbeV2.ps1").read_text(encoding="utf-8")
    match = re.search(r"ValidateSet\((.*?)\)\]\[string\]\$Mode", source, re.S)
    assert match
    modes = set(re.findall(r"'([^']+)'", match.group(1)))
    assert modes == EXPECTED_MODES
    assert "Invoke-MatrixContractCase.ps1" in source


def test_probe_v3_dispatcher_and_failed_case_contract_are_closed() -> None:
    source = (KIT / "Invoke-FailedMatrixClosureProbeV3.ps1").read_text(encoding="utf-8")
    match = re.search(r"ValidateSet\((.*?)\)\]\[string\]\$Mode", source, re.S)
    assert match
    assert set(re.findall(r"'([^']+)'", match.group(1))) == EXPECTED_V3_MODES
    assert "Invoke-ENV1B3ManagedProcess" in source
    assert "if($r.timed_out-or$r.exit_code-ne0)" in source
    assert "exit 0" in source and "exit 2" in source
    assert "ContractAudit" in source and "W12EvidenceAudit" in source

    tamper = (KIT / "Invoke-TamperMatrix.ps1").read_text(encoding="utf-8")
    assert "@(Compare-Object @($evidence.process_before) @($evidence.process_after)).Count" in tamper
    assert "TimeoutSeconds $WrapperTimeoutSeconds" in tamper
    assert "candidate_runtime_defect_proven=$false" in tamper
    assert "W09-STAGES.json" in tamper


def test_probe_v3r1_exposes_five_independent_w08_targets() -> None:
    source = (KIT / "Invoke-FailedMatrixClosureProbeV3R1.ps1").read_text(encoding="utf-8")
    match = re.search(r"ValidateSet\((.*?)\)\]\[string\]\$Mode", source, re.S)
    assert match
    assert set(re.findall(r"'([^']+)'", match.group(1))) == EXPECTED_V3R1_MODES
    for mode in ("W08Pointer", "W08ReleaseManifest", "W08RuntimeManifest", "W08Payload", "W08PythonDll"):
        assert mode in source
    assert "Read-FinalResult" in source
    assert "ENV1B3_PUBLIC_MODE_TIMEOUT" in source
    assert "ENV1B3_PUBLIC_MODE_OUTPUT_INVALID" in source


def test_probe_v3r2_separates_guest_and_host_modes_and_deprecates_old_aggregate() -> None:
    source = (KIT / "Invoke-FailedMatrixClosureProbeV3R2.ps1").read_text(encoding="utf-8")
    match = re.search(r"ValidateSet\((.*?)\)\]\[string\]\$Mode", source, re.S)
    assert match
    assert set(re.findall(r"'([^']+)'", match.group(1))) == (
        EXPECTED_V3R2_GUEST_MODES | EXPECTED_V3R2_HOST_MODES | {"W08Aggregate"}
    )
    assert "ENV1B3_DEPRECATED_W08_AGGREGATE_MODE" in source
    host_branch = source[source.index("if ($Mode -eq 'W08HostAggregate')"):source.index("if ($Mode -eq 'ContractAudit')")]
    assert "Invoke-W08HostAggregate.ps1" in host_branch
    assert "Invoke-Child" not in host_branch
    assert "Invoke-TamperMatrix.ps1" not in host_branch
    assert "Mode='All'" not in source and "Mode=All" not in source
    assert "ENV1B3_PUBLIC_MODE_EXIT_CONTRACT_INVALID" in source


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
def test_strictmode_empty_compare_and_durable_reboot_state_contract(tmp_path: Path) -> None:
    module = str(KIT / "ENV1B3.Validation.psm1").replace("'", "''")
    state = str(tmp_path / "state.json").replace("'", "''")
    command = (
        "Set-StrictMode -Version Latest;$ErrorActionPreference='Stop';"
        f"Import-Module '{module}' -Force;"
        "$empty=@(Compare-Object @() @()).Count;"
        f"$sha=Write-ENV1B3DurableJson -Path '{state}' -Document @{{schema='fixture';value=1}};"
        f"$doc=Read-ENV1B3DurableJson -Path '{state}' -ExpectedSha256 $sha;"
        "[ordered]@{empty=$empty;sha=$sha;value=$doc.value}|ConvertTo-Json -Compress"
    )
    result = _run_ps(command)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["empty"] == 0 and payload["value"] == 1
    assert re.fullmatch(r"[0-9a-f]{64}", payload["sha"])

    for content in (b"", b"\0" * 32, b'{"schema":"fixture"}\n'):
        target = tmp_path / "bad.json"
        target.write_bytes(content)
        bad_sha = hashlib.sha256(content).hexdigest()
        failed = _run_ps(
            f"Import-Module '{module}' -Force;Read-ENV1B3DurableJson -Path "
            f"'{str(target).replace(chr(39), chr(39)*2)}' -ExpectedSha256 '{'0'*64 if content.startswith(b'{') else bad_sha}'"
        )
        assert failed.returncode != 0
        assert "ENV1B3_REBOOT_STATE_DURABILITY_FAILED" in failed.stderr


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
def test_defender_exclusion_normalizer_ignores_null_and_is_case_insensitive() -> None:
    module = str(KIT / "ENV1B3.Validation.psm1").replace("'", "''")
    command = (
        f"Import-Module '{module}' -Force;"
        "$a=Get-ENV1B3NonEmptyStringSet @($null,$null,$null,' ','C:\\SAFE');"
        "$b=Get-ENV1B3NonEmptyStringSet @('c:\\safe',$null);"
        "$d=@(Compare-Object -ReferenceObject @($a) -DifferenceObject @($b) -CaseSensitive:$false);"
        "[ordered]@{a=@($a).Count;b=@($b).Count;difference=$d.Count}|ConvertTo-Json -Compress"
    )
    result = _run_ps(command)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == {"a": 1, "b": 1, "difference": 0}


def test_ps51_sources_are_ascii_and_w12_w13_fields_are_formal() -> None:
    for path in KIT.glob("*.ps*"):
        assert all(byte < 128 for byte in path.read_bytes()), path.name
    resource = (KIT / "Invoke-ResourceInterferenceMatrix.ps1").read_text(encoding="ascii")
    assert "retry_after_cleanup_passed=$retryPassed" in resource
    assert "Get-ENV1B3NonEmptyStringSet" in resource
    assert "actual_exclusion_count=" in resource
    assert "scan_completed=$true" in resource


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
def test_w08_dirty_runtime_baseline_is_blocked_without_cleanup(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    lock = runtime / "runtime-supervisor.lock"
    lock.write_text('{"foreign":true}\n', encoding="utf-8")
    evidence = tmp_path / "evidence"
    completed = subprocess.run(
        [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(KIT / "Invoke-TamperMatrix.ps1"), "-SourceInstallRoot", str(source),
         "-CaseRoot", str(tmp_path / "cases"), "-EvidenceRoot", str(evidence), "-Mode", "Pointer",
         "-ContractPath", str(KIT / "matrix-contracts.json"), "-RuntimeRootForTest", str(runtime)],
        text=True, encoding="utf-8", capture_output=True, timeout=120, check=False,
    )
    assert completed.returncode == 2, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["result"] == "BLOCKED"
    assert payload["code"] == "ENV1B3_W08_RUNTIME_BASELINE_DIRTY"
    assert lock.exists()
    assert not (tmp_path / "cases" / "w08-pointer").exists()


def _audit_fixture(root: Path) -> tuple[Path, Path]:
    contract = json.loads((KIT / "matrix-contracts.json").read_text(encoding="utf-8"))
    manifest = root / "PROBE-MANIFEST.json"
    manifest.write_text(json.dumps({
        "matrix_contract_sha256": _sha256(KIT / "matrix-contracts.json"),
        "expected_candidate_id": "candidate-fixture",
        "expected_candidate_handoff_sha256": "3" * 64,
        "expected_probe_v2_evidence_sha256": "1" * 64,
        "expected_w12_evidence_sha256": "2" * 64,
    }) + "\n", encoding="utf-8")
    matrix_root = root / "matrix"
    for case in (item for item in contract["cases"] if item["case_id"] in {"W05", "W08", "W09", "W10", "W11", "W13"}):
        case_root = matrix_root / case["case_id"]
        sub_root = case_root / "subchecks" / case["case_id"]
        sub_root.mkdir(parents=True)
        fields = {
            **{field: True for field in case["required_evidence_fields"]},
            **{f"execution_context_{field}": True for field in case["required_execution_context"]},
            **{f"fixture_{field}": True for field in case["required_fixtures"]},
        }
        listed = []
        for index, subcheck in enumerate(case["mandatory_subchecks"]):
            record = {
                "schema_version": "env-1b3-subcheck-result-v1",
                "overall_task_id": "ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE",
                "matrix_version": "env-1b3-windows-validation-matrix-v1",
                "case_id": case["case_id"], "subcheck_id": subcheck, "result": "PASS",
                "code": "FIXTURE_PASS", "evidence": fields if index == 0 else {},
            }
            (sub_root / f"{subcheck}.json").write_text(json.dumps(record) + "\n", encoding="utf-8")
            listed.append({"subcheck_id": subcheck, "result": "PASS", "code": "FIXTURE_PASS"})
        aggregate = {
            "schema_version": "env-1b3-case-result-v1",
            "overall_task_id": "ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE",
            "matrix_version": "env-1b3-windows-validation-matrix-v1",
            "case_id": case["case_id"], "result": "PASS", "code": "FIXTURE_PASS",
            "evidence": {"subchecks": listed},
        }
        if case["case_id"] == "W08":
            source_hashes = {subcheck: _sha256(sub_root / f"{subcheck}.json") for subcheck in case["mandatory_subchecks"]}
            aggregate["evidence"].update({
                "aggregation_source": "host_only_evidence_aggregator",
                "source_evidence_sha256s": source_hashes,
                "w08_evidence_set_sha256": _canonical_hashes_sha256(source_hashes),
            })
        (case_root / f"{case['case_id']}.json").write_text(json.dumps(aggregate) + "\n", encoding="utf-8")
    w12 = matrix_root / "W12"
    w12.mkdir()
    (w12 / "W12-EVIDENCE-AUDIT.json").write_text(json.dumps({
        "schema_version": "env-1b3-w12-evidence-audit-v3",
        "overall_task_id": "ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE",
        "matrix_version": "env-1b3-windows-validation-matrix-v1", "case_id": "W12",
        "result": "PASS", "code": "FIXTURE_PASS", "candidate_id": "candidate-fixture",
        "source_probe_v2_zip_sha256": "1" * 64, "candidate_handoff_sha256": "3" * 64,
        "candidate_modified": False, "w12_aggregate_sha256": "2" * 64,
        "w12_subcheck_sha256s": {
            "archive_preflight_low_space": "4" * 64, "materialization_low_space": "5" * 64,
            "writable_root_low_space": "6" * 64, "pointer_atomicity": "7" * 64,
        },
        "recovery_evidence_sha256": "8" * 64, "w12_evidence_set_sha256": "9" * 64,
        "retry_after_cleanup_passed": True,
    }) + "\n", encoding="utf-8")
    return manifest, matrix_root


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
@pytest.mark.parametrize("defect", [
    "false_context", "false_fixture", "bad_schema", "bad_case", "bad_subcheck",
    "bad_result", "bad_aggregate", "w08_source_hash_mismatch", "w12_sha_mismatch",
    "w12_candidate_modified", "w12_evidence_set_missing",
])
def test_contract_audit_rejects_false_values_and_identity_mismatch(tmp_path: Path, defect: str) -> None:
    manifest, matrix_root = _audit_fixture(tmp_path)
    record_path = matrix_root / "W05" / "subchecks" / "W05" / "long_path_materialization.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if defect == "false_context":
        record["evidence"]["execution_context_long_path_enabled"] = False
    elif defect == "false_fixture":
        record["evidence"]["fixture_candidate_handoff"] = False
    elif defect == "bad_schema":
        record["schema_version"] = "wrong"
    elif defect == "bad_case":
        record["case_id"] = "W06"
    elif defect == "bad_subcheck":
        record["subcheck_id"] = "other"
    elif defect == "bad_result":
        record["result"] = "UNKNOWN"
    if defect in {"false_context", "false_fixture", "bad_schema", "bad_case", "bad_subcheck", "bad_result"}:
        record_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    elif defect == "bad_aggregate":
        aggregate_path = matrix_root / "W05" / "W05.json"
        aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
        aggregate["result"] = "BLOCKED"
        aggregate_path.write_text(json.dumps(aggregate) + "\n", encoding="utf-8")
    elif defect == "w08_source_hash_mismatch":
        record_path = matrix_root / "W08" / "subchecks" / "W08" / "payload.json"
        value = json.loads(record_path.read_text(encoding="utf-8"))
        value["code"] = "CHANGED_AFTER_AGGREGATION"
        record_path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    else:
        supplemental = matrix_root / "W12" / "W12-EVIDENCE-AUDIT.json"
        value = json.loads(supplemental.read_text(encoding="utf-8"))
        if defect == "w12_sha_mismatch":
            value["w12_aggregate_sha256"] = "a" * 64
        elif defect == "w12_candidate_modified":
            value["candidate_modified"] = True
        else:
            value["w12_evidence_set_sha256"] = ""
        supplemental.write_text(json.dumps(value) + "\n", encoding="utf-8")
    completed = subprocess.run(
        [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(KIT / "Invoke-MatrixContractAudit.ps1"), "-ProbeManifestPath", str(manifest),
         "-ContractPath", str(KIT / "matrix-contracts.json"), "-MatrixEvidenceRoot", str(matrix_root),
         "-EvidenceRoot", str(tmp_path / "audit")],
        text=True, encoding="utf-8", capture_output=True, timeout=120, check=False,
    )
    assert completed.returncode == 2, completed.stdout + completed.stderr
    assert json.loads(completed.stdout.strip().splitlines()[-1])["result"] == "FAIL"


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
def test_w13_preexisting_exclusion_is_unchanged_but_not_absent() -> None:
    module = str(KIT / "ENV1B3.Validation.psm1").replace("'", "''")
    result = _run_ps(
        f"Import-Module '{module}' -Force;"
        "$before=Get-ENV1B3NonEmptyStringSet @($null,' C:\\Existing ');"
        "$after=Get-ENV1B3NonEmptyStringSet @('c:\\existing',$null,' ');"
        "$same=@(Compare-Object @($before) @($after) -CaseSensitive:$false).Count-eq0;"
        "[ordered]@{absent=(@($after).Count-eq0);unchanged=$same;count=@($after).Count}|ConvertTo-Json -Compress"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == {"absent": False, "unchanged": True, "count": 1}


W08_TARGETS = {
    "current_release": "W08PointerEvidenceRoot",
    "release_manifest": "W08ReleaseManifestEvidenceRoot",
    "runtime_manifest": "W08RuntimeManifestEvidenceRoot",
    "payload": "W08PayloadEvidenceRoot",
    "python314_dll": "W08PythonDllEvidenceRoot",
}


def _make_w08_target(root: Path, subcheck: str) -> Path:
    target = root / subcheck
    output = target / "subchecks" / "W08"
    output.mkdir(parents=True)
    record = {
        "schema_version": "env-1b3-subcheck-result-v1",
        "overall_task_id": "ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE",
        "matrix_version": "env-1b3-windows-validation-matrix-v1",
        "case_id": "W08", "subcheck_id": subcheck, "result": "PASS", "code": "FIXTURE_PASS",
        "evidence": {
            "start_failed_closed": True, "restart_failed_closed": True, "health_failed_closed": True,
            "status_diagnostic": True, "owned_stop_succeeded": True, "foreign_process_survived": True,
            "execution_context_isolated_case_copies": True, "fixture_materialized_release": True,
        },
    }
    (output / f"{subcheck}.json").write_text(json.dumps(record) + "\n", encoding="utf-8")
    return target


def _run_w08_aggregate(roots: dict[str, Path], output: Path) -> subprocess.CompletedProcess[str]:
    command = [
        POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", str(KIT / "Invoke-W08HostAggregate.ps1"),
    ]
    for subcheck, parameter in W08_TARGETS.items():
        command.extend([f"-{parameter}", str(roots[subcheck])])
    command.extend(["-ContractPath", str(KIT / "matrix-contracts.json"), "-EvidenceRoot", str(output)])
    return subprocess.run(command, text=True, encoding="utf-8", capture_output=True, timeout=120, check=False)


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
def test_w08_host_aggregate_reads_five_immutable_targets_without_tamper_or_process(tmp_path: Path) -> None:
    roots = {subcheck: _make_w08_target(tmp_path / "inputs", subcheck) for subcheck in W08_TARGETS}
    completed = _run_w08_aggregate(roots, tmp_path / "aggregate")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["result"] == "PASS"
    assert result["evidence"]["aggregation_source"] == "host_only_evidence_aggregator"
    assert set(result["evidence"]["source_evidence_sha256s"]) == set(W08_TARGETS)
    assert result["evidence"]["w08_evidence_set_sha256"] == _canonical_hashes_sha256(
        result["evidence"]["source_evidence_sha256s"]
    )
    source = (KIT / "Invoke-W08HostAggregate.ps1").read_text(encoding="utf-8")
    assert "Invoke-TamperMatrix" not in source
    assert "Invoke-ENV1B3ManagedProcess" not in source
    assert "Diagnostics.Process" not in source


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
@pytest.mark.parametrize("defect", ["missing", "duplicate", "unexpected", "identity", "not_pass"])
def test_w08_host_aggregate_rejects_invalid_target_sets(tmp_path: Path, defect: str) -> None:
    roots = {subcheck: _make_w08_target(tmp_path / "inputs", subcheck) for subcheck in W08_TARGETS}
    target = roots["payload"] / "subchecks" / "W08" / "payload.json"
    if defect == "missing":
        target.unlink()
    elif defect == "duplicate":
        roots["payload"] = roots["current_release"]
    elif defect == "unexpected":
        (target.parent / "unexpected.json").write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        record = json.loads(target.read_text(encoding="utf-8"))
        if defect == "identity":
            record["subcheck_id"] = "current_release"
        else:
            record["result"] = "FAIL"
        target.write_text(json.dumps(record) + "\n", encoding="utf-8")
    completed = _run_w08_aggregate(roots, tmp_path / "aggregate")
    assert completed.returncode == 2
    assert json.loads(completed.stdout.strip().splitlines()[-1])["result"] == "FAIL"


def _probe_v2_documents(candidate_id: str, handoff_sha: str, *, mutation: str | None = None) -> dict[str, bytes]:
    task = "ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE"
    matrix = "env-1b3-windows-validation-matrix-v1"
    ids = ["archive_preflight_low_space", "materialization_low_space", "writable_root_low_space", "pointer_atomicity"]
    identity = {
        "schema_version": "env-1b3-probe-v2-candidate-binding-v1",
        "candidate_id": candidate_id, "zip_sha256": handoff_sha, "modified": False,
    }
    if mutation == "candidate_identity":
        identity["candidate_id"] = "other-candidate"
    elif mutation == "candidate_handoff":
        identity["zip_sha256"] = "f" * 64
    elif mutation == "candidate_modified":
        identity["modified"] = True
    documents: dict[str, object] = {"CANDIDATE-05-IDENTITY.json": identity}
    listed = [{"subcheck_id": value, "result": "PASS", "code": "FIXTURE_PASS"} for value in ids]
    documents["cases/W12/W12.json"] = {
        "schema_version": "env-1b3-case-result-v1", "overall_task_id": task, "matrix_version": matrix,
        "case_id": "W12", "result": "PASS", "code": "FIXTURE_PASS", "evidence": {"subchecks": listed},
    }
    for subcheck in ids:
        evidence: dict[str, object] = {}
        if subcheck == "materialization_low_space":
            evidence = {"no_final_app_root": True, "pointer_unchanged": True, "pointer_temp_absent": True}
        elif subcheck == "pointer_atomicity":
            evidence = {"pointer_unchanged": True, "pointer_temp_absent": True}
        documents[f"cases/W12/subchecks/W12/{subcheck}.json"] = {
            "schema_version": "env-1b3-subcheck-result-v1", "overall_task_id": task, "matrix_version": matrix,
            "case_id": "W12", "subcheck_id": subcheck, "result": "PASS", "code": "FIXTURE_PASS",
            "evidence": evidence,
        }
    documents["cases/W12/w12-recovery-materialization/W02.json"] = {
        "schema_version": "env-1b3-case-result-v1", "overall_task_id": task, "matrix_version": matrix,
        "case_id": "W02", "result": "PASS", "code": "FIXTURE_PASS",
        "evidence": {"candidate_id": candidate_id},
    }
    for index in range(50):
        documents[f"filler/{index:02d}.json"] = {"fixture": index}
    return {
        path: (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        for path, value in documents.items()
    }


def _build_probe_v2_zip(
    root: Path, *, mutation: str | None = None, candidate_id: str = "candidate-fixture",
    handoff_sha: str = "a" * 64,
) -> tuple[Path, Path, dict[str, bytes]]:
    documents = _probe_v2_documents(candidate_id, handoff_sha, mutation=mutation)
    sums = {path: hashlib.sha256(value).hexdigest() for path, value in documents.items()}
    if mutation == "internal_sums":
        sums["filler/00.json"] = "0" * 64
    elif mutation == "subcheck_hash":
        sums["cases/W12/subchecks/W12/materialization_low_space.json"] = "0" * 64
    elif mutation == "recovery_hash":
        sums["cases/W12/w12-recovery-materialization/W02.json"] = "0" * 64
    sums_text = "".join(f"{value} *{path.replace('/', chr(92))}\n" for path, value in sorted(sums.items()))
    archive = root / f"probe-v2-{mutation or 'valid'}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as output:
        for path, value in documents.items():
            output.writestr(path.replace("/", "\\"), value)
        output.writestr("SHA256SUMS", sums_text.encode("utf-8"))
        if mutation == "unbound":
            output.writestr("unbound.json", b"{}\n")
        elif mutation == "unsafe":
            output.writestr("../escape.json", b"{}\n")
        elif mutation == "casefold":
            output.writestr("FILLER\\00.JSON", b"{}\n")
    manifest = root / f"manifest-{mutation or 'valid'}.json"
    manifest.write_text(json.dumps({
        "expected_candidate_id": candidate_id,
        "expected_candidate_handoff_sha256": handoff_sha,
        "expected_probe_v2_evidence_sha256": "f" * 64 if mutation == "outer_sha" else _sha256(archive),
        "expected_w12_evidence_sha256": hashlib.sha256(documents["cases/W12/W12.json"]).hexdigest(),
    }) + "\n", encoding="utf-8")
    return archive, manifest, documents


def _run_w12_audit(
    archive: Path, manifest: Path, output: Path, mirror: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", str(KIT / "Invoke-W12EvidenceAudit.ps1"), "-ProbeManifestPath", str(manifest),
        "-ProbeV2EvidenceZip", str(archive), "-EvidenceRoot", str(output),
    ]
    if mirror is not None:
        command.extend(["-W12EvidenceRoot", str(mirror)])
    return subprocess.run(command, text=True, encoding="utf-8", capture_output=True, timeout=120, check=False)


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
def test_w12_audit_reads_and_closes_probe_v2_zip_directly(tmp_path: Path) -> None:
    archive, manifest, _ = _build_probe_v2_zip(tmp_path)
    passed = _run_w12_audit(archive, manifest, tmp_path / "audit")
    assert passed.returncode == 0, passed.stdout + passed.stderr
    result = json.loads(passed.stdout.strip().splitlines()[-1])
    assert result["schema_version"] == "env-1b3-w12-evidence-audit-v3"
    assert result["retry_after_cleanup_passed"] is True
    assert result["source_probe_v2_zip_sha256"] == _sha256(archive)
    assert result["candidate_handoff_sha256"] == "a" * 64
    assert result["candidate_modified"] is False
    assert len(result["w12_subcheck_sha256s"]) == 4
    assert re.fullmatch(r"[0-9a-f]{64}", result["w12_evidence_set_sha256"])
    assert result["internal_sha256s_verified"] == 57


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
@pytest.mark.parametrize("mutation", [
    "outer_sha", "internal_sums", "unbound", "unsafe", "casefold", "candidate_identity",
    "candidate_handoff", "candidate_modified", "subcheck_hash", "recovery_hash",
])
def test_w12_zip_audit_rejects_tamper_and_identity_drift(tmp_path: Path, mutation: str) -> None:
    archive, manifest, _ = _build_probe_v2_zip(tmp_path, mutation=mutation)
    completed = _run_w12_audit(archive, manifest, tmp_path / "audit")
    assert completed.returncode == 2
    assert json.loads(completed.stdout.strip().splitlines()[-1])["result"] == "FAIL"


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
def test_w12_optional_mirror_must_match_zip_bytes(tmp_path: Path) -> None:
    archive, manifest, documents = _build_probe_v2_zip(tmp_path)
    mirror = tmp_path / "mirror"
    for path, value in documents.items():
        if path.startswith("cases/W12/"):
            target = mirror / path.removeprefix("cases/W12/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value)
    (mirror / "subchecks" / "W12" / "pointer_atomicity.json").write_text("{}\n", encoding="utf-8")
    completed = _run_w12_audit(archive, manifest, tmp_path / "audit", mirror)
    assert completed.returncode == 2
    assert "ENV1B3_W12_EVIDENCE_BINDING_INVALID" in completed.stdout


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
def test_subcheck_aggregation_requires_all_and_prevents_overwrite(tmp_path: Path) -> None:
    module = str(KIT / "ENV1B3.Validation.psm1").replace("'", "''")
    contract = str(KIT / "matrix-contracts.json").replace("'", "''")
    evidence = str(tmp_path / "evidence").replace("'", "''")
    command = (
        "Set-StrictMode -Version Latest;$ErrorActionPreference='Stop';"
        f"Import-Module '{module}' -Force;"
        "$ids=@('owned_stop_after_tamper','foreign_stop_rejected','foreign_process_survived','owned_cleanup_succeeded');"
        f"foreach($id in $ids){{Write-ENV1B3SubcheckResult -EvidenceRoot '{evidence}' -CaseId W09 -SubcheckId $id -Result PASS -Code FIXTURE_PASS|Out-Null}};"
        f"$r=Complete-ENV1B3CaseResult -EvidenceRoot '{evidence}' -CaseId W09 -ContractPath '{contract}';"
        "$blocked=$false;try{Write-ENV1B3SubcheckResult -EvidenceRoot '"
        + evidence
        + "' -CaseId W09 -SubcheckId foreign_stop_rejected -Result PASS -Code FIXTURE_PASS|Out-Null}catch{$blocked=$_.Exception.Message -match 'ENV1B3_EVIDENCE_OVERWRITE_FORBIDDEN'};"
        "[ordered]@{result=$r.result;count=$r.evidence.mandatory_subcheck_count;overwrite_blocked=$blocked}|ConvertTo-Json -Compress"
    )
    completed = _run_ps(command)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result == {"result": "PASS", "count": 4, "overwrite_blocked": True}


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
def test_matrix_contract_loader_rejects_missing_case(tmp_path: Path) -> None:
    document = json.loads((KIT / "matrix-contracts.json").read_text(encoding="utf-8"))
    document["cases"].pop()
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(document, separators=(",", ":")) + "\n", encoding="utf-8")
    module = str(KIT / "ENV1B3.Validation.psm1").replace("'", "''")
    command = f"Import-Module '{module}' -Force;Read-ENV1B3MatrixContracts '{str(invalid).replace(chr(39), chr(39)*2)}'"
    result = _run_ps(command)
    assert result.returncode != 0
    assert "ENV1B3_MATRIX_CONTRACT_INVALID" in result.stderr


def test_w08_w09_w11_w12_w13_w14_scripts_include_complete_contract_branches() -> None:
    tamper = (KIT / "Invoke-TamperMatrix.ps1").read_text(encoding="utf-8")
    for command in ("'start'", "'restart'", "'health'", "'status'", "'stop'"):
        assert command in tamper
    for subcheck in (
        "current_release", "release_manifest", "runtime_manifest", "payload", "python314_dll",
        "owned_stop_after_tamper", "foreign_stop_rejected", "foreign_process_survived", "owned_cleanup_succeeded",
    ):
        assert subcheck in tamper

    reboot = (KIT / "Invoke-RebootResume.ps1").read_text(encoding="utf-8")
    for phase in ("StoppedPrepare", "StoppedResume", "RunningPrepare", "RunningResume"):
        assert phase in reboot
    for field in ("app_root_identity", "pointer_sha256", "ownership_summary", "foreign_process_survived"):
        assert field in reboot

    resource = (KIT / "Invoke-ResourceInterferenceMatrix.ps1").read_text(encoding="utf-8")
    for subcheck in (
        "archive_preflight_low_space", "materialization_low_space", "writable_root_low_space", "pointer_atomicity",
        "archive_lock_failure", "recovery_after_lock_release", "defender_enabled", "controlled_scan_result", "permanent_exclusions_absent",
    ):
        assert subcheck in resource
    assert "Start-MpScan" in resource
    assert "ENV1B3_SYSTEM_VOLUME_FORBIDDEN" in resource

    final_identity = (KIT / "Invoke-FinalIdentityMatrix.ps1").read_text(encoding="utf-8")
    assert "lifecycle_executed=$false" in final_identity
    assert "readonly_app_root" in final_identity
    assert "offline_non_admin_lifecycle" in final_identity
    assert "RequireOffline" in final_identity


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
def test_all_validation_powershell_parses_under_windows_powershell_51() -> None:
    script = (
        "$errors=@();Get-ChildItem -LiteralPath '"
        + str(KIT).replace("'", "''")
        + "' -File|Where-Object{$_.Extension -in '.ps1','.psm1'}|ForEach-Object{"
        "$t=$null;$e=$null;[void][Management.Automation.Language.Parser]::ParseFile($_.FullName,[ref]$t,[ref]$e);$errors+=@($e)};"
        "[ordered]@{count=$errors.Count;messages=@($errors|ForEach-Object{$_.Message})}|ConvertTo-Json -Depth 5 -Compress;"
        "if($errors.Count){exit 2}"
    )
    result = _run_ps(script)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1])["count"] == 0


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
def test_probe_v2_bundle_is_closed_and_binds_contract(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    kit = repository / "tools" / "validation" / "windows" / "env_1b3"
    shutil.copytree(KIT, kit)
    subprocess.run(["git", "init", "-q", repository], check=True)
    subprocess.run(["git", "-C", repository, "config", "user.name", "fixture"], check=True)
    subprocess.run(["git", "-C", repository, "config", "user.email", "fixture@example.invalid"], check=True)
    subprocess.run(["git", "-C", repository, "add", "tools"], check=True)
    subprocess.run(["git", "-C", repository, "commit", "-q", "-m", "fixture"], check=True)
    head = subprocess.check_output(["git", "-C", repository, "rev-parse", "HEAD"], text=True).strip()
    output = tmp_path / "output"
    completed = subprocess.run(
        [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(kit / "New-RemainingMatrixProbeV2.ps1"),
         "-Repository", str(repository), "-OutputRoot", str(output), "-ExpectedCandidateId", "ice-2026.07.6-52bcc5f711ab-candidate-05",
         "-ExpectedCandidateHandoffSha256", "a2f9e7ccb9cb78960ca69eb984c8d669288146e80a438427efc2e4952daec3b6"],
        text=True, encoding="utf-8", capture_output=True, timeout=120, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    archive_path = output / f"ENV-1B3-REMAINING-MATRIX-PROBE-V2-{head}.zip"
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        assert len(names) == len(set(name.casefold() for name in names))
        assert all("\\" not in name and not name.startswith("/") for name in names)
        archive.extractall(tmp_path / "extracted")
    extracted = tmp_path / "extracted"
    manifest = json.loads((extracted / "PROBE-MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "env-1b3-remaining-matrix-probe-v2"
    assert set(manifest["executable_cases"]) == EXPECTED_MODES
    assert manifest["diagnostic_only"] is True
    assert manifest["not_a_release_candidate"] is True
    assert manifest["cannot_support_final_acceptance"] is True
    assert manifest["production_approved"] is False
    contract = extracted / manifest["matrix_contract_filename"]
    assert _sha256(contract) == manifest["matrix_contract_sha256"]
    sums = dict(line.split("  ", 1)[::-1] for line in (extracted / "SHA256SUMS").read_text(encoding="utf-8").splitlines())
    actual = {path.relative_to(extracted).as_posix(): _sha256(path) for path in extracted.rglob("*") if path.is_file() and path.name != "SHA256SUMS"}
    assert sums == actual


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
def test_probe_v3r2_bundle_public_modes_and_blocked_passthrough(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    kit = repository / "tools" / "validation" / "windows" / "env_1b3"
    shutil.copytree(KIT, kit)
    subprocess.run(["git", "init", "-q", repository], check=True)
    subprocess.run(["git", "-C", repository, "config", "user.name", "fixture"], check=True)
    subprocess.run(["git", "-C", repository, "config", "user.email", "fixture@example.invalid"], check=True)
    subprocess.run(["git", "-C", repository, "add", "tools"], check=True)
    subprocess.run(["git", "-C", repository, "commit", "-q", "-m", "fixture"], check=True)
    head = subprocess.check_output(["git", "-C", repository, "rev-parse", "HEAD"], text=True).strip()
    candidate = tmp_path / "candidate.zip"
    candidate.write_bytes(b"immutable-candidate-fixture")
    candidate_sha = _sha256(candidate)
    candidate_id = "ice-2026.07.6-52bcc5f711ab-candidate-05"
    probe_v2_sha = "1" * 64
    w12_sha = "2" * 64
    output = tmp_path / "output"
    built = subprocess.run(
        [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(kit / "New-FailedMatrixClosureProbeV3R2.ps1"),
         "-Repository", str(repository), "-OutputRoot", str(output),
         "-ExpectedCandidateId", candidate_id, "-ExpectedCandidateHandoffSha256", candidate_sha,
         "-ExpectedProbeV2EvidenceSha256", probe_v2_sha, "-ExpectedW12EvidenceSha256", w12_sha],
        text=True, encoding="utf-8", capture_output=True, timeout=120, check=False,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    archive_path = output / f"ENV-1B3-FAILED-MATRIX-CLOSURE-PROBE-V3R2-{head}.zip"
    extracted = tmp_path / "probe"
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(extracted)
    manifest = json.loads((extracted / "PROBE-MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "env-1b3-failed-matrix-closure-probe-v3r2"
    assert set(manifest["guest_executable_cases"]) == EXPECTED_V3R2_GUEST_MODES
    assert set(manifest["host_only_cases"]) == EXPECTED_V3R2_HOST_MODES

    handoff = tmp_path / "handoff"
    handoff.mkdir()
    (handoff / "CANDIDATE-HANDOFF.json").write_text(
        json.dumps({"candidate_id": candidate_id, "release_id": "ice-fixture"}) + "\n",
        encoding="utf-8",
    )
    matrix_root = tmp_path / "matrix"
    contracts = json.loads((extracted / "validation-kit" / "matrix-contracts.json").read_text(encoding="utf-8"))
    wanted = {"W05", "W08", "W09", "W10", "W11", "W13"}
    for case in (item for item in contracts["cases"] if item["case_id"] in wanted):
        case_root = matrix_root / case["case_id"]
        sub_root = case_root / "subchecks" / case["case_id"]
        sub_root.mkdir(parents=True)
        fields = {
            **{field: True for field in case["required_evidence_fields"]},
            **{f"execution_context_{field}": True for field in case["required_execution_context"]},
            **{f"fixture_{field}": True for field in case["required_fixtures"]},
        }
        records = []
        for index, subcheck in enumerate(case["mandatory_subchecks"]):
            evidence = fields if index == 0 else {}
            record = {
                "schema_version": "env-1b3-subcheck-result-v1",
                "overall_task_id": "ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE",
                "matrix_version": "env-1b3-windows-validation-matrix-v1", "case_id": case["case_id"],
                "subcheck_id": subcheck, "result": "PASS", "code": "FIXTURE_PASS", "evidence": evidence,
            }
            (sub_root / f"{subcheck}.json").write_text(json.dumps(record) + "\n", encoding="utf-8")
            records.append({"subcheck_id": subcheck, "result": "PASS", "code": "FIXTURE_PASS"})
        aggregate = {"schema_version": "env-1b3-case-result-v1",
                     "overall_task_id": "ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE",
                     "matrix_version": "env-1b3-windows-validation-matrix-v1", "case_id": case["case_id"],
                     "result": "PASS", "code": "FIXTURE_PASS", "evidence": {"subchecks": records}}
        if case["case_id"] == "W08":
            source_hashes = {subcheck: _sha256(sub_root / f"{subcheck}.json") for subcheck in case["mandatory_subchecks"]}
            aggregate["evidence"].update({
                "aggregation_source": "host_only_evidence_aggregator",
                "source_evidence_sha256s": source_hashes,
                "w08_evidence_set_sha256": _canonical_hashes_sha256(source_hashes),
            })
        (case_root / f"{case['case_id']}.json").write_text(json.dumps(aggregate) + "\n", encoding="utf-8")
    w12_root = matrix_root / "W12"
    w12_root.mkdir()
    (w12_root / "W12-EVIDENCE-AUDIT.json").write_text(json.dumps({
        "schema_version": "env-1b3-w12-evidence-audit-v3",
        "overall_task_id": "ENV-1B3-CLEAN-WINDOWS-VALIDATION-AND-RELEASE-CANDIDATE",
        "matrix_version": "env-1b3-windows-validation-matrix-v1", "case_id": "W12",
        "result": "PASS", "code": "ENV1B3_W12_EVIDENCE_AUDIT_PASS", "candidate_id": candidate_id,
        "source_probe_v2_zip_sha256": probe_v2_sha, "candidate_handoff_sha256": candidate_sha,
        "candidate_modified": False, "w12_aggregate_sha256": w12_sha,
        "w12_subcheck_sha256s": {
            "archive_preflight_low_space": "4" * 64, "materialization_low_space": "5" * 64,
            "writable_root_low_space": "6" * 64, "pointer_atomicity": "7" * 64,
        },
        "recovery_evidence_sha256": "8" * 64, "w12_evidence_set_sha256": "9" * 64,
        "retry_after_cleanup_passed": True,
    }) + "\n", encoding="utf-8")

    evidence = tmp_path / "audit"
    common = [
        POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", str(extracted / "Invoke-FailedMatrixClosureProbeV3R2.ps1"), "-Mode", "ContractAudit",
        "-EvidenceRoot", str(evidence), "-MatrixEvidenceRoot", str(matrix_root),
    ]
    passed = subprocess.run(common, text=True, encoding="utf-8", capture_output=True, timeout=120, check=False)
    assert passed.returncode == 0, passed.stdout + passed.stderr
    assert json.loads(passed.stdout.strip().splitlines()[-1])["result"] == "PASS"
    (matrix_root / "W08" / "subchecks" / "W08" / "payload.json").unlink()
    failed_command = common.copy()
    failed_command[failed_command.index("-EvidenceRoot") + 1] = str(tmp_path / "audit-fail")
    failed = subprocess.run(
        failed_command,
        text=True, encoding="utf-8", capture_output=True, timeout=120, check=False,
    )
    assert failed.returncode == 2
    assert json.loads(failed.stdout.strip().splitlines()[-1])["exit_code"] == 2

    blocked_evidence = tmp_path / "blocked"
    blocked = subprocess.run(
        [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(extracted / "Invoke-FailedMatrixClosureProbeV3R2.ps1"), "-Mode", "W05",
         "-CandidateHandoffZip", str(candidate), "-HandoffRoot", str(handoff), "-TestRoot", str(tmp_path / "test"),
         "-EvidenceRoot", str(blocked_evidence)],
        text=True, encoding="utf-8", capture_output=True, timeout=120, check=False,
    )
    assert blocked.returncode == 2
    blocked_result = json.loads(blocked.stdout.strip().splitlines()[-1])
    assert blocked_result["result"] == "BLOCKED"
    assert blocked_result["code"] == "ENV1B3_LONG_PATHS_DISABLED"

    deprecated = subprocess.run(
        [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(extracted / "Invoke-FailedMatrixClosureProbeV3R2.ps1"), "-Mode", "W08Aggregate",
         "-EvidenceRoot", str(tmp_path / "deprecated")],
        text=True, encoding="utf-8", capture_output=True, timeout=120, check=False,
    )
    assert deprecated.returncode == 2
    deprecated_result = json.loads(deprecated.stdout.strip().splitlines()[-1])
    assert deprecated_result["result"] == "BLOCKED"
    assert deprecated_result["code"] == "ENV1B3_DEPRECATED_W08_AGGREGATE_MODE"
