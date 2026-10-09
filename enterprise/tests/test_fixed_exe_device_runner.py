"""Targeted offline-kit boundaries; these do not substitute for real gates."""
import hashlib
import json
from pathlib import Path

import pytest

from enterprise.tests import fixed_exe_device_runner as runner


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
