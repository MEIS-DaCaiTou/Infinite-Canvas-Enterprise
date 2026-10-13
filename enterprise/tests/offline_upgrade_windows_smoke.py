"""Opt-in C6 complete installed-copy drills; only newly owned synthetic data.

Bundled Python runs frozen target code. Native entry, pointer, SQLite, Runtime
and verifiers are real. One fault kills only this runner; another stops only the
target service before its real health probe. Windows registration/GUI is a
separate acceptance and these drills stop at AWAITING_REGISTRATION.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import urllib.error
import urllib.request

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from enterprise import fresh_install as fresh, install_cache as files
from enterprise.paths import PortableRootInputs, derive_portable_path_roots
from enterprise.release.release_manifest_v2 import materialize_release_fixture
from enterprise.runtime.portable import windows_local_app_data_known_folder
from enterprise.tests.fixed_exe_update_windows_smoke import (
    _asset_view, _configure, _remove_owned_local_root, _environment, _native, _seed_business,
    preserved_local_roots, NAMES,
)
from enterprise.tests.update_mvp_1_windows_smoke import _create_owned_local_roots, _free_port, _port_open

RUNNER = r'''
import json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from enterprise import install_upgrade as u, install_lifecycle as lifecycle
from enterprise.ops.update import mvp
app, root, assets, native, setup, local, operation, fault = map(str, sys.argv[1:])
def checkpoint(stage):
    if fault == 'death' and stage == 'entry_published': os._exit(93)
    if fault == 'health' and stage == 'target_health':
        target = Path(root)/'releases'/u.verify_release_assets(Path(assets)).manifest.release_id
        code, result = mvp._run_launcher(target, 'stop')
        assert code == 0 and result, 'owned target stop failed'
u._checkpoint = checkpoint
try:
    args = dict(install_root=root,release_dir=assets,local_app_data_base=local,confirm_no_active_tasks=True)
    if operation == 'uninstall': result = lifecycle.uninstall_retaining_data(**args)
    elif operation == 'recover': result = u.recover_upgrade(**args)
    else: result = u.upgrade_retained(**args,native_entry_dir=native,setup_executable=setup)
    print(json.dumps(result,separators=(',',':')),flush=True)
except Exception as exc:
    print(json.dumps({'code':getattr(exc,'code',type(exc).__name__)}),flush=True)
    raise SystemExit(2)
'''


def _run(app, root, assets, native, setup, local, operation, fault=""):
    return subprocess.run([str(app / "python/python.exe"), "-I", "-B", "-c", RUNNER,
        str(app), str(root), str(assets), str(native), str(setup), str(local), operation, fault],
        cwd=app, env=_environment(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=600, creationflags=subprocess.CREATE_NO_WINDOW)


def _result(process, output, name):
    (output / (name + "-stderr.log")).write_bytes(process.stderr)
    if process.returncode != 0:
        raise RuntimeError("OFFLINE_DRILL_FAILED:" + str(process.returncode) + ":" + process.stdout.decode("utf-8", "replace")[-250:])
    result = json.loads(process.stdout)
    (output / (name + ".json")).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def _stop(root, evidence, ports):
    code, value = _native(root, "stop", evidence)
    if code != 0 or value.get("worker_exit_code") != 0 or any(_port_open(port) for port in ports):
        raise RuntimeError("OFFLINE_DRILL_CLEANUP_UNCONFIRMED")


def _http(port, path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def run(args):
    if os.name != "nt":
        raise RuntimeError("OFFLINE_DRILL_WINDOWS_REQUIRED")
    output = args.evidence_root.absolute()
    files._safe(output, missing=True); output.mkdir(exist_ok=False)
    source = _asset_view(args.source_build, output / "source-assets")
    target = _asset_view(args.target_build, output / "target-assets")
    from enterprise.install_entry import verify_entry_bundle
    for assets, native in ((source, args.source_native_entry), (target, args.target_native_entry)):
        identity = assets.manifest.section("enterprise_source")
        verify_entry_bundle(native, commit=identity["commit"], tree=identity["tree"])
    app = output / "target-tool" / target.manifest.section("archive")["root_prefix"]
    materialize_release_fixture(target.manifest_path, target.archive_path, target.inventory_path, app)
    local = windows_local_app_data_known_folder()
    report = {"schema_version": "c6-offline-drill-v1", "production_touched": False,
        "source_manifest_sha256": source.manifest.raw_sha256, "target_manifest_sha256": target.manifest.raw_sha256,
        "windows_registration_gui_verified": False, "online_handoff_tested": False, "scenarios": []}
    # Offline maintenance starts only from a verified stopped source. It does
    # not spawn an online handoff worker; that package's breakaway prerequisite
    # cannot substitute for these actual native boot/health/exit checks.
    from enterprise.runtime.windows import current_job_diagnostics
    report["runner_context"] = current_job_diagnostics()
    with preserved_local_roots(local, "c6-suite-" + uuid.uuid4().hex[:10],
                               explicitly_authorized=args.preserve_existing_local_roots):
      for scenario in args.scenarios:
        nonce = "c6-" + uuid.uuid4().hex[:10]
        evidence = output / scenario; evidence.mkdir()
        root = evidence / "install"
        with contextlib.ExitStack():
            _create_owned_local_roots(local, NAMES, nonce)
            ports = (_free_port(), _free_port()); installed = None
            print("C6 scenario started: " + scenario, flush=True)
            try:
                installed = fresh.install_greenfield(release_dir=source.manifest_path.parent, install_root=root,
                    username="c6-owned-fixture-admin", password="Fixture-only-C6-Strong-Password-2026!",
                    password_confirmation="Fixture-only-C6-Strong-Password-2026!", local_app_data_base=local,
                    native_entry_dir=args.source_native_entry)
                roots = derive_portable_path_roots(PortableRootInputs(root, local), source.manifest.release_id)
                _configure(roots, *ports)
                protected = {k: v for k, v in _seed_business(roots, installed.first_user_id).items()
                             if k not in {"InfiniteCanvas.exe", "state\\installation.json", "state/installation.json"}}
                before_entry = files._file(root / "InfiniteCanvas.exe")
                code, started = _native(root, "start", evidence)
                if code != 0 or started.get("worker_exit_code") != 0:
                    raise RuntimeError("OFFLINE_DRILL_SOURCE_START_FAILED")
                code, _ = _native(root, "health", evidence)
                if code != 0: raise RuntimeError("OFFLINE_DRILL_SOURCE_HEALTH_FAILED")
                _stop(root, evidence, ports)
                print("C6 source verified stopped: " + scenario, flush=True)
                if scenario == "retained":
                    result = _result(_run(app, root, source.manifest_path.parent, args.source_native_entry, args.target_setup, local, "uninstall"), evidence, "uninstall")
                    assert result["lifecycle_state"] == "UNINSTALLED" and not (root / "InfiniteCanvas.exe").exists()
                fault = "death" if scenario == "interrupted" else "health" if scenario == "rollback" else ""
                process = _run(app, root, target.manifest_path.parent, args.target_native_entry, args.target_setup, local, "upgrade", fault)
                (evidence / "upgrade-process.json").write_text(json.dumps({"return_code": process.returncode,
                    "stdout": process.stdout.decode("utf-8", "replace")[-2048:]}, indent=2), encoding="utf-8")
                (evidence / "upgrade-process-stderr.log").write_bytes(process.stderr)
                if fault == "death":
                    if process.returncode != 93:
                        raise RuntimeError("OFFLINE_INTERRUPT_NOT_REACHED:" + str(process.returncode) + ":" + process.stdout.decode("utf-8", "replace")[-250:])
                    (evidence / "interrupted-stderr.log").write_bytes(process.stderr)
                    result = _result(_run(app, root, target.manifest_path.parent, args.target_native_entry, args.target_setup, local, "recover"), evidence, "recovered")
                else:
                    result = _result(process, evidence, "upgraded")
                expected = "ROLLED_BACK" if scenario in {"interrupted", "rollback"} else "AWAITING_REGISTRATION"
                assert result["upgrade_state"] == expected and result["installation_id"] == installed.installation_id
                print("C6 upgrade result: " + scenario + " " + expected, flush=True)
                for relative, contents in protected.items():
                    assert (root / relative).read_bytes() == contents, relative
                if expected == "ROLLED_BACK":
                    assert files._file(root / "InfiniteCanvas.exe") == before_entry
                    assert not (root / "state/install-upgrade-active.json").exists()
                else:
                    code, info = _native(root, "tool-info", evidence)
                    assert code == 0 and info["native_tool_contract"] == 2 and info["release_id"] == target.manifest.release_id
                    assert _http(ports[1], "/enterprise/health") == 200
                    assert _http(ports[1], "/api/app-info") == 503
                    assert files._file(root / "state/windows-maintenance/maintenance-setup.exe")["sha256"] == files._file(args.target_setup)["sha256"]
                    result = _result(_run(app, root, target.manifest_path.parent, args.target_native_entry, args.target_setup, local, "recover"), evidence, "successful-no-rollback")
                    assert result["upgrade_state"] == "AWAITING_REGISTRATION"
                _stop(root, evidence, ports)
                report["scenarios"].append({"name": scenario, "state": expected, "business_files_retained": True,
                    "installation_id_retained": True, "ports_closed": True,
                    "native_original_object_restored": expected == "ROLLED_BACK"})
            finally:
                if installed and (root / "InfiniteCanvas.exe").exists():
                    _stop(root, evidence, ports)
                for name in NAMES:
                    _remove_owned_local_root(local / name, local, nonce)
    (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for field in ("source-build", "source-native-entry", "target-build", "target-native-entry", "target-setup", "evidence-root"):
        p.add_argument("--" + field, type=Path, required=True)
    p.add_argument("--preserve-existing-local-roots", action="store_true")
    p.add_argument("--scenarios", nargs="+", choices=("in-place", "retained", "interrupted", "rollback"), default=["in-place", "retained", "interrupted", "rollback"])
    args = p.parse_args()
    try:
        print(json.dumps(run(args), separators=(",", ":"))); return 0
    except Exception as exc:
        print(json.dumps({"result": "failed", "error": str(exc)[-350:]})); return 2


if __name__ == "__main__":
    raise SystemExit(main())
