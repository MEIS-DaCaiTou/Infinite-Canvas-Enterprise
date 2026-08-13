"""Bounded, redacted Runtime/update diagnostics for the Update Center."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

from enterprise.paths import PathRoots
from enterprise.runtime.logging import redact_text, redact_value, utc_now


MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_LINES = 500
LOG_NAMES = frozenset(
    {
        "launcher.log",
        "supervisor.log",
        "upstream.stdout.log",
        "upstream.stderr.log",
        "gateway.stdout.log",
        "gateway.stderr.log",
        "health.log",
        "crash-events.jsonl",
    }
)


def _read_small_json(path: Path, maximum: int = 64 * 1024) -> dict[str, Any] | None:
    data = bytearray()
    try:
        with path.open("rb") as handle:
            while len(data) < maximum + 1:
                chunk = handle.read(min(16 * 1024, maximum + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
    except OSError:
        return None
    if not data or len(data) > maximum:
        return None
    try:
        payload = json.loads(bytes(data).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return None
    return payload if type(payload) is dict else None


def _tail_lines(path: Path, *, limit: int, secret_values: tuple[str, ...]) -> list[str]:
    if not path.is_file():
        return []
    size = path.stat().st_size
    with path.open("rb") as handle:
        handle.seek(max(0, size - MAX_SOURCE_BYTES))
        raw = handle.read(MAX_SOURCE_BYTES)
    text = raw.decode("utf-8", errors="replace")
    return [redact_text(line, secret_values=secret_values)[:4096] for line in text.splitlines()[-limit:]]


def recent_diagnostics(
    roots: PathRoots,
    *,
    job_id: str | None = None,
    limit: int = 100,
    level: str = "",
    keyword: str = "",
    secret_values: tuple[str, ...] = (),
) -> dict[str, Any]:
    limit = min(max(int(limit), 1), MAX_LINES)
    level = str(level or "").strip().casefold()[:32]
    keyword = str(keyword or "").strip().casefold()[:128]
    records: list[dict[str, str]] = []
    for name in sorted(LOG_NAMES):
        for line in _tail_lines(roots.LOG_ROOT / "runtime" / name, limit=limit, secret_values=secret_values):
            folded = line.casefold()
            if level and level not in folded:
                continue
            if keyword and keyword not in folded:
                continue
            records.append({"source": name, "line": line})
    if job_id:
        events = roots.STAGING_ROOT / "update-mvp" / "jobs" / job_id / "events.jsonl"
        for line in _tail_lines(events, limit=limit, secret_values=secret_values):
            folded = line.casefold()
            if level and level not in folded:
                continue
            if keyword and keyword not in folded:
                continue
            records.append({"source": "update-events.jsonl", "line": line})
    summary: dict[str, Any] = {}
    state_path = roots.RUNTIME_ROOT / "runtime-state.json"
    state = _read_small_json(state_path)
    if state is not None:
        summary["runtime"] = _public_snapshot(state)
    elif state_path.exists():
        summary["runtime"] = {"status": "unavailable"}
    if job_id:
        status_path = roots.STAGING_ROOT / "update-mvp" / "jobs" / job_id / "status.json"
        status = _read_small_json(status_path)
        if status is not None:
            summary["update_job"] = _public_snapshot(status)
        elif status_path.exists():
            summary["update_job"] = {"status": "unavailable"}
    return {
        "schema_version": "enterprise-update-diagnostics-v1",
        "generated_at": utc_now(),
        "summary": redact_value(summary, secret_values=secret_values),
        "record_count": min(len(records), limit),
        "records": redact_value(records[-limit:], secret_values=secret_values),
    }


def _public_snapshot(value: Any, *, key: str = "") -> Any:
    if isinstance(value, dict):
        return {str(name): _public_snapshot(item, key=str(name)) for name, item in value.items()}
    if isinstance(value, list):
        return [_public_snapshot(item, key=key) for item in value[:100]]
    if isinstance(value, str) and any(part in key.casefold() for part in ("path", "root", "executable")):
        return Path(value).name if value else ""
    return value


def diagnostics_zip(payload: dict[str, Any]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "update-diagnostics.json",
            (json.dumps(redact_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"),
        )
    return output.getvalue()
