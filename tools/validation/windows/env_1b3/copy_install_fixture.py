"""Copy one complete ENV-1B3 install fixture with Windows long-path semantics."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil


class FixtureCopyError(Exception):
    pass


def _filesystem_path(path: Path) -> Path:
    """Use the Win32 extended prefix without changing the logical path identity."""
    if os.name != "nt":
        return path
    value = str(path.absolute())
    if value.startswith("\\\\?\\"):
        return Path(value)
    if value.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + value[2:])
    return Path("\\\\?\\" + value)


def _is_reparse(path: Path) -> bool:
    stat = path.lstat()
    return path.is_symlink() or bool(getattr(stat, "st_file_attributes", 0) & 0x400)


def _tree(root: Path) -> tuple[int, str]:
    root = _filesystem_path(root)
    records: list[tuple[str, int, str]] = []
    items = list(root.rglob("*"))
    if any(_is_reparse(item) for item in items):
        raise FixtureCopyError("ENV1B3_W09_SOURCE_INSTALL_ROOT_INVALID")
    for path in sorted((item for item in items if item.is_file()), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        records.append((relative, path.stat().st_size, digest.hexdigest()))
    aggregate = hashlib.sha256()
    for relative, size, digest in records:
        aggregate.update(f"{relative}\0{size}\0{digest}\n".encode("utf-8"))
    return len(records), aggregate.hexdigest()


def _copy_fixture() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-install-root", required=True)
    parser.add_argument("--destination", required=True)
    args = parser.parse_args()
    source = Path(args.source_install_root).resolve(strict=True)
    destination = Path(args.destination).resolve(strict=False)
    if destination.exists() or source == destination or source in destination.parents or destination in source.parents:
        raise FixtureCopyError("ENV1B3_W09_SOURCE_CASE_ROOT_OVERLAP")
    cursor = source
    while True:
        if _is_reparse(cursor):
            raise FixtureCopyError("ENV1B3_W09_SOURCE_INSTALL_ROOT_INVALID")
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    pointer = json.loads((source / "state" / "current-release.json").read_text(encoding="utf-8"))
    release_id = pointer.get("release_id")
    expected_relative = f"releases/{release_id}"
    if pointer.get("app_root_relative") != expected_relative:
        raise FixtureCopyError("ENV1B3_W09_SOURCE_INSTALL_ROOT_INVALID")
    app_root = source / "releases" / str(release_id)
    if not (app_root / "python" / "python.exe").is_file():
        raise FixtureCopyError("ENV1B3_W09_SOURCE_INSTALL_ROOT_INVALID")
    source_count, source_tree = _tree(source)
    shutil.copytree(_filesystem_path(source), _filesystem_path(destination), symlinks=False)
    destination_count, destination_tree = _tree(destination)
    copied_pointer = json.loads((destination / "state" / "current-release.json").read_text(encoding="utf-8"))
    copied_app = destination / "releases" / str(release_id)
    passed = (
        destination_count == source_count
        and destination_tree == source_tree
        and copied_pointer.get("release_id") == release_id
        and copied_pointer.get("app_root_relative") == expected_relative
        and copied_app.is_dir()
    )
    print(json.dumps({
        "result": "PASS" if passed else "FAIL",
        "file_count": destination_count,
        "tree_sha256": destination_tree,
        "release_id": release_id,
        "app_root_exists": copied_app.is_dir(),
    }, sort_keys=True, separators=(",", ":")))
    return 0 if passed else 2


def main() -> int:
    try:
        return _copy_fixture()
    except FixtureCopyError as exc:
        code = str(exc)
    except (OSError, ValueError, json.JSONDecodeError):
        code = "ENV1B3_W09_FIXTURE_COPY_FAILED"
    print(json.dumps({"result": "FAIL", "code": code}, sort_keys=True, separators=(",", ":")))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
