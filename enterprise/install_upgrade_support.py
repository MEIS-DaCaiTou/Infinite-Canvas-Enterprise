"""Read-only classification of replaceable maintenance caches.

The installed program/identity is proved by install_lifecycle.current_source.
An old cache is never an execution source: the upgrade transaction retains its
original bytes and publishes the authenticated incoming Setup and new metadata.
Registration still requires strict validation of the newly published pair.
"""
from configparser import ConfigParser, Error as ConfigError
from dataclasses import dataclass

from enterprise import install_cache as files


SETUP = "state/windows-maintenance/maintenance-setup.exe"
INFO = "state/windows-maintenance/support.ini"
PRODUCT = "MEIS-DaCaiTou/Infinite-Canvas-Enterprise"
FIELDS = {"product", "installationid", "setupsha256", "setupsize"}


class SupportError(RuntimeError):
    def __init__(self, code="INSTALL_UPGRADE_SUPPORT_UNPROVEN"):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class SourceSupport:
    before: dict
    rebuild_required: bool
    reason: str


def _token(path, limit):
    files._safe(path, missing=True)
    if not files._exists(path):
        return None
    if files._io(path).stat().st_size > limit:
        raise SupportError()
    return files._file(path)


def _observe(root, installation_id):
    setup, info = root / SETUP, root / INFO
    before = {"setup": _token(setup, 512 * 1024 * 1024), "support": _token(info, 16384)}
    values = None
    sections = []
    if before["support"] is not None:
        raw = files._io(info).read_bytes()
        try:
            parser = ConfigParser(interpolation=None, strict=True)
            parser.read_string(raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"))
            sections = parser.sections()
            values = dict(parser["Lifecycle"])
        except (ConfigError, UnicodeError, KeyError, ValueError):
            pass
    # Recheck the same objects after reading; a race is not cache corruption.
    if before != {"setup": _token(setup, 512 * 1024 * 1024), "support": _token(info, 16384)}:
        raise SupportError("INSTALL_UPGRADE_SUPPORT_CHANGED")
    foreign = values is not None and (
        values.get("product", PRODUCT) != PRODUCT
        or values.get("installationid", installation_id) != installation_id)
    valid = (values is not None and sections == ["Lifecycle"]
        and set(values) in (FIELDS, FIELDS | {"uninstaller", "uninstallersha256"})
        and values["product"] == PRODUCT and values["installationid"] == installation_id
        and before["setup"] is not None
        and values["setupsha256"] == before["setup"]["sha256"]
        and values["setupsize"] == str(before["setup"]["size_bytes"]))
    reason = "verified" if valid else "missing" if None in before.values() else "damaged"
    return SourceSupport(before, not valid, reason), foreign


def inspect_source_support(root, installation_id):
    """Called only after current_source proves the installation and program."""
    observation, foreign = _observe(root, installation_id)
    if foreign:
        raise SupportError("INSTALL_UPGRADE_SUPPORT_IDENTITY_CONFLICT")
    return observation


def validate_published_support(root, installation_id):
    """Do not apply cache-rebuild tolerance to the target or registration."""
    observation, _foreign = _observe(root, installation_id)
    if all(value is None for value in observation.before.values()):
        return  # Legacy absence; the transaction's slot checks still apply.
    if observation.rebuild_required:
        raise SupportError()
