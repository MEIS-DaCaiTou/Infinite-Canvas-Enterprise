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
import asyncio
import json
from pathlib import Path
from PIL import Image
from enterprise.paths import (
    PortableRootInputs, derive_portable_path_roots, install_path_roots_for_process,
    prepare_application_directories, prepare_install_state_directories,
    prepare_ops_directories, prepare_runtime_directories,
)
install = Path(r'''%s''')
local = Path(r'''%s''')
roots = derive_portable_path_roots(PortableRootInputs(install, local), 'release-A')
install_path_roots_for_process(roots)
prepare_application_directories(roots)
prepare_install_state_directories(roots)
prepare_ops_directories(roots)
prepare_runtime_directories(roots)
import main
asyncio.run(main.startup_event())
main.save_canvas({'id': 'canvas-1', 'nodes': []})
conversation = main.new_conversation('user-1', 'fixture conversation')
main.save_to_history({'id': 'history-1', 'type': 'fixture'})
input_path = Path(main.OUTPUT_INPUT_DIR) / 'fixture.png'
input_path.parent.mkdir(parents=True, exist_ok=True)
Image.new('RGB', (4, 4), (0, 128, 255)).save(input_path)
output_path = Path(main.OUTPUT_DIR) / 'fixture-output.txt'
output_path.write_text('isolated output fixture', encoding='utf-8')
asyncio.run(main.media_preview('/assets/input/fixture.png', 64))
from enterprise import db
connection = db.get_db()
connection.execute('CREATE TABLE IF NOT EXISTS integration_fixture (id INTEGER PRIMARY KEY)')
connection.commit()
db_sidecars = [str(path) for path in Path(db.DB_PATH).parent.glob(Path(db.DB_PATH).name + '*') if path.is_file()]
connection.close()
from enterprise.runtime.logging import RuntimeLogs
runtime_logs = RuntimeLogs(roots.LOG_ROOT / 'runtime')
runtime_logs.write('gateway.stdout.log', 'integration_fixture_log')
from enterprise.ops import runner
report_dir = roots.STAGING_ROOT / 'reports'
log_file = roots.LOG_ROOT / 'ops' / 'integration.jsonl'
assert runner.main(['inventory', '--app-root', str(roots.APP_ROOT), '--output-dir', str(report_dir), '--log-file', str(log_file), '--job-id', 'integration-inventory']) == 0
backup_dir = roots.BACKUP_ROOT / 'integration-backup'
backup = runner.backup_sqlite_database(Path(db.DB_PATH), backup_dir / 'enterprise.db', source_database_relative_path='data/enterprise.db')
assert backup['sqlite_backup_status'] == 'success'
runner.write_json(backup_dir / 'backup-manifest.json', {'kind': 'integration-backup-fixture', **backup})
print(json.dumps({
  'base': main.BASE_DIR, 'history': main.HISTORY_FILE, 'assets': main.ASSETS_DIR,
  'static': main.STATIC_DIR, 'workflow': main.WORKFLOW_DIR,
  'canvas': main.canvas_path('canvas-1'),
  'conversation': main.conversation_path('user-1', conversation['id']),
  'input': str(input_path), 'output': str(output_path), 'preview': main.MEDIA_PREVIEW_DIR,
  'database': db.DB_PATH, 'db_sidecars': db_sidecars, 'report_dir': str(report_dir), 'backup_root': str(roots.BACKUP_ROOT),
  'runtime_log_dir': str(roots.LOG_ROOT / 'runtime'), 'runtime_root': str(roots.RUNTIME_ROOT),
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
    assert Path(payload["canvas"]).is_file()
    assert Path(payload["conversation"]).is_file()
    assert Path(payload["history"]).is_file()
    assert Path(payload["input"]).is_file()
    assert Path(payload["output"]).is_file()
    assert any(Path(payload["preview"]).iterdir())
    assert Path(payload["database"]).is_file()
    assert payload["db_sidecars"]
    assert all(Path(path).parent == Path(payload["database"]).parent for path in payload["db_sidecars"])
    assert any(Path(payload["report_dir"]).glob("*.json"))
    assert (Path(payload["backup_root"]) / "integration-backup" / "backup-manifest.json").is_file()
    assert any(Path(payload["runtime_log_dir"]).glob("*.log"))
    assert not Path(payload["runtime_root"]).is_relative_to(Path(payload["runtime_log_dir"]))
    assert sorted(path.relative_to(app).as_posix() for path in app.rglob("*") if path.is_file()) == ["main.py", "workflows/shipped.json"]
    assert tree_digest(app) == app_before
    assert tree_digest(app / "static") == static_before
    assert tree_digest(app / "workflows") == workflows_before
