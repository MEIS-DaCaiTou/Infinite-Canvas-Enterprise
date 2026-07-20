from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from enterprise.release import static_build
from enterprise.release.app_root_audit import missing_audit_anchors, uncovered_write_sites
from enterprise.release.static_build import StaticBuildError, build_static_tree


REPO_ROOT = Path(__file__).resolve().parents[2]


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_fixture(root: Path) -> Path:
    source = root / "source static"
    for directory in ("css", "empty/deep", "fonts", "images", "js", "nested"):
        (source / directory).mkdir(parents=True, exist_ok=True)
    files = {
        "js/app.js": b"console.log('stable');\n",
        "css/site.css": b"body { color: #123; }\n",
        "fonts/site.woff2": b"woff2-bytes",
        "images/picture.png": b"png-bytes",
        "images/photo.jpg": b"jpeg-bytes",
        "images/image.webp": b"webp-bytes",
        "images/vector.svg": b"<svg></svg>\n",
        "images/space \u4e2d\u6587.png": b"encoded-name",
        "nested/page.html": b'<script src="../js/app.js?v=legacy"></script>\n',
        "nested/unrelated.html": b'<link href="../css/site.css" rel="stylesheet">\n',
    }
    for relative, content in files.items():
        (source / relative).write_bytes(content)
    (source / "index.html").write_text(
        """<!doctype html>
<script src="/static/js/app.js?v=first&theme=dark&v=old#load"></script>
<link href="css/site.css?theme=dark&v=old#colors" rel="stylesheet">
<img src="images/picture.png"><img src="images/photo.jpg">
<img src="images/image.webp"><img src="images/vector.svg">
<img src="images/space%20%E4%B8%AD%E6%96%87.png">
<style>@font-face { src: url('/static/fonts/site.woff2?v=old#font'); }</style>
<iframe data-src="/static/nested/page.html?v=old"></iframe>
<a href="https://example.invalid/app.css?v=remote">external</a>
<img src="data:image/png;base64,AAAA"><img src="blob:fixture">
<a href="mailto:test@example.invalid">mail</a>
<a href="javascript:void(0)">script</a>
""",
        encoding="utf-8",
        newline="",
    )
    return source


def _build(root: Path, source: Path, name: str) -> tuple[Path, Path, dict[str, object]]:
    output = root / f"{name}-output"
    report = root / f"{name}-report.json"
    payload = build_static_tree(source, output, report)
    return output, report, payload


def test_deterministic_outputs_reports_and_mtime_independence(tmp_path: Path) -> None:
    first_root = tmp_path / "first location"
    second_root = tmp_path / "\u7b2c\u4e8c\u4e2a\u4e34\u65f6\u76ee\u5f55"
    first_root.mkdir()
    second_root.mkdir()
    first_source = _write_fixture(first_root)
    second_source = second_root / "different source name"
    shutil.copytree(first_source, second_source)

    for path in second_source.rglob("*"):
        if path.is_file():
            os.utime(path, (1_700_000_000, 1_700_000_000))

    first_output, first_report, first_payload = _build(first_root, first_source, "build")
    second_output, second_report, second_payload = _build(second_root, second_source, "build")

    assert _tree_bytes(first_output) == _tree_bytes(second_output)
    assert (first_output / "empty/deep").is_dir()
    assert first_payload == second_payload
    assert first_report.read_bytes() == second_report.read_bytes()
    assert first_payload["output_tree_digest"] == second_payload["output_tree_digest"]
    report_text = first_report.read_text(encoding="utf-8")
    assert str(tmp_path) not in report_text
    assert "timestamp" not in report_text.lower()
    assert "mtime" not in report_text.lower()


def test_resource_types_queries_fragments_and_external_urls(tmp_path: Path) -> None:
    source = _write_fixture(tmp_path)
    output, _, report = _build(tmp_path, source, "types")
    html = (output / "index.html").read_text(encoding="utf-8")
    resources = {item["path"]: item["sha256"] for item in report["resources"]}

    expected_paths = {
        "css/site.css",
        "fonts/site.woff2",
        "images/image.webp",
        "images/photo.jpg",
        "images/picture.png",
        "images/space \u4e2d\u6587.png",
        "images/vector.svg",
        "js/app.js",
        "nested/page.html",
    }
    assert expected_paths <= resources.keys()
    assert all(len(value) == 64 and value == value.lower() for value in resources.values())
    assert f"/static/js/app.js?theme=dark&v={resources['js/app.js']}#load" in html
    assert html.count(f"/static/js/app.js?theme=dark&v={resources['js/app.js']}#load") == 1
    assert f"css/site.css?theme=dark&v={resources['css/site.css']}#colors" in html
    assert f"/static/fonts/site.woff2?v={resources['fonts/site.woff2']}#font" in html
    encoded_name_hash = resources["images/space \u4e2d\u6587.png"]
    assert f"images/space%20%E4%B8%AD%E6%96%87.png?v={encoded_name_hash}" in html
    assert "https://example.invalid/app.css?v=remote" in html
    assert "data:image/png;base64,AAAA" in html
    assert "blob:fixture" in html
    assert "mailto:test@example.invalid" in html
    assert "javascript:void(0)" in html
    assert report["skipped_external_url_count"] == 5
    assert report["unresolved_references"] == []


def test_nested_html_uses_its_own_directory(tmp_path: Path) -> None:
    source = _write_fixture(tmp_path)
    output, _, report = _build(tmp_path, source, "nested")
    resources = {item["path"]: item["sha256"] for item in report["resources"]}
    nested = (output / "nested/page.html").read_text(encoding="utf-8")
    assert f"../js/app.js?v={resources['js/app.js']}" in nested


def test_content_change_is_scoped(tmp_path: Path) -> None:
    baseline_root = tmp_path / "baseline"
    changed_root = tmp_path / "changed"
    baseline_root.mkdir()
    changed_root.mkdir()
    baseline_source = _write_fixture(baseline_root)
    changed_source = changed_root / "source"
    shutil.copytree(baseline_source, changed_source)
    (changed_source / "js/app.js").write_bytes((changed_source / "js/app.js").read_bytes() + b"!")

    baseline_output, _, baseline_report = _build(baseline_root, baseline_source, "release")
    changed_output, _, changed_report = _build(changed_root, changed_source, "release")
    before = {item["path"]: item["sha256"] for item in baseline_report["resources"]}
    after = {item["path"]: item["sha256"] for item in changed_report["resources"]}

    assert before["js/app.js"] != after["js/app.js"]
    assert before["css/site.css"] == after["css/site.css"]
    assert (baseline_output / "index.html").read_bytes() != (changed_output / "index.html").read_bytes()
    assert (baseline_output / "nested/page.html").read_bytes() != (changed_output / "nested/page.html").read_bytes()
    assert (baseline_output / "nested/unrelated.html").read_bytes() == (
        changed_output / "nested/unrelated.html"
    ).read_bytes()


def test_source_tree_is_unchanged_on_success_and_repeated_build(tmp_path: Path) -> None:
    source = _write_fixture(tmp_path)
    before = _tree_bytes(source)
    first_output, _, first_report = _build(tmp_path, source, "first")
    second_output, _, second_report = _build(tmp_path, source, "second")
    assert _tree_bytes(source) == before
    assert not any(path.name.endswith(".tmp") for path in source.rglob("*"))
    assert _tree_bytes(first_output) == _tree_bytes(second_output)
    assert first_report == second_report


def test_missing_local_resource_fails_closed_without_source_or_report_changes(tmp_path: Path) -> None:
    source = _write_fixture(tmp_path)
    (source / "index.html").write_text('<script src="missing.js"></script>', encoding="utf-8")
    before = _tree_bytes(source)
    output = tmp_path / "failed-output"
    report = tmp_path / "failed-report.json"
    with pytest.raises(StaticBuildError, match="local-resource-unresolved") as error:
        build_static_tree(source, output, report)
    assert str(tmp_path) not in str(error.value)
    assert _tree_bytes(source) == before
    assert not output.exists()
    assert not report.exists()


@pytest.mark.parametrize("relationship", ["same", "inside"])
def test_source_output_relationships_fail_closed(tmp_path: Path, relationship: str) -> None:
    source = _write_fixture(tmp_path)
    output = source if relationship == "same" else source / "generated"
    with pytest.raises(StaticBuildError):
        build_static_tree(source, output, tmp_path / f"{relationship}.json")


def test_existing_output_even_when_empty_fails_closed(tmp_path: Path) -> None:
    source = _write_fixture(tmp_path)
    output = tmp_path / "existing"
    output.mkdir()
    with pytest.raises(StaticBuildError, match="output-already-exists"):
        build_static_tree(source, output, tmp_path / "report.json")


def test_existing_report_is_not_overwritten(tmp_path: Path) -> None:
    source = _write_fixture(tmp_path)
    report = tmp_path / "existing-report.json"
    report.write_text("sentinel", encoding="utf-8")
    output = tmp_path / "report-race-output"
    with pytest.raises(StaticBuildError, match="report-already-exists"):
        build_static_tree(source, output, report)
    assert report.read_text(encoding="utf-8") == "sentinel"
    assert not output.exists()


def test_reference_escape_fails_closed(tmp_path: Path) -> None:
    source = _write_fixture(tmp_path)
    (tmp_path / "outside.js").write_text("outside", encoding="utf-8")
    (source / "index.html").write_text('<script src="../outside.js"></script>', encoding="utf-8")
    with pytest.raises(StaticBuildError, match="reference-escapes-source"):
        build_static_tree(source, tmp_path / "escape-output", tmp_path / "escape-report.json")


def test_source_symlink_or_reparse_marker_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _write_fixture(tmp_path)
    outside = tmp_path / "outside.js"
    outside.write_text("outside", encoding="utf-8")
    link = source / "js/link.js"
    try:
        link.symlink_to(outside)
    except OSError:
        link.write_text("simulated-reparse-entry", encoding="utf-8")
        original = static_build._has_reparse_point
        monkeypatch.setattr(
            static_build,
            "_has_reparse_point",
            lambda path: path == link or original(path),
        )
    with pytest.raises(StaticBuildError, match="source-reparse-point"):
        build_static_tree(source, tmp_path / "link-output", tmp_path / "link-report.json")


def test_cli_requires_explicit_paths_and_builds_without_network(tmp_path: Path) -> None:
    source = _write_fixture(tmp_path)
    cli = REPO_ROOT / "tools/build_release_static.py"
    missing = subprocess.run([sys.executable, str(cli)], capture_output=True, text=True, check=False)
    assert missing.returncode != 0
    output = tmp_path / "cli-output"
    report = tmp_path / "cli-report.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(cli),
            "--source-static-root",
            str(source),
            "--output-static-root",
            str(output),
            "--report",
            str(report),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(report.read_text(encoding="utf-8"))["result"] == "pass"


def test_repository_static_tree_builds_only_in_temporary_staging(tmp_path: Path) -> None:
    source = REPO_ROOT / "static"
    before = _tree_bytes(source)
    output = tmp_path / "repository-static-output"
    report_path = tmp_path / "repository-static-report.json"
    report = build_static_tree(source, output, report_path)
    assert report["result"] == "pass"
    assert report["html_file_count"] >= 1
    assert report["static_resource_count"] >= 1
    assert _tree_bytes(source) == before


def _load_isolated_main(tmp_path: Path):
    app_root = tmp_path / "isolated-app"
    app_root.mkdir()
    shutil.copyfile(REPO_ROOT / "main.py", app_root / "main.py")
    static_root = _write_fixture(app_root)
    static_root.rename(app_root / "static")
    before = _tree_bytes(app_root / "static")
    module_name = f"env_1b1a_main_{uuid.uuid4().hex}"
    specification = importlib.util.spec_from_file_location(module_name, app_root / "main.py")
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module, app_root / "static", before


def test_main_import_and_fastapi_startup_do_not_modify_static(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module, static_root, before = _load_isolated_main(tmp_path)
    assert _tree_bytes(static_root) == before
    response = module.static_html_response("index.html")
    assert response.body == before["index.html"]
    called: list[str] = []
    for name in (
        "migrate_asset_library_into_dirs",
        "migrate_double_extension_uploads",
        "migrate_mislabeled_image_extensions",
    ):
        monkeypatch.setattr(module, name, lambda target=name: called.append(target))
    asyncio.run(module.startup_event())
    assert _tree_bytes(static_root) == before
    assert called == [
        "migrate_asset_library_into_dirs",
        "migrate_double_extension_uploads",
        "migrate_mislabeled_image_extensions",
    ]


def test_main_no_longer_contains_runtime_static_version_sync() -> None:
    source = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
    assert "sync_static_html_versions" not in source
    assert "versioned_static_html" not in source
    response_slice = source[
        source.index("def static_html_response") : source.index("STATIC_PROMPT_TEMPLATE_MD")
    ]
    assert "getmtime(" not in response_slice
    startup_slice = source[source.index("async def startup_event") : source.index('@app.websocket("/ws/stats")')]
    for migration in (
        "migrate_asset_library_into_dirs",
        "migrate_double_extension_uploads",
        "migrate_mislabeled_image_extensions",
    ):
        assert migration in startup_slice


def test_app_root_write_audit_anchors_and_structural_coverage() -> None:
    assert missing_audit_anchors(REPO_ROOT) == []
    assert uncovered_write_sites(REPO_ROOT) == []
