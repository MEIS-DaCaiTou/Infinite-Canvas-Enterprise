"""Compatibility layout which keeps main.py's public string constants stable."""
from __future__ import annotations

from dataclasses import dataclass

from enterprise.paths import PathRoots


@dataclass(frozen=True)
class AppPathLayout:
    roots: PathRoots

    @property
    def BASE_DIR(self) -> str: return str(self.roots.APP_ROOT)
    @property
    def WORKFLOW_DIR(self) -> str: return str(self.roots.DATA_ROOT / "workflows")
    @property
    def SHIPPED_WORKFLOW_DIR(self) -> str: return str(self.roots.APP_ROOT / "workflows")
    @property
    def STATIC_DIR(self) -> str: return str(self.roots.APP_ROOT / "static")
    @property
    def OUTPUT_DIR(self) -> str: return str(self.roots.UPLOAD_ROOT / "output")
    @property
    def ASSETS_DIR(self) -> str: return str(self.roots.UPLOAD_ROOT / "assets")
    @property
    def OUTPUT_INPUT_DIR(self) -> str: return str(self.roots.UPLOAD_ROOT / "assets" / "input")
    @property
    def OUTPUT_OUTPUT_DIR(self) -> str: return str(self.roots.UPLOAD_ROOT / "assets" / "output")
    @property
    def ASSET_LIBRARY_DIR(self) -> str: return str(self.roots.UPLOAD_ROOT / "assets" / "library")
    @property
    def LOCAL_UPLOAD_DIR(self) -> str: return str(self.roots.UPLOAD_ROOT / "assets" / "uploads")
    @property
    def HISTORY_FILE(self) -> str: return str(self.roots.DATA_ROOT / "history.json")
    @property
    def API_ENV_FILE(self) -> str: return str(self.roots.CONFIG_ROOT / "API" / ".env")
    @property
    def DATA_DIR(self) -> str: return str(self.roots.DATA_ROOT)
    @property
    def CONVERSATION_DIR(self) -> str: return str(self.roots.DATA_ROOT / "conversations")
    @property
    def CANVAS_DIR(self) -> str: return str(self.roots.DATA_ROOT / "canvases")
    @property
    def MEDIA_PREVIEW_DIR(self) -> str: return str(self.roots.CACHE_ROOT / "media_previews")
    @property
    def ASSET_LIBRARY_PATH(self) -> str: return str(self.roots.DATA_ROOT / "asset_library.json")
    @property
    def PROMPT_LIBRARY_PATH(self) -> str: return str(self.roots.DATA_ROOT / "prompt_libraries.json")
    @property
    def API_PROVIDERS_FILE(self) -> str: return str(self.roots.CONFIG_ROOT / "api_providers.json")
    @property
    def RUNNINGHUB_WORKFLOW_STORE_FILE(self) -> str: return str(self.roots.DATA_ROOT / "runninghub_workflows.json")
    @property
    def SHARED_FOLDERS_FILE(self) -> str: return str(self.roots.DATA_ROOT / "shared_folders.json")
    @property
    def GLOBAL_CONFIG_FILE(self) -> str: return str(self.roots.CONFIG_ROOT / "global_config.json")
