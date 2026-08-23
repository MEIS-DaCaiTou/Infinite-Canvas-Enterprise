#!/usr/bin/env python3
"""Build one deterministic Gate-A INSTALL-UX-1 Setup rehearsal."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath


SCHEMA_VERSION = "install-ux-1-installer-metadata-v1"
BUILD_RECORD_SCHEMA = "install-ux-1-unsigned-build-record-v1"
MAX_JSON_BYTES = 2 * 1024 * 1024
DEVICE_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


class InstallerBuildError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _sha256(path: Path, *, maximum: int | None = None) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if maximum is not None and total > maximum:
                raise InstallerBuildError("INSTALL_UX_BUILD_FILE_TOO_LARGE")
            digest.update(chunk)
    return digest.hexdigest(), total


def _load_json(path: Path) -> dict[str, object]:
    digest, size = _sha256(path, maximum=MAX_JSON_BYTES)
    if size <= 0:
        raise InstallerBuildError("INSTALL_UX_BUILD_JSON_INVALID")
    try:
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise InstallerBuildError("INSTALL_UX_BUILD_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise InstallerBuildError("INSTALL_UX_BUILD_JSON_INVALID")
    value["_source_sha256"] = digest
    return value


def _canonical_bytes(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _write_new_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as target:
        target.write(_canonical_bytes(payload))


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", os.fspath(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        shell=False,
        check=False,
    )
    if completed.returncode != 0:
        raise InstallerBuildError("INSTALL_UX_BUILD_GIT_IDENTITY_FAILED")
    return completed.stdout.strip()


def _require_clean_repo(repo: Path) -> tuple[str, str]:
    if _git(repo, "status", "--short", "--untracked-files=all"):
        raise InstallerBuildError("INSTALL_UX_BUILD_WORKTREE_DIRTY")
    commit = _git(repo, "rev-parse", "HEAD")
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    if len(commit) != 40 or len(tree) != 40:
        raise InstallerBuildError("INSTALL_UX_BUILD_GIT_IDENTITY_FAILED")
    return commit, tree


def _safe_archive_name(value: str) -> str:
    normalized = value.replace("\\", "/")
    if not normalized or normalized.startswith(("/", "//")) or "\x00" in normalized:
        raise InstallerBuildError("INSTALL_UX_BUILD_ARCHIVE_PATH_INVALID")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise InstallerBuildError("INSTALL_UX_BUILD_ARCHIVE_PATH_INVALID")
    for part in path.parts:
        if ":" in part or part.rstrip(" .") != part:
            raise InstallerBuildError("INSTALL_UX_BUILD_ARCHIVE_PATH_INVALID")
        stem = part.split(".", 1)[0].casefold()
        if stem in DEVICE_NAMES:
            raise InstallerBuildError("INSTALL_UX_BUILD_ARCHIVE_PATH_INVALID")
    return "/".join(path.parts)


def _inspect_archive(path: Path, policy: dict[str, object]) -> tuple[str, int, int]:
    rules = policy["archive_safety"]
    if not isinstance(rules, dict):
        raise InstallerBuildError("INSTALL_UX_BUILD_POLICY_INVALID")
    maximum_entries = int(rules["maximum_entries"])
    maximum_size = int(rules["maximum_uncompressed_bytes"])
    seen: set[str] = set()
    roots: set[str] = set()
    total_size = 0
    file_count = 0
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > maximum_entries:
                raise InstallerBuildError("INSTALL_UX_BUILD_ARCHIVE_INVALID")
            for info in entries:
                name = _safe_archive_name(info.filename)
                folded = name.casefold()
                if folded in seen:
                    raise InstallerBuildError("INSTALL_UX_BUILD_ARCHIVE_PATH_COLLISION")
                seen.add(folded)
                roots.add(name.split("/", 1)[0])
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    raise InstallerBuildError("INSTALL_UX_BUILD_ARCHIVE_REPARSE_FORBIDDEN")
                if not info.is_dir():
                    file_count += 1
                    total_size += int(info.file_size)
                    if total_size > maximum_size:
                        raise InstallerBuildError("INSTALL_UX_BUILD_ARCHIVE_TOO_LARGE")
    except InstallerBuildError:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise InstallerBuildError("INSTALL_UX_BUILD_ARCHIVE_INVALID") from exc
    if len(roots) != 1 or file_count <= 0:
        raise InstallerBuildError("INSTALL_UX_BUILD_ARCHIVE_INVALID")
    return next(iter(roots)), file_count, total_size


def _verify_toolchain(
    policy: dict[str, object], iscc: Path, official_installer: Path
) -> dict[str, object]:
    expected_installer = str(policy["official_installer_sha256"])
    installer_hash, installer_size = _sha256(official_installer)
    if installer_hash != expected_installer:
        raise InstallerBuildError("INSTALL_UX_BUILD_TOOLCHAIN_INVALID")
    closure = policy["compiler_closure"]
    if not isinstance(closure, dict) or iscc.name != policy["compiler_entry"]:
        raise InstallerBuildError("INSTALL_UX_BUILD_TOOLCHAIN_INVALID")
    observed: dict[str, str] = {}
    for name, expected in closure.items():
        candidate = iscc.parent / str(name)
        actual, _size = _sha256(candidate)
        if actual != expected:
            raise InstallerBuildError("INSTALL_UX_BUILD_TOOLCHAIN_INVALID")
        observed[str(name)] = actual
    return {
        "official_installer_filename": official_installer.name,
        "official_installer_sha256": installer_hash,
        "official_installer_size_bytes": installer_size,
        "compiler_closure": observed,
        "version": policy["version"],
    }


def _compile(
    *,
    iscc: Path,
    script: Path,
    definitions: dict[str, str],
) -> None:
    command = [os.fspath(iscc)]
    command.extend(f"/D{name}={value}" for name, value in definitions.items())
    command.append(os.fspath(script))
    completed = subprocess.run(
        command,
        cwd=script.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60 * 30,
        shell=False,
        check=False,
    )
    if completed.returncode != 0:
        tail = (completed.stdout + "\n" + completed.stderr)[-4000:]
        raise InstallerBuildError(f"INSTALL_UX_BUILD_COMPILER_FAILED:{tail}")


def build(args: argparse.Namespace) -> dict[str, object]:
    repo = args.repo.resolve()
    release_dir = args.release_dir.resolve()
    output_root = args.output_root.resolve()
    iscc = args.iscc.resolve()
    official_installer = args.official_installer.resolve()
    if output_root.exists():
        raise InstallerBuildError("INSTALL_UX_BUILD_OUTPUT_EXISTS")
    output_root.mkdir(parents=True)
    commit, tree = _require_clean_repo(repo)

    sys.path.insert(0, os.fspath(repo))
    from enterprise.fresh_install import verify_release_assets
    from enterprise.release.release_manifest_v2 import verify_release_manifest_v2

    policy_path = repo / "installer" / "windows" / "install-ux-1-build-policy.json"
    tool_policy_path = repo / "installer" / "windows" / "inno-setup-toolchain-policy.json"
    script = repo / "installer" / "windows" / "InfiniteCanvasEnterprise.iss"
    policy = _load_json(policy_path)
    tool_policy = _load_json(tool_policy_path)
    policy_hash = str(policy.pop("_source_sha256"))
    tool_policy_hash = str(tool_policy.pop("_source_sha256"))
    if policy.get("schema_version") != "install-ux-1-build-policy-v1":
        raise InstallerBuildError("INSTALL_UX_BUILD_POLICY_INVALID")
    if tool_policy.get("schema_version") != "install-ux-1-inno-toolchain-policy-v1":
        raise InstallerBuildError("INSTALL_UX_BUILD_TOOLCHAIN_POLICY_INVALID")
    toolchain = _verify_toolchain(tool_policy, iscc, official_installer)
    assets = verify_release_assets(release_dir)
    verification = verify_release_manifest_v2(
        assets.manifest_path,
        assets.archive_path,
        assets.inventory_path,
        expected_enterprise_commit=commit,
        expected_enterprise_tree=tree,
    )
    root_prefix, archive_files, archive_uncompressed = _inspect_archive(assets.archive_path, policy)
    version = (repo / "VERSION").read_text(encoding="utf-8").strip()
    if version != str(assets.manifest.section("identity")["release_version"]):
        raise InstallerBuildError("INSTALL_UX_BUILD_RELEASE_VERSION_MISMATCH")
    asset_records: list[dict[str, object]] = []
    for path in (assets.archive_path, assets.manifest_path, assets.inventory_path):
        digest, size = _sha256(path)
        asset_records.append({"filename": path.name, "sha256": digest, "size_bytes": size})
    metadata: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "enterprise_commit": commit,
        "enterprise_tree": tree,
        "version": version,
        "release_id": assets.manifest.release_id,
        "archive_root_prefix": root_prefix,
        "archive_file_count": archive_files,
        "archive_uncompressed_bytes": archive_uncompressed,
        "core_asset_count": 3,
        "core_assets": asset_records,
        "payload_tree_sha256": verification.payload_tree_sha256,
        "runtime_tree_sha256": assets.manifest.section("runtime")["runtime_tree_sha256"],
        "static_tree_sha256": assets.manifest.section("release_payload")["static_tree_sha256"],
        "build_policy_sha256": policy_hash,
        "toolchain_policy_sha256": tool_policy_hash,
        "production_approved": False,
        "gate": "A",
    }
    metadata_path = output_root / "installer-metadata.json"
    _write_new_json(metadata_path, metadata)
    metadata_hash, metadata_size = _sha256(metadata_path)
    output_name = f"Infinite-Canvas-Enterprise-Setup-{version}-x64"
    common = {
        "AppVersion": version,
        "ReleaseId": assets.manifest.release_id,
        "ArchiveFilename": assets.archive_path.name,
        "ArchiveSha256": str(asset_records[0]["sha256"]),
        "ArchiveSize": str(asset_records[0]["size_bytes"]),
        "ManifestFilename": assets.manifest_path.name,
        "ManifestSha256": str(asset_records[1]["sha256"]),
        "ManifestSize": str(asset_records[1]["size_bytes"]),
        "InventoryFilename": assets.inventory_path.name,
        "InventorySha256": str(asset_records[2]["sha256"]),
        "InventorySize": str(asset_records[2]["size_bytes"]),
        "ArchiveRootPrefix": root_prefix,
        "AssetDir": os.fspath(release_dir),
        "MetadataPath": os.fspath(metadata_path),
        "MetadataSha256": metadata_hash,
        "MetadataSize": str(metadata_size),
        "OutputBaseFilename": output_name,
    }
    built: list[Path] = []
    for label in ("compile-a", "compile-b"):
        output = output_root / label
        output.mkdir()
        definitions = {**common, "OutputDir": os.fspath(output)}
        _compile(iscc=iscc, script=script, definitions=definitions)
        candidate = output / f"{output_name}.exe"
        if not candidate.is_file():
            raise InstallerBuildError("INSTALL_UX_BUILD_OUTPUT_MISSING")
        built.append(candidate)
    first_hash, first_size = _sha256(built[0])
    second_hash, second_size = _sha256(built[1])
    if (first_hash, first_size) != (second_hash, second_size):
        raise InstallerBuildError("INSTALL_UX_BUILD_UNSIGNED_NOT_REPRODUCIBLE")
    setup_path = output_root / f"{output_name}.exe"
    shutil.copy2(built[0], setup_path)
    record = {
        "schema_version": BUILD_RECORD_SCHEMA,
        "enterprise_commit": commit,
        "enterprise_tree": tree,
        "release_id": assets.manifest.release_id,
        "version": version,
        "metadata_sha256": metadata_hash,
        "unsigned_setup_filename": setup_path.name,
        "unsigned_setup_sha256": first_hash,
        "unsigned_setup_size_bytes": first_size,
        "unsigned_builds_identical": True,
        "authenticode_signed": False,
        "rfc3161_timestamped": False,
        "toolchain": toolchain,
        "production_approved": False,
    }
    _write_new_json(output_root / "unsigned-installer-build-record.json", record)
    return record


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repo", type=Path, required=True)
    result.add_argument("--release-dir", type=Path, required=True)
    result.add_argument("--output-root", type=Path, required=True)
    result.add_argument("--iscc", type=Path, required=True)
    result.add_argument("--official-installer", type=Path, required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        payload = build(parser().parse_args(argv))
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    except InstallerBuildError as exc:
        code = exc.code.split(":", 1)[0]
        print(json.dumps({"status": "blocked", "code": code}, sort_keys=True, separators=(",", ":")))
        return 2
    except BaseException:
        print(
            json.dumps(
                {"status": "blocked", "code": "INSTALL_UX_BUILD_INTERNAL_ERROR"},
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
