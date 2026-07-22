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
import json
from pathlib import Path
from enterprise.paths import derive_development_path_roots, install_path_roots_for_process
install_path_roots_for_process(derive_development_path_roots(Path.cwd()))
import main
root = Path(r"""%s""")
shipped, user = root / "shipped", root / "user"
shipped.mkdir(parents=True)
user.mkdir()
(shipped / "builtin.json").write_text(json.dumps({"source": "shipped"}), encoding="utf-8")
main.SHIPPED_WORKFLOW_DIR, main.WORKFLOW_DIR = str(shipped), str(user)
listed = main.list_workflows()["workflows"]
assert listed == [{"name": "builtin.json", "title": "builtin", "builtin": True, "field_count": 0}]
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
