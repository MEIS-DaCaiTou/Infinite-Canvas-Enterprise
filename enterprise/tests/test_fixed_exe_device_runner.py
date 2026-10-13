"""Targeted offline-kit boundaries; these do not substitute for real gates."""
import hashlib
import json
from pathlib import Path

import pytest

from enterprise.tests import fixed_exe_device_runner as runner
from enterprise.tests import fixed_exe_handoff_qualification as qualification


def _kit(root):
    (root / "fixture.txt").write_bytes(b"synthetic")
    manifest = {"schema_version": runner.SCHEMA, "synthetic_only": True, "production_authorized": False,
                "source_commit": "a" * 40, "target_commit": "b" * 40,
                "files": [{"path": "fixture.txt", "size_bytes": 9,
                           "sha256": hashlib.sha256(b"synthetic").hexdigest()}]}
    _write(root, manifest)
    return manifest


def _write(root, manifest):
    (root / runner.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")


def test_verification_is_read_only_and_requires_complete_closure(tmp_path):
    manifest = _kit(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert runner.verify_kit(tmp_path) == manifest
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before
    (tmp_path / "extra.txt").write_bytes(b"unapproved")
    with pytest.raises(RuntimeError, match="CLOSURE_MISMATCH"):
        runner.verify_kit(tmp_path)


@pytest.mark.parametrize("change", ["bytes", "size", "duplicate", "escape", "unc", "production", "head"])
def test_modified_or_unqualified_kit_is_rejected(tmp_path, change):
    manifest = _kit(tmp_path)
    if change == "bytes":
        (tmp_path / "fixture.txt").write_bytes(b"different")
    elif change == "size":
        manifest["files"][0]["size_bytes"] = True
    elif change == "duplicate":
        manifest["files"].append(dict(manifest["files"][0], path="FIXTURE.TXT"))
    elif change == "escape":
        manifest["files"][0]["path"] = "../elsewhere"
    elif change == "unc":
        manifest["files"][0]["path"] = "//server/file"
    elif change == "production":
        manifest["production_authorized"] = True
    else:
        manifest["target_commit"] = "unknown"
    _write(tmp_path, manifest)
    with pytest.raises(RuntimeError, match="KIT_"):
        runner.verify_kit(tmp_path)


def _summary():
    return {"schema_version": "fixed-exe-update-windows-drill-v1", "historical_roots_restored": True,
            "production_touched": False, "paid_provider_called": False,
            "results": [{"scenario": name, "state": state, "fixed_exe": True,
                         "real_http_execute": True, "detached_worker_exited": True,
                         "source_processes_exited": True, "business_identity_config_and_media_retained": True,
                         "production_touched": False, "automatic_source_recovery": name == "rollback"}
                        for name, state in runner.EXPECTED.items()]}


def test_gate_summary_requires_real_coverage_and_restoration():
    summary = _summary()
    assert set(runner.gate_results(summary).values()) == {"PASS"}
    summary["historical_roots_restored"] = False
    assert set(runner.gate_results(summary).values()) == {"NOT_CONFIRMED"}


@pytest.mark.parametrize("change", ["state", "worker", "data", "http", "automatic", "duplicate"])
def test_label_alone_or_duplicate_results_never_pass_three_gates(change):
    summary = _summary()
    result = summary["results"][1]
    if change == "duplicate":
        summary["results"][2] = dict(result)
    else:
        key = {"state": "state", "worker": "detached_worker_exited", "data": "business_identity_config_and_media_retained",
               "http": "real_http_execute", "automatic": "automatic_source_recovery"}[change]
        result[key] = "FAILED" if change == "state" else False
    assert "NOT_CONFIRMED" in runner.gate_results(summary).values()


def test_failed_qualification_does_not_invoke_drill_or_touch_history(tmp_path, monkeypatch):
    root = tmp_path / "kit"
    root.mkdir()
    evidence = tmp_path / "new-evidence"
    manifest = _kit(root)
    monkeypatch.setattr(runner, "_check_run_paths", lambda *args: None)
    monkeypatch.setattr(runner, "_qualification", lambda *args: (False, {"qualified": False}))
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: pytest.fail("must not launch drill"))
    assert runner.run_kit(root, evidence, manifest, preserve=True) == 2
    report = json.loads((evidence / "share/RESULT.json").read_bytes())
    assert report["state"] == "PREFLIGHT_BLOCKED"
    assert set(report["gates"].values()) == {"NOT_RUN"}
    assert not (evidence / "drill").exists()
    assert not (evidence / "PRIVATE-drill-output.log").exists()
    with runner.zipfile.ZipFile(evidence / "pr148-synthetic-gates-report.zip") as archive:
        assert set(archive.namelist()) == {"share/RESULT.json", "share/QUALIFICATION.json"}


def test_invalid_run_context_never_creates_evidence(tmp_path, monkeypatch):
    root = tmp_path / "kit"
    root.mkdir()
    manifest = _kit(root)
    evidence = tmp_path / "absent"
    monkeypatch.setattr(runner, "_check_run_paths", lambda *a: (_ for _ in ()).throw(RuntimeError("blocked")))
    with pytest.raises(RuntimeError, match="blocked"):
        runner.run_kit(root, evidence, manifest)
    assert not evidence.exists()


def _qualified():
    return {"schema_version": qualification.SCHEMA, "child_exit_code": 0,
            "qualified": True, "production_touched": False,
            "handoff_context": {"schema_version": qualification.CHILD_SCHEMA,
                "qualified": True, "production_touched": False,
                "creation_context": {"job_query_ok": True, "process_in_job": True, "job_limit_flags": 0x1800},
                "source_pid": 11, "source_created_at": 22, "worker_pid": 33, "worker_created_at": 44,
                "worker_in_job": True,
                **{field: True for field in qualification.REQUIRED_EVIDENCE}}}


@pytest.mark.parametrize("missing", list(qualification.REQUIRED_EVIDENCE) + ["source_pid", "worker_created_at"])
def test_qualification_requires_every_bound_evidence_field(missing):
    result = _qualified()
    assert qualification.qualified_result(result)
    result["handoff_context"].pop(missing)
    assert not qualification.qualified_result(result)


@pytest.mark.parametrize("change", ["schema", "child-schema", "job-query", "child-exit", "pid-bool", "production"])
def test_qualification_rejects_stale_schema_unknown_job_and_invalid_identity(change):
    result = _qualified()
    if change == "schema":
        result["schema_version"] = "old"
    elif change == "child-schema":
        result["handoff_context"]["schema_version"] = "old"
    elif change == "job-query":
        result["handoff_context"]["creation_context"]["job_query_ok"] = False
    elif change == "child-exit":
        result["child_exit_code"] = True
    elif change == "pid-bool":
        result["handoff_context"]["source_pid"] = True
    else:
        result["production_touched"] = True
    assert not qualification.qualified_result(result)


def test_claimed_qualified_label_cannot_start_drill(tmp_path, monkeypatch):
    root = tmp_path / "kit"
    root.mkdir()
    manifest = _kit(root)
    evidence = tmp_path / "unverified-evidence"
    monkeypatch.setattr(runner, "_check_run_paths", lambda *args: None)
    monkeypatch.setattr(runner, "_qualification", lambda *args: (True, {"qualified": True}))
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: pytest.fail("must not launch drill"))
    assert runner.run_kit(root, evidence, manifest, preserve=True) == 2
    report = json.loads((evidence / "share/RESULT.json").read_bytes())
    assert report["state"] == "PREFLIGHT_BLOCKED"
    assert set(report["gates"].values()) == {"NOT_RUN"}
    assert not (evidence / "PRIVATE-drill-output.log").exists()


@pytest.mark.parametrize("payload,exit_code,expected", [(None, 0, True), ({"qualified": True}, 0, False), (None, 2, False)])
def test_runner_subprocess_result_requires_v2_evidence(tmp_path, monkeypatch, payload, exit_code, expected):
    from unittest.mock import Mock
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    payload = _qualified() if payload is None else payload
    def completed(*args, **kwargs):
        (evidence / "qualification.json").write_text(json.dumps(payload), encoding="utf-8")
        return Mock(returncode=exit_code)
    monkeypatch.setattr(runner.subprocess, "run", completed)
    accepted, saved = runner._qualification(tmp_path, evidence, {})
    assert accepted is expected
    assert saved == payload


@pytest.mark.skipif(qualification.os.name != "nt", reason="Windows creation flags")
def test_qualification_parent_uses_isolated_exact_script_not_cwd_import(tmp_path, monkeypatch):
    from unittest.mock import Mock
    payload = _qualified()["handoff_context"]
    launch = Mock(return_value=Mock(returncode=0, stdout=json.dumps(payload)))
    monkeypatch.setattr(qualification.subprocess, "run", launch)
    monkeypatch.setattr(qualification, "current_job_diagnostics", lambda: {})
    monkeypatch.setattr(qualification.sys, "argv", ["qualification", "--output", str(tmp_path / "result.json")])
    assert qualification.main() == 0
    command = launch.call_args.args[0]
    assert command[:3] == [qualification.sys.executable, "-I", "-B"]
    assert command[3] == str(Path(qualification.__file__).resolve())
    assert command[4:] == ["--supervisor-context"]
