"""
Focused checks for the OPS-2A runner.

The tests build temporary app roots and never touch production data.  They cover
report generation, secret redaction, read-only data checks, release validation,
dry-run upgrade planning, and explicit backup copying into a temp directory.

Run from the repository root:

    python .\\enterprise\\tests\\test_ops_runner.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enterprise.ops.runner import history_id_for_record


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_ops(app_root: Path, *args: str, expect: int = 0) -> tuple[subprocess.CompletedProcess[str], dict]:
    cmd = [
        sys.executable,
        "-m",
        "enterprise.ops.runner",
        *args,
        "--app-root",
        str(app_root),
        "--output-dir",
        str(app_root / "ops_artifacts"),
        "--log-file",
        str(app_root / "logs" / "ops" / "jobs.jsonl"),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, env=env)
    assert result.returncode == expect, result.stderr + result.stdout
    report_path = Path(result.stdout.strip().split(": ", 1)[1])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["_report_path"] = str(report_path)
    return result, report


def create_sample_app(app_root: Path) -> dict[str, str]:
    write_text(app_root / "VERSION", "2026.07.test\n")
    write_text(app_root / "main.py", "# sample app\n")
    write_text(app_root / "enterprise" / "__init__.py", "")
    write_text(app_root / "enterprise-static" / "login.html", "<html></html>\n")
    write_text(app_root / "static" / "index.html", "<html></html>\n")
    write_text(app_root / "workflows" / "sample.json", "{}\n")
    write_text(app_root / "API" / "sample.py", "# sample api\n")
    write_text(app_root / "enterprise.env", "JWT_SECRET=super-secret-value\nADMIN_USERNAME=admin\n")
    write_text(app_root / "API" / ".env", "API_PROVIDER_CUSTOM_API_KEY=secret-key-value\n")
    write_text(app_root / "data" / "canvases" / "canvas-a.json", "{}\n")
    write_text(app_root / "data" / "canvases" / "canvas-b.json", "{}\n")
    write_text(app_root / "data" / "conversations" / "conversation-a.json", "{}\n")
    write_text(app_root / "assets" / "output" / "a.png", "image\n")
    write_text(app_root / "output" / "legacy.txt", "legacy\n")

    owned_history = {
        "type": "online",
        "timestamp": 1,
        "outputs": ["/assets/output/a.png"],
        "prompt": "owned",
        "model": "test",
    }
    missing_owner_history = {
        "type": "online",
        "timestamp": 2,
        "outputs": ["/assets/output/missing-owner.png"],
        "prompt": "missing",
        "model": "test",
    }
    write_json(app_root / "history.json", [owned_history, missing_owner_history])

    db_path = app_root / "data" / "enterprise.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE user_history_map (
                history_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL
            );
            CREATE TABLE user_canvas_map (
                user_id TEXT NOT NULL,
                canvas_id TEXT PRIMARY KEY
            );
            CREATE TABLE user_conversation_map (
                user_id TEXT NOT NULL,
                conversation_id TEXT PRIMARY KEY
            );
            CREATE TABLE user_resource_map (
                user_id TEXT NOT NULL,
                resource_url TEXT PRIMARY KEY
            );
            """
        )
        conn.execute(
            "INSERT INTO user_history_map (history_id, user_id) VALUES (?, ?)",
            (history_id_for_record(owned_history), "user-a"),
        )
        conn.execute(
            "INSERT INTO user_history_map (history_id, user_id) VALUES (?, ?)",
            ("hist_stale_owner", "user-a"),
        )
        conn.execute("INSERT INTO user_canvas_map (user_id, canvas_id) VALUES (?, ?)", ("user-a", "canvas-a"))
        conn.execute("INSERT INTO user_canvas_map (user_id, canvas_id) VALUES (?, ?)", ("user-a", "canvas-stale"))
        conn.execute(
            "INSERT INTO user_conversation_map (user_id, conversation_id) VALUES (?, ?)",
            ("user-a", "conversation-a"),
        )
        conn.execute(
            "INSERT INTO user_resource_map (user_id, resource_url) VALUES (?, ?)",
            ("user-a", "/assets/output/a.png"),
        )
        conn.execute(
            "INSERT INTO user_resource_map (user_id, resource_url) VALUES (?, ?)",
            ("user-a", "/assets/output/missing.png"),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "owned_history_id": history_id_for_record(owned_history),
        "missing_owner_history_id": history_id_for_record(missing_owner_history),
    }


def create_release(release_root: Path, forbidden: bool = False) -> None:
    write_text(release_root / "app" / "VERSION", "2026.07.test\n")
    write_text(release_root / "app" / "main.py", "# release\n")
    write_text(release_root / "app" / "enterprise" / "__init__.py", "")
    write_json(release_root / "manifest" / "release-manifest.json", {"source_commit": "abc123"})
    if forbidden:
        write_text(release_root / "app" / "assets" / "output" / "leak.png", "runtime\n")


def run_all() -> None:
    with tempfile.TemporaryDirectory(prefix="ice-ops-runner-") as raw_tmp:
        app_root = Path(raw_tmp)
        ids = create_sample_app(app_root)

        _, inventory = run_ops(app_root, "inventory")
        assert inventory["status"] == "pass"
        assert inventory["inventory"]["env_keys"]["enterprise.env"] == ["ADMIN_USERNAME", "JWT_SECRET"]
        assert "super-secret-value" not in json.dumps(inventory, ensure_ascii=False)
        assert "secret-key-value" not in json.dumps(inventory, ensure_ascii=False)

        _, data_check = run_ops(app_root, "check-data")
        assert data_check["status"] == "warn"
        assert data_check["checks"]["history"]["missing_owner_count"] == 1
        assert data_check["checks"]["history"]["owner_without_record_count"] == 1
        assert ids["missing_owner_history_id"] in data_check["checks"]["history"]["missing_owner_samples"]
        assert data_check["checks"]["canvases"]["files_without_owner_count"] == 1
        assert data_check["checks"]["canvases"]["owners_without_file_count"] == 1
        assert data_check["checks"]["resources"]["missing_file_count"] == 1

        _, dry_backup = run_ops(
            app_root,
            "backup",
            "--backup-root",
            str(app_root.parent / "backups"),
        )
        assert dry_backup["dry_run"] is True
        assert not Path(dry_backup["backup_dir"]).exists()
        assert "super-secret-value" not in json.dumps(dry_backup, ensure_ascii=False)

        api_env_path = app_root / "API" / ".env"
        api_env_path.unlink()
        _, missing_api_env_backup = run_ops(
            app_root,
            "backup",
            "--backup-root",
            str(app_root.parent / "backups"),
        )
        assert missing_api_env_backup["status"] == "warn"
        assert "API/.env missing" in missing_api_env_backup["warnings"]
        sensitive_files = {item["path"]: item for item in missing_api_env_backup["sensitive_files"]}
        assert sensitive_files["API/.env"]["exists"] is False
        assert sensitive_files["API/.env"]["env_keys"] == []
        write_text(api_env_path, "API_PROVIDER_CUSTOM_API_KEY=secret-key-value\n")

        live_conn = sqlite3.connect(app_root / "data" / "enterprise.db")
        try:
            live_conn.execute("PRAGMA journal_mode=WAL")
            live_conn.execute(
                "CREATE TABLE IF NOT EXISTS ops_backup_probe (id INTEGER PRIMARY KEY, value TEXT)"
            )
            live_conn.execute("INSERT INTO ops_backup_probe (value) VALUES (?)", ("wal-backed-commit",))
            live_conn.commit()

            _, executed_backup = run_ops(
                app_root,
                "backup",
                "--backup-root",
                str(app_root.parent / "backups"),
                "--execute",
            )
        finally:
            live_conn.close()
        assert executed_backup["dry_run"] is False
        assert executed_backup["status"] == "pass"
        assert executed_backup["sqlite_backup_method"] == "sqlite3.Connection.backup"
        assert executed_backup["sqlite_backup_status"] == "success"
        backup_dir = Path(executed_backup["backup_dir"])
        backup_db = backup_dir / "app" / "data" / "enterprise.db"
        assert (backup_dir / "app" / "history.json").exists()
        assert (backup_dir / "app" / "API" / ".env").exists()
        assert backup_db.exists()
        assert not (backup_dir / "app" / "data" / "enterprise.db-wal").exists()
        assert not (backup_dir / "app" / "data" / "enterprise.db-shm").exists()
        assert (backup_dir / "backup-manifest.json").exists()
        with sqlite3.connect(backup_db) as backup_conn:
            row = backup_conn.execute(
                "SELECT value FROM ops_backup_probe ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert row and row[0] == "wal-backed-commit"

        bad_sqlite_root = app_root.parent / "bad-sqlite-app"
        write_text(bad_sqlite_root / "enterprise.env", "JWT_SECRET=bad\n")
        write_text(bad_sqlite_root / "API" / ".env", "API_PROVIDER_CUSTOM_API_KEY=bad\n")
        write_text(bad_sqlite_root / "data" / "enterprise.db", "not a sqlite database\n")
        _, failed_sqlite_backup = run_ops(
            bad_sqlite_root,
            "backup",
            "--backup-root",
            str(app_root.parent / "bad-sqlite-backups"),
            "--execute",
            expect=2,
        )
        assert failed_sqlite_backup["status"] == "fail"
        assert failed_sqlite_backup["sqlite_backup_method"] == "sqlite3.Connection.backup"
        assert failed_sqlite_backup["sqlite_backup_status"] == "failed"
        assert Path(failed_sqlite_backup["_report_path"]).exists()

        bad_release = app_root.parent / "bad-release"
        create_release(bad_release, forbidden=True)
        _, release_report = run_ops(app_root, "validate-release", "--release", str(bad_release), expect=2)
        assert release_report["status"] == "fail"
        assert release_report["forbidden_path_count"] == 1

        wrapped_release = app_root.parent / "wrapped-release"
        write_text(wrapped_release / "Infinite-Canvas-Enterprise" / "data" / "enterprise.db", "db")
        write_text(wrapped_release / "Infinite-Canvas-Enterprise" / "assets" / "output" / "a.png", "image")
        write_text(wrapped_release / "release-root" / "app" / "history.json", "[]")
        write_text(wrapped_release / "some-wrapper" / "API" / ".env", "SECRET=value\n")
        _, wrapped_report = run_ops(app_root, "validate-release", "--release", str(wrapped_release), expect=2)
        assert wrapped_report["status"] == "fail"
        assert wrapped_report["forbidden_path_count"] == 4

        unsafe_zip = app_root.parent / "unsafe-release.zip"
        with zipfile.ZipFile(unsafe_zip, "w") as archive:
            archive.writestr("../data/enterprise.db", "unsafe")
        _, unsafe_report = run_ops(app_root, "validate-release", "--release", str(unsafe_zip), expect=2)
        assert unsafe_report["status"] == "fail"
        assert unsafe_report["forbidden_path_count"] == 1

        windows_unsafe_zip = app_root.parent / "windows-unsafe-release.zip"
        with zipfile.ZipFile(windows_unsafe_zip, "w") as archive:
            archive.writestr("C:/release/main.py", "unsafe")
            archive.writestr("D:\\release\\main.py", "unsafe")
            archive.writestr("\\\\server\\share\\main-backslash.py", "unsafe")
            archive.writestr("//server/share/main-slash.py", "unsafe")
        _, windows_unsafe_report = run_ops(
            app_root,
            "validate-release",
            "--release",
            str(windows_unsafe_zip),
            expect=2,
        )
        assert windows_unsafe_report["status"] == "fail"
        assert windows_unsafe_report["forbidden_path_count"] == 4

        good_release = app_root.parent / "good-release"
        create_release(good_release, forbidden=False)
        _, upgrade_plan = run_ops(
            app_root,
            "prepare-upgrade",
            "--release",
            str(good_release),
            "--backup-manifest",
            dry_backup["_report_path"],
            "--data-check-report",
            data_check["_report_path"],
            "--target-commit",
            "target-commit",
            "--maintenance-window",
            "03:00-05:00",
            expect=2,
        )
        assert upgrade_plan["status"] == "blocked"
        assert any("dry-run" in blocker for blocker in upgrade_plan["blockers"])
        assert any(step["phase"] == "rollback-decision" for step in upgrade_plan["steps"])
        assert all("No " in item for item in upgrade_plan["not_executed"])

        log_path = app_root / "logs" / "ops" / "jobs.jsonl"
        assert log_path.exists()
        logs = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        assert any(item["event"] == "started" and item["command"] == "inventory" for item in logs)
        assert any(item["event"] == "finished" and item["command"] == "prepare-upgrade" for item in logs)


if __name__ == "__main__":
    run_all()
    print("ops runner checks passed")
