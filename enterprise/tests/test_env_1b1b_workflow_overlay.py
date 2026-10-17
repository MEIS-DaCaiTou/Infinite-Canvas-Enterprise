from __future__ import annotations

import json
import os
import subprocess
import sys
from enterprise.app_paths import AppPathLayout
from enterprise.paths import PortableRootInputs, derive_portable_path_roots


def test_workflow_roots_are_separate_and_user_root_has_override_precedence(tmp_path):
    roots = derive_portable_path_roots(PortableRootInputs(tmp_path / "install", tmp_path / "local"), "release-A")
    layout = AppPathLayout(roots)
    assert layout.SHIPPED_WORKFLOW_DIR.endswith("releases\\release-A\\workflows")
    assert layout.WORKFLOW_DIR.endswith("data\\workflows")
    assert layout.SHIPPED_WORKFLOW_DIR != layout.WORKFLOW_DIR


def test_workflow_overlay_copies_before_config_and_never_deletes_shipped_source(tmp_path):
    script = r'''
import asyncio
import hashlib
import json
from pathlib import Path
from enterprise.paths import derive_development_path_roots, install_path_roots_for_process
install_path_roots_for_process(derive_development_path_roots(Path.cwd()))
import main
root = Path(r"""%s""")
shipped, user = root / "shipped", root / "user"
shipped.mkdir(parents=True)
user.mkdir()

def digest_tree(path):
    hasher = hashlib.sha256()
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        hasher.update(item.relative_to(path).as_posix().encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(item.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()

(shipped / "builtin.json").write_text(json.dumps({"source": "shipped"}), encoding="utf-8")
main.SHIPPED_WORKFLOW_DIR, main.WORKFLOW_DIR = str(shipped), str(user)
assert main.list_workflows()["workflows"] == []
listed = main.list_workflows(include_disabled=True)["workflows"]
assert listed == [{"name": "builtin.json", "title": "builtin", "builtin": True, "field_count": 0, "enabled": False}]
assert main.get_workflow("builtin.json")["workflow"]["source"] == "shipped"
main.save_workflow_config("builtin.json", main.WorkflowConfig(title="copied"))
assert (user / "builtin.json").is_file()
assert (shipped / "builtin.json").is_file()
(user / "builtin.json").write_text(json.dumps({"source": "user"}), encoding="utf-8")
assert main.get_workflow("builtin.json")["workflow"]["source"] == "user"
assert main.delete_workflow("builtin.json") == {"ok": True}
assert not (user / "builtin.json").exists() and (shipped / "builtin.json").is_file()
try:
    main.delete_workflow("builtin.json")
except main.HTTPException as exc:
    assert exc.detail == "BUILTIN_WORKFLOW_DELETE_FORBIDDEN"
else:
    raise AssertionError("shipped workflow deletion was allowed")

custom = shipped / "custom"
custom.mkdir()
shipped_example = custom / "example.json"
shipped_example.write_text(json.dumps({"1": {"class_type": "ShippedNode", "inputs": {"value": "shipped"}}}, ensure_ascii=False), encoding="utf-8")
shipped_bytes_before = shipped_example.read_bytes()
shipped_digest_before = hashlib.sha256(shipped_bytes_before).hexdigest()
shipped_tree_before = digest_tree(shipped)
payload = main.WorkflowUploadRequest(
    name="example.json",
    workflow={"1": {"class_type": "UserNode", "inputs": {"value": "user"}}},
)
created = main.upload_workflow(payload)
assert created == {"name": "custom/example.json"}
user_example = user / "custom" / "example.json"
assert user_example.is_file()
assert json.loads(user_example.read_text(encoding="utf-8"))["1"]["class_type"] == "UserNode"
assert shipped_example.read_bytes() == shipped_bytes_before
assert hashlib.sha256(shipped_example.read_bytes()).hexdigest() == shipped_digest_before
assert digest_tree(shipped) == shipped_tree_before
override = main.get_workflow("custom/example.json")
assert override["workflow"]["1"]["class_type"] == "UserNode"
assert override["builtin"] is False
listed_override = [item for item in main.list_workflows()["workflows"] if item["name"] == "custom/example.json"]
assert len(listed_override) == 1
assert listed_override[0]["builtin"] is False
assert main.delete_workflow("custom/example.json") == {"ok": True}
assert not user_example.exists()
assert shipped_example.read_bytes() == shipped_bytes_before
assert hashlib.sha256(shipped_example.read_bytes()).hexdigest() == shipped_digest_before
assert digest_tree(shipped) == shipped_tree_before
restored = main.get_workflow("custom/example.json")
assert restored["workflow"]["1"]["class_type"] == "ShippedNode"
assert restored["builtin"] is True
listed_restored = [item for item in main.list_workflows(include_disabled=True)["workflows"] if item["name"] == "custom/example.json"]
assert len(listed_restored) == 1
assert listed_restored[0]["builtin"] is True
assert not restored["config"]["enabled"]
# Explicit availability survives the overlay and never removes shipped bytes.
main.save_workflow_config("builtin.json", main.WorkflowConfig(title="enabled", enabled=True))
assert any(item["name"] == "builtin.json" for item in main.list_workflows()["workflows"])
main.save_workflow_config("builtin.json", main.WorkflowConfig(title="disabled", enabled=False))
assert all(item["name"] != "builtin.json" for item in main.list_workflows()["workflows"])
assert main.get_workflow("builtin.json")["config"]["enabled"] is False
assert (shipped / "builtin.json").is_file() and (user / "builtin.json").is_file()
# Client-supplied enablement cannot run a workflow disabled in saved settings.
try:
    asyncio.run(main.run_workflow("builtin.json", main.WorkflowRunRequest(config=main.WorkflowConfig(enabled=True))))
except main.HTTPException as exc:
    assert exc.status_code == 409
else:
    raise AssertionError("disabled workflow ran")
main.upload_workflow(main.WorkflowUploadRequest(name="disabled",workflow={"1":{"class_type":"PrimitiveStringMultiline","inputs":{"value":"test"}}}))
main.save_workflow_config("custom/disabled.json",main.WorkflowConfig(enabled=False))
try:
    main.prepare_comfy_workflow(main.GenerateRequest(type="workflow-custom", workflow_json="custom/disabled.json"))
except main.HTTPException as exc:
    assert exc.status_code == 409
else:
    raise AssertionError("canvas direct generation bypassed disabled setting")
# Dedicated local modes can still prepare their graph, independent of catalog visibility.
main.prepare_comfy_workflow(main.GenerateRequest(type="zimage", workflow_json="custom/disabled.json"))
# Historical configured workflows remain available without a new required flag.
main.save_workflow_config("builtin.json", main.WorkflowConfig(fields=[main.WorkflowField(id="f",node="1",input="text")]))
assert main.workflow_enabled("builtin.json", {"fields":[{"id":"f"}]})
assert any(item["name"] == "builtin.json" for item in main.list_workflows()["workflows"])
print("overlay-pass")
''' % str(tmp_path).replace("\\", "\\\\")
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=__import__("pathlib").Path(__file__).resolve().parents[2],
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.rstrip().endswith("overlay-pass")
