"""Pure, fail-closed path-root contracts for ENV-1B1B.

This module deliberately has no dependency on application configuration,
database, gateway, or runtime code.  It defines paths only; entrypoint and
interpreter binding remain an ENV-1B1C responsibility.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal


PATH_ROOTS_SCHEMA = "env-1b1b-path-roots-v1"
DEVELOPMENT_PROFILE = "development"
PORTABLE_RELEASE_PROFILE = "portable-release"
_ROOT_FIELDS = (
    "INSTALL_ROOT", "RELEASE_ROOT", "APP_ROOT", "CONFIG_ROOT", "DATA_ROOT",
    "UPLOAD_ROOT", "LOG_ROOT", "BACKUP_ROOT", "STATE_ROOT", "STAGING_ROOT",
    "RUNTIME_ROOT", "CACHE_ROOT", "TEMP_ROOT", "PYTHON_RUNTIME",
)
_DERIVATION_TOKEN = object()
_RELEASE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_WINDOWS_DEVICE_RE = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.I)
OperationTargetKind = Literal["output", "log", "backup", "workspace"]


class PathRootsError(RuntimeError):
    """Stable, redacted failure for the path-root contract."""

    def __init__(self, code: str, root_label: str = "") -> None:
        self.code = code
        self.root_label = root_label
        super().__init__(f"{code}:{root_label}" if root_label else code)


def _reject_windows_special(value: str, label: str) -> None:
    text = value.strip()
    lowered = text.lower()
    if lowered.startswith("\\\\?\\") or lowered.startswith("\\\\.\\"):
        raise PathRootsError("PATH_DEVICE_NAMESPACE", label)
    if text.startswith("\\\\") or text.startswith("//"):
        raise PathRootsError("PATH_UNC_FORBIDDEN", label)
    # Windows accepts C:relative paths; they must never identify a root.
    if len(text) >= 2 and text[1] == ":" and (len(text) == 2 or text[2:3] not in {"\\", "/"}):
        raise PathRootsError("PATH_DRIVE_RELATIVE", label)


def _normalise(path: Path | str, label: str) -> Path:
    raw = os.fspath(path)
    if not raw:
        raise PathRootsError("PATH_EMPTY", label)
    _reject_windows_special(raw, label)
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise PathRootsError("PATH_NOT_ABSOLUTE", label)
    return Path(os.path.abspath(os.path.normpath(str(candidate))))


def _key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path))).replace("/", "\\")


def _inside(child: Path, parent: Path, *, allow_equal: bool = False) -> bool:
    """Containment using normalized path components, never string prefixes."""
    child_key, parent_key = _key(child), _key(parent)
    try:
        common = _key(Path(os.path.commonpath((str(child), str(parent)))))
    except ValueError:
        return False
    return common == parent_key and (allow_equal or child_key != parent_key)


def validate_release_component(value: object) -> str:
    """Validate a release directory component without importing state parsing."""
    if not isinstance(value, str) or not value.isascii() or not _RELEASE_COMPONENT_RE.fullmatch(value):
        raise PathRootsError("RELEASE_COMPONENT_INVALID", "APP_ROOT")
    if value.endswith((".", " ")) or ".." in value:
        raise PathRootsError("RELEASE_COMPONENT_INVALID", "APP_ROOT")
    # The first basename component determines Windows device-name semantics.
    if _WINDOWS_DEVICE_RE.fullmatch(value.split(".", 1)[0]):
        raise PathRootsError("RELEASE_COMPONENT_DEVICE", "APP_ROOT")
    return value


def _assert_no_reparse(path: Path, label: str) -> None:
    """Check every existing component without following an untrusted link.

    This is pre-use/post-create validation, not a Windows handle based
    race-free protocol; callers must not claim it eliminates TOCTOU races.
    """
    anchor = Path(path.anchor)
    current = anchor
    for component in path.parts[1:]:
        current = current / component
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            break
        except OSError as exc:
            raise PathRootsError("PATH_LSTAT_FAILED", label) from exc
        attrs = getattr(info, "st_file_attributes", 0)
        if stat.S_ISLNK(info.st_mode) or attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise PathRootsError("PATH_REPARSE_FORBIDDEN", label)


def _same_volume(left: Path, right: Path) -> bool:
    return os.path.splitdrive(str(left))[0].casefold() == os.path.splitdrive(str(right))[0].casefold()


@dataclass(frozen=True)
class PortableRootInputs:
    install_root: Path
    local_app_data_base: Path
    expected_manifest_sha256: str | None = None


@dataclass(frozen=True)
class PortableRootLayout:
    """Portable roots that are knowable before resolving APP_ROOT.

    The current-release pointer is intentionally not read here.  An
    entrypoint first derives this layout, reads and validates the pointer from
    ``STATE_ROOT``, and only then derives a complete :class:`PathRoots`.
    """

    INSTALL_ROOT: Path
    RELEASE_ROOT: Path
    CONFIG_ROOT: Path
    DATA_ROOT: Path
    UPLOAD_ROOT: Path
    LOG_ROOT: Path
    BACKUP_ROOT: Path
    STATE_ROOT: Path
    STAGING_ROOT: Path
    RUNTIME_ROOT: Path
    CACHE_ROOT: Path
    TEMP_ROOT: Path
    expected_manifest_sha256: str | None = None


@dataclass(frozen=True)
class PathRoots:
    INSTALL_ROOT: Path
    RELEASE_ROOT: Path
    APP_ROOT: Path
    CONFIG_ROOT: Path
    DATA_ROOT: Path
    UPLOAD_ROOT: Path
    LOG_ROOT: Path
    BACKUP_ROOT: Path
    STATE_ROOT: Path
    STAGING_ROOT: Path
    RUNTIME_ROOT: Path
    CACHE_ROOT: Path
    TEMP_ROOT: Path
    PYTHON_RUNTIME: Path
    profile: str
    schema_version: str = PATH_ROOTS_SCHEMA
    legacy_app_relative_layout: bool = False
    release_validation_eligible: bool = False
    production_approval_eligible: bool = False
    # ``init=False`` prevents callers (and ``dataclasses.replace``) from
    # copying or supplying this private capability.  Only trusted derivation
    # helpers can mark a fully derived value for use.
    _derivation_token: object | None = field(default=None, init=False, repr=False, compare=False)

    @property
    def root_identity(self) -> str:
        raw = "\0".join([self.schema_version, self.profile, *(_key(getattr(self, field)) for field in _ROOT_FIELDS)])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def inspect(self) -> dict[str, object]:
        # Deliberately exposes only labels/identity, never host paths.
        return {
            "schema_version": self.schema_version,
            "profile": self.profile,
            "root_identity": self.root_identity,
            "root_labels": list(_ROOT_FIELDS),
            "legacy_app_relative_layout": self.legacy_app_relative_layout,
            "release_validation_eligible": self.release_validation_eligible,
            "production_approval_eligible": self.production_approval_eligible,
        }


def _mark_trusted(roots: PathRoots) -> PathRoots:
    object.__setattr__(roots, "_derivation_token", _DERIVATION_TOKEN)
    return roots


def derive_development_path_roots(code_root: Path | str | None = None) -> PathRoots:
    """Derive legacy-compatible development roots anchored at code, never cwd."""
    app_root = _normalise(code_root or Path(__file__).resolve().parents[1], "APP_ROOT")
    install = app_root.parent
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return _mark_trusted(PathRoots(
        INSTALL_ROOT=install, RELEASE_ROOT=install / "releases", APP_ROOT=app_root,
        CONFIG_ROOT=app_root, DATA_ROOT=app_root / "data", UPLOAD_ROOT=app_root,
        LOG_ROOT=app_root / "logs", BACKUP_ROOT=app_root / "ops_backups",
        STATE_ROOT=app_root / "state", STAGING_ROOT=app_root / "ops_artifacts",
        RUNTIME_ROOT=local / "InfiniteCanvasEnterprise" / "runtime",
        CACHE_ROOT=app_root / "data", TEMP_ROOT=Path(tempfile_root()),
        PYTHON_RUNTIME=app_root / "python", profile=DEVELOPMENT_PROFILE,
        legacy_app_relative_layout=True,
    ))


def tempfile_root() -> str:
    # Kept isolated to avoid importing tempfile in code paths that use the model.
    return os.environ.get("TMP") or os.environ.get("TEMP") or str(Path.home() / "AppData" / "Local" / "Temp")


def derive_portable_path_roots(inputs: PortableRootInputs, release_id: str) -> PathRoots:
    """Pure v1 portable layout derivation.  It performs no I/O."""
    layout = derive_portable_root_layout(inputs)
    release_id = validate_release_component(release_id)
    app = layout.RELEASE_ROOT / release_id
    return _mark_trusted(PathRoots(
        INSTALL_ROOT=layout.INSTALL_ROOT, RELEASE_ROOT=layout.RELEASE_ROOT, APP_ROOT=app,
        CONFIG_ROOT=layout.CONFIG_ROOT, DATA_ROOT=layout.DATA_ROOT, UPLOAD_ROOT=layout.UPLOAD_ROOT,
        LOG_ROOT=layout.LOG_ROOT, BACKUP_ROOT=layout.BACKUP_ROOT, STATE_ROOT=layout.STATE_ROOT,
        STAGING_ROOT=layout.STAGING_ROOT, RUNTIME_ROOT=layout.RUNTIME_ROOT,
        CACHE_ROOT=layout.CACHE_ROOT, TEMP_ROOT=layout.TEMP_ROOT, PYTHON_RUNTIME=app / "python",
        profile=PORTABLE_RELEASE_PROFILE,
    ))


def derive_portable_root_layout(inputs: PortableRootInputs) -> PortableRootLayout:
    """Stage one of portable startup: derive only non-release-owned roots."""
    install = _normalise(inputs.install_root, "INSTALL_ROOT")
    local = _normalise(inputs.local_app_data_base, "LOCALAPPDATA")
    return PortableRootLayout(
        INSTALL_ROOT=install,
        RELEASE_ROOT=install / "releases",
        CONFIG_ROOT=install / "config",
        DATA_ROOT=install / "data",
        UPLOAD_ROOT=install / "data" / "uploads",
        LOG_ROOT=install / "logs",
        BACKUP_ROOT=install / "backups",
        STATE_ROOT=install / "state",
        STAGING_ROOT=install / "staging",
        RUNTIME_ROOT=local / "InfiniteCanvasEnterprise" / "runtime",
        CACHE_ROOT=local / "Infinite-Canvas-Enterprise" / "cache",
        TEMP_ROOT=local / "Infinite-Canvas-Enterprise" / "temp",
        expected_manifest_sha256=inputs.expected_manifest_sha256,
    )


def validate_common_path_roots(roots: PathRoots) -> None:
    if roots.schema_version != PATH_ROOTS_SCHEMA or roots.profile not in {DEVELOPMENT_PROFILE, PORTABLE_RELEASE_PROFILE}:
        raise PathRootsError("PATH_ROOTS_SCHEMA_INVALID")
    values = {name: _normalise(getattr(roots, name), name) for name in _ROOT_FIELDS}
    for name, value in values.items():
        _assert_no_reparse(value, name)
    allowed = {
        ("INSTALL_ROOT", "RELEASE_ROOT"), ("INSTALL_ROOT", "CONFIG_ROOT"), ("INSTALL_ROOT", "DATA_ROOT"),
        ("INSTALL_ROOT", "LOG_ROOT"), ("INSTALL_ROOT", "BACKUP_ROOT"), ("INSTALL_ROOT", "STATE_ROOT"),
        ("INSTALL_ROOT", "STAGING_ROOT"), ("RELEASE_ROOT", "APP_ROOT"), ("DATA_ROOT", "UPLOAD_ROOT"),
        ("APP_ROOT", "PYTHON_RUNTIME"),
    }
    # Development retains a code-root compatibility layout.  Its APP_ROOT is
    # intentionally not a release child and is validated by the dedicated
    # development validator; portable-release must satisfy the full graph.
    required_relations = allowed if roots.profile == PORTABLE_RELEASE_PROFILE else set()
    for parent_name, child_name in required_relations:
        if not _inside(values[child_name], values[parent_name]):
            raise PathRootsError("PATH_CONTAINMENT_INVALID", child_name)
    if roots.profile == PORTABLE_RELEASE_PROFILE:
        names = list(values)
        for i, left_name in enumerate(names):
            for right_name in names[i + 1:]:
                left, right = values[left_name], values[right_name]
                if _key(left) == _key(right):
                    raise PathRootsError("PATH_ROOTS_EQUAL", left_name)
                # Permit the transitive edges implied by the only allowed
                # containment graph (INSTALL→RELEASE→APP→PYTHON and
                # INSTALL→DATA→UPLOAD), but no sibling/root overlap.
                relation_allowed = (left_name, right_name) in allowed or (right_name, left_name) in allowed
                relation_allowed = relation_allowed or {left_name, right_name} in (
                    {"INSTALL_ROOT", "APP_ROOT"}, {"INSTALL_ROOT", "PYTHON_RUNTIME"},
                    {"RELEASE_ROOT", "PYTHON_RUNTIME"}, {"INSTALL_ROOT", "UPLOAD_ROOT"},
                )
                if not relation_allowed and (_inside(left, right) or _inside(right, left)):
                    raise PathRootsError("PATH_ROOTS_UNEXPECTED_CONTAINMENT", left_name)
    if not _same_volume(values["RELEASE_ROOT"], values["STAGING_ROOT"]):
        raise PathRootsError("PATH_RELEASE_STAGING_VOLUME_MISMATCH", "STAGING_ROOT")


def validate_development_path_roots(roots: PathRoots) -> None:
    if roots.profile != DEVELOPMENT_PROFILE or not roots.legacy_app_relative_layout:
        raise PathRootsError("PATH_DEVELOPMENT_PROFILE_INVALID")
    if roots.release_validation_eligible or roots.production_approval_eligible:
        raise PathRootsError("PATH_DEVELOPMENT_ELIGIBILITY_INVALID")
    validate_common_path_roots(roots)


def validate_portable_release_layout(roots: PathRoots) -> None:
    if roots.profile != PORTABLE_RELEASE_PROFILE:
        raise PathRootsError("PATH_PORTABLE_PROFILE_INVALID")
    validate_portable_path_roots(roots)
    if not roots.APP_ROOT.is_dir() or not (roots.APP_ROOT / "main.py").is_file() or not (roots.APP_ROOT / "static").is_dir():
        raise PathRootsError("PATH_PORTABLE_APP_LAYOUT_INVALID", "APP_ROOT")


def validate_portable_path_roots(roots: PathRoots) -> None:
    """Validate portable root relationships without requiring shipped payload files.

    Directory preparation is intentionally allowed before an APP_ROOT payload is
    populated, while runtime resolution still calls ``validate_portable_release_layout``.
    Both paths require a trusted, factory-derived ``PathRoots`` capability.
    """
    if roots.profile != PORTABLE_RELEASE_PROFILE:
        raise PathRootsError("PATH_PORTABLE_PROFILE_INVALID")
    validate_common_path_roots(roots)


def validate_path_roots_for_use(roots: PathRoots) -> None:
    """Gate process installation and every mutable-directory capability."""
    if roots._derivation_token is not _DERIVATION_TOKEN:
        raise PathRootsError("PATH_ROOTS_UNTRUSTED")
    if roots.profile == DEVELOPMENT_PROFILE:
        validate_development_path_roots(roots)
    elif roots.profile == PORTABLE_RELEASE_PROFILE:
        validate_portable_path_roots(roots)
    else:
        raise PathRootsError("PATH_ROOTS_SCHEMA_INVALID")


def resolve_database_path(roots: PathRoots, configured: str | Path | None) -> Path:
    """Resolve DB_PATH without allowing portable roots to escape DATA_ROOT."""
    validate_path_roots_for_use(roots)
    if configured is None:
        return roots.DATA_ROOT / "enterprise.db"
    raw = os.fspath(configured)
    if not raw:
        raise PathRootsError("DB_PATH_EMPTY", "DATA_ROOT")
    _reject_windows_special(raw, "DATA_ROOT")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = roots.DATA_ROOT / candidate
    candidate = _normalise(candidate, "DATA_ROOT")
    if _key(candidate) == _key(roots.DATA_ROOT) or candidate.name in {"", "."}:
        raise PathRootsError("DB_PATH_DIRECTORY_INVALID", "DATA_ROOT")
    if roots.profile == PORTABLE_RELEASE_PROFILE and not _inside(candidate, roots.DATA_ROOT):
        raise PathRootsError("DB_PATH_OUTSIDE_DATA_ROOT", "DATA_ROOT")
    _assert_no_reparse(roots.DATA_ROOT, "DATA_ROOT")
    _assert_no_reparse(candidate.parent, "DATA_ROOT")
    _assert_no_reparse(candidate, "DATA_ROOT")
    return candidate


def _operation_relative_base(roots: PathRoots, kind: OperationTargetKind) -> Path:
    if kind == "output":
        return roots.STAGING_ROOT / "reports"
    if kind == "log":
        return roots.LOG_ROOT / "ops"
    if kind == "backup":
        return roots.BACKUP_ROOT
    if kind == "workspace":
        return roots.STAGING_ROOT / "workspace"
    raise PathRootsError("OPS_TARGET_KIND_INVALID")


def _assert_portable_operation_target_allowed(
    roots: PathRoots,
    candidate: Path,
    *,
    app_root: Path,
    label: str,
) -> None:
    app_root = _normalise(app_root, "APP_ROOT")
    _assert_no_reparse(candidate, label)
    if (
        _key(candidate) == _key(app_root)
        or _inside(candidate, app_root)
        or _inside(app_root, candidate)
    ):
        raise PathRootsError("OPS_TARGET_APP_ROOT_OVERLAP", label)
    if _key(candidate) == _key(roots.RELEASE_ROOT) or _inside(candidate, roots.RELEASE_ROOT):
        raise PathRootsError("OPS_TARGET_RELEASE_ROOT_FORBIDDEN", label)


def resolve_operation_target(
    roots: PathRoots,
    value: str | Path,
    kind: OperationTargetKind,
    *,
    app_root: Path | str | None = None,
    target_type: Literal["directory", "file"] = "directory",
    must_exist: bool = False,
    must_be_new: bool = False,
) -> Path:
    """Resolve an OPS operation target without mutating ``PathRoots``.

    Development keeps legacy command-line compatibility: relative operation
    paths remain application-root relative. Portable-release commands anchor
    relative targets to the corresponding external root and reject APP_ROOT,
    RELEASE_ROOT, special Windows path forms, reparse escapes, and source/target
    overlap. This is a pre-use check, not a Windows handle no-follow protocol.
    """
    validate_path_roots_for_use(roots)
    raw = os.fspath(value)
    if not raw:
        raise PathRootsError("OPS_TARGET_EMPTY", kind)
    _reject_windows_special(raw, kind)
    supplied = Path(raw)
    if not supplied.is_absolute():
        if roots.profile == PORTABLE_RELEASE_PROFILE:
            supplied = _operation_relative_base(roots, kind) / supplied
        else:
            supplied = Path(app_root) / supplied if app_root is not None else roots.APP_ROOT / supplied
    candidate = _normalise(supplied, kind)
    if target_type == "file" and candidate.name in {"", "."}:
        raise PathRootsError("OPS_TARGET_FILE_INVALID", kind)
    if roots.profile == PORTABLE_RELEASE_PROFILE:
        _assert_portable_operation_target_allowed(
            roots,
            candidate.parent if target_type == "file" else candidate,
            app_root=Path(app_root) if app_root is not None else roots.APP_ROOT,
            label=kind,
        )
        _assert_no_reparse(candidate, kind)
    else:
        _assert_no_reparse(candidate.parent if target_type == "file" else candidate, kind)
        _assert_no_reparse(candidate, kind)
    if must_exist and not (candidate.is_file() if target_type == "file" else candidate.is_dir()):
        raise PathRootsError("OPS_TARGET_MISSING", kind)
    if must_be_new and candidate.exists():
        raise PathRootsError("OPS_TARGET_EXISTS", kind)
    return candidate


def validate_new_operation_directory(
    roots: PathRoots,
    path: Path | str,
    kind: OperationTargetKind,
    *,
    app_root: Path | str | None = None,
) -> Path:
    candidate = resolve_operation_target(
        roots,
        path,
        kind,
        app_root=app_root,
        target_type="directory",
        must_be_new=True,
    )
    _assert_no_reparse(candidate.parent, kind)
    return candidate


def _create_and_check(paths: Iterable[tuple[Path, str]]) -> None:
    for path, label in paths:
        _assert_no_reparse(path, label)
        path.mkdir(parents=True, exist_ok=True)
        _assert_no_reparse(path, label)


def prepare_application_directories(roots: PathRoots) -> None:
    validate_path_roots_for_use(roots)
    _create_and_check(((roots.DATA_ROOT / name, "DATA_ROOT") for name in ("conversations", "canvases", "workflows", "trash")))
    _create_and_check(((roots.UPLOAD_ROOT / name, "UPLOAD_ROOT") for name in ("assets/input", "assets/output", "assets/library", "assets/uploads", "output")))
    _create_and_check(((roots.CACHE_ROOT / "media_previews", "CACHE_ROOT"), (roots.LOG_ROOT / "application", "LOG_ROOT"), (roots.TEMP_ROOT / "application", "TEMP_ROOT")))


def prepare_runtime_directories(roots: PathRoots) -> None:
    validate_path_roots_for_use(roots)
    _create_and_check(((roots.RUNTIME_ROOT / "control", "RUNTIME_ROOT"), (roots.LOG_ROOT / "runtime", "LOG_ROOT"), (roots.LOG_ROOT / "health", "LOG_ROOT"), (roots.LOG_ROOT / "crash", "LOG_ROOT")))


def prepare_ops_directories(roots: PathRoots) -> None:
    validate_path_roots_for_use(roots)
    _create_and_check(((roots.BACKUP_ROOT, "BACKUP_ROOT"), (roots.STAGING_ROOT / "reports", "STAGING_ROOT"), (roots.STAGING_ROOT / "workspace", "STAGING_ROOT"), (roots.LOG_ROOT / "ops", "LOG_ROOT")))


def prepare_install_state_directories(roots: PathRoots) -> None:
    validate_path_roots_for_use(roots)
    _create_and_check(((roots.CONFIG_ROOT, "CONFIG_ROOT"), (roots.STATE_ROOT, "STATE_ROOT")))


_installed_roots: PathRoots | None = None
_install_lock = threading.Lock()


def install_path_roots_for_process(roots: PathRoots) -> PathRoots:
    global _installed_roots
    validate_path_roots_for_use(roots)
    with _install_lock:
        if _installed_roots is None:
            _installed_roots = roots
        elif _installed_roots != roots:
            raise PathRootsError("PATH_ROOTS_PROCESS_REINITIALIZATION")
        return _installed_roots


def get_path_roots() -> PathRoots:
    if _installed_roots is None:
        raise PathRootsError("PATH_ROOTS_PROCESS_UNINITIALIZED")
    return _installed_roots


def _reset_path_roots_for_tests() -> None:
    """Test-only reset.  It is intentionally private and never called by runtime code."""
    global _installed_roots
    with _install_lock:
        _installed_roots = None
