"""OPS-2A command runner.

This module is intentionally standalone and standard-library only.  It creates
read-only inventory and data-check reports, validates offline release packages,
prepares upgrade plans, and can copy a pre-upgrade backup when explicitly asked
to execute.

Run from the repository root:

    python -m enterprise.ops.runner inventory
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

# The OPS runner is intentionally supported as a directly executed file.
if __package__ in {None, ""}:
    _REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
    if str(_REPOSITORY_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPOSITORY_ROOT))

from enterprise.ops.release_validation import validate_release
from enterprise.ops.update.errors import OnlineUpdateError
from enterprise.ops.update.providers import GitHubReleasesProvider, LocalFixtureProvider
from enterprise.ops.update.service import OnlineUpdateService


DEFAULT_ARTIFACT_DIR = "ops_artifacts"
DEFAULT_BACKUP_DIR = "ops_backups"
DEFAULT_LOG_FILE = "logs/ops/jobs.jsonl"
SAMPLE_LIMIT = 20

CRITICAL_RUNTIME_PATHS = (
    "data",
    "assets",
    "output",
    "history.json",
    "data/enterprise.db",
    "enterprise.env",
    "API/.env",
)

REQUIRED_ENV_FILES = (
    "enterprise.env",
    "API/.env",
)

BACKUP_ITEMS = (
    "VERSION",
    "main.py",
    "enterprise",
    "enterprise-static",
    "static",
    "workflows",
    "API",
    "data",
    "assets",
    "output",
    "history.json",
    "enterprise.env",
    "启动企业版.bat",
)

BACKUP_IGNORE_NAMES = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    "ops_artifacts",
    "ops_backups",
    "logs",
}

SQLITE_BACKUP_METHOD = "sqlite3.Connection.backup"
SQLITE_RUNTIME_NAMES = {"enterprise.db", "enterprise.db-wal", "enterprise.db-shm"}

def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def compact_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def make_job_id(command: str) -> str:
    return f"{command}-{compact_timestamp()}-{uuid.uuid4().hex[:8]}"


def resolve_path(app_root: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return app_root / path


def rel_posix(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def safe_sample(values: list[str] | set[str], limit: int = SAMPLE_LIMIT) -> list[str]:
    return sorted(values)[:limit]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json_file(path: Path) -> tuple[Any | None, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as exc:
        return None, str(exc)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


class OpsJobLogger:
    def __init__(self, log_file: Path, job_id: str, command: str, operator: str | None = None):
        self.log_file = log_file
        self.job_id = job_id
        self.command = command
        self.operator = operator or ""

    def event(self, event: str, **details: Any) -> None:
        payload: dict[str, Any] = {
            "ts": utc_now(),
            "job_id": self.job_id,
            "command": self.command,
            "event": event,
        }
        if self.operator:
            payload["operator"] = self.operator
        if details:
            payload["details"] = details
        append_jsonl(self.log_file, payload)


def iter_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    if path.is_file():
        return [path]
    return [child for child in path.rglob("*") if child.is_file()]


def path_summary(root: Path, rel_path: str) -> dict[str, Any]:
    path = root / rel_path
    files = iter_files(path)
    size = 0
    for file_path in files:
        try:
            size += file_path.stat().st_size
        except OSError:
            pass
    return {
        "path": rel_path,
        "exists": path.exists(),
        "kind": "directory" if path.is_dir() else "file" if path.is_file() else "missing",
        "file_count": len(files),
        "total_bytes": size,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_git(app_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=app_root,
        text=True,
        capture_output=True,
        check=True,
        timeout=20,
    )
    return result.stdout.strip()


def collect_git_summary(app_root: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {"available": False}
    try:
        branch = run_git(app_root, "branch", "--show-current")
        commit = run_git(app_root, "rev-parse", "HEAD")
        status_lines = run_git(app_root, "status", "--porcelain", "--untracked-files=all").splitlines()
        summary.update(
            {
                "available": True,
                "branch": branch,
                "commit": commit,
                "dirty_count": len(status_lines),
                "dirty_runtime_count": sum(1 for line in status_lines if is_runtime_git_status_line(line)),
            }
        )
    except Exception as exc:
        summary["error"] = str(exc)
    return summary


def is_runtime_git_status_line(line: str) -> bool:
    path = line[3:].replace("\\", "/") if len(line) > 3 else line.replace("\\", "/")
    runtime_prefixes = ("assets/", "output/", "data/", "logs/", "ops_artifacts/", "ops_backups/")
    runtime_exact = {"history.json", "enterprise.env", "API/.env"}
    return path in runtime_exact or path.startswith(runtime_prefixes)


def read_version(app_root: Path) -> str | None:
    version_path = app_root / "VERSION"
    if not version_path.exists():
        return None
    return version_path.read_text(encoding="utf-8", errors="replace").strip()


def read_env_keys(path: Path) -> list[str]:
    if not path.exists() or not path.is_file():
        return []
    keys: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key:
            keys.append(key)
    return sorted(dict.fromkeys(keys))


def sqlite_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro"


def sqlite_connect_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(sqlite_uri(path), uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def sqlite_table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").fetchall()
    return [str(row[0]) for row in rows]


def sqlite_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({quote_ident(table)})").fetchall()
    except sqlite3.Error:
        return set()
    return {str(row[1]) for row in rows}


def quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def sqlite_count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {quote_ident(table)}").fetchone()[0])


def collect_sqlite_summary(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {"exists": False, "tables": {}, "error": "database file missing"}
    try:
        with sqlite_connect_readonly(db_path) as conn:
            tables = sqlite_table_names(conn)
            return {
                "exists": True,
                "path": db_path.as_posix(),
                "tables": {table: sqlite_count(conn, table) for table in tables},
                "schema_tables": tables,
            }
    except Exception as exc:
        return {"exists": True, "tables": {}, "error": str(exc)}


def load_history_records(history_path: Path) -> tuple[list[dict[str, Any]], str | None]:
    if not history_path.exists():
        return [], "history.json missing"
    data, error = read_json_file(history_path)
    if error:
        return [], error
    if isinstance(data, list):
        raw_records = data
    elif isinstance(data, dict):
        raw_records = data.get("history") or data.get("items") or data.get("records") or []
    else:
        raw_records = []
    records = [record for record in raw_records if isinstance(record, dict)]
    return records, None


def normalize_resource_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        path = parsed.path
    else:
        path = text
    path = unquote(path).replace("\\", "/")
    if not path.startswith("/"):
        path = "/" + path
    if path.startswith("/assets/") or path.startswith("/output/"):
        return path
    return ""


def is_protected_resource(value: str) -> bool:
    return value.startswith("/assets/") or value.startswith("/output/")


def history_resource_urls(record: Any, found: list[str] | None = None) -> list[str]:
    found = found if found is not None else []
    if isinstance(record, str):
        resource_url = normalize_resource_url(record)
        if is_protected_resource(resource_url) and resource_url not in found:
            found.append(resource_url)
    elif isinstance(record, dict):
        for child in record.values():
            history_resource_urls(child, found)
    elif isinstance(record, list):
        for child in record:
            history_resource_urls(child, found)
    return found


def history_timestamp_key(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.6f}"
    text = str(value or "").strip()
    try:
        return f"{float(text):.6f}"
    except Exception:
        return text


def history_id_for_record(record: dict[str, Any]) -> str:
    urls = history_resource_urls(record)
    identity = {
        "type": str(record.get("type") or "zimage"),
        "timestamp": history_timestamp_key(record.get("timestamp")),
        "resource_url": urls[0] if urls else "",
        "task_id": str(record.get("task_id") or ""),
        "request_id": str(record.get("request_id") or ""),
        "prompt_id": str(record.get("prompt_id") or ""),
        "prompt": str(record.get("prompt") or ""),
        "model": str(record.get("model") or ""),
    }
    raw = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "hist_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def history_summary(app_root: Path) -> dict[str, Any]:
    records, error = load_history_records(app_root / "history.json")
    type_counts = Counter(str(record.get("type") or "zimage") for record in records)
    return {
        "exists": (app_root / "history.json").exists(),
        "record_count": len(records),
        "type_counts": dict(sorted(type_counts.items())),
        "error": error,
    }


def fetch_column_values(conn: sqlite3.Connection, table: str, column: str) -> set[str]:
    tables = set(sqlite_table_names(conn))
    if table not in tables or column not in sqlite_columns(conn, table):
        return set()
    rows = conn.execute(f"SELECT {quote_ident(column)} FROM {quote_ident(table)}").fetchall()
    return {str(row[0]) for row in rows if row[0] is not None and str(row[0]).strip()}


def file_stems(path: Path, suffix: str = ".json") -> set[str]:
    if not path.exists() or not path.is_dir():
        return set()
    return {child.stem for child in path.glob(f"*{suffix}") if child.is_file()}


def resource_url_to_path(app_root: Path, resource_url: str) -> Path | None:
    text = str(resource_url or "").strip()
    if not text:
        return None
    parsed = urlparse(text)
    query = parse_qs(parsed.query)
    path = unquote(parsed.path or text).replace("\\", "/")
    if path in {"/api/view", "/api/download-output", "/api/media-preview"}:
        for key in ("path", "file", "filename", "url"):
            if query.get(key):
                path = unquote(query[key][0]).replace("\\", "/")
                break
    if not path.startswith("/"):
        path = "/" + path
    if path.startswith("/assets/") or path.startswith("/output/"):
        return app_root / path.lstrip("/")
    return None


def collect_inventory(app_root: Path) -> dict[str, Any]:
    env_files = {
        "enterprise.env": read_env_keys(app_root / "enterprise.env"),
        "API/.env": read_env_keys(app_root / "API" / ".env"),
    }
    paths = {rel_path: path_summary(app_root, rel_path) for rel_path in CRITICAL_RUNTIME_PATHS}
    return {
        "generated_at": utc_now(),
        "app_root": app_root.as_posix(),
        "version": read_version(app_root),
        "git": collect_git_summary(app_root),
        "paths": paths,
        "env_keys": env_files,
        "sqlite": collect_sqlite_summary(app_root / "data" / "enterprise.db"),
        "history": history_summary(app_root),
    }


def command_inventory(args: argparse.Namespace, job_id: str, logger: OpsJobLogger) -> dict[str, Any]:
    app_root = args.app_root.resolve()
    output_dir = resolve_path(app_root, args.output_dir)
    report = {
        "kind": "inventory-report",
        "job_id": job_id,
        "status": "pass",
        "inventory": collect_inventory(app_root),
    }
    report_path = output_dir / f"inventory-{job_id}.json"
    write_json(report_path, report)
    logger.event("report_written", report_path=report_path.as_posix())
    report["_report_path"] = report_path.as_posix()
    return report


def command_check_data(args: argparse.Namespace, job_id: str, logger: OpsJobLogger) -> dict[str, Any]:
    app_root = args.app_root.resolve()
    output_dir = resolve_path(app_root, args.output_dir)
    critical: list[str] = []
    warnings: list[str] = []

    db_path = app_root / "data" / "enterprise.db"
    history_records, history_error = load_history_records(app_root / "history.json")
    if history_error:
        critical.append(f"history.json could not be read: {history_error}")
    if not db_path.exists():
        critical.append("data/enterprise.db missing")

    result: dict[str, Any] = {
        "critical_paths": {rel_path: path_summary(app_root, rel_path) for rel_path in CRITICAL_RUNTIME_PATHS},
        "history": {
            "record_count": len(history_records),
            "missing_owner_count": 0,
            "owner_without_record_count": 0,
            "missing_owner_samples": [],
            "owner_without_record_samples": [],
        },
        "canvases": {},
        "conversations": {},
        "resources": {},
    }

    for rel_path, summary in result["critical_paths"].items():
        if rel_path in {"history.json", "data/enterprise.db"} and not summary["exists"]:
            critical.append(f"{rel_path} missing")
        elif not summary["exists"]:
            warnings.append(f"{rel_path} missing")

    if db_path.exists():
        try:
            with sqlite_connect_readonly(db_path) as conn:
                history_ids = {history_id_for_record(record) for record in history_records}
                mapped_history_ids = fetch_column_values(conn, "user_history_map", "history_id")
                history_missing_owner = history_ids - mapped_history_ids
                history_owner_without_record = mapped_history_ids - history_ids
                if history_missing_owner:
                    warnings.append(f"{len(history_missing_owner)} history records have no user_history_map owner")
                if history_owner_without_record:
                    warnings.append(f"{len(history_owner_without_record)} user_history_map rows have no history.json record")
                result["history"].update(
                    {
                        "mapped_owner_count": len(mapped_history_ids),
                        "computed_history_id_count": len(history_ids),
                        "missing_owner_count": len(history_missing_owner),
                        "owner_without_record_count": len(history_owner_without_record),
                        "missing_owner_samples": safe_sample(history_missing_owner),
                        "owner_without_record_samples": safe_sample(history_owner_without_record),
                    }
                )

                result["canvases"] = compare_file_ids_to_owner_map(
                    app_root,
                    conn,
                    "data/canvases",
                    "user_canvas_map",
                    "canvas_id",
                    warnings,
                )
                result["conversations"] = compare_file_ids_to_owner_map(
                    app_root,
                    conn,
                    "data/conversations",
                    "user_conversation_map",
                    "conversation_id",
                    warnings,
                )
                result["resources"] = compare_resources(app_root, conn, warnings)
        except Exception as exc:
            critical.append(f"enterprise.db could not be read: {exc}")

    status = "fail" if critical else "warn" if warnings else "pass"
    report = {
        "kind": "data-check-report",
        "job_id": job_id,
        "status": status,
        "generated_at": utc_now(),
        "app_root": app_root.as_posix(),
        "findings": {"critical": critical, "warnings": warnings},
        "checks": result,
        "note": "Read-only report. No owner map, runtime file, database, or history data was modified.",
    }
    report_path = output_dir / f"data-check-{job_id}.json"
    write_json(report_path, report)
    logger.event("report_written", report_path=report_path.as_posix(), status=status)
    report["_report_path"] = report_path.as_posix()
    return report


def compare_file_ids_to_owner_map(
    app_root: Path,
    conn: sqlite3.Connection,
    rel_dir: str,
    table: str,
    column: str,
    warnings: list[str],
) -> dict[str, Any]:
    filesystem_ids = file_stems(app_root / rel_dir)
    mapped_ids = fetch_column_values(conn, table, column)
    files_without_owner = filesystem_ids - mapped_ids
    owners_without_file = mapped_ids - filesystem_ids
    if files_without_owner:
        warnings.append(f"{len(files_without_owner)} {rel_dir} files have no {table} owner")
    if owners_without_file:
        warnings.append(f"{len(owners_without_file)} {table} rows have no file in {rel_dir}")
    return {
        "file_count": len(filesystem_ids),
        "mapped_owner_count": len(mapped_ids),
        "files_without_owner_count": len(files_without_owner),
        "owners_without_file_count": len(owners_without_file),
        "files_without_owner_samples": safe_sample(files_without_owner),
        "owners_without_file_samples": safe_sample(owners_without_file),
    }


def compare_resources(app_root: Path, conn: sqlite3.Connection, warnings: list[str]) -> dict[str, Any]:
    resource_urls = fetch_column_values(conn, "user_resource_map", "resource_url")
    missing_files: set[str] = set()
    unresolvable_urls: set[str] = set()
    existing_files = 0
    for resource_url in resource_urls:
        path = resource_url_to_path(app_root, resource_url)
        if path is None:
            unresolvable_urls.add(resource_url)
            continue
        if path.exists():
            existing_files += 1
        else:
            missing_files.add(resource_url)
    if missing_files:
        warnings.append(f"{len(missing_files)} user_resource_map URLs point to missing local files")
    if unresolvable_urls:
        warnings.append(f"{len(unresolvable_urls)} user_resource_map URLs could not be mapped to local files")
    return {
        "mapped_resource_count": len(resource_urls),
        "existing_file_count": existing_files,
        "missing_file_count": len(missing_files),
        "unresolvable_url_count": len(unresolvable_urls),
        "missing_file_samples": safe_sample(missing_files),
        "unresolvable_url_samples": safe_sample(unresolvable_urls),
    }


def command_backup(args: argparse.Namespace, job_id: str, logger: OpsJobLogger) -> dict[str, Any]:
    app_root = args.app_root.resolve()
    output_dir = resolve_path(app_root, args.output_dir)
    backup_root = resolve_path(app_root, args.backup_root)
    backup_id = args.backup_id or f"{args.backup_type}-{compact_timestamp()}-{uuid.uuid4().hex[:8]}"
    backup_dir = backup_root / backup_id
    item_summaries = [backup_item_summary(app_root, rel_path) for rel_path in BACKUP_ITEMS]
    env_summaries = [env_file_summary(app_root, rel_path) for rel_path in REQUIRED_ENV_FILES]
    missing = [item["path"] for item in item_summaries if item["required"] and not item["exists"]]
    missing.extend(item["path"] for item in env_summaries if item["required"] and not item["exists"])
    warnings = sorted({f"{path} missing" for path in missing})
    dry_run = not args.execute
    sqlite_backup_path = backup_dir / "app" / "data" / "enterprise.db"
    sqlite_backup: dict[str, Any] = {
        "sqlite_backup_method": SQLITE_BACKUP_METHOD,
        "sqlite_backup_status": "dry-run" if dry_run else "pending",
        "sqlite_backup_path": sqlite_backup_path.as_posix(),
    }

    manifest: dict[str, Any] = {
        "kind": "backup-manifest",
        "job_id": job_id,
        "backup_id": backup_id,
        "backup_type": args.backup_type,
        "status": "warn" if warnings else "pass",
        "dry_run": dry_run,
        "generated_at": utc_now(),
        "app_root": app_root.as_posix(),
        "backup_root": backup_root.as_posix(),
        "backup_dir": backup_dir.as_posix(),
        "git": collect_git_summary(app_root),
        "version": read_version(app_root),
        "items": item_summaries,
        "sensitive_files": env_summaries,
        **sqlite_backup,
        "warnings": warnings,
        "note": "Manifest records env key names only. Env values and secrets are not written to the manifest.",
    }

    if args.execute:
        if backup_dir.exists():
            raise RuntimeError(f"backup directory already exists: {backup_dir}")
        logger.event("copy_started", backup_dir=backup_dir.as_posix())
        copy_backup_items(app_root, backup_dir)
        logger.event("sqlite_backup_started", sqlite_backup_path=sqlite_backup_path.as_posix())
        sqlite_backup = backup_sqlite_database(
            app_root / "data" / "enterprise.db",
            sqlite_backup_path,
            source_database_relative_path="data/enterprise.db",
        )
        manifest.update(sqlite_backup)
        if sqlite_backup["sqlite_backup_status"] == "failed":
            manifest["status"] = "fail"
        logger.event(
            "sqlite_backup_finished",
            status=sqlite_backup["sqlite_backup_status"],
            sqlite_backup_path=sqlite_backup_path.as_posix(),
        )
        manifest["copied_at"] = utc_now()
        manifest["dry_run"] = False
        manifest_path = backup_dir / "backup-manifest.json"
    else:
        manifest_path = output_dir / f"backup-manifest-{job_id}.json"

    write_json(manifest_path, manifest)
    logger.event(
        "manifest_written",
        manifest_path=manifest_path.as_posix(),
        dry_run=dry_run,
        status=manifest["status"],
    )
    manifest["_report_path"] = manifest_path.as_posix()
    return manifest


def backup_item_summary(app_root: Path, rel_path: str) -> dict[str, Any]:
    summary = path_summary(app_root, rel_path)
    required = rel_path in CRITICAL_RUNTIME_PATHS or rel_path in {"enterprise.env"}
    if summary["kind"] == "file" and summary["exists"]:
        try:
            summary["sha256"] = sha256_file(app_root / rel_path)
        except OSError:
            summary["sha256"] = ""
    summary["required"] = required
    return summary


def env_file_summary(app_root: Path, rel_path: str) -> dict[str, Any]:
    path = app_root / rel_path
    return {
        "path": rel_path,
        "exists": path.exists() and path.is_file(),
        "required": True,
        "env_keys": read_env_keys(path),
    }


def copy_backup_items(app_root: Path, backup_dir: Path) -> None:
    target_root = backup_dir / "app"
    for rel_path in BACKUP_ITEMS:
        src = app_root / rel_path
        if not src.exists():
            continue
        dst = target_root / rel_path
        if src.is_dir():
            shutil.copytree(src, dst, ignore=backup_ignore)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def backup_ignore(dir_path: str, names: list[str]) -> set[str]:
    ignored = {name for name in names if name in BACKUP_IGNORE_NAMES}
    if Path(dir_path).name == "data":
        ignored.update(name for name in names if name in SQLITE_RUNTIME_NAMES)
    if Path(dir_path).name == "API":
        # Keep API/.env in production backups; it is a critical restore file.
        ignored.discard(".env")
    return ignored


def backup_sqlite_database(
    source_path: Path,
    destination_path: Path,
    *,
    source_database_relative_path: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "sqlite_backup_method": SQLITE_BACKUP_METHOD,
        "sqlite_backup_status": "pending",
        "sqlite_backup_path": destination_path.as_posix(),
    }
    if not source_path.exists():
        result["sqlite_backup_status"] = "failed"
        result["sqlite_backup_error"] = "source database missing"
        return result

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if destination_path.exists():
            destination_path.unlink()
        with sqlite_connect_readonly(source_path) as source_conn:
            journal_mode_row = source_conn.execute("PRAGMA main.journal_mode").fetchone()
            if not journal_mode_row or not isinstance(journal_mode_row[0], str):
                raise RuntimeError("source database journal mode could not be inspected")
            source_fingerprint = {
                "source_database_relative_path": source_database_relative_path,
                "source_database_size_bytes": source_path.stat().st_size,
                "source_database_sha256": sha256_file(source_path),
                "source_database_journal_mode": journal_mode_row[0].casefold(),
            }
            with sqlite3.connect(destination_path) as destination_conn:
                source_conn.backup(destination_conn)
        result["sqlite_backup_status"] = "success"
        try:
            result["sqlite_backup_size_bytes"] = destination_path.stat().st_size
            result["sqlite_backup_sha256"] = sha256_file(destination_path)
            result.update(source_fingerprint)
        except OSError:
            pass
    except Exception as exc:
        result["sqlite_backup_status"] = "failed"
        result["sqlite_backup_error"] = str(exc)
    return result


def command_validate_release(args: argparse.Namespace, job_id: str, logger: OpsJobLogger) -> dict[str, Any]:
    app_root = args.app_root.resolve()
    output_dir = resolve_path(app_root, args.output_dir)
    release_path = resolve_path(app_root, args.release)
    report = validate_release(release_path, job_id)
    report["app_root"] = app_root.as_posix()
    report_path = output_dir / f"release-validation-{job_id}.json"
    write_json(report_path, report)
    logger.event("report_written", report_path=report_path.as_posix(), status=report["status"])
    report["_report_path"] = report_path.as_posix()
    return report


def command_prepare_upgrade(args: argparse.Namespace, job_id: str, logger: OpsJobLogger) -> dict[str, Any]:
    app_root = args.app_root.resolve()
    output_dir = resolve_path(app_root, args.output_dir)
    blockers: list[str] = []
    warnings: list[str] = []
    inputs: dict[str, Any] = {}

    release_report = None
    if args.release:
        release_report = validate_release(resolve_path(app_root, args.release), job_id)
        inputs["release_validation"] = summarize_report_input(release_report)
        if release_report["status"] == "fail":
            blockers.extend(release_report["findings"]["critical"])
        elif release_report["status"] == "warn":
            warnings.extend(release_report["findings"]["warnings"])
    else:
        blockers.append("release path not provided")

    if args.backup_manifest:
        backup_manifest_path = resolve_path(app_root, args.backup_manifest)
        backup_manifest, error = read_json_file(backup_manifest_path)
        if error or not isinstance(backup_manifest, dict):
            blockers.append(f"backup manifest could not be read: {error}")
        else:
            backup_manifest["_report_path"] = backup_manifest_path.as_posix()
            inputs["backup_manifest"] = summarize_report_input(backup_manifest)
            if backup_manifest.get("dry_run"):
                blockers.append("backup manifest is dry-run; execute backup before production upgrade")
            if backup_manifest.get("status") == "fail":
                blockers.append("backup manifest status is fail")
            elif backup_manifest.get("status") == "warn":
                warnings.extend(str(item) for item in backup_manifest.get("warnings", []))
    else:
        blockers.append("backup manifest not provided")

    if args.data_check_report:
        data_check_path = resolve_path(app_root, args.data_check_report)
        data_check_report, error = read_json_file(data_check_path)
        if error or not isinstance(data_check_report, dict):
            blockers.append(f"data-check report could not be read: {error}")
        else:
            data_check_report["_report_path"] = data_check_path.as_posix()
            inputs["data_check_report"] = summarize_report_input(data_check_report)
            findings = data_check_report.get("findings", {})
            blockers.extend(str(item) for item in findings.get("critical", []))
            warnings.extend(str(item) for item in findings.get("warnings", []))
    else:
        blockers.append("data-check report not provided")

    steps = build_upgrade_steps(args.maintenance_window)
    status = "blocked" if blockers else "ready-with-warnings" if warnings else "ready"
    plan = {
        "kind": "upgrade-plan",
        "job_id": job_id,
        "status": status,
        "generated_at": utc_now(),
        "app_root": app_root.as_posix(),
        "target_commit": args.target_commit or "",
        "maintenance_window": args.maintenance_window or "",
        "operator": args.operator or "",
        "inputs": inputs,
        "blockers": blockers,
        "warnings": warnings,
        "steps": steps,
        "rollback_reference": {
            "decision_point": "Decide rollback before the maintenance window reaches its rollback deadline.",
            "source": "Use the verified pre-upgrade backup manifest and keep failed release logs for review.",
        },
        "not_executed": [
            "No files were replaced.",
            "No services were stopped or started.",
            "No database migration was run.",
            "No rollback was executed.",
        ],
    }
    report_path = output_dir / f"upgrade-plan-{job_id}.json"
    write_json(report_path, plan)
    logger.event("plan_written", report_path=report_path.as_posix(), status=status)
    plan["_report_path"] = report_path.as_posix()
    return plan


def summarize_report_input(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": report.get("kind", ""),
        "status": report.get("status", ""),
        "job_id": report.get("job_id", ""),
        "path": report.get("_report_path") or report.get("release_path") or report.get("backup_dir") or "",
        "generated_at": report.get("generated_at", ""),
    }


def build_upgrade_steps(maintenance_window: str | None) -> list[dict[str, Any]]:
    return [
        {"phase": "precheck", "action": "Review inventory, data-check report, release validation, and backup manifest."},
        {"phase": "backup", "action": "Confirm executed pre-upgrade backup path, manifest, size, and restore readability."},
        {"phase": "rehearsal", "action": "Restore production data copy into a rehearsal directory and validate startup there."},
        {"phase": "dry-run", "action": "Run migration dry-run and data integrity checks in the rehearsal copy only."},
        {"phase": "maintenance-window", "action": maintenance_window or "Schedule a low-traffic maintenance window before production switch."},
        {"phase": "switch", "action": "Follow reviewed manual steps; do not run git pull, checkout, reset, or overwrite runtime data."},
        {"phase": "acceptance", "action": "Verify login, admin, normal-user isolation, history, assets, WebSocket, LAN, and public HTTPS."},
        {"phase": "rollback-decision", "action": "Rollback from full backup if startup, login, isolation, history, files, or public access fails."},
    ]


OPS3_COMMANDS = {
    "check-update",
    "fetch-release",
    "stage-release",
    "prepare-online-update",
}


def _online_update_service(args: argparse.Namespace) -> OnlineUpdateService:
    if args.provider == "github-releases":
        provider = GitHubReleasesProvider()
    elif args.provider == "local-fixture":
        if not args.fixture:
            raise OnlineUpdateError("local fixture provider requires a fixture file")
        provider = LocalFixtureProvider(args.fixture)
    else:
        raise OnlineUpdateError("online update provider is not supported")
    return OnlineUpdateService(app_root=args.app_root, workspace=args.workspace, provider=provider)


def command_check_update(args: argparse.Namespace) -> dict[str, Any]:
    return _online_update_service(args).check_update(allow_prerelease=args.allow_prerelease)


def command_fetch_release(args: argparse.Namespace) -> dict[str, Any]:
    return _online_update_service(args).fetch_release(
        allow_prerelease=args.allow_prerelease,
        release_id=args.release_id or None,
    )


def _offline_online_update_service(args: argparse.Namespace) -> OnlineUpdateService:
    # Staging and planning never make network calls; a local provider preserves
    # the shared service constructor without creating a GitHub client.
    provider = LocalFixtureProvider(getattr(args, "fixture", "") or "missing-fixture.json")
    return OnlineUpdateService(app_root=args.app_root, workspace=args.workspace, provider=provider)


def command_stage_release(args: argparse.Namespace) -> dict[str, Any]:
    return _offline_online_update_service(args).stage_release(
        manifest_path=args.manifest,
        archive_path=args.archive,
    )


def command_prepare_online_update(args: argparse.Namespace) -> dict[str, Any]:
    return _offline_online_update_service(args).prepare_online_update(
        stage_report_path=args.stage_report,
        backup_manifest_path=args.backup_manifest or None,
        data_check_report_path=args.data_check_report or None,
        maintenance_window=args.maintenance_window,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ops-runner", description="Infinite Canvas Enterprise OPS-2A toolkit")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--app-root", type=Path, default=Path.cwd(), help="Application root. Defaults to cwd.")
        subparser.add_argument("--output-dir", default=DEFAULT_ARTIFACT_DIR, help="Directory for JSON reports.")
        subparser.add_argument("--log-file", default=DEFAULT_LOG_FILE, help="JSONL OPS job log path.")
        subparser.add_argument("--operator", default="", help="Optional operator name for local logs.")
        subparser.add_argument("--job-id", default="", help="Optional explicit job id.")

    inventory = subparsers.add_parser("inventory", help="Write read-only inventory report.")
    add_common(inventory)
    inventory.set_defaults(handler=command_inventory)

    check_data = subparsers.add_parser("check-data", help="Write read-only data consistency report.")
    add_common(check_data)
    check_data.set_defaults(handler=command_check_data)

    backup = subparsers.add_parser("backup", help="Write backup manifest, and copy files only with --execute.")
    add_common(backup)
    backup.add_argument("--backup-root", default=DEFAULT_BACKUP_DIR, help="Backup output root.")
    backup.add_argument("--backup-type", default="pre-upgrade", choices=("pre-upgrade", "full", "snapshot"))
    backup.add_argument("--backup-id", default="", help="Optional explicit backup id.")
    backup.add_argument("--execute", action="store_true", help="Actually copy backup files. Default is dry-run.")
    backup.set_defaults(handler=command_backup)

    validate = subparsers.add_parser("validate-release", help="Validate an offline release directory or zip.")
    add_common(validate)
    validate.add_argument("--release", required=True, help="Release directory or zip to validate.")
    validate.set_defaults(handler=command_validate_release)

    prepare = subparsers.add_parser("prepare-upgrade", help="Write a non-executing upgrade plan.")
    add_common(prepare)
    prepare.add_argument("--release", required=False, help="Release directory or zip to validate for the plan.")
    prepare.add_argument("--backup-manifest", required=False, help="Executed backup manifest JSON.")
    prepare.add_argument("--data-check-report", required=False, help="Data-check report JSON.")
    prepare.add_argument("--target-commit", default="", help="Target commit expected after upgrade.")
    prepare.add_argument("--maintenance-window", default="", help="Planned maintenance window text.")
    prepare.set_defaults(handler=command_prepare_upgrade)

    def add_online_update_common(subparser: argparse.ArgumentParser, *, provider: bool) -> None:
        subparser.add_argument("--app-root", type=Path, default=Path.cwd(), help="Application root read-only input.")
        subparser.add_argument("--workspace", type=Path, required=True, help="Existing OPS workspace outside the application root.")
        if provider:
            subparser.add_argument("--provider", choices=("github-releases", "local-fixture"), default="github-releases")
            subparser.add_argument("--fixture", default="", help="Local fixture JSON; only used with local-fixture.")

    check_update = subparsers.add_parser("check-update", help="Check a trusted provider without downloading a package.")
    add_online_update_common(check_update, provider=True)
    check_update.add_argument("--allow-prerelease", action="store_true", help="Include trusted prereleases explicitly.")
    check_update.set_defaults(handler=command_check_update)

    fetch_release = subparsers.add_parser("fetch-release", help="Download a verified release into the OPS workspace.")
    add_online_update_common(fetch_release, provider=True)
    fetch_release.add_argument("--allow-prerelease", action="store_true", help="Include trusted prereleases explicitly.")
    fetch_release.add_argument("--release-id", default="", help="Optional trusted provider release identifier.")
    fetch_release.set_defaults(handler=command_fetch_release)

    stage_release = subparsers.add_parser("stage-release", help="Safely extract a fetched release into a new workspace staging directory.")
    add_online_update_common(stage_release, provider=False)
    stage_release.add_argument("--manifest", required=True, help="Workspace-relative or workspace-contained manifest path.")
    stage_release.add_argument("--archive", required=True, help="Workspace-relative or workspace-contained archive path.")
    stage_release.set_defaults(handler=command_stage_release)

    prepare_online_update = subparsers.add_parser("prepare-online-update", help="Write a non-executing online-update plan.")
    add_online_update_common(prepare_online_update, provider=False)
    prepare_online_update.add_argument("--stage-report", required=True, help="Successful stage-release report JSON.")
    prepare_online_update.add_argument("--backup-manifest", default="", help="Existing executed backup manifest JSON.")
    prepare_online_update.add_argument("--data-check-report", default="", help="Existing data-check report JSON.")
    prepare_online_update.add_argument("--maintenance-window", default="", help="Optional reviewed maintenance-window text.")
    prepare_online_update.set_defaults(handler=command_prepare_online_update)

    return parser


def run(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    if args.command in OPS3_COMMANDS:
        report = args.handler(args)
        return (2 if report.get("status") in {"fail", "blocked"} else 0), report
    app_root = args.app_root.resolve()
    job_id = args.job_id or make_job_id(args.command)
    log_file = resolve_path(app_root, args.log_file)
    logger = OpsJobLogger(log_file, job_id, args.command, args.operator)
    logger.event("started", app_root=app_root.as_posix())
    started = time.time()
    try:
        report = args.handler(args, job_id, logger)
        elapsed_ms = int((time.time() - started) * 1000)
        logger.event(
            "finished",
            status=report.get("status", ""),
            elapsed_ms=elapsed_ms,
            report_path=report.get("_report_path", ""),
        )
        code = 2 if report.get("status") in {"fail", "blocked"} else 0
        return code, report
    except Exception as exc:
        logger.event("failed", error=type(exc).__name__, message=str(exc))
        raise


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        code, report = run(args)
    except Exception as exc:
        if args.command in OPS3_COMMANDS:
            message = exc.public_message if isinstance(exc, OnlineUpdateError) else "Online update preparation failed"
            print(f"{args.command} failed: {message}", file=sys.stderr)
        else:
            print(f"{args.command} failed: {exc}", file=sys.stderr)
        return 1
    report_path = report.get("_report_path", "")
    status = report.get("status", "")
    if report_path:
        print(f"{args.command} {status}: {report_path}")
    else:
        print(f"{args.command} {status}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
