"""Repeatable structural coverage check for the ENV-1B1A write audit.

This is not a claim that static analysis can prove the absence of every write.
It combines Python AST inspection, focused script scanning, and an explicit
symbol inventory.  A newly introduced obvious write in production code fails
coverage until the audit inventory is reviewed.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, order=True)
class WriteSite:
    file: str
    symbol: str
    operation: str
    line: int


_MAIN_SYMBOLS = frozenset(
    {
        "<module>",
        "_local_upload_item",
        "_write_local_upload_classification",
        "apimart_upload_file_payload",
        "apimart_upload_payload_from_bytes",
        "batch_crop_asset_library_items",
        "caption_local_assets",
        "cleanup_expired_canvas_trash",
        "codex_chat_text",
        "codex_postprocess_image_to_requested_size",
        "codex_prepare_local_media",
        "codex_reference_paths",
        "compress_data_url_image",
        "convert_output_to_jpg",
        "create_asset_library_category",
        "create_local_asset_folder",
        "delete_asset_library_category",
        "delete_conversation",
        "delete_history",
        "delete_local_assets",
        "delete_project",
        "delete_workflow",
        "download_comfy_output",
        "download_github_update_files",
        "download_image",
        "download_modelscope_update_files",
        "ensure_runtime_config_files",
        "export_smart_canvas_group",
        "gemini_cli_chat_text",
        "generate_angle_cloud",
        "generate_cloud",
        "generate_codex_provider_image",
        "generate_gemini_cli_provider_image",
        "generate_jimeng_provider_image",
        "generate_jimeng_video",
        "generate_video_preview_image",
        "image_jpeg._build",
        "image_output_meta",
        "image_path_to_data_url",
        "image_size_from_reference",
        "import_canvas_workflow",
        "import_local_assets_from_urls",
        "import_local_image_file",
        "jimeng_local_output_url",
        "jimeng_prepare_local_media",
        "make_asset_library_item",
        "make_workflow_library_item_from_bytes",
        "media_preview._build_preview",
        "migrate_asset_library_into_dirs",
        "migrate_double_extension_uploads",
        "migrate_mislabeled_image_extensions",
        "move_local_assets",
        "ms_generate",
        "poll_angle_cloud",
        "purge_canvas",
        "reference_to_data_url",
        "remove_asset_library_file",
        "rename_local_asset_folder",
        "rename_local_asset_item",
        "rollback_update",
        "run_codex_cli",
        "runninghub_store_remote_output",
        "save_ai_image_to_output",
        "save_api_providers",
        "save_asset_library",
        "save_canvas",
        "save_comfy_text_output",
        "save_conversation",
        "save_local_asset_caption",
        "save_projects",
        "save_prompt_libraries",
        "save_remote_video_to_output",
        "save_runninghub_workflow_store",
        "save_to_history",
        "save_workflow_config",
        "schedule_self_restart",
        "shared_folders_save",
        "smart_group_export_folder",
        "update_canvas_meta",
        "update_env_values",
        "update_from_github",
        "upload_ai_base64",
        "upload_ai_reference",
        "upload_local_assets",
        "upload_workflow",
        "user_dir",
        "video_reference_to_frame_data_urls",
        "xlsx_embedded_image_data_urls",
    }
)

# Symbols are functional audit anchors. Multiple calls in one symbol belong to
# one documented write flow; a new symbol is treated as a new write point.
AUDITED_PRODUCTION_SYMBOLS: dict[str, frozenset[str]] = {
    "main.py": _MAIN_SYMBOLS,
    "enterprise/db.py": frozenset({"get_db", "set_canvas_project"}),
    "enterprise/interceptors.py": frozenset({"_write_history_records", "normalize_resource_url"}),
    "enterprise/migrations/sec_1b1_role_auth.py": frozenset({"_open_connection"}),
    "enterprise/migrations/sqlite_existing.py": frozenset({"open_existing_sqlite"}),
    "enterprise/ops/runner.py": frozenset(
        {"append_jsonl", "backup_sqlite_database", "copy_backup_items", "sqlite_connect_readonly", "write_json"}
    ),
    "enterprise/ops/update/download.py": frozenset({"atomic_download"}),
    "enterprise/ops/update/http_client.py": frozenset({"SafeHttpClient.stream"}),
    "enterprise/ops/update/jobs.py": frozenset({"UpdateJob.append_log", "_atomic_json_create"}),
    "enterprise/ops/update/staging.py": frozenset({"stage_release_archive"}),
    "enterprise/release/static_build.py": frozenset(
        {"_atomic_write_report", "_copy_tree", "build_static_tree"}
    ),
    "enterprise/runtime/child.py": frozenset({"_serve"}),
    "enterprise/runtime/control.py": frozenset(
        {"_discard_bootstrap_failure", "_prepare_bootstrap_failure_path"}
    ),
    "enterprise/runtime/host.py": frozenset({"_write_bootstrap_failure"}),
    "enterprise/runtime/logging.py": frozenset(
        {"RotatingTextLog.__init__", "RotatingTextLog._rotate_locked", "RotatingTextLog.write", "RuntimeLogs.__init__"}
    ),
    "enterprise/runtime/process.py": frozenset({"graceful_stop", "start_process"}),
    "enterprise/runtime/state.py": frozenset(
        {
            "RuntimeStateStore.acquire_foreground_lock",
            "RuntimeStateStore.clear_stale_lock",
            "RuntimeStateStore.consume_commands",
            "RuntimeStateStore.initialize",
            "RuntimeStateStore.purge_control",
            "RuntimeStateStore.release_lock",
            "RuntimeStateStore.remove_ack",
            "RuntimeStateStore.reserve_lock",
            "_atomic_json_replace",
        }
    ),
    "get-pip.py": frozenset({"main", "monkeypatch_for_cert"}),
    "tools/sec_1b2_local_runner.py": frozenset({"_write_final_json", "_write_new_json"}),
}

AUDITED_SCRIPT_FILES = frozenset(
    {
        "_self_restart.bat",
        "enterprise/tests/test_start_stop.ps1",
        "tools/jimeng_cli_install.ps1",
        "tools/jimeng_cli_login.ps1",
        "tools/ops/windows/run-ops2a-backup-execute.ps1",
        "tools/ops/windows/run-ops2a-prod-dryrun.ps1",
        "tools/photoshop-asset-connector/js/agent.js",
        "tools/photoshop-asset-connector/js/app.js",
        "tools/photoshop-asset-connector/js/net.js",
        "tools/photoshop-asset-connector/js/ps.js",
        "tools/chrome-local-asset-importer/popup.js",
        "安装依赖.bat",
    }
)

_PATH_METHODS = frozenset({"mkdir", "rename", "replace", "rmdir", "touch", "unlink", "write_bytes", "write_text"})
_OS_WRITES = frozenset({"makedirs", "mkdir", "remove", "removedirs", "rename", "replace", "rmdir", "unlink"})
_SHUTIL_WRITES = frozenset({"copy", "copy2", "copyfile", "copytree", "move", "rmtree"})
_TEMP_WRITES = frozenset({"NamedTemporaryFile", "TemporaryDirectory", "mkdtemp", "mkstemp"})
_SCRIPT_WRITE_PATTERN = re.compile(
    r"(?i)(?:Out-File|Set-Content|Add-Content|New-Item|Copy-Item|Move-Item|Remove-Item|"
    r"Start-Transcript|Invoke-WebRequest[^\r\n]*-OutFile|localStorage\.setItem|>>\s*(?!nul\b|\$null\b))"
)


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _write_open(call: ast.Call, full_name: str) -> bool:
    if full_name == "open":
        mode_index = 1
    elif full_name.endswith(".open"):
        mode_index = 0
    else:
        return False
    mode: str | None = "r"
    if len(call.args) > mode_index:
        value = call.args[mode_index]
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            mode = value.value
        elif full_name == "open":
            mode = None
    for keyword in call.keywords:
        if keyword.arg == "mode":
            mode = str(keyword.value.value) if isinstance(keyword.value, ast.Constant) else None
    return mode is None or any(character in mode for character in "wax+")


class _WriteVisitor(ast.NodeVisitor):
    def __init__(self, relative_file: str) -> None:
        self.relative_file = relative_file
        self.stack: list[str] = []
        self.sites: list[WriteSite] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        full_name = _call_name(node.func)
        attribute = node.func.attr if isinstance(node.func, ast.Attribute) else full_name
        operation = ""
        if _write_open(node, full_name):
            operation = "open-write"
        elif attribute in _PATH_METHODS:
            # String.replace is deliberately excluded unless its receiver looks
            # path-like. os.replace is handled below.
            if attribute != "replace":
                operation = attribute
            elif full_name == "os.replace" or re.search(r"(?:path|source|destination|temporary)\.replace$", full_name):
                operation = "replace"
        elif full_name.startswith("os.") and attribute in _OS_WRITES:
            operation = full_name
        elif full_name.startswith("shutil.") and attribute in _SHUTIL_WRITES:
            operation = full_name
        elif full_name.startswith("tempfile.") and attribute in _TEMP_WRITES:
            operation = full_name
        elif full_name in {"json.dump", "logging.FileHandler", "sqlite3.connect", "urllib.request.urlretrieve"}:
            operation = full_name
        elif attribute in {"extract", "extractall"} and "zip" in full_name.lower():
            operation = "zip-extract"
        elif attribute == "save":
            operation = "save"
        if operation:
            self.sites.append(
                WriteSite(
                    file=self.relative_file,
                    symbol=".".join(self.stack) or "<module>",
                    operation=operation,
                    line=node.lineno,
                )
            )
        self.generic_visit(node)


def scan_repository(repo_root: Path) -> list[WriteSite]:
    sites: list[WriteSite] = []
    ignored_parts = {".git", ".pytest_cache", "__pycache__", "node_modules", "python"}
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file() or any(part in ignored_parts for part in path.parts):
            continue
        relative = path.relative_to(repo_root).as_posix()
        if path.suffix.lower() == ".py":
            try:
                tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=relative)
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            visitor = _WriteVisitor(relative)
            visitor.visit(tree)
            sites.extend(visitor.sites)
        elif path.suffix.lower() in {".bat", ".cmd", ".js", ".ps1"}:
            try:
                text = path.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                if _SCRIPT_WRITE_PATTERN.search(line):
                    sites.append(WriteSite(relative, "<script>", "script-write", line_number))
    return sorted(set(sites))


def uncovered_write_sites(repo_root: Path) -> list[WriteSite]:
    uncovered: list[WriteSite] = []
    for site in scan_repository(repo_root):
        if site.file.startswith("enterprise/tests/"):
            continue
        if site.file.startswith(("enterprise-static/", "static/")):
            # Browser storage belongs to the client cache, not APP_ROOT. The
            # shipped browser trees are covered as one explicit audit class.
            continue
        if site.file in AUDITED_SCRIPT_FILES:
            continue
        if site.symbol in AUDITED_PRODUCTION_SYMBOLS.get(site.file, frozenset()):
            continue
        uncovered.append(site)
    return uncovered


def missing_audit_anchors(repo_root: Path) -> list[str]:
    missing: list[str] = []
    for relative_file, symbols in AUDITED_PRODUCTION_SYMBOLS.items():
        source_path = repo_root / relative_file
        if not source_path.is_file():
            missing.append(f"missing-file:{relative_file}")
            continue
        try:
            tree = ast.parse(source_path.read_text(encoding="utf-8-sig"), filename=relative_file)
        except (OSError, SyntaxError, UnicodeDecodeError):
            missing.append(f"unreadable-file:{relative_file}")
            continue
        defined = {"<module>"}
        stack: list[str] = []

        class DefinitionVisitor(ast.NodeVisitor):
            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                stack.append(node.name)
                defined.add(".".join(stack))
                self.generic_visit(node)
                stack.pop()

            visit_AsyncFunctionDef = visit_FunctionDef

        DefinitionVisitor().visit(tree)
        for symbol in symbols:
            if symbol not in defined:
                missing.append(f"missing-symbol:{relative_file}:{symbol}")
    for relative_file in AUDITED_SCRIPT_FILES:
        if not (repo_root / relative_file).is_file():
            missing.append(f"missing-script:{relative_file}")
    return sorted(missing)
