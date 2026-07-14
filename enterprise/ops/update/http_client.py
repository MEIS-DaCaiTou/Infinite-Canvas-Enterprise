"""Bounded HTTP access with redirect revalidation for trusted providers."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from typing import Any, Iterator, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from enterprise.ops.update.errors import ReleaseDownloadError, ReleaseProviderError


MAX_REDIRECTS = 3
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
SENSITIVE_REDIRECT_HEADERS = frozenset(
    {"authorization", "cookie", "proxy-authorization", "x-api-key", "x-auth-token", "x-access-token"}
)


@dataclass(frozen=True)
class UrlPolicy:
    """Allow only an explicit HTTPS host set, with test-only loopback HTTP."""

    allowed_hosts: frozenset[str]
    allow_loopback_http: bool = False

    def validate(self, url: object) -> str:
        if not isinstance(url, str) or not url or url != url.strip():
            raise ReleaseDownloadError("release URL is invalid")
        parsed = urlparse(url)
        host = (parsed.hostname or "").casefold()
        if parsed.username or parsed.password or parsed.fragment or not host:
            raise ReleaseDownloadError("release URL is invalid")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ReleaseDownloadError("release URL is invalid") from exc
        local_fixture_url = self.allow_loopback_http and parsed.scheme == "http" and host in LOOPBACK_HOSTS
        if port is not None and not local_fixture_url and port != 443:
            raise ReleaseDownloadError("release URL is not an approved HTTPS source")
        if parsed.scheme == "https" and host in self.allowed_hosts:
            return url
        if (
            local_fixture_url
        ):
            return url
        raise ReleaseDownloadError("release URL is not an approved HTTPS source")


class _ValidatedRedirectHandler(HTTPRedirectHandler):
    def __init__(self, policy: UrlPolicy) -> None:
        super().__init__()
        self._policy = policy
        self._redirect_count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        self._redirect_count += 1
        if self._redirect_count > MAX_REDIRECTS:
            raise ReleaseDownloadError("release redirect limit exceeded")
        redirect_url = urljoin(req.full_url, newurl)
        self._policy.validate(redirect_url)
        redirected = super().redirect_request(req, fp, code, msg, headers, redirect_url)
        if redirected is not None and _redirect_crosses_origin(req.full_url, redirect_url):
            _strip_sensitive_headers(redirected)
        return redirected


def _redirect_crosses_origin(source_url: str, destination_url: str) -> bool:
    source = urlparse(source_url)
    destination = urlparse(destination_url)
    return (
        source.scheme.casefold(),
        (source.hostname or "").casefold(),
        source.port,
    ) != (
        destination.scheme.casefold(),
        (destination.hostname or "").casefold(),
        destination.port,
    )


def _strip_sensitive_headers(request: Request) -> None:
    """Remove credentials copied by urllib before an origin-changing redirect."""
    for mapping in (request.headers, request.unredirected_hdrs):
        for key in tuple(mapping):
            if key.casefold() in SENSITIVE_REDIRECT_HEADERS:
                del mapping[key]


def _content_length(headers: Mapping[str, str]) -> int | None:
    raw = headers.get("Content-Length")
    if raw is None:
        return None
    if not raw.isascii() or not raw.isdecimal():
        raise ReleaseDownloadError("release content length is invalid")
    return int(raw)


class SafeHttpClient:
    """Small standard-library HTTP client that never retains response bodies."""

    def __init__(self, policy: UrlPolicy, *, timeout_seconds: int = 10) -> None:
        if type(timeout_seconds) is not int or timeout_seconds < 1 or timeout_seconds > 60:
            raise ValueError("timeout_seconds must be between 1 and 60")
        self.policy = policy
        self.timeout_seconds = timeout_seconds

    def stream(
        self,
        url: str,
        *,
        maximum_bytes: int,
        headers: Mapping[str, str] | None = None,
    ) -> Iterator[tuple[Any, int | None, int]]:
        """Yield one bounded response; callers must consume it with a context manager."""
        if type(maximum_bytes) is not int or maximum_bytes < 1:
            raise ValueError("maximum_bytes must be a positive integer")
        self.policy.validate(url)
        redirect_handler = _ValidatedRedirectHandler(self.policy)
        opener = build_opener(redirect_handler)
        request_headers = {"Accept": "application/json"}
        if headers:
            request_headers.update(headers)
        request = Request(url, headers=request_headers, method="GET")
        try:
            response = opener.open(request, timeout=self.timeout_seconds)
        except (HTTPError, URLError, socket.timeout, TimeoutError) as exc:
            raise ReleaseDownloadError("trusted release source request failed") from exc
        expected_length = _content_length(response.headers)
        if expected_length is not None and expected_length > maximum_bytes:
            response.close()
            raise ReleaseDownloadError("trusted release response exceeds its size limit")

        class _ResponseIterator:
            def __iter__(self) -> Iterator[tuple[Any, int | None, int]]:
                try:
                    yield response, expected_length, redirect_handler._redirect_count
                finally:
                    response.close()

        return iter(_ResponseIterator())

    def read_json(
        self,
        url: str,
        *,
        maximum_bytes: int,
        headers: Mapping[str, str] | None = None,
    ) -> object:
        """Read a bounded UTF-8 JSON document without exposing a remote body on errors."""
        data = self.read_bytes(url, maximum_bytes=maximum_bytes, headers=headers)
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReleaseProviderError("trusted release metadata is invalid JSON") from exc

    def read_bytes(
        self,
        url: str,
        *,
        maximum_bytes: int,
        headers: Mapping[str, str] | None = None,
    ) -> bytes:
        """Read a bounded small document such as metadata or a manifest."""
        data, _redirect_count = self.read_bytes_with_redirect_count(
            url,
            maximum_bytes=maximum_bytes,
            headers=headers,
        )
        return data

    def read_bytes_with_redirect_count(
        self,
        url: str,
        *,
        maximum_bytes: int,
        headers: Mapping[str, str] | None = None,
    ) -> tuple[bytes, int]:
        """Read a bounded document and return only its redirect count as evidence."""
        chunks: list[bytes] = []
        received = 0
        redirect_count = 0
        for response, _content_size, redirect_count in self.stream(url, maximum_bytes=maximum_bytes, headers=headers):
            while True:
                chunk = response.read(min(64 * 1024, maximum_bytes - received + 1))
                if not chunk:
                    break
                received += len(chunk)
                if received > maximum_bytes:
                    raise ReleaseDownloadError("trusted release response exceeds its size limit")
                chunks.append(chunk)
        return b"".join(chunks), redirect_count
