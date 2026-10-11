"""Complete bounded GitHub catalogs; cached bytes require HTTP revalidation.

The cache is an optimization, never an offline source of upgrade authority. It
contains no credentials, writes no files and has no retention/TTL policy.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import parse_qs, urlparse

from enterprise.ops.update.errors import OnlineUpdateError, ReleaseCatalogError
from enterprise.ops.update.http_client import JsonHttpResponse, SafeHttpClient


CATALOG_PAGE_SIZE = 50
MAX_CATALOG_RECORDS = 1000
MAX_CATALOG_PAGES = 21  # includes the empty terminator after exactly 1000 records
MAX_CACHE_SUBJECTS = 4
_ETAG = re.compile(r'(?:W/)?"[\x21\x23-\x7e]{0,500}"\Z')


@dataclass(frozen=True)
class CatalogSnapshot:
    records: tuple[object, ...]
    page_count: int
    conditional_hits: int

    def public_summary(self) -> dict[str, object]:
        return {
            "complete": True, "record_count": len(self.records),
            "page_count": self.page_count, "conditional_hits": self.conditional_hits,
        }


@dataclass(frozen=True)
class _Page:
    raw: bytes
    etag: str | None
    link: str | None


@dataclass
class _Bucket:
    lock: threading.Lock = field(default_factory=threading.Lock)
    pages: dict[int, _Page] = field(default_factory=dict)


class ReleaseCatalogCache:
    """Bounded process cache isolated by repository and credential fingerprint."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: OrderedDict[tuple[str, bytes], _Bucket] = OrderedDict()

    def bucket(self, repository: str, headers: Mapping[str, str]) -> _Bucket:
        identity = hashlib.sha256(headers.get("Authorization", "").encode("utf-8")).digest()
        key = (repository, identity)
        with self._lock:
            bucket = self._buckets.setdefault(key, _Bucket())
            self._buckets.move_to_end(key)
            while len(self._buckets) > MAX_CACHE_SUBJECTS:
                self._buckets.popitem(last=False)
            return bucket


class _CatalogMoved(Exception):
    pass


def _next_page(link: str | None, repository: str, repository_id: int, current: int) -> int | None:
    """Validate next-page authority; never follow a server-supplied URL."""
    if link is None:
        return None
    if not isinstance(link, str) or len(link) > 8192 or any(ord(char) < 32 for char in link):
        raise ReleaseCatalogError()
    next_number = None
    for part in link.split(","):
        match = re.fullmatch(r'\s*<([^<>]+)>\s*;\s*rel="([a-z ]+)"\s*', part)
        if match is None:
            raise ReleaseCatalogError()
        if "next" not in match[2].split():
            continue
        parsed = urlparse(match[1])
        try:
            query = parse_qs(parsed.query, strict_parsing=True, keep_blank_values=True)
            port = parsed.port
        except ValueError as exc:
            raise ReleaseCatalogError() from exc
        if (
            next_number is not None or parsed.scheme != "https"
            or parsed.hostname != "api.github.com" or port not in {None, 443}
            or parsed.username or parsed.password or parsed.fragment
            or parsed.path.casefold() not in {
                f"/repos/{repository}/releases".casefold(),
                f"/repositories/{repository_id}/releases",
            }
            or query != {"per_page": [str(CATALOG_PAGE_SIZE)], "page": [str(current + 1)]}
        ):
            raise ReleaseCatalogError()
        next_number = current + 1
    return next_number


def read_catalog(
    *, repository: str, repository_id: int, client: SafeHttpClient, cache: ReleaseCatalogCache,
    maximum_bytes: int, headers: Mapping[str, str],
) -> CatalogSnapshot:
    """Publish all pages together, or expose no update candidates at all.

    Offset pagination can move while a release is published. Recheck the first
    page after a multi-page crawl and restart once if its bytes/link changed or
    an ID overlapped a page boundary. This is not a GitHub transaction snapshot;
    all chosen route/Manifest/archive authority is checked again in prepare.
    """
    bucket = cache.bucket(repository, headers)
    with bucket.lock:
        for attempt in range(2):
            staged: dict[int, _Page] = {}
            hits = 0

            def fetch(number: int, prior: Mapping[int, _Page]) -> _Page:
                nonlocal hits
                previous = prior.get(number)
                request_headers = dict(headers)
                if previous is not None and previous.etag is not None:
                    request_headers["If-None-Match"] = previous.etag
                url = f"https://api.github.com/repos/{repository}/releases?per_page={CATALOG_PAGE_SIZE}&page={number}"
                response: JsonHttpResponse = client.read_json_response(
                    url, maximum_bytes=maximum_bytes, headers=request_headers,
                )
                if response.redirect_count != 0 or response.status not in {200, 304}:
                    raise ReleaseCatalogError()
                if response.etag is not None and (
                    not isinstance(response.etag, str) or not _ETAG.fullmatch(response.etag)
                ):
                    raise ReleaseCatalogError()
                if response.status == 304:
                    if previous is None or previous.etag is None or response.value is not None:
                        raise ReleaseCatalogError()
                    if response.etag is not None and response.etag != previous.etag:
                        raise ReleaseCatalogError()
                    hits += 1
                    page = _Page(previous.raw, previous.etag, response.link if response.link is not None else previous.link)
                else:
                    value = response.value
                    if type(value) is not list or len(value) > CATALOG_PAGE_SIZE:
                        raise ReleaseCatalogError()
                    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    if len(raw) > maximum_bytes:
                        raise ReleaseCatalogError()
                    page = _Page(raw, response.etag, response.link)
                _next_page(page.link, repository, repository_id, number)
                return page

            try:
                records: list[object] = []
                identities: set[str] = set()
                for number in range(1, MAX_CATALOG_PAGES + 1):
                    page = fetch(number, bucket.pages if attempt == 0 else {})
                    values = json.loads(page.raw)
                    page_ids = []
                    for item in values:
                        raw_id = item.get("id") if type(item) is dict else None
                        if type(raw_id) is int and raw_id >= 0:
                            page_ids.append(str(raw_id))
                        elif isinstance(raw_id, str) and raw_id and raw_id == raw_id.strip() and len(raw_id) <= 256:
                            page_ids.append(raw_id)
                    if len(set(page_ids)) != len(page_ids):
                        raise ReleaseCatalogError()
                    if identities.intersection(page_ids):
                        raise _CatalogMoved()
                    identities.update(page_ids)
                    staged[number] = page
                    records.extend(values)
                    if len(records) > MAX_CATALOG_RECORDS:
                        raise ReleaseCatalogError()
                    following = _next_page(page.link, repository, repository_id, number)
                    if following is None and len(values) < CATALOG_PAGE_SIZE:
                        break
                else:
                    raise ReleaseCatalogError()
                if len(staged) > 1:
                    head = fetch(1, staged)
                    first = staged[1]
                    if head.raw != first.raw or _next_page(head.link, repository, repository_id, 1) != _next_page(first.link, repository, repository_id, 1):
                        raise _CatalogMoved()
                    staged[1] = head
                bucket.pages = staged
                return CatalogSnapshot(tuple(records), len(staged), hits)
            except _CatalogMoved:
                if attempt == 1:
                    raise ReleaseCatalogError() from None
            except ReleaseCatalogError:
                raise
            except (OnlineUpdateError, OSError, ValueError) as exc:
                raise ReleaseCatalogError() from exc
    raise ReleaseCatalogError()
