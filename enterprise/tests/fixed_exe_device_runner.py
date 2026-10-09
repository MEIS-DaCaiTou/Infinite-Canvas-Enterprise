"""Offline synthetic gate runner; not an installer or production updater.

The operator first verifies the delivered ZIP hash and launches this runner
from the test device's desktop. No existing application is stopped by this
tool. A failed independent-handoff qualification never enters the EXE drill.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import zipfile

from enterprise.path_safety import assert_no_reparse_ancestors

SCHEMA = "pr148-offline-synthetic-kit-v1"
EXPECTED = {"success": "SUCCEEDED", "rollback": "ROLLED_BACK", "recovery-required": "RECOVERY_REQUIRED"}
MANIFEST = "KIT-MANIFEST.json"


def _new_json(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True)
        stream.write("\n")


def _sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _relative(value):
    if (not isinstance(value, str) or not value or "\\" in value or ":" in value
            or any(part in ("", ".", "..") or part.endswith((".", " ")) for part in value.split("/"))
            or any(ord(char) < 32 for char in value)):
        raise RuntimeError("KIT_PATH_INVALID")
    return value


def verify_kit(root):
    root = Path(os.path.abspath(root))
    assert_no_reparse_ancestors(root)
    manifest_path = root / MANIFEST
    assert_no_reparse_ancestors(manifest_path)
    if not manifest_path.is_file() or manifest_path.stat().st_size > 2 * 1024 * 1024:
        raise RuntimeError("KIT_MANIFEST_INVALID")
    manifest = json.loads(manifest_path.read_bytes())
    if (type(manifest) is not dict or manifest.get("schema_version") != SCHEMA
            or manifest.get("synthetic_only") is not True or manifest.get("production_authorized") is not False
            or not re.fullmatch(r"[0-9a-f]{40}", str(manifest.get("target_commit", "")))
            or not re.fullmatch(r"[0-9a-f]{40}", str(manifest.get("source_commit", "")))):
        raise RuntimeError("KIT_IDENTITY_INVALID")
    entries = manifest.get("files")
    if type(entries) is not list or not 1 <= len(entries) <= 10000:
        raise RuntimeError("KIT_INVENTORY_INVALID")
    expected = {}
    size = 0
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "sha256", "size_bytes"}:
            raise RuntimeError("KIT_INVENTORY_INVALID")
        relative = _relative(entry["path"])
        key = relative.casefold()
        if key in expected or key == MANIFEST.casefold():
            raise RuntimeError("KIT_INVENTORY_INVALID")
        if (type(entry["size_bytes"]) is not int or entry["size_bytes"] < 0
                or not re.fullmatch(r"[0-9a-f]{64}", str(entry["sha256"]))):
            raise RuntimeError("KIT_INVENTORY_INVALID")
        expected[key] = relative
        size += entry["size_bytes"]
        if size > 512 * 1024 * 1024:
            raise RuntimeError("KIT_SIZE_LIMIT")
        path = root / relative
        assert_no_reparse_ancestors(path)
        if not path.is_file() or path.stat().st_size != entry["size_bytes"] or _sha(path) != entry["sha256"]:
            raise RuntimeError("KIT_BYTES_MISMATCH")
    actual = {}
    for folder, directories, files in os.walk(root, followlinks=False):
        for name in directories + files:
            path = Path(folder) / name
            assert_no_reparse_ancestors(path)
            if not stat.S_ISDIR(path.lstat().st_mode) and not stat.S_ISREG(path.lstat().st_mode):
                raise RuntimeError("KIT_PATH_INVALID")
        for name in files:
            relative = (Path(folder) / name).relative_to(root).as_posix()
            if relative == MANIFEST:
                continue
            key = relative.casefold()
            if key in actual:
                raise RuntimeError("KIT_INVENTORY_INVALID")
            actual[key] = relative
        if len(actual) > 10000:
            raise RuntimeError("KIT_INVENTORY_INVALID")
    if actual != expected:
        raise RuntimeError("KIT_CLOSURE_MISMATCH")
    return manifest


def gate_results(summary):
    """A terminal label alone does not qualify as an accepted real gate."""
    failed = {name: "NOT_CONFIRMED" for name in EXPECTED}
    if (type(summary) is not dict or summary.get("schema_version") != "fixed-exe-update-windows-drill-v1"
            or summary.get("historical_roots_restored") is not True
            or summary.get("production_touched") is not False or summary.get("paid_provider_called") is not False):
        return failed
    results = summary.get("results")
    if type(results) is not list or len(results) != 3:
        return failed
    by_name = {}
    for result in results:
        if type(result) is not dict or result.get("scenario") in by_name:
            return failed
        by_name[result.get("scenario")] = result
    if set(by_name) != set(EXPECTED):
        return failed
    for name, state in EXPECTED.items():
        result = by_name[name]
        if (result.get("state") == state and result.get("fixed_exe") is True
                and result.get("real_http_execute") is True and result.get("detached_worker_exited") is True
                and result.get("source_processes_exited") is True
                and result.get("business_identity_config_and_media_retained") is True
                and result.get("production_touched") is False
                and (name != "rollback" or result.get("automatic_source_recovery") is True)):
            failed[name] = "PASS"
    return failed


def _check_run_paths(root, evidence):
    if os.name != "nt" or sys.version_info[:3] != (3, 14, 6):
        raise RuntimeError("KIT_FIXED_CP314_WINDOWS_REQUIRED")
    if os.path.normcase(os.path.abspath(sys.executable)) != os.path.normcase(str(root / "driver/python/python.exe")):
        raise RuntimeError("KIT_DRIVER_IDENTITY_MISMATCH")
    # Keep nonce-bearing Release staging paths well below MAX_PATH. Never
    # fall back to C:, change the machine's policy, or replace an old run.
    if (root.drive.upper() != "D:" or evidence.drive.upper() != "D:" or not evidence.is_absolute()
            or len(str(root)) > 65 or len(str(evidence)) > 65 or evidence == Path(evidence.anchor)
            or evidence == root or evidence in root.parents or root in evidence.parents):
        raise RuntimeError("KIT_NEW_SHORT_D_PATHS_REQUIRED")
    assert_no_reparse_ancestors(evidence, allow_missing=True)
    if evidence.exists():
        raise RuntimeError("KIT_EVIDENCE_EXISTS")


def _qualification(root, evidence, environment):
    result = subprocess.run([sys.executable, "-I", "-B", "-m", "enterprise.tests.fixed_exe_handoff_qualification",
        "--output", str(evidence / "qualification.json")], cwd=root / "driver", env=environment,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    path = evidence / "qualification.json"
    payload = json.loads(path.read_bytes()) if path.is_file() else {}
    return result.returncode == 0 and payload.get("qualified") is True, payload


def _deliver(evidence, report, qualification):
    share = evidence / "share"
    share.mkdir(exist_ok=False)
    _new_json(share / "RESULT.json", report)
    # Qualification emits only boolean/OS/Job diagnostics, never environment
    # values or application memory. Do not export raw fixture logs or databases.
    _new_json(share / "QUALIFICATION.json", qualification)
    archive_path = evidence / "pr148-synthetic-gates-report.zip"
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ("RESULT.json", "QUALIFICATION.json"):
            archive.write(share / name, "share/" + name)
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip() is not None or set(archive.namelist()) != {"share/RESULT.json", "share/QUALIFICATION.json"}:
            raise RuntimeError("KIT_REPORT_ZIP_INVALID")
    print(json.dumps({"state": report["state"], "gates": report["gates"],
                      "report_zip": str(archive_path), "sha256": _sha(archive_path)}, sort_keys=True))


def run_kit(root, evidence, manifest, *, preserve=False):
    from enterprise.tests.fixed_exe_update_windows_smoke import _environment
    _check_run_paths(root, evidence)
    evidence.mkdir(parents=True, exist_ok=False)
    assert_no_reparse_ancestors(evidence)
    report = {"schema_version": "pr148-test-device-result-v1", "target_commit": manifest["target_commit"],
              "source_commit": manifest["source_commit"], "synthetic_only": True, "production_touched": False,
              "started_utc": datetime.now(timezone.utc).isoformat(), "state": "PREFLIGHT_BLOCKED",
              "gates": {name: "NOT_RUN" for name in EXPECTED}, "historical_roots_restored": "not_confirmed",
              "release_published": False, "pr_merge_authorized": False}
    qualification = {}
    try:
        qualified, qualification = _qualification(root, evidence, _environment())
        if qualified:
            command = [sys.executable, "-I", "-B", "-m", "enterprise.tests.fixed_exe_update_windows_smoke",
                "--run-all", "--source-build", str(root / "source"), "--target-build", str(root / "target"),
                "--source-native-entry", str(root / "native"), "--evidence-root", str(evidence / "drill")]
            if preserve:
                command.append("--preserve-existing-local-roots")
            # Do not hard-kill the drill: its finally blocks must confirm owned
            # process exit and restore the preserved, already-stopped history.
            with (evidence / "PRIVATE-drill-output.log").open("xb") as stream:
                completed = subprocess.run(command, cwd=root / "driver", env=_environment(),
                    stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT)
            report["drill_exit_code"] = completed.returncode
            summary_path = evidence / "drill/SUMMARY.json"
            summary = json.loads(summary_path.read_bytes()) if summary_path.is_file() else {}
            report["gates"] = gate_results(summary)
            report["historical_roots_restored"] = summary.get("historical_roots_restored", "not_confirmed")
            phase_keys = {"launcher_exit_code", "code", "result_code", "failure_stage", "errno", "winerror"}
            report["phase_evidence"] = {
                item["scenario"]: {phase: {key: value for key, value in fields.items()
                    if key in phase_keys and (value is None or type(value) in (bool, int)
                    or isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value))}
                    for phase, fields in item.get("runtime_phases", {}).items()
                    if phase in {"target_start", "target_stop", "target_health", "source_start", "source_health"}
                    and isinstance(fields, dict)}
                for item in summary.get("results", []) if isinstance(item, dict) and item.get("scenario") in EXPECTED}
            report["state"] = ("THREE_GATES_PASSED" if completed.returncode == 0
                               and all(value == "PASS" for value in report["gates"].values()) else "GATE_FAILED")
        else:
            report["code"] = "INDEPENDENT_HANDOFF_ENVIRONMENT_NOT_VERIFIED"
    except Exception as exc:
        # No credential-bearing exception messages in the share report.
        report["state"] = "GATE_FAILED" if (evidence / "PRIVATE-drill-output.log").exists() else "PREFLIGHT_BLOCKED"
        report["error_type"] = type(exc).__name__
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    _deliver(evidence, report, qualification)
    return 0 if report["state"] == "THREE_GATES_PASSED" else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--verify-only", action="store_true")
    mode.add_argument("--run-all", action="store_true")
    parser.add_argument("--kit-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--confirm-synthetic-test-device", action="store_true")
    parser.add_argument("--preserve-existing-local-roots", action="store_true")
    args = parser.parse_args()
    root = Path(os.path.abspath(args.kit_root))
    manifest = verify_kit(root)
    if args.verify_only:
        print(json.dumps({"verified": True, "target_commit": manifest["target_commit"],
                          "source_commit": manifest["source_commit"], "files": len(manifest["files"])}))
        return 0
    if not args.confirm_synthetic_test_device or args.evidence_root is None:
        raise RuntimeError("KIT_TEST_DEVICE_CONFIRMATION_REQUIRED")
    return run_kit(root, args.evidence_root, manifest, preserve=args.preserve_existing_local_roots)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"state": "PREFLIGHT_BLOCKED", "error_type": type(exc).__name__}))
        raise SystemExit(2)
