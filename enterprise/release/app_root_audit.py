"""Tracked-file drift gate for the ENV-1B1A APP_ROOT write audit.

The scanner is deliberately a conservative maintenance control, not a proof
that static analysis can discover every possible write. It combines Python AST
inspection, focused script inspection, stable call fingerprints, frozen
operation counts, and W01-W40 flow anchors.
"""

from __future__ import annotations

import ast
import hashlib
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


_FLOW_IDS = frozenset(f"W{number:02d}" for number in range(1, 41))
_SCANNED_SUFFIXES = frozenset({".bat", ".cmd", ".js", ".ps1", ".py"})
_EXCLUDED_PREFIXES = ("enterprise/tests/", "enterprise-static/", "static/")
_PATH_METHODS = frozenset(
    {"mkdir", "rename", "replace", "rmdir", "touch", "unlink", "write_bytes", "write_text"}
)
_OS_WRITES = frozenset(
    {"makedirs", "mkdir", "remove", "removedirs", "rename", "replace", "rmdir", "unlink"}
)
_SHUTIL_WRITES = frozenset({"copy", "copy2", "copyfile", "copytree", "move", "rmtree"})
_TEMP_WRITES = frozenset({"NamedTemporaryFile", "TemporaryDirectory", "mkdtemp", "mkstemp"})
_SCRIPT_WRITE_PATTERN = re.compile(
    r"(?i)(?:Out-File|Set-Content|Add-Content|New-Item|Copy-Item|Move-Item|Remove-Item|"
    r"Start-Transcript|Invoke-WebRequest[^\r\n]*-OutFile|localStorage\.setItem|>>\s*(?!nul\b|\$null\b))"
)


@dataclass(frozen=True, order=True)
class WriteSite:
    file: str
    symbol: str
    operation: str
    fingerprint: str
    line: int

    @property
    def operation_key(self) -> tuple[str, str, str]:
        return self.file, self.symbol, self.operation


@dataclass(frozen=True, order=True)
class ParseFailure:
    file: str
    code: str


@dataclass(frozen=True)
class AuditScan:
    scanned_files: tuple[str, ...]
    excluded_files: tuple[str, ...]
    parse_failures: tuple[ParseFailure, ...]
    sites: tuple[WriteSite, ...]


@dataclass(frozen=True, order=True)
class AuditMapping:
    file: str
    symbol: str
    operation: str
    expected_count: int
    flow_id: str

    @property
    def operation_key(self) -> tuple[str, str, str]:
        return self.file, self.symbol, self.operation


@dataclass(frozen=True, order=True)
class FlowAnchor:
    flow_id: str
    file: str
    symbol: str | None = None


@dataclass(frozen=True)
class AuditResult:
    scan: AuditScan
    mapped_sites: int
    site_manifest_digest: str
    uncovered_sites: tuple[WriteSite, ...]
    stale_mappings: tuple[str, ...]
    missing_flow_anchors: tuple[str, ...]
    invalid_flow_ids: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not (
            self.scan.parse_failures
            or self.uncovered_sites
            or self.stale_mappings
            or self.missing_flow_anchors
            or self.invalid_flow_ids
        )

    @property
    def statistics(self) -> dict[str, int]:
        return {
            "scanned_files": len(self.scan.scanned_files),
            "excluded_files": len(self.scan.excluded_files),
            "parse_failures": len(self.scan.parse_failures),
            "detected_sites": len(self.scan.sites),
            "mapped_sites": self.mapped_sites,
            "uncovered_sites": len(self.uncovered_sites),
            "stale_audit_mappings": len(self.stale_mappings),
        }


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


def _operation(call: ast.Call) -> str:
    full_name = _call_name(call.func)
    attribute = call.func.attr if isinstance(call.func, ast.Attribute) else full_name
    if _write_open(call, full_name):
        return "open-write"
    if attribute in _PATH_METHODS:
        if attribute != "replace":
            return attribute
        if full_name == "os.replace" or re.search(
            r"(?:path|source|destination|temporary)\.replace$", full_name
        ):
            return "replace"
    if full_name.startswith("os.") and attribute in _OS_WRITES:
        return full_name
    if full_name.startswith("shutil.") and attribute in _SHUTIL_WRITES:
        return full_name
    if full_name.startswith("tempfile.") and attribute in _TEMP_WRITES:
        return full_name
    if full_name in {
        "json.dump",
        "logging.FileHandler",
        "sqlite3.connect",
        "urllib.request.urlretrieve",
    }:
        return full_name
    if attribute in {"extract", "extractall"} and "zip" in full_name.lower():
        return "zip-extract"
    if attribute == "save":
        return "save"
    return ""


def _fingerprint(operation: str, normalized_call: str) -> str:
    material = f"{operation}\0{normalized_call}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


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
        operation = _operation(node)
        if operation:
            normalized_call = ast.dump(node, annotate_fields=True, include_attributes=False)
            self.sites.append(
                WriteSite(
                    file=self.relative_file,
                    symbol=".".join(self.stack) or "<module>",
                    operation=operation,
                    fingerprint=_fingerprint(operation, normalized_call),
                    line=node.lineno,
                )
            )
        self.generic_visit(node)


def git_tracked_files(repo_root: Path) -> tuple[str, ...]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("git-tracked-files-unavailable")
    try:
        decoded = completed.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("git-tracked-files-not-utf8") from exc
    return tuple(sorted(item for item in decoded.split("\0") if item))


def _normalize_tracked_file(relative_file: str) -> str:
    normalized = relative_file.replace("\\", "/")
    candidate = Path(normalized)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("tracked-file-outside-repository")
    return candidate.as_posix()


def scan_tracked_files(repo_root: Path, tracked_files: Iterable[str]) -> AuditScan:
    sites: list[WriteSite] = []
    scanned_files: list[str] = []
    excluded_files: list[str] = []
    failures: list[ParseFailure] = []

    for relative in sorted({_normalize_tracked_file(item) for item in tracked_files}):
        path = repo_root / Path(relative)
        if path.suffix.lower() not in _SCANNED_SUFFIXES or relative.startswith(_EXCLUDED_PREFIXES):
            excluded_files.append(relative)
            continue
        scanned_files.append(relative)
        if not path.is_file():
            failures.append(ParseFailure(relative, "tracked-file-missing"))
            continue
        if path.suffix.lower() == ".py":
            try:
                source = path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError:
                failures.append(ParseFailure(relative, "python-unicode-decode-error"))
                continue
            except OSError:
                failures.append(ParseFailure(relative, "python-read-error"))
                continue
            try:
                tree = ast.parse(source, filename=relative)
            except SyntaxError:
                failures.append(ParseFailure(relative, "python-syntax-error"))
                continue
            visitor = _WriteVisitor(relative)
            visitor.visit(tree)
            sites.extend(visitor.sites)
            continue

        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            failures.append(ParseFailure(relative, "script-unicode-decode-error"))
            continue
        except OSError:
            failures.append(ParseFailure(relative, "script-read-error"))
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            match = _SCRIPT_WRITE_PATTERN.search(line)
            if match is None:
                continue
            normalized = " ".join(line.strip().split())
            sites.append(
                WriteSite(
                    relative,
                    "<script>",
                    "script-write",
                    _fingerprint("script-write", normalized),
                    line_number,
                )
            )

    return AuditScan(
        scanned_files=tuple(scanned_files),
        excluded_files=tuple(excluded_files),
        parse_failures=tuple(sorted(failures)),
        sites=tuple(sorted(sites)),
    )


def _defined_symbols(path: Path, relative_file: str) -> tuple[set[str], str | None]:
    try:
        source = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return set(), "anchor-unicode-decode-error"
    except OSError:
        return set(), "anchor-read-error"
    try:
        tree = ast.parse(source, filename=relative_file)
    except SyntaxError:
        return set(), "anchor-syntax-error"
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
    return defined, None


def validate_flow_anchors(repo_root: Path, anchors: Sequence[FlowAnchor]) -> tuple[str, ...]:
    missing: list[str] = []
    symbol_cache: dict[str, tuple[set[str], str | None]] = {}
    for anchor in anchors:
        path = repo_root / Path(anchor.file)
        if not path.is_file():
            missing.append(f"{anchor.flow_id}:missing-file:{anchor.file}")
            continue
        if anchor.symbol is None:
            continue
        if path.suffix.lower() != ".py":
            missing.append(f"{anchor.flow_id}:symbol-on-non-python:{anchor.file}")
            continue
        if anchor.file not in symbol_cache:
            symbol_cache[anchor.file] = _defined_symbols(path, anchor.file)
        defined, failure = symbol_cache[anchor.file]
        if failure:
            missing.append(f"{anchor.flow_id}:{failure}:{anchor.file}")
        elif anchor.symbol not in defined:
            missing.append(f"{anchor.flow_id}:missing-symbol:{anchor.file}:{anchor.symbol}")
    return tuple(sorted(missing))


def evaluate_scan(
    scan: AuditScan,
    mappings: Sequence[AuditMapping],
    anchors: Sequence[FlowAnchor],
    *,
    required_flow_ids: frozenset[str] = _FLOW_IDS,
    missing_flow_anchors: Sequence[str] = (),
) -> AuditResult:
    expected: dict[tuple[str, str, str], AuditMapping] = {}
    invalid_flow_ids = sorted(
        {
            item.flow_id
            for item in (*mappings, *anchors)
            if item.flow_id not in required_flow_ids
        }
    )
    for mapping in mappings:
        if mapping.operation_key in expected:
            raise ValueError("duplicate-audit-mapping")
        if mapping.expected_count < 1:
            raise ValueError("invalid-audit-expected-count")
        expected[mapping.operation_key] = mapping

    actual = Counter(site.operation_key for site in scan.sites)
    uncovered: list[WriteSite] = []
    mapped_count = 0
    sites_by_key: dict[tuple[str, str, str], list[WriteSite]] = {}
    for site in scan.sites:
        sites_by_key.setdefault(site.operation_key, []).append(site)
    for key, sites in sites_by_key.items():
        mapping = expected.get(key)
        allowed = mapping.expected_count if mapping is not None else 0
        mapped_count += min(len(sites), allowed)
        uncovered.extend(sorted(sites)[allowed:])

    stale: list[str] = []
    for key, mapping in sorted(expected.items()):
        count = actual.get(key, 0)
        if count != mapping.expected_count:
            stale.append(
                f"{mapping.flow_id}:{mapping.file}:{mapping.symbol}:{mapping.operation}:"
                f"expected={mapping.expected_count}:actual={count}"
            )

    anchored_flows = {anchor.flow_id for anchor in anchors}
    for flow_id in sorted(required_flow_ids - anchored_flows):
        stale.append(f"{flow_id}:missing-flow-anchor-declaration")

    return AuditResult(
        scan=scan,
        mapped_sites=mapped_count,
        site_manifest_digest="",
        uncovered_sites=tuple(sorted(uncovered)),
        stale_mappings=tuple(stale),
        missing_flow_anchors=tuple(sorted(missing_flow_anchors)),
        invalid_flow_ids=tuple(invalid_flow_ids),
    )


_MAIN_SYMBOLS = frozenset(
    {
        "<module>", "_local_upload_item", "_write_local_upload_classification",
        "apimart_upload_file_payload", "apimart_upload_payload_from_bytes",
        "batch_crop_asset_library_items", "caption_local_assets", "cleanup_expired_canvas_trash",
        "codex_chat_text", "codex_postprocess_image_to_requested_size", "codex_prepare_local_media",
        "codex_reference_paths", "compress_data_url_image", "convert_output_to_jpg",
        "create_asset_library_category", "create_local_asset_folder", "delete_asset_library_category",
        "delete_conversation", "delete_history", "delete_local_assets", "delete_project",
        "delete_workflow", "download_comfy_output", "download_github_update_files", "download_image",
        "download_modelscope_update_files", "ensure_runtime_config_files", "export_smart_canvas_group",
        "gemini_cli_chat_text", "generate_angle_cloud", "generate_cloud", "generate_codex_provider_image",
        "generate_gemini_cli_provider_image", "generate_jimeng_provider_image", "generate_jimeng_video",
        "generate_video_preview_image", "image_jpeg._build", "image_output_meta",
        "image_path_to_data_url", "image_size_from_reference", "import_canvas_workflow",
        "import_local_assets_from_urls", "import_local_image_file", "jimeng_local_output_url",
        "jimeng_prepare_local_media", "make_asset_library_item", "make_workflow_library_item_from_bytes",
        "media_preview._build_preview", "migrate_asset_library_into_dirs",
        "migrate_double_extension_uploads", "migrate_mislabeled_image_extensions", "move_local_assets",
        "ms_generate", "poll_angle_cloud", "purge_canvas", "reference_to_data_url",
        "remove_asset_library_file", "rename_local_asset_folder", "rename_local_asset_item",
        "rollback_update", "run_codex_cli", "runninghub_store_remote_output", "save_ai_image_to_output",
        "save_api_providers", "save_asset_library", "save_canvas", "save_comfy_text_output",
        "save_conversation", "save_local_asset_caption", "save_projects", "save_prompt_libraries",
        "save_remote_video_to_output", "save_runninghub_workflow_store", "save_to_history",
        "save_workflow_config", "schedule_self_restart", "shared_folders_save",
        "smart_group_export_folder", "update_canvas_meta", "update_env_values", "update_from_github",
        "upload_ai_base64", "upload_ai_reference", "upload_local_assets", "upload_workflow", "user_dir",
        "video_reference_to_frame_data_urls", "xlsx_embedded_image_data_urls",
    }
)

_MAIN_FLOW_BY_SYMBOL = {symbol: "W17" for symbol in _MAIN_SYMBOLS}
_MAIN_FLOW_BY_SYMBOL.update(
    {
        "<module>": "W02",
        "ensure_runtime_config_files": "W05",
        "update_env_values": "W06",
        "save_to_history": "W07", "delete_history": "W07",
        "save_conversation": "W08", "delete_conversation": "W08",
        "save_canvas": "W09", "save_projects": "W09", "update_canvas_meta": "W09",
        "delete_project": "W09", "purge_canvas": "W09",
        "save_asset_library": "W10", "save_prompt_libraries": "W10",
        "shared_folders_save": "W10", "save_runninghub_workflow_store": "W10",
        "save_api_providers": "W11",
        "upload_workflow": "W12", "save_workflow_config": "W12", "delete_workflow": "W12",
        "_copy_shipped_workflow_to_user": "W12",
        "make_workflow_library_item_from_bytes": "W12", "import_canvas_workflow": "W12",
        "_local_upload_item": "W13", "_write_local_upload_classification": "W13",
        "apimart_upload_file_payload": "W13", "apimart_upload_payload_from_bytes": "W13",
        "import_local_assets_from_urls": "W13", "import_local_image_file": "W13",
        "upload_ai_base64": "W13", "upload_ai_reference": "W13", "upload_local_assets": "W13",
        "batch_crop_asset_library_items": "W14", "caption_local_assets": "W14",
        "create_asset_library_category": "W14", "create_local_asset_folder": "W14",
        "delete_asset_library_category": "W14", "delete_local_assets": "W14",
        "make_asset_library_item": "W14", "move_local_assets": "W14",
        "remove_asset_library_file": "W14", "rename_local_asset_folder": "W14",
        "rename_local_asset_item": "W14", "save_local_asset_caption": "W14",
        "download_comfy_output": "W15", "download_image": "W15", "generate_angle_cloud": "W15",
        "generate_cloud": "W15", "generate_codex_provider_image": "W15",
        "generate_gemini_cli_provider_image": "W15", "generate_jimeng_provider_image": "W15",
        "generate_jimeng_video": "W15", "generate_video_preview_image": "W15",
        "poll_angle_cloud": "W15", "runninghub_store_remote_output": "W15",
        "save_ai_image_to_output": "W15", "save_comfy_text_output": "W15",
        "save_remote_video_to_output": "W15",
        "image_jpeg._build": "W16", "media_preview._build_preview": "W16",
        "migrate_asset_library_into_dirs": "W20", "migrate_double_extension_uploads": "W21",
        "migrate_mislabeled_image_extensions": "W21",
        "download_github_update_files": "W22", "download_modelscope_update_files": "W22",
        "update_from_github": "W23", "rollback_update": "W23",
        "schedule_self_restart": "W24",
    }
)

_OTHER_FLOW_BY_SYMBOL: dict[tuple[str, str], str] = {
    ("enterprise/db.py", "get_db"): "W18",
    ("enterprise/db.py", "set_canvas_project"): "W09",
    ("enterprise/interceptors.py", "_write_history_records"): "W07",
    ("enterprise/interceptors.py", "normalize_resource_url"): "W13",
    # Capability-scoped root preparation replaces import-time APP_ROOT mkdirs;
    # it is audited as W02 until the per-flow runtime split is expanded.
    ("enterprise/paths.py", "_create_and_check"): "W02",
    # current-release is a STATE_ROOT primitive only (test/validation call
    # sites in ENV-1B1B), classified with the existing state-control flow.
    ("enterprise/release/current_release.py", "atomic_write_current_release"): "W24",
    ("enterprise/migrations/sec_1b1_role_auth.py", "_open_connection"): "W19",
    ("enterprise/migrations/sqlite_existing.py", "open_existing_sqlite"): "W19",
    ("enterprise/ops/runner.py", "append_jsonl"): "W30",
    ("enterprise/ops/runner.py", "backup_sqlite_database"): "W31",
    ("enterprise/ops/runner.py", "copy_backup_items"): "W31",
    ("enterprise/ops/runner.py", "sqlite_connect_readonly"): "W31",
    ("enterprise/ops/runner.py", "write_json"): "W29",
    ("enterprise/ops/update/download.py", "atomic_download"): "W32",
    ("enterprise/ops/update/http_client.py", "SafeHttpClient.stream"): "W32",
    ("enterprise/ops/update/jobs.py", "UpdateJob.append_log"): "W30",
    ("enterprise/ops/update/jobs.py", "_atomic_json_create"): "W32",
    ("enterprise/ops/update/staging.py", "stage_release_archive"): "W33",
    ("enterprise/release/runtime_provenance.py", "_atomic_write_report"): "W40",
    ("enterprise/release/static_build.py", "_atomic_write_report"): "W40",
    ("enterprise/release/static_build.py", "_copy_tree"): "W40",
    ("enterprise/release/static_build.py", "build_static_tree"): "W40",
    ("enterprise/runtime/child.py", "_serve"): "W28",
    ("enterprise/runtime/control.py", "_discard_bootstrap_failure"): "W28",
    ("enterprise/runtime/control.py", "_prepare_bootstrap_failure_path"): "W28",
    ("enterprise/runtime/host.py", "_write_bootstrap_failure"): "W28",
    ("enterprise/runtime/logging.py", "RotatingTextLog.__init__"): "W27",
    ("enterprise/runtime/logging.py", "RotatingTextLog._rotate_locked"): "W27",
    ("enterprise/runtime/logging.py", "RotatingTextLog.write"): "W27",
    ("enterprise/runtime/logging.py", "RuntimeLogs.__init__"): "W27",
    ("enterprise/runtime/process.py", "graceful_stop"): "W28",
    ("enterprise/runtime/process.py", "start_process"): "W26",
    ("enterprise/runtime/state.py", "RuntimeStateStore.acquire_foreground_lock"): "W26",
    ("enterprise/runtime/state.py", "RuntimeStateStore.clear_stale_lock"): "W26",
    ("enterprise/runtime/state.py", "RuntimeStateStore.consume_commands"): "W26",
    ("enterprise/runtime/state.py", "RuntimeStateStore.initialize"): "W26",
    ("enterprise/runtime/state.py", "RuntimeStateStore.purge_control"): "W26",
    ("enterprise/runtime/state.py", "RuntimeStateStore.release_lock"): "W26",
    ("enterprise/runtime/state.py", "RuntimeStateStore.remove_ack"): "W26",
    ("enterprise/runtime/state.py", "RuntimeStateStore.reserve_lock"): "W26",
    ("enterprise/runtime/state.py", "_atomic_json_replace"): "W26",
    ("get-pip.py", "main"): "W35",
    ("get-pip.py", "monkeypatch_for_cert"): "W35",
    ("tools/sec_1b2_local_runner.py", "_write_final_json"): "W19",
    ("tools/sec_1b2_local_runner.py", "_write_new_json"): "W19",
}

_SCRIPT_FLOW_BY_FILE = {
    "_self_restart.bat": "W25",
    "tools/chrome-local-asset-importer/popup.js": "W38",
    "tools/jimeng_cli_install.ps1": "W36",
    "tools/jimeng_cli_login.ps1": "W36",
    "tools/ops/windows/run-ops2a-backup-execute.ps1": "W37",
    "tools/ops/windows/run-ops2a-prod-dryrun.ps1": "W37",
    "tools/photoshop-asset-connector/js/agent.js": "W38",
    "tools/photoshop-asset-connector/js/app.js": "W38",
    "tools/photoshop-asset-connector/js/net.js": "W38",
    "安装依赖.bat": "W35",
}


def _flow_for_operation(file: str, symbol: str) -> str:
    if file == "main.py":
        return _MAIN_FLOW_BY_SYMBOL[symbol]
    if symbol == "<script>":
        return _SCRIPT_FLOW_BY_FILE[file]
    return _OTHER_FLOW_BY_SYMBOL[(file, symbol)]


# Frozen after reviewing the Git-tracked production scan. The manifest hashes
# every mapped site as (file, symbol, operation, normalized-call fingerprint,
# Wxx flow). Line numbers are deliberately excluded, while duplicate identical
# calls remain duplicate records. Any added/removed/changed call drifts it.
EXPECTED_SITE_MANIFEST_DIGEST = "406aa718d7c8fd2cf49a846f563b92bd9b33ab34f609d9d721c0c5de528e2acb"

FLOW_ANCHORS: tuple[FlowAnchor, ...] = (
    FlowAnchor("W01", "main.py", "startup_event"),
    FlowAnchor("W02", "main.py", "<module>"),
    FlowAnchor("W03", "main.py", "<module>"),
    FlowAnchor("W04", "main.py", "<module>"),
    FlowAnchor("W05", "main.py", "ensure_runtime_config_files"),
    FlowAnchor("W06", "main.py", "update_env_values"),
    FlowAnchor("W07", "main.py", "save_to_history"),
    FlowAnchor("W08", "main.py", "save_conversation"),
    FlowAnchor("W09", "main.py", "save_canvas"),
    FlowAnchor("W10", "main.py", "save_asset_library"),
    FlowAnchor("W11", "main.py", "save_api_providers"),
    FlowAnchor("W12", "main.py", "upload_workflow"),
    FlowAnchor("W13", "main.py", "upload_local_assets"),
    FlowAnchor("W14", "main.py", "move_local_assets"),
    FlowAnchor("W15", "main.py", "save_ai_image_to_output"),
    FlowAnchor("W16", "main.py", "media_preview._build_preview"),
    FlowAnchor("W17", "main.py", "codex_prepare_local_media"),
    FlowAnchor("W18", "enterprise/db.py", "get_db"),
    FlowAnchor("W19", "enterprise/migrations/sqlite_existing.py", "open_existing_sqlite"),
    FlowAnchor("W20", "main.py", "migrate_asset_library_into_dirs"),
    FlowAnchor("W21", "main.py", "migrate_double_extension_uploads"),
    FlowAnchor("W22", "main.py", "download_github_update_files"),
    FlowAnchor("W23", "main.py", "update_from_github"),
    FlowAnchor("W24", "main.py", "schedule_self_restart"),
    FlowAnchor("W25", "_self_restart.bat"),
    FlowAnchor("W26", "enterprise/runtime/state.py", "RuntimeStateStore.initialize"),
    FlowAnchor("W27", "enterprise/runtime/logging.py", "RuntimeLogs.__init__"),
    FlowAnchor("W28", "enterprise/runtime/host.py", "_write_bootstrap_failure"),
    FlowAnchor("W29", "enterprise/ops/runner.py", "write_json"),
    FlowAnchor("W30", "enterprise/ops/runner.py", "append_jsonl"),
    FlowAnchor("W31", "enterprise/ops/runner.py", "backup_sqlite_database"),
    FlowAnchor("W32", "enterprise/ops/update/download.py", "atomic_download"),
    FlowAnchor("W33", "enterprise/ops/update/staging.py", "stage_release_archive"),
    FlowAnchor("W34", "enterprise/tests/test_env_1b1a_static_build.py"),
    FlowAnchor("W35", "get-pip.py", "main"),
    FlowAnchor("W36", "tools/jimeng_cli_install.ps1"),
    FlowAnchor("W37", "tools/ops/windows/run-ops2a-backup-execute.ps1"),
    FlowAnchor("W38", "tools/chrome-local-asset-importer/popup.js"),
    FlowAnchor("W39", "enterprise/runtime/child.py", "_serve"),
    FlowAnchor("W40", "enterprise/release/static_build.py", "build_static_tree"),
)


def audit_repository(
    repo_root: Path, tracked_files: Iterable[str] | None = None
) -> AuditResult:
    tracked = git_tracked_files(repo_root) if tracked_files is None else tuple(tracked_files)
    scan = scan_tracked_files(repo_root, tracked)
    missing = validate_flow_anchors(repo_root, FLOW_ANCHORS)
    mapped_records: list[str] = []
    uncovered: list[WriteSite] = []
    invalid_flow_ids: set[str] = set()
    for site in scan.sites:
        try:
            flow_id = _flow_for_operation(site.file, site.symbol)
        except KeyError:
            uncovered.append(site)
            continue
        if flow_id not in _FLOW_IDS:
            invalid_flow_ids.add(flow_id)
            continue
        mapped_records.append(
            "\0".join(
                (site.file, site.symbol, site.operation, site.fingerprint, flow_id)
            )
        )
    encoded_manifest = "\n".join(sorted(mapped_records)).encode("utf-8")
    manifest_digest = hashlib.sha256(encoded_manifest).hexdigest()
    stale: list[str] = []
    if manifest_digest != EXPECTED_SITE_MANIFEST_DIGEST:
        stale.append(
            "site-manifest-digest-mismatch:"
            f"expected={EXPECTED_SITE_MANIFEST_DIGEST}:actual={manifest_digest}"
        )
    anchored_flows = {anchor.flow_id for anchor in FLOW_ANCHORS}
    for flow_id in sorted(_FLOW_IDS - anchored_flows):
        stale.append(f"{flow_id}:missing-flow-anchor-declaration")
    return AuditResult(
        scan=scan,
        mapped_sites=len(mapped_records),
        site_manifest_digest=manifest_digest,
        uncovered_sites=tuple(sorted(uncovered)),
        stale_mappings=tuple(stale),
        missing_flow_anchors=missing,
        invalid_flow_ids=tuple(sorted(invalid_flow_ids)),
    )


def uncovered_write_sites(repo_root: Path) -> list[WriteSite]:
    """Compatibility wrapper returning uncovered sites from the strict gate."""

    return list(audit_repository(repo_root).uncovered_sites)


def missing_audit_anchors(repo_root: Path) -> list[str]:
    """Compatibility wrapper returning all non-site gate failures."""

    result = audit_repository(repo_root)
    return sorted(
        [f"parse-failure:{item.file}:{item.code}" for item in result.scan.parse_failures]
        + list(result.stale_mappings)
        + list(result.missing_flow_anchors)
        + list(result.invalid_flow_ids)
    )
