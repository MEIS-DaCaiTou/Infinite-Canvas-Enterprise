"""Bounded, redacted runtime logging primitives."""

from __future__ import annotations

import json
import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAX_LOG_BYTES = 10 * 1024 * 1024
MAX_LOG_BACKUPS = 10
_SENSITIVE_KEY = re.compile(r"(?:authorization|cookie|token|secret|password|api[_-]?key|jwt)", re.IGNORECASE)
_SENSITIVE_TEXT = (
    (re.compile(r"(?i)(authorization\s*[:=]\s*)([^\r\n]+)"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(bearer\s+)([^\s,;]+)"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(cookie\s*[:=]\s*)([^\r\n]+)"), r"\1[REDACTED]"),
    (re.compile(r"(?i)((?:api[_-]?key|github_token|jwt_secret|password|secret)\s*[:=]\s*)([^\s,;]+)"), r"\1[REDACTED]"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def redact_text(value: object) -> str:
    text = str(value)
    for pattern, replacement in _SENSITIVE_TEXT:
        text = pattern.sub(replacement, text)
    return text


def redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _SENSITIVE_KEY.search(str(key)) else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


class RotatingTextLog:
    """Small dependency-free, synchronous rotating text writer.

    Child streams are pumped through this writer so stdout/stderr are rotated
    and redacted as well as supervisor-originated events.
    """

    def __init__(self, path: Path, *, max_bytes: int = MAX_LOG_BYTES, backups: int = 5) -> None:
        if type(max_bytes) is not int or max_bytes < 64 * 1024 or max_bytes > MAX_LOG_BYTES:
            raise ValueError("runtime log size must be between 64 KiB and 10 MiB")
        if type(backups) is not int or backups < 1 or backups > MAX_LOG_BACKUPS:
            raise ValueError("runtime log backup count must be between 1 and 10")
        self.path = path
        self.max_bytes = max_bytes
        self.backups = backups
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def _rotate_locked(self) -> None:
        try:
            if self.path.stat().st_size < self.max_bytes:
                return
        except OSError:
            return
        for index in range(self.backups, 0, -1):
            older = self.path.with_name(f"{self.path.name}.{index}")
            newer = self.path.with_name(f"{self.path.name}.{index + 1}")
            if index == self.backups:
                try:
                    older.unlink()
                except FileNotFoundError:
                    pass
            elif older.exists():
                older.replace(newer)
        if self.path.exists():
            self.path.replace(self.path.with_name(f"{self.path.name}.1"))
        self.path.touch(exist_ok=True)

    def write(self, value: object) -> None:
        text = redact_text(value)
        with self._lock:
            self._rotate_locked()
            with self.path.open("a", encoding="utf-8", newline="") as handle:
                handle.write(text)
                if not text.endswith("\n"):
                    handle.write("\n")
                handle.flush()


class StreamPump:
    """Persist one child pipe with optional foreground mirroring."""

    def __init__(self, source: Any, destination: RotatingTextLog, *, mirror: bool = False) -> None:
        self._source = source
        self._destination = destination
        self._mirror = mirror
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def join(self, timeout: float = 1.0) -> None:
        self._thread.join(timeout=timeout)

    def _run(self) -> None:
        try:
            while True:
                chunk = self._source.readline()
                if not chunk:
                    break
                if isinstance(chunk, bytes):
                    text = chunk.decode("utf-8", errors="replace")
                else:
                    text = str(chunk)
                redacted = redact_text(text)
                self._destination.write(redacted)
                if self._mirror:
                    sys.stdout.write(redacted)
                    sys.stdout.flush()
        finally:
            try:
                self._source.close()
            except Exception:
                pass


class RuntimeLogs:
    """Named runtime logs and structured crash-event JSONL output."""

    def __init__(self, root: Path, *, max_bytes: int = MAX_LOG_BYTES, backups: int = 5, foreground: bool = False) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.foreground = foreground
        self._logs = {
            name: RotatingTextLog(self.root / name, max_bytes=max_bytes, backups=backups)
            for name in (
                "launcher.log",
                "supervisor.log",
                "upstream.stdout.log",
                "upstream.stderr.log",
                "gateway.stdout.log",
                "gateway.stderr.log",
                "health.log",
                "crash-events.jsonl",
            )
        }

    def write(self, name: str, event: str, **fields: Any) -> None:
        payload = {"ts": utc_now(), "event": event, **redact_value(fields)}
        self._logs[name].write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))

    def stream_pumps(self, role: str) -> tuple[RotatingTextLog, RotatingTextLog]:
        if role not in {"upstream", "gateway"}:
            raise ValueError("runtime role is invalid")
        return self._logs[f"{role}.stdout.log"], self._logs[f"{role}.stderr.log"]

    def crash_event(self, **fields: Any) -> None:
        self.write("crash-events.jsonl", "crash_event", **fields)
