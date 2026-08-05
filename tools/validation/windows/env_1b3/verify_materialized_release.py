#!/usr/bin/env python3
"""Standalone, read-only ENV-1B3 materialized Release verifier."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import unicodedata
from pathlib import Path
from typing import Any


INVENTORY_SCHEMA = "ops-release-payload-inventory-v1"
MANIFEST_SCHEMA = "ops-release-manifest-v2"
HANDOFF_SCHEMA = "env-1b3-candidate-handoff-v1"
RESULT_SCHEMA = "env-1b3-materialized-verifier-result-v1"
MAX_INVENTORY_BYTES = 16 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_HANDOFF_BYTES = 64 * 1024
MAX_FILES = 20_000
MAX_SINGLE_FILE_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
WINDOWS_REPARSE_POINT = 0x400
DEVICE_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


class VerificationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _strip_windows_namespace(value: str) -> str:
    """Return the logical Windows path without changing non-namespace input."""
    if value.startswith("\\\\?\\UNC\\"):
        return "\\\\" + value[8:]
    if value.startswith("\\\\?\\") and len(value) >= 7 and value[5] == ":" and value[6] in "\\/":
        return value[4:]
    return value


def _filesystem_path(path: Path) -> Path:
    """Use Win32's extended namespace for long-path-safe read-only access."""
    absolute = str(path.absolute())
    if os.name != "nt" or absolute.startswith("\\\\?\\"):
        return Path(absolute)
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute[2:])
    return Path("\\\\?\\" + absolute)


def _comparison_path(path: Path) -> str:
    value = _strip_windows_namespace(os.path.abspath(os.fspath(path)))
    return os.path.normcase(value)


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VerificationError("ENV1B3_MATERIALIZED_JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _read_bounded(path: Path, limit: int, code: str) -> bytes:
    try:
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
    except OSError as exc:
        raise VerificationError(code) from exc
    if not data or len(data) > limit:
        raise VerificationError(code)
    return data


def _read_json(path: Path, limit: int, code: str) -> tuple[dict[str, Any], bytes]:
    data = _read_bounded(path, limit, code)
    if data.startswith(b"\xef\xbb\xbf"):
        raise VerificationError(code)
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
    except VerificationError:
        raise
    except Exception as exc:
        raise VerificationError(code) from exc
    if type(value) is not dict:
        raise VerificationError(code)
    return value, data


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _windows_key(value: str) -> str:
    return "/".join(unicodedata.normalize("NFC", part).casefold() for part in value.split("/"))


def _safe_relative(value: Any) -> str:
    if type(value) is not str or not value or len(value) > 240 or "\\" in value or value.startswith("/"):
        raise VerificationError("ENV1B3_MATERIALIZED_PATH_INVALID")
    if len(value) > 1 and value[1] == ":":
        raise VerificationError("ENV1B3_MATERIALIZED_PATH_INVALID")
    parts = value.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise VerificationError("ENV1B3_MATERIALIZED_PATH_INVALID")
    for part in parts:
        if (
            ":" in part
            or part.endswith((" ", "."))
            or any(ord(character) < 32 or ord(character) == 127 for character in part)
            or unicodedata.normalize("NFC", part).casefold().split(".", 1)[0] in DEVICE_NAMES
        ):
            raise VerificationError("ENV1B3_MATERIALIZED_PATH_INVALID")
    return "/".join(parts)


def _lstat_regular(path: Path, *, directory: bool = False) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise VerificationError("ENV1B3_MATERIALIZED_FILE_MISSING") from exc
    attributes = int(getattr(info, "st_file_attributes", 0))
    if stat.S_ISLNK(info.st_mode) or attributes & WINDOWS_REPARSE_POINT:
        raise VerificationError("ENV1B3_MATERIALIZED_REPARSE_FORBIDDEN")
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise VerificationError("ENV1B3_MATERIALIZED_PATH_INVALID")
    elif not stat.S_ISREG(info.st_mode):
        raise VerificationError("ENV1B3_MATERIALIZED_FILE_TYPE_INVALID")
    return info


def _assert_no_reparse_ancestors(path: Path) -> None:
    current = Path(os.path.abspath(os.fspath(path)))
    while True:
        if current.exists():
            _lstat_regular(current, directory=True)
        parent = current.parent
        if parent == current:
            break
        current = parent


def _canonical_json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _parse_inventory(value: dict[str, Any], raw: bytes) -> tuple[list[dict[str, Any]], str, int]:
    if set(value) != {"entries", "file_count", "schema_version", "total_size_bytes", "tree_sha256"}:
        raise VerificationError("ENV1B3_MATERIALIZED_INVENTORY_INVALID")
    if value["schema_version"] != INVENTORY_SCHEMA or type(value["entries"]) is not list:
        raise VerificationError("ENV1B3_MATERIALIZED_INVENTORY_INVALID")
    if type(value["file_count"]) is not int or type(value["total_size_bytes"]) is not int:
        raise VerificationError("ENV1B3_MATERIALIZED_INVENTORY_INVALID")
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    previous: str | None = None
    total = 0
    digest = hashlib.sha256()
    for record in value["entries"]:
        if type(record) is not dict or set(record) != {"path", "sha256", "size_bytes"}:
            raise VerificationError("ENV1B3_MATERIALIZED_INVENTORY_INVALID")
        relative = _safe_relative(record["path"])
        key = _windows_key(relative)
        if key in seen:
            raise VerificationError("ENV1B3_MATERIALIZED_PATH_DUPLICATE")
        seen.add(key)
        if previous is not None and previous >= relative:
            raise VerificationError("ENV1B3_MATERIALIZED_INVENTORY_NONCANONICAL")
        size = record["size_bytes"]
        sha = record["sha256"]
        if type(size) is not int or size < 0 or size > MAX_SINGLE_FILE_BYTES:
            raise VerificationError("ENV1B3_MATERIALIZED_INVENTORY_INVALID")
        if type(sha) is not str or len(sha) != 64 or any(character not in "0123456789abcdef" for character in sha):
            raise VerificationError("ENV1B3_MATERIALIZED_INVENTORY_INVALID")
        digest.update(relative.encode("utf-8") + b"\0" + str(size).encode("ascii") + b"\0" + sha.encode("ascii") + b"\n")
        entries.append({"path": relative, "sha256": sha, "size_bytes": size})
        total += size
        previous = relative
        if len(entries) > MAX_FILES or total > MAX_TOTAL_BYTES:
            raise VerificationError("ENV1B3_MATERIALIZED_INVENTORY_LIMIT_EXCEEDED")
    tree = digest.hexdigest()
    if (
        value["file_count"] != len(entries)
        or value["total_size_bytes"] != total
        or value["tree_sha256"] != tree
        or raw != _canonical_json(value)
    ):
        raise VerificationError("ENV1B3_MATERIALIZED_INVENTORY_BINDING_INVALID")
    return entries, tree, total


def _walk_files(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    keys: set[str] = set()

    def visit(directory: Path, relative_prefix: str) -> None:
        _lstat_regular(directory, directory=True)
        try:
            children = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as exc:
            raise VerificationError("ENV1B3_MATERIALIZED_READ_FAILED") from exc
        for child in children:
            relative = _safe_relative(f"{relative_prefix}/{child.name}" if relative_prefix else child.name)
            path = Path(child.path)
            try:
                info = child.stat(follow_symlinks=False)
            except OSError as exc:
                raise VerificationError("ENV1B3_MATERIALIZED_READ_FAILED") from exc
            attributes = int(getattr(info, "st_file_attributes", 0))
            if child.is_symlink() or attributes & WINDOWS_REPARSE_POINT:
                raise VerificationError("ENV1B3_MATERIALIZED_REPARSE_FORBIDDEN")
            key = _windows_key(relative)
            if key in keys:
                raise VerificationError("ENV1B3_MATERIALIZED_PATH_DUPLICATE")
            keys.add(key)
            if stat.S_ISDIR(info.st_mode):
                visit(path, relative)
            elif stat.S_ISREG(info.st_mode):
                result[relative] = path
            else:
                raise VerificationError("ENV1B3_MATERIALIZED_FILE_TYPE_INVALID")

    visit(root, "")
    return result


def _hash_file(path: Path, expected_size: int) -> str:
    info = _lstat_regular(path)
    if info.st_size != expected_size:
        raise VerificationError("ENV1B3_MATERIALIZED_SIZE_MISMATCH")
    digest = hashlib.sha256()
    remaining = expected_size
    try:
        with path.open("rb") as stream:
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise VerificationError("ENV1B3_MATERIALIZED_READ_FAILED")
                digest.update(chunk)
                remaining -= len(chunk)
            if stream.read(1):
                raise VerificationError("ENV1B3_MATERIALIZED_SIZE_MISMATCH")
    except VerificationError:
        raise
    except OSError as exc:
        raise VerificationError("ENV1B3_MATERIALIZED_READ_FAILED") from exc
    return digest.hexdigest()


def verify_materialized_release(
    app_root: Path,
    inventory_path: Path,
    manifest_path: Path,
    handoff_path: Path,
    *,
    require_cp314: bool = True,
) -> dict[str, Any]:
    app_root = _filesystem_path(app_root)
    inventory_path = _filesystem_path(inventory_path)
    manifest_path = _filesystem_path(manifest_path)
    handoff_path = handoff_path.absolute()
    _assert_no_reparse_ancestors(app_root)
    _lstat_regular(app_root, directory=True)
    for path in (inventory_path, manifest_path):
        try:
            path.relative_to(app_root)
        except ValueError as exc:
            raise VerificationError("ENV1B3_MATERIALIZED_PATH_INVALID") from exc
        _lstat_regular(path)

    inventory, inventory_raw = _read_json(inventory_path, MAX_INVENTORY_BYTES, "ENV1B3_MATERIALIZED_INVENTORY_INVALID")
    manifest, manifest_raw = _read_json(manifest_path, MAX_MANIFEST_BYTES, "ENV1B3_MATERIALIZED_MANIFEST_INVALID")
    handoff, _ = _read_json(handoff_path, MAX_HANDOFF_BYTES, "ENV1B3_MATERIALIZED_HANDOFF_INVALID")
    entries, tree, total = _parse_inventory(inventory, inventory_raw)

    if manifest.get("schema_version") != MANIFEST_SCHEMA or handoff.get("schema_version") != HANDOFF_SCHEMA:
        raise VerificationError("ENV1B3_MATERIALIZED_IDENTITY_MISMATCH")
    identity = manifest.get("identity")
    payload = manifest.get("release_payload")
    archive = manifest.get("archive")
    if type(identity) is not dict or type(payload) is not dict or type(archive) is not dict:
        raise VerificationError("ENV1B3_MATERIALIZED_MANIFEST_INVALID")
    if (
        identity.get("release_id") != handoff.get("release_id")
        or handoff.get("candidate_id") != f"{identity.get('release_id')}-candidate-{handoff.get('candidate_sequence')}"
        or _sha256(manifest_raw) != handoff.get("manifest_sha256")
        or _sha256(inventory_raw) != handoff.get("inventory_sha256")
        or payload.get("inventory_sha256") != handoff.get("inventory_sha256")
        or archive.get("inventory_sha256") != handoff.get("inventory_sha256")
        or payload.get("inventory_path") != inventory_path.relative_to(app_root).as_posix()
        or payload.get("embedded_manifest_path") != manifest_path.relative_to(app_root).as_posix()
        or payload.get("file_count") != len(entries)
        or payload.get("total_size_bytes") != total
        or payload.get("tree_sha256") != tree
        or archive.get("payload_tree_sha256") != tree
        or handoff.get("payload_tree_sha256") != tree
    ):
        raise VerificationError("ENV1B3_MATERIALIZED_IDENTITY_MISMATCH")

    actual = _walk_files(app_root)
    metadata = {manifest_path.relative_to(app_root).as_posix(), inventory_path.relative_to(app_root).as_posix()}
    payload_files = {name: path for name, path in actual.items() if name not in metadata}
    expected_names = {entry["path"] for entry in entries}
    if set(payload_files) != expected_names:
        missing = expected_names - set(payload_files)
        raise VerificationError("ENV1B3_MATERIALIZED_FILE_MISSING" if missing else "ENV1B3_MATERIALIZED_EXTRA_FILE")
    for entry in entries:
        if _hash_file(payload_files[entry["path"]], entry["size_bytes"]) != entry["sha256"]:
            raise VerificationError("ENV1B3_MATERIALIZED_HASH_MISMATCH")

    python_executable = app_root / "python" / "python.exe"
    _lstat_regular(python_executable)
    if require_cp314:
        if not (
            sys.flags.isolated == 1
            and sys.flags.dont_write_bytecode == 1
            and sys.dont_write_bytecode is True
            and sys.version_info[:2] == (3, 14)
            and Path(sys.executable).name.casefold() == "python.exe"
        ):
            raise VerificationError("ENV1B3_MATERIALIZED_FIXED_PYTHON_INVALID")
        try:
            if _comparison_path(Path(sys.executable)) != _comparison_path(python_executable):
                raise VerificationError("ENV1B3_MATERIALIZED_FIXED_PYTHON_INVALID")
        except OSError as exc:
            raise VerificationError("ENV1B3_MATERIALIZED_FIXED_PYTHON_INVALID") from exc

    return {
        "schema_version": RESULT_SCHEMA,
        "result": "pass",
        "release_id": identity["release_id"],
        "file_count": len(entries),
        "total_size_bytes": total,
        "payload_tree_sha256": tree,
        "fixed_cp314": require_cp314,
        "app_root_unchanged": True,
        "network_accessed": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--handoff", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if not all(path.is_absolute() for path in (args.app_root, args.inventory, args.manifest, args.handoff)):
            raise VerificationError("ENV1B3_MATERIALIZED_PATH_INVALID")
        result = verify_materialized_release(args.app_root, args.inventory, args.manifest, args.handoff)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
        return 0
    except VerificationError as exc:
        print(json.dumps({"code": exc.code, "exit_code": 2, "status": "blocked"}, sort_keys=True, separators=(",", ":")))
        return 2
    except Exception:
        print(json.dumps({"code": "ENV1B3_MATERIALIZED_INTERNAL_ERROR", "exit_code": 2, "status": "blocked"}, sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
