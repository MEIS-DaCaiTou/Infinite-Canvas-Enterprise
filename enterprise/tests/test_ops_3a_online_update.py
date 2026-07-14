"""Temporary-directory checks for the non-executing OPS-3A update core.

Run from the repository root:

    python .\\enterprise\\tests\\test_ops_3a_online_update.py
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
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


def make_manifest(
    archive: bytes,
    *,
    version: str = "2026.07.7",
    file_count: int = 3,
    minimum_current_version: str = "2026.07.6",
    maximum_current_version: str = "",
    source_tree: str = "b" * 40,
) -> dict:
    return {
        "schema_version": "ops-release-manifest-v1",
        "release_version": version,
        "source_commit": COMMIT,
        "source_tree": source_tree,
        "generated_at": "2026-07-14T00:00:00Z",
        "archive": {
            "filename": f"Infinite-Canvas-Enterprise-release-{COMMIT}.zip",
            "size_bytes": len(archive),
            "sha256": sha256(archive),
        },
        "package": {"file_count": file_count, "root_prefix": ROOT_PREFIX},
        "compatibility": {
            "minimum_current_version": minimum_current_version,
            "maximum_current_version": maximum_current_version,
            "requires_database_migration": False,
            "migration_ids": [],
        },
        "release_notes": "Test release",
    }


class FixtureHandler(BaseHTTPRequestHandler):
    responses: ClassVar[dict[str, tuple[int, dict[str, str], bytes]]] = {}
    request_headers: ClassVar[dict[str, dict[str, str]]] = {}

    def do_GET(self) -> None:  # noqa: N802
        self.request_headers[self.path] = {key.casefold(): value for key, value in self.headers.items()}
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
    database_path = root / "data" / "enterprise.db"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE user_canvas_map (user_id TEXT NOT NULL, canvas_id TEXT NOT NULL)")
        connection.execute("INSERT INTO user_canvas_map (user_id, canvas_id) VALUES (?, ?)", ("user-1", "canvas-1"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_journal_mode(path: Path) -> str:
    header = path.read_bytes()[:100]
    assert header[:16] == b"SQLite format 3\x00" and header[18] == header[19]
    return "wal" if header[18] == 2 else "delete"


def set_journal_header(path: Path, mode: str) -> None:
    version = {"delete": 1, "wal": 2}[mode]
    payload = bytearray(path.read_bytes())
    assert len(payload) >= 100 and payload[:16] == b"SQLite format 3\x00"
    payload[18] = version
    payload[19] = version
    path.write_bytes(payload)


def directory_fingerprints(path: Path) -> dict[str, str]:
    return {
        child.name: f"{child.stat().st_size}:{sha256_file(child)}"
        for child in sorted(path.iterdir())
        if child.is_file()
    }


def write_formal_backup(app_root: Path, manifest_path: Path) -> dict:
    source_path = app_root / "data" / "enterprise.db"
    backup_dir = manifest_path.parent / "formal-backup"
    backup_path = backup_dir / "app" / "data" / "enterprise.db"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"{source_path.resolve().as_uri()}?mode=ro", uri=True) as source, sqlite3.connect(backup_path) as target:
        source.backup(target)
    payload = {
        "kind": "backup-manifest",
        "backup_id": "temporary-formal-backup",
        "status": "pass",
        "dry_run": False,
        "generated_at": "2026-07-14T00:00:00Z",
        "copied_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "app_root": app_root.resolve().as_posix(),
        "backup_dir": backup_dir.resolve().as_posix(),
        "sqlite_backup_status": "success",
        "sqlite_backup_path": backup_path.resolve().as_posix(),
        "source_database_relative_path": "data/enterprise.db",
        "source_database_size_bytes": source_path.stat().st_size,
        "source_database_sha256": sha256_file(source_path),
        "source_database_journal_mode": source_journal_mode(source_path),
        "sqlite_backup_size_bytes": backup_path.stat().st_size,
        "sqlite_backup_sha256": sha256_file(backup_path),
    }
    write_json(manifest_path, payload)
    return payload


def write_data_check(app_root: Path, report_path: Path, *, status: str = "warn") -> dict:
    payload = {
        "kind": "data-check-report",
        "status": status,
        "app_root": app_root.resolve().as_posix(),
        "findings": {"critical": [], "warnings": ["operator-review"] if status == "warn" else []},
    }
    write_json(report_path, payload)
    return payload


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
        FixtureHandler.request_headers = {}
        FixtureHandler.responses = {
            "/bytes": (200, {}, b"payload"),
            "/redirect": (302, {"Location": "http://example.invalid/blocked"}, b""),
            "/redirect-cross-host": (302, {"Location": f"http://localhost:{server.server.server_port}/redirect-target"}, b""),
            "/redirect-target": (200, {}, b"redirected"),
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
        expect_error(ReleaseDownloadError, atomic_download, client, url=f"{server.base_url}/bytes", destination=Path(raw) / "bad-size.zip", maximum_bytes=32, expected_size_bytes=8)
        assert not (Path(raw) / "bad.zip").exists()
        assert not list(Path(raw).glob("*.part"))
        expect_error(ReleaseDownloadError, client.read_bytes, f"{server.base_url}/slow", maximum_bytes=32)
        assert client.read_bytes(
            f"{server.base_url}/redirect-cross-host",
            maximum_bytes=32,
            headers={"Authorization": "Bearer fixture", "Cookie": "fixture-cookie", "X-Trace": "preserved"},
        ) == b"redirected"
        redirected_headers = FixtureHandler.request_headers["/redirect-target"]
        assert "authorization" not in redirected_headers and "cookie" not in redirected_headers
        assert redirected_headers["x-trace"] == "preserved"


class StaticGitHubClient:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.request_headers: list[dict[str, str]] = []

    def read_json(self, _url: str, *, maximum_bytes: int, headers: dict[str, str]) -> object:
        assert maximum_bytes > 0 and headers["Accept"]
        self.request_headers.append(dict(headers))
        return self.payload


class LoopbackGitHubProvider(GitHubReleasesProvider):
    """Test-only trusted provider shape with loopback asset endpoints."""

    url_policy = UrlPolicy(frozenset(), allow_loopback_http=True)


def verify_github_release_filtering() -> None:
    def asset(name: str) -> dict[str, str]:
        return {"name": name, "browser_download_url": f"https://github.com/downloads/{name}"}

    valid = {
        "id": 77,
        "tag_name": "v2026.07.7",
        "draft": False,
        "prerelease": False,
        "published_at": "2026-07-14T00:00:00Z",
        "assets": [asset("ops-release-manifest-v1.json"), asset("release.zip")],
    }
    provider = GitHubReleasesProvider(
        http_client=StaticGitHubClient(
            [
                {"id": 1, "tag_name": "v2025.13.1", "draft": True},
                {"id": 2, "tag_name": "historical-tag", "draft": False, "prerelease": False, "assets": []},
                {"id": 3, "tag_name": "v2026.07.8", "draft": False, "prerelease": False, "assets": [asset("release.zip")]},
                valid,
            ]
        )
    )
    releases = provider.list_releases()
    assert [release.release_id for release in releases] == ["77"]
    assert provider.diagnostics == (
        "draft_release_skipped",
        "invalid_or_incomplete_release_skipped",
        "invalid_or_incomplete_release_skipped",
    )
    with tempfile.TemporaryDirectory(prefix="ice-ops3a-provider-diagnostics-") as raw:
        root = Path(raw)
        app_root, workspace = root / "app", root / "workspace"
        make_app(app_root)
        workspace.mkdir()
        invalid_client = StaticGitHubClient(
            [{"id": 3, "tag_name": "v2026.07.8", "draft": False, "prerelease": False, "assets": []}]
        )
        invalid_provider = GitHubReleasesProvider(http_client=invalid_client)
        invalid_service = OnlineUpdateService(app_root=app_root, workspace=workspace, provider=invalid_provider)
        invalid_check = invalid_service.check_update()
        invalid_fetch = invalid_service.fetch_release()
        for report in (invalid_check, invalid_fetch):
            assert report["status"] == "blocked"
            assert report["provider_outcome"] == "all_provider_records_skipped"
            assert report["provider_diagnostic_count"] == 1
            assert report["provider_diagnostics"] == ["invalid_or_incomplete_release_skipped"]

        historical = dict(valid)
        historical.update({"id": 76, "tag_name": "v2026.07.6"})
        historical_provider = GitHubReleasesProvider(http_client=StaticGitHubClient([historical]))
        historical_service = OnlineUpdateService(app_root=app_root, workspace=workspace, provider=historical_provider)
        historical_check = historical_service.check_update()
        assert historical_check["status"] == "pass"
        assert historical_check["provider_outcome"] == "valid_records_no_newer_eligible_release"
        assert historical_check["provider_diagnostic_count"] == 0


def verify_private_github_asset_authorization() -> None:
    """Private GitHub assets receive transient auth only on their initial origin."""
    with tempfile.TemporaryDirectory(prefix="ice-ops3a-private-release-") as raw, LocalServer() as server:
        root = Path(raw)
        app_root, workspace = root / "app", root / "workspace"
        make_app(app_root)
        workspace.mkdir()
        archive = make_archive(
            root / "private-release.zip",
            {
                f"{ROOT_PREFIX}/VERSION": b"2026.07.7\n",
                f"{ROOT_PREFIX}/main.py": b"# release\n",
                f"{ROOT_PREFIX}/enterprise/__init__.py": b"",
            },
        )
        manifest = make_manifest(archive)
        archive_name = manifest["archive"]["filename"]
        FixtureHandler.request_headers = {}
        FixtureHandler.responses = {
            "/private-manifest": (200, {}, json.dumps(manifest, sort_keys=True).encode("utf-8")),
            f"/private/{archive_name}": (302, {"Location": f"http://localhost:{server.server.server_port}/signed/{archive_name}"}, b""),
            f"/signed/{archive_name}": (200, {}, archive),
            "/fixture-manifest": (200, {}, json.dumps(manifest, sort_keys=True).encode("utf-8")),
            f"/fixture/{archive_name}": (200, {}, archive),
        }
        metadata_payload = [
            {
                "id": 91,
                "tag_name": "v2026.07.7",
                "draft": False,
                "prerelease": False,
                "published_at": "2026-07-14T00:00:00Z",
                "assets": [
                    {"name": "ops-release-manifest-v1.json", "browser_download_url": f"{server.base_url}/private-manifest"},
                    {"name": archive_name, "browser_download_url": f"{server.base_url}/private/{archive_name}"},
                ],
            }
        ]
        metadata_client = StaticGitHubClient(metadata_payload)
        provider = LoopbackGitHubProvider(http_client=metadata_client)
        previous_token = os.environ.get("GITHUB_TOKEN")
        token = "private-fixture-token"
        try:
            os.environ["GITHUB_TOKEN"] = token
            service = OnlineUpdateService(app_root=app_root, workspace=workspace, provider=provider)
            fetched = service.fetch_release()
            assert fetched["status"] == "pass"
            assert metadata_client.request_headers[0]["Authorization"] == f"Bearer {token}"
            assert FixtureHandler.request_headers["/private-manifest"]["authorization"] == f"Bearer {token}"
            assert FixtureHandler.request_headers[f"/private/{archive_name}"]["authorization"] == f"Bearer {token}"
            signed_headers = FixtureHandler.request_headers[f"/signed/{archive_name}"]
            assert "authorization" not in signed_headers and "cookie" not in signed_headers
            serialized = json.dumps(fetched) + (workspace / "jobs.jsonl").read_text(encoding="utf-8")
            assert token not in serialized

            fixture = root / "local-releases.json"
            local_record = fixture_record(server)
            local_record["manifest_url"] = f"{server.base_url}/fixture-manifest"
            local_record["archive_url"] = f"{server.base_url}/fixture/{archive_name}"
            write_json(fixture, {"releases": [local_record]})
            local_app, local_workspace = root / "local-app", root / "local-workspace"
            make_app(local_app)
            local_workspace.mkdir()
            local_service = OnlineUpdateService(
                app_root=local_app,
                workspace=local_workspace,
                provider=LocalFixtureProvider(fixture),
            )
            local_check = local_service.check_update()
            assert local_check["status"] == "pass", local_check
            assert "authorization" not in FixtureHandler.request_headers["/fixture-manifest"]
            assert local_service.provider.release_request_headers(local_service.provider.list_releases()[0]) == {}
        finally:
            if previous_token is None:
                os.environ.pop("GITHUB_TOKEN", None)
            else:
                os.environ["GITHUB_TOKEN"] = previous_token


def verify_zip_defences() -> None:
    unsafe_entries = (
        "../x",
        "/x",
        "C:/x",
        "//server/share/x",
        f"{ROOT_PREFIX}\\..\\x",
        f"{ROOT_PREFIX}/VERSION:alternate-stream",
        f"{ROOT_PREFIX}/CON.txt",
        f"{ROOT_PREFIX}/aux/file",
        f"{ROOT_PREFIX}/trailing-dot.",
        f"{ROOT_PREFIX}/trailing-space ",
        f"{ROOT_PREFIX}/control\x1f-character",
    )
    with tempfile.TemporaryDirectory(prefix="ice-ops3a-zip-") as raw:
        root = Path(raw)
        for index, name in enumerate(unsafe_entries):
            archive = make_archive(root / f"unsafe-{index}.zip", {name: b"x"})
            manifest = parse_release_manifest(make_manifest(archive, file_count=1))
            expect_error(ReleaseStagingError, inspect_zip_archive, root / f"unsafe-{index}.zip", manifest)
        duplicate = make_archive(root / "duplicate.zip", {f"{ROOT_PREFIX}/Foo": b"a", f"{ROOT_PREFIX}/foo": b"b"})
        expect_error(ReleaseStagingError, inspect_zip_archive, root / "duplicate.zip", parse_release_manifest(make_manifest(duplicate, file_count=2)))
        unicode_collision = make_archive(
            root / "unicode-collision.zip",
            {f"{ROOT_PREFIX}/caf\u00e9.txt": b"a", f"{ROOT_PREFIX}/cafe\u0301.txt": b"b"},
        )
        expect_error(ReleaseStagingError, inspect_zip_archive, root / "unicode-collision.zip", parse_release_manifest(make_manifest(unicode_collision, file_count=2)))
        directory_root = root / "directory-root.zip"
        with zipfile.ZipFile(directory_root, "w") as archive_file:
            archive_file.writestr(f"{ROOT_PREFIX}/", b"")
            archive_file.writestr(f"{ROOT_PREFIX}/VERSION", b"2026.07.7\n")
        assert len(inspect_zip_archive(directory_root, parse_release_manifest(make_manifest(directory_root.read_bytes(), file_count=1)))) == 1
        symlink = root / "symlink.zip"
        with zipfile.ZipFile(symlink, "w") as archive_file:
            info = zipfile.ZipInfo(f"{ROOT_PREFIX}/link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive_file.writestr(info, b"target")
        expect_error(ReleaseStagingError, inspect_zip_archive, symlink, parse_release_manifest(make_manifest(symlink.read_bytes(), file_count=1)))
        reparse = root / "reparse.zip"
        with zipfile.ZipFile(reparse, "w") as archive_file:
            info = zipfile.ZipInfo(f"{ROOT_PREFIX}/junction")
            info.external_attr = 0x0400
            archive_file.writestr(info, b"x")
        expect_error(ReleaseStagingError, inspect_zip_archive, reparse, parse_release_manifest(make_manifest(reparse.read_bytes(), file_count=1)))
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
        expect_error(OnlineUpdateValidationError, OnlineUpdateService, app_root=app_root, workspace=app_root / "invalid-workspace", provider=provider)
        check = service.check_update()
        assert check["status"] == "pass" and check["target_version"] == "2026.07.7"
        assert check["state"] == "metadata_ready" and check["finished_at"]
        assert check["source_tree"] == manifest["source_tree"]
        assert check["provider_diagnostic_count"] == 0 and check["provider_diagnostics"] == []
        same_release = fixture_record(server, version="2026.07.6", release_id="76")
        write_json(fixture, {"releases": [same_release, draft, prerelease, normal]})
        same_fetch = service.fetch_release(release_id="76")
        assert same_fetch["status"] == "blocked" and not list((workspace / "downloads").glob("*"))
        older_release = fixture_record(server, version="2026.07.5", release_id="75")
        write_json(fixture, {"releases": [older_release, draft, prerelease, normal]})
        older_fetch = service.fetch_release(release_id="75")
        assert older_fetch["status"] == "blocked" and not list((workspace / "downloads").glob("*"))
        write_json(fixture, {"releases": [draft, prerelease, normal]})
        incompatible_fetch_manifest = make_manifest(archive, minimum_current_version="2026.07.7")
        FixtureHandler.responses["/manifest"] = (200, {}, json.dumps(incompatible_fetch_manifest, sort_keys=True).encode("utf-8"))
        assert service.fetch_release()["status"] == "blocked"
        FixtureHandler.responses["/manifest"] = (200, {}, manifest_bytes)
        fetched = service.fetch_release()
        assert fetched["status"] == "pass" and fetched["state"] == "verifying" and fetched["source_tree"] == manifest["source_tree"]
        assert (workspace / fetched["archive_path"]).exists()
        (app_root / "VERSION").write_text("2026.07.7\n", encoding="utf-8")
        same_stage = service.stage_release(manifest_path=fetched["manifest_path"], archive_path=fetched["archive_path"])
        assert same_stage["status"] == "blocked"
        (app_root / "VERSION").write_text("2026.07.6\n", encoding="utf-8")
        incompatible_min_path = workspace / "downloads" / "incompatible-min.json"
        incompatible_max_path = workspace / "downloads" / "incompatible-max.json"
        write_json(incompatible_min_path, incompatible_fetch_manifest)
        write_json(
            incompatible_max_path,
            make_manifest(archive, minimum_current_version="2026.07.1", maximum_current_version="2026.07.5"),
        )
        assert service.stage_release(manifest_path=incompatible_min_path, archive_path=fetched["archive_path"])["status"] == "blocked"
        assert service.stage_release(manifest_path=incompatible_max_path, archive_path=fetched["archive_path"])["status"] == "blocked"
        staged = service.stage_release(manifest_path=fetched["manifest_path"], archive_path=fetched["archive_path"])
        assert staged["status"] == "pass" and staged["state"] == "staged" and staged["source_tree"] == manifest["source_tree"]
        assert (workspace / staged["staging_path"]).is_dir()
        backup = root / "backup-manifest.json"
        data_check = root / "data-check.json"
        write_formal_backup(app_root, backup)
        write_data_check(app_root, data_check)
        plan = service.prepare_online_update(
            stage_report_path=workspace / staged["report_paths"][0],
            backup_manifest_path=backup,
            data_check_report_path=data_check,
            maintenance_window="03:00-04:00",
        )
        assert plan["status"] == "pass" and plan["state"] == "planned"
        evidence = plan["input_evidence"]
        assert evidence["stage_report"]["path"].startswith("reports/")
        assert evidence["stage_report"]["sha256"] == sha256_file(workspace / staged["report_paths"][0])
        assert evidence["backup_manifest"]["sha256"] == sha256_file(backup)
        assert evidence["data_check_report"]["sha256"] == sha256_file(data_check)
        assert plan["source_tree"] == manifest["source_tree"]
        assert evidence["release_manifest"]["source_tree"] == manifest["source_tree"]
        assert all(item.startswith("No ") for item in plan["not_executed"])
        assert "operator-review" not in json.dumps(plan)
        forged_stage_payload = json.loads((workspace / staged["report_paths"][0]).read_text(encoding="utf-8"))
        forged_stage_payload["migration_required"] = True
        forged_stage_path = workspace / "reports" / "forged-stage-report.json"
        write_json(forged_stage_path, forged_stage_payload)
        assert service.prepare_online_update(stage_report_path=forged_stage_path, backup_manifest_path=backup, data_check_report_path=data_check)["status"] == "blocked"
        missing_tree_payload = json.loads((workspace / staged["report_paths"][0]).read_text(encoding="utf-8"))
        missing_tree_payload.pop("source_tree")
        missing_tree_path = workspace / "reports" / "missing-source-tree.json"
        write_json(missing_tree_path, missing_tree_payload)
        assert service.prepare_online_update(stage_report_path=missing_tree_path, backup_manifest_path=backup, data_check_report_path=data_check)["status"] == "blocked"
        stage_tree_tampered = json.loads((workspace / staged["report_paths"][0]).read_text(encoding="utf-8"))
        stage_tree_tampered["source_tree"] = "c" * 40
        stage_tree_tampered_path = workspace / "reports" / "tampered-source-tree.json"
        write_json(stage_tree_tampered_path, stage_tree_tampered)
        assert service.prepare_online_update(stage_report_path=stage_tree_tampered_path, backup_manifest_path=backup, data_check_report_path=data_check)["status"] == "blocked"
        manifest_tree_tampered = dict(manifest)
        manifest_tree_tampered["source_tree"] = "c" * 40
        manifest_tree_path = workspace / "downloads" / "tampered-source-tree-manifest.json"
        write_json(manifest_tree_path, manifest_tree_tampered)
        manifest_tree_report = json.loads((workspace / staged["report_paths"][0]).read_text(encoding="utf-8"))
        manifest_tree_report["manifest_path"] = "downloads/tampered-source-tree-manifest.json"
        manifest_tree_report["manifest_sha256"] = sha256_file(manifest_tree_path)
        manifest_tree_report_path = workspace / "reports" / "tampered-manifest-source-tree.json"
        write_json(manifest_tree_report_path, manifest_tree_report)
        assert service.prepare_online_update(stage_report_path=manifest_tree_report_path, backup_manifest_path=backup, data_check_report_path=data_check)["status"] == "blocked"
        incompatible_plan_path = workspace / "downloads" / "incompatible-plan-manifest.json"
        write_json(incompatible_plan_path, incompatible_fetch_manifest)
        incompatible_plan_report = json.loads((workspace / staged["report_paths"][0]).read_text(encoding="utf-8"))
        incompatible_plan_report["manifest_path"] = "downloads/incompatible-plan-manifest.json"
        incompatible_plan_report["manifest_sha256"] = sha256_file(incompatible_plan_path)
        incompatible_plan_report_path = workspace / "reports" / "incompatible-plan-stage.json"
        write_json(incompatible_plan_report_path, incompatible_plan_report)
        assert service.prepare_online_update(stage_report_path=incompatible_plan_report_path, backup_manifest_path=backup, data_check_report_path=data_check)["status"] == "blocked"
        outside_stage_report = root / "forged-stage-report.json"
        write_json(outside_stage_report, staged)
        outside_stage = service.prepare_online_update(
            stage_report_path=outside_stage_report,
            backup_manifest_path=backup,
            data_check_report_path=data_check,
        )
        assert outside_stage["status"] == "blocked"
        (app_root / "VERSION").write_text("2026.07.7\n", encoding="utf-8")
        same_plan = service.prepare_online_update(
            stage_report_path=workspace / staged["report_paths"][0],
            backup_manifest_path=backup,
            data_check_report_path=data_check,
        )
        assert same_plan["status"] == "blocked"
        (app_root / "VERSION").write_text("2026.07.6\n", encoding="utf-8")
        for field, value in (
            ("kind", "wrong-kind"),
            ("app_root", "/not-the-app-root"),
            ("source_database_size_bytes", 0),
            ("source_database_sha256", "0" * 64),
            ("source_database_journal_mode", "wal"),
            ("sqlite_backup_size_bytes", 0),
            ("sqlite_backup_sha256", "0" * 64),
            ("copied_at", "2000-01-01T00:00:00Z"),
        ):
            invalid_backup = json.loads(backup.read_text(encoding="utf-8"))
            invalid_backup[field] = value
            write_json(backup, invalid_backup)
            assert service.prepare_online_update(stage_report_path=workspace / staged["report_paths"][0], backup_manifest_path=backup, data_check_report_path=data_check)["status"] == "blocked"
            write_formal_backup(app_root, backup)
        for field, value in (("kind", "wrong-kind"), ("status", "fail"), ("app_root", "/not-the-app-root")):
            invalid_data = json.loads(data_check.read_text(encoding="utf-8"))
            invalid_data[field] = value
            write_json(data_check, invalid_data)
            assert service.prepare_online_update(stage_report_path=workspace / staged["report_paths"][0], backup_manifest_path=backup, data_check_report_path=data_check)["status"] == "blocked"
            write_data_check(app_root, data_check)
        source_database = app_root / "data" / "enterprise.db"
        original_database = source_database.read_bytes()
        wal_sidecar = Path(f"{source_database}-wal")
        shm_sidecar = Path(f"{source_database}-shm")
        try:
            set_journal_header(source_database, "wal")
            wal_sidecar.write_bytes(b"fixture-wal")
            shm_sidecar.write_bytes(b"fixture-shm")
            wal_backup = json.loads(backup.read_text(encoding="utf-8"))
            wal_backup["source_database_size_bytes"] = source_database.stat().st_size
            wal_backup["source_database_sha256"] = sha256_file(source_database)
            wal_backup["source_database_journal_mode"] = "wal"
            write_json(backup, wal_backup)
            before_database_sha256 = sha256_file(source_database)
            before_directory = directory_fingerprints(source_database.parent)
            wal_plan = service.prepare_online_update(
                stage_report_path=workspace / staged["report_paths"][0],
                backup_manifest_path=backup,
                data_check_report_path=data_check,
            )
            assert wal_plan["status"] == "pass"
            assert wal_plan["input_evidence"]["backup_manifest"]["source_database_journal_mode"] == "wal"
            assert wal_plan["input_evidence"]["backup_manifest"]["source_database_sidecars"]["wal"]["present"] is True
            assert wal_plan["input_evidence"]["backup_manifest"]["source_database_sidecars"]["shm"]["present"] is True
            assert sha256_file(source_database) == before_database_sha256
            assert directory_fingerprints(source_database.parent) == before_directory
            mismatch_backup = dict(wal_backup)
            mismatch_backup["source_database_journal_mode"] = "delete"
            write_json(backup, mismatch_backup)
            assert service.prepare_online_update(
                stage_report_path=workspace / staged["report_paths"][0],
                backup_manifest_path=backup,
                data_check_report_path=data_check,
            )["status"] == "blocked"
        finally:
            source_database.write_bytes(original_database)
            for sidecar in (wal_sidecar, shm_sidecar):
                if sidecar.exists():
                    sidecar.unlink()
            write_formal_backup(app_root, backup)
        assert "sqlite3.connect" not in (ROOT / "enterprise" / "ops" / "update" / "service.py").read_text(encoding="utf-8")
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
        cli_fetch = run_cli(
            app_root,
            workspace,
            "fetch-release",
            "--provider",
            "local-fixture",
            "--fixture",
            str(fixture),
        )
        assert cli_fetch["status"] == "pass"
        cli_stage = run_cli(
            app_root,
            workspace,
            "stage-release",
            "--manifest",
            cli_fetch["manifest_path"],
            "--archive",
            cli_fetch["archive_path"],
        )
        assert cli_stage["status"] == "pass" and cli_stage["state"] == "staged"
        cli_plan = run_cli(
            app_root,
            workspace,
            "prepare-online-update",
            "--stage-report",
            str(workspace / cli_stage["report_paths"][0]),
            "--backup-manifest",
            str(backup),
            "--data-check-report",
            str(data_check),
        )
        assert cli_plan["status"] == "pass" and cli_plan["state"] == "planned"
        assert not (app_root / "ops_artifacts").exists()

        staged_version = workspace / staged["staging_path"] / ROOT_PREFIX / "VERSION"
        staged_version.write_text("2026.07.999\n", encoding="utf-8")
        content_tampered_stage = service.prepare_online_update(
            stage_report_path=workspace / staged["report_paths"][0],
            backup_manifest_path=backup,
            data_check_report_path=data_check,
        )
        assert content_tampered_stage["status"] == "blocked"
        staged_version.write_text("2026.07.7\n", encoding="utf-8")
        (workspace / staged["staging_path"] / "extra-file").write_text("tampered", encoding="utf-8")
        tampered_stage = service.prepare_online_update(
            stage_report_path=workspace / staged["report_paths"][0],
            backup_manifest_path=backup,
            data_check_report_path=data_check,
        )
        assert tampered_stage["status"] == "blocked"
        (workspace / staged["staging_path"] / "extra-file").unlink()
        staged_archive = workspace / staged["archive_path"]
        staged_manifest = workspace / staged["manifest_path"]
        original_archive = staged_archive.read_bytes()
        original_manifest = staged_manifest.read_bytes()
        staged_archive.write_bytes(b"archive-tampered")
        assert service.prepare_online_update(stage_report_path=workspace / staged["report_paths"][0], backup_manifest_path=backup, data_check_report_path=data_check)["status"] == "blocked"
        staged_archive.write_bytes(original_archive)
        staged_manifest.write_bytes(b"manifest-tampered")
        assert service.prepare_online_update(stage_report_path=workspace / staged["report_paths"][0], backup_manifest_path=backup, data_check_report_path=data_check)["status"] == "blocked"
        staged_manifest.write_bytes(original_manifest)

        runtime_archive = make_archive(root / "runtime-release.zip", {f"{ROOT_PREFIX}/data/enterprise.db": b"runtime"})
        runtime_manifest = make_manifest(runtime_archive, file_count=1)
        runtime_manifest_path = workspace / "runtime-manifest.json"
        runtime_archive_path = workspace / runtime_manifest["archive"]["filename"]
        write_json(runtime_manifest_path, runtime_manifest)
        runtime_archive_path.write_bytes(runtime_archive)
        staging_before = sorted((workspace / "staging").iterdir())
        runtime_stage = service.stage_release(manifest_path=runtime_manifest_path, archive_path=runtime_archive_path)
        assert runtime_stage["status"] == "fail"
        assert sorted((workspace / "staging").iterdir()) == staging_before


def verify_job_redaction() -> None:
    with tempfile.TemporaryDirectory(prefix="ice-ops3a-job-") as raw:
        workspace = Path(raw)
        job = UpdateJob("check-update", workspace)
        job.transition("checking", **{"token": "nope"})
        job.transition("metadata_ready", **{"cookie": "nope"})
        job.complete()
        report = job.write_report(status="pass")
        job.append_log("tested", authorization="nope", nested={"api_key": "nope"})
        serialized = json.dumps(report) + (workspace / "jobs.jsonl").read_text(encoding="utf-8")
        assert "nope" not in serialized and "[redacted]" in serialized
        expect_error(OnlineUpdateValidationError, job.transition, "downloading")


def run_all() -> None:
    verify_versions_and_manifest()
    verify_http_and_download()
    verify_github_release_filtering()
    verify_private_github_asset_authorization()
    verify_zip_defences()
    verify_service_and_cli()
    verify_job_redaction()


if __name__ == "__main__":
    run_all()
    print("OPS-3A online update checks passed")
