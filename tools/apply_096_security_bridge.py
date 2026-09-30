"""Bootstrap the one-time 09.6 security-activated database bridge.

Run with the installed 09.6 bundled Python and the three assets of the
official 09.9 Release.  This script first verifies and materializes the target
without touching the live database, then launches its reviewed worker in a
fresh process.  It never edits the immutable 09.6 release or drops audit data.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import uuid
from pathlib import Path


SOURCE_RELEASE_ID = "ice-2026.09.6-8f65c5cd328f"
SOURCE_MANIFEST_SHA256 = "e183631d52bbd0955477dfc6f6540aea99a0e173bb11821544a1db926a2cb85d"
TARGET_VERSION = "2026.09.9"


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _absolute_path(value: str, *, directory: bool) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("SECURITY_BRIDGE_PATH_NOT_ABSOLUTE")
    path = Path(os.path.abspath(os.path.normpath(os.fspath(path))))
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise ValueError("SECURITY_BRIDGE_PATH_INVALID")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely bridge an exact 09.6 security-activated installation to 09.9")
    parser.add_argument("--install-root", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--confirm-no-active-tasks", action="store_true")
    args = parser.parse_args()
    if not args.confirm_no_active_tasks:
        _emit({"result": "blocked", "code": "ACTIVE_TASK_DRAIN_CONFIRMATION_REQUIRED"})
        return 2
    try:
        install_root = _absolute_path(args.install_root, directory=True)
        manifest_path = _absolute_path(args.manifest, directory=False)
        archive_path = _absolute_path(args.archive, directory=False)
        inventory_path = _absolute_path(args.inventory, directory=False)
        source_root = install_root / "releases" / SOURCE_RELEASE_ID
        expected_python = source_root / "python" / "python.exe"
        if os.path.normcase(os.path.abspath(sys.executable)) != os.path.normcase(os.path.abspath(expected_python)):
            raise ValueError("SECURITY_BRIDGE_PYTHON_IDENTITY_MISMATCH")
        sys.path.insert(0, os.fspath(source_root))
        from enterprise.release.release_manifest_v2 import (
            materialize_release_fixture,
            read_release_manifest_v2,
            verify_materialized_release,
            verify_release_manifest_v2,
        )
        from enterprise.runtime.portable import build_portable_preflight
        from enterprise.path_safety import assert_no_reparse_ancestors

        preflight = build_portable_preflight(source_root, verify_full_payload=True)
        if (
            preflight.current_release.release.release_id != SOURCE_RELEASE_ID
            or preflight.release_manifest.raw_sha256 != SOURCE_MANIFEST_SHA256
        ):
            raise ValueError("SECURITY_BRIDGE_SOURCE_IDENTITY_MISMATCH")
        verify_release_manifest_v2(manifest_path, archive_path, inventory_path)
        target_manifest = read_release_manifest_v2(manifest_path)
        if str(target_manifest.section("identity")["release_version"]) != TARGET_VERSION:
            raise ValueError("SECURITY_BRIDGE_TARGET_VERSION_MISMATCH")
        stage = preflight.roots.STAGING_ROOT / "workspace" / f"security-bridge-{target_manifest.release_id}-{uuid.uuid4().hex}"
        assert_no_reparse_ancestors(stage, allow_missing=True)
        stage.parent.mkdir(parents=True, exist_ok=True)
        materialize_release_fixture(manifest_path, archive_path, inventory_path, stage)
        verify_materialized_release(
            stage,
            inventory_path=stage / str(target_manifest.section("release_payload")["inventory_path"]),
        )
        worker = stage / "enterprise" / "ops" / "update" / "bridge_worker_096.py"
        if not worker.is_file():
            raise ValueError("SECURITY_BRIDGE_WORKER_MISSING")
        environment = dict(os.environ)
        for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONINSPECT"):
            environment.pop(name, None)
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [
                os.fspath(expected_python), "-I", "-B", os.fspath(worker),
                "--install-root", os.fspath(install_root),
                "--staged-target-root", os.fspath(stage),
                "--manifest", os.fspath(manifest_path),
                "--archive", os.fspath(archive_path),
                "--inventory", os.fspath(inventory_path),
            ],
            cwd=os.fspath(source_root), env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        lines = completed.stdout.decode("utf-8", errors="replace").splitlines()
        result = json.loads(lines[-1]) if lines else None
        if type(result) is not dict or result.get("result") not in {"succeeded", "failed_safe", "blocked"}:
            raise ValueError("SECURITY_BRIDGE_WORKER_RESULT_INVALID")
        _emit(result)
        return 0 if completed.returncode == 0 and result["result"] == "succeeded" else 2
    except Exception as exc:
        code = str(exc)
        if not code or len(code) > 96 or not all(char.isupper() or char.isdigit() or char == "_" for char in code):
            code = "SECURITY_BRIDGE_BOOTSTRAP_FAILED"
        _emit({"result": "blocked", "code": code})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
