"""Focused contracts for the ENV-1B2A reproducible Windows Runtime builder."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from enterprise.release import runtime_provenance as provenance
from enterprise.release import windows_runtime_build as build


ROOT = Path(__file__).resolve().parents[2]
WINDOWS_INPUTS = ROOT / "runtime" / "windows"


def _json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _wheel(path: Path, name: str = "demo", version: str = "1.0") -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{name}-{version}.dist-info/METADATA", f"Name: {name}\nVersion: {version}\nLicense: MIT\n")
        archive.writestr(f"{name}/__init__.py", b"")


def _wheel_record(path: Path, *, package: str = "demo", version: str = "1.0") -> dict[str, object]:
    return {
        "abi_tags": ["none"],
        "compatible_with_cpython_314_win_amd64": True,
        "filename": path.name,
        "package": package,
        "platform_tags": ["any"],
        "python_tags": ["py3"],
        "sha256": build.sha256_file(path),
        "size_bytes": path.stat().st_size,
        "source_requirement_relation": "direct:test",
        "version": version,
    }


def _wheel_lock(path: Path, record: dict[str, object]) -> None:
    _json(
        path,
        {
            "invalid_wheel_count": 0,
            "schema_version": build.WHEELHOUSE_LOCK_SCHEMA,
            "target_platform": "win_amd64",
            "target_python_abi": "cp314",
            "wheel_count": 1,
            "wheels": [record],
        },
    )


def test_committed_source_lock_and_build_policy_are_exact() -> None:
    source = build.load_source_policy(WINDOWS_INPUTS / "python-source.json")
    wheel_payload, wheels = build.load_wheelhouse_lock(WINDOWS_INPUTS / "wheelhouse.lock.json")
    lock = build.parse_requirements_lock(WINDOWS_INPUTS / "requirements.lock")
    policy = build.load_build_policy(WINDOWS_INPUTS / "build-policy.json")
    assert source["version"] == "3.14.6"
    assert source["sha256"] == "df901e84a896ff1ee720ad03377e0c8d8c2244fda79808aeeaff6316df1cb75c"
    assert len(source["expected_core_inventory"]) == 36
    assert source["ordinary_gil_build"] is True
    assert source["free_threaded"] is False
    assert source["python_pth_policy"]["relative_app_root_entry"] == ".."
    assert source["python_pth_policy"]["import_site_enabled"] is True
    assert wheel_payload["wheel_count"] == len(wheels) == len(lock) == 30
    assert lock == {name: (wheel.version, wheel.sha256) for name, wheel in wheels.items()}
    assert {item["package"] for item in policy["bootstrap_wheels"]} == {"pip", "setuptools", "wheel"}


@pytest.mark.parametrize(
    ("updates", "expected_code"),
    (
        ({"version": "3.10.11", "python_abi": "cp310"}, "PYTHON_SOURCE_POLICY_INVALID"),
        ({"ordinary_gil_build": False}, "PYTHON_SOURCE_POLICY_INVALID"),
        ({"free_threaded": True}, "PYTHON_SOURCE_POLICY_INVALID"),
    ),
)
def test_active_source_policy_rejects_legacy_or_nonstandard_runtime(
    tmp_path: Path, updates: dict[str, object], expected_code: str
) -> None:
    payload = json.loads((WINDOWS_INPUTS / "python-source.json").read_text(encoding="utf-8"))
    payload.update(updates)
    policy = tmp_path / "python-source.json"
    _json(policy, payload)
    with pytest.raises(build.WindowsRuntimeBuildError) as exc:
        build.load_source_policy(policy)
    assert exc.value.code == expected_code


@pytest.mark.parametrize(
    "updates",
    (
        {"active_python_version": "3.10.11", "active_python_abi": "cp310"},
        {"ordinary_gil_build": False},
        {"free_threaded": True},
    ),
)
def test_active_build_policy_rejects_legacy_or_nonstandard_runtime(
    tmp_path: Path, updates: dict[str, object]
) -> None:
    payload = json.loads((WINDOWS_INPUTS / "build-policy.json").read_text(encoding="utf-8"))
    payload.update(updates)
    policy = tmp_path / "build-policy.json"
    _json(policy, payload)
    with pytest.raises(build.WindowsRuntimeBuildError) as exc:
        build.load_build_policy(policy)
    assert exc.value.code == "BUILD_POLICY_INVALID"


@pytest.mark.parametrize(
    "line",
    (
        "demo==1.0",
        "demo>=1.0 --hash=sha256:" + "a" * 64,
        "demo==1.0 --hash=sha256:not-a-hash",
        "demo==1.0 --hash=sha256:" + "A" * 64,
    ),
)
def test_dependency_lock_requires_exact_version_and_lowercase_sha256(tmp_path: Path, line: str) -> None:
    path = tmp_path / "requirements.lock"
    path.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(build.WindowsRuntimeBuildError) as exc:
        build.parse_requirements_lock(path)
    assert exc.value.code == "DEPENDENCY_LOCK_LINE_INVALID"


def test_dependency_lock_rejects_duplicate_normalized_name(tmp_path: Path) -> None:
    path = tmp_path / "requirements.lock"
    path.write_text(
        "demo-name==1 --hash=sha256:" + "a" * 64 + "\n"
        "demo_name==1 --hash=sha256:" + "a" * 64 + "\n",
        encoding="utf-8",
    )
    with pytest.raises(build.WindowsRuntimeBuildError) as exc:
        build.parse_requirements_lock(path)
    assert exc.value.code == "DEPENDENCY_LOCK_DUPLICATE"


@pytest.mark.parametrize(
    "filename",
    ("demo-1.0.tar.gz", "demo-1.0-cp311-cp311-win_amd64.whl", "demo-1.0-cp314-cp314-win32.whl"),
)
def test_wheelhouse_lock_rejects_sdist_and_unsupported_tags(tmp_path: Path, filename: str) -> None:
    wheel = tmp_path / filename
    wheel.write_bytes(b"fixture")
    record = _wheel_record(wheel)
    record.update({"python_tags": ["cp314"], "abi_tags": ["cp314"], "platform_tags": ["win_amd64"]})
    path = tmp_path / "wheelhouse.lock.json"
    _wheel_lock(path, record)
    with pytest.raises(build.WindowsRuntimeBuildError) as exc:
        build.load_wheelhouse_lock(path)
    assert exc.value.code in {"WHEELHOUSE_RECORD_INVALID", "RELATIVE_PATH_INVALID"}


def test_prepare_sources_rejects_tampered_official_archive(tmp_path: Path) -> None:
    policy = json.loads((WINDOWS_INPUTS / "python-source.json").read_text(encoding="utf-8"))
    archive = tmp_path / policy["archive_filename"]
    archive.write_bytes(b"tampered")
    with pytest.raises(build.WindowsRuntimeBuildError) as exc:
        build.prepare_sources(
            source_archive=archive,
            source_policy=WINDOWS_INPUTS / "python-source.json",
            output=tmp_path / "prepared",
        )
    assert exc.value.code == "PYTHON_SOURCE_HASH_MISMATCH"


def test_prepare_wheelhouse_is_closed_and_hash_bound(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    wheel = seed / "demo-1.0-py3-none-any.whl"
    _wheel(wheel)
    lock_path = tmp_path / "wheelhouse.lock.json"
    _wheel_lock(lock_path, _wheel_record(wheel))
    bootstrap = tmp_path / "bootstrap"
    bootstrap.mkdir()
    policy = json.loads((WINDOWS_INPUTS / "build-policy.json").read_text(encoding="utf-8"))
    for item in policy["bootstrap_wheels"]:
        target = bootstrap / item["filename"]
        target.write_bytes(item["package"].encode("ascii"))
        item["sha256"] = build.sha256_file(target)
        item["size_bytes"] = target.stat().st_size
    policy_path = tmp_path / "policy.json"
    _json(policy_path, policy)
    application, copied_bootstrap = build.prepare_wheelhouse(
        seed_wheelhouse=seed,
        seed_bootstrap_wheelhouse=bootstrap,
        wheelhouse_lock=lock_path,
        build_policy=policy_path,
        output=tmp_path / "prepared",
    )
    assert [path.name for path in application.iterdir()] == [wheel.name]
    assert len(list(copied_bootstrap.iterdir())) == 3


def test_prepare_wheelhouse_rejects_extra_file(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    wheel = seed / "demo-1.0-py3-none-any.whl"
    _wheel(wheel)
    (seed / "extra.whl").write_bytes(b"extra")
    lock_path = tmp_path / "wheelhouse.lock.json"
    _wheel_lock(lock_path, _wheel_record(wheel))
    with pytest.raises(build.WindowsRuntimeBuildError) as exc:
        build._verify_wheel_files(seed, build.load_wheelhouse_lock(lock_path)[1])
    assert exc.value.code == "WHEELHOUSE_CLOSURE_INVALID"


def test_output_root_must_not_preexist(tmp_path: Path) -> None:
    target = tmp_path / "owned"
    target.mkdir()
    with pytest.raises(build.WindowsRuntimeBuildError) as exc:
        build._new_output_root(target)
    assert exc.value.code == "OUTPUT_ALREADY_EXISTS"


def test_console_script_normalization_removes_path_bearing_launchers_and_record_rows(tmp_path: Path) -> None:
    site = tmp_path / "site-packages"
    scripts = site / "bin"
    metadata = site / "demo-1.0.dist-info"
    scripts.mkdir(parents=True)
    metadata.mkdir()
    (scripts / "demo.exe").write_bytes(b"absolute-build-path")
    record = metadata / "RECORD"
    record.write_text(
        "../../bin/demo.exe,sha256=abc,19\n"
        "demo/__init__.py,sha256=def,0\n"
        "demo-1.0.dist-info/RECORD,,\n",
        encoding="utf-8",
    )
    build._strip_console_scripts(site)
    assert not scripts.exists()
    assert record.read_text(encoding="utf-8").splitlines() == [
        "demo/__init__.py,sha256=def,0",
        "demo-1.0.dist-info/RECORD,,",
    ]


def test_deterministic_archive_has_closed_single_runtime_root(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "python.exe").write_bytes(b"python")
    (runtime / "folder").mkdir()
    (runtime / "folder" / "value.txt").write_text("value\n", encoding="utf-8")
    first = tmp_path / "a.zip"
    second = tmp_path / "b.zip"
    first_records, first_sha = build._deterministic_archive(runtime, first)
    second_records, second_sha = build._deterministic_archive(runtime, second)
    assert first_sha == second_sha
    assert first_records == second_records
    assert set(first_records) == {"runtime/python.exe", "runtime/folder/value.txt"}
    assert all(info.date_time == build._ZIP_TIMESTAMP for info in zipfile.ZipFile(first).infolist())


def test_sbom_is_canonical_and_deterministic(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    wheel_path = wheelhouse / "demo-1.0-py3-none-any.whl"
    _wheel(wheel_path)
    wheel = build.LockedWheel(
        "demo", "1.0", wheel_path.name, build.sha256_file(wheel_path), wheel_path.stat().st_size,
        ("py3",), ("none",), ("any",), "direct:test",
    )
    arguments = {
        "wheels": {"demo": wheel},
        "wheelhouse": wheelhouse,
        "installed": {"demo": "1.0"},
        "runtime_digest": "a" * 64,
        "input_hashes": {"python_source_sha256": "b" * 64},
        "bootstrap_policy": json.loads((WINDOWS_INPUTS / "build-policy.json").read_text(encoding="utf-8")),
        "dependency_graph": {"demo": ()},
    }
    assert build._canonical_json(build._build_sbom(**arguments)) == build._canonical_json(build._build_sbom(**arguments))
    assert b"CycloneDX" in build._canonical_json(build._build_sbom(**arguments))
    payload = build._build_sbom(**arguments)
    assert payload["dependencies"][0]["ref"] == "runtime"


def test_sbom_contains_closed_requires_dist_edges(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    first_path = wheelhouse / "first-1.0-py3-none-any.whl"
    second_path = wheelhouse / "second-2.0-py3-none-any.whl"
    _wheel(first_path, "first", "1.0")
    _wheel(second_path, "second", "2.0")
    wheels = {
        name: build.LockedWheel(
            name, version, path.name, build.sha256_file(path), path.stat().st_size,
            ("py3",), ("none",), ("any",), "direct:test",
        )
        for name, version, path in (("first", "1.0", first_path), ("second", "2.0", second_path))
    }
    payload = build._build_sbom(
        wheels=wheels,
        wheelhouse=wheelhouse,
        installed={"first": "1.0", "second": "2.0"},
        runtime_digest="a" * 64,
        input_hashes={},
        bootstrap_policy=json.loads((WINDOWS_INPUTS / "build-policy.json").read_text(encoding="utf-8")),
        dependency_graph={"first": ("second",), "second": ()},
    )
    dependency = next(item for item in payload["dependencies"] if item["ref"] == "pkg:pypi/first@1.0")
    assert dependency["dependsOn"] == ["pkg:pypi/second@2.0"]


def test_builder_source_has_offline_install_and_no_shell_or_network_client() -> None:
    source = (ROOT / "enterprise" / "release" / "windows_runtime_build.py").read_text(encoding="utf-8")
    assert '"--no-index"' in source
    assert '"--find-links"' in source
    assert '"--require-hashes"' in source
    assert "shell=False" in source
    assert "urllib.request" not in source and "requests." not in source


def test_real_bundled_python_fixture_is_explicit_and_external_only() -> None:
    source = (ROOT / "enterprise" / "release" / "windows_runtime_build.py").read_text(encoding="utf-8")
    assert "ICE_B2_FIXTURE_LOCAL_BASE" in source
    assert "fixture_only_local_root_injection" in source
    assert "temporary_business_test_environment_accessed" in source
    assert '"启动企业版.bat"' in source
    assert '"查看企业版状态.bat"' in source
    assert '"企业版健康检查.bat"' in source
    assert '"停止企业版.bat"' in source
    assert "dataclasses.replace(config, fixture_child_wrapper=True)" in source
    assert "formal_wrapper_success_chain_verified" in source


def test_clean_environment_preserves_windows_architecture_but_not_python_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")
    monkeypatch.setenv("USERPROFILE", r"C:\Users\fixture")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\untrusted-local-app-data")
    monkeypatch.setenv("PYTHONHOME", "untrusted-home")
    monkeypatch.setenv("PYTHONPATH", "untrusted-path")
    environment = build._clean_environment(tmp_path)
    assert environment["PROCESSOR_ARCHITECTURE"] == "AMD64"
    assert environment["USERPROFILE"] == r"C:\Users\fixture"
    assert "LOCALAPPDATA" not in environment
    assert "PYTHONHOME" not in environment
    assert "PYTHONPATH" not in environment


def test_existing_verifier_accepts_official_root_core_inventory(tmp_path: Path) -> None:
    archive = tmp_path / "official.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        for name in provenance.UPSTREAM_CORE_FILES:
            handle.writestr(name, name.encode("ascii"))
    records, _ = provenance._zip_inventory(archive)
    assert set(provenance._upstream_core_inventory(records)) == set(provenance.UPSTREAM_CORE_FILES)
