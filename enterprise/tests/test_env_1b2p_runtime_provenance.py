"""ENV-1B2P layered runtime provenance verification tests."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enterprise.release import runtime_provenance as provenance


ENTERPRISE_COMMIT = "a" * 40
ORIGINAL_PTH = b"python310.zip\r\n.\r\n\r\n# Uncomment to run site.main() automatically\r\nimport site\r\n"
CANDIDATE_PTH = b"python310.zip\r\n.\r\n..\r\nimport site\r\n"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _file_record(path: Path, relative: str) -> dict[str, object]:
    content = path.read_bytes()
    return {"path": relative, "sha256": _sha(content), "size_bytes": len(content)}


@dataclass
class Fixture:
    root: Path
    runtime: Path
    manifest: Path
    lock: Path
    wheel_manifest: Path
    wheelhouse: Path
    source_archive: Path
    upstream_archive: Path
    external_report: Path
    target_archive: Path | None
    rebuild_attestation: Path | None
    pip_check_report: Path | None
    archive_build_record: Path | None
    probe: dict[str, object]


def _write_zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in sorted(entries):
            archive.writestr(name, entries[name])


def _build_fixture(
    tmp_path: Path,
    *,
    independent_dependency: bool = False,
    formal_archive: bool = False,
    build_record: bool = False,
) -> Fixture:
    runtime = tmp_path / "candidate-runtime"
    runtime.mkdir()
    upstream_content: dict[str, bytes] = {}
    candidate_content: dict[str, bytes] = {}
    for relative in provenance.UPSTREAM_CORE_FILES:
        upstream = ORIGINAL_PTH if relative == "python310._pth" else f"upstream:{relative}".encode("utf-8")
        candidate = CANDIDATE_PTH if relative == "python310._pth" else upstream
        upstream_content[relative] = upstream
        candidate_content[relative] = candidate
        path = runtime / Path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(candidate)

    upstream_archive = tmp_path / "fixed-upstream-core.zip"
    source_archive = tmp_path / "source-python.zip"
    _write_zip(upstream_archive, {f"python/{name}": content for name, content in upstream_content.items()})
    _write_zip(source_archive, {f"python/{name}": content for name, content in upstream_content.items()})

    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    wheel_data = {
        "alpha-1.0-py3-none-any.whl": b"alpha-wheel",
        "native-2.0-cp310-cp310-win_amd64.whl": b"native-wheel",
    }
    for name, content in wheel_data.items():
        (wheelhouse / name).write_bytes(content)
    lock = tmp_path / "requirements-windows-cp310.lock"
    lock.write_text("alpha==1.0\nnative==2.0\n", encoding="utf-8")
    wheel_manifest = tmp_path / "wheelhouse-sha256.json"
    wheel_payload = {
        "invalid_wheel_count": 0,
        "schema_version": provenance.WHEELHOUSE_MANIFEST_SCHEMA,
        "target_platform": "win_amd64",
        "target_python_abi": "cp310",
        "wheel_count": 2,
        "wheels": [
            {
                "abi_tags": ["none" if "none-any" in name else "cp310"],
                "compatible_with_cpython_310_win_amd64": True,
                "filename": name,
                "package": "alpha" if name.startswith("alpha-") else "native",
                "platform_tags": ["any" if name.endswith("none-any.whl") else "win_amd64"],
                "python_tags": ["py3" if "-py3-" in name else "cp310"],
                "sha256": _sha(content),
                "size_bytes": len(content),
                "version": "1.0" if name.startswith("alpha-") else "2.0",
            }
            for name, content in sorted(wheel_data.items())
        ],
    }
    wheel_manifest.write_text(json.dumps(wheel_payload, sort_keys=True), encoding="utf-8")
    external_report = tmp_path / "external-validation.md"
    external_report.write_text("Historical validation attachment only.\n", encoding="utf-8")

    core_names = ("python.exe", "pythonw.exe", "python310.dll", "python310.zip", "python310._pth")
    core_files = []
    for name in core_names:
        content = (runtime / name).read_bytes()
        core_files.append({"filename": name, "sha256": _sha(content), "size_bytes": len(content)})
    files = [_file_record(path, path.relative_to(runtime).as_posix()) for path in sorted(runtime.rglob("*")) if path.is_file()]
    runtime_size = sum(int(item["size_bytes"]) for item in files)
    manifest_payload: dict[str, object] = {
        "architecture": "x64",
        "core_files": core_files,
        "dependency_lock": {
            "filename": lock.name,
            "invalid_wheel_count": 0,
            "sha256": provenance._sha256_file(lock),
            "wheel_count": 2,
            "wheelhouse_manifest_filename": wheel_manifest.name,
            "wheelhouse_manifest_sha256": provenance._sha256_file(wheel_manifest),
        },
        "embedded_pth": {
            "candidate_sha256": _sha(CANDIDATE_PTH),
            "import_site_enabled": True,
            "original_sha256": _sha(ORIGINAL_PTH),
            "relative_app_root_entry": "..",
        },
        "files_summary": {"runtime_file_count": len(files), "runtime_size_bytes": runtime_size},
        "python_abi": "cp310",
        "python_implementation": "CPython",
        "python_version": "3.10.11",
        "schema_version": provenance.RUNTIME_MANIFEST_SCHEMA,
        "source": {
            "enterprise_commit": ENTERPRISE_COMMIT,
            "upstream_commit": provenance.FIXED_UPSTREAM_COMMIT,
            "upstream_repository": provenance.FIXED_UPSTREAM_REPOSITORY,
            "upstream_version": provenance.FIXED_UPSTREAM_VERSION,
        },
        "source_python_zip": {
            "provenance_verified": False,
            "sha256": provenance._sha256_file(source_archive),
            "size_bytes": source_archive.stat().st_size,
        },
    }
    runtime_tree_digest = provenance._tree_inventory(runtime)[1]
    wheelhouse_tree_digest = provenance._tree_inventory(wheelhouse)[1]
    installed_closure_digest = provenance._installed_closure_digest({"alpha": "1.0", "native": "2.0"})
    dependency_binding = manifest_payload["dependency_lock"]
    assert isinstance(dependency_binding, dict)
    independent_common: dict[str, object] = {
        "dependency_lock_sha256": provenance._sha256_file(lock),
        "enterprise_commit": ENTERPRISE_COMMIT,
        "installed_closure_sha256": installed_closure_digest,
        "python_abi": "cp310",
        "python_version": "3.10.11",
        "runtime_tree_sha256": runtime_tree_digest,
        "upstream_commit": provenance.FIXED_UPSTREAM_COMMIT,
        "wheelhouse_manifest_sha256": provenance._sha256_file(wheel_manifest),
        "wheelhouse_tree_sha256": wheelhouse_tree_digest,
    }
    rebuild_attestation: Path | None = None
    pip_check_report: Path | None = None
    if independent_dependency:
        rebuild_attestation = tmp_path / "dependency-rebuild-attestation.json"
        rebuild_payload = {
            **independent_common,
            "exit_code": 0,
            "network_download_count": 0,
            "rebuild_command_classification": "offline-locked-wheelhouse",
            "result": "pass",
            "schema_version": provenance.DEPENDENCY_REBUILD_ATTESTATION_SCHEMA,
        }
        rebuild_attestation.write_text(json.dumps(rebuild_payload, sort_keys=True), encoding="utf-8")
        pip_check_report = tmp_path / "pip-check-report.json"
        pip_payload = {
            **independent_common,
            "broken_requirements": [],
            "command_identity": "python-minus-m-pip-check",
            "exit_code": 0,
            "result": "pass",
            "schema_version": provenance.PIP_CHECK_REPORT_SCHEMA,
        }
        pip_check_report.write_text(json.dumps(pip_payload, sort_keys=True), encoding="utf-8")
        dependency_binding.update(
            {
                "pip_check_report_filename": pip_check_report.name,
                "pip_check_report_sha256": provenance._sha256_file(pip_check_report),
                "rebuild_attestation_filename": rebuild_attestation.name,
                "rebuild_attestation_sha256": provenance._sha256_file(rebuild_attestation),
            }
        )

    target_archive: Path | None = None
    archive_build_record: Path | None = None
    if formal_archive:
        target_archive = tmp_path / "candidate-runtime.zip"
        _write_zip(target_archive, {f"runtime/{name}": content for name, content in candidate_content.items()})
        manifest_payload["files"] = files
        manifest_payload["archive_provenance"] = {
            "archive_sha256": provenance._sha256_file(target_archive),
            "artifact_role": "assembled_candidate_runtime",
            "dependency_lock_sha256": provenance._sha256_file(lock),
            "enterprise_commit": ENTERPRISE_COMMIT,
            "post_build_changes_detected": False,
            "python_abi": "cp310",
            "python_version": "3.10.11",
            "root_prefix": "runtime",
            "upstream_commit": provenance.FIXED_UPSTREAM_COMMIT,
            "wheelhouse_manifest_sha256": provenance._sha256_file(wheel_manifest),
        }
        if build_record:
            archive_records = provenance._zip_inventory(target_archive)[0]
            file_records = {
                str(item["path"]): provenance.FileRecord(
                    str(item["path"]), str(item["sha256"]), int(item["size_bytes"])
                )
                for item in files
            }
            archive_build_record = tmp_path / "archive-build-record.json"
            build_payload = {
                "build_result": "pass",
                "builder_identifier": "fixture-runtime-archive-builder",
                "builder_version": "fixture-builder-v1",
                "dependency_lock_sha256": provenance._sha256_file(lock),
                "enterprise_commit": ENTERPRISE_COMMIT,
                "full_file_inventory_sha256": provenance._records_digest(file_records),
                "output_archive_entry_count": len(archive_records),
                "output_archive_sha256": provenance._sha256_file(target_archive),
                "post_build_changes_detected": False,
                "python_abi": "cp310",
                "python_version": "3.10.11",
                "runtime_tree_sha256": runtime_tree_digest,
                "schema_version": provenance.ARCHIVE_BUILD_RECORD_SCHEMA,
                "upstream_commit": provenance.FIXED_UPSTREAM_COMMIT,
                "wheelhouse_manifest_sha256": provenance._sha256_file(wheel_manifest),
                "wheelhouse_tree_sha256": wheelhouse_tree_digest,
            }
            archive_build_record.write_text(json.dumps(build_payload, sort_keys=True), encoding="utf-8")
            archive_binding = manifest_payload["archive_provenance"]
            assert isinstance(archive_binding, dict)
            archive_binding.update(
                {
                    "archive_build_record_filename": archive_build_record.name,
                    "archive_build_record_sha256": provenance._sha256_file(archive_build_record),
                }
            )

    manifest = tmp_path / "runtime-manifest.json"
    manifest.write_text(json.dumps(manifest_payload, sort_keys=True), encoding="utf-8")
    probe: dict[str, object] = {
        "abiflags": "",
        "architecture": ["64bit", "WindowsPE"],
        "base_prefix_basename": runtime.name,
        "distributions": [
            {"name": "alpha", "version": "1.0"},
            {"name": "native", "version": "2.0"},
        ],
        "executable_basename": "python.exe",
        "implementation": "CPython",
        "implementation_name": "cpython",
        "machine": "AMD64",
        "pointer_bits": 64,
        "prefix_basename": runtime.name,
        "soabi": "cp310",
        "version": "fixture CPython 3.10.11",
        "version_info": [3, 10, 11],
    }
    return Fixture(
        tmp_path,
        runtime,
        manifest,
        lock,
        wheel_manifest,
        wheelhouse,
        source_archive,
        upstream_archive,
        external_report,
        target_archive,
        rebuild_attestation,
        pip_check_report,
        archive_build_record,
        probe,
    )


def _verify(fixture: Fixture, **overrides: object) -> dict[str, object]:
    arguments: dict[str, object] = {
        "core_runtime_root": fixture.runtime,
        "runtime_manifest": fixture.manifest,
        "dependency_lock": fixture.lock,
        "wheelhouse_manifest": fixture.wheel_manifest,
        "wheelhouse": fixture.wheelhouse,
        "dependency_rebuild_attestation": fixture.rebuild_attestation,
        "pip_check_report": fixture.pip_check_report,
        "archive": fixture.target_archive,
        "archive_build_record": fixture.archive_build_record,
        "source_runtime_archive": fixture.source_archive,
        "external_validation_report": fixture.external_report,
        "upstream_core_archive": fixture.upstream_archive,
        "enterprise_commit": ENTERPRISE_COMMIT,
        "upstream_commit": provenance.FIXED_UPSTREAM_COMMIT,
    }
    arguments.update(overrides)
    with patch.object(provenance, "_candidate_interpreter_probe", return_value=fixture.probe):
        return provenance.verify_runtime_provenance(**arguments)


def _check(report: dict[str, object], identifier: str) -> dict[str, object]:
    return next(item for item in report["checks"] if item["id"] == identifier)  # type: ignore[index]


def _rewrite_bound_artifact(
    fixture: Fixture,
    artifact: Path,
    *,
    manifest_section: str,
    manifest_sha256_field: str,
    updates: dict[str, object],
) -> None:
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload.update(updates)
    artifact.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    manifest = json.loads(fixture.manifest.read_text(encoding="utf-8"))
    manifest[manifest_section][manifest_sha256_field] = provenance._sha256_file(artifact)
    fixture.manifest.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")


def test_complete_core_runtime_matches_fixed_upstream(tmp_path: Path) -> None:
    report = _verify(_build_fixture(tmp_path))
    assert report["core_runtime_provenance_verified"] is True
    assert report["overall_classification"] == "partially_verified"
    assert _check(report, "fixed-upstream-core-inventory")["count"] == 34


def test_core_file_missing_fails_integrity(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    (fixture.runtime / "python310.dll").unlink()
    report = _verify(fixture)
    assert report["result"] == "fail"
    assert report["core_runtime_provenance_verified"] is False


def test_core_file_hash_mismatch_fails_integrity(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    (fixture.runtime / "python.exe").write_bytes(b"changed")
    assert _verify(fixture)["overall_classification"] == "failed_integrity"


def test_manifest_declared_core_file_must_exist(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    payload = json.loads(fixture.manifest.read_text(encoding="utf-8"))
    payload["core_files"].append({"filename": "missing.dll", "sha256": "0" * 64, "size_bytes": 1})
    fixture.manifest.write_text(json.dumps(payload), encoding="utf-8")
    assert _check(_verify(fixture), "core-manifest-files-match-runtime")["status"] == "fail"


@pytest.mark.parametrize("unsafe", ["../escape.dll", "C:/absolute.dll"])
def test_manifest_rejects_unsafe_core_paths(tmp_path: Path, unsafe: str) -> None:
    fixture = _build_fixture(tmp_path)
    payload = json.loads(fixture.manifest.read_text(encoding="utf-8"))
    payload["core_files"][0]["filename"] = unsafe
    fixture.manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(provenance.ProvenanceVerificationError):
        _verify(fixture)


def test_reparse_runtime_root_is_rejected(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    original = provenance._has_reparse_point

    def classify(path: Path) -> bool:
        return path.absolute() == fixture.runtime.absolute() or original(path)

    with patch.object(provenance, "_has_reparse_point", side_effect=classify):
        with pytest.raises(provenance.ProvenanceVerificationError, match="input-reparse-point"):
            _verify(fixture)


def test_unsupported_manifest_schema_fails_closed(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    payload = json.loads(fixture.manifest.read_text(encoding="utf-8"))
    payload["schema_version"] = "future-schema"
    fixture.manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(provenance.ProvenanceVerificationError, match="unsupported-schema"):
        _verify(fixture)


def test_lock_and_wheelhouse_bidirectional_closure(tmp_path: Path) -> None:
    report = _verify(_build_fixture(tmp_path, independent_dependency=True))
    assert _check(report, "dependency-lock-wheel-manifest-closure")["status"] == "pass"
    assert _check(report, "wheelhouse-bidirectional-closure")["status"] == "pass"
    assert _check(report, "candidate-installed-exact-closure")["status"] == "pass"
    assert report["dependency_layer_rebuilt_and_verified"] is True


def test_unlocked_distribution_fails_exact_installed_closure(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path, independent_dependency=True)
    fixture.probe["distributions"].append({"name": "rogue", "version": "1.0"})  # type: ignore[union-attr]
    report = _verify(fixture)
    assert _check(report, "candidate-installed-exact-closure")["status"] == "fail"
    assert report["dependency_layer_rebuilt_and_verified"] is False
    assert report["overall_classification"] == "failed_integrity"


def test_fixed_bootstrap_distribution_allowlist_is_reported(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    fixture.probe["distributions"].append({"name": "pip", "version": "26.1.1"})  # type: ignore[union-attr]
    report = _verify(fixture)
    assert _check(report, "candidate-installed-exact-closure")["status"] == "pass"
    assert report["bootstrap_distribution_allowlist"] == ["pip", "setuptools", "wheel"]
    assert report["bootstrap_distributions"] == [{"name": "pip", "version": "26.1.1"}]


def test_manifest_pip_check_boolean_cannot_elevate_dependency(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    payload = json.loads(fixture.manifest.read_text(encoding="utf-8"))
    payload["dependency_rebuild_evidence"] = {"pip_check_passed": True}
    fixture.manifest.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    report = _verify(fixture)
    assert report["dependency_layer_rebuilt_and_verified"] is False
    assert _check(report, "dependency-rebuild-attestation-binding")["status"] == "insufficient"


def test_manifest_offline_boolean_cannot_elevate_dependency(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    payload = json.loads(fixture.manifest.read_text(encoding="utf-8"))
    payload["dependency_rebuild_evidence"] = {"network_download_count": 0, "offline": True}
    fixture.manifest.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    report = _verify(fixture)
    assert report["dependency_layer_rebuilt_and_verified"] is False
    assert _check(report, "pip-check-report-binding")["status"] == "insufficient"


def test_missing_independent_rebuild_attestation_is_insufficient(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path, independent_dependency=True)
    report = _verify(fixture, dependency_rebuild_attestation=None)
    assert report["dependency_layer_rebuilt_and_verified"] is False
    assert _check(report, "dependency-rebuild-attestation-binding")["status"] == "insufficient"
    assert report["result"] == "pass"


def test_missing_independent_pip_check_report_is_insufficient(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path, independent_dependency=True)
    report = _verify(fixture, pip_check_report=None)
    assert report["dependency_layer_rebuilt_and_verified"] is False
    assert _check(report, "pip-check-report-binding")["status"] == "insufficient"
    assert report["result"] == "pass"


def test_rebuild_attestation_hash_mismatch_fails_integrity(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path, independent_dependency=True)
    assert fixture.rebuild_attestation is not None
    fixture.rebuild_attestation.write_text(
        fixture.rebuild_attestation.read_text(encoding="utf-8") + "\n", encoding="utf-8"
    )
    report = _verify(fixture)
    assert _check(report, "dependency-rebuild-attestation-binding")["status"] == "fail"
    assert report["overall_classification"] == "failed_integrity"


def test_pip_check_report_hash_mismatch_fails_integrity(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path, independent_dependency=True)
    assert fixture.pip_check_report is not None
    fixture.pip_check_report.write_text(
        fixture.pip_check_report.read_text(encoding="utf-8") + "\n", encoding="utf-8"
    )
    report = _verify(fixture)
    assert _check(report, "pip-check-report-binding")["status"] == "fail"
    assert report["overall_classification"] == "failed_integrity"


def test_rebuild_attestation_runtime_tree_mismatch_fails_integrity(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path, independent_dependency=True)
    assert fixture.rebuild_attestation is not None
    _rewrite_bound_artifact(
        fixture,
        fixture.rebuild_attestation,
        manifest_section="dependency_lock",
        manifest_sha256_field="rebuild_attestation_sha256",
        updates={"runtime_tree_sha256": "0" * 64},
    )
    report = _verify(fixture)
    assert _check(report, "dependency-rebuild-attestation-content")["status"] == "fail"
    assert report["overall_classification"] == "failed_integrity"


def test_pip_check_nonzero_exit_fails_integrity(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path, independent_dependency=True)
    assert fixture.pip_check_report is not None
    _rewrite_bound_artifact(
        fixture,
        fixture.pip_check_report,
        manifest_section="dependency_lock",
        manifest_sha256_field="pip_check_report_sha256",
        updates={"exit_code": 1, "result": "fail"},
    )
    report = _verify(fixture)
    assert _check(report, "pip-check-report-content")["status"] == "fail"
    assert report["overall_classification"] == "failed_integrity"


def test_pip_check_broken_requirements_fail_integrity(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path, independent_dependency=True)
    assert fixture.pip_check_report is not None
    _rewrite_bound_artifact(
        fixture,
        fixture.pip_check_report,
        manifest_section="dependency_lock",
        manifest_sha256_field="pip_check_report_sha256",
        updates={"broken_requirements": ["alpha requires missing"]},
    )
    report = _verify(fixture)
    assert _check(report, "pip-check-report-content")["status"] == "fail"
    assert report["overall_classification"] == "failed_integrity"


def test_nested_platform_wheelhouse_is_closed_by_basename(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path, independent_dependency=True)
    leaf = fixture.wheelhouse / "windows-x64" / "cp310"
    leaf.mkdir(parents=True)
    for wheel in list(fixture.wheelhouse.glob("*.whl")):
        wheel.replace(leaf / wheel.name)
    tree_digest = provenance._tree_inventory(fixture.wheelhouse)[1]
    assert fixture.rebuild_attestation is not None and fixture.pip_check_report is not None
    _rewrite_bound_artifact(
        fixture,
        fixture.rebuild_attestation,
        manifest_section="dependency_lock",
        manifest_sha256_field="rebuild_attestation_sha256",
        updates={"wheelhouse_tree_sha256": tree_digest},
    )
    _rewrite_bound_artifact(
        fixture,
        fixture.pip_check_report,
        manifest_section="dependency_lock",
        manifest_sha256_field="pip_check_report_sha256",
        updates={"wheelhouse_tree_sha256": tree_digest},
    )
    report = _verify(fixture)
    assert report["dependency_layer_rebuilt_and_verified"] is True
    assert _check(report, "wheelhouse-unchanged")["status"] == "pass"


def test_lock_missing_wheel_fails_integrity(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    fixture.lock.write_text(fixture.lock.read_text(encoding="utf-8") + "missing==3.0\n", encoding="utf-8")
    assert _verify(fixture)["result"] == "fail"


def test_wheelhouse_extra_file_fails_integrity(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    (fixture.wheelhouse / "extra-1.0-py3-none-any.whl").write_bytes(b"extra")
    assert _check(_verify(fixture), "wheelhouse-bidirectional-closure")["status"] == "fail"


def test_wheel_hash_mismatch_fails_integrity(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    next(fixture.wheelhouse.glob("*.whl")).write_bytes(b"tampered")
    assert _check(_verify(fixture), "wheelhouse-sha256")["status"] == "fail"


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("native-2.0-cp310-cp310-win_amd64.whl", True),
        ("portable-2.0-py3-none-any.whl", True),
        ("legacy-2.0-py2-none-any.whl", False),
        ("native-2.0-cp311-cp311-win_amd64.whl", False),
        ("native-2.0-cp310-cp310-manylinux_x86_64.whl", False),
    ],
)
def test_wheel_tag_compatibility(filename: str, expected: bool) -> None:
    assert provenance._wheel_is_cp310_win_amd64(filename) is expected


def test_formal_candidate_archive_can_be_verified(tmp_path: Path) -> None:
    report = _verify(
        _build_fixture(tmp_path, independent_dependency=True, formal_archive=True, build_record=True)
    )
    assert report["archive_provenance_verified"] is True
    assert report["overall_classification"] == "verified"
    assert _check(report, "archive-build-record-binding")["status"] == "pass"
    assert _check(report, "archive-build-record-content")["status"] == "pass"


def test_legacy_zero_build_process_hash_without_artifact_cannot_verify_archive(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path, independent_dependency=True, formal_archive=True)
    payload = json.loads(fixture.manifest.read_text(encoding="utf-8"))
    payload["archive_provenance"]["build_process_record_sha256"] = "0" * 64
    fixture.manifest.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    report = _verify(fixture)
    assert report["archive_provenance_verified"] is False
    assert _check(report, "archive-build-record-binding")["status"] == "insufficient"
    assert report["result"] == "pass"


def test_missing_archive_build_record_is_insufficient(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path, independent_dependency=True, formal_archive=True)
    report = _verify(fixture)
    assert report["archive_provenance_verified"] is False
    assert _check(report, "archive-build-record-content")["status"] == "insufficient"
    assert report["result"] == "pass"


def test_archive_build_record_hash_mismatch_fails_integrity(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path, independent_dependency=True, formal_archive=True, build_record=True)
    assert fixture.archive_build_record is not None
    fixture.archive_build_record.write_text(
        fixture.archive_build_record.read_text(encoding="utf-8") + "\n", encoding="utf-8"
    )
    report = _verify(fixture)
    assert _check(report, "archive-build-record-binding")["status"] == "fail"
    assert report["overall_classification"] == "failed_integrity"


@pytest.mark.parametrize(
    "field",
    [
        "output_archive_sha256",
        "runtime_tree_sha256",
        "dependency_lock_sha256",
        "wheelhouse_manifest_sha256",
        "wheelhouse_tree_sha256",
    ],
)
def test_archive_build_record_content_mismatch_fails_integrity(tmp_path: Path, field: str) -> None:
    fixture = _build_fixture(tmp_path, independent_dependency=True, formal_archive=True, build_record=True)
    assert fixture.archive_build_record is not None
    _rewrite_bound_artifact(
        fixture,
        fixture.archive_build_record,
        manifest_section="archive_provenance",
        manifest_sha256_field="archive_build_record_sha256",
        updates={field: "0" * 64},
    )
    report = _verify(fixture)
    assert _check(report, "archive-build-record-content")["status"] == "fail"
    assert report["overall_classification"] == "failed_integrity"


def test_archive_inventory_matches_manifest(tmp_path: Path) -> None:
    report = _verify(
        _build_fixture(tmp_path, independent_dependency=True, formal_archive=True, build_record=True)
    )
    assert _check(report, "assembled-archive-file-inventory")["status"] == "pass"


def test_archive_missing_manifest_file_fails_integrity(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path, independent_dependency=True, formal_archive=True, build_record=True)
    assert fixture.target_archive is not None
    entries = {f"runtime/{name}": (fixture.runtime / name).read_bytes() for name in provenance.UPSTREAM_CORE_FILES[:-1]}
    _write_zip(fixture.target_archive, entries)
    assert _verify(fixture)["result"] == "fail"


def test_archive_extra_file_fails_integrity(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path, independent_dependency=True, formal_archive=True, build_record=True)
    assert fixture.target_archive is not None
    with zipfile.ZipFile(fixture.target_archive, "a") as archive:
        archive.writestr("runtime/extra.dll", b"extra")
    assert _verify(fixture)["result"] == "fail"


def test_archive_path_escape_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "escape.zip"
    _write_zip(path, {"../escape.dll": b"escape"})
    with pytest.raises(provenance.ProvenanceVerificationError, match="archive-unsafe-path"):
        provenance._zip_inventory(path)


def test_archive_duplicate_normalized_path_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("python/A.dll", b"one")
        archive.writestr("python/a.dll", b"two")
    with pytest.raises(provenance.ProvenanceVerificationError, match="archive-duplicate-path"):
        provenance._zip_inventory(path)


@pytest.mark.parametrize("name", ["python/file.txt:stream", "python/CON", "python/aux.txt"])
def test_archive_ads_and_device_names_are_rejected(tmp_path: Path, name: str) -> None:
    path = tmp_path / "unsafe.zip"
    _write_zip(path, {name: b"unsafe"})
    with pytest.raises(provenance.ProvenanceVerificationError, match="archive-unsafe-path"):
        provenance._zip_inventory(path)


def test_isolated_archive_hash_does_not_verify_provenance(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    report = _verify(fixture, archive=fixture.source_archive)
    assert report["archive_provenance_verified"] is False


def test_missing_rebuild_and_pip_check_keeps_dependency_false(tmp_path: Path) -> None:
    report = _verify(_build_fixture(tmp_path))
    assert report["dependency_layer_rebuilt_and_verified"] is False
    assert "pip-check-report-missing" in report["evidence_gaps"]


def test_production_approval_is_always_false(tmp_path: Path) -> None:
    report = _verify(
        _build_fixture(tmp_path, independent_dependency=True, formal_archive=True, build_record=True)
    )
    assert report["production_approved"] is False


def test_report_contains_no_absolute_input_path(tmp_path: Path) -> None:
    report = _verify(_build_fixture(tmp_path))
    encoded = json.dumps(report, sort_keys=True)
    assert str(tmp_path) not in encoded
    assert "traceback" not in encoded.casefold()
    assert "secret" not in encoded.casefold()
    assert all("\\" not in str(item.get("basename")) for item in report["artifacts"])  # type: ignore[union-attr]


def test_same_input_produces_same_report(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    assert _verify(fixture) == _verify(fixture)


def test_mtime_changes_do_not_change_report(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    before = _verify(fixture)
    for path in (fixture.manifest, fixture.lock, fixture.source_archive):
        metadata = path.stat()
        os.utime(path, (metadata.st_atime + 10, metadata.st_mtime + 10))
    assert before == _verify(fixture)


def test_verification_does_not_modify_inputs(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path, independent_dependency=True, formal_archive=True, build_record=True)
    before = provenance._tree_inventory(fixture.runtime)[1]
    wheelhouse_before = provenance._tree_inventory(fixture.wheelhouse)[1]
    source_before = provenance._sha256_file(fixture.source_archive)
    independent_files = [
        fixture.rebuild_attestation,
        fixture.pip_check_report,
        fixture.archive_build_record,
        fixture.target_archive,
    ]
    independent_before = {
        path: provenance._sha256_file(path) for path in independent_files if path is not None
    }
    _verify(fixture)
    assert provenance._tree_inventory(fixture.runtime)[1] == before
    assert provenance._tree_inventory(fixture.wheelhouse)[1] == wheelhouse_before
    assert provenance._sha256_file(fixture.source_archive) == source_before
    assert all(provenance._sha256_file(path) == digest for path, digest in independent_before.items())


def test_failure_report_never_claims_success() -> None:
    report = provenance.failure_report("fixture-failure")
    assert report["result"] == "fail"
    assert report["production_approved"] is False
    assert not report["core_runtime_provenance_verified"]


def test_cli_missing_required_boundaries_fails_closed() -> None:
    from tools import verify_runtime_provenance as cli

    with pytest.raises(SystemExit) as raised:
        cli.main([])
    assert raised.value.code == 2


def test_verifier_has_no_network_install_or_shell_true() -> None:
    source = (ROOT / "enterprise" / "release" / "runtime_provenance.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
    assert "urllib" not in imported
    assert "socket" not in imported
    assert "pip install" not in source
    assert "shell=True" not in source
    assert "shell=False" in source


def test_external_report_alone_cannot_elevate_layers(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    report = _verify(
        fixture,
        dependency_lock=None,
        wheelhouse_manifest=None,
        wheelhouse=None,
        source_runtime_archive=None,
        upstream_core_archive=None,
        archive=None,
    )
    assert report["core_runtime_provenance_verified"] is False
    assert report["dependency_layer_rebuilt_and_verified"] is False
    assert report["archive_provenance_verified"] is False


def test_missing_candidate_archive_is_insufficient_not_integrity_failure(tmp_path: Path) -> None:
    report = _verify(_build_fixture(tmp_path))
    assert _check(report, "archive-evidence-present")["status"] == "insufficient"
    assert report["result"] == "pass"


def test_missing_upstream_core_evidence_keeps_core_false(tmp_path: Path) -> None:
    report = _verify(_build_fixture(tmp_path), upstream_core_archive=None)
    assert report["core_runtime_provenance_verified"] is False
    assert _check(report, "fixed-upstream-core-inventory")["status"] == "insufficient"


def test_output_report_cannot_be_inside_runtime(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    with pytest.raises(provenance.ProvenanceVerificationError, match="output-report-inside-input"):
        provenance.validate_output_report_path(
            fixture.runtime / "report.json", input_files=(), input_directories=(fixture.runtime,)
        )


def test_existing_output_report_is_rejected(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    output.write_text("{}", encoding="utf-8")
    with pytest.raises(provenance.ProvenanceVerificationError, match="output-report-already-exists"):
        provenance.validate_output_report_path(output, input_files=(), input_directories=())


def test_archive_symlink_entry_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "symlink.zip"
    info = zipfile.ZipInfo("python/link")
    info.create_system = 3
    info.external_attr = (stat_mode := 0o120777) << 16
    assert stat_mode
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(info, "target")
    with pytest.raises(provenance.ProvenanceVerificationError, match="archive-symlink-entry"):
        provenance._zip_inventory(path)


def test_source_archive_hash_mismatch_fails_integrity(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    payload = json.loads(fixture.manifest.read_text(encoding="utf-8"))
    payload["source_python_zip"]["sha256"] = "0" * 64
    fixture.manifest.write_text(json.dumps(payload), encoding="utf-8")
    assert _verify(fixture)["result"] == "fail"


def test_historical_enterprise_commit_is_reported_without_corrupting_core(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    payload = json.loads(fixture.manifest.read_text(encoding="utf-8"))
    payload["source"]["enterprise_commit"] = "b" * 40
    fixture.manifest.write_text(json.dumps(payload), encoding="utf-8")
    report = _verify(fixture)
    assert report["core_runtime_provenance_verified"] is True
    assert _check(report, "enterprise-baseline-binding")["status"] == "insufficient"


def test_artifacts_use_basename_and_digest_only(tmp_path: Path) -> None:
    report = _verify(_build_fixture(tmp_path))
    for artifact in report["artifacts"]:  # type: ignore[union-attr]
        assert set(artifact) <= {
            "artifact_type",
            "basename",
            "sha256",
            "size_bytes",
            "schema_version",
            "declared_identifier",
        }
        assert "/" not in artifact["basename"] and "\\" not in artifact["basename"]


def test_independent_artifacts_are_reported_with_fixed_schemas(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path, independent_dependency=True, formal_archive=True, build_record=True)
    report = _verify(fixture)
    artifacts = {item["artifact_type"]: item for item in report["artifacts"]}  # type: ignore[union-attr]
    assert (
        artifacts["dependency_rebuild_attestation"]["schema_version"]
        == provenance.DEPENDENCY_REBUILD_ATTESTATION_SCHEMA
    )
    assert artifacts["pip_check_report"]["schema_version"] == provenance.PIP_CHECK_REPORT_SCHEMA
    assert artifacts["archive_build_record"]["schema_version"] == provenance.ARCHIVE_BUILD_RECORD_SCHEMA
