from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "tools" / "validation" / "windows" / "env_1b3" / "verify_materialized_release.py"


def _load_verifier():
    spec = importlib.util.spec_from_file_location("env1b3_materialized_verifier", VERIFIER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: dict[str, object]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _tree(entries: list[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(
            str(entry["path"]).encode()
            + b"\0"
            + str(entry["size_bytes"]).encode()
            + b"\0"
            + str(entry["sha256"]).encode()
            + b"\n"
        )
    return digest.hexdigest()


def _write_materialized_fixture(root: Path) -> tuple[Path, Path, Path, Path]:
    app_root = root / "install" / "releases" / "fixture-release"
    payloads = {
        "payload.txt": b"payload\n",
        "python/python.exe": b"fixed-python-fixture\n",
        "Unicode/文件 with space.txt": b"unicode\n",
    }
    entries: list[dict[str, object]] = []
    for relative, data in sorted(payloads.items()):
        path = app_root / Path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        entries.append({"path": relative, "sha256": _sha(data), "size_bytes": len(data)})
    inventory = {
        "entries": entries,
        "file_count": len(entries),
        "schema_version": "ops-release-payload-inventory-v1",
        "total_size_bytes": sum(int(entry["size_bytes"]) for entry in entries),
        "tree_sha256": _tree(entries),
    }
    inventory_bytes = _canonical(inventory)
    inventory_path = app_root / "release-payload-inventory.json"
    inventory_path.write_bytes(inventory_bytes)
    manifest = {
        "schema_version": "ops-release-manifest-v2",
        "identity": {"release_id": "fixture-release"},
        "archive": {
            "inventory_sha256": _sha(inventory_bytes),
            "payload_tree_sha256": inventory["tree_sha256"],
        },
        "release_payload": {
            "embedded_manifest_path": "release-manifest.json",
            "file_count": inventory["file_count"],
            "inventory_path": inventory_path.name,
            "inventory_sha256": _sha(inventory_bytes),
            "total_size_bytes": inventory["total_size_bytes"],
            "tree_sha256": inventory["tree_sha256"],
        },
    }
    manifest_bytes = _canonical(manifest)
    manifest_path = app_root / "release-manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    handoff = {
        "schema_version": "env-1b3-candidate-handoff-v1",
        "candidate_id": "fixture-release-candidate-05",
        "candidate_sequence": "05",
        "inventory_sha256": _sha(inventory_bytes),
        "manifest_sha256": _sha(manifest_bytes),
        "payload_tree_sha256": inventory["tree_sha256"],
        "release_id": "fixture-release",
    }
    handoff_path = root / "CANDIDATE-HANDOFF.json"
    handoff_path.write_bytes(_canonical(handoff))
    return app_root, inventory_path, manifest_path, handoff_path


def _verify(paths: tuple[Path, Path, Path, Path]):
    module = _load_verifier()
    return module.verify_materialized_release(*paths, require_cp314=False)


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def test_standalone_verifier_accepts_closed_payload_without_tools_and_is_read_only(tmp_path: Path) -> None:
    paths = _write_materialized_fixture(tmp_path)
    assert not (paths[0] / "tools").exists()
    before = _tree_digest(paths[0])
    result = _verify(paths)
    assert result["result"] == "pass"
    assert result["file_count"] == 3
    assert result["fixed_cp314"] is False
    assert _tree_digest(paths[0]) == before


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("missing", "ENV1B3_MATERIALIZED_FILE_MISSING"),
        ("extra", "ENV1B3_MATERIALIZED_EXTRA_FILE"),
        ("hash", "ENV1B3_MATERIALIZED_HASH_MISMATCH"),
        ("size", "ENV1B3_MATERIALIZED_SIZE_MISMATCH"),
        ("tree", "ENV1B3_MATERIALIZED_INVENTORY_BINDING_INVALID"),
        ("manifest", "ENV1B3_MATERIALIZED_IDENTITY_MISMATCH"),
    ],
)
def test_standalone_verifier_rejects_materialized_tamper(
    tmp_path: Path, mutation: str, expected_code: str
) -> None:
    paths = _write_materialized_fixture(tmp_path)
    app_root, inventory_path, manifest_path, _ = paths
    payload = app_root / "payload.txt"
    if mutation == "missing":
        payload.unlink()
    elif mutation == "extra":
        (app_root / "extra.txt").write_text("extra\n", encoding="utf-8")
    elif mutation == "hash":
        payload.write_bytes(b"PAYLOAD\n")
    elif mutation == "size":
        payload.write_bytes(b"payload-extra\n")
    elif mutation == "tree":
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        inventory["tree_sha256"] = "0" * 64
        inventory_path.write_bytes(_canonical(inventory))
    elif mutation == "manifest":
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["identity"]["release_id"] = "other-release"
        manifest_path.write_bytes(_canonical(manifest))
    module = _load_verifier()
    with pytest.raises(module.VerificationError) as captured:
        module.verify_materialized_release(*paths, require_cp314=False)
    assert captured.value.code == expected_code


def test_standalone_verifier_rejects_inventory_duplicate_and_casefold_collision(tmp_path: Path) -> None:
    paths = _write_materialized_fixture(tmp_path)
    inventory_path = paths[1]
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    duplicate = dict(inventory["entries"][0])
    duplicate["path"] = str(duplicate["path"]).upper()
    inventory["entries"].append(duplicate)
    inventory["file_count"] += 1
    inventory["total_size_bytes"] += duplicate["size_bytes"]
    inventory["tree_sha256"] = _tree(inventory["entries"])
    inventory_path.write_bytes(_canonical(inventory))
    module = _load_verifier()
    with pytest.raises(module.VerificationError) as captured:
        module.verify_materialized_release(*paths, require_cp314=False)
    assert captured.value.code == "ENV1B3_MATERIALIZED_PATH_DUPLICATE"


def test_standalone_verifier_rejects_reparse_payload_when_supported(tmp_path: Path) -> None:
    paths = _write_materialized_fixture(tmp_path)
    payload = paths[0] / "payload.txt"
    target = tmp_path / "foreign.txt"
    target.write_text("payload\n", encoding="utf-8")
    payload.unlink()
    try:
        payload.symlink_to(target)
    except OSError:
        pytest.skip("real file symlink unavailable on this Windows host")
    module = _load_verifier()
    with pytest.raises(module.VerificationError) as captured:
        module.verify_materialized_release(*paths, require_cp314=False)
    assert captured.value.code == "ENV1B3_MATERIALIZED_REPARSE_FORBIDDEN"
