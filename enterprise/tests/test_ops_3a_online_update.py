"""Temporary-directory checks for the non-executing OPS-3A update core.

Run from the repository root:

    python .\\enterprise\\tests\\test_ops_3a_online_update.py
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enterprise.ops.update.download import atomic_download
from enterprise.ops.update.errors import (
    OnlineUpdateValidationError,
    ReleaseDownloadError,
    ReleaseManifestError,
    ReleaseStagingError,
)
from enterprise.ops.update.http_client import SafeHttpClient, UrlPolicy
from enterprise.ops.update.jobs import UpdateJob
from enterprise.ops.update.manifest import parse_release_manifest, parse_release_manifest_bytes
from enterprise.ops.update.providers import DEFAULT_GITHUB_REPOSITORY, GitHubReleasesProvider, LocalFixtureProvider
from enterprise.ops.update.service import OnlineUpdateService
from enterprise.ops.update.staging import inspect_zip_archive
from enterprise.ops.update.versions import compare_versions, parse_version


COMMIT = "a" * 40
ROOT_PREFIX = f"Infinite-Canvas-Enterprise-{COMMIT}"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_archive(path: Path, entries: dict[str, bytes]) -> bytes:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return path.read_bytes()


def make_manifest(archive: bytes, *, version: str = "2026.07.7", file_count: int = 3) -> dict:
    return {
        "schema_version": "ops-release-manifest-v1",
        "release_version": version,
        "source_commit": COMMIT,
        "source_tree": "b" * 40,
        "generated_at": "2026-07-14T00:00:00Z",
        "archive": {
            "filename": f"Infinite-Canvas-Enterprise-release-{COMMIT}.zip",
            "size_bytes": len(archive),
            "sha256": sha256(archive),
        },
        "package": {"file_count": file_count, "root_prefix": ROOT_PREFIX},
        "compatibility": {
            "minimum_current_version": "2026.07.6",
            "maximum_current_version": "",
            "requires_database_migration": False,
            "migration_ids": [],
        },
        "release_notes": "Test release",
    }


class FixtureHandler(BaseHTTPRequestHandler):
    responses: ClassVar[dict[str, tuple[int, dict[str, str], bytes]]] = {}

    def do_GET(self) -> None:  # noqa: N802
        status, headers, body = self.responses.get(self.path, (404, {}, b""))
        if self.path == "/slow":
            time.sleep(2)
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        if "Content-Length" not in headers:
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def log_message(self, _format: str, *_args: object) -> None:
        return


class LocalServer:
    def __enter__(self) -> "LocalServer":
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        return self

    def __exit__(self, *_args: object) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


def make_app(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "VERSION").write_text("2026.07.6\n", encoding="utf-8")
    (root / "main.py").write_text("# app\n", encoding="utf-8")


def fixture_record(server: LocalServer, *, version: str = "2026.07.7", release_id: str = "77", draft: bool = False, prerelease: bool = False) -> dict:
    return {
        "repository": DEFAULT_GITHUB_REPOSITORY,
        "release_id": release_id,
        "tag_name": f"v{version}",
        "version": version,
        "prerelease": prerelease,
        "draft": draft,
        "published_at": "2026-07-14T00:00:00Z",
        "manifest_url": f"{server.base_url}/manifest",
        "archive_url": f"{server.base_url}/archive/Infinite-Canvas-Enterprise-release-{COMMIT}.zip",
        "release_notes": "fixture",
    }


def run_cli(app_root: Path, workspace: Path, *args: str, expect: int = 0) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "enterprise" / "ops" / "runner.py"),
            *args,
            "--app-root",
            str(app_root),
            "--workspace",
            str(workspace),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=os.environ.copy(),
    )
    assert result.returncode == expect, result.stdout + result.stderr
    report_path = Path(result.stdout.strip().split(": ", 1)[1])
    return json.loads(report_path.read_text(encoding="utf-8"))


def expect_error(error_type: type[Exception], callable_object, *args, **kwargs) -> None:
    try:
        callable_object(*args, **kwargs)
    except error_type:
        return
    raise AssertionError(f"expected {error_type.__name__}")


def verify_versions_and_manifest() -> None:
    assert str(parse_version("2026.07.6")) == "2026.07.6"
    assert compare_versions("2026.07.6", "2026.07.7") == "newer"
    assert compare_versions("2026.07.7", "2026.07.7") == "same"
    assert compare_versions("2026.07.7", "2026.07.6") == "older"
    assert compare_versions("2026.7.6", "2026.07.7") == "invalid"
    for invalid in (" 2026.07.6", "2026.13.1", "2026.07.-1", "2026.07.01"):
        expect_error(ValueError, parse_version, invalid)

    with tempfile.TemporaryDirectory(prefix="ice-ops3a-manifest-") as raw:
        archive = make_archive(Path(raw) / "release.zip", {f"{ROOT_PREFIX}/VERSION": b"2026.07.7\n"})
        manifest = make_manifest(archive, file_count=1)
        assert parse_release_manifest(manifest).release_version == "2026.07.7"
        bad = dict(manifest)
        bad["unknown"] = True
        expect_error(ReleaseManifestError, parse_release_manifest, bad)
        bad = json.dumps(manifest).replace('"release_version": "2026.07.7"', '"release_version": true')
        expect_error(ReleaseManifestError, parse_release_manifest_bytes, bad.encode("utf-8"))
        duplicate = json.dumps(manifest)[:-1] + ',"release_version":"2026.07.7"}'
        expect_error(ReleaseManifestError, parse_release_manifest_bytes, duplicate.encode("utf-8"))


def verify_http_and_download() -> None:
    github = GitHubReleasesProvider()
    expect_error(ReleaseDownloadError, github.url_policy.validate, "http://api.github.com/releases")
    expect_error(ReleaseDownloadError, github.url_policy.validate, "https://example.invalid/release")
    with LocalServer() as server, tempfile.TemporaryDirectory(prefix="ice-ops3a-http-") as raw:
        FixtureHandler.responses = {
            "/bytes": (200, {}, b"payload"),
            "/redirect": (302, {"Location": "http://example.invalid/blocked"}, b""),
            "/oversized": (200, {"Content-Length": "999"}, b"small"),
            "/slow": (200, {}, b"late"),
        }
        client = SafeHttpClient(UrlPolicy(frozenset(), allow_loopback_http=True), timeout_seconds=1)
        result = atomic_download(
            client,
            url=f"{server.base_url}/bytes",
            destination=Path(raw) / "download.zip",
            maximum_bytes=32,
            expected_size_bytes=7,
            expected_sha256=sha256(b"payload"),
        )
        assert result.size_bytes == 7 and result.path.exists()
        expect_error(ReleaseDownloadError, atomic_download, client, url=f"{server.base_url}/bytes", destination=result.path, maximum_bytes=32)
        expect_error(ReleaseDownloadError, client.read_bytes, f"{server.base_url}/redirect", maximum_bytes=32)
        expect_error(ReleaseDownloadError, client.read_bytes, f"{server.base_url}/oversized", maximum_bytes=32)
        expect_error(ReleaseDownloadError, atomic_download, client, url=f"{server.base_url}/bytes", destination=Path(raw) / "bad.zip", maximum_bytes=32, expected_sha256="0" * 64)
        assert not (Path(raw) / "bad.zip").exists()
        assert not list(Path(raw).glob("*.part"))
        expect_error(ReleaseDownloadError, client.read_bytes, f"{server.base_url}/slow", maximum_bytes=32)


def verify_zip_defences() -> None:
    unsafe_entries = ("../x", "/x", "C:/x", "//server/share/x", f"{ROOT_PREFIX}\\..\\x")
    with tempfile.TemporaryDirectory(prefix="ice-ops3a-zip-") as raw:
        root = Path(raw)
        for index, name in enumerate(unsafe_entries):
            archive = make_archive(root / f"unsafe-{index}.zip", {name: b"x"})
            manifest = parse_release_manifest(make_manifest(archive, file_count=1))
            expect_error(ReleaseStagingError, inspect_zip_archive, root / f"unsafe-{index}.zip", manifest)
        duplicate = make_archive(root / "duplicate.zip", {f"{ROOT_PREFIX}/Foo": b"a", f"{ROOT_PREFIX}/foo": b"b"})
        expect_error(ReleaseStagingError, inspect_zip_archive, root / "duplicate.zip", parse_release_manifest(make_manifest(duplicate, file_count=2)))
        symlink = root / "symlink.zip"
        with zipfile.ZipFile(symlink, "w") as archive_file:
            info = zipfile.ZipInfo(f"{ROOT_PREFIX}/link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive_file.writestr(info, b"target")
        expect_error(ReleaseStagingError, inspect_zip_archive, symlink, parse_release_manifest(make_manifest(symlink.read_bytes(), file_count=1)))
        bomb = make_archive(root / "bomb.zip", {f"{ROOT_PREFIX}/large.txt": b"0" * 4096})
        expect_error(ReleaseStagingError, inspect_zip_archive, root / "bomb.zip", parse_release_manifest(make_manifest(bomb, file_count=1)), max_compression_ratio=1)


def verify_service_and_cli() -> None:
    with tempfile.TemporaryDirectory(prefix="ice-ops3a-service-") as raw, LocalServer() as server:
        root = Path(raw)
        app_root, workspace = root / "app", root / "workspace"
        make_app(app_root)
        workspace.mkdir()
        archive = make_archive(
            root / "release.zip",
            {
                f"{ROOT_PREFIX}/VERSION": b"2026.07.7\n",
                f"{ROOT_PREFIX}/main.py": b"# release\n",
                f"{ROOT_PREFIX}/enterprise/__init__.py": b"",
            },
        )
        manifest = make_manifest(archive)
        manifest_bytes = json.dumps(manifest, sort_keys=True).encode("utf-8")
        FixtureHandler.responses = {
            "/manifest": (200, {}, manifest_bytes),
            f"/archive/Infinite-Canvas-Enterprise-release-{COMMIT}.zip": (200, {}, archive),
        }
        fixture = root / "releases.json"
        normal = fixture_record(server)
        draft = fixture_record(server, version="2026.07.9", release_id="79", draft=True)
        prerelease = fixture_record(server, version="2026.07.8", release_id="78", prerelease=True)
        write_json(fixture, {"releases": [draft, prerelease, normal]})
        provider = LocalFixtureProvider(fixture)
        service = OnlineUpdateService(app_root=app_root, workspace=workspace, provider=provider)
        check = service.check_update()
        assert check["status"] == "pass" and check["target_version"] == "2026.07.7"
        assert check["state"] == "metadata_ready" and check["finished_at"]
        fetched = service.fetch_release()
        assert fetched["status"] == "pass" and fetched["state"] == "verifying"
        assert (workspace / fetched["archive_path"]).exists()
        staged = service.stage_release(manifest_path=fetched["manifest_path"], archive_path=fetched["archive_path"])
        assert staged["status"] == "pass" and staged["state"] == "staged"
        assert (workspace / staged["staging_path"]).is_dir()
        backup = root / "backup-manifest.json"
        data_check = root / "data-check.json"
        write_json(backup, {"status": "pass", "dry_run": False, "sqlite_backup_status": "success"})
        write_json(data_check, {"kind": "data-check-report", "status": "warn", "warnings": ["sample"]})
        plan = service.prepare_online_update(
            stage_report_path=workspace / staged["report_paths"][0],
            backup_manifest_path=backup,
            data_check_report_path=data_check,
            maintenance_window="03:00-04:00",
        )
        assert plan["status"] == "pass" and plan["state"] == "planned"
        assert all(item.startswith("No ") for item in plan["not_executed"])
        blocked = service.prepare_online_update(
            stage_report_path=workspace / staged["report_paths"][0],
            backup_manifest_path=None,
            data_check_report_path=None,
        )
        assert blocked["status"] == "blocked" and blocked["blockers"]
        logs = (workspace / "jobs.jsonl").read_text(encoding="utf-8")
        assert "manifest_url" not in logs and "archive_url" not in logs
        assert not (app_root / "logs").exists()

        cli_check = run_cli(
            app_root,
            workspace,
            "check-update",
            "--provider",
            "local-fixture",
            "--fixture",
            str(fixture),
        )
        assert cli_check["status"] == "pass" and cli_check["target_version"] == "2026.07.7"
        assert not (app_root / "ops_artifacts").exists()


def verify_job_redaction() -> None:
    with tempfile.TemporaryDirectory(prefix="ice-ops3a-job-") as raw:
        workspace = Path(raw)
        job = UpdateJob("check-update", workspace)
        job.transition("checking", token="nope")
        job.transition("metadata_ready", cookie="nope")
        job.complete()
        report = job.write_report(status="pass")
        job.append_log("tested", authorization="nope", nested={"api_key": "nope"})
        serialized = json.dumps(report) + (workspace / "jobs.jsonl").read_text(encoding="utf-8")
        assert "nope" not in serialized and "[redacted]" in serialized
        expect_error(OnlineUpdateValidationError, job.transition, "downloading")


def run_all() -> None:
    verify_versions_and_manifest()
    verify_http_and_download()
    verify_zip_defences()
    verify_service_and_cli()
    verify_job_redaction()


if __name__ == "__main__":
    run_all()
    print("OPS-3A online update checks passed")
