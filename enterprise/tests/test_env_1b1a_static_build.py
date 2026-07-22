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
from enterprise.release.app_root_audit import (
    EXPECTED_SITE_MANIFEST_DIGEST,
    AuditMapping,
    FlowAnchor,
    audit_repository,
    evaluate_scan,
    scan_tracked_files,
    validate_flow_anchors,
)
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


def _write_css_fixture(root: Path) -> Path:
    source = root / "css-source"
    for directory in ("css/theme", "fonts", "images", "js"):
        (source / directory).mkdir(parents=True, exist_ok=True)
    (source / "fonts/site.ttf").write_bytes(b"font-v1")
    (source / "images/background.png").write_bytes(b"background-v1")
    (source / "images/icon.svg").write_bytes(b"<svg></svg>\n")
    (source / "js/unrelated.js").write_bytes(b"console.log('unrelated');\n")
    (source / "css/app.css").write_text(
        """@import url('theme/fonts.css');
@import "print.css" screen;
body { background: url('../images/background.png?theme=dark#hero'); }
.external { background: url(https://example.invalid/remote.png); }
.protocol { background: url(//cdn.example.invalid/remote.png); }
.data { background: url(data:image/png;base64,AAAA); }
.blob { background: url(blob:fixture); }
""",
        encoding="utf-8",
        newline="",
    )
    (source / "css/print.css").write_text(
        "@import 'theme/colors.css';\n@media print { body { color: black; } }\n",
        encoding="utf-8",
        newline="",
    )
    (source / "css/theme/colors.css").write_text(
        ":root { --brand: #123456; }\n", encoding="utf-8", newline=""
    )
    (source / "css/theme/fonts.css").write_text(
        """@font-face { src: url('../../fonts/site.ttf?v=old#font') format('truetype'); }
.icon { background: url('/static/images/icon.svg'); }
""",
        encoding="utf-8",
        newline="",
    )
    (source / "index.html").write_text(
        '<link href="css/app.css?v=legacy" rel="stylesheet">\n'
        '<script src="js/unrelated.js"></script>\n',
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
    assert baseline_report["html_build_id"] != changed_report["html_build_id"]
    assert (baseline_output / "index.html").read_bytes() != (changed_output / "index.html").read_bytes()
    assert (baseline_output / "nested/page.html").read_bytes() != (changed_output / "nested/page.html").read_bytes()
    assert f"nested/page.html?v={baseline_report['html_build_id']}" in (
        baseline_output / "index.html"
    ).read_text(encoding="utf-8")
    assert f"nested/page.html?v={changed_report['html_build_id']}" in (
        changed_output / "index.html"
    ).read_text(encoding="utf-8")
    assert (baseline_output / "nested/unrelated.html").read_bytes() == (
        changed_output / "nested/unrelated.html"
    ).read_bytes()


def test_css_import_graph_transitively_hashes_fonts_images_and_external_urls(tmp_path: Path) -> None:
    source = _write_css_fixture(tmp_path)
    output, _, report = _build(tmp_path, source, "css")
    resources = {item["path"]: item for item in report["resources"]}

    assert {
        "css/app.css",
        "css/print.css",
        "css/theme/colors.css",
        "css/theme/fonts.css",
        "fonts/site.ttf",
        "images/background.png",
        "images/icon.svg",
        "js/unrelated.js",
    } <= resources.keys()
    assert resources["fonts/site.ttf"]["sha256"] == _sha256(b"font-v1")
    assert resources["images/background.png"]["sha256"] == _sha256(b"background-v1")
    assert resources["css/app.css"]["version_policy"] == "transformed-css-sha256"
    assert report["css_dependency_order"].index("css/theme/fonts.css") < report[
        "css_dependency_order"
    ].index("css/app.css")
    assert report["css_dependency_order"].index("css/theme/colors.css") < report[
        "css_dependency_order"
    ].index("css/print.css")
    assert report["css_dependency_order"].index("css/print.css") < report[
        "css_dependency_order"
    ].index("css/app.css")
    assert report["css_transitive_resource_count"] >= 6

    app_css = (output / "css/app.css").read_text(encoding="utf-8")
    fonts_css = (output / "css/theme/fonts.css").read_text(encoding="utf-8")
    html = (output / "index.html").read_text(encoding="utf-8")
    assert f"theme/fonts.css?v={resources['css/theme/fonts.css']['sha256']}" in app_css
    assert f"print.css?v={resources['css/print.css']['sha256']}" in app_css
    assert f"../images/background.png?theme=dark&v={resources['images/background.png']['sha256']}#hero" in app_css
    assert f"../../fonts/site.ttf?v={resources['fonts/site.ttf']['sha256']}#font" in fonts_css
    assert f"/static/images/icon.svg?v={resources['images/icon.svg']['sha256']}" in fonts_css
    assert "url(https://example.invalid/remote.png)" in app_css
    assert "url(//cdn.example.invalid/remote.png)" in app_css
    assert "url(data:image/png;base64,AAAA)" in app_css
    assert "url(blob:fixture)" in app_css
    assert f"css/app.css?v={resources['css/app.css']['sha256']}" in html


def test_css_leaf_change_propagates_to_css_and_html_only(tmp_path: Path) -> None:
    baseline_root = tmp_path / "baseline-css"
    changed_root = tmp_path / "changed-css"
    baseline_root.mkdir()
    changed_root.mkdir()
    baseline_source = _write_css_fixture(baseline_root)
    changed_source = changed_root / "source"
    shutil.copytree(baseline_source, changed_source)
    (changed_source / "fonts/site.ttf").write_bytes(b"font-v2")

    baseline_output, _, baseline_report = _build(baseline_root, baseline_source, "release")
    changed_output, _, changed_report = _build(changed_root, changed_source, "release")
    before = {item["path"]: item["sha256"] for item in baseline_report["resources"]}
    after = {item["path"]: item["sha256"] for item in changed_report["resources"]}

    assert before["fonts/site.ttf"] != after["fonts/site.ttf"]
    assert before["css/theme/fonts.css"] != after["css/theme/fonts.css"]
    assert before["css/app.css"] != after["css/app.css"]
    assert before["images/background.png"] == after["images/background.png"]
    assert before["js/unrelated.js"] == after["js/unrelated.js"]
    assert (baseline_output / "css/theme/fonts.css").read_bytes() != (
        changed_output / "css/theme/fonts.css"
    ).read_bytes()
    assert (baseline_output / "css/app.css").read_bytes() != (
        changed_output / "css/app.css"
    ).read_bytes()
    assert (baseline_output / "index.html").read_bytes() != (
        changed_output / "index.html"
    ).read_bytes()


def test_css_import_cycle_fails_closed_with_stable_sanitized_code(tmp_path: Path) -> None:
    source = _write_css_fixture(tmp_path)
    (source / "css/theme/colors.css").write_text(
        "@import '../print.css';\n", encoding="utf-8", newline=""
    )
    before = _tree_bytes(source)
    output = tmp_path / "cycle-output"
    report = tmp_path / "cycle-report.json"
    with pytest.raises(StaticBuildError, match="css-import-cycle") as error:
        build_static_tree(source, output, report)
    assert error.value.code == "css-import-cycle"
    assert str(tmp_path) not in str(error.value)
    assert not output.exists()
    assert not report.exists()
    assert _tree_bytes(source) == before


@pytest.mark.parametrize(
    ("url", "expected_code"),
    [
        ("../images/missing.png", "local-resource-unresolved"),
        ("../../outside.png", "reference-escapes-source"),
    ],
)
def test_css_missing_or_escaping_resource_fails_closed(
    tmp_path: Path, url: str, expected_code: str
) -> None:
    source = _write_css_fixture(tmp_path)
    (source / "css/app.css").write_text(
        f"body {{ background: url('{url}'); }}\n", encoding="utf-8", newline=""
    )
    if expected_code == "reference-escapes-source":
        (tmp_path / "outside.png").write_bytes(b"outside")
    before = _tree_bytes(source)
    with pytest.raises(StaticBuildError, match=expected_code):
        build_static_tree(source, tmp_path / "bad-output", tmp_path / "bad-report.json")
    assert _tree_bytes(source) == before


def test_html_cycles_use_one_deterministic_build_id(tmp_path: Path) -> None:
    source = tmp_path / "html-cycle-source"
    (source / "nested").mkdir(parents=True)
    (source / "js").mkdir()
    (source / "a.html").write_text(
        '<a href="nested/b.html">B</a>\n', encoding="utf-8", newline=""
    )
    (source / "nested/b.html").write_text(
        '<a href="../a.html">A</a><script src="../js/app.js"></script>\n',
        encoding="utf-8",
        newline="",
    )
    (source / "js/app.js").write_bytes(b"app-v1")
    output, _, report = _build(tmp_path, source, "cycle")
    build_id = report["html_build_id"]
    assert report["html_version_policy"] == "builder-version-and-source-tree-sha256-v1"
    assert f"nested/b.html?v={build_id}" in (output / "a.html").read_text(encoding="utf-8")
    assert f"../a.html?v={build_id}" in (output / "nested/b.html").read_text(encoding="utf-8")


def test_html_build_id_includes_builder_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_root = tmp_path / "first-builder"
    second_root = tmp_path / "second-builder"
    first_root.mkdir()
    second_root.mkdir()
    first_source = _write_fixture(first_root)
    second_source = second_root / "source"
    shutil.copytree(first_source, second_source)
    _, _, first_report = _build(first_root, first_source, "release")
    monkeypatch.setattr(static_build, "BUILDER_VERSION", "env-1b1a-static-builder-test-version")
    _, _, second_report = _build(second_root, second_source, "release")
    assert first_report["source_tree_digest"] == second_report["source_tree_digest"]
    assert first_report["html_build_id"] != second_report["html_build_id"]


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
    resource_paths = {item["path"] for item in report["resources"]}
    assert "vendor/css/fonts.css" in resource_paths
    assert {
        "vendor/fonts/inter-1.ttf",
        "vendor/fonts/inter-2.ttf",
        "vendor/fonts/inter-3.ttf",
        "vendor/fonts/inter-4.ttf",
        "vendor/fonts/inter-5.ttf",
        "vendor/fonts/jetbrains-mono-6.ttf",
        "vendor/fonts/jetbrains-mono-7.ttf",
        "vendor/fonts/space-grotesk-8.ttf",
        "vendor/fonts/space-grotesk-9.ttf",
        "vendor/fonts/space-grotesk-10.ttf",
    } <= resource_paths
    assert _tree_bytes(source) == before


def _load_isolated_main(tmp_path: Path):
    app_root = tmp_path / "isolated-app"
    app_root.mkdir()
    shutil.copyfile(REPO_ROOT / "main.py", app_root / "main.py")
    static_root = _write_fixture(app_root)
    static_root.rename(app_root / "static")
    before = _tree_bytes(app_root / "static")
    from enterprise.paths import (
        _reset_path_roots_for_tests,
        derive_development_path_roots,
        install_path_roots_for_process,
    )
    _reset_path_roots_for_tests()
    install_path_roots_for_process(derive_development_path_roots(app_root))
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
    # Restore a source-anchored development root for later tests.  The isolated
    # main import above intentionally exercises explicit process installation.
    from enterprise.paths import _reset_path_roots_for_tests, derive_development_path_roots, install_path_roots_for_process
    _reset_path_roots_for_tests()
    install_path_roots_for_process(derive_development_path_roots(REPO_ROOT))


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
    result = audit_repository(REPO_ROOT)
    assert result.ok, {
        "statistics": result.statistics,
        "parse_failures": result.scan.parse_failures,
        "uncovered": result.uncovered_sites,
        "stale": result.stale_mappings,
        "missing_anchors": result.missing_flow_anchors,
        "invalid_flows": result.invalid_flow_ids,
    }
    assert result.site_manifest_digest == EXPECTED_SITE_MANIFEST_DIGEST
    assert result.statistics["scanned_files"] >= 1
    assert result.statistics["excluded_files"] >= 1
    assert result.statistics["detected_sites"] == result.statistics["mapped_sites"]
    assert result.statistics["detected_sites"] >= 1
    assert result.statistics["parse_failures"] == 0
    assert result.statistics["uncovered_sites"] == 0
    assert result.statistics["stale_audit_mappings"] == 0


def _evaluate_fixture_audit(
    root: Path,
    tracked_files: tuple[str, ...],
    mappings: tuple[AuditMapping, ...],
    anchors: tuple[FlowAnchor, ...],
):
    scan = scan_tracked_files(root, tracked_files)
    missing = validate_flow_anchors(root, anchors)
    required = frozenset(anchor.flow_id for anchor in anchors)
    return evaluate_scan(
        scan,
        mappings,
        anchors,
        required_flow_ids=required,
        missing_flow_anchors=missing,
    )


def test_audit_new_write_in_existing_symbol_fails(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_text(
        "def audited():\n    open('one.txt', 'w').close()\n",
        encoding="utf-8",
        newline="",
    )
    mapping = (AuditMapping("module.py", "audited", "open-write", 1, "W01"),)
    anchors = (FlowAnchor("W01", "module.py", "audited"),)
    baseline = _evaluate_fixture_audit(tmp_path, ("module.py",), mapping, anchors)
    assert baseline.ok

    source.write_text(
        "def audited():\n"
        "    open('one.txt', 'w').close()\n"
        "    open('two.txt', 'w').close()\n",
        encoding="utf-8",
        newline="",
    )
    drifted = _evaluate_fixture_audit(tmp_path, ("module.py",), mapping, anchors)
    assert not drifted.ok
    assert len(drifted.uncovered_sites) == 1
    assert len(drifted.stale_mappings) == 1
    assert drifted.uncovered_sites[0].symbol == "audited"


def test_audit_new_write_in_existing_script_fails(tmp_path: Path) -> None:
    script = tmp_path / "runner.ps1"
    script.write_text("'one' | Set-Content one.txt\n", encoding="utf-8", newline="")
    mapping = (AuditMapping("runner.ps1", "<script>", "script-write", 1, "W01"),)
    anchors = (FlowAnchor("W01", "runner.ps1"),)
    baseline = _evaluate_fixture_audit(tmp_path, ("runner.ps1",), mapping, anchors)
    assert baseline.ok

    script.write_text(
        "'one' | Set-Content one.txt\n' two' | Add-Content two.txt\n",
        encoding="utf-8",
        newline="",
    )
    drifted = _evaluate_fixture_audit(tmp_path, ("runner.ps1",), mapping, anchors)
    assert not drifted.ok
    assert len(drifted.uncovered_sites) == 1
    assert len(drifted.stale_mappings) == 1


def test_audit_python_syntax_error_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "broken.py"
    source.write_text("def broken(:\n    pass\n", encoding="utf-8", newline="")
    anchors = (FlowAnchor("W01", "broken.py", "broken"),)
    result = _evaluate_fixture_audit(tmp_path, ("broken.py",), (), anchors)
    assert not result.ok
    assert result.scan.parse_failures[0].code == "python-syntax-error"
    assert result.missing_flow_anchors


def test_audit_unmapped_site_and_stale_mapping_fail(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_text(
        "def audited():\n    open('one.txt', 'w').close()\n",
        encoding="utf-8",
        newline="",
    )
    anchors = (FlowAnchor("W01", "module.py", "audited"),)
    unmapped = _evaluate_fixture_audit(tmp_path, ("module.py",), (), anchors)
    assert not unmapped.ok
    assert len(unmapped.uncovered_sites) == 1

    stale_mapping = (
        AuditMapping("module.py", "audited", "open-write", 1, "W01"),
        AuditMapping("module.py", "audited", "write_text", 1, "W01"),
    )
    stale = _evaluate_fixture_audit(tmp_path, ("module.py",), stale_mapping, anchors)
    assert not stale.ok
    assert any("write_text" in item for item in stale.stale_mappings)


def test_audit_missing_required_wxx_anchor_fails(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_text("def anchor():\n    return 1\n", encoding="utf-8", newline="")
    scan = scan_tracked_files(tmp_path, ("module.py",))
    anchors = (FlowAnchor("W01", "module.py", "anchor"),)
    result = evaluate_scan(
        scan,
        (),
        anchors,
        required_flow_ids=frozenset({"W01", "W02"}),
        missing_flow_anchors=validate_flow_anchors(tmp_path, anchors),
    )
    assert not result.ok
    assert "W02:missing-flow-anchor-declaration" in result.stale_mappings


def test_audit_uses_explicit_tracked_files_not_untracked_noise(tmp_path: Path) -> None:
    tracked = tmp_path / "tracked.py"
    tracked.write_text("def stable():\n    return 1\n", encoding="utf-8", newline="")
    untracked = tmp_path / "untracked.py"
    untracked.write_text(
        "def noisy():\n    open('noise.txt', 'w').close()\n",
        encoding="utf-8",
        newline="",
    )
    scan = scan_tracked_files(tmp_path, ("tracked.py",))
    assert scan.scanned_files == ("tracked.py",)
    assert scan.sites == ()
