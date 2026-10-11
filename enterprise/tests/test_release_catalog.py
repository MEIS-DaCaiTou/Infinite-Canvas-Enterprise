"""Catalog/network/cache contracts; no Release or installation is modified."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from enterprise.ops.update.errors import ReleaseCatalogError, ReleaseDownloadError
from enterprise.ops.update.http_client import JsonHttpResponse, SafeHttpClient, UrlPolicy
from enterprise.ops.update.providers import DEFAULT_GITHUB_REPOSITORY, DEFAULT_GITHUB_REPOSITORY_ID, GitHubReleasesProvider
from enterprise.ops.update.release_catalog import MAX_CATALOG_RECORDS, ReleaseCatalogCache
from enterprise.ops.update.route_catalog import RoutePreviewCache
from enterprise.ops.update.upgrade_routes import ReleaseState, UpgradeRouteError
from enterprise.tests.test_ops_3a_online_update import FixtureHandler, LocalServer
from enterprise.tests.test_upgrade_routes import _document, _sha


REPO = DEFAULT_GITHUB_REPOSITORY
URL = f"https://api.github.com/repos/{REPO}/releases?per_page=50&page=1"


def release(identifier=90, version="2026.08.1", *, development=False):
    def asset(name, asset_id):
        return {"id": asset_id, "name": name, "state": "uploaded", "size": 100,
                "url": f"https://api.github.com/repos/{REPO}/releases/assets/{asset_id}"}
    return {
        "id": identifier, "tag_name": "v" + version, "draft": False,
        "prerelease": development, "published_at": "2026-10-11T00:00:00Z",
        "assets": [asset("ops-release-manifest-v1.json", identifier * 10),
                   asset("ops-release-manifest-v2.json", identifier * 10 + 1),
                   asset("release-payload-inventory.json", identifier * 10 + 2),
                   asset("Infinite-Canvas-Enterprise-test-win-x64.zip", identifier * 10 + 3),
                   {**asset("upgrade-routes-v1.json", identifier * 10 + 4), "digest": "sha256:" + "a" * 64}],
    }


class Client:
    def __init__(self, pages, *, links=None):
        self.pages = pages
        self.links = links or {}
        self.calls = []
        self.fail_page = None
        self.forced = None

    def read_json_response(self, url, *, headers, **_kwargs):
        assert url.startswith(f"https://api.github.com/repos/{REPO}/releases?")
        number = int(parse_qs(urlparse(url).query)["page"][0])
        self.calls.append((number, dict(headers)))
        if number == self.fail_page:
            raise ReleaseDownloadError(detail_code="RELEASE_HTTP_REQUEST_FAILED")
        if self.forced is not None:
            return self.forced
        value = self.pages.get(number, [])
        digest = '"' + hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest() + '"'
        if headers.get("If-None-Match") == digest:
            return JsonHttpResponse(None, 304, digest, self.links.get(number))
        return JsonHttpResponse(value, etag=digest, link=self.links.get(number))


@pytest.fixture(autouse=True)
def no_workstation_credential(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


@pytest.mark.parametrize("v2", [False, True])
def test_both_formats_include_page_two_and_revalidate_all_pages(v2):
    client = Client({1: [{"id": n, "draft": True} for n in range(1, 51)], 2: [release()]})
    provider = GitHubReleasesProvider(http_client=client)
    read = provider.list_release_v2_candidates if v2 else provider.list_releases
    assert len(read()) == 1
    assert provider.record_count == 51
    assert provider.catalog_snapshot.page_count == 2
    assert [n for n, _ in client.calls] == [1, 2, 1]
    assert provider.catalog_snapshot.conditional_hits == 1  # head consistency check
    client.calls.clear()
    assert len(read()) == 1
    assert provider.catalog_snapshot.conditional_hits == 3
    assert [n for n, _ in client.calls] == [1, 2, 1]
    assert all("If-None-Match" in headers for _, headers in client.calls)


def test_full_page_requires_an_empty_terminator_without_link():
    provider = GitHubReleasesProvider(http_client=Client({1: [{"id": n, "draft": True} for n in range(50)]}))
    assert provider.list_release_v2_candidates() == []
    assert provider.record_count == 50
    assert provider.catalog_snapshot.page_count == 2


def test_short_page_with_next_link_is_not_mistaken_for_complete_history():
    client = Client({1: [{"id": 1, "draft": True}], 2: [release()]},
                    links={1: f'<{URL.replace("page=1", "page=2")}>; rel="next"'})
    assert len(GitHubReleasesProvider(http_client=client).list_release_v2_candidates()) == 1


@pytest.mark.parametrize("uri", [
    f"https://api.github.com/repositories/{DEFAULT_GITHUB_REPOSITORY_ID}/releases",
    f"https://api.github.com/repos/{REPO.lower()}/releases",
])
def test_real_github_numeric_alias_and_case_normalization_are_bound_to_this_repository(uri):
    client = Client({1: [{"id": 1, "draft": True}], 2: [release()]},
                    links={1: f'<{uri}?per_page=50&page=2>; rel="next"'})
    assert len(GitHubReleasesProvider(http_client=client).list_release_v2_candidates()) == 1
    assert [number for number, _ in client.calls] == [1, 2, 1]


@pytest.mark.parametrize("link", [
    '<https://example.invalid/releases?page=2>; rel="next"',
    '<https://api.github.com/repos/other/repo/releases?per_page=50&page=2>; rel="next"',
    f'<https://api.github.com/repositories/{DEFAULT_GITHUB_REPOSITORY_ID + 1}/releases?per_page=50&page=2>; rel="next"',
    f'<{URL}>; rel="next"',
    f'<{URL.replace("page=1", "page=3")}>; rel="next"',
    f'<{URL.replace("page=1", "page=2")}&token=private>; rel="next"',
    f'<{URL.replace("page=1", "page=2")}>; rel="next", <{URL}>; rel="next"',
    'malformed', '\r\nAuthorization: private',
])
def test_bad_link_cannot_redirect_or_expand_catalog_authority(link):
    client = Client({1: [release()]}, links={1: link})
    provider = GitHubReleasesProvider(http_client=client)
    with pytest.raises(ReleaseCatalogError):
        provider.list_release_v2_candidates()
    assert len(client.calls) == 1
    assert provider.catalog_snapshot is None and provider.record_count == 0


@pytest.mark.parametrize("response", [
    JsonHttpResponse(None, 304), JsonHttpResponse([], 206),
    JsonHttpResponse([], redirect_count=1), JsonHttpResponse({}, 200),
    JsonHttpResponse([{}] * 51), JsonHttpResponse([], etag='"ok"\r\nsecret'),
    JsonHttpResponse([{"body": "x" * (1024 * 1024 + 1)}]),
])
def test_unbound_304_redirect_partial_or_oversized_response_is_rejected(response):
    client = Client({})
    client.forced = response
    with pytest.raises(ReleaseCatalogError):
        GitHubReleasesProvider(http_client=client).list_releases()


def test_failure_never_publishes_partial_pages_or_returns_stale_cache():
    client = Client({1: [{"id": n, "draft": True} for n in range(50)], 2: [release()]})
    provider = GitHubReleasesProvider(http_client=client)
    assert len(provider.list_releases()) == 1
    client.fail_page = 2
    with pytest.raises(ReleaseCatalogError):
        provider.list_releases()
    assert provider.record_count == 0 and provider.catalog_snapshot is None
    client.fail_page = None
    client.pages[2] = [release(91)]
    assert provider.list_releases()[0].release_id == "91"


def test_cache_is_isolated_across_credential_rotation_and_anonymous_access(monkeypatch):
    cache = ReleaseCatalogCache()
    client = Client({1: [release()]})
    for credential in ["synthetic-a", "synthetic-b", ""]:
        monkeypatch.setenv("GITHUB_TOKEN", credential)
        provider = GitHubReleasesProvider(http_client=client, catalog_cache=cache)
        provider.list_releases()
        assert "If-None-Match" not in client.calls[-1][1]
        provider.list_releases()
        assert "If-None-Match" in client.calls[-1][1]
    assert "synthetic-a" not in repr(cache._buckets)
    assert "synthetic-b" not in repr(cache._buckets)


def test_cache_subjects_are_bounded(monkeypatch):
    cache = ReleaseCatalogCache()
    client = Client({1: []})
    for number in range(8):
        monkeypatch.setenv("GITHUB_TOKEN", f"synthetic-{number}")
        GitHubReleasesProvider(http_client=client, catalog_cache=cache).list_releases()
    assert len(cache._buckets) == 4


@pytest.mark.parametrize("count, accepted", [(MAX_CATALOG_RECORDS, True), (MAX_CATALOG_RECORDS + 1, False)])
def test_capacity_boundary_is_explicit_and_fail_closed(count, accepted):
    rows = [{"id": n, "draft": True} for n in range(count)]
    client = Client({n // 50 + 1: rows[n:n + 50] for n in range(0, count, 50)})
    provider = GitHubReleasesProvider(http_client=client)
    if accepted:
        assert provider.list_releases() == []
        assert provider.record_count == MAX_CATALOG_RECORDS
        assert provider.catalog_snapshot.page_count == 21
    else:
        with pytest.raises(ReleaseCatalogError):
            provider.list_releases()
        assert provider.catalog_snapshot is None


@pytest.mark.parametrize("second", [release(), {**release(), "id": "90"}])
def test_duplicate_within_a_page_is_invalid(second):
    with pytest.raises(ReleaseCatalogError):
        GitHubReleasesProvider(http_client=Client({1: [release(), second]})).list_releases()


def test_boundary_overlap_restarts_once_and_keeps_refusing_unstable_history():
    client = Client({1: [{"id": n, "draft": True} for n in range(1, 51)], 2: [release(50)]})
    with pytest.raises(ReleaseCatalogError):
        GitHubReleasesProvider(http_client=client).list_releases()
    assert [n for n, _ in client.calls] == [1, 2, 1, 2]


def test_publication_during_pagination_restarts_the_whole_snapshot():
    class Moving(Client):
        def read_json_response(self, url, **kwargs):
            if len(self.calls) == 2:
                self.pages[1][0] = {"id": 99, "draft": True}
            return super().read_json_response(url, **kwargs)
    client = Moving({1: [{"id": n, "draft": True} for n in range(1, 51)], 2: [release()]})
    provider = GitHubReleasesProvider(http_client=client)
    assert len(provider.list_releases()) == 1
    assert [n for n, _ in client.calls] == [1, 2, 1, 1, 2, 1]
    assert provider.catalog_snapshot.records[0]["id"] == 99


def test_concurrent_readers_share_only_revalidated_complete_snapshots():
    client = Client({1: [release()]})
    cache = ReleaseCatalogCache()
    def read(_):
        provider = GitHubReleasesProvider(http_client=client, catalog_cache=cache)
        return provider.list_releases()[0].release_id
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(read, range(8))) == ["90"] * 8
    assert len(client.calls) == 8
    assert sum("If-None-Match" in headers for _, headers in client.calls) == 7


def test_real_http_304_requires_cached_authority_and_assets_still_reject_304():
    FixtureHandler.responses = {"/catalog": (200, {"ETag": '"one"'}, b"[]")}
    FixtureHandler.request_headers = {}
    with LocalServer() as server:
        client = SafeHttpClient(UrlPolicy(frozenset(), allow_loopback_http=True))
        url = server.base_url + "/catalog"
        response = client.read_json_response(url, maximum_bytes=100)
        assert response.value == [] and response.etag == '"one"'
        FixtureHandler.responses["/catalog"] = (304, {"ETag": '"one"'}, b"")
        assert client.read_json_response(url, maximum_bytes=100, headers={"If-None-Match": '"one"'}).status == 304
        assert FixtureHandler.request_headers["/catalog"]["if-none-match"] == '"one"'
        with pytest.raises(ReleaseDownloadError):
            client.read_bytes(url, maximum_bytes=100)


def test_real_http_size_and_json_failures_do_not_expose_remote_body():
    FixtureHandler.responses = {"/large": (200, {}, b"x" * 101), "/invalid": (200, {}, b"private-body")}
    with LocalServer() as server:
        client = SafeHttpClient(UrlPolicy(frozenset(), allow_loopback_http=True))
        with pytest.raises(ReleaseDownloadError):
            client.read_json_response(server.base_url + "/large", maximum_bytes=100)
        with pytest.raises(Exception) as error:
            client.read_json_response(server.base_url + "/invalid", maximum_bytes=100)
        assert "private-body" not in str(error.value)


def test_catalog_uses_real_paginated_http_and_revalidated_304_without_stale_fallback():
    first = [{"id": n, "draft": True} for n in range(50)]
    path = f"/repos/{REPO}/releases?per_page=50&page="
    FixtureHandler.responses = {
        path + "1": (200, {"ETag": '"first"'}, json.dumps(first).encode()),
        path + "2": (200, {"ETag": '"second"'}, json.dumps([release()]).encode()),
    }
    FixtureHandler.request_headers = {}
    with LocalServer() as server:
        class Transport(SafeHttpClient):
            def read_json_response(self, url, **kwargs):
                parsed = urlparse(url)
                return super().read_json_response(server.base_url + parsed.path + "?" + parsed.query, **kwargs)
        provider = GitHubReleasesProvider(http_client=Transport(UrlPolicy(frozenset(), allow_loopback_http=True)))
        assert provider.list_release_v2_candidates()[0].provider_release_id == "90"
        for number, etag in [("1", '"first"'), ("2", '"second"')]:
            FixtureHandler.responses[path + number] = (304, {"ETag": etag}, b"")
        assert provider.list_release_v2_candidates()[0].provider_release_id == "90"
        assert provider.catalog_snapshot.conditional_hits == 3
        assert FixtureHandler.request_headers[path + "2"]["if-none-match"] == '"second"'
        FixtureHandler.responses[path + "2"] = (403, {}, b"private-remote-error")
        with pytest.raises(ReleaseCatalogError) as error:
            provider.list_release_v2_candidates()
        assert "private-remote-error" not in str(error.value)
        assert provider.catalog_snapshot is None


def test_304_with_a_different_validator_cannot_authorize_cached_bytes():
    client = Client({1: [release()]})
    provider = GitHubReleasesProvider(http_client=client)
    provider.list_release_v2_candidates()
    client.forced = JsonHttpResponse(None, 304, '"different"')
    with pytest.raises(ReleaseCatalogError):
        provider.list_release_v2_candidates()
    assert provider.catalog_snapshot is None


def test_short_http_body_cannot_be_mistaken_for_a_complete_empty_catalog():
    FixtureHandler.responses = {"/truncated": (200, {"Content-Length": "50"}, b"[]")}
    with LocalServer() as server:
        client = SafeHttpClient(UrlPolicy(frozenset(), allow_loopback_http=True))
        with pytest.raises(ReleaseDownloadError):
            client.read_json_response(server.base_url + "/truncated", maximum_bytes=100)


def test_incomplete_catalog_has_a_redacted_chinese_api_error():
    from enterprise import update_api
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        update_api._error(ReleaseCatalogError())
    assert error.value.detail["code"] == "RELEASE_CATALOG_INCOMPLETE"
    assert "未启动升级" in error.value.detail["message"]


def test_api_offers_page_two_target_and_prepare_bypasses_advisory_cache(monkeypatch):
    from enterprise import update_api
    from enterprise.ops.update.mvp import UpdateMvpError
    _, declaration = _document("ice-target", "2026.08.1", "2", "ice-source", "2026.07.6", "1")
    provider = GitHubReleasesProvider(http_client=Client({1: [{"id": n, "draft": True} for n in range(50)], 2: [release()]}))
    monkeypatch.setattr(update_api, "_provider", lambda: provider)
    monkeypatch.setattr(update_api, "_route_preview_cache", RoutePreviewCache())
    source = SimpleNamespace(release_id="ice-source", raw_sha256=_sha("1"), section=lambda _: {"release_version": "2026.07.6"})
    monkeypatch.setattr(update_api, "read_release_manifest_v2", lambda _: source)
    monkeypatch.setattr(update_api, "read_current_release_result_from_state_root", lambda _: SimpleNamespace(release=SimpleNamespace(release_id=source.release_id, manifest_sha256=source.raw_sha256)))
    monkeypatch.setattr(update_api, "inspect_installed_route_state", lambda **_: ReleaseState(source.release_id, "2026.07.6", source.raw_sha256, _sha("a"), 1, "stable"))
    calls = []
    def loader(*_):
        calls.append("fresh-route")
        return declaration
    monkeypatch.setattr(update_api, "read_release_routes", loader)
    first = update_api._check_update_sync()
    second = update_api._check_update_sync()
    assert first["catalog"]["record_count"] == 51 and first["catalog"]["complete"] is True
    assert first["latest"]["provider_release_id"] == "90"
    assert second["releases"][0]["route_status"] == "direct"
    assert calls == ["fresh-route"]
    monkeypatch.setattr(update_api, "UpdateJobStore", lambda _: SimpleNamespace(assert_no_unresolved_recovery=lambda: None))
    def changed(*_):
        calls.append("prepare-revalidated")
        raise UpgradeRouteError("UPGRADE_ROUTE_DIGEST_MISMATCH")
    monkeypatch.setattr(update_api, "read_release_routes", changed)
    monkeypatch.setattr(update_api, "atomic_download", lambda **_: pytest.fail("no asset staging after route mismatch"))
    with pytest.raises(UpdateMvpError, match="SYSTEM_UPDATE_ROUTE_INVALID"):
        update_api._prepare_update_sync("synthetic-actor", "90")
    assert calls[-1] == "prepare-revalidated"


def test_preview_cache_key_binds_digest_and_credential(monkeypatch):
    cache = RoutePreviewCache()
    client = Client({1: [release()]})
    provider = GitHubReleasesProvider(http_client=client)
    metadata = provider.list_release_v2_candidates()[0]
    _, routes = _document("ice-target", "2026.08.1", "2", "ice-source", "2026.07.6", "1")
    calls = []
    def loader(*_):
        calls.append(1)
        return routes
    assert cache.read(provider, metadata, loader) == routes
    assert cache.read(provider, metadata, loader) == routes
    cache.read(provider, replace(metadata, upgrade_routes_sha256="b" * 64), loader)
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-rotated")
    provider.list_release_v2_candidates()
    cache.read(provider, metadata, loader)
    assert len(calls) == 3
