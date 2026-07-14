"""Monotonic, secret-free online-update job state and workspace reports."""

from __future__ import annotations

import json
import math
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from enterprise.ops.update.errors import OnlineUpdateError, OnlineUpdateValidationError


JOB_STATES = {
    "created",
    "checking",
    "metadata_ready",
    "downloading",
    "verifying",
    "staging",
    "staged",
    "planned",
    "failed",
}
TERMINAL_STATES = {"failed"}
ALLOWED_TRANSITIONS = {
    "created": {"checking", "staging", "planned", "failed"},
    "checking": {"metadata_ready", "failed"},
    "metadata_ready": {"downloading", "failed"},
    "downloading": {"verifying", "failed"},
    "verifying": {"staging", "failed"},
    "staging": {"staged", "failed"},
    "staged": {"planned", "failed"},
    "planned": set(),
    "failed": set(),
}
SENSITIVE_KEY_FRAGMENTS = (
    "token",
    "cookie",
    "authorization",
    "password",
    "secret",
    "api_key",
    "apikey",
    "credential",
    "jwt",
    "env",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_workspace(path: str | os.PathLike[str], *, app_root: Path) -> Path:
    """Require an existing workspace distinct from the application root."""
    workspace = Path(path)
    if not workspace.exists() or not workspace.is_dir():
        raise OnlineUpdateValidationError("OPS workspace must be an existing directory")
    try:
        resolved = workspace.resolve(strict=True)
        root = app_root.resolve(strict=True)
        if resolved == root or resolved.is_relative_to(root):
            raise OnlineUpdateValidationError("OPS workspace must not be the application root")
    except OSError as exc:
        raise OnlineUpdateValidationError("OPS workspace could not be validated") from exc
    return resolved


def workspace_child(workspace: Path, candidate: Path) -> Path:
    """Require a new or existing path to remain inside the explicit workspace."""
    try:
        resolved_candidate = candidate.resolve(strict=False)
        resolved_candidate.relative_to(workspace)
    except (OSError, ValueError) as exc:
        raise OnlineUpdateValidationError("OPS workspace path is invalid") from exc
    return resolved_candidate


def workspace_relative(workspace: Path, candidate: Path) -> str:
    """Return a stable workspace-relative path for reports and JSONL logs."""
    return workspace_child(workspace, candidate).relative_to(workspace).as_posix()


def _safe_json_value(value: Any) -> Any:
    if type(value) is dict:
        result: dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key)
            normalized = key_text.casefold().replace("-", "_")
            if any(fragment in normalized for fragment in SENSITIVE_KEY_FRAGMENTS):
                result[key_text] = "[redacted]"
            else:
                result[key_text] = _safe_json_value(child)
        return result
    if type(value) is list:
        return [_safe_json_value(child) for child in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else "[unsupported]"
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return "[unsupported]"


def _atomic_json_create(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise OnlineUpdateValidationError("OPS report destination already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(_safe_json_value(payload), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        temporary.unlink()
    except FileExistsError as exc:
        raise OnlineUpdateValidationError("OPS report destination already exists") from exc
    except OSError as exc:
        raise OnlineUpdateValidationError("OPS report could not be written") from exc
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


@dataclass
class UpdateJob:
    """Monotonic update-preparation job with structured JSON-safe facts."""

    job_type: str
    workspace: Path
    job_id: str = field(default_factory=lambda: f"online-update-{uuid.uuid4().hex}")
    state: str = "created"
    started_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    finished_at: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)
    report_paths: list[str] = field(default_factory=list)
    failure_code: str = ""
    failure_message: str = ""

    def transition(self, state: str, **fields: Any) -> None:
        if self.finished_at is not None:
            raise OnlineUpdateValidationError("a completed online update job cannot change state")
        if state not in JOB_STATES or state not in ALLOWED_TRANSITIONS[self.state]:
            raise OnlineUpdateValidationError("online update job state transition is invalid")
        self.state = state
        self.updated_at = utc_now()
        self.fields.update(_safe_json_value(fields))
    def complete(self) -> None:
        """Mark a successfully completed command without changing its stage state."""
        if self.state == "failed":
            raise OnlineUpdateValidationError("a failed online update job cannot complete")
        self.updated_at = utc_now()
        self.finished_at = self.updated_at

    def fail(self, error: OnlineUpdateError) -> None:
        if self.finished_at is not None or self.state == "failed":
            return
        self.state = "failed"
        self.updated_at = utc_now()
        self.finished_at = self.updated_at
        self.failure_code = error.code
        self.failure_message = error.public_message

    def snapshot(self, *, status: str) -> dict[str, Any]:
        return {
            "kind": "online-update-job-report",
            "job_id": self.job_id,
            "job_type": self.job_type,
            "status": status,
            "state": self.state,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
            **_safe_json_value(self.fields),
            "report_paths": list(self.report_paths),
            "failure_code": self.failure_code,
            "failure_message": self.failure_message,
        }

    def write_report(self, *, status: str) -> dict[str, Any]:
        path = workspace_child(self.workspace, self.workspace / "reports" / f"{self.job_id}.json")
        relative_path = workspace_relative(self.workspace, path)
        self.report_paths.append(relative_path)
        report = self.snapshot(status=status)
        _atomic_json_create(path, report)
        return report

    def append_log(self, event: str, **details: Any) -> None:
        path = workspace_child(self.workspace, self.workspace / "jobs.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = _safe_json_value(
            {
                "ts": utc_now(),
                "job_id": self.job_id,
                "job_type": self.job_type,
                "state": self.state,
                "event": event,
                "details": details,
            }
        )
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
