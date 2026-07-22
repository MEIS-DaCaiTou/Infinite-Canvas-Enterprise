from __future__ import annotations

import json
import os
import subprocess
import sys
import hashlib
from pathlib import Path


def tree_digest(root: Path) -> str:
    records = []
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.relative_to(root).as_posix()):
        records.append(f"{path.relative_to(root).as_posix()}:{hashlib.sha256(path.read_bytes()).hexdigest()}")
    return hashlib.sha256("\n".join(records).encode("utf-8")).hexdigest()


def test_portable_roots_are_installed_before_main_import_and_keep_app_root_clean(tmp_path: Path):
    install = tmp_path / "安装 空格"
    app = install / "releases" / "release-A"
    (app / "static").mkdir(parents=True)
    (app / "main.py").write_text("# layout marker\n", encoding="utf-8")
    (app / "workflows").mkdir()
    (app / "workflows" / "shipped.json").write_text("{}\n", encoding="utf-8")
    app_before = tree_digest(app)
    static_before = tree_digest(app / "static")
    workflows_before = tree_digest(app / "workflows")
    script = """
import json
from pathlib import Path
from enterprise.paths import PortableRootInputs, derive_portable_path_roots, install_path_roots_for_process, prepare_application_directories
install = Path(r'''%s''')
local = Path(r'''%s''')
roots = derive_portable_path_roots(PortableRootInputs(install, local), 'release-A')
install_path_roots_for_process(roots)
prepare_application_directories(roots)
import main
print(json.dumps({
  'base': main.BASE_DIR, 'history': main.HISTORY_FILE, 'assets': main.ASSETS_DIR,
  'static': main.STATIC_DIR, 'workflow': main.WORKFLOW_DIR,
}))
""" % (str(install), str(tmp_path / "local"))
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[2], env=env,
        capture_output=True, text=True, check=True,
    )
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["base"].endswith("releases\\release-A")
    assert "\\data\\history.json" in payload["history"]
    assert "\\data\\uploads\\assets" in payload["assets"]
    assert payload["static"].endswith("releases\\release-A\\static")
    assert payload["workflow"].endswith("\\data\\workflows")
    assert sorted(path.relative_to(app).as_posix() for path in app.rglob("*") if path.is_file()) == ["main.py", "workflows/shipped.json"]
    assert tree_digest(app) == app_before
    assert tree_digest(app / "static") == static_before
    assert tree_digest(app / "workflows") == workflows_before
