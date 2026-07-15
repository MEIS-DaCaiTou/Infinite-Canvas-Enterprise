"""Bounded, role-aware local TCP and HTTP health checks."""

from __future__ import annotations

import http.client
import json
import socket
from dataclasses import asdict, dataclass
from typing import Any


MAX_BODY_BYTES = 64 * 1024


@dataclass(frozen=True)
class HealthResult:
    ok: bool
    category: str
    status_code: int | None = None

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)


def tcp_check(host: str, port: int, *, timeout_seconds: float = 2.0) -> HealthResult:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return HealthResult(True, "tcp_ok")
    except ConnectionRefusedError:
        return HealthResult(False, "connection_refused")
    except socket.timeout:
        return HealthResult(False, "connect_timeout")
    except OSError:
        return HealthResult(False, "tcp_failure")


def _http_check(host: str, port: int, path: str, *, timeout_seconds: float = 3.0) -> tuple[HealthResult, bytes]:
    connection = http.client.HTTPConnection(host, port, timeout=timeout_seconds)
    try:
        connection.request("GET", path, headers={"Accept": "application/json", "User-Agent": "Infinite-Canvas-Enterprise-Runtime"})
        response = connection.getresponse()
        body = response.read(MAX_BODY_BYTES + 1)
        if len(body) > MAX_BODY_BYTES:
            return HealthResult(False, "response_too_large", response.status), b""
        return HealthResult(200 <= response.status < 300, "http_ok" if 200 <= response.status < 300 else "http_failure", response.status), body
    except socket.timeout:
        return HealthResult(False, "read_timeout"), b""
    except (ConnectionRefusedError, http.client.HTTPException, OSError):
        return HealthResult(False, "connection_failure"), b""
    finally:
        connection.close()


def upstream_health(host: str, port: int) -> HealthResult:
    result, _body = _http_check(host, port, "/api/app-info")
    return result


def gateway_health(host: str, port: int) -> HealthResult:
    result, body = _http_check(host, port, "/enterprise/health")
    if result.ok:
        return result
    if result.status_code == 503:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return result
        if type(payload) is dict and payload.get("gateway") == "ok" and payload.get("upstream") == "unreachable":
            return HealthResult(False, "upstream_unavailable", 503)
    return result
